"""The answer sheet: the AI's whole output for one section card, in a fixed shape the framework checks.

    ## B1 SEP-TIME-01
    Facts:
    - Every scoped host synchronises from an enterprise NTP server. (E-063) {observed; all 12 hosts}
    Unknown: whether a fallback source exists during isolation.
    Rating: Not Met
    Rating reason: the requirement asks for an OT-resident source; none was evidenced.

    ## B2 Discovery Information
    Rows:
    | Aspect | Configuration Observed | Coverage / Source |
    | Time source | Enterprise NTP, stratum 4 | all 12 hosts; 03_time_status (E-063) |

    ## B3 Drawbridge Impact
    Facts:
    - ...
    Keep: the current paragraph already answers this.      (revise lane: leave the document as it is)
    Search: w32tm local clock fallback                     (ask the framework for more evidence, once)

The AI never writes anchors, edit IDs, Where/Do lines, front matter or comment notes: `render` adds them
from the document spec. `validate` enforces: a block for every question, evidence IDs that exist and were
on the card (or were appended by this run), a basis of observed / documented / stated, hosts in a fact's
scope that appear in the cited evidence, a rating from the document's own dropdown with a reason, table
rows with exactly the table's columns.

    python3 -m csa_docx.answer_sheet validate <sheet> --card <card.json> [--matrix evidence-matrix.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

_BLOCK = re.compile(r"^##\s+([BC]\d+)\b[^\n]*$", re.M)
_FIELD = re.compile(r"^(Facts|Unknown|Rating reason|Rating|Rows|Bullets|Search|Keep|Answer):\s*(.*)$", re.I)
_FACT = re.compile(r"^[-*]\s+(?P<text>.+?)\s*(?:\((?P<ids>E-\d+(?:\s*,\s*E-\d+)*)\))?\s*(?:\{(?P<meta>[^}]*)\})?\s*$")
_EID = re.compile(r"\bE-\d+\b")
_HOST = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")
BASES = ("observed", "documented", "stated")


# ---------------------------------------------------------------- parse

def parse(text: str) -> dict[str, dict]:
    """{question id: {facts: [...], unknown, rating, rating_reason, rows: [[...]], bullets: [...], search: [...], keep}}"""
    out: dict[str, dict] = {}
    marks = list(_BLOCK.finditer(text))
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        b = {"facts": [], "unknown": [], "rating": "", "rating_reason": "", "rows": [], "bullets": [],
             "search": [], "keep": "", "answer": "", "raw": body.strip()}
        field = None
        for line in body.splitlines():
            s = line.strip()
            if not s:
                continue
            f = _FIELD.match(s)
            if f:
                field = f.group(1).lower()
                val = f.group(2).strip()
                if field == "unknown" and val:
                    b["unknown"].append(val)
                elif field == "rating":
                    b["rating"] = val
                elif field == "rating reason":
                    b["rating_reason"] = val
                elif field == "search" and val:
                    b["search"].append(val)
                elif field == "keep":
                    b["keep"] = val or "yes"
                elif field == "answer":
                    b["answer"] = val
                continue
            if field == "facts" and s.startswith(("-", "*")):
                fm = _FACT.match(s)
                meta = (fm.group("meta") or "") if fm else ""
                basis, _, scope = meta.partition(";")
                b["facts"].append({"text": (fm.group("text") if fm else s.lstrip("-* ")).strip(),
                                   "ids": _EID.findall(fm.group("ids") or "") if fm else _EID.findall(s),
                                   "basis": basis.strip().lower(), "scope": scope.strip(), "line": s})
            elif field == "rows" and s.startswith("|"):
                cells = [c.strip() for c in s.strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    b["rows"].append(cells)
            elif field == "bullets" and s.startswith(("-", "*")):
                b["bullets"].append(s.lstrip("-* ").strip())
            elif field == "unknown":
                b["unknown"].append(s.lstrip("-* "))
            elif field == "search":
                b["search"].append(s.lstrip("-* "))
            elif field in ("rating reason",):
                b["rating_reason"] = (b["rating_reason"] + " " + s).strip()
        out[m.group(1)] = b
    return out


# ---------------------------------------------------------------- validate

def load_matrix(path: Path | None) -> dict[str, dict]:
    if not path or not Path(path).is_file():
        return {}
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        return {r["evidence_id"].upper(): r for r in csv.DictReader(fh)}


def _f(level: str, code: str, qid: str | None, message: str) -> dict:
    return {"level": level, "code": code, "question": qid, "message": message}


def validate(sheet: dict[str, dict], card: dict, matrix: dict[str, dict] | None = None,
             ratings: list[str] | None = None, new_ids: set[str] | None = None) -> dict:
    """Findings for a parsed sheet against its card. ERROR blocks rendering; WARN is reported."""
    findings: list[dict] = []
    matrix = matrix or {}
    allowed = {r["id"].upper() for p in card.get("evidence", {}).values() for r in p.get("rows", [])}
    allowed |= {i.upper() for i in (new_ids or set())}
    ratings = ratings or card.get("ratings") or ["Met", "Partially Met", "Not Met", "Not Applicable"]
    qs = {q["id"]: q for q in card["questions"]}
    searches = {qid: b["search"] for qid, b in sheet.items() if b["search"]}
    for qid, q in qs.items():
        b = sheet.get(qid)
        if b is None:
            findings.append(_f("ERROR", "QUESTION_MISSING", qid, f"no '## {qid}' block"))
            continue
        has = b["facts"] or b["unknown"] or b["keep"] or b["rows"] or b["bullets"] or b["answer"] or b["search"]
        if not has:
            findings.append(_f("ERROR", "EMPTY_ANSWER", qid, "no Facts, Rows, Bullets, Unknown, Keep or Search"))
        for fact in b["facts"]:
            if not fact["ids"]:
                findings.append(_f("ERROR", "FACT_NO_EVIDENCE", qid, f"a fact cites no evidence ID: {fact['text'][:80]}"))
            if fact["basis"] not in BASES:
                findings.append(_f("ERROR", "BAD_BASIS", qid, f"basis must be one of {', '.join(BASES)}: {fact['line'][:90]}"))
            if q["kind"] in ("requirement", "narrative", "findings") and _IP.search(fact["text"]):
                findings.append(_f("WARN", "IP_IN_PROSE", qid, f"address in a prose fact: use the host name if one is known (fine where none was found): {fact['text'][:80]}"))
        cited = {i.upper() for fact in b["facts"] for i in fact["ids"]}
        cited |= {i.upper() for row in b["rows"] for c in row for i in _EID.findall(c)}
        cited |= {i.upper() for x in b["bullets"] for i in _EID.findall(x)}
        for i in sorted(cited):
            if matrix and i not in matrix:
                findings.append(_f("ERROR", "UNKNOWN_EVIDENCE", qid, f"{i} is not in the evidence matrix"))
            elif allowed and i not in allowed:
                findings.append(_f("ERROR", "EVIDENCE_NOT_ON_CARD", qid,
                                   f"{i} was not on the card; ask for it with 'Search:' or append it to the matrix first"))
        for fact in b["facts"]:
            hosts = set(_HOST.findall(fact["scope"])) | set(_HOST.findall(fact["text"]))
            if not hosts or not matrix:
                continue
            seen = " ".join((matrix.get(i.upper(), {}).get("claim", "") + " " +
                             matrix.get(i.upper(), {}).get("evidence_excerpt", "") + " " +
                             matrix.get(i.upper(), {}).get("source_title", "")) for i in fact["ids"])
            outside = sorted(h for h in hosts if h not in seen)
            if outside:
                findings.append(_f("ERROR", "SCOPE_OUTSIDE_EVIDENCE", qid,
                                   f"{', '.join(outside)} named but not in the cited evidence ({', '.join(fact['ids'])})"))
        if q["kind"] == "requirement" and b["search"] and not b["facts"]:
            pass                                   # waiting for the searched evidence
        elif q["kind"] == "requirement":
            if b["keep"] and not b["rating"]:
                pass
            elif b["rating"] not in ratings:
                findings.append(_f("ERROR", "RATING_INVALID", qid, f"rating '{b['rating']}' is not one of {', '.join(ratings)}"))
            if b["rating"] and not b["rating_reason"]:
                findings.append(_f("ERROR", "RATING_NO_REASON", qid, "a rating needs a 'Rating reason:'"))
            if not b["facts"] and not b["keep"] and b["rating"] not in ("Not Applicable",):
                findings.append(_f("ERROR", "REQUIREMENT_NO_FACTS", qid, "a current state needs at least one fact"))
        if q["kind"] in ("observation", "register") and b["rows"]:
            want = [c.strip().lower() for c in q.get("columns", [])]
            header, data = b["rows"][0], b["rows"][1:]
            if [c.lower() for c in header] != want:
                findings.append(_f("ERROR", "COLUMNS", qid, f"header must be | {' | '.join(q.get('columns', []))} |"))
            for r in data:
                if len(r) != len(want):
                    findings.append(_f("ERROR", "ROW_WIDTH", qid, f"row has {len(r)} cells, the table has {len(want)}: {' | '.join(r)[:80]}"))
            if not data:
                findings.append(_f("ERROR", "NO_ROWS", qid, "Rows: has a header but no rows"))
    for qid in sheet:
        if qid not in qs:
            findings.append(_f("WARN", "EXTRA_BLOCK", qid, "this question is not on the card"))
    errors = [x for x in findings if x["level"] == "ERROR"]
    status = "NEEDS_SEARCH" if searches and not errors else "ERROR" if errors else "OK"
    return {"status": status, "errors": len(errors), "warnings": len(findings) - len(errors),
            "findings": findings, "searches": searches}


def errors_text(res: dict) -> str:
    return "\n".join(f"- {x['level']} {x['code']} {x['question'] or ''}: {x['message']}" for x in res["findings"])


# ---------------------------------------------------------------- render

def _sentence(fact: dict) -> str:
    t = fact["text"].strip()
    return t if t.endswith((".", "!", "?")) else t + "."


_EID_PAREN = re.compile(r"\s*\((?:E-\d+(?:\s*,\s*)?)+\)")


def no_ids(s: str) -> str:
    """Document text never carries evidence IDs: they stay in Facts, Why and the Fact audit."""
    s = _EID_PAREN.sub("", s)
    s = re.sub(r"\s*\bE-\d+\b", "", s)
    return re.sub(r"\s+([;,.|])", r"\1", s).strip()


def _quote(s: str, n: int = 90) -> str:
    s = " ".join((s or "").split()).replace('"', "'")
    return s[:n]


def render_records(sheet: dict[str, dict], card: dict, node: dict, section: str, start: int) -> dict:
    """Change-file records for a valid sheet. Returns {records: [markdown], open: [...], keep: [...],
    scaffold: [...], audit: [...]}. Anchors come from the document spec node."""
    recs, open_q, keep, scaffold, audit = [], [], [], [], []
    n = start
    parts = node["parts"]

    def record(title, where, current, facts, text, why, note):
        nonlocal n
        eid = f"S{section}-E{n}"
        n += 1
        fl = "\n".join(facts) if facts else "- (no facts: see Why)"
        recs.append(f"### {eid} - {title}\n\n**Where:** `{where}` -- currently: \"{_quote(current)}\"\n\n**Do:** Replace\n\n"
                    f"**Facts:**\n\n{fl}\n\n**Text:**\n\n" + "\n".join("> " + x for x in text.splitlines()) +
                    f"\n\n**Why:** {why}\n\n**Note:** {note}\n\n---\n")
        return eid

    for q in card["questions"]:
        b = sheet.get(q["id"])
        if not b:
            continue
        for u in b["unknown"]:
            open_q.append(f"- [{q['id']}] {u}")
        if b["keep"]:
            keep.append(f"- [{q['id']}] {b['keep'] if b['keep'] != 'yes' else 'the current text already answers it'}")
            if q["kind"] != "requirement" or not b["rating"]:
                continue
        if q["kind"] == "comment":
            if b["answer"]:
                keep.append(f"- [{q['id']}] {b['answer']}")
            continue
        p = parts[q["part"]] if q.get("part") is not None and q["part"] < len(parts) else {}
        facts = [f"- [{q['id']}] {f['text']} ({', '.join(f['ids'])}) {{basis: {f['basis']}; scope: {f['scope'] or 'see evidence'}}}"
                 for f in b["facts"]] + [f"- Unknown: {u}" for u in b["unknown"][:1]]
        ids = sorted({i for f in b["facts"] for i in f["ids"]})
        why = (f"Evidence {', '.join(ids)}." if ids else "No evidence row; see the open question.") + (
            f" Rating: {b['rating_reason']}" if b["rating_reason"] else "")
        if q["kind"] == "requirement":
            req = next((r for r in p.get("requirements", []) if r["id"] == q["req_id"]), None)
            if not req:
                continue
            observed = " ".join(_sentence(f) for f in b["facts"]) or "Not Applicable to the system in scope."
            if b["unknown"]:
                observed += f" Not established: {b['unknown'][0].rstrip('.')}."
            eid = record(f"{q['req_id']} current state and rating", f"{p['table']}-R{req['row']}",
                         (p.get("row_texts") or [""] * req["row"])[req["row"] - 2] if len(p.get("row_texts", [])) >= req["row"] - 1 else q["req_id"],
                         facts, f"Observed: {observed}\nAssessment: {b['rating']}", why,
                         f"Current state and rating of {q['req_id']} from the evidence.")
            audit += [f"| {eid} | {_quote(_sentence(f), 160)} | {', '.join(f['ids'])} | {f['basis']} | {f['scope'] or '-'} |" for f in b["facts"]]
        elif q["kind"] in ("observation", "register"):
            data = b["rows"][1:]
            have = p.get("rows", 0)
            if len(data) > have:
                scaffold.append({"kind": "rows", "table": p["table"], **(p.get("under") or {"heading": node["title"],
                                 "occurrence": 1, "table": 1}), "set_count": len(data)})
            texts = p.get("row_texts", [])
            if have > len(data) and any(not t.startswith("[") for t in texts[len(data):]):
                keep.append(f"- [{q['id']}] rows {len(data) + 1} to {have} of {p.get('label') or p.get('facet') or 'the table'} left as they are")
            for k, row in enumerate(data, start=2):
                eid = record(f"{p.get('label') or p.get('facet') or node['title']}: row {k - 1}", f"{p['table']}-R{k}",
                             texts[k - 2] if k - 2 < len(texts) else "", [f"- [{q['id']}] {' | '.join(row)}"],
                             " | ".join(no_ids(c) for c in row),
                             f"Evidence {', '.join(sorted(set(_EID.findall(' '.join(row))))) or 'see the row'}.",
                             f"Row {k - 1} of {p.get('label') or p.get('facet') or 'the table'} from the evidence.")
        elif q["kind"] == "narrative":
            text = " ".join(_sentence(f) for f in b["facts"])
            if b["unknown"]:
                text += f" Not established: {b['unknown'][0].rstrip('.')}."
            if not text.strip():
                continue
            eid = record(f"{p.get('facet') or node['title']}", p.get("pid", node["hid"] + "-P1"), p.get("current", ""),
                         facts, text, why, f"{p.get('facet') or node['title']} from the evidence.")
            audit += [f"| {eid} | {_quote(_sentence(f), 160)} | {', '.join(f['ids'])} | {f['basis']} | {f['scope'] or '-'} |" for f in b["facts"]]
        elif q["kind"] == "findings":
            holders = [(pid, t) for pid, t in zip(p.get("pids", []), p.get("bullets", []))]
            free = [(pid, t) for pid, t in holders if t.startswith("[")]
            bullets = b["bullets"] or [_sentence(f) for f in b["facts"]]
            if len(bullets) > len(free):
                scaffold.append({"kind": "bullets", "heading": p.get("facet") or node["title"], "occurrence": 1,
                                 "set_count": len(holders) - len(free) + len(bullets)})
            for (pid, cur), text in zip(free, bullets):
                record(f"{node['title']}: finding", pid, cur, facts, no_ids(text), why, f"Finding for {node['title']}.")
    return {"records": recs, "open": open_q, "keep": keep, "scaffold": scaffold, "audit": audit, "next": n}


def render_change_file(sheet: dict[str, dict], card: dict, node: dict, spec: dict, *, app: str, docx_name: str,
                       section: str, start: int, brief: str, existing: str | None = None) -> dict:
    """A new change file, or `existing` with the new records, audit rows, unchanged items and open questions added
    (earlier records are never touched; the brief is replaced by the one from the document)."""
    r = render_records(sheet, card, node, section, start)
    first, last = f"S{section}-E{start}", f"S{section}-E{r['next'] - 1}"
    change_set = f"{first} to {last}" if r["records"] else "none"
    if existing:
        text = merge(existing, r, brief, change_set)
    else:
        parts = [f"# Changes to Current State Assessment - {app}",
                 f"## Section {section} Change Record", "",
                 f"**File reviewed:** {docx_name}",
                 f"**Section:** {section} (subsection {node['number']} {node['title']}, key {node['key']})",
                 f"**Suggested change set:** {change_set}",
                 "**Status:** Proposed changes.",
                 f"**Section key:** {node['key']}", "", "---", "", brief.strip(), "", "---", "", "## Proposed changes", ""]
        parts += r["records"] or ["No changes: every question is answered by the current text or is open.", ""]
        parts += ["", "## Fact audit", "", "| Record | Sentence | Evidence quote | Basis | Scope |", "| --- | --- | --- | --- | --- |"]
        parts += r["audit"] or ["| - | - | - | - | - |"]
        parts += ["", "---", "", "## Items intentionally left unchanged", ""] + (r["keep"] or ["- None."])
        parts += ["", "---", "", "## Open questions", ""] + (r["open"] or ["There are no open questions."])
        text = "\n".join(parts + [""])
    return {"text": text, "records": len(r["records"]), "scaffold": r["scaffold"], "next": r["next"],
            "open": len(r["open"]), "change_set": change_set}


def _section_span(text: str, heading: str) -> tuple[int, int] | None:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, re.M | re.I)
    if not m:
        return None
    nxt = re.search(r"^##\s+\S", text[m.end():], re.M)
    return m.start(), (m.end() + nxt.start()) if nxt else len(text)


def merge(existing: str, r: dict, brief: str, change_set: str) -> str:
    text = existing
    span = _section_span(text, "Section brief")
    if span:
        end = span[1]
        tail = text[span[0]:end]
        cut = tail.find("\n---")
        end = span[0] + cut if cut > 0 else end
        text = text[:span[0]] + brief.strip() + "\n" + text[end:]
    else:
        first = re.search(r"^---\s*$", text, re.M)
        at = first.end() if first else len(text)
        text = text[:at] + "\n\n" + brief.strip() + "\n\n---\n" + text[at:]
    if r["records"]:
        span = _section_span(text, "Proposed changes")
        block = "\n" + "\n".join(r["records"])
        if span:
            text = text[:span[1]].rstrip() + "\n" + block + "\n" + text[span[1]:]
        else:
            text = text.rstrip() + "\n\n## Proposed changes\n" + block
    def add_under(txt: str, heading: str, lines: list[str]) -> str:
        if not lines:
            return txt
        sp = _section_span(txt, heading)
        if not sp:
            return txt.rstrip() + f"\n\n## {heading}\n\n" + "\n".join(lines) + "\n"
        body = txt[sp[0]:sp[1]].rstrip()
        body = re.sub(r"\n(There are no new open questions[^\n]*|There are no open questions\.?|- None\.)\s*$", "", body)
        return txt[:sp[0]] + body + "\n" + "\n".join(lines) + "\n\n" + txt[sp[1]:]
    text = add_under(text, "Fact audit", r["audit"])
    text = add_under(text, "Items intentionally left unchanged", r["keep"])
    text = add_under(text, "Open questions", r["open"])
    text = re.sub(r"^\*\*Suggested change set:\*\*.*$", f"**Suggested change set:** {change_set} (earlier records in this file are kept)",
                  text, count=1, flags=re.M)
    text = re.sub(r"^\*\*Status:\*\*.*$", "**Status:** Proposed changes.", text, count=1, flags=re.M)
    return text


def next_edit_number(reviews: Path, section: str) -> int:
    """The next S<N>-E<n> after every one already used for this section in reviews/."""
    used = [0]
    for f in Path(reviews).glob(f"ChangesCSA_*_Section{section}*.md"):
        used += [int(x) for x in re.findall(rf"\bS{section}-E(\d+)\b", f.read_text(encoding="utf-8", errors="ignore"))]
    return max(used) + 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["validate", "parse", "render"])
    ap.add_argument("sheet", type=Path)
    ap.add_argument("--card", type=Path, required=True)
    ap.add_argument("--matrix", type=Path)
    ap.add_argument("--new-ids", default="", help="validate: evidence IDs appended during this run")
    ap.add_argument("--docx", type=Path, help="render: the working document")
    ap.add_argument("--section", help="render: framework section number (3)")
    ap.add_argument("--change-file", type=Path, help="render: the change file to write (merged when it exists)")
    ap.add_argument("--app", default="")
    a = ap.parse_args(argv)
    sheet = parse(a.sheet.read_text(encoding="utf-8"))
    if a.action == "parse":
        print(json.dumps(sheet, indent=1))
        return 0
    card = json.loads(a.card.read_text(encoding="utf-8"))
    if a.action == "validate":
        res = validate(sheet, card, load_matrix(a.matrix), new_ids={x.strip() for x in a.new_ids.split(",") if x.strip()})
        print(json.dumps(res, indent=1))
        return 0 if res["status"] == "OK" else 1
    from csa_docx import doc_spec, section_card, spec_cli
    spec = spec_cli.load(a.docx)
    node = doc_spec.resolve(spec, card["key"])
    cf = a.change_file
    existing = cf.read_text(encoding="utf-8") if cf and cf.is_file() else None
    start = next_edit_number(cf.parent, a.section) if cf else 1
    out = render_change_file(sheet, card, node, spec, app=a.app, docx_name=a.docx.name if a.docx else "",
                             section=a.section, start=start, brief=section_card.brief_markdown(node, spec), existing=existing)
    if cf and not out["scaffold"]:
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text(out["text"], encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "text"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
