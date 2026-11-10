"""Check every open question against the evidence matrix and the discovery index (no model).

Reads csa-work/draft/open-questions.md (the `Unknown:` lines of every answered card, written by the draft lane) and
runs gap_lookup.lookup_gap on each question. What the index finds goes into the append-only lead store
(duplicates are reused and terminal leads are never offered again). The result is written to
csa-work/intake/gap-check-<UTC>.json and gap-check-latest.json for the Evidence Workspace.

    python3 -m csa_docx.gap_sweep --workspace <project_root> [--section KEY] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from csa_docx import gap_lookup

_SECTION = re.compile(r"^##\s+(\d+(?:\.\d+)*)\s+(.*?)\s+\(([A-Z0-9_]+)\)\s*$")
_FIGURE = re.compile(r"^##\s+Figure for\s+(\d+(?:\.\d+)*)\s+(.*?)\s*$")
_ROLE = re.compile(r"^##\s+Role table for\s+(.*?)\s*$")
_BULLET = re.compile(r"^\s*-\s+\[([A-Za-z0-9_.-]+)\]\s+(.+?)\s*$")


def question_fingerprint(text: str) -> str:
    """Content identity for a question, independent of its position in the question file."""
    normal = re.sub(r"\s+", " ", text or "").strip().casefold()
    return "sha256:" + hashlib.sha256(normal.encode("utf-8")).hexdigest()


def _generated_dr_id(base_id: str, text: str) -> str:
    """A readable, position-independent DR id. Rewording creates a new question identity."""
    return f"{base_id}-Q{question_fingerprint(text).split(':', 1)[1][:12].upper()}"


def parse_open_questions(text: str) -> list[dict]:
    """[{number, title, key, qid, dr_id, text}] from open-questions.md. A figure heading takes the key of the section
    with the same number (FIGURE-<number> when there is none). Lines outside a recognised heading, and bullets without
    a [QID], are skipped."""
    keys: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        m = _SECTION.match(line)
        if m:
            keys.setdefault(m.group(1), (m.group(3), m.group(2)))
    out: list[dict] = []
    current: tuple[str, str, str] | None = None        # (number, title, key)
    used: set[str] = set()
    for line in text.splitlines():
        if line.startswith("## "):
            m, f, rt = _SECTION.match(line), _FIGURE.match(line), _ROLE.match(line)
            if m:
                current = (m.group(1), m.group(2), m.group(3))
            elif f:
                key, title = keys.get(f.group(1), (f"FIGURE-{f.group(1)}", f.group(2)))
                current = (f.group(1), title, key)
            elif rt:
                # role-table capture gaps carry their own DR id (DR-<key>-Tnn); the section number
                # is only a display nicety, so an unknown table falls back to the table title
                cur = None
                for number, (_, title) in keys.items():
                    if title and title.split(" & ")[0].lower() == rt.group(1).lower():
                        cur = (number, title, f"ROLETABLE-{number}")
                        break
                current = cur or ("", rt.group(1), "ROLETABLE")
            else:
                current = None
            continue
        b = _BULLET.match(line)
        if not b or current is None:
            continue
        bracket, body = b.group(1), b.group(2)
        number, title, key = current
        explicit = bracket.upper().startswith("DR-")
        if explicit:
            base_id, qid = bracket, bracket.rsplit("-", 1)[-1]
        else:
            base_id, qid = f"DR-{key}-{bracket}", bracket
        # Generated IDs include the question fingerprint, so reordering other QUESTION lines cannot
        # attach an old settlement to different words. Explicit DR IDs remain authoritative; only a
        # malformed duplicate explicit ID receives the same content-derived disambiguator.
        dr_id = base_id if explicit and base_id not in used else _generated_dr_id(base_id, body)
        if dr_id in used:  # identical duplicate line: retain a unique parse result and flag it below
            dr_id = f"{dr_id}-DUP"
        used.add(dr_id)
        out.append({"number": number, "title": title, "key": key, "qid": qid, "dr_id": dr_id,
                    "question_fingerprint": question_fingerprint(body), "text": body})
    return out


def _safe_for_retirement(text: str, questions: list[dict]) -> bool:
    """Only retire after every question line parsed and every parsed DR ID is unambiguous.
    parse_open_questions gives each line a unique DR id (a block can hold several questions), so
    the only failure left here is a question file with unparseable or malformed list lines."""
    if not text.strip() or not questions:
        return False
    bullets = [line for line in text.splitlines() if line.lstrip().startswith("- ")]
    if len(bullets) != len(questions):
        return False
    ids = [q["dr_id"] for q in questions]
    return len(ids) == len(set(ids))


def _retire_absent(workspace: Path, questions: list[dict], section_key: str | None) -> list[str]:
    from csa_docx import leads
    active = {q["dr_id"] for q in questions}
    rows = leads.open_leads(workspace)
    if section_key:
        rows = [r for r in rows if str(r.get("dr_id", "")).startswith(f"DR-{section_key}-")]
    ids = [r["lead_id"] for r in rows if r.get("dr_id") not in active]
    if ids:
        scope = f"section {section_key}" if section_key else "complete open-question set"
        leads.review(workspace, ids, "retired", "gap sweep", f"question absent from successful {scope}")
    return ids


def _drain_closed_leads(workspace: Path, results: list[dict]) -> list[str]:
    """Terminalise the open leads of the questions this run closed: NOT_FOUND leaves are not an answer and
    ANSWERED leaves are superseded by the explicit resolution. Only leads of the run's own questions, and only
    through the append-only review log — no lead row is deleted and no evidence-matrix row is written."""
    from csa_docx import leads
    closed: dict[str, dict] = {}
    for r in results:
        if r["verdict"] in ("NOT_FOUND", "ANSWERED"):
            closed[r["dr_id"]] = r
    rows = leads.open_leads(workspace)
    for dr_id, q in closed.items():
        ids = [r["lead_id"] for r in rows if r.get("dr_id") == dr_id]
        if not ids:
            continue
        if q["verdict"] == "NOT_FOUND":
            note = "question closed NOT_FOUND by fresh gap-check; saved scope supersedes earlier candidate: " \
                   + q.get("searched", "")[:200]
            leads.review(workspace, ids, "not_an_answer", "gap sweep", note)
        else:
            note = "question closed ANSWERED by fresh gap-check; answered by " + \
                   (", ".join(q.get("answer_evidence_ids") or []) or "saved resolution record")
            leads.review(workspace, ids, "retired", "gap sweep", note)
    return sorted({r["lead_id"] for r in rows if r.get("dr_id") in closed})


def refresh_derived_questions(workspace: Path, project_key: str, docx: Path) -> dict:
    """Refresh capture-derived gap stores and the consolidated question file; never alter the DOCX."""
    workspace = Path(workspace)
    work = workspace / "csa-work"
    from csa_docx import draft_lane, topic_tables
    tables = topic_tables.refresh_saved(work)
    errors = [r for r in tables if r.get("status") not in ("OK", "NO_PROFILE", "EMPTY")]
    if errors:
        raise RuntimeError("role-table gap refresh failed: " + "; ".join(
            f"{r.get('key')}: {r.get('message') or r.get('status')}" for r in errors))
    from csa_docx.figures import work as figure_work
    from csa_docx.techdiagram.cli import _network
    ctx = figure_work.open_ctx(project_key, work, Path(docx), _network(work))
    figures = figure_work.refresh_gap_records(ctx)
    questions = draft_lane.open_questions(work)
    return {"topic_tables": tables, "figures": figures, "questions": questions}


def card_listed(work: Path, key: str, qid: str, cache: dict) -> set[str] | None:
    """The evidence IDs the section's card listed for one answer-sheet block (cards/<KEY>.json, evidence[<block>].rows): what the
    answerer was shown. None when there is no card or the card has no such block (a figure or role-table question). Read only."""
    if key not in cache:
        try:
            cache[key] = json.loads((Path(work) / "cards" / f"{key}.json").read_text(encoding="utf-8")).get("evidence") or {}
        except (OSError, ValueError):
            cache[key] = None
    evidence = cache[key]
    if not evidence or qid not in evidence:
        return None
    return {str(r.get("id", "")).upper() for r in evidence[qid].get("rows", [])}


def sweep(workspace: Path, section_key: str | None = None, *, refresh_derived: bool = False,
          project_key: str = "", docx: Path | None = None) -> dict:
    """Look up every open question (or one section's); write intake/gap-check-<ts>.json and gap-check-latest.json."""
    workspace = Path(workspace)
    work = workspace / "csa-work"
    if refresh_derived:
        if not project_key or not docx:
            raise ValueError("refreshing derived questions requires project_key and docx")
        refresh_derived_questions(workspace, project_key, Path(docx))
    source = work / "draft" / "open-questions.md"
    source_text = source.read_text(encoding="utf-8") if source.is_file() else ""
    all_questions = parse_open_questions(source_text)
    safe_retirement = _safe_for_retirement(source_text, all_questions)
    from csa_docx import question_exclusions
    removed = question_exclusions.load(work)           # questions the owner removed from the list
    qs = [q for q in all_questions if q["dr_id"] not in removed]
    if section_key:
        qs = [q for q in qs if q["key"] == section_key]
    results = []
    cards: dict = {}
    for q in qs:
        duplicate_id = sum(1 for candidate in all_questions if candidate["dr_id"] == q["dr_id"]) > 1
        if duplicate_id or not safe_retirement:
            reason = "duplicate DR id" if duplicate_id else "question file contains unparsed or malformed question lines"
            res = {"verdict": "INCOMPLETE", "answer_evidence_ids": [], "related_evidence_ids": [],
                   "lead_ids": [], "kind": "system", "owners": [], "ask": False, "queries": [],
                   "searched": f"not searched: {reason}",
                   "coverage": {"incomplete_reasons": [reason]}}
        else:
            res = gap_lookup.lookup_gap(workspace, q["dr_id"], q["text"])
        answers = list(dict.fromkeys(res.get("answer_evidence_ids", res.get("evidence_ids", []))))[:gap_lookup._MAX_CANDIDATES]
        related = list(dict.fromkeys(res.get("related_evidence_ids", res.get("related", []))))[:gap_lookup._MAX_CANDIDATES]
        lead_ids = list(dict.fromkeys(res.get("lead_ids", res.get("index", []))))[:gap_lookup._MAX_CANDIDATES]
        results.append({**q, "verdict": res["verdict"], "answer_evidence_ids": answers,
                        "related_evidence_ids": related, "lead_ids": lead_ids, "evidence_ids": answers,
                        "kind": res.get("kind", ""), "owners": res.get("owners", []), "ask": bool(res.get("ask")), "related": related,
                        "queries": res.get("queries", []), "searched": res.get("searched", ""),
                        "searches": len(res.get("queries", [])),
                        "coverage": res.get("coverage", {}), "incomplete": res.get("verdict") == "INCOMPLETE"})
        listed = card_listed(work, q["key"], q["qid"], cards)
        # related rows the answerer was never shown: the card's row selection did not surface them. Information only; no verdict uses it
        results[-1].update({"card_block": listed is not None,
                            "unseen_related": [] if listed is None else [e for e in related if str(e).upper() not in listed]})
    retired = _retire_absent(workspace, qs, section_key) if safe_retirement else []
    drained = _drain_closed_leads(workspace, results) if safe_retirement else []
    affected: dict[str, dict] = {}
    for r in results:
        if r["verdict"] not in ("ANSWERED", "CANDIDATES"):
            continue
        a = affected.setdefault(r["key"], {"number": r["number"], "key": r["key"], "title": r["title"],
                                           "answered": 0, "candidates": 0})
        a["answered" if r["verdict"] == "ANSWERED" else "candidates"] += 1
    stamp = time.gmtime()
    input_warnings = [] if safe_retirement else ["question file is empty, malformed, contains unparsed list items, or reuses a DR id"]
    record = {"schema_version": 4, "input_complete": safe_retirement, "input_warnings": input_warnings,
              "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", stamp), "section": section_key or "",
              "questions": results, "affected": list(affected.values()), "retired_lead_ids": retired,
              "drained_lead_ids": drained, "removed_by_owner": sorted(q["dr_id"] for q in all_questions if q["dr_id"] in removed),
              "summary": summarise(results)}
    folder = work / "intake"
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=1, ensure_ascii=False)
    (folder / f"gap-check-{time.strftime('%Y%m%dT%H%M%SZ', stamp)}.json").write_text(text, encoding="utf-8")
    (folder / "gap-check-latest.json").write_text(text, encoding="utf-8")
    write_to_ask(folder / "to-ask-latest.md", results, record["checked_at"])
    return record


