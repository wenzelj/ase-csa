"""Questions, brief and section card for one node of the document spec.

The questions come from the document: each requirement row asks for the current state and a rating
against its requirement text; each observation table and register asks for one row per thing with the
table's columns; each placeholder paragraph asks its bracket text; each findings list asks for one bullet
per finding; each reviewer comment under the heading is a C question. The scope map's Must explain and
Not here are added when the node's requirement family or heading matches a scope-map domain; a section
with no entry still gets every question from its own tables.

The section card is the AI's whole input for one node: the questions, the requirement text, columns,
guidance, reviewer comments, the current text, the scope extras, one worked example for its kind and
the evidence pack (candidate evidence per question, gathered before the AI starts).

    python3 -m csa_docx.section_card --docx D [--workspace W] [--work-dir WD] <target> [--brief] [--no-evidence]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from csa_docx import doc_spec

REFERENCES = Path(__file__).resolve().parents[2] / "references"
EXAMPLES = REFERENCES / "answer-examples"
MAX_ROWS_PER_QUESTION = 8
EXCERPT = 300


# ---------------------------------------------------------------- questions

def _topic(node: dict) -> str:
    return node["title"]


def questions(node: dict, spec: dict | None = None) -> list[dict]:
    """[{id, kind, part, text, req_id?, columns?}] in document order. Reviewer comments become C items."""
    out: list[dict] = []
    ratings = " / ".join((spec or {}).get("ratings") or doc_spec.DEFAULT_RATINGS)
    for i, p in enumerate(node["parts"]):
        where = p.get("label") or p.get("facet") or _topic(node)
        k = p["kind"]
        if k == "requirement":
            for r in p["requirements"]:
                out.append({"kind": "requirement", "part": i, "req_id": r["id"], "row": r["row"],
                            "text": f"{r['id']}: \"{r['text']}\" What is the current state of the system against this "
                                    f"requirement, and how does it rate ({ratings}; Not Applicable needs a justification)?"})
        elif k == "observation":
            cols = p.get("columns") or []
            out.append({"kind": "observation", "part": i, "columns": cols,
                        "text": f"{where}: which aspects of {_topic(node)} were observed? One row per aspect with "
                                f"{', '.join(cols[1:]) or 'what was observed'}."})
        elif k == "register":
            cols = p.get("columns") or []
            first = cols[0] if cols else "item"
            out.append({"kind": "register", "part": i, "columns": cols,
                        "text": f"{where}: one row per {first.lower()}, with {', '.join(cols[1:]) or 'its details'}."})
        elif k == "narrative":
            out.append({"kind": "narrative", "part": i,
                        "text": f"{p.get('facet') or _topic(node)}: {p.get('question') or 'one paragraph'}"})
        elif k == "findings":
            holders = [b for b in p.get("bullets", []) if doc_spec.is_placeholder(b)]
            hint = holders[0].strip("[] ") if holders else "finding"
            out.append({"kind": "findings", "part": i,
                        "text": f"{p.get('facet') or _topic(node)}: one bullet per {hint.lower()}"
                                + (" (keep the standard bullets)" if len(holders) < len(p.get("bullets", [])) else "") + "."})
    for n, q in enumerate(out, start=1):
        q["id"] = f"B{n}"
    for n, c in enumerate(node.get("comments", []), start=1):
        out.append({"id": f"C{n}", "kind": "comment", "part": None,
                    "text": f"Reviewer comment ({c['author'] or 'unknown'}): \"{' '.join(c['text'].split())[:240]}\""})
    return out


def scope_extras(node: dict) -> dict | None:
    """Must explain / Not here from the scope map, by requirement family or heading, never by number."""
    try:
        from csa_docx import scope_map
        domains = scope_map.load()
    except (ImportError, OSError, ValueError):
        return None
    fams = set(doc_spec.families(node))
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower().replace("&", " and ")).strip()  # noqa: E731
    for d in domains.values():
        dfams = {re.match(r"SEP-([A-Z]+)-", r).group(1) for r in d["req_ids"]}
        if (fams and fams & dfams) or norm(d["title"]) == norm(node["title"]):
            return {"must_explain": d["must_explain"].strip(), "not_here": d["not_here"].strip(), "owns": d["owns"].strip()}
    return None


def rules(node: dict, spec: dict | None = None) -> list[str]:
    """The template's guidance that applies to this node. The template writes a rule once, on the first block
    of its kind ("This applies to every ..."), so a node also inherits: its section's (Heading 1) guidance,
    the guidance on the first sibling of the same kind, and guidance on facets (Discovery Information,
    Drawbridge Impact) and labels it shares."""
    own = list(node.get("guidance", []))
    if spec:
        nodes = spec["nodes"]
        parent = next((n for n in nodes if n["path"] == node.get("parent")), None)
        if parent:
            own += [g for g in parent.get("guidance", []) if not g.get("facet")]
        first = next((n for n in nodes if n.get("parent") == node.get("parent") and n["kind"] == node["kind"]), None)
        facets = {p.get("facet") for p in node["parts"] if p.get("facet")} | {p.get("label") for p in node["parts"] if p.get("label")}
        if first and first is not node:
            own += [g for g in first.get("guidance", []) if not g.get("facet") or g.get("facet") in facets]
    seen, out = set(), []
    for g in own:
        t = " ".join(g["text"].split())
        if t not in seen:
            seen.add(t)
            out.append((f"{g['facet']}: " if g.get("facet") else "") + t)
    return out


def brief_markdown(node: dict, spec: dict | None = None) -> str:
    """The `## Section brief` block a change file carries (check-change reads it)."""
    qs = questions(node, spec)
    extra = scope_extras(node)
    reqs = [q["req_id"] for q in qs if q.get("req_id")]
    path = node["title"]
    if node.get("parent") and spec:
        parent = next((n for n in spec["nodes"] if n["path"] == node["parent"]), None)
        if parent:
            path = f"{parent['title']} > {node['title']}"
    purpose = (f"Explain, for {path}: {extra['must_explain'][:1].lower() + extra['must_explain'][1:]}"
               if extra and extra["must_explain"] else
               f"Answer what {path} asks in the document: " + "; ".join(sorted({q["kind"] for q in qs if q["kind"] != "comment"})))
    lines = ["## Section brief", "", f"- **Purpose:** {purpose.rstrip('.')}.",
             f"- **Requirements:** {', '.join(reqs) or 'none in this section'}", "- **Questions:**"]
    lines += [f"  - {q['id']} {q['text']}" for q in qs]
    lines.append(f"- **Not here:** {(extra or {}).get('not_here') or 'no scope-map entry for this section'}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- evidence pack

def _skills() -> Path:
    return Path(__file__).resolve().parents[2] / "skills"


def _run(cmd: list[str]) -> dict | None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def _matrix(workspace: Path, query: str, limit: int = MAX_ROWS_PER_QUESTION) -> list[dict]:
    script = _skills() / "csa-evidence-matrix" / "scripts" / "evidence_matrix.py"
    res = _run([sys.executable, str(script), "--workspace", str(workspace), "lookup", query, "--limit", str(limit)])
    return (res or {}).get("matches", []) if (res or {}).get("status") == "OK" else []


def _row(m: dict) -> dict:
    """One evidence row as the card shows it."""
    legacy = (m.get("gap_or_action") or "").startswith("legacy L-")
    return {"id": m["evidence_id"], "status": m.get("status", ""),
            "claim": " ".join((m.get("claim") or "").split())[:EXCERPT],
            "source": (m.get("source_title") or "")[:160],
            "note": "previous assessment, not checked against the captures" if legacy else
                    ("searched: " + (m.get("source_title") or "")[:160]) if m.get("status") == "NOT_FOUND" else ""}


_STATUS_RANK = {"VERIFIED": 0, "INFERRED": 1, "CONFLICTING": 2, "UNCONFIRMED": 3, "NOT_FOUND": 4}
_STOP = set("""what which where when does each every with from that this have were would their there also into only
other about after before while will should could being been than then them they these those system systems current
state against requirement rate rating how and the for one row per aspect aspects observed""".split())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower().replace("&", " and ")).strip()


def _words(s: str) -> set[str]:
    return {w for w in _norm(s).split() if len(w) > 3 and w not in _STOP}


def _matrix_rows(workspace: Path) -> list[dict]:
    import csv
    path = Path(workspace) / "csa-work" / "evidence-matrix.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _rejected(workspace: Path) -> set[str]:
    path = Path(workspace) / "csa-work" / "evidence-reviews.jsonl"
    latest: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                latest[rec.get("evidence_id", "").upper()] = rec.get("state", "")
    return {i for i, s in latest.items() if s == "rejected"}


def evidence_pack(node: dict, qs: list[dict], workspace: Path | None, extra_searches: dict | None = None,
                  exclude: tuple[str, ...] = ()) -> dict:
    """{question id: {"rows", "cut", "candidates", "searched"}}, gathered before the AI starts.

    Rows recorded for this section (the matrix `section` or `csa_area` names its topic) come first, ranked by
    status and by the words they share with the question; matrix lookups add rows recorded elsewhere; index
    hits not yet in the matrix are offered as unverified candidates only when they are about the question.
    Rejected rows are never offered. Capped per question; what is cut is listed by ID."""
    pack: dict[str, dict] = {}
    if not workspace:
        return pack
    try:
        from csa_docx import gap_lookup
    except ImportError:
        gap_lookup = None
    rows = _matrix_rows(workspace)
    rejected = _rejected(workspace)
    topic = _norm(node["title"])
    own = [r for r in rows if r["evidence_id"].upper() not in rejected and (
        topic and (topic in _norm(r.get("section", "")) or _norm(r.get("csa_area", "")) in (topic, topic.replace(" and ", " "))))]
    for q in qs:
        if q["kind"] == "comment":
            continue
        qwords = _words(q["text"]) | _words(node["title"])
        searched = [f"matrix rows recorded for {node['title']}"]
        scored: dict[str, tuple] = {}
        for r in own:
            overlap = len(qwords & _words(r.get("claim", "") + " " + r.get("question", "")))
            scored[r["evidence_id"]] = (_STATUS_RANK.get(r.get("status", ""), 5), -overlap, r)
        queries = [node["title"] + " " + " ".join(sorted(qwords - _words(node["title"]))[:4])]
        queries += (extra_searches or {}).get(q["id"], [])
        for query in queries:
            searched.append(f"matrix lookup '{query.strip()}'")
            for m in _matrix(workspace, query):
                if m["evidence_id"].upper() in rejected or m["evidence_id"] in scored:
                    continue
                if m.get("score", 0) < 0.4 and query not in (extra_searches or {}).get(q["id"], []):
                    continue
                scored[m["evidence_id"]] = (_STATUS_RANK.get(m.get("status", ""), 5) + 1, -int(10 * m.get("score", 0)), m)
        ranked = [v[2] for v in sorted(scored.values(), key=lambda v: (v[0], v[1]))]
        kept = [_row(m) for m in ranked[:MAX_ROWS_PER_QUESTION]]
        cut = [m["evidence_id"] for m in ranked[MAX_ROWS_PER_QUESTION:]]
        cands = []
        if gap_lookup is not None:
            for query in [f"{node['title']} {' '.join(sorted(qwords)[:5])}"] + (extra_searches or {}).get(q["id"], []):
                hits, ran, _ = gap_lookup._index_stage(workspace, query, exclude)
                searched += [f"index '{x}'" for x in ran[:2]]
                for h in hits[:3]:
                    cands.append({"source": h.get("source_title", "")[:160], "where": h.get("page_or_location", ""),
                                  "excerpt": " ".join(h.get("evidence_excerpt", "").split())[:EXCERPT]})
        pack[q["id"]] = {"rows": kept, "cut": cut, "candidates": cands[:3], "searched": searched}
    return pack


# ---------------------------------------------------------------- card

def _example(kind: str) -> str:
    f = EXAMPLES / f"{kind}.md"
    return f.read_text(encoding="utf-8").strip() if f.is_file() else ""


def _current(node: dict) -> list[str]:
    out = []
    for p in node["parts"]:
        if p["kind"] == "requirement":
            for r in p["requirements"]:
                out.append(f"{r['id']}: current state: {r['current_state'] or '(empty)'}; rating: {r['rating'] or '(empty)'}")
        elif p["kind"] in ("narrative", "note") and p.get("answered") and p.get("text"):
            out.append(f"{p.get('facet') or node['title']}: {p['text'][:400]}")
        elif p["kind"] == "text" and p.get("text"):
            out.append(f"{p.get('facet') or node['title']}: {p['text'][:400]}")
        elif p["kind"] in ("observation", "register"):
            out.append(f"{p.get('label') or p.get('facet') or node['title']}: {p.get('filled', 0)} filled row(s) of {p.get('rows', 0)}")
    return out


_HOST = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b")


def _established(node: dict, qs: list[dict], pack: dict, workspace: Path | None) -> dict:
    """{question id: facts already established by validated sheets of other sections}, at most 8 per question.
    Their evidence rows join the question's pack (flagged `established`) so the answer may cite them."""
    if not workspace:
        return {}
    from csa_docx import fact_store

    work = Path(workspace) / "csa-work"
    if not fact_store.store_path(work).is_file():
        return {}
    rows = {r["evidence_id"].upper(): r for r in _matrix_rows(workspace)}
    out: dict[str, list[dict]] = {}
    for q in qs:
        if q["kind"] == "comment" or q["id"] not in pack:
            continue
        hosts = {h for r in pack[q["id"]]["rows"] for h in _HOST.findall(r.get("claim", ""))}
        found = fact_store.lookup(work, _words(q["text"]) | _words(node["title"]), hosts, 8, exclude_section=node["key"])
        if not found:
            continue
        out[q["id"]] = [{k: f[k] for k in ("fact", "evidence_ids", "section", "question", "basis")} for f in found]
        have = {r["id"].upper() for r in pack[q["id"]]["rows"]}
        for f in found:
            for eid in f["evidence_ids"]:
                if eid.upper() not in have and eid.upper() in rows:
                    pack[q["id"]]["rows"].append({**_row(rows[eid.upper()]), "established": True})
                    have.add(eid.upper())
    return out


