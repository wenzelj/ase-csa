from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx.change_parser import parse_change_records
from csa_docx.cli_apply_section import _scope_records
from csa_docx.ooxml import (
    DocumentEditor,
    make_paragraph,
    markdown_to_paragraph_texts,
    normalise_text,
    paragraph_text,
    qn,
    W_NS,
    _extract_labeled_values,
    _extract_pipe_row_replacements,
    _extract_range_spec,
    _extract_row_labels,
    _extract_following_bullet_count,
    _has_range_replacement,
    _anchor_variants,
    find_anchor,
)
from csa_docx.engines.docxengine_adapter import (
    DocxEngineEditor,
    _extract_delete_until_heading,
    _extract_heading_to_sentence_range,
    _has_paragraph_plus_following_line_replacement,
)
from csa_docx.validator import validate_docx


def test_extract_pipe_row_replacements():
    text = (
        "> **DNS Location |** Configured resolvers are external to the IAMPS application hosts "
        "| Host resolver configuration + design documentation\n>\n"
        "> **Local DNS Services |** No DNS Server service identified on the discovered IAMPS hosts "
        "| Host service/process evidence"
    )
    assert _extract_pipe_row_replacements(text) == [
        (
            "DNS Location",
            [
                "Configured resolvers are external to the IAMPS application hosts",
                "Host resolver configuration + design documentation",
            ],
        ),
        (
            "Local DNS Services",
            [
                "No DNS Server service identified on the discovered IAMPS hosts",
                "Host service/process evidence",
            ],
        ),
    ]
    assert _extract_pipe_row_replacements("no pipes here") == []


def test_extract_pipe_row_replacements_skips_markdown_table_header_and_separator():
    text = """| Port | Service | Evidence Interpretation |
|---|---|---|
| 135 | RPC | Microsoft RPC endpoint-mapping/service evidence |
| 445 | SMB | SMB service or connection evidence |"""

    assert _extract_pipe_row_replacements(text) == [
        ("135", ["RPC", "Microsoft RPC endpoint-mapping/service evidence"]),
        ("445", ["SMB", "SMB service or connection evidence"]),
    ]


def test_parse_basic_change_record():
    markdown = """### E-1 - Example
**Where:** Section 1, sentence beginning exactly:
`Old text`

**Do:** Replace

**Text:**

> New text

**Why:**
Because it is approved.
"""
    records = parse_change_records(markdown)
    assert len(records) == 1
    assert records[0].edit_id == "E-1"
    assert records[0].where.startswith("Section 1")
    assert records[0].action == "Replace"
    assert records[0].text == "New text"
    assert "approved" in records[0].why


def test_find_anchor_after_markdown_cleanup():
    where = """Section 4, immediately after the sentence beginning exactly:

Discovery activity was performed using host-level script execution across IAMPS servers."""
    assert find_anchor(where) == "Discovery activity was performed using host-level script execution across IAMPS servers."


def test_find_anchor_supports_heading_exactly():
    where = """Section 6.1, heading exactly:

6.1.1 Design and Functionality Expected"""
    assert find_anchor(where) == "6.1.1 Design and Functionality Expected"


def test_heading_anchor_variants_allow_generated_word_numbering():
    assert _anchor_variants("6.1.1 Design and Functionality Expected") == [
        "6.1.1 Design and Functionality Expected",
        "Design and Functionality Expected",
    ]


def test_markdown_bullets_become_separate_paragraphs():
    assert markdown_to_paragraph_texts("Intro:\n\n- one\n- two\n\nOutro.") == [
        "Intro:",
        "- one",
        "- two",
        "Outro.",
    ]


def test_markdown_to_paragraph_texts_strips_blockquote_markers():
    # Change records write multi-paragraph **Text:** content as a Markdown
    # blockquote (every line, including blank separators, prefixed with
    # ">"). Regression for a bug (found via E-146/E-153 in Section 9) where
    # the literal "> " prefix leaked into applied paragraph text because a
    # bare ">" separator line is non-empty and was not recognised as a
    # paragraph break.
    raw = (
        "> First paragraph of approved replacement text.\n"
        ">\n"
        "> Second paragraph, with a bullet list:\n"
        ">\n"
        "> - first point\n"
        "> - second point\n"
        ">\n"
        "> Final paragraph."
    )
    assert markdown_to_paragraph_texts(raw) == [
        "First paragraph of approved replacement text.",
        "Second paragraph, with a bullet list:",
        "- first point",
        "- second point",
        "Final paragraph.",
    ]


