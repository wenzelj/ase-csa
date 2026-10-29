"""Questions, brief and section card for one node of the document spec.

The questions come from the document: each requirement row asks for the current state and a rating
against its requirement text; each observation table and register asks for one row per thing with the
table's columns; each placeholder paragraph asks its bracket text; the optional note under a table asks
for one fact the rows cannot show, or None (note_candidates offers what the data shows); each findings list
asks for one bullet per finding; each reviewer comment under the heading is a C question. The scope map's Must explain and
Not here are added when the node's requirement family or heading matches a scope-map domain; a section
with no entry still gets every question from its own tables.

The section card is the AI's whole input for one node: the questions, the requirement text, columns,
guidance, reviewer comments, the current text, the scope extras, background knowledge (passages from the
knowledge folders and the system model, never evidence: see knowledge.py), one worked example for its kind and the evidence pack
(candidate evidence per question, gathered before the AI starts).

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


_ISOLATION = re.compile(r"\b(drawbridge|isolat\w*)\b", re.I)


def isolation_question(topic: str) -> str:
    """The Drawbridge Impact question, asked about the system's functions rather than the infrastructure
    capability: "DNS is lost" is not an answer, "Reveloc loses its database, so alerts stop" is."""
    return (f"Which of the system's functions depend on {topic}? During an isolation event, which of those functions "
            "stop, which keep working (and why), and what does that mean for operations? Has any fallback been tested "
            "or documented?")


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
                                    f"requirement, what evidence-backed story explains that state, and how does it rate "
                                    f"({ratings}; Not Applicable needs a justification)?"})
        elif k == "observation":
            cols = p.get("columns") or []
            prof = _topic_profile(node)
            if prof:
                shows = ", ".join(c["label"].lower() for c in prof["columns"])
                text = (f"{where}: the role table above this table already shows {_topic(node)} per role group "
                        f"({shows}). Which points about {_topic(node)} are not per host: what exists or is missing across "
                        f"the system, and what was not tested? One row per point with "
                        f"{', '.join(cols[1:]) or 'what was observed'}. Never repeat a host's setting from the role table.")
            else:
                text = (f"{where}: which aspects of {_topic(node)} were observed? One row per aspect with "
                        f"{', '.join(cols[1:]) or 'what was observed'}.")
            out.append({"kind": "observation", "part": i, "columns": cols, "text": text})
        elif k == "register":
            cols = p.get("columns") or []
            first = cols[0] if cols else "item"
            out.append({"kind": "register", "part": i, "columns": cols,
                        "text": f"{where}: one row per {first.lower()}, with {', '.join(cols[1:]) or 'its details'}."})
        elif k == "narrative":
            facet = p.get('facet') or _topic(node)
            ask = p.get('question') or 'one paragraph'
            if _ISOLATION.search(f"{facet} {ask}"):
                ask = isolation_question(_topic(node))
            out.append({"kind": "narrative", "part": i, "text": f"{facet}: {ask}"})
        elif k == "note":
            # The optional note under a table: one or two sentences for a fact the rows cannot show, or None
            # (the placeholder is then removed). The rows of the table above it are carried so the check can
            # refuse a note that only repeats one of them (NOTE_REPEATS_ROW).
            table = next((x for x in reversed(node["parts"][:i]) if x.get("columns")), None)
            tname = (table or {}).get("label") or (table or {}).get("facet") or where
            out.append({"kind": "note", "part": i, "table_rows": list((table or {}).get("row_texts") or []),
                        "text": f"{where}: the optional note under the {tname} table. Is there one fact about "
                                f"{_topic(node)} that the table rows cannot show: a host or role group that differs "
                                "from the others in its group, sources that disagree, or evidence that covers fewer "
                                "hosts than the table? Write it in one or two sentences from the evidence (no rating, "
                                "risk or recommendation, and never a repeat of a row), or write 'None: <why>' and the "
                                "placeholder is removed."})
        elif k == "findings":
            holders = [b for b in p.get("bullets", []) if doc_spec.is_placeholder(b)]
            hint = holders[0].strip("[] ") if holders else "finding"
            out.append({"kind": "findings", "part": i,
                        "text": f"{p.get('facet') or _topic(node)}: one bullet per {hint.lower()}"
                                + (" (keep the standard bullets)" if len(holders) < len(p.get("bullets", [])) else "") + "."})
    # Notes are numbered after the other questions (still listed in document order), so adding the note
    # question never renumbers the blocks earlier answers and the fact store were keyed by.
    for n, q in enumerate([q for q in out if q["kind"] != "note"] + [q for q in out if q["kind"] == "note"], start=1):
        q["id"] = f"B{n}"
    for n, c in enumerate(node.get("comments", []), start=1):
        out.append({"id": f"C{n}", "kind": "comment", "part": None,
                    "text": f"Reviewer comment ({c['author'] or 'unknown'}): \"{' '.join(c['text'].split())[:240]}\""})
    return out


def count_hint(fact: str) -> str:
    """' [restate without "nine captured hosts": ...]' when a fact the card hands on counts hosts, else ''.
    Old answers were written before NO_TOTALS; the agent keeps their evidence but must not copy the count."""
    from csa_docx.answer_sheet import totals_in
    hit = totals_in(fact or "")
    return f' [restate without "{hit}": name the role group or the hosts]' if hit else ""


def _topic_profile(node: dict) -> dict | None:
    """The topic-table profile for this subsection's heading (references/topic-tables), if there is one."""
    try:
        from csa_docx import topic_tables
        return topic_tables.profile_for(node.get("title", ""))
    except (ImportError, OSError, ValueError):
        return None


def role_table(node: dict, workspace: Path | None) -> dict | None:
    """The role table topic_tables.py builds for this subsection from the captures (None without a profile or data)."""
    if not workspace or not _topic_profile(node):
        return None
    from csa_docx import topic_tables
    ts = [t for t in topic_tables.build_all(Path(workspace) / "csa-work", node["title"], node.get("key", "")) if t.get("status") == "OK"]
    return ts or None


def _role_table_lines(ts) -> list[str]:
    ts = ts if isinstance(ts, list) else [ts]
    t = ts[0]
    split = any(x.get("requirement") for x in ts)
    title = "Requirement evidence tables" if split else "Role table"
    placement = ("The framework puts each table directly after its matching SEP story under Discovery Information. "
                 if split else
                 "The framework puts this table under Discovery Information, above the Aspect table, every time this subsection is written. ")
    out = ["", f"## {title} (built by the framework from the captures)", "",
           placement + "It is the detailed discovery evidence for this topic. Keep the SEP story as the synthesis and "
           "do not recreate these tables in an Aspect block (ROLE_TABLE_REPEAT). Write about hosts by these role groups, never by a number of hosts "
           "(NO_TOTALS). Use it in the Current State and Drawbridge Impact text, citing the evidence rows for the same facts.",
           "", topic_markdown(ts)]
    if t.get("gaps"):
        out += ["", "Already raised as Discovery Required by the framework (do not write these as QUESTION: lines):"]
        out += [f"- {g['dr_id']}: {g['text']}" for g in t["gaps"]]
    return out


def topic_markdown(t: dict) -> str:
    from csa_docx import topic_tables
    return topic_tables.markdown(t)


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
        parent = next((n for n in nodes if n.get("path") == node.get("parent")), None)
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


def _file_rows(work: Path, rel: str, encoding: str = "utf-8") -> list[dict]:
    """The rows of csa-work/<rel> as dicts: from the system model store when it is current for that file (modelstore.rows),
    else from the file itself. [] when the file is missing."""
    import csv
    from csa_docx import modelstore
    got = modelstore.rows(work, rel)
    if got is not None:
        return got
    f = Path(work) / rel
    if not f.is_file():
        return []
    with f.open(newline="", encoding=encoding) as fh:
        return list(csv.DictReader(fh))


def _matrix_rows(workspace: Path) -> list[dict]:
    """The evidence the card may offer: verified evidence only (evidence_live.get_verified_evidence)."""
    from csa_docx import evidence_live
    return evidence_live.get_verified_evidence(Path(workspace) / "csa-work" / "evidence-matrix.csv")


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


MAX_FRAME_TERMS = 6
FRAME_HITS_PER_TERM = 2