def card(node: dict, spec: dict, workspace: Path | None = None, evidence: bool = True,
         extra_searches: dict | None = None, exclude: tuple[str, ...] = ()) -> dict:
    qs = questions(node, spec)
    pack = evidence_pack(node, qs, workspace, extra_searches, exclude) if evidence else {}
    established = _established(node, qs, pack, workspace) if pack else {}
    extra = scope_extras(node)
    kinds = sorted({q["kind"] for q in qs if q["kind"] != "comment"})
    lines = [f"# Card: {node['title']} (key {node['key']}, section {node['number']})", "",
             f"Kind: {node['kind']}", "", "## Questions", ""]
    for q in qs:
        lines.append(f"- {q['id']} {q['text']}")
        if q.get("columns"):
            lines.append(f"  Columns: {' | '.join(q['columns'])}")
    rl = rules(node, spec)
    if rl:
        lines += ["", "## Rules from the template", ""] + [f"- {r}" for r in rl]
    if extra:
        lines += ["", "## Scope", "", f"- Must explain: {extra['must_explain']}", f"- Not here: {extra['not_here']}"]
    cur = _current(node)
    if cur:
        lines += ["", "## Current text in the document", ""] + [f"- {c}" for c in cur]
    if established:
        lines += ["", "## Facts already established", "",
                  "Reuse a fact if it answers the question; still cite its evidence IDs.", ""]
        for qid, facts in established.items():
            lines.append(f"### {qid}")
            for f in facts:
                lines.append(f"- {f['fact']} (section {f['section']}; {', '.join(f['evidence_ids'])})")
    if pack:
        lines += ["", "## Evidence pack", ""]
        for qid, p in pack.items():
            lines.append(f"### {qid}")
            for r in p["rows"]:
                if r.get("established"):
                    continue                    # listed under Facts already established
                note = f" [{r['note']}]" if r["note"] else ""
                lines.append(f"- {r['id']} {r['status']}: {r['claim']}{note}")
            for c in p["candidates"]:
                lines.append(f"- candidate (unverified, not in the matrix): {c['source']} {c['where']}: {c['excerpt']}")
            if not p["rows"] and not p["candidates"]:
                lines.append("- nothing on record")
            if p["cut"]:
                lines.append(f"- more rows not shown: {', '.join(p['cut'])}")
            lines.append(f"- searched: {'; '.join(p['searched'])}")
    for k in kinds:
        ex = _example(k)
        if ex:
            lines += ["", f"## Example answer ({k})", "", ex]
    text = "\n".join(lines) + "\n"
    return {"status": "OK", "key": node["key"], "number": node["number"], "title": node["title"], "text": text,
            "questions": qs, "evidence": pack, "established": established, "tokens": len(text) // 4,
            "ratings": spec.get("ratings") or doc_spec.DEFAULT_RATINGS, "kinds": kinds}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("--docx", type=Path)
    ap.add_argument("--template", type=Path)
    ap.add_argument("--workspace", type=Path)
    ap.add_argument("--work-dir", type=Path)
    ap.add_argument("--brief", action="store_true", help="print only the section brief")
    ap.add_argument("--no-evidence", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--search", action="append", default=[], metavar="QID=TERMS",
                    help="extra searches the AI asked for, e.g. B3='w32tm local clock'")
    ap.add_argument("--exclude", action="append", default=[], help="a source file name never offered (the previous assessment)")
    a = ap.parse_args(argv)
    from csa_docx import spec_cli
    spec = spec_cli.load(a.docx, a.template, a.work_dir)
    try:
        node = doc_spec.resolve(spec, a.target)
    except doc_spec.ResolveError as e:
        print(str(e), file=sys.stderr)
        return 1
    if a.brief:
        text = brief_markdown(node, spec)
        if a.out:
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(text, encoding="utf-8")
        print(text, end="")
        return 0
    extra: dict[str, list[str]] = {}
    for s in a.search:
        qid, _, terms = s.partition("=")
        if terms.strip():
            extra.setdefault(qid.strip(), []).append(terms.strip())
    res = card(node, spec, a.workspace, evidence=not a.no_evidence, extra_searches=extra, exclude=tuple(a.exclude))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(res["text"], encoding="utf-8")
        a.out.with_suffix(".json").write_text(json.dumps({k: v for k, v in res.items() if k != "text"}, indent=1),
                                              encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "text"}, indent=1) if a.json else res["text"], end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