def test_markdown_to_paragraph_texts_raw_range_spec_replacement_has_no_blockquote_markers():
    # End-to-end regression: the raw replacement text captured by
    # _extract_range_spec (used for "Do: Replace ... through ...:" edits)
    # bypasses change_parser's own blockquote stripping, so
    # markdown_to_paragraph_texts must strip it itself.
    raw_block = (
        "**Where:** Section 9.3.2, sentence beginning exactly:\n\n"
        "`Under IT/OT separation, IAMPS hosts will lose connectivity to the configured time sources`\n\n"
        "**Do:** Replace the opening content through the line:\n\n"
        "`Progressive divergence of system clocks`\n\n"
        "**Text:**\n\n"
        "> If IT/OT separation removes reachability, those hosts will no longer receive updates.\n"
        ">\n"
        "> The hosts will continue to operate using their local system clocks.\n\n"
        "**Why:**  \nExplanatory rationale.\n"
    )
    spec = _extract_range_spec(raw_block)
    assert spec is not None
    _, _, replacement_text = spec
    paragraphs = markdown_to_paragraph_texts(replacement_text)
    assert paragraphs == [
        "If IT/OT separation removes reachability, those hosts will no longer receive updates.",
        "The hosts will continue to operate using their local system clocks.",
    ]
    assert not any(p.startswith(">") or " > " in p for p in paragraphs)


def test_extract_following_bullet_count_from_action():
    assert _extract_following_bullet_count("Replace this sentence and its three bullets.") == 3
    assert _extract_following_bullet_count("Replace the sentence and 2 bullets.") == 2


def test_extract_simple_table_row_labels_and_values():
    where = "row beginning `Database Integration (SQL)`"
    text = """> **Observed:** SQL-related Active Directory group evidence is present.
>
> **Assessment:** Supporting contextual evidence only."""

    assert _extract_row_labels(where, text) == ["Database Integration (SQL)"]
    assert _extract_labeled_values(text) == {
        "": {
            "observed": "SQL-related Active Directory group evidence is present.",
            "assessment": "Supporting contextual evidence only.",
        }
    }


def test_extract_table_row_label_after_markdown_cleanup():
    where = "row beginning Database Integration (SQL)"
    assert _extract_row_labels(where, "> **Assessment:** Supporting contextual evidence only.") == [
        "Database Integration (SQL)"
    ]


def test_extract_multi_row_labeled_table_values():
    where = "row beginning `Network Services Multi-protocol`"
    text = """> **Network Services - Observed:** Host discovery identifies RPC.
>
> **Network Services - Assessment:** Multiple host-level network services are evidenced.
>
> **Cross-Domain Connectivity - Observed:** Host configuration confirms use of enterprise AD.
>
> **Cross-Domain Connectivity - Assessment:** Enterprise infrastructure usage is evidenced."""

    assert _extract_row_labels(where, text) == ["Network Services", "Cross-Domain Connectivity"]
    assert _extract_labeled_values(text)["Network Services"]["observed"] == "Host discovery identifies RPC."
    assert (
        _extract_labeled_values(text)["Cross-Domain Connectivity"]["assessment"]
        == "Enterprise infrastructure usage is evidenced."
    )


def test_extract_range_replacement_spec():
    raw = """Then, in Section 5.5.1, replace the content beginning `Core infrastructure dependencies (AD, DNS, NTP) are:` through the final bullet `Security tooling (CrowdStrike, Splunk)` with:

> - Host discovery confirms domain joined hosts.
> - Endpoint services are present.

---"""

    assert _extract_range_spec(raw) == (
        "Core infrastructure dependencies (AD, DNS, NTP) are:",
        "Security tooling (CrowdStrike, Splunk)",
        "> - Host discovery confirms domain joined hosts.\n> - Endpoint services are present.",
    )