def frame_terms(node: dict, qs: list[dict]) -> dict[str, list[str]]:
    """{question id: [index search terms]} from the topic frame's slots (``"search"``: the words the captures and
    documents use for what the slot asks, such as a service, a policy key or a tool). A requirement question gets the
    terms of the slots that name its requirement, every other question the terms of all slots. Empty without a frame."""
    from csa_docx import topic_frames
    raw = topic_frames.frame_for(node.get("title", "")) or {}
    out: dict[str, list[str]] = {}
    for q in qs:
        if q["kind"] == "comment":
            continue
        terms: list[str] = []
        for s in raw.get("slots", []):
            if q["kind"] != "requirement" or q.get("req_id") in s.get("requirements", []):
                terms += [x for x in s.get("search", []) if x not in terms]
        if terms:
            out[q["id"]] = terms[:MAX_FRAME_TERMS]
    return out


def _index_hits(workspace: Path, term: str, exclude: tuple[str, ...], cache: dict) -> list[dict]:
    """Discovery index hits for one frame search term (cached per card): the term is chosen for its topic, so no
    word-overlap filter is applied. Each hit is a candidate only, never evidence."""
    if term not in cache:
        script = _skills() / "csa-discovery-index" / "scripts" / "discovery_index.py"
        res = _run([sys.executable, str(script), "--workspace", str(workspace), "search", term,
                    "--limit", str(FRAME_HITS_PER_TERM), "--per-file", "1"])
        hits = (res or {}).get("results", []) if (res or {}).get("status") == "OK" else []
        cache[term] = [h for h in hits if not any(e and e in h.get("rel_path", "") for e in exclude)]
    return cache[term]


