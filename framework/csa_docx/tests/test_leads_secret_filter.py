"""The credential-text heuristic (still used to redact log samples); discovery leads are no longer filtered by it."""
from csa_docx import leads


def test_flags_and_placeholders_are_not_secrets():
    for text in ("Elevated Token:_x0009__x0009_Yes_x000D__x000A_", "Token: No", "password: ********",
                 "token = <redacted>", "Elevated Token: %%1842", "PasswordLastSet: 2026-01-01"):
        assert not leads._looks_secret(text), text


def test_credential_values_are_secrets():
    for text in ("password=Abc123!xyz", "pwd: hunter2", "api_key = AKIA1234567890",
                 "Token:_x0009_eyJhbGciOiJIUzI1NiJ9", "secret: s3cr3t"):
        assert leads._looks_secret(text), text


def test_add_leads_keeps_every_hit_including_secret_looking_text(tmp_path):
    hits = [{"source_ref": "a.txt", "rel_path": "a.txt", "evidence_excerpt": "DNS server 10.0.0.1"},
            {"source_ref": "b.txt", "rel_path": "b.txt", "evidence_excerpt": "accesskey=P Print"}]
    ws = tmp_path / "workspace"
    (ws / "csa-work").mkdir(parents=True, exist_ok=True)
    assert len(leads.add_leads(ws, "DR-X-B1-Q1", "B1", "What DNS server?", hits)) == 2