def test_extract_sentence_and_bullets_through_range_spec():
    record = parse_change_records(
        """### E-115 - Correct the Domain Membership conclusion
**Where:** Section 7.2.1, sentence beginning exactly:

`This confirms that authentication for IAMPS systems is performed via Active Directory domain services`

**Do:** Replace this sentence and all bullets through:

`Group police enforcement`

**Text:**

> This confirms that the discovered IAMPS hosts are members of the `internal.qr.com.au` Active Directory domain.
>
> Domain membership supports the use of:
>
> - domain user authentication where domain credentials are used
> - computer-account authentication with Active Directory

**Why:**
Domain membership does not prove the credential type used by every application process.
"""
    )[0]

    assert _has_range_replacement(record)
    assert _extract_range_spec(record.raw) == (
        "This confirms that authentication for IAMPS systems is performed via Active Directory domain services",
        "Group police enforcement",
        "> This confirms that the discovered IAMPS hosts are members of the `internal.qr.com.au` Active Directory domain.\n>\n> Domain membership supports the use of:\n>\n> - domain user authentication where domain credentials are used\n> - computer-account authentication with Active Directory",
    )


def test_extract_introductory_text_through_bullets_ending_range_spec():
    record = parse_change_records(
        """### E-129 - Reframe the Section 8 introduction
**Where:** Section 8, sentence beginning exactly:

`The purpose of this assessment is to determine how network connectivity, dependency paths, and communication behaviour are implemented`

**Do:** Replace the introductory text through the bullets ending with:

`Survivability under IT/OT separation conditions`

**Text:**

> This section reviews IAMPS network architecture using design documentation and host-level discovery evidence.
>
> - design-defined zones and conduits
> - host-level service and connection evidence

**Why:**
The original introduction overstates the available evidence.
"""
    )[0]

    assert _has_range_replacement(record)
    assert _extract_range_spec(record.raw) == (
        "The purpose of this assessment is to determine how network connectivity, dependency paths, and communication behaviour are implemented",
        "Survivability under IT/OT separation conditions",
        "> This section reviews IAMPS network architecture using design documentation and host-level discovery evidence.\n>\n> - design-defined zones and conduits\n> - host-level service and connection evidence",
    )


def test_docxengine_adapter_extracts_section7_remaining_operation_shapes():
    records = parse_change_records(
        """### E-124 - Replace the absolute authentication-failure list
**Where:** Section 7.3.2, heading:

`Impact Under IT/OT Separation`

**Do:** Replace all content from this heading through the sentence ending:

`where no alternative identity source or local authentication fallback was identified.`

**Text:**
Replacement.

**Why:** Because.

### E-127 - Remove the recommendations and target-state planning
**Where:** Section 7.3.5, heading exactly:

`7.3.5 Recommendations`

**Do:** Delete Sections 7.3.5 through 7.3.9 in full, including:

- `7.3.6 Overview`

Delete all content up to `7.4 Drawing`.

**Text:** None.

**Why:** Out of scope.

### E-128 - Preserve future-state Active Directory only as design context
**Where:** Section 7.1, text beginning exactly:

`The design also identifies identity services as part of OT 3.5 BASE_INFRA`

**Do:** Replace this paragraph and the following line.

**Text:**
Replacement.

**Why:** Because.
"""
    )

    assert _extract_heading_to_sentence_range(records[0]) == (
        "Impact Under IT/OT Separation",
        "where no alternative identity source or local authentication fallback was identified.",
    )
    assert _extract_delete_until_heading(records[1]) == "7.4 Drawing"
    assert _has_paragraph_plus_following_line_replacement(records[2])


def test_scope_records_respects_start_and_end_ids():
    records = parse_change_records(
        """### E-1 - One
**Where:** `One`
**Do:** Replace
**Text:** A

### E-2 - Two
**Where:** `Two`
**Do:** Replace
**Text:** B

### E-3 - Three
**Where:** `Three`
**Do:** Replace
**Text:** C
"""
    )
    assert [record.edit_id for record in _scope_records(records, "E-2", "E-3")] == ["E-2", "E-3"]


