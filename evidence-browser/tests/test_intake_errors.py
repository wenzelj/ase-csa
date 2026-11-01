from backend.intake_errors import classify_log

TB = """Traceback (most recent call last):
  File "/opt/x/csa_docx/gap_lookup.py", line 12, in <module>
    @dataclass(slots=True)
TypeError: dataclass() got an unexpected keyword argument 'slots'
"""


def test_identical_tracebacks_merge():
    text = "start\n" + TB + "progress\n" + TB.replace("line 12", "line 99") + TB
    groups = classify_log(text)
    assert len(groups) == 1
    g = groups[0]
    assert g["kind"] == "traceback" and g["count"] == 3
    assert g["first_line"] == 2 and g["last_line"] == 11
    assert g["signature"].startswith("TypeError: dataclass()")
    assert len(g["sample"]) <= 300


def test_argparse_invalid_choice_merges():
    text = (
        "usage: gap_lookup [-h]\n"
        "gap_lookup: error: argument action: invalid choice: 'E-12' (choose from x)\n"
        "gap_lookup: error: argument action: invalid choice: 'E-345' (choose from x)\n"
    )
    groups = classify_log(text)
    assert len(groups) == 1 and groups[0]["kind"] == "cli_error" and groups[0]["count"] == 2


def test_cli_error_program_with_spaces():
    line = "python3.14 -m csa_docx.gap_lookup: error: argument action: invalid choice: '--related-evidence E-1'\n"
    groups = classify_log(line)
    assert len(groups) == 1 and groups[0]["kind"] == "cli_error"


def test_echoed_source_not_counted():
    assert classify_log('    raise ValueError("saved search scope is required")\n  except ValueError:\n') == []


def test_clean_log_is_empty():
    assert classify_log("step 1 of 3\ndone\n") == []
    assert classify_log("") == []


def test_no_terminal_line_not_counted():
    assert classify_log("csa: no terminal here, so the agent runs headless (no interactive UI)\n") == []


def test_indented_traceback_counted():
    text = "   Traceback (most recent call last):\n     File \"a.py\", line 1\n   KeyError: 'x'\nnext\n"
    groups = classify_log(text)
    assert len(groups) == 1 and groups[0]["kind"] == "traceback" and groups[0]["first_line"] == 1


def test_truncated_traceback():
    assert classify_log("Traceback (most recent call last):\n  File \"a.py\", line 1\n") == []
    assert classify_log("Traceback (most recent call last):\n  File \"a.py\", line 1\nTypeErr") == []
    assert len(classify_log("Traceback (most recent call last):\n  File \"a.py\", line 1\nTypeError: x\n")) == 1


def test_csa_error_and_skipped():
    text = "csa: could not open /tmp/a/b.db\nERROR: all fine\n3 hit(s) skipped\n2 hit(s) withheld\n"
    groups = classify_log(text)
    kinds = {g["kind"] for g in groups}
    assert kinds == {"csa_error", "skipped"}
    assert [g for g in groups if g["kind"] == "csa_error"][0]["signature"] == "csa: could not open b.db"
    assert len([g for g in groups if g["kind"] == "skipped"]) == 2


def test_credential_sample_withheld():
    groups = classify_log("csa: failed to log in with password=Abc123!xyz\n")
    assert groups[0]["sample"] == "[withheld: looked like a credential]"


def test_order_and_cap():
    text = "".join("csa: failed thing%s%s\n" % (chr(97 + i % 26), chr(97 + i // 26)) for i in range(40))
    assert len(classify_log(text)) == 25
    text = "csa: failed a\ncsa: failed b\ncsa: failed b\n"
    assert classify_log(text)[0]["signature"] == "csa: failed b"
