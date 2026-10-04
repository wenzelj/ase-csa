"""Prose budget from the size of the system.

A section describing a big application needs more words than one describing a single server. The host
register (``<work_dir>/hosts/hosts.csv``, built by ``hostmodel build``) already knows how many in-scope
hosts, roles and connections there are, so the length guides come from that, not from a fixed number.

    section words        = 400 + 40 per in-scope host + 60 per role + 5 per host link   (400 .. 5000)
    Current State words  = 80 + 3 per in-scope host                                      (80 .. 250)

With no host register the old fixed guides are used (1500 and 100). These are guides (advisory notes in
prose_lint and a warning in check_section); they never block an edit.
"""
from __future__ import annotations

import csv
from pathlib import Path

DEFAULT_SECTION_WORDS = 1500
DEFAULT_CURRENT_STATE_WORDS = 100


def find_work_dir(*starts) -> Path | None:
    """The first folder holding hosts/hosts.csv: each start, its csa-work child, then its parents."""
    for s in starts:
        if not s:
            continue
        p = Path(s).resolve()
        for d in [p, *p.parents]:
            for cand in (d, d / "csa-work"):
                if (cand / "hosts" / "hosts.csv").is_file():
                    return cand
    return None


def system_size(work_dir: Path | None) -> dict | None:
    if not work_dir:
        return None
    hosts_csv = work_dir / "hosts" / "hosts.csv"
    if not hosts_csv.is_file():
        return None
    with hosts_csv.open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("host") or "").strip()]
    in_scope = [r for r in rows if not (r.get("in_scope") or "").strip()]  # empty in_scope = in scope (peers are marked)
    roles = {(r.get("role") or "").strip().lower() for r in in_scope} - {""}
    links = 0
    links_csv = work_dir / "hosts" / "host_links.csv"
    if links_csv.is_file():
        with links_csv.open(encoding="utf-8", newline="") as fh:
            links = sum(1 for _ in csv.DictReader(fh))
    return {"hosts": len(in_scope), "roles": len(roles), "links": links}


def budgets(*starts) -> dict:
    size = system_size(find_work_dir(*starts))
    if not size:
        return {"section_words": DEFAULT_SECTION_WORDS, "current_state_words": DEFAULT_CURRENT_STATE_WORDS, "basis": "default"}
    section = 400 + 40 * size["hosts"] + 60 * size["roles"] + 5 * size["links"]
    cs = 80 + 3 * size["hosts"]
    return {
        "section_words": max(400, min(5000, section)),
        "current_state_words": max(80, min(250, cs)),
        "basis": f"{size['hosts']} in-scope hosts, {size['roles']} roles, {size['links']} links",
    }


if __name__ == "__main__":
    import json, sys
    print(json.dumps(budgets(*(sys.argv[1:] or ["."])), indent=2))