def test_delete_adds_comment_to_nearest_surviving_paragraph(tmp_path):
    document_xml = _make_test_docx_parts(tmp_path)
    editor = DocumentEditor(document_xml)
    body = editor.root.find(qn(W_NS, "body"))
    assert body is not None
    body.append(make_paragraph("Design and Functionality Expected"))
    body.append(make_paragraph("The next paragraph remains."))
    record = parse_change_records(
        """### E-96 - Remove duplicate heading
**Where:** Section 6.1, heading exactly:
`6.1.1 Design and Functionality Expected`
**Do:** Delete
**Text:** None.
**Why:** Duplicate heading.
"""
    )[0]

    result = editor.apply_change(record, "Wenzel Joubert", "WJ")

    assert result.status == "APPLIED"
    assert result.comment_id == "0"
    remaining = [normalise_text(paragraph_text(paragraph)) for paragraph in editor.paragraphs()]
    assert "Design and Functionality Expected" not in remaining
    assert any("The next paragraph remains." in text for text in remaining)


def test_replace_all_content_in_section_body_preserves_heading_and_next_section(tmp_path):
    document_xml = _make_test_docx_parts(tmp_path)
    editor = DocumentEditor(document_xml, section_heading="DNS")
    body = editor.root.find(qn(W_NS, "body"))
    assert body is not None
    body.append(_make_heading("Domain Membership (Supporting Evidence)", 3))
    body.append(make_paragraph("All IAMPS hosts are:"))
    body.append(make_paragraph("Domain joined to:"))
    body.append(make_paragraph("internal.qr.com.au"))
    body.append(_make_heading("Local DNS Capability", 3))
    body.append(make_paragraph("No evidence was identified in script outputs for:"))
    record = parse_change_records(
        """### E-99 - Qualify the domain-membership interpretation
**Where:** Section 6.2.2, sentence beginning exactly:
`All IAMPS hosts are:`
**Do:** Replace all content in Section 6.2.2.
**Text:**
All discovered IAMPS hosts in the extracted script set are domain joined to `internal.qr.com.au`.

Domain membership is supporting evidence that Windows infrastructure functions may use DNS.
**Why:** Domain membership supports DNS dependence for Active Directory service discovery.
"""
    )[0]

    result = editor.apply_change(record, "Wenzel Joubert", "WJ")

    texts = [normalise_text(paragraph_text(paragraph)) for paragraph in editor.paragraphs()]
    assert result.status == "APPLIED"
    assert result.comment_id == "0"
    assert texts == [
        "Domain Membership (Supporting Evidence)",
        "All discovered IAMPS hosts in the extracted script set are domain joined to internal.qr.com.au.",
        "Domain membership is supporting evidence that Windows infrastructure functions may use DNS.",
        "Local DNS Capability",
        "No evidence was identified in script outputs for:",
    ]


def test_replace_anchor_and_following_bullets_preserves_next_heading(tmp_path):
    document_xml = _make_test_docx_parts(tmp_path)
    editor = DocumentEditor(document_xml, section_heading="DNS")
    body = editor.root.find(qn(W_NS, "body"))
    assert body is not None
    body.append(_make_heading("Local DNS Capability", 3))
    body.append(make_paragraph("No evidence was identified in script outputs for:"))
    body.append(make_paragraph("Local DNS server processes"))
    body.append(make_paragraph("DNS forwarding services within the OT environment"))
    body.append(make_paragraph("Alternate or secondary DNS configurations"))
    body.append(_make_heading("Summary of Observed State", 3))
    body.append(make_paragraph("Aspect"))
    record = parse_change_records(
        """### E-100 - Scope the Local DNS Capability findings correctly
**Where:** Section 6.2.3, sentence exactly:
`No evidence was identified in script outputs for:`
**Do:** Replace this sentence and its three bullets.
**Text:**
On the discovered IAMPS hosts, the reviewed script outputs did not identify:

- a locally hosted DNS Server service
- an additional configured DNS resolver beyond `10.40.228.97` and `10.45.228.97`

The host-level scripts do not establish whether DNS forwarding exists elsewhere.
**Why:** Host discovery cannot establish absence elsewhere in OT.
"""
    )[0]

    result = editor.apply_change(record, "Wenzel Joubert", "WJ")

    texts = [normalise_text(paragraph_text(paragraph)) for paragraph in editor.paragraphs()]
    assert result.status == "APPLIED"
    assert result.comment_id == "0"
    assert texts == [
        "Local DNS Capability",
        "On the discovered IAMPS hosts, the reviewed script outputs did not identify:",
        "- a locally hosted DNS Server service",
        "- an additional configured DNS resolver beyond 10.40.228.97 and 10.45.228.97",
        "The host-level scripts do not establish whether DNS forwarding exists elsewhere.",
        "Summary of Observed State",
        "Aspect",
    ]


