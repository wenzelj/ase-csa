"""The credential filter on discovery leads: block real-looking values, never fail the run, ignore field labels."""
from csa_docx import leads


def test_flags_and_placeholders_are_not_secrets():
    for text in ("Elevated Token:_x0009__x0009_Yes_x000D__x000A_", "Token: No", "password: ********",
                 "token = <redacted>", "Elevated Token: %%1842", "PasswordLastSet: 2026-01-01"):
        assert not leads._looks_secret(text), text


def test_credential_values_are_secrets():
    for text in ("password=Abc123!xyz", "pwd: hunter2", "api_key = AKIA1234567890",
                 "Token:_x0009_eyJhbGciOiJIUzI1NiJ9", "secret: s3cr3t"):
        assert leads._looks_secret(text), text


def test_add_leads_skips_a_secret_hit_and_keeps_the_rest(tmp_path):
    good = {"source_ref": "a.txt", "rel_path": "a.txt", "evidence_excerpt": "DNS server 10.0.0.1"}
    bad = {"source_ref": "b.txt", "rel_path": "b.txt", "evidence_excerpt": "password=Abc123!xyz"}
    ws = tmp_path / "workspace"
    (ws / "csa-work").mkdir(parents=True, exist_ok=True)
    ids = leads.add_leads(ws, "DR-X-B1-Q1", "B1", "What DNS server?", [bad, good])
    assert len(ids) == 1
    stored = (ws / "csa-work" / "intake" / "leads.jsonl").read_text()
    assert "Abc123" not in stored and "DNS server" in stored
