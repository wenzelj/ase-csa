from csa_docx import topic_tables as T

P = '<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'


def _doc(*paras):
    return "<w:body>" + "".join(P.format(s=s, t=t) for s, t in paras) + "</w:body>"


def test_flat_subsection_is_located_under_its_own_heading():
    xml = _doc(("Heading1", "Migration Discovery"), ("Heading2", "File Transfer and Local Storage"),
               ("ListBullet", "a finding"), ("Heading1", "Next"))
    ins, end, lvl = T._locate(xml, "File Transfer and Local Storage")
    assert xml[:ins].endswith("File Transfer and Local Storage</w:t></w:r></w:p>")
    assert "a finding" in xml[ins:end] and "Next" not in xml[ins:end]


def test_domain_section_without_discovery_information_is_still_refused():
    xml = _doc(("Heading2", "DNS"), ("Heading3", "Drawbridge Impact"), ("Normal", "x"))
    assert T._locate(xml, "DNS") is None
