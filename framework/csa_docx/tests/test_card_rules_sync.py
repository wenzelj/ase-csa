"""csa-card-rules.md copies sections of csa-core-rules.md word for word; this fails when they drift."""
import re
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[3]
SHARED = ("Document text", "Never infer", "Evidence IDs never in document text", "Stopping")


def section(text: str, name: str) -> str:
    m = re.search(r"^## " + re.escape(name) + r"\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert m, f"no section {name!r}"
    return m.group(1).strip()


def test_shared_sections_match_the_core_rules():
    core = (AGENTS / "csa-core-rules.md").read_text(encoding="utf-8")
    card = (AGENTS / "csa-card-rules.md").read_text(encoding="utf-8")
    for name in SHARED:
        assert section(card, name) == section(core, name), f"{name} differs: copy it from csa-core-rules.md"


def test_card_rules_leave_out_the_pipeline_sections():
    card = (AGENTS / "csa-card-rules.md").read_text(encoding="utf-8")
    for name in ("Change files", "Subsections", "Word comments", "Tracked changes and human gates", "Evidence matrix first"):
        assert f"## {name}" not in card


def test_card_rules_stay_small():
    assert len((AGENTS / "csa-card-rules.md").read_bytes()) <= 6000