def evidence_pack(node: dict, qs: list[dict], workspace: Path | None, extra_searches: dict | None = None,
                  exclude: tuple[str, ...] = (), skip: frozenset = frozenset(), terms: dict | None = None) -> dict:
    """{question id: {"rows", "cut", "candidates", "searched"}}, gathered before the AI starts.

    Rows recorded for this section (the matrix `section` or `csa_area` names its topic) come first, ranked by
    status and by the words they share with the question; matrix lookups add rows recorded elsewhere; index
    hits not yet in the matrix are offered as unverified candidates only when they are about the question.
    Rejected rows are never offered. Capped per question; what is cut is listed by ID. Rows in ``skip`` (the ones
    the analysis frame already cites, with their findings, on the same card) are not repeated, so they take no slot."""
    pack: dict[str, dict] = {}
    if not workspace:
        return pack
    try:
        from csa_docx import gap_lookup
    except ImportError:
        gap_lookup = None
    rows = _matrix_rows(workspace)
    offered = {r["evidence_id"].upper() for r in rows}
    rejected = _rejected(workspace)
    cache: dict = {}
    topic = _norm(node["title"])
    own = [r for r in rows if r["evidence_id"].upper() not in rejected and r["evidence_id"].upper() not in skip and (
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
                if m["evidence_id"].upper() in rejected or m["evidence_id"] in scored or m["evidence_id"].upper() in skip:
                    continue
                if m["evidence_id"].upper() not in offered:
                    continue           # the lookup also returns searches that found nothing, disagreements and unread candidates
                if m.get("score", 0) < 0.4 and query not in (extra_searches or {}).get(q["id"], []):
                    continue
                scored[m["evidence_id"]] = (_STATUS_RANK.get(m.get("status", ""), 5) + 1, -int(10 * m.get("score", 0)), m)
        ranked = [v[2] for v in sorted(scored.values(), key=lambda v: (v[0], v[1]))]
        kept = [_row(m) for m in ranked[:MAX_ROWS_PER_QUESTION]]
        cut = [m["evidence_id"] for m in ranked[MAX_ROWS_PER_QUESTION:]]
        cands = []
        for term in (terms or {}).get(q["id"], []):        # the frame's own words for this question's slots
            searched.append(f"index '{term}'")
            for h in _index_hits(workspace, term, exclude, cache):
                cands.append({"source": h.get("source_title", "")[:160], "where": h.get("page_or_location", ""),
                              "excerpt": " ".join(h.get("evidence_excerpt", "").split())[:EXCERPT]})
        if gap_lookup is not None and not (terms or {}).get(q["id"]):
            for query in [f"{node['title']} {' '.join(sorted(qwords)[:5])}"] + (extra_searches or {}).get(q["id"], []):
                hits, ran, _ = gap_lookup._index_stage(workspace, query, exclude)
                searched += [f"index '{x}'" for x in ran[:2]]
                for h in hits[:3]:
                    cands.append({"source": h.get("source_title", "")[:160], "where": h.get("page_or_location", ""),
                                  "excerpt": " ".join(h.get("evidence_excerpt", "").split())[:EXCERPT]})
        if skip:
            searched.append(f"{len(skip)} rows the analysis frame cites are on the card with its findings, not repeated here")
        pack[q["id"]] = {"rows": kept, "cut": cut, "candidates": cands[:4 if (terms or {}).get(q["id"]) else 3],
                         "searched": searched}
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


def facts_to_keep(node: dict, workspace: Path | None) -> list[dict]:
    """Capture-backed facts this subsection's applied answers have stated (from the fact store), newest wording
    per question and capture evidence: [{question, fact, evidence_ids, capture_ids}]. A re-answer keeps each, or
    says why it no longer applies (``Dropped:``); the answer-sheet check enforces it (CAPTURE_DROPPED)."""
    if not workspace:
        return []
    from csa_docx import fact_store
    from csa_docx.answer_sheet import source_class
    work = Path(workspace) / "csa-work"
    rows = {r["evidence_id"].upper(): r for r in _matrix_rows(workspace)}
    rejected = _rejected(workspace)
    latest: dict[tuple, dict] = {}
    for f in fact_store._read(work):
        if f.get("section") != node["key"] or f.get("basis") == "background":
            continue
        caps = sorted(i for i in f.get("evidence_ids", []) if (rows.get(i.upper()) or {}).get("status") == "VERIFIED"
                      and source_class(rows.get(i.upper())) == "capture" and i.upper() not in rejected)
        if not caps:                 # a fact keeps the evidence that is verified; with none of its capture rows left it is not carried
            continue
        k = (f.get("question", ""), tuple(caps))
        if k not in latest or f.get("added", "") >= latest[k].get("added", ""):
            latest[k] = {"question": f.get("question", ""), "fact": f["fact"],
                         "evidence_ids": [i for i in f["evidence_ids"] if i.upper() in rows],
                         "capture_ids": caps, "added": f.get("added", ""), "kind": f.get("kind", "fact")}
    # a capture set already covered by a newer fact of the same question is not asked for twice
    out = sorted(latest.values(), key=lambda x: (x["question"], x["added"]), reverse=True)
    seen: dict[str, set] = {}
    keep = []
    for x in out:
        have = seen.setdefault(x["question"], set())
        if set(x["capture_ids"]) <= have:
            continue
        have |= set(x["capture_ids"])
        keep.append(x)
    return sorted(keep, key=lambda x: (x["question"], x["capture_ids"]))


def _value_items_in(value: str, low: str) -> bool:
    """True when every named item of a finding's value ("CAcom (C:\\), Music (C:\\Users\\x)") is already in the old fact: the
    fact listed it, so the finding adds nothing that fact denies."""
    items = [i.strip().lower() for i in re.findall(r"(?:^|,\s*)([^,(]+?)\s*(?:\(|,|$)", value) if i.strip()]
    return bool(items) and all(i in low for i in items)


def filter_keep(keep: list[dict], fr: dict | None) -> tuple[list[dict], list[dict]]:
    """(keep, correct) against the subsection's analysis frame. Keep (enforced by CAPTURE_DROPPED): a fact whose capture
    evidence is one of the frame's findings. Correct: a fact that says a setting has its baseline value ("default and
    administrative shares", "none found") for hosts where the frame found more; it carries the findings it contradicts.
    Any other old fact is not offered: it does not answer this topic's frame. Without a frame, everything is kept."""
    if not fr:
        return keep, []
    from csa_docx import topic_frames
    ids = {i.upper() for i in topic_frames.all_ids(fr)}
    rules = []                       # (baseline phrase, non-baseline findings of the same slot)
    for s in fr.get("slots", []):
        base = [f for f in s["findings"] if f.get("value") and not f.get("requirements")]
        more = [f for f in s["findings"] if f.get("value") and f.get("requirements")]
        for f in base:
            phrase = " ".join(f["value"].lower().split()[:3])
            if phrase and more:
                rules.append((phrase, more))
    kept, correct = [], []
    for k in keep:
        low = k["fact"].lower()
        hit = [f for phrase, more in rules if phrase in low for f in more
               if any(t.lower() in low for t in (f.get("roles") or []) + (f.get("hosts") or []))
               and not _value_items_in(f.get("value") or "", low)]
        if hit:
            correct.append({**k, "contradicts": [{"text": f["text"], "ids": f.get("ids", [])} for f in hit],
                            "phrase": next(ph for ph, more in rules if ph in low and any(f in more for f in hit))})
        elif {i.upper() for i in k["capture_ids"]} & ids:
            kept.append(k)
    return kept, correct


ESTABLISHED_PER_QUESTION = 4


def filter_established(established: dict, pack: dict, fr: dict | None) -> dict:
    """Facts other sections validated, kept only where they touch this topic: their evidence is one of the frame's
    findings, or one of the question's own evidence rows (found by this topic's search, not added as established).
    At most ESTABLISHED_PER_QUESTION per question. The evidence rows of facts left out leave the pack too.
    Without a frame, the facts are only capped."""
    from csa_docx import topic_frames
    frame_ids = {i.upper() for i in topic_frames.all_ids(fr)} if fr else None
    out: dict[str, list[dict]] = {}
    for qid, facts in established.items():
        rows = (pack.get(qid) or {}).get("rows", [])
        own = {r["id"].upper() for r in rows if not r.get("established")}
        touch = own | (frame_ids or set())
        kept = [f for f in facts if frame_ids is None or {i.upper() for i in f["evidence_ids"]} & touch]
        kept = kept[:ESTABLISHED_PER_QUESTION]
        if kept:
            out[qid] = kept
        need = {i.upper() for f in kept for i in f["evidence_ids"]}
        if qid in pack:
            pack[qid]["rows"] = [r for r in rows if not r.get("established") or r["id"].upper() in need]
    return out


def _foreign_absence(fact: dict, rows: dict, key: str) -> bool:
    """True when the fact rests on a NOT_FOUND row recorded for another subsection: an absence found while
    answering one subsection (no fallback for storage) says nothing about another (DNS)."""
    from csa_docx.answer_sheet import _REQ_KEY
    for i in fact.get("evidence_ids", []):
        r = rows.get(i.upper()) or {}
        keys = set(_REQ_KEY.findall(r.get("question") or ""))
        if r.get("status") == "NOT_FOUND" and keys and key.upper() not in keys:
            return True
    return False


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
        found = [f for f in found if not _foreign_absence(f, rows, node["key"])]
        if not found:
            continue
        out[q["id"]] = [{k: f[k] for k in ("fact", "evidence_ids", "section", "question", "basis")} for f in found]
        for f in out[q["id"]]:                      # a fact keeps only the evidence IDs the card may offer
            f["evidence_ids"] = [i for i in f["evidence_ids"] if i.upper() in rows]
        out[q["id"]] = [f for f in out[q["id"]] if f["evidence_ids"]]
        have = {r["id"].upper() for r in pack[q["id"]]["rows"]}
        for f in found:
            for eid in f["evidence_ids"]:
                if eid.upper() not in have and eid.upper() in rows:
                    pack[q["id"]]["rows"].append({**_row(rows[eid.upper()]), "established": True})
                    have.add(eid.upper())
    return out


_HOSTNAME = re.compile(r"\b[A-Z]{3}PRD[A-Z]{3}\d{3}\b")


def host_register(workspace: Path | None) -> dict | None:
    """Captured in-scope hosts grouped by role, plus named-but-not-captured hosts of the system.

    Read from csa-work/hosts/hosts.csv; a missing role is filled from roles.csv (process/service matches).
    Returns {"groups": [{"role", "hosts", "sites"}], "total", "uncaptured": [{"host", "role", "site"}]}."""
    if not workspace:
        return None
    import csv
    d = Path(workspace) / "csa-work" / "hosts"
    hf = d / "hosts.csv"
    if not hf.is_file():
        return None
    rows = _file_rows(d.parent, "hosts/hosts.csv")
    fill: dict[str, str] = {}
    rf = d / "roles.csv"
    if rf.is_file():
        for r in csv.DictReader(rf.open(encoding="utf-8")):
            if r.get("kind") in ("process", "service") and r.get("role"):
                for h in _HOSTNAME.findall(r.get("basis") or ""):
                    fill.setdefault(h, r["role"])
    groups: dict[str, dict] = {}
    uncaptured = []
    for r in rows:
        host = r["host"].strip()
        role = (r.get("role") or "").strip() or fill.get(host, "")
        if not role:
            m = re.search(r"Role '([^']+)'", " ".join(v or "" for v in r.values()))
            role = m.group(1) if m else ""
        site = (r.get("site") or "").strip()
        if (r.get("in_scope") or "").strip() == "peer":
            if role or (r.get("system") or "").strip():
                uncaptured.append({"host": host, "role": (role or "role not recorded"), "site": site})
            continue
        if not (r.get("capture") or "").strip():
            continue
        key = (role or "role not recorded")
        g = groups.setdefault(key.lower(), {"role": key, "hosts": [], "sites": []})
        g["hosts"].append(host)
        if site and site not in g["sites"]:
            g["sites"].append(site)
    gl = sorted(groups.values(), key=lambda g: (-len(g["hosts"]), g["role"]))
    from csa_docx import topic_frames, zones as zones_mod
    zs = zones_mod.for_project(d.parent)
    for g in gl:
        g["hosts"].sort()
        g["zones"] = list(dict.fromkeys(zs.of(h).get("zone", "") or "zone not recorded" for h in g["hosts"]))
    unnamed = []
    unnamed = _file_rows(d.parent, "hosts/addresses.csv")
    return {"groups": gl, "total": sum(len(g["hosts"]) for g in gl), "uncaptured": uncaptured, "unnamed": unnamed,
            "zone_conflicts": topic_frames.zone_conflicts(d.parent)}


def _register_lines(reg: dict) -> list[str]:
    out = ["", "## Host register (captured hosts, grouped by role)", "",
           "Any host table uses one row per role group below, never one row per host. Write about hosts by role group or "
           "by name, never by a number or total of hosts (NO_TOTALS). The zone is the side of the OT boundary the host "
           "is on: it wins over any OT or IT in a role name.", ""]
    for c in reg.get("zone_conflicts") or []:
        out.append(f"- ZONE CONFLICT: {c['text']}")
    for g in reg["groups"]:
        out.append(f"- {g['role']}: {', '.join(g['hosts'])}" + (f"; site: {', '.join(g['sites'])}" if g["sites"] else "")
                   + (f"; zone: {', '.join(g['zones'])}" if g.get("zones") else ""))
    if reg["uncaptured"]:
        out += ["", "Named in the sources for this system but not captured (scope to be confirmed):"]
        for u in reg["uncaptured"]:
            out.append(f"- {u['host']}: {u['role']}" + (f"; site: {u['site']}" if u["site"] else ""))
    un = reg.get("unnamed") or []
    if un:
        # every address several hosts use, then every private address that connects in (a client of the system)
        many = [u for u in un if int(u.get("host_count") or 0) >= 2 and u.get("kind") == "private"]
        inbound = [u for u in un if u not in many and u.get("kind") == "private" and "inbound" in (u.get("directions") or "")]
        shown = (many + inbound)[:30]
        out += ["", f"Peers seen only by address (name not captured; {len(un)} in total, not counted in the hosts above). "
                    "Refer to one by its address and say its name was not captured:"]
        for u in shown:
            ev = (u.get("evidence_ids") or "").split(";")
            out.append(f"- {u['address']} ({u['kind']}): from {u['host_count']} host(s) {u['seen_from'].replace(';', ', ')}; "
                       f"{u['directions']}; ports {u['ports'].replace(';', ', ')}"
                       + (f" ({', '.join(e for e in ev if e)})" if any(ev) else ""))
        if len(un) > len(shown):
            out.append(f"- {len(un) - len(shown)} more (public addresses, or private ones seen outbound from one host): csa hosts unresolved")
    return out


_NOTE_STOP = {"and", "the", "for", "with", "from", "management", "validation", "access", "general", "status"}


def _note_words(s: str) -> set[str]:
    return {w for w in _norm(s).split() if len(w) >= 3 and w not in _NOTE_STOP}


def note_candidates(node: dict, workspace: Path | None, reg: dict | None, rows: list[dict] | None = None,
                    limit: int = 5) -> list[dict]:
    """Facts the optional note under a table could state, worked out from the data, never by the model:
    hosts of one role group that differ on an attribute of this topic (csa-work/hosts/host_facts.csv), an
    attribute of this topic recorded for fewer captured hosts than the register holds, and CONFLICTING
    evidence rows of this topic. Each candidate carries the capture rows that record it, so the note can
    cite them. [{"text", "ids"}]"""
    if not workspace:
        return []
    import csv
    topic = _note_words(node["title"])
    rows = rows if rows is not None else _matrix_rows(workspace)
    rejected = _rejected(workspace)
    live = [r for r in rows if r["evidence_id"].upper() not in rejected]
    out: list[dict] = []

    def ids_for(host: str, value: str) -> list[str]:
        v = value.lower()
        hit = [r["evidence_id"] for r in live if f"_{host}_".lower() in (r.get("source_title") or "").lower()
               and v in ((r.get("claim") or "") + " " + (r.get("evidence_excerpt") or "")).lower()]
        return hit[:1]

    fact_rows = _file_rows(Path(workspace) / "csa-work", "hosts/host_facts.csv")
    role_of = {h: g["role"] for g in (reg or {}).get("groups", []) for h in g["hosts"]}
    if fact_rows and role_of:
        by_attr: dict[str, dict[str, str]] = {}
        for r in fact_rows:
            if r.get("host") in role_of and (r.get("value") or "").strip():
                by_attr.setdefault(r["attribute"], {}).setdefault(r["host"], r["value"].strip())
        for attr, vals in sorted(by_attr.items()):
            if not topic & _note_words(attr.replace("_", " ")) or attr == "dns_resolver: Secondary":
                continue                            # the secondary only mirrors the primary in a two-server list
            label = " ".join(attr.replace("_", " ").replace(":", " ").split()).lower()
            for g in (reg or {}).get("groups", []):
                have = {h: vals[h] for h in g["hosts"] if h in vals}
                count = lambda v: list(have.values()).count(v)
                distinct = sorted(set(have.values()), key=lambda v: (-count(v), v))
                if len(have) < 2 or len(distinct) < 2:
                    continue
                main = distinct[0]
                odd = sorted(h for h, v in have.items() if v != main)
                same = sorted(h for h, v in have.items() if v == main)
                if count(main) == count(distinct[1]):       # no majority: name each value, take no side
                    text = f"{g['role']}: {label} differs between the hosts, " + ", ".join(
                        f"{v} on {', '.join(sorted(h for h, x in have.items() if x == v))}" for v in distinct)
                else:
                    text = (f"{g['role']}: {label} is {main} on {', '.join(same)} but "
                            + ", ".join(f"{have[h]} on {h}" for h in odd))
                ids = {i for h in odd for i in ids_for(h, have[h])}
                ids |= next((set(x) for x in (ids_for(h, main) for h in same) if x), set())
                ids = sorted(ids)
                out.append({"text": text, "ids": ids})
            missing = sorted(set(role_of) - set(vals))
            if missing and len(vals) >= 2:
                out.append({"text": f"{label} is recorded for {len(vals)} of {len(role_of)} captured hosts, "
                                    f"not for {', '.join(missing)}", "ids": []})
    if card_service(node) == "dns":           # the site pattern first: it says more than one role group
        out = _dns_order_candidates(Path(workspace), live) + out
    for r in live:
        if r.get("status") == "CONFLICTING" and topic & _note_words(r.get("section", "") + " " + r.get("csa_area", "").replace("_", " ")):
            out.append({"text": f"sources disagree: {' '.join((r.get('claim') or '').split())[:200]}", "ids": [r["evidence_id"]]})
    return out[:limit]


SHARED_HEAD = "## Shared enterprise services (other applications in the estate)"
SERVICE_NAME = {"dns": "DNS", "time": "time"}
SHARED_IDS = 3                 # other-project rows cited per use: enough to show it, not enough to drown the card


def card_service(node: dict) -> str | None:
    """The enterprise service a card is about: dns (DNS / Name Resolution) or time (Time ...), else None."""
    t = (node.get("title") or "").lower()
    if re.search(r"\bdns\b|name resolution", t):
        return "dns"
    if re.search(r"\btime\b", t):
        return "time"
    return None


def shared_services(node: dict, workspace: Path | None, reg: dict | None) -> tuple[list[str], list[dict]]:
    """(card lines, citable rows) for the servers this system's hosts use for the card's service that other
    estate members also use. Rows are the other members' evidence, as context only (<project>:E-nnn)."""
    svc = card_service(node)
    if not workspace or not svc:
        return [], []
    try:
        from csa_docx import estate
        from csa_docx.answer_sheet import load_matrix
    except ImportError:
        return [], []
    key = estate.key_for_work_dir(Path(workspace) / "csa-work")
    uses = estate.uses_for(key, svc) if key else []
    if not uses:
        return [], []
    matrix = load_matrix(Path(workspace) / "csa-work" / "evidence-matrix.csv")
    total = (reg or {}).get("total") or 0
    lines = ["", SHARED_HEAD, "",
             "Other applications in the estate use these servers too. This is context about those applications, not this "
             "system's evidence: cite their rows (<project>:E-nnn) only in narrative and note blocks, with the project in "
             "the fact's scope (CROSS_PROJECT_ONLY, CROSS_PROJECT_SCOPE).", ""]
    rows, seen = [], set()
    for u in uses:
        mine = u["mine"]
        of = f" of this system's {total} captured hosts" if total else " of this system's captured hosts"
        line = (f"- {u['server']} ({u['ips'].replace(';', ', ')}): {SERVICE_NAME[svc]} for {mine['clients']}{of} "
                f"({mine['preference']}).")
        for o in u["others"]:
            every = [i for i in (o.get("evidence_ids") or "").split(";") if i]
            ids = every[:SHARED_IDS]
            more = f" and {len(every) - len(ids)} more" if len(every) > len(ids) else ""
            line += (f" Also used by {estate.label_of(o['project'])} ({o['project']}): {o['clients']} host(s), "
                     f"{o['preference']}" + (f" (for example {', '.join(ids)}{more})" if more else f" ({', '.join(ids)})" if ids else "") + ".")
            for i in ids:
                r = matrix.get(i.upper())
                if r and i.upper() not in seen:
                    seen.add(i.upper())
                    rows.append({"id": i, "status": r.get("status", ""), "claim": " ".join((r.get("claim") or "").split())[:EXCERPT],
                                 "source": (r.get("source_title") or "")[:160],
                                 "note": f"other application: {estate.label_of(o['project'])}"})
        lines.append(line)
    return lines, rows


def _primaries(work_dir: Path) -> dict[str, tuple[str, str]]:
    """{host: (site, primary DNS server)} for a project's captured hosts (hosts.csv + host_services.csv)."""
    hosts = Path(work_dir) / "hosts"
    if not (hosts / "host_services.csv").is_file() or not (hosts / "hosts.csv").is_file():
        return {}
    site = {r["host"]: (r.get("site") or "").strip() for r in _file_rows(Path(work_dir), "hosts/hosts.csv", "utf-8-sig")
            if (r.get("capture") or "").strip() and (r.get("in_scope") or "") != "peer"}
    out = {}
    for r in _file_rows(Path(work_dir), "hosts/host_services.csv", "utf-8-sig"):
        if r.get("service") == "dns" and str(r.get("preference")) == "1" and site.get(r.get("client_host")):
            out[r["client_host"]] = (site[r["client_host"]], r.get("server_host") or r.get("server_ip"))
    return out


def _majority(servers: list[str], least: int = 2, share: float = 0.5) -> str | None:
    counts: dict[str, int] = {}
    for x in servers:
        counts[x] = counts.get(x, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < least or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]) \
            or ranked[0][1] / len(servers) <= share:
        return None
    return ranked[0][0]


def _dns_order_candidates(workspace: Path, rows: list[dict]) -> list[dict]:
    """Hosts whose primary DNS server differs from the one most hosts of their site use. A site this project's
    own hosts split evenly is compared with the same site in the other estate applications (context only:
    their evidence is cited as <project>:E-nnn)."""
    wd = Path(workspace) / "csa-work"
    mine = _primaries(wd)
    q = {r.get("question", ""): r["evidence_id"] for r in rows}
    by_site: dict[str, dict[str, str]] = {}
    for h, (st, srv) in mine.items():
        by_site.setdefault(st, {})[h] = srv
    others: dict[str, list[tuple[str, str, str]]] = {}    # site -> [(project, host, server)]
    try:
        from csa_docx import estate
        for k, owd in estate.citable_projects(wd).items():
            if estate.estate_of(k):
                for h, (st, srv) in _primaries(owd).items():
                    others.setdefault(st, []).append((k, h, srv))
    except ImportError:
        estate = None
    out = []
    for st, hs in sorted(by_site.items()):
        main = _majority(list(hs.values()))
        if main:
            for h in sorted(x for x, srv in hs.items() if srv != main):
                ids = [i for i in [q.get(f"Which DNS servers is {h} configured to use?")] if i]
                out.append({"text": f"{st}: {sum(1 for v in hs.values() if v == main)} of {len(hs)} captured hosts use {main} "
                                    f"as their primary DNS server, but {h} uses {hs[h]}", "ids": ids})
            continue
        ext = others.get(st, [])
        emain = _majority([srv for _, _, srv in ext], least=3, share=0.75)
        if not emain or estate is None:
            continue
        odd = sorted(h for h, srv in hs.items() if srv != emain)
        if not odd:
            continue
        projs = sorted({k for k, _, srv in ext if srv == emain})
        labels = " and ".join(estate.label_of(k) for k in projs)
        prow = {r.get("question", ""): f"{k}:{r['evidence_id']}" for k in projs
                for r in estate._read(estate.citable_projects(wd)[k] / "evidence-matrix.csv")}
        ext_ids = [prow[f"Which DNS servers is {h} configured to use?"] for k, h, srv in sorted(ext)
                   if srv == emain and f"Which DNS servers is {h} configured to use?" in prow][:2]
        own_ids = [q[f"Which DNS servers is {h} configured to use?"] for h in odd if f"Which DNS servers is {h} configured to use?" in q]
        n = sum(1 for _, _, srv in ext if srv == emain)
        out.append({"text": f"{st}: this system's captured hosts split between primary DNS servers, but {n} of {len(ext)} "
                            f"{st} hosts in {labels} ({', '.join(projs)}) use {emain} first; {', '.join(odd)} use "
                            f"{', '.join(sorted({hs[h] for h in odd}))} first",
                    "ids": own_ids + ext_ids})
    return out


# one line of the Drawbridge guidance above, read back as data (the checks need the list of functions to cover)
def _established_effect(fn: dict, cand: dict, iso: dict, pnames: dict, domain: dict) -> dict:
    """What the flows establish for one function in one domain: the parts that deliver it (by the words of its name, what
    delivers it and what it depends on), and of their paths in the isolation digest those whose mechanism belongs to the
    domain, split into cut, may be cut (a far end with no zone recorded) and kept (both ends inside OT)."""
    from csa_docx import scope_map
    toks = {w for w in re.findall(r"[a-z0-9]+(?:[./][a-z0-9]+)*", " ".join(str(fn.get(k) or "") for k in ("function", "delivered_by")).lower())
            if len(w) >= 4}                 # what the function is and what delivers it; its dependencies name other parts
    pids = [pid for pid, ns in cand.items() if toks & ns]
    out = {"parts": [pnames.get(p, p) for p in pids], "cut": [], "may_cut": [], "kept": []}
    for key in ("cut", "may_cut", "kept"):
        for pid in pids:
            for it in iso.get(pid, {}).get(key, []):
                if scope_map.dependency_matches(it["mechanism"], domain):
                    text = f"{it['mechanism']} between the {pnames.get(pid, pid)} and the {it['other']}"
                    if text not in out[key]:
                        out[key].append(text)
    if not pids:
        line = "    The flows establish: no part that delivers this function was identified, so nothing is established."
    else:
        def show(xs: list[str]) -> str:
            return "; ".join(xs[:6]) + (f" and {len(xs) - 6} more" if len(xs) > 6 else "") if xs else "none"
        line = (f"    The flows establish (parts: {', '.join(out['parts'][:4])}): cut: {show(out['cut'])}. May be cut (zone not recorded): "
                f"{show(out['may_cut'])}. Stays inside OT: {show(out['kept'])}.")
    out["line"] = line
    return out


_FN_LINE = re.compile(r"^\s*Function with an explicit (?P<domain>.+?) dependency to assess: (?P<function>.+?): recorded dependency: "
                      r"(?P<dependency>.*?) \(matched: (?P<matched>[^)]*)\)\s*$")


def drawbridge_function_lines(node: dict, qs: list[dict], workspace: Path | None, sink: dict | None = None) -> dict[str, list[str]]:
    """Domain-specific function prompts for Drawbridge Impact.

    Every requirement-domain card receives only functions whose declared dependencies explicitly match that
    domain's controlled scope terms. A function's name is not evidence that it depends on the domain. The overall
    isolation-validation domain (3.12) is the sole exception:
    it owns the whole-system isolation summary and therefore receives every function with its path-isolation effect.
    """
    if not workspace:
        return {}
    from csa_docx import knowledge, scope_map
    model = knowledge.system_model(workspace)
    if not (model.get("functions") or []):
        return {}
    domain = scope_map.for_section(node.get("number", ""), node.get("title", ""))
    if not domain:
        return {}

    whole_system = domain["key"] == "3.12"
    iso: dict[str, dict] = {}
    cand: dict[str, set[str]] = {}
    pnames: dict[str, str] = {}
    if True:                      # the parts and their isolation digest: 3.12 writes the whole-system view, a domain card the paths of its domain
        from csa_docx import parts as parts_mod
        from csa_docx.parts import is_label
        try:
            doc = parts_mod.assemble(Path(workspace) / "csa-work")
        except (OSError, ValueError, KeyError):
            doc = {}
        if not doc.get("parts") and whole_system:
            return {}
        iso = parts_mod.isolation(Path(workspace) / "csa-work", doc) if doc.get("parts") else {}
        generic = {"server", "servers", "host", "group", "availability", "cluster", "application",
                   "applications", "general", "purpose", "management", "system", "node", "controller",
                   "services", "service", "data", "other", "internal", "peers", "not", "identified",
                   "unidentified", "enterprise", "directory", "time", "sql", "tgoip", "license",
                   "licence", "manager", "radio"}

        def words(s: str) -> set[str]:
            return {w for w in re.findall(r"[a-z0-9]+(?:[./][a-z0-9]+)*", (s or "").lower())
                    if len(w) >= 4 and not w.isdigit() and w not in generic}

        for part in doc.get("parts", []):
            pnames[part["id"]] = part["name"]
            if part["id"] not in iso:
                continue
            names = {part["name"]} | set(part.get("aliases") or []) | set(parts_mod.short_names(part["name"]))
            if is_label(part):
                names |= set(parts_mod.names(part))
            cand[part["id"]] = {w for name in names for w in words(name)}

    out: dict[str, list[str]] = {}
    for q in qs:
        if q.get("kind") != "narrative" or "drawbridge" not in (q.get("text") or "").lower():
            continue
        lines: list[str] = []
        if not whole_system:
            for fn in model.get("functions", []):
                dependency = "; ".join(str(fn.get(k) or "") for k in ("depends_on", "it_dependencies")
                                       if str(fn.get(k) or "").strip())
                matched = scope_map.dependency_matches(dependency, domain)
                if not matched:
                    continue
                lines.append(
                    f"  Function with an explicit {domain['title']} dependency to assess: {fn['function']}: "
                    f"recorded dependency: {dependency} (matched: {', '.join(matched)})"
                )
                est = _established_effect(fn, cand, iso, pnames, domain)
                lines.append(est["line"])
                if sink is not None:
                    sink.setdefault(q["id"], []).append({"domain": domain["title"], "function": fn["function"], "dependency": dependency,
                                                         "matched": ", ".join(matched), **{k: est[k] for k in ("parts", "cut", "may_cut", "kept")}})
            if lines:
                lines.append(
                    f"  Write only consequences caused by loss or unavailability of {domain['title']}. A function stops "
                    "only where this section's evidence establishes that its matched dependency is unavailable during "
                    "isolation. Start each Drawbridge sentence with the cause in this domain's terms (\"With the storage and "
                    "transfer path cut, ...\"). Keep every evidence fact in Facts: facts about another domain's path stay "
                    "in Facts and are left out of the Drawbridge Text. Do not import an outcome caused by another domain. "
                    "If the behaviour is not established, write a QUESTION: line asking what would establish it. "
                    "Under each function, \"The flows establish\" gives what the framework worked out from the flows for this "
                    "domain's paths: what is cut, what may be cut (zone not recorded) and what stays inside OT."
                )
            else:
                lines.append(
                    f"  No function in the system model declares an explicit {domain['title']} dependency. Do not infer "
                    "one from shared servers or from a whole-system isolation outcome. Use this section's evidence or "
                    "write a QUESTION: line asking for the function-level impact."
                )
            out[q["id"]] = lines
            continue
        for fn in model.get("functions", []):
            text = " ".join(str(fn.get(k) or "") for k in ("function", "delivered_by", "depends_on", "it_dependencies"))
            toks = words(text)
            pids = {pid for pid, ns in cand.items() if toks & ns}
            if not pids:
                continue
            if any(iso[pid]["cut"] for pid in pids):
                effect = "lost"
            elif any(iso[pid]["may_cut"] for pid in pids):
                effect = "may be lost"
            else:
                effect = "keeps working"
            lines.append(f"  Functions to write about (from the system model): {fn['function']}: "
                         f"delivered by {fn['delivered_by']}; isolation effect: {effect}")
        if lines:
            lines.append("  Write: one sentence on what keeps working, by function; one sentence for each function lost "
                         "or at risk, saying what stops; one sentence on any fallback and what is unknown. Name "
                         "functions, not lists of parts. This whole-system view is permitted here because Isolation & "
                         "Resilience Validation owns the overall Drawbridge outcome.")
            out[q["id"]] = lines
    return out


def system_name(workspace: Path | None) -> str:
    """The system's name as the working document writes it (its "System Name:" line), or "" when the
    document has none. The framework holds no system name of its own: the document is the one place."""
    if not workspace:
        return ""
    import zipfile
    for root in (Path(workspace), Path(workspace).parent):
        fv = root / "01 Current State AS Built" / "01 Final Version"
        docs = sorted(d for d in fv.glob("*.docx") if not d.name.startswith("~$")) if fv.is_dir() else []
        if len(docs) != 1:
            continue
        try:
            xml = zipfile.ZipFile(docs[0]).read("word/document.xml").decode("utf8", "ignore")
        except (OSError, KeyError, zipfile.BadZipFile):
            return ""
        for para in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
            text = re.sub(r"<[^>]+>", "", re.sub(r"<w:del .*?</w:del>", "", para, flags=re.S)).strip()
            m = re.match(r"System Name:\s*(.+)$", text)
            if m:
                return m.group(1).strip()
    return ""


def condition_lines(req_id: str, req_text: str = "") -> list[str]:
    """The card lines under one requirement question that say what decides its rating: the conditions
    split from its text (conditions.load), the logic that joins them, and the note when the split has
    not been reviewed."""
    from csa_docx import conditions
    c = conditions.load(req_id, req_text)
    out = ["  What decides this rating (conditions):"]
    out += [f"  - {x['id']}: {x['text']}" for x in c["conditions"]]
    if len(c["conditions"]) > 1:
        out.append(f"  - Logic: {c['logic']}   (Met only when the logic holds; an unknown condition caps the rating at Partially Met)")
    if not c["reviewed"]:
        out.append("  (conditions not reviewed yet: use them, and say nothing that depends on their wording)")
    return out


def must_address_by_question(qs: list[dict], fr: dict | None) -> dict[str, list[dict]]:
    """{question id: [must-address item]}: the frame's findings each requirement question owes
    (topic_frames.must_address), keyed by the question that answers that requirement."""
    if not fr:
        return {}
    from csa_docx import topic_frames
    by_req = topic_frames.must_address(fr)
    return {q["id"]: by_req[q["req_id"]] for q in qs if q.get("kind") == "requirement" and by_req.get(q.get("req_id"))}


def must_address_lines(items: list[dict]) -> list[str]:
    """The card lines under one requirement question: what it must cite, or raise as Unknown."""
    if not items:
        return []
    out = ["  Must address (from the analysis frame): cite each finding's evidence in this block, or write an "
           "QUESTION: line that names it (SLOT_NOT_ANSWERED):"]
    for x in items:
        ids = f" ({', '.join(x['ids'])})" if x["ids"] else ""
        out.append(f"  - {x['slot']}: {'Unknown unless the evidence pack answers it: ' if x['empty'] else ''}"
                   f"{x['text'][:260]}{ids}")
    return out


# What a requirement call is told about the prose, in place of the whole-section rules digest (about 800 tokens)
REQUIREMENT_RULES = [
    "Write one to three sentences about this requirement only. The first gives the verdict and the part or parts that decide it.",
    "Test every condition the requirement states (for example independent of a share outside OT, or a documented fallback). Say which the findings settle, and raise as Unknown each one they leave open.",
    "When the rating is not Met, the sentence after the verdict says what keeps it from Met.",
    "Then one sentence for each part that differs. Name a part by the name listed under Parts, never by a host.",
    "Say something about a part only where a finding listed under that part shows it.",
    "Judge every finding listed: supports or contradicts (it becomes a Fact), or gap with the question to ask in note. None may be left without a verdict and none may be set aside, except a kept fact, which may be not relevant with a reason in note.",
    "One part with two roles is one thing: use the single name given for it, never the list.",
    "Another application's name (IAMPS) appears only where it meets a part of this system.",
    "A finding marked declared only, attempted or not found is not an observed fact: say so, or raise it as Unknown.",
    "State the rating from the choices given and give one sentence of reason. Not Applicable needs a justification.",
    "Name every part listed under Parts in the Text, or cover the rest with \"and every other part\" when the same is true of all of them. Name at most three parts in one sentence and say what parts share once, rather than listing them again.",
    "Keep each sentence under 45 words and use a part's name once in a sentence. No semicolons, no totals, no IP addresses.",
    "Write what is, in plain Australian English. Do not copy the wording of an evidence row.",
]


def kept_rows(keep: list[dict], qid: str, covered: set[str]) -> list[dict]:
    """Facts to keep of question ``qid`` that no finding carries (their evidence IDs are not among ``covered``), as rows the
    model can judge like findings: K1, K2, ... The framework restates them with their own evidence IDs, or drops them
    with the model's reason."""
    out = []
    for n, k in enumerate([k for k in keep if k.get("question") == qid and not {i.upper() for i in k["evidence_ids"]} <= covered], 1):
        out.append({"key": f"K{n}", "part": "(kept from the earlier answer)", "part_id": "", "part_ids": [], "side": "", "slot": "kept",
                    "text": k["fact"], "ids": list(k["evidence_ids"]), "basis": "observed", "direction": "", "keep": [k["fact"]],
                    "kept": True})
    return out


def requirement_view(card: dict, qid: str) -> dict | None:
    """The small input for one requirement question, or None when ``qid`` is not a requirement question of the card:
    {"qid", "req_id", "text", "ratings", "parts": [name], "findings": [part findings, see parts.requirement_findings, each
    with "keep": the Facts to keep it carries], "unanswered": [slot question the captures leave empty], "isolation":
    {part name: effect} (only where the requirement is about isolation), "rows": [evidence row], "digest": [block],
    "disagree": [line], "rules": [line], "markdown", "tokens"}. It holds this requirement's findings and rows only: not the
    other questions, the host register, the role table, the background or the applications block."""
    from csa_docx import parts as parts_mod
    q = next((x for x in card.get("questions", []) if x["id"] == qid and x.get("kind") == "requirement"), None)
    if not q:
        return None
    req = q.get("req_id", "")
    pv = card.get("parts") or {}
    found = parts_mod.requirement_findings(pv, req)
    keep = card.get("keep") or []
    for f in found:
        f["keep"] = [k["fact"] for k in keep if set(i.upper() for i in k["evidence_ids"]) & set(i.upper() for i in f["ids"])]
    found += kept_rows(keep, qid, {i.upper() for f in found for i in f["ids"]})
    names = [pv["parts"][pid] for pid in (pv.get("owed") or {}).get(qid, []) if pid in pv.get("parts", {})]
    write_as = {n: re.split(r",\s*", n)[0] for n in names if "," in n}
    owed = ((card.get("frame") or {}).get("must_address") or {}).get(qid, [])
    unanswered = [x["text"] for x in owed if x.get("empty")]
    isolating = bool(re.search(r"isolat", q["text"], re.I))
    iso = {pv["parts"][pid]: pv["isolation"][pid]["effect"][:300] for pid in (pv.get("owed") or {}).get(qid, [])
           if isolating and pid in pv.get("isolation", {}) and pid in pv.get("parts", {})}
    pack = (card.get("evidence") or {}).get(qid) or {}
    rows = [r for r in pack.get("rows", []) if not r.get("established")]
    ids = {r["id"].upper() for r in rows}
    disagree = [d for d in card.get("disagree", []) if (m := re.match(r"Rows disagree: (\S+) ", d)) and m.group(1).upper() in ids]
    lines = [f"# Requirement {qid}", "", q["text"], "", "## Parts", ""] + [f"- {n}" + (f" (one part: write \"{write_as[n]}\" in a sentence, never the whole list)" if n in write_as else "") for n in names or ["(none owed)"]]
    lines += ["", "## Findings (give each a verdict)", ""]
    for f in found:
        ids_ = f" ({', '.join(f['ids'])})" if f["ids"] else ""
        kept = " [fact to keep]" if f["keep"] else ""
        where = "in OT" if f["side"] == "ot" else "outside OT" if f["side"] == "outside" else "OT and outside OT" if f["side"] == "mixed" else ""
        lines.append(f"- {f['key']} | {f['part']} [{f['slot']}, {f['basis']}{', ' + where if where else ''}]: {f['text'][:260]}{ids_}{kept}")
    lines += [f"- Unknown unless the evidence below answers it: {t}" for t in unanswered]
    if not found and not unanswered:
        lines.append("- none bound to this requirement")
    if iso:
        lines += ["", "## When OT is isolated", ""] + [f"- {n}: {e}" for n, e in iso.items()]
    lines += ["", "## Evidence", ""]
    for block in pack.get("digest", []):
        lines += block + [""]
    lines += [f"- {r['id']} {r['status']}: {r['claim']}" + (f" [{r['note']}]" if r.get("note") else "") for r in rows] or ["- nothing on record"]
    lines += [f"- {d}" for d in disagree]
    lines += ["", "## Rules", ""] + [f"- {r}" for r in REQUIREMENT_RULES]
    ratings = card.get("ratings") or doc_spec.DEFAULT_RATINGS
    lines += ["", f"Ratings: {' / '.join(ratings)}"]
    md = "\n".join(lines) + "\n"
    return {"qid": qid, "req_id": req, "text": q["text"], "ratings": list(ratings), "parts": names, "findings": found,
            "unanswered": unanswered, "isolation": iso, "rows": rows, "digest": pack.get("digest", []), "disagree": disagree,
            "rules": list(REQUIREMENT_RULES), "markdown": md, "tokens": len(md) // 4}


def requirement_tokens(card: dict) -> dict[str, int]:
    """{question id: tokens of its requirement_view}, for the per-requirement budget."""
    return {q["id"]: v["tokens"] for q in card.get("questions", []) if (v := requirement_view(card, q["id"]))}


def card(node: dict, spec: dict, workspace: Path | None = None, evidence: bool = True,
         extra_searches: dict | None = None, exclude: tuple[str, ...] = ()) -> dict:
    qs = questions(node, spec)
    requirement_stories = (any(q["kind"] == "requirement" for q in qs)
                           and any(k.strip().lower() == "discovery information"
                                   for k in (node.get("facets") or {})))
    fr = None                    # the analysis frame: built first, so each requirement question can list what it owes
    if evidence and workspace:   # and the evidence pack does not repeat the rows the frame already cites
        from csa_docx import topic_frames
        fr = topic_frames.build(Path(workspace), node["title"], node.get("key", ""))
        if fr.get("status") != "OK":
            fr = None
    on_frame = frozenset(i.upper() for i in topic_frames.all_ids(fr)) if fr else frozenset()
    pack = evidence_pack(node, qs, workspace, extra_searches, exclude, skip=on_frame,
                         terms=frame_terms(node, qs) if fr else None) if evidence else {}
    established = _established(node, qs, pack, workspace) if pack else {}
    if pack:
        from csa_docx import evidence_digest
        all_rows = _matrix_rows(workspace)
        for q in qs:
            if q["id"] not in pack:
                continue
            part = node["parts"][q["part"]] if q.get("part") is not None else {}
            need = evidence_digest.need_for(q, node, (part or {}).get("evidence_need"))
            d = evidence_digest.digest(q, need, node, all_rows, workspace)
            pack[q["id"]].update({"need": need, "digest": d["blocks"], "digest_ids": d["ids"]})
    extra = scope_extras(node)
    kinds = sorted({q["kind"] for q in qs if q["kind"] != "comment"})
    reg = host_register(workspace) if evidence else None
    shared_lines, shared_rows = shared_services(node, workspace, reg) if evidence else ([], [])
    for q in qs:                 # other applications' rows join the table and note packs, so the answer may cite them
        if q["kind"] in ("observation", "note") and q["id"] in pack and shared_rows:
            have = {r["id"].upper() for r in pack[q["id"]]["rows"]}
            pack[q["id"]]["rows"] += [dict(r) for r in shared_rows if r["id"].upper() not in have]
    note_qs = [q for q in qs if q["kind"] == "note" and q["id"] in pack]
    if note_qs:
        all_rows = _matrix_rows(workspace)
        by_id = {r["evidence_id"].upper(): r for r in all_rows}
        try:
            from csa_docx.estate import peer_rows
            by_id.update({k.upper(): {**r, "evidence_id": k} for k, r in peer_rows(Path(workspace) / "csa-work").items()})
        except ImportError:
            pass
        cands = note_candidates(node, workspace, reg, all_rows)
        for q in note_qs:
            p = pack[q["id"]]
            p["note_candidates"] = cands
            have = {r["id"].upper() for r in p["rows"]}
            for c in cands:          # the rows a candidate rests on go on the card, so the note may cite them
                for i in c["ids"]:
                    if i.upper() not in have and i.upper() in by_id:
                        p["rows"].append(_row(by_id[i.upper()]))
                        have.add(i.upper())
    owed = must_address_by_question(qs, fr)
    seen_rows = {r["id"]: r for p_ in pack.values() for r in p_.get("rows", [])}
    disagree = topic_frames.row_disagreements(fr, list(seen_rows.values())) if fr else []
    pview = None                 # the system parts (csa-work/parts.json): the names every section writes about
    if evidence and workspace:
        from csa_docx import parts as parts_mod
        pview = parts_mod.card_view(Path(workspace) / "csa-work", fr, qs)
    established = filter_established(established, pack, fr) if established else established
    practice_view = {}
    if evidence and workspace:
        from csa_docx import practice as practice_mod
        practice_view = practice_mod.card_view(Path(workspace) / "csa-work", node.get("key", ""))
    lines = [f"# Card: {node['title']} (key {node['key']}, section {node['number']})", "",
             f"Kind: {node['kind']}", "", "## Questions", ""]
    db_functions: dict[str, list[dict]] = {}
    db_lines = drawbridge_function_lines(node, qs, workspace, db_functions)
    for q in qs:
        lines.append(f"- {q['id']} {q['text']}")
        if q.get("columns"):
            lines.append(f"  Columns: {' | '.join(q['columns'])}")
        lines += must_address_lines(owed.get(q["id"], []))
        lines += db_lines.get(q["id"], [])
        if q.get("kind") == "requirement" and q.get("req_id"):
            rtext = ""
            for p in node.get("parts", []):
                if p.get("kind") == "requirement":
                    for r in p.get("requirements", []):
                        if r.get("id") == q["req_id"]:
                            rtext = r.get("text", "")
            lines += condition_lines(q["req_id"], rtext)
        if q.get("req_id") and practice_view:
            from csa_docx.practice import card_lines as practice_card_lines
            lines += practice_card_lines(q["req_id"], practice_view)
        if pview:
            from csa_docx.parts import owed_lines
            lines += owed_lines(pview, q["id"])
    if requirement_stories:
        lines += ["", "## Requirement summaries and stories", "",
                  'For every requirement block write both `Summary:` and `Story:`. Do not put the SEP label or a title in either field; the framework adds a bold title from the requirement ID and wording.', '- Summary is the Current State table cell: one to three sentences, at most 80 words, stating the control or practice and its main qualification.', '- Story is the paragraph under its requirement title in Discovery Information. It explains the rating to a reader who has not seen the evidence:', '  1. First sentence: the rating and the condition that decides it (see "What decides this rating").', '  2. Then one sentence for each condition that is not met or is unknown, saying what the system does and which parts cause it. Name at most three parts in a sentence, by their display names.', '  3. End with what is still unknown, in one sentence, if anything is.', "  At most 90 words. Say nothing about another requirement's conditions. Hosts, ports and inventories stay in the tables."]
    sysname = system_name(workspace)
    if sysname:
        lines += ["", "## System name", "",
                  f"- The document names the system \"{sysname}\". Use exactly this name, spelled and cased this way, "
                  "whenever you refer to the system as a whole. Evidence rows and quoted sources may spell it another way; "
                  "do not copy that spelling into your text."]
    from csa_docx import knowledge
    bg_lines, bg_ids = (knowledge.card_section(node["key"], node["title"], qs, (extra or {}).get("must_explain", ""), workspace)
                        if evidence else ([], []))
    lines += bg_lines
    rl = rules(node, spec)
    if rl:
        lines += ["", "## Rules from the template", ""] + [f"- {r}" for r in rl]
    if extra:
        lines += ["", "## Scope", "", f"- Must explain: {extra['must_explain']}", f"- Not here: {extra['not_here']}"]
        if fr:
            from csa_docx import topic_frames
            lines += [f"- {x}" for x in topic_frames.scope_conflicts(fr, extra["not_here"])]
            lines += [f"- {x}" for x in disagree]
    cur = _current(node)
    if cur:
        lines += ["", "## Current text in the document", ""] + [f"- {c}" for c in cur]
    keep, correct = filter_keep(facts_to_keep(node, workspace) if evidence else [], fr)
    if correct:
        lines += ["", "## Facts to correct or drop", "",
                  "Earlier answers stated these, but the analysis frame shows otherwise. Do not repeat them: state the "
                  "finding instead, citing its evidence, and add `Dropped: E-<n> contradicted by <finding>` to the block.", ""]
        for c in correct:
            lines.append(f"- {c['question']}: {c['fact']} ({', '.join(c['evidence_ids'])})")
            if c.get("phrase"):
                lines.append(f"  Only the claim \"{c['phrase']} ...\" is contradicted. If another claim in this fact "
                             "still stands, cite the row for that claim and leave the Dropped: line out; otherwise drop the row and "
                             "do not cite it (CITED_AND_DROPPED).")
            lines += [f"  Contradicted by: {x['text'][:220]}" + (f" ({', '.join(x['ids'])})" if x["ids"] else "")
                      for x in c["contradicts"]]
    if keep:
        lines += ["", "## Facts to keep", "",
                  "This subsection's applied answers stated these facts and table rows from the discovery captures. Keep "
                  "each in the block shown (a table row as a row of that table), citing its capture evidence, or add `Dropped: E-<n> <why it no longer applies>` to that "
                  "block. The check refuses an answer that loses one silently (CAPTURE_DROPPED). Keep the fact and its evidence, "
                  "not its old wording: restate it in your own words, and where it counts hosts (marked below) name the role "
                  "groups or the hosts instead of any number or total (NO_TOTALS).", ""]
        lines += [f"- {k['question']}{' (table row)' if k.get('kind') == 'row' else ''}: {k['fact']} "
                  f"({', '.join(k['evidence_ids'])}){count_hint(k['fact'])}" for k in keep]
    if established:
        lines += ["", "## Facts already established", "",
                  "Facts other sections have already validated. Reuse one where it answers a question; still cite its evidence IDs.", ""]
        by_fact: dict[tuple, list[str]] = {}
        for qid, facts in established.items():
            for f in facts:
                by_fact.setdefault((f["fact"], f["section"], ", ".join(f["evidence_ids"])), []).append(qid)
        for (fact, sec, ev), qids in by_fact.items():
            lines.append(f"- {fact} (section {sec}; {ev}; for {', '.join(qids)}){count_hint(fact)}")
    if reg and reg["groups"]:
        lines += _register_lines(reg)
    rtables = role_table(node, workspace) if evidence else None
    rtable = rtables[0] if rtables else None
    if rtables:
        lines += _role_table_lines(rtables)
    frame = None
    if fr:
        from csa_docx import topic_frames
        lines += topic_frames.card_lines(fr)
        frame = {"slots": [s["id"] for s in fr["slots"]], "ids": sorted(topic_frames.all_ids(fr)),
                 "coverage": topic_frames.coverage_targets(fr), "must_address": owed,
                 "context_ids": topic_frames.context_ids(fr), "zone_conflicts": fr.get("zone_conflicts", []),
                 "strict": fr.get("strict", False)}
    if pview:
        lines += pview["lines"]
    lines += shared_lines
    if pack:
        lines += ["", "## Evidence pack", "",
                  "These rows are worded the way the source records them (\"The system matrix records X as ...\"). "
                  "Never copy that wording: restate each as a fact about the host or application "
                  "(\"X is the <part> that ...\", naming the part as the System parts list does) and put the source in the basis braces. "
                  "A fact whose subject is the matrix, capture, host map or previous assessment is rejected (SOURCE_AS_SUBJECT).", ""]
        shown: dict[str, str] = {}
        for qid, p in pack.items():
            lines.append(f"### {qid}")
            need = p.get("need")
            if need:
                lines.append(f"Evidence need: {need}" + (" (not recognised from the question: rows only; set evidence_need "
                                                          "for this question in the scope map if they do not answer it)"
                                                          if need == "default" else ""))
            if p.get("digest"):
                for block in p["digest"]:
                    key = "\n".join(block)
                    if key in shown:
                        lines.append(f"- {block[0].rstrip(':')}: shown under {shown[key]} above; its evidence IDs may be cited here.")
                    else:
                        shown[key] = qid
                        lines += [""] + block
                lines += ["", "Rows:"]
            if "note_candidates" in p:
                lines.append("Note candidates (worked out from the host facts and the evidence, for the note only; "
                             "write one only if the table rows do not already show it, and cite its rows):")
                lines += [f"- {c['text']}" + (f" ({', '.join(c['ids'])})" if c["ids"] else "")
                          for c in p["note_candidates"]] or ["- none found: write 'None: <why>' unless a row below shows one"]
                lines.append("")
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
            lines += ["", f"## Example answer ({k}): format only, not evidence", "",
                      "> Invented to show the shape of an answer. Its hosts, facts and evidence IDs (E-0nnn) describe no "
                      "real system. Never copy a line from it: the answer check rejects one (EXAMPLE_COPIED).", "", ex,
                      "", f"(end of example answer ({k}))"]
    text = "\n".join(lines) + "\n"
    return {"status": "OK", "key": node["key"], "number": node["number"], "title": node["title"], "text": text,
            "system_name": sysname,
            "questions": qs, "evidence": pack, "established": established, "background_ids": bg_ids,
            "keep": [{k: x[k] for k in ("question", "fact", "evidence_ids", "capture_ids")} for x in keep], "tokens": len(text) // 4,
            "correct": [{k: x[k] for k in ("question", "fact", "evidence_ids", "capture_ids", "contradicts")} for x in correct],
            "ratings": spec.get("ratings") or doc_spec.DEFAULT_RATINGS, "kinds": kinds, "host_register": reg,
            "role_table": rtable, "role_tables": rtables or [], "frame": frame, "disagree": disagree,
            "parts": {k: v for k, v in pview.items() if k != "lines"} if pview else None,
            "practice": practice_view, "requirement_stories": requirement_stories,
            "drawbridge_functions": {k: v for k, v in db_functions.items() if v}}


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
