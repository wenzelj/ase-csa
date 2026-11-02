import json

from backend import intake_errors
from backend.intake_errors import classify_log, intake_runs

FW = str(intake_errors._AGENTS_DIR / "framework" / "csa_docx" / "gap_lookup.py")
TB = f"""Traceback (most recent call last):
  File "{FW}", line 12, in <module>
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


def test_cli_usage_errors_not_reported():
    text = (
        "gap_lookup: error: argument action: invalid choice: 'E-12' (choose from x)\n"
        "python3.14 -m csa_docx.gap_lookup: error: unrecognized arguments: --related-evidence E-1\n"
    )
    assert classify_log(text) == []


def test_echoed_source_not_counted():
    assert classify_log('    raise ValueError("saved search scope is required")\n  except ValueError:\n') == []


def test_clean_log_is_empty():
    assert classify_log("step 1 of 3\ndone\n") == []
    assert classify_log("") == []


def test_no_terminal_line_not_counted():
    assert classify_log("csa: no terminal here, so the agent runs headless (no interactive UI)\n") == []


def test_indented_traceback_counted():
    text = "   Traceback (most recent call last):\n     File \"%s\", line 1\n   KeyError: 'x'\nnext\n" % FW
    groups = classify_log(text)
    assert len(groups) == 1 and groups[0]["kind"] == "traceback" and groups[0]["first_line"] == 1


def test_truncated_traceback():
    head = "Traceback (most recent call last):\n  File \"%s\", line 1\n" % FW
    assert classify_log(head) == []
    assert classify_log(head + "TypeErr") == []
    assert len(classify_log(head + "TypeError: x\n")) == 1


def test_agent_script_traceback_not_reported():
    text = ("Traceback (most recent call last):\n  File \"<string>\", line 7, in <module>\n"
            "  File \"/opt/homebrew/lib/python3.14/re/__init__.py\", line 278, in findall\n"
            "re.PatternError: unterminated character set at position 5\n")
    assert classify_log(text) == []


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


def _job(root, job_id, operation, state, created, exit_code=0, stdout="", stderr="", message=None):
    folder = root / "ui-jobs" / job_id
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(json.dumps({
        "id": job_id, "project_key": "p", "operation": operation, "state": state, "created_at": created,
        "started_at": created, "finished_at": None if state == "running" else created,
        "exit_code": exit_code, "message": message}))
    (folder / "stdout.log").write_text(stdout)
    (folder / "stderr.log").write_text(stderr)


def _project(tmp_path):
    return {"key": "p", "work_dir": str(tmp_path)}


def test_intake_runs_states_and_filter(tmp_path):
    _job(tmp_path, "a", "ingest", "succeeded", "2026-01-01T00:00:01+00:00", stdout="done\n")
    _job(tmp_path, "b", "intake", "succeeded", "2026-01-01T00:00:02+00:00", stderr=TB)
    _job(tmp_path, "c", "gap_check", "cancelled", "2026-01-01T00:00:03+00:00", exit_code=-15)
    _job(tmp_path, "d", "resolve_gaps", "running", "2026-01-01T00:00:04+00:00", exit_code=None, stdout="x\n")
    _job(tmp_path, "e", "answer", "failed", "2026-01-01T00:00:05+00:00")
    runs = intake_runs(_project(tmp_path))
    assert [r["id"] for r in runs] == ["d", "c", "b", "a"]
    by = {r["id"]: r for r in runs}
    assert by["a"]["has_problems"] is False and by["a"]["step"] == "ingest"
    assert by["b"]["has_problems"] is True and by["b"]["problems"][0]["stream"] == "stderr"
    assert by["b"]["reason"].startswith("TypeError")
    assert by["c"]["state"] == "cancelled" and by["c"]["has_problems"] is False
    assert by["d"]["state"] == "running" and by["d"]["step"] == "settle"
    assert len(intake_runs(_project(tmp_path), limit=2)) == 2


def test_intake_runs_cached(tmp_path, monkeypatch):
    _job(tmp_path, "a", "ingest", "succeeded", "2026-01-01T00:00:01+00:00", stdout="done\n")
    calls = []
    real = intake_errors._read_log
    monkeypatch.setattr(intake_errors, "_read_log", lambda *a, **k: calls.append(a) or real(*a, **k))
    intake_runs(_project(tmp_path))
    first = len(calls)
    assert first == 2
    intake_runs(_project(tmp_path))
    assert len(calls) == first


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_warnings_empty_without_intake_folder(tmp_path):
    assert intake_errors.intake_warnings(tmp_path) == []


def test_warnings_from_gap_check(tmp_path):
    qs = [{"verdict": "INCOMPLETE", "coverage": {"incomplete_reasons": ["a", "b"]}},
          {"verdict": "INCOMPLETE", "coverage": {"incomplete_reasons": ["a"]}},
          {"verdict": "ANSWERED"}]
    _write(tmp_path / "intake" / "gap-check-latest.json",
           {"schema_version": 3, "input_warnings": ["bad file"], "questions": qs})
    codes = {w["code"]: w for w in intake_errors.intake_warnings(tmp_path)}
    assert codes["input_warning"]["message"] == "bad file" and codes["input_warning"]["step"] == "gaps"
    assert codes["incomplete_questions"]["count"] == 2 and "a (2)" in codes["incomplete_questions"]["message"]
    assert codes["old_schema"]["severity"] == "warning"


def test_warnings_from_sync_and_unreadable(tmp_path):
    (tmp_path / "graph-audit.jsonl").write_text(
        json.dumps({"action": "sync", "ts": "t", "report": {"status": "ERROR"}}) + "\n", encoding="utf-8")
    (tmp_path / "evidence-matrix.csv").write_text("x\n", encoding="utf-8")
    _write(tmp_path / "intake" / "latest.json", {"unreadable": [{"rel_path": "a"}, {"rel_path": "b"}]})
    got = {w["code"]: w for w in intake_errors.intake_warnings(tmp_path)}
    assert got["sync_failed"]["severity"] == "error" and got["sync_failed"]["step"] == "ingest"
    assert got["sync_behind"]["severity"] == "warning"
    assert got["unreadable_files"]["count"] == 2 and got["unreadable_files"]["step"] == "documents"


def test_warnings_ignore_unreadable_records(tmp_path):
    (tmp_path / "intake").mkdir()
    (tmp_path / "intake" / "gap-check-latest.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "intake" / "latest.json").write_text("[]", encoding="utf-8")
    assert intake_errors.intake_warnings(tmp_path) == []


def test_failure_cleared_by_a_later_clean_run_of_the_same_step(tmp_path):
    _job(tmp_path, "old", "gap_check", "failed", "2026-01-01T00:00:01+00:00", exit_code=1, stderr=TB)
    _job(tmp_path, "new", "gap_check", "succeeded", "2026-01-01T00:00:02+00:00")
    _job(tmp_path, "other", "intake", "failed", "2026-01-01T00:00:03+00:00", exit_code=1, stderr=TB)
    by = {r["id"]: r for r in intake_runs(_project(tmp_path))}
    assert by["old"]["has_problems"] is False and by["old"]["problems"] == [] and by["old"]["superseded"] is True
    assert by["other"]["has_problems"] is True
