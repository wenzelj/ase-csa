"""Deterministic gap checking against the csa-work-v2 repository.

This is the v2 counterpart to the v1 ``gap_sweep`` storage path.  It keeps the
question-file and result shape used by the Evidence Workspace, but stores leads
and sweep history in SQLite through ``Repo``.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import gap_lookup, v2_access
from .gap_sweep import card_listed, parse_open_questions, summarise, write_to_ask
from .v2repo import Repo
from .v2repo import intake as _intake  # noqa: F401  (registers Repo namespaces)


def _words(text: str) -> list[str]:
    return [w for w in gap_lookup.topic_words(gap_lookup.strip_confirmers(text), limit=8)
            if len(w) >= 4]


def _evidence_candidates(repo: Repo, text: str, limit: int = 5) -> list[str]:
    words = _words(text)
    if not words:
        return []
    scored = []
    for row in repo.evidence.list(status="VERIFIED"):
        if row.get("review_state") == "rejected":
            continue
        hay = " ".join(str(row.get(k) or "") for k in ("claim", "question", "excerpt")).lower()
        score = sum(1 for word in words if word in hay)
        if score:
            scored.append((score, row["id"]))
    return [eid for _, eid in sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]]


def _index_candidates(repo: Repo, text: str, limit: int = 5) -> list[dict]:
    words = _words(text)
    if not words:
        return []
    hits = v2_access.index_search(repo.path, " ".join(words), limit=limit * 3,
                                  per_file=1, any_terms=True)
    if hits.get("status") != "OK":
        return []
    relevant = [h for h in hits.get("results", [])
                if gap_lookup.relevant(h.get("evidence_excerpt", ""), text)]
    return gap_lookup.rank_hits(relevant, text, limit=limit)


def _open_questions(work: Path) -> list[dict]:
    source = work / "draft" / "open-questions.md"
    if not source.is_file():
        from . import draft_lane
        draft_lane.open_questions(work)
    return parse_open_questions(source.read_text(encoding="utf-8"))


def run(work_dir: str | Path, section_key: str | None = None) -> dict:
    """Run a v2 gap check and write the compatible JSON/ask snapshots."""
    work = Path(work_dir)
    if work.name != "csa-work-v2":
        raise ValueError("v2 gap check requires a csa-work-v2 directory")
    repo = Repo(work)
    try:
        questions = [q for q in _open_questions(work)
                     if not section_key or q["key"] == section_key]
        results = []
        with repo.tx():
            for q in questions:
                evidence_ids = _evidence_candidates(repo, q["text"])
                hits = _index_candidates(repo, q["text"])
                lead_ids = []
                for hit in hits:
                    scope = f"v2 discovery index: {hit.get('rel_path', '')}"
                    existing = [x for x in repo.leads.list(state="open", dr_id=q["dr_id"])
                                if scope in x.get("searched_scope", "")]
                    if existing:
                        lead_ids.append(existing[0]["id"])
                    else:
                        lead_ids.append(repo.leads.create(
                            q["text"], scope, dr_id=q["dr_id"], actor="csa-gap-check"))
                verdict = "CANDIDATES" if lead_ids else ("CANDIDATES" if evidence_ids else "NOT_FOUND")
                searched = "v2 evidence table; v2 discovery FTS"
                if not hits:
                    searched += " (no relevant FTS hits)"
                repo.gap_checks.run(q["dr_id"], q["text"], lead_ids,
                                   actor="csa-gap-check", note=searched)
                related = evidence_ids if not lead_ids else []
                results.append({**q, "verdict": verdict,
                                "answer_evidence_ids": [], "related_evidence_ids": related,
                                "lead_ids": lead_ids, "evidence_ids": [],
                                "kind": gap_lookup.classify_gap(q["text"]),
                                "owners": gap_lookup.owners_in(q["text"]),
                                "ask": gap_lookup.needs_person(q["text"]),
                                "queries": words_for_report(q["text"]),
                                "searched": searched, "searches": 1,
                                "coverage": {"matrix": "v2", "index_complete": True},
                                "incomplete": False})
        affected = []
        for row in results:
            if row["verdict"] in ("ANSWERED", "CANDIDATES"):
                current = next((x for x in affected if x["key"] == row["key"]), None)
                if current is None:
                    current = {"number": row["number"], "key": row["key"],
                               "title": row["title"], "answered": 0, "candidates": 0}
                    affected.append(current)
                current["candidates"] += row["verdict"] == "CANDIDATES"
                current["answered"] += row["verdict"] == "ANSWERED"
        record = {"schema_version": 4, "input_complete": True, "input_warnings": [],
                  "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "section": section_key or "", "questions": results, "affected": affected,
                  "retired_lead_ids": [], "drained_lead_ids": [], "removed_by_owner": [],
                  "summary": summarise(results)}
        folder = work / "intake"
        folder.mkdir(parents=True, exist_ok=True)
        text = json.dumps(record, indent=1, ensure_ascii=False)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        (folder / f"gap-check-{stamp}.json").write_text(text, encoding="utf-8")
        (folder / "gap-check-latest.json").write_text(text, encoding="utf-8")
        write_to_ask(folder / "to-ask-latest.md", results, record["checked_at"])
        return record
    finally:
        repo.close()


def words_for_report(text: str) -> list[str]:
    return _words(text)
