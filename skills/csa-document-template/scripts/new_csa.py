#!/usr/bin/env python3
"""Create a new Current State Assessment .docx from the CSA Word template (.dotx).

Standard library only (Python 3.8+). Does not need Word.

What it does
  * copies the template package into a new .docx (content type switched from template to document)
  * sets the CSA_* custom document properties and refreshes the cached text of every
    DOCPROPERTY field (cover, subtitle, page header, Section 1.1) so the document is correct
    before Word ever recalculates fields
  * strips the author-guidance Word comments (unless --keep-comments)
  * asks Word to refresh fields/TOC on first open (unless --no-update-fields)
  * refuses to overwrite an existing file (unless --force)

It never edits any other document. Output is one JSON object on stdout; exit code 0 = created,
2 = refused/failed.

Example
  python3 new_csa.py --system-name "Traction Power SCADA" \
      --out "01 Current State AS Built/01 Final Version/Current State Assessment - Traction Power SCADA.docx"
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

TEMPLATE_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
DOCUMENT_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"

# property name -> (CLI flag, default). None default = must be supplied / computed.
PROPERTIES = [
    ("CSA_SystemName", "system_name", None),
    ("CSA_Date", "date", None),
    ("CSA_Version", "doc_version", None),
    ("CSA_Status", "status", None),
    ("CSA_PreparedFor", "prepared_for", None),
    ("CSA_PreparedBy", "prepared_by", None),
    ("CSA_Project", "project", None),
    ("CSA_ReferenceStandard", "reference_standard", None),
]


def fail(message: str, **extra) -> "None":
    print(json.dumps({"status": "ERROR", "message": message, **extra}, indent=2))
    sys.exit(2)


def find_template(explicit: str | None, workspace: Path) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_absolute():
            p = workspace / p
        if not p.is_file():
            fail(f"template not found: {p}")
        return p
    folder = workspace / "CSA Template"
    candidates = sorted(glob.glob(str(folder / "CSA_Template_v*.dotx")), key=_version_key)
    if not candidates:
        fail(f"no CSA_Template_v*.dotx found in {folder}")
    return Path(candidates[-1])  # highest version


def _version_key(path: str):
    m = re.search(r"_v(\d+(?:\.\d+)*)\.dotx$", path)
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def read_template_defaults(z: zipfile.ZipFile) -> dict[str, str]:
    xml = z.read("docProps/custom.xml").decode("utf-8")
    out = {}
    for m in re.finditer(r'<property [^>]*name="([^"]+)"[^>]*><vt:lpwstr>(.*?)</vt:lpwstr>', xml, re.S):
        out[m.group(1)] = (m.group(2).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    return out


def set_custom_property(xml: str, name: str, value: str) -> tuple[str, bool]:
    pat = re.compile(r'(<property [^>]*name="%s"[^>]*><vt:lpwstr>)(.*?)(</vt:lpwstr>)' % re.escape(name), re.S)
    new, n = pat.subn(lambda m: m.group(1) + escape(value) + m.group(3), xml)
    return new, n > 0


def set_field_cache(xml: str, name: str, value: str) -> tuple[str, int]:
    """Replace the cached result text of every DOCPROPERTY "<name>" complex field."""
    rpr = r"(?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?"
    pat = re.compile(
        r'(DOCPROPERTY "%s"[^<]*</w:instrText></w:r><w:r>%s<w:fldChar w:fldCharType="separate"/></w:r><w:r>%s<w:t(?: [^>]*)?>)(.*?)(</w:t>)'
        % (re.escape(name), rpr, rpr),
        re.S,
    )
    return pat.subn(lambda m: m.group(1) + escape(value) + m.group(3), xml)


def strip_comments(doc_xml: str) -> str:
    doc_xml = re.sub(r'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="\d+"/></w:r>', "", doc_xml)
    doc_xml = re.sub(r'<w:commentRange(?:Start|End) w:id="\d+"/>', "", doc_xml)
    return doc_xml


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default=".", help="project root (default: current directory)")
    ap.add_argument("--template", help="template path (default: highest version in '<workspace>/CSA Template/')")
    ap.add_argument("--out", required=True, help="output .docx path (relative paths are under --workspace)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing output file")
    ap.add_argument("--system-name", required=True)
    ap.add_argument("--date", help="dd/mm/yyyy (default: today)")
    ap.add_argument("--doc-version", help="default: template value")
    ap.add_argument("--status", help="default: template value")
    ap.add_argument("--prepared-for", help="default: template value")
    ap.add_argument("--prepared-by", help="default: template value")
    ap.add_argument("--project", help="default: template value")
    ap.add_argument("--reference-standard", help="default: template value")
    ap.add_argument("--author", help="core.xml creator / last-modified-by (default: template value)")
    ap.add_argument("--keep-comments", action="store_true", help="keep the template's author-guidance comments")
    ap.add_argument("--no-update-fields", action="store_true", help="do not ask Word to refresh fields and TOC on open")
    args = ap.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    template = find_template(args.template, workspace)
    out = Path(args.out).expanduser()
    if not out.is_absolute():
        out = workspace / out
    if out.suffix.lower() != ".docx":
        fail("--out must end in .docx", out=str(out))
    if out.exists() and not args.force:
        fail("output already exists; refusing to overwrite (use --force only if the user asked for it)", out=str(out))
    if not args.system_name.strip():
        fail("--system-name must not be empty")

    with zipfile.ZipFile(template) as zin:
        names = zin.namelist()
        parts = {n: zin.read(n) for n in names}
        infos = {n: zin.getinfo(n) for n in names}
    defaults = read_template_defaults(zipfile.ZipFile(template))

    values: dict[str, str] = {}
    for prop, flag, _ in PROPERTIES:
        v = getattr(args, flag)
        if flag == "date" and not v:
            v = datetime.date.today().strftime("%d/%m/%Y")
        if flag == "system_name":
            v = v.strip()
        values[prop] = v if v else defaults.get(prop, "")
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", values["CSA_Date"]):
        fail("--date must be dd/mm/yyyy", got=values["CSA_Date"])

    # --- content types
    ct = parts["[Content_Types].xml"].decode("utf-8")
    if TEMPLATE_CT not in ct:
        fail("input is not a Word template package (template.main content type not found)")
    ct = ct.replace(TEMPLATE_CT, DOCUMENT_CT)

    # --- custom properties + cached field text
    custom = parts["docProps/custom.xml"].decode("utf-8")
    field_hits: dict[str, int] = {}
    field_parts = [n for n in names if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", n)]
    field_xml = {n: parts[n].decode("utf-8") for n in field_parts}
    for prop, value in values.items():
        custom, ok = set_custom_property(custom, prop, value)
        if not ok:
            fail(f"template has no custom property {prop}")
        total = 0
        for n in field_parts:
            field_xml[n], k = set_field_cache(field_xml[n], prop, value)
            total += k
        field_hits[prop] = total
    parts["docProps/custom.xml"] = custom.encode("utf-8")

    # --- comments
    comments_removed = 0
    if not args.keep_comments:
        comments_removed = len(re.findall(r"<w:commentReference ", field_xml["word/document.xml"]))
        field_xml["word/document.xml"] = strip_comments(field_xml["word/document.xml"])
        drop = [n for n in names if re.fullmatch(r"word/comments\w*\.xml", n)]
        for n in drop:
            del parts[n]
        rels = parts["word/_rels/document.xml.rels"].decode("utf-8")
        rels = re.sub(r'<Relationship [^>]*Target="comments\w*\.xml"[^>]*/>', "", rels)
        parts["word/_rels/document.xml.rels"] = rels.encode("utf-8")
        ct = re.sub(r'<Override PartName="/word/comments\w*\.xml"[^>]*/>', "", ct)
    for n in field_parts:
        parts[n] = field_xml[n].encode("utf-8")
    parts["[Content_Types].xml"] = ct.encode("utf-8")

    # --- settings: ask Word to refresh fields on open
    if not args.no_update_fields:
        st = parts["word/settings.xml"].decode("utf-8")
        if "<w:updateFields" not in st:
            st = st.replace("<w:footnotePr>", '<w:updateFields w:val="true"/><w:footnotePr>', 1)
        parts["word/settings.xml"] = st.encode("utf-8")

    # --- core properties
    core = parts["docProps/core.xml"].decode("utf-8")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    title = escape(f"Current State Assessment - {values['CSA_SystemName']}")
    core = re.sub(r"<dc:title>.*?</dc:title>", f"<dc:title>{title}</dc:title>", core, flags=re.S)
    core = re.sub(r"(<dcterms:created[^>]*>).*?(</dcterms:created>)", lambda m: m.group(1) + now + m.group(2), core, flags=re.S)
    core = re.sub(r"(<dcterms:modified[^>]*>).*?(</dcterms:modified>)", lambda m: m.group(1) + now + m.group(2), core, flags=re.S)
    core = re.sub(r"<dc:subject>.*?</dc:subject>", "<dc:subject></dc:subject>", core, flags=re.S)
    if args.author:
        core = re.sub(r"<dc:creator>.*?</dc:creator>", f"<dc:creator>{escape(args.author)}</dc:creator>", core, flags=re.S)
    parts["docProps/core.xml"] = core.encode("utf-8")

    # --- write (content types first, as Word expects)
    out.parent.mkdir(parents=True, exist_ok=True)
    order = ["[Content_Types].xml"] + [n for n in names if n in parts and n != "[Content_Types].xml"]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in order:
            zout.writestr(n, parts[n])

    missing_fields = [p for p, k in field_hits.items() if k == 0]
    print(json.dumps({
        "status": "CREATED",
        "docx": str(out),
        "template": str(template),
        "properties": values,
        "fields_refreshed": field_hits,
        "properties_without_fields": missing_fields,
        "comments_removed": comments_removed,
        "update_fields_on_open": not args.no_update_fields,
        "next": "Run scripts/check_csa.py on the new file, then prepareDocument() before any edit.",
    }, indent=2))


if __name__ == "__main__":
    main()
