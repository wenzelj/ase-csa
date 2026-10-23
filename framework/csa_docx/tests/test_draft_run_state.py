"""Draft run state reports the latest attempt separately from the last applied answer."""

import json

from csa_docx import draft_lane


def test_failed_attempt_keeps_last_ok_and_reports_diagnostics(tmp_path):
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "DNS.answer.md").write_text("## B1 DNS\nUnknown: owner to confirm.\n", encoding="utf-8")
    draft_lane.record_run(tmp_path, "DNS", "3.5", "DNS", "OK", "8 parts written")
    applied = json.loads((tmp_path / "draft" / "runs.json").read_text())["DNS"]
    assert applied["last_ok"] and applied["sheet_sha256"]

    draft_lane.record_run(tmp_path, "DNS", "3.5", "DNS", "FAILED", "NO_TOTALS, UNKNOWN_BUNDLED",
                          "VALIDATING", "B1,B3", 9000, "evo", "deadbeef")
    current = json.loads((tmp_path / "draft" / "runs.json").read_text())["DNS"]
    assert current["status"] == "FAILED" and current["last_ok"] == applied["last_ok"]
    assert current["blocks"] == "B1,B3" and current["elapsed_s"] == 9000.0
    assert current["sheet_sha256"] == applied["sheet_sha256"] and current["candidate_sha256"] == "deadbeef"
    report = draft_lane.failed_runs(tmp_path)
    assert len(report) == 1 and "B1,B3" in report[0] and "150.0 min" in report[0]


def test_running_and_ready_are_not_reported_as_failed(tmp_path):
    draft_lane.record_run(tmp_path, "DNS", "3.5", "DNS", "RUNNING", "repairing", "REPAIRING", "B1",
                          model="codex")
    assert draft_lane.failed_runs(tmp_path) == []
    draft_lane.record_run(tmp_path, "DNS", "3.5", "DNS", "READY", "--no-apply", "READY")
    assert draft_lane.failed_runs(tmp_path) == []
    ready = json.loads((tmp_path / "draft" / "runs.json").read_text())["DNS"]
    assert ready["model"] == "codex" and ready["blocks"] == "B1"
