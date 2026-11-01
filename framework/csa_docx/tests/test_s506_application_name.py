"""S506: the card names the system (optional project 'application') and no longer uses 'captured hosts' in its heading."""
from csa_docx import estate, section_card

SENTENCE = ("Refer to the hosts as the Demo/App hosts, or by role group or host name. Do not write 'the captured hosts'. "
            "The role table footnote already shows which hosts were not captured and which are assumed to match their role.")
OLD_HEADING = "Host register (captured hosts, grouped by role)"


def project(tmp_path, monkeypatch, application=True):
    ws = tmp_path / "proj"
    hosts = ws / "csa-work" / "hosts"
    hosts.mkdir(parents=True)
    (hosts / "hosts.csv").write_text("host,role,site,capture,in_scope\nSQL1,SQL Server,Site A,yes,yes\n", encoding="utf-8")
    reg = tmp_path / "PROJECTS.yaml"
    reg.write_text("projects:\n  - key: demo\n    label: Demo\n    work_dir: \"%s\"\n%s"
                   % (ws / "csa-work", '    application: "Demo/App"\n' if application else ""), encoding="utf-8")
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(reg))
    return ws


def card_text(ws):
    return "\n".join(section_card._register_lines(section_card.host_register(ws)))


def test_application_in_card(tmp_path, monkeypatch):
    ws = project(tmp_path, monkeypatch)
    assert estate.application_name(ws / "csa-work") == "Demo/App"
    text = card_text(ws)
    assert SENTENCE in text and "Demo/App" in text
    assert "## Host register (hosts grouped by role)" in text
    assert OLD_HEADING not in text


def test_no_application_leaves_sentence_out(tmp_path, monkeypatch):
    ws = project(tmp_path, monkeypatch, application=False)
    assert estate.application_name(ws / "csa-work") == ""
    text = card_text(ws)
    assert "Refer to the hosts as the" not in text and "Demo/App" not in text
    assert OLD_HEADING not in text
