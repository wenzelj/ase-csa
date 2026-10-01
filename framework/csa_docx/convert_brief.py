"""One focused brief per template subsection for `csa convert`.

The evidence and writer agents read only this file about the old document: the subsection's scope,
the old facts mapped to it, the hosts involved, the discovery tables that may hold the same facts and
the evidence already recorded. A brief over its token budget is split by old heading.

    python3 -m csa_docx.convert_brief --work-dir <csa-work> --target 3.4 [--budget 6000]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

from csa_docx import requirement_assign, requirement_audit, scope_map

BLOCKS_JSON = (Path(__file__).resolve().parents[2] / "skills" / "csa-document-template"
               / "references" / "template-blocks.json")

_LEGACY_ID = re.compile(r"legacy\s+(L-\d+)")


def _template_title(target: str) -> str | None:
    """Template heading of a target that is not a 3.x domain."""
    try:
        blocks = json.loads(BLOCKS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for m in blocks.get("migration", []):
        if m.get("number") == target:
            return m.get("heading")
    for key in ("glossary", "discovery_required", "coverage"):
        if blocks.get(key, {}).get("number") == target:
            return blocks[key].get("heading")
    if target == "2.1":
        return blocks.get("executive_summary", {}).get("heading")
    return None


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _legacy_line(block: dict) -> str:
    text = block.get("text", "")
    if block.get("kind") == "table_row":
        header, cells = block.get("header") or [], block.get("cells") or []
        if header and len(header) == len(cells):
            text = "; ".join(f"{h}: {c}" for h, c in zip(header, cells))
    return f"- `{block['id']}` {text}".rstrip()


def _cell(v: str) -> str:
    return (v or "").replace("|", "/").strip()


def _hosts_part(work_dir: Path, legacy_text: str) -> list[str]:
    path = work_dir / "hosts" / "hosts.csv"
    if not path.is_file():
        return ["No host register."]
    rows = [r for r in _read_csv(path) if not (r.get("in_scope") or "").strip()]
    lowered = legacy_text.lower()
    named = [r for r in rows if (r.get("host") or "").strip() and r["host"].strip().lower() in lowered]
    chosen = named or rows
    if not chosen:
        return ["No hosts listed."]
    out = ["| Host | Role | Site |", "| --- | --- | --- |"]
    out += [f"| {_cell(r.get('host'))} | {_cell(r.get('role'))} | {_cell(r.get('site'))} |" for r in chosen]
    return out


def _term_variants(terms: list[str]) -> list[str]:
    out = set()
    for t in terms:
        out.add(t.lower())
        out.add(t.lower().replace(" ", "_"))
    return sorted(out)


def _discovery_part(work_dir: Path, domain: dict | None) -> list[str]:
    if domain is None:
        return ["See csa index tables."]
    path = work_dir / "discovery-index.sqlite"
    if not path.is_file():
        return ["No discovery index."]
    variants = _term_variants(domain.get("signal_terms", []))
    if not variants:
        return ["No matching tables."]
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            names = [r[0] for r in con.execute("SELECT DISTINCT table_name FROM rows") if r[0]]
            hits = []
            for name in sorted(names):
                hay = [name.lower()]
                for (data,) in con.execute("SELECT data FROM rows WHERE table_name = ? LIMIT 50", (name,)):
                    try:
                        obj = json.loads(data)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(obj, dict):
                        hay += [str(k).lower() for k in obj]
                if any(v in h or v.replace("_", " ") in h.replace("_", " ") for v in variants for h in hay):
                    hits.append(name)
        finally:
            con.close()
    except sqlite3.Error:
        return ["Index not readable."]
    return [f"- `{n}`" for n in hits] or ["No matching tables."]


def _evidence_part(work_dir: Path, ids: set[str]) -> list[str]:
    out = []
    for r in _read_csv(work_dir / "evidence-matrix.csv"):
        if any(m in ids for m in _LEGACY_ID.findall(r.get("gap_or_action") or "")):
            out.append(f"- {r.get('evidence_id', '')} ({r.get('status', '')}) {r.get('claim', '')}".rstrip())
    return out or ["None yet."]


def _not_found_part(work_dir: Path) -> list[str]:
    out = [f"- {r.get('evidence_id', '')} {r.get('claim', '')} (searched: {r.get('source_title', '')})"
           for r in _read_csv(work_dir / "evidence-matrix.csv")
           if (r.get("status") or "").upper() == "NOT_FOUND"]
    return out or ["None."]


def _tokens(text: str) -> int:
    return len(text) // 4


_GROUPS = (("observed", "Observed"), ("gap", "Gaps and qualifiers"),
           ("consequence", "Consequences"), ("design", "Design intent"))
_MAX_CLUSTERS = 40


def _load_facts(work_dir: Path) -> list[dict]:
    path = work_dir / "legacy" / "facts.jsonl"
    if not path.is_file():
        return []
    facts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            f = json.loads(line)
            ids = f.get("req_ids")
            if isinstance(ids, str):
                f["req_ids"] = [i for i in ids.split(";") if i]
            facts.append(f)
    return facts


def _cluster_line(members: list[dict]) -> str:
    first = members[0]
    fids = ", ".join(m["fact_id"] for m in members)
    lids = ", ".join(dict.fromkeys(m["legacy_id"] for m in members))
    line = f"- `{first['cluster']}` {first['text']} ({fids}; {lids})"
    if any(m.get("absolute") for m in members):
        line += " [absolute]"
    if any(m.get("not_evidence") for m in members):
        line += " [not evidence: check]"
    q = next((m["qualifier"] for m in members if m.get("qualifier")), "")
    if q:
        line += f" [qualifier: {q}]"
    return line


def _requirement_part(req: dict, facts: list[dict], tables: dict[str, int], matrix: list[dict]) -> tuple[str, int]:
    mine = [f for f in facts if (f.get("req_ids") or [""])[0] == req["req_id"]]
    matched = {t: n for t, n in tables.items()
               if req["index_tables"].strip() and re.search(req["index_tables"], t, re.I)}
    table_line = ", ".join(f"{t} ({n} host{'s' if n != 1 else ''})" for t, n in sorted(matched.items())) \
        or "none captured"
    lines = [f"### {req['req_id']} {req['requirement']}", "",
             f"- **Answer from:** {req['answer_from']}",
             f"- **Not evidence for:** {req['not_evidence_for'] or 'nothing listed'}",
             f"- **Discovery Information aspects:** {req['discovery_aspects']}",
             f"- **Discovery tables:** {table_line}", "", "#### Candidate facts", ""]

    clusters: dict[str, list[dict]] = {}
    for f in mine:
        if f["stype"] in dict(_GROUPS):
            clusters.setdefault(f["cluster"], []).append(f)
    ranked = sorted(clusters.values(), key=lambda m: -len(m))
    shown = ranked[:_MAX_CLUSTERS]
    keep = {id(m) for m in shown}
    n_lines = 0
    for stype, label in _GROUPS:
        group = [m for m in clusters.values() if id(m) in keep and m[0]["stype"] == stype]
        if group:
            lines += [f"**{label}**", ""] + [_cluster_line(m) for m in group] + [""]
            n_lines += len(group)
    if not n_lines:
        lines += ["None found in the previous assessment.", ""]
    if len(ranked) > len(shown):
        lines += [f"- ... {len(ranked) - len(shown)} more clusters in legacy/facts.csv", ""]
    recs = sum(1 for f in mine if f["stype"] == "recommendation")
    if recs:
        lines += [f"- Recommendations left out: {recs} (see convert/parked.md)", ""]

    ids = {f["legacy_id"] for f in mine}
    ev = [f"- {r.get('evidence_id', '')} ({r.get('status', '')}) {r.get('claim', '')}".rstrip()
          for r in matrix if any(m in ids for m in _LEGACY_ID.findall(r.get("gap_or_action") or ""))]
    lines += ["#### Evidence already in the matrix", ""] + (ev or ["None yet."]) + [""]
    return "\n".join(lines), n_lines


def _elsewhere_part(target: str, facts: list[dict], reqs_by_id: dict[str, dict], domains: dict) -> list[str]:
    counts: dict[str, int] = {}
    for f in facts:
        ids = f.get("req_ids") or []
        if not ids or f["stype"] not in dict(_GROUPS):
            continue
        first_part = (f.get("path") or "").split(" > ")[0]
        if not (f.get("old_target") == target or target in scope_map.legacy_hosts(first_part, domains)):
            continue
        req = reqs_by_id.get(ids[0])
        if req and req["domain"] != target:
            counts[ids[0]] = counts.get(ids[0], 0) + 1
    return [f"- {rid} ({reqs_by_id[rid]['domain']}): {n}" for rid, n in counts.items()] or ["None."]


def _requirement_brief(work_dir: Path, target: str, budget_tokens: int, domain: dict, domains: dict,
                       facts: list[dict], reqs: list[dict]) -> dict:
    all_reqs = requirement_assign.load_requirements()
    reqs_by_id = {r["req_id"]: r for r in all_reqs}
    tables = requirement_audit._index_tables(work_dir)
    matrix = _read_csv(work_dir / "evidence-matrix.csv")

    parts, n_lines = [], 0
    for r in reqs:
        text, n = _requirement_part(r, facts, tables, matrix)
        parts.append(text)
        n_lines += n
    req_ids = [r["req_id"] for r in reqs]
    if not any((f.get("req_ids") or [""])[0] in req_ids for f in facts):
        return {"status": "EMPTY", "target": target, "files": [], "blocks": 0, "mode": "requirement"}

    head = "\n".join([f"# Conversion brief: {target} {domain['title']}", "", "## Scope", "",
                      f"- **Requirements:** {domain['requirements']}",
                      f"- **Must explain:** {domain['must_explain']}",
                      f"- **Owns:** {domain['owns']}",
                      f"- **Not here:** {domain['not_here']}", "", "## Requirements", ""])
    candidate_text = "\n".join(parts)
    tail = "\n".join(["", "## Facts that belong elsewhere", ""] + _elsewhere_part(target, facts, reqs_by_id, domains)
                     + ["", "## Hosts", ""] + _hosts_part(work_dir, candidate_text)
                     + ["", "## Discovery tables", ""] + _discovery_part(work_dir, domain)
                     + ["", "## Answer plan", "",
                        f"Write convert/{target}/answer-plan.csv (columns: legacy_ids, req_id, statement_type, fact, "
                        "evidence_scope, destination, confidence, transformation, gap_generated) and check it with "
                        "python3 -m csa_docx.answer_plan.", ""])

    base = _tokens(head + tail)
    files_parts: list[list[str]] = []
    used = 0
    for part in parts:
        cost = _tokens(part) + 1
        if files_parts and used + cost <= budget_tokens - base:
            files_parts[-1].append(part)
            used += cost
        else:
            files_parts.append([part])
            used = cost

    out_dir = work_dir / "convert" / target
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("brief*.md"):
        old.unlink()
    files, tokens = [], []
    for n, ps in enumerate(files_parts, start=1):
        text = head + "\n".join(ps) + tail
        f = out_dir / ("brief.md" if n == 1 else f"brief-{n}.md")
        f.write_text(text, encoding="utf-8")
        files.append(str(f))
        tokens.append(_tokens(text))
    return {"status": "OK", "target": target, "files": files, "blocks": n_lines, "split": len(files) > 1,
            "tokens": tokens, "mode": "requirement", "requirements": req_ids}


def build_brief(work_dir: Path, target: str, *, budget_tokens: int = 6000,
                domains: dict | None = None, block_mode: bool = False) -> dict:
    """``block_mode`` forces the block brief (the old blocks as they stand) even when facts exist; `csa move` uses it."""
    work_dir = Path(work_dir)
    if domains is None:
        try:
            domains = scope_map.load()
        except (ValueError, OSError):
            domains = {}
    facts = [] if block_mode else _load_facts(work_dir)
    if domains.get(target) and any("req_ids" in f for f in facts):
        reqs = [r for r in requirement_assign.load_requirements() if r["domain"] == target]
        if reqs:
            return _requirement_brief(work_dir, target, budget_tokens, domains[target], domains, facts, reqs)

    rows = [r for r in _read_csv(work_dir / "legacy" / "map.csv")
            if r.get("target") == target and r.get("job") in ("convert", "context")]
    if not rows:
        return {"status": "EMPTY", "target": target, "files": [], "blocks": 0, "mode": "block"}

    blocks = {}
    bpath = work_dir / "legacy" / "blocks.jsonl"
    if bpath.is_file():
        for line in bpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                b = json.loads(line)
                blocks[b["id"]] = b

    domain = domains.get(target)
    title = domain["title"] if domain else (_template_title(target) or target)

    # Part 3 groups: old path -> lines, in block order.
    groups: dict[str, list[str]] = {}
    ids: set[str] = set()
    for r in rows:
        b = blocks.get(r["id"])
        if not b:
            continue
        ids.add(r["id"])
        groups.setdefault(r["path"], []).append(_legacy_line(b))
    all_lines = "\n".join(line for g in groups.values() for line in g)

    head = [f"# Conversion brief: {target} {title}", "", "## Scope", ""]
    if domain:
        head += [f"- **Requirements:** {domain['requirements']}",
                 f"- **Must explain:** {domain['must_explain']}",
                 f"- **Owns:** {domain['owns']}",
                 f"- **Not here:** {domain['not_here']}"]
    else:
        head += [f"Run `csa scope {target}` for this subsection's scope."]
    head += [""]
    tail = ["", "## Hosts", ""] + _hosts_part(work_dir, all_lines)
    tail += ["", "## Discovery tables", ""] + _discovery_part(work_dir, domain)
    tail += ["", "## Evidence already in the matrix", ""] + _evidence_part(work_dir, ids)
    if target == "8":
        tail += ["", "## Not found in any source", ""] + _not_found_part(work_dir)
    tail += [""]

    head_text, tail_text = "\n".join(head), "\n".join(tail)
    group_texts = ["\n".join([f"### {path}", ""] + lines + [""]) for path, lines in groups.items()]

    # Pack groups into files within the budget; an oversize group goes alone.
    base = _tokens(head_text + "\n## Legacy content\n\n" + tail_text)
    files_groups: list[list[str]] = []
    used = 0
    for g in group_texts:
        cost = _tokens(g) + 1
        if files_groups and used + cost <= budget_tokens - base:
            files_groups[-1].append(g)
            used += cost
        else:
            files_groups.append([g])
            used = cost
    if not files_groups:
        files_groups = [[]]

    out_dir = work_dir / "convert" / target
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("brief*.md"):
        old.unlink()
    files, tokens = [], []
    for n, gs in enumerate(files_groups, start=1):
        text = head_text + "\n## Legacy content\n\n" + "\n".join(gs) + tail_text
        f = out_dir / ("brief.md" if n == 1 else f"brief-{n}.md")
        f.write_text(text, encoding="utf-8")
        files.append(str(f))
        tokens.append(_tokens(text))
    return {"status": "OK", "target": target, "files": files,
            "blocks": sum(len(g) for g in groups.values()),
            "split": len(files) > 1, "tokens": tokens, "mode": "block"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the conversion brief for one template subsection.")
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--budget", type=int, default=6000)
    a = ap.parse_args(argv)
    print(json.dumps(build_brief(a.work_dir, a.target, budget_tokens=a.budget), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