def test_replace_pipe_format_table_rows_like_e101(tmp_path):
    document_xml = _make_test_docx_parts(tmp_path)
    editor = DocumentEditor(document_xml)
    body = editor.root.find(qn(W_NS, "body"))
    assert body is not None
    table = ET.SubElement(body, qn(W_NS, "tbl"))
    table.append(_make_table_row("Aspect", "Observed State", "Evidence"))
    table.append(_make_table_row("DNS Resolvers", "10.40.228.97, 10.45.228.97", "Script outputs"))
    dns_location = _make_table_row("DNS Location", "Enterprise IT hosted", "IP range + domain")
    local_dns = _make_table_row("Local DNS Services", "Not present", "No service/process identified")
    table.append(dns_location)
    table.append(local_dns)

    record = parse_change_records(
        """### E-101 - Correct the Summary of Observed State table
**Where:** Section 6.2.3 table, row beginning exactly:
`DNS Location Enterprise IT hosted`
**Do:** Replace the `DNS Location` and `Local DNS Services` rows.
**Text:**
> **DNS Location |** Configured resolvers are external to the IAMPS application hosts; enterprise infrastructure hosting is identified in IAMPS design documentation | Host resolver configuration + design documentation
>
> **Local DNS Services |** No DNS Server service identified on the discovered IAMPS hosts | Host service/process evidence
**Why:** The original table treats inferred hosting location and absence across the environment as directly observed facts.
"""
    )[0]

    result = editor.apply_change(record, "Wenzel Joubert", "WJ")

    assert result.status == "APPLIED"
    assert result.comment_id is not None
    rows = {
        normalise_text(paragraph_text(row.findall(qn(W_NS, "tc"))[0].find(qn(W_NS, "p")))): row
        for row in table.findall(qn(W_NS, "tr"))
    }
    def row_values(row):
        return [normalise_text(paragraph_text(tc.find(qn(W_NS, "p")))) for tc in row.findall(qn(W_NS, "tc"))]

    assert row_values(dns_location) == [
        "DNS Location",
        "Configured resolvers are external to the IAMPS application hosts; enterprise infrastructure hosting is identified in IAMPS design documentation",
        "Host resolver configuration + design documentation",
    ]
    assert row_values(local_dns) == [
        "Local DNS Services",
        "No DNS Server service identified on the discovered IAMPS hosts",
        "Host service/process evidence",
    ]
    assert "DNS Location" in rows and "Local DNS Services" in rows


def test_docxengine_replaces_pipe_format_table_rows_like_e101(tmp_path):
    docx = _make_test_docx(tmp_path)
    editor = DocxEngineEditor(docx)
    record = parse_change_records(
        """### E-101 - Correct the Summary of Observed State table
**Where:** Section 6.2.3 table, row beginning exactly:
`DNS Location Enterprise IT hosted`
**Do:** Replace the `DNS Location` and `Local DNS Services` rows.
**Text:**
> **DNS Location |** Configured resolvers are external to the IAMPS application hosts; enterprise infrastructure hosting is identified in IAMPS design documentation | Host resolver configuration + design documentation
>
> **Local DNS Services |** No DNS Server service identified on the discovered IAMPS hosts | Host service/process evidence
**Why:** The original table treats inferred hosting location and absence across the environment as directly observed facts.
"""
    )[0]

    result = editor.apply_change(record, "Wenzel Joubert", "WJ")
    editor.save()

    assert result.status == "APPLIED"
    assert result.comment_id is not None
    rows = _read_docx_table_rows(docx)
    assert rows["DNS Location"] == [
        "DNS Location",
        "Configured resolvers are external to the IAMPS application hosts; enterprise infrastructure hosting is identified in IAMPS design documentation",
        "Host resolver configuration + design documentation",
    ]
    assert rows["Local DNS Services"] == [
        "Local DNS Services",
        "No DNS Server service identified on the discovered IAMPS hosts",
        "Host service/process evidence",
    ]
    validation = validate_docx(docx)
    assert validation["comment_id_consistency"] == "Pass"
    assert validation["table_row_comment_safety"] == "Pass"