def write_to_ask(path: Path, results: list[dict], stamp: str) -> None:
    """The questions a person has to answer, grouped by who the question names (or "to be assigned") and then by section."""
    groups: dict[str, dict[str, list[dict]]] = {}
    for r in results:
        if (r.get("ask") or r.get("owners")) and r["verdict"] != "ANSWERED":
            for who in r.get("owners") or ["to be assigned"]:
                groups.setdefault(who, {}).setdefault(f"{r['number']} {r['title']}", []).append(r)
    lines = [f"# Questions for people ({stamp})", "",
             "Questions the captures cannot answer: who owns or decides something, or a policy, plan, procedure, fallback or test. "
             "Possible answers found in documents are marked for reading."]
    for who in sorted(groups):
        lines += ["", f"## {who}"]
        for section, items in groups[who].items():
            lines += ["", f"### {section}"]
            lines += [f"- [{q['qid']}] {q['text']}" + (f" (leads to read: {len(q['lead_ids'])})" if q.get("lead_ids") else "")
                      for q in items]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarise(results: list[dict]) -> dict:
    """What a lookup run did, in numbers: gaps, by kind and verdict, searches run, candidates to read (never more than five
    per gap), gaps with related matrix rows to read, and who has to be asked for the ones nothing answers."""
    import collections
    verdicts = collections.Counter(r["verdict"] for r in results)
    # who has to be asked: every open question a person must answer, under the owner its wording names or "to be assigned"
    ask = collections.Counter(o for r in results if (r.get("ask") or r.get("owners")) and r["verdict"] != "ANSWERED"
                              for o in (r.get("owners") or ["to be assigned"]))
    return {"gaps": len(results), "by_kind": dict(collections.Counter(r.get("kind") or "system" for r in results)),
            "by_verdict": dict(verdicts), "searches": sum(r.get("searches", 0) for r in results),
            "incomplete": verdicts.get("INCOMPLETE", 0),
            "candidates_to_read": sum(len(r.get("lead_ids", [])) for r in results if r["verdict"] == "CANDIDATES"),
            "gaps_with_related_rows": sum(1 for r in results if r.get("related")),
            "card_blocks": sum(1 for r in results if r.get("card_block")),
            "gaps_with_unseen_related": sum(1 for r in results if r.get("unseen_related")),
            "to_ask": dict(ask.most_common(6))}


