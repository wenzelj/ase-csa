"""Draft run state reports the latest attempt separately from the last applied answer."""

import json
import os
import signal
from pathlib import Path

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

CSA_BIN = Path(__file__).resolve().parents[3] / "bin" / "csa"


def _state(run, phase, blocks, detail="", model="evo"):
    return {
        "CSA_RUN_STATE_FILE": str(run / "draft" / "runs.json"),
        "CSA_RUN_STATE_DIR": str(run),
        "CSA_RUN_STATE_KEY": "DNS",
        "CSA_RUN_STATE_NUMBER": "3.5",
        "CSA_RUN_STATE_TITLE": "DNS",
        "CSA_PHASE": phase,
        "CSA_BLOCKS": blocks,
        "CSA_RUN_DETAIL": detail,
        "CSA_MODEL": model,
    }


def _terminate(tmp_path, run_state, signum):
    """A csa process with the handler installed receives signum while a draft run is in flight (no model, no DOCX)."""
    import signal
    import subprocess
    import sys
    import time
    src = CSA_BIN.read_text(encoding="utf-8")
    assert "signal.signal(signal.SIGTERM, _finalize_interrupted_run)" in src, "the csa command installs the handler"
    assert "signal.signal(signal.SIGHUP, _finalize_interrupted_run)" in src
    code = (
        "import importlib.machinery, importlib.util, os, signal, sys, time"
        f"; os.environ.update({run_state!r})"
        "; loader = importlib.machinery.SourceFileLoader('csa', " + repr(str(CSA_BIN)) + ")"
        "; spec = importlib.util.spec_from_loader('csa', loader)"
        "; mod = importlib.util.module_from_spec(spec)"
        "; loader.exec_module(mod)"
        "; signal.signal(signal.SIGTERM, mod._finalize_interrupted_run)"
        "; signal.signal(signal.SIGHUP, mod._finalize_interrupted_run)"
        "; assert signal.getsignal(signal.SIGTERM) == mod._finalize_interrupted_run"
        "; time.sleep(300)"
    )
    env = dict(os.environ)
    env.update({k: str(v) for k, v in run_state.items()})
    env["PYTHONPATH"] = os.pathsep.join([str(CSA_BIN.parent), str(Path(__file__).resolve().parents[2])])
    p = subprocess.Popen([sys.executable, "-c", code], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2.5)
    assert p.poll() is None, p.stderr
    p.send_signal(signum)
    out, err = p.communicate(timeout=60)
    return p, out, err


def test_sigterm_in_generating_records_interrupted(tmp_path):
    draft_lane.record_run(tmp_path, "DNS", "3.5", "DNS", "RUNNING", "model pass answer", "GENERATING", "B1,B3",
                          model="evo")
    p, out, err = _terminate(tmp_path, _state(tmp_path, "GENERATING", "B1,B3", "model pass answer"), signal.SIGTERM)
    assert p.returncode != 0, (p.returncode, out, err)
    rec = json.loads((tmp_path / "draft" / "runs.json").read_text())["DNS"]
    assert rec["status"] == "INTERRUPTED"
    assert rec["phase"] == "GENERATING" and rec["blocks"] == "B1,B3" and rec["model"] == "evo"
    assert "SIGTERM" in rec["detail"]
    assert len(draft_lane.failed_runs(tmp_path)) == 1 and "INTERRUPTED" in draft_lane.failed_runs(tmp_path)[0]


def test_sighup_in_repairing_records_interrupted(tmp_path):
    draft_lane.record_run(tmp_path, "DNS", "3.5", "DNS", "RUNNING", "model pass repair", "REPAIRING", "B1",
                          model="evo")
    p, out, err = _terminate(tmp_path, _state(tmp_path, "REPAIRING", "B1", "model pass repair"), signal.SIGHUP)
    assert p.returncode != 0, (p.returncode, out, err)
    rec = json.loads((tmp_path / "draft" / "runs.json").read_text())["DNS"]
    assert rec["status"] == "INTERRUPTED"
    assert rec["phase"] == "REPAIRING" and rec["blocks"] == "B1" and rec["model"] == "evo"
    assert "SIGHUP" in rec["detail"]


def test_handler_keeps_terminal_state_and_is_idempotent(tmp_path):
    draft_lane.record_run(tmp_path, "DNS", "3.5", "DNS", "FAILED", "model pass answer exited 1 and wrote no output",
                          "MODEL", "B3", model="evo")
    p, out, err = _terminate(tmp_path, _state(tmp_path, "MODEL", "B3", "model pass answer exited 1"), signal.SIGTERM)
    assert p.returncode != 0, (p.returncode, out, err)
    rec = json.loads((tmp_path / "draft" / "runs.json").read_text())["DNS"]
    assert rec["status"] == "FAILED" and rec["detail"] == "model pass answer exited 1 and wrote no output"