def test_docxengine_replaces_labelled_observed_and_assessment_table_cells(tmp_path):
    docx = _make_test_docx(tmp_path)
    editor = DocxEngineEditor(docx)
    record = parse_change_records(
        """### E-102 - Correct the service table
**Where:** Section 6.3 table, row beginning `Database Integration (SQL)`
**Do:** Replace the Observed and Assessment values.
**Text:**
> **Observed:** SQL Server use is evidenced by configuration and connection artefacts.
> **Assessment:** Supporting contextual evidence only.
**Why:** The prior row overstated the available evidence.
"""
    )[0]

    result = editor.apply_change(record, "Wenzel Joubert", "WJ")
    editor.save()

    assert result.status == "APPLIED"
    assert result.comment_id is not None
    rows = _read_docx_table_rows(docx)
    assert rows["Database Integration (SQL)"] == [
        "Database Integration (SQL)",
        "Current observed text",
        "SQL Server use is evidenced by configuration and connection artefacts.",
        "Supporting contextual evidence only.",
    ]
    validation = validate_docx(docx)
    assert validation["comment_id_consistency"] == "Pass"
    assert validation["table_row_comment_safety"] == "Pass"


def _make_test_docx_parts(tmp_path):
    word_dir = tmp_path / "word"
    rels_dir = word_dir / "_rels"
    rels_dir.mkdir(parents=True)
    (tmp_path / "[Content_Types].xml").write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        encoding="utf-8",
    )
    (rels_dir / "document.xml.rels").write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>""",
        encoding="utf-8",
    )
    document_xml = word_dir / "document.xml"
    document_xml.write_text(
        """<?xml version='1.0' encoding='utf-8'?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body /></w:document>""",
        encoding="utf-8",
    )
    return document_xml


def _make_test_docx(tmp_path) -> Path:
    document_xml = _make_test_docx_parts(tmp_path / "pkg")
    editor = DocumentEditor(document_xml)
    body = editor.root.find(qn(W_NS, "body"))
    assert body is not None
    table = ET.SubElement(body, qn(W_NS, "tbl"))
    table.append(_make_table_row("Aspect", "Observed State", "Evidence"))
    table.append(_make_table_row("DNS Resolvers", "10.40.228.97, 10.45.228.97", "Script outputs"))
    table.append(_make_table_row("DNS Location", "Enterprise IT hosted", "IP range + domain"))
    table.append(_make_table_row("Local DNS Services", "Not present", "No service/process identified"))
    second_table = ET.SubElement(body, qn(W_NS, "tbl"))
    second_table.append(_make_table_row("Capability", "Current State", "Observed State", "Assessment"))
    second_table.append(_make_table_row("Database Integration (SQL)", "Current observed text", "Old observed", "Old assessment"))
    editor.save()

    docx = tmp_path / "fixture.docx"
    with zipfile.ZipFile(docx, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted((tmp_path / "pkg").rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(tmp_path / "pkg").as_posix())
    return docx


def _read_docx_table_rows(docx: Path) -> dict[str, list[str]]:
    with zipfile.ZipFile(docx) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    rows: dict[str, list[str]] = {}
    for row in root.iter(qn(W_NS, "tr")):
        values = [
            normalise_text(" ".join(paragraph_text(p) for p in cell.iter(qn(W_NS, "p"))))
            for cell in row.findall(qn(W_NS, "tc"))
        ]
        if values:
            rows[values[0]] = values
    return rows


def _make_table_row(*cells: str) -> ET.Element:
    tr = ET.Element(qn(W_NS, "tr"))
    for cell in cells:
        tc = ET.SubElement(tr, qn(W_NS, "tc"))
        tc.append(make_paragraph(cell))
    return tr


def _make_heading(text: str, level: int) -> ET.Element:
    paragraph = make_paragraph(text)
    ppr = ET.Element(qn(W_NS, "pPr"))
    ET.SubElement(ppr, qn(W_NS, "pStyle"), {qn(W_NS, "val"): f"Heading{level}"})
    paragraph.insert(0, ppr)
    return paragraph
