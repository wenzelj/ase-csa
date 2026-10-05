from csa_docx import session_stats as ss

LOG = """user
prompt text
codex
Reading the rules.
exec
/bin/zsh -lc "cd /w && sed -n '1,80p' .agents/csa-core-rules.md" succeeded in 5ms:
line one
line two
exec
/bin/zsh -lc "cd /w && cat .agents/csa-core-rules.md .agents/other.md" succeeded in 5ms:
aaaa
bbbb
exec
/bin/zsh -lc "cd /w && ls" succeeded in 5ms:
file
tokens used
12,345
"""


def test_counts_and_bytes(tmp_path):
    log = tmp_path / "t.log"
    log.write_text(LOG, encoding="utf-8")
    st = ss.stats(log)
    assert st["commands"] == 3
    assert st["tokens_used"] == 12345
    assert st["output_bytes"] == len("line one\nline two\n") + len("aaaa\nbbbb\n") + len("file\n")


def test_file_read_twice_is_top(tmp_path):
    log = tmp_path / "t.log"
    log.write_text(LOG, encoding="utf-8")
    top = ss.stats(log)["top_files"]
    first = next(t for t in top if t["file"] == ".agents/csa-core-rules.md")
    assert first["reads"] == 2
    assert top[0]["file"] == ".agents/csa-core-rules.md"
    assert all(t["file"] != "80p" and t["file"] != "1,80p" for t in top)


def test_no_tokens_line(tmp_path):
    log = tmp_path / "t.log"
    log.write_text("exec\n/bin/zsh -lc \"ls\" succeeded in 1ms:\nx\n", encoding="utf-8")
    assert ss.stats(log)["tokens_used"] is None


def test_timing_fields():
    st = {"output_bytes": 2048, "commands": 4, "tokens_used": None}
    assert ss.timing_fields("answer", st) == {"answer_read_kb": 2.0, "answer_commands": 4, "answer_tokens": None}