def report_lines(summary: dict) -> list[str]:
    s = summary
    k = ", ".join(f"{n} {name}" for name, n in sorted(s["by_kind"].items()))
    v = ", ".join(f"{n} {name.lower().replace('_', ' ')}" for name, n in sorted(s["by_verdict"].items()))
    lines = [f"{s['gaps']} open question(s): {k}.", f"Result: {v}.",
             f"{s['searches']} search(es) run; {s['candidates_to_read']} candidate(s) to read (at most {gap_lookup._MAX_CANDIDATES} per question); "
             f"{s['gaps_with_related_rows']} question(s) with related matrix rows to read."]
    if s.get("card_blocks"):
        lines.append(f"{s['gaps_with_unseen_related']} of {s['card_blocks']} question(s) with a card block have related rows "
                     f"the card never listed for it.")
    if s.get("incomplete"):
        lines.append(f"{s['incomplete']} question(s) have incomplete checks and remain open; see coverage.incomplete_reasons.")
    if s["to_ask"]:
        lines.append("Still open, to ask: " + "; ".join(f"{o} ({n})" for o, n in s["to_ask"].items()) + ".")
    return lines


_LABEL = {"ANSWERED": "answered", "CANDIDATES": "possible answer found", "NOT_FOUND": "not found", "INCOMPLETE": "search incomplete"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check every open question against the evidence matrix and the index.")
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--section", default="", help="only this section's questions (stamp key, e.g. BAK)")
    ap.add_argument("--refresh-derived", action="store_true")
    ap.add_argument("--project-key", default="")
    ap.add_argument("--docx", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = sweep(a.workspace, a.section or None, refresh_derived=a.refresh_derived,
                project_key=a.project_key, docx=a.docx)
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if not res["questions"]:
        if res.get("input_complete"):
            print("No open questions (csa-work/draft/open-questions.md is missing or empty).")
        else:
            print("No parseable open questions; checks are incomplete. Review input_warnings in gap-check-latest.json.")
        return 0
    for q in res["questions"]:
        ids = ", ".join(q.get("lead_ids", []) if q["verdict"] == "CANDIDATES" else q.get("answer_evidence_ids", []))
        print(f"  {q['number']:<6} {q['dr_id']:<34} {_LABEL.get(q['verdict'], q['verdict'].lower())}" + (f" ({ids})" if ids else ""))
    print("")
    for line in report_lines(res["summary"]):
        print(line)
    n = sum(a["answered"] + a["candidates"] for a in res["affected"])
    print(f"{n} of {len(res['questions'])} open question(s) have evidence to read, in {len(res['affected'])} subsection(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
