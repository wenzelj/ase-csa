"""csa intake: the evidence agent's intake mode turns new documents from the latest index build into matrix rows."""
import subprocess
import sys
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[3]
CSA = AGENTS / "bin" / "csa"


def test_intake_prompt_names_the_record_and_rules():
    r = subprocess.run([sys.executable, str(CSA), "-p", "test", "intake", "--print"], capture_output=True, text=True)
    prompt = r.stdout + r.stderr
    assert r.returncode == 0, prompt[-800:]
    assert "MODE=INTAKE" in prompt and "INTAKE=latest" in prompt and "intake/latest.json" in prompt
    assert "csa-evidence-investigator-agent.md" in prompt
    rules = (AGENTS / "csa-evidence-investigator-agent.md").read_text(encoding="utf-8")
    for needle in ("## Intake mode (MODE=INTAKE)", "evidence_matrix.py", "--dry-run", "graph_store.py",
                   "append-node", "Never infer", "unreadable", ".evidence.md", "CONFLICTING"):
        assert needle in rules, needle
