"""Look for evidence before a gap is recorded as not found.

A gap ("confirm the role of HOST", "confirm whether an OT DNS service exists") is only a gap when the
evidence does not answer it. This runs the framework's own lookups in the usual order:

1. the evidence matrix (`evidence_matrix.py lookup`), ignoring rows that only restate the previous
   assessment (`gap_or_action` starts `legacy L-`), earlier NOT_FOUND rows and rejected rows;
2. the discovery index (`discovery_index.py search`): by host name in workbooks and documents, and by
   host plus topic word in the captures. Every usable hit is added to the matrix as an UNCONFIRMED row
   that quotes the source (read it: a person or the evidence agent promotes it to VERIFIED with a claim,
   or rejects it with `evidence_matrix.py review --state rejected`; a rejected row is not offered again).

Verdicts: ANSWERED (the matrix already answers it), CANDIDATES (something was found, so the gap is not
yet a gap), NOT_FOUND (nothing; `searched` says exactly what was looked in, for the NOT_FOUND row).

After reading what was found, a person or the evidence agent settles it one of two ways:
  * it answers the question: record a VERIFIED row that states the answer and restate the gap;
  * it does not: `python3 -m csa_docx.gap_lookup confirm --workspace W --dr DR-DNS-01 --text "..."
    --considered E-052,E-053 --ask "who to ask"` rejects the candidate rows and records a NOT_FOUND row that
    lists the rows considered, so the same rows are not offered again.

    python3 -m csa_docx.gap_lookup check   --workspace W --dr DR-DNS-01 --text "..." [--legacy-docx F]
    python3 -m csa_docx.gap_lookup confirm --workspace W --dr DR-DNS-01 --text "..." --considered E-1,E-2 --ask "..."
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2] / "skills"
MATRIX_SCRIPT = _SKILLS / "csa-evidence-matrix" / "scripts" / "evidence_matrix.py"
INDEX_SCRIPT = _SKILLS / "csa-discovery-index" / "scripts" / "discovery_index.py"

_HOST = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
_STOP = set("""confirm whether exists exist that this with from have were would which their there where also into only
observed captures captured capture evidence found need needs needed show shows shown states stated source sources
role roles site sites what does did each every other any some being been than then them they these those about
after before while when will should could including observe observing not are was did its but has can who how why
either neither both none nor may might must shall the and for you your our out off per via yet""".split())
_STOP |= set("""applies apply applied during successfully finds find tool tools assigned documented tested test tests exists
exist maintained required sits across between within complete completely rapidly approved procedure procedures policy
policies owner owners team kept keep held able whose onto upon
recorded known identified established stated specified provided defined unknown unclear""".split())
_NOISE_PATHS = ("89_output_file_inventory", ".ps1", "preflight")
# capture files that only answer a gap about what they inventory: 70 of the candidates the settle step judged came from the
# scheduled-tasks inventory, none was an answer (a time-sync task is not the time source)
_NOISE_UNLESS = {"66_scheduled_tasks": re.compile(r"\b(?:tasks?|schedul\w*|jobs?|backup|patch\w*|maintenance)\b", re.I),
                 "74_application_events": re.compile(r"\b(?:events?|errors?|logs?|crash\w*|fail\w*)\b", re.I)}
_DOC_EXTS = (".docx", ".xlsx", ".pdf", ".csv")       # the documents the index holds; the other files are captures
_MAX_QUERIES = 12
_MAX_CANDIDATES = 8          # candidates kept per gap: the settle step reads these, so a gap never brings 84 of them
_MIN_TOPIC_COVERAGE = 0.5   # share of the gap's topic words a hit must contain when no host ties it to the gap


def _loose(word: str) -> str:
    """A word as found in text whatever its ending: the start of a long plain word (restored -> resto)."""
    return word[:max(4, len(word) - 3)] if len(word) >= 6 and word.isalpha() else word


def _phrase_in(phrase: str, low: str) -> bool:
    """The phrase's words together (at most one other word between them), in any word ending: "time source" is in
    "Time sources" and "time source (stratum 4)" but not in "Next Run Time ... source"."""
    ws = [re.escape(_loose(w)) for w in phrase.lower().split()]
    return bool(ws) and bool(re.search(r"\b" + r"\w*\W+(?:\w+\W+)?".join(ws), low))


def relevant(excerpt: str, text: str, vocab: list[str] | None = None) -> bool:
    """A hit is only a candidate when it is about the gap. A host named in the gap and found in the hit ties it
    to the gap. Otherwise the hit must hold at least two of the gap's topic words and half of them, so a page
    that happens to say "network" and "time" is not offered as the answer to a question about resolver zones."""
    low = (excerpt or "").lower()
    hosts = [h.lower() for h in hosts_in(text)]
    words = topic_words(text, limit=8)
    if hosts:
        # a gap that names a host is answered only by something about that host ("IPTPRDLIC201: its time source is not
        # known" is not answered by the time-sync tasks of another host). A line that only lists the host
        # ("ROTPRDREV101 MOTPRDREV101 | ...") says nothing about what the gap asks, so it must also hold a topic word
        if not any(h in low for h in hosts):
            return False
        return not words or any(w[:5] in low for w in words)
    phrases = _phrases(text, vocab)
    if phrases:                 # the section has its own vocabulary: a hit that uses it is relevant; so is one that shares
        variants = [" ".join(spelling_variant(w) or w for w in p.split()) for p in phrases]   # three of the gap's words
        if any(_phrase_in(p, low) for p in phrases + variants):
            return True
        return len(words) >= 4 and sum(1 for w in words if w[:5] in low) >= 4
    if not words:
        return not hosts        # a host-only gap needs the host in the hit; with neither there is nothing to judge by
    hit = sum(1 for w in words if w[:5] in low)
    return hit >= 2 and hit / len(words) >= _MIN_TOPIC_COVERAGE
_ANSWER_SCORE, _ANSWER_COVERAGE = 0.6, 0.75
_MIN_MATRIX_SCORE = 0.4


def _run(cmd: list[str]) -> dict | None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def _rejected(workspace: Path) -> set[str]:
    """Evidence IDs whose latest review is `rejected` (evidence-reviews.jsonl)."""
    path = workspace / "csa-work" / "evidence-reviews.jsonl"
    latest: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                latest[rec["evidence_id"].upper()] = rec.get("state", "")
    return {i for i, s in latest.items() if s == "rejected"}


def _acknowledged(workspace: Path, dr_id: str) -> set[str]:
    """Evidence IDs a earlier `confirm` recorded as considered and not an answer to this gap."""
    path = workspace / "csa-work" / "evidence-matrix.csv"
    out: set[str] = set()
    if path.is_file():
        from csa_docx import modelstore
        for r in modelstore.read_csv(path):
            if r.get("status") == "NOT_FOUND" and dr_id in (r.get("gap_or_action") or ""):
                out.update(re.findall(r"E-\d+", r.get("inference_reason") or ""))
    return out


# "..., which the network owner could confirm": who can answer is not what the gap is about, and its words
# ("network", "owner") made four of ten searches meaningless
_CONFIRMER = re.compile(r",?\s*\b(?:which|who)\s+(?:the\s+)?[^,.;]{0,90}?\b(?:could|can|would|will|should)\s+"
                        r"(?:confirm|answer|say|tell|provide|check|verify)\b[^,.;]*", re.I)


def strip_confirmers(text: str) -> str:
    """The gap without its "which the X owner could confirm" clauses."""
    new = _CONFIRMER.sub("", text or "")
    return (text or "").strip() if new == text else re.sub(r"\s+", " ", new).strip(" ,;.")


def section_vocabulary(dr_id: str) -> tuple[list[str], str]:
    """(the evidence vocabulary of the topic frame whose key is in the Discovery Required ID, its area): DR-TIME-F1 ->
    the Time Synchronisation frame's look_for and search phrases. Empty when the section has no frame."""
    m = re.match(r"(?i)DR-([A-Z0-9]+)-", dr_id or "")
    if not m:
        return [], ""
    try:
        from csa_docx import topic_frames
        for fr in topic_frames.all_frames():
            if str(fr.get("key", "")).upper() == m.group(1).upper():
                vocab = [p for s in fr.get("slots", []) for p in (s.get("look_for") or s.get("search") or [])]
                return list(dict.fromkeys(vocab)), fr.get("area", "")
    except Exception:
        pass
    return [], ""


_ROLE_CLAUSE = re.compile(r"\b(?:which|who)\s+(?:the\s+)?(?P<who>[^,.;]{0,90}?)\s+(?:could|can|would|will|should)\s+"
                          r"(?:confirm|answer|say|tell|provide|check|verify)\b", re.I)
_POLICY = re.compile(r"\b(?:policy|policies|procedure|procedures|plan|schedule|retention|retain|tested|approved|approval|"
                     r"documented|responsible|administers?|owns?|sla|agreement|contract|governance|processes)\b", re.I)


def owners_in(text: str) -> list[str]:
    """Who the gap says can answer it: "which the application owner or backup service owner could confirm" ->
    ["application owner", "backup service owner"]."""
    out: list[str] = []
    for m in _ROLE_CLAUSE.finditer(text or ""):
        for part in re.split(r"\s*(?:,|\bor\b|\band\b)\s*", m["who"]):
            part = re.sub(r"^(?:the|a|an)\s+", "", part.strip(), flags=re.I)
            if part and part.lower() not in {x.lower() for x in out}:
                out.append(part)
    return out


_WHO = re.compile(r"\bwho\b|\baccounts?\b[^.]{0,40}\badminister|\bresponsible\b|\bowns\b|\badministers?\b", re.I)


def classify_gap(text: str) -> str:
    """What kind of answer the gap needs. The "which the X owner could confirm" clause is on nearly every gap, system facts
    included, so it only says who to ask; the question itself decides. "owner": it asks who (who administers, which accounts
    administer, who is responsible). "document": a policy, procedure, plan, schedule or test. "system": a fact about the hosts
    the captures can show. Owner and document gaps are looked up in documents only: a capture holds settings, never a
    retention policy."""
    q = strip_confirmers(text)
    return "owner" if _WHO.search(q) else "document" if _POLICY.search(q) else "system"


_SPELL = (("isation", "ization"), ("ising", "izing"), ("ised", "ized"), ("ises", "izes"), ("ise", "ize"), ("yse", "yze"))


def spelling_variant(word: str) -> str | None:
    """The other spelling (synchronise <-> synchronize); None when there is none."""
    w = word.lower()
    for uk, us in _SPELL:
        if w.endswith(uk) and len(w) > len(uk) + 3:
            return w[:-len(uk)] + us
        if w.endswith(us) and len(w) > len(us) + 3:
            return w[:-len(us)] + uk
    return None


def hosts_in(text: str) -> list[str]:
    return list(dict.fromkeys(_HOST.findall(text or "")))


def topic_words(text: str, limit: int = 6) -> list[str]:
    words = [w.lower() for w in _WORD.findall(_HOST.sub(" ", text or ""))]
    return list(dict.fromkeys(w for w in words if w not in _STOP))[:limit]


def _strong(phrase: str) -> bool:
    """A phrase worth searching the index for: two words or more, or one distinctive word. A common single word ("zone",
    "message") or a generic pair ("host name", "IP address") finds unrelated lines."""
    return (" " in phrase.strip() or len(phrase.strip()) >= 8) and phrase.strip().lower() not in _GENERIC


_GENERIC = {"host name", "ip address", "domain name", "operating system", "event log", "log file"}


def _phrases(text: str, vocab: list[str] | None) -> list[str]:
    """The section vocabulary phrases the gap is about, the most specific first: those sharing content words with it,
    ranked by the length of the words they share (retention beats backup; security level beats zone)."""
    from csa_docx import matrix_candidates as M
    q = M.words(text)
    scored = [(sum(len(w) for w in re.findall(r"[A-Za-z]+", p) if M.words(w) & q), i, p)
              for i, p in enumerate(M.natural_terms(vocab)) if M.words(p) & q and _strong(p)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [p for _, _, p in scored[:4]]


def queries(text: str, kind: str = "system", vocab: list[str] | None = None) -> list[tuple[str, str | None]]:
    """(search terms, path-like filter) pairs. Hosts: the host alone in workbooks and documents, then host plus a topic
    word in the captures. The section's own vocabulary phrases that the gap is about come first (and their other spelling:
    synchronise and synchronize). No host and no vocabulary: pairs of the leading topic words. An owner or document gap is
    searched in documents only."""
    hosts, words = hosts_in(text), topic_words(text)
    out: list[tuple[str, str | None]] = []
    for h in hosts[:4]:
        out += [(h, ".xlsx"), (h, ".docx")]
        if kind == "system":
            out += [(f"{h} {w}", None) for w in words[:3]]
    terms = list(_phrases(text, vocab))
    if not terms and not hosts:
        if len(words) >= 2:
            terms += [f"{a} {b}" for a, b in combinations(words[:5], 2)]       # every pair of the leading topic words
        elif words:
            terms.append(words[0])
    for term in list(terms):
        alt = " ".join(spelling_variant(w) or w for w in term.split())
        if alt != term:
            terms.append(alt)
    for term in terms:
        if kind == "system":
            out.append((term, None))
        else:
            out += [(term, ext) for ext in _DOC_EXTS]
    return out[:_MAX_QUERIES]


def _matrix_stage(workspace: Path, text: str, rejected: set[str]) -> tuple[str, list[str]]:
    res = _run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "lookup", text, "--limit", "40"])
    if not res or res.get("status") != "OK":
        return "NO_MATRIX", []
    kept = []
    for m in res.get("matches", []):
        if m["evidence_id"].upper() in rejected or m.get("status") == "NOT_FOUND":
            continue
        if (m.get("gap_or_action") or "").startswith("legacy L-"):
            continue
        kept.append(m)
    answered = any(m["status"] in ("VERIFIED", "INFERRED") and m["score"] >= _ANSWER_SCORE
                   and m["coverage"] >= _ANSWER_COVERAGE for m in kept)
    # the lookup is asked for 40 rows so that the framework's own NOT_FOUND rows cannot crowd the real ones out; what is
    # offered to read is the best few, and only a row that scores like an answer
    kept = sorted((m for m in kept if m.get("score", 0) >= _MIN_MATRIX_SCORE), key=lambda m: -m.get("score", 0))[:_MAX_CANDIDATES]
    return ("ANSWERED" if answered else "CANDIDATES" if kept else "NONE"), [m["evidence_id"] for m in kept]


def hit_score(excerpt: str, source: str, text: str, vocab: list[str] | None = None) -> float:
    """How well an index hit answers a gap: a host the gap names +3, each section vocabulary phrase +3, each topic word
    +1, a current document or capture +1; the previous assessment -4 (it repeats claims nobody has checked) unless it
    names the host."""
    low = (excerpt or "").lower()
    hosts = [h.lower() for h in hosts_in(text)]
    named = any(h in low for h in hosts)
    score = 3.0 if named else 0.0
    score += sum(3 for p in _phrases(text, vocab) if _phrase_in(p, low))
    score += sum(1 for w in topic_words(text, limit=8) if w[:5] in low)
    from csa_docx import answer_sheet
    if answer_sheet.source_class({"source_title": source}) == "previous":
        score -= 0.0 if named else 4.0
    else:
        score += 1
    return score


def rank_hits(hits: list[dict], text: str, vocab: list[str] | None = None, limit: int = _MAX_CANDIDATES) -> list[dict]:
    """The best ``limit`` hits, best first; a hit scoring zero or less is dropped."""
    scored = sorted(((hit_score(h.get("evidence_excerpt", ""), h.get("source_title", "") or h.get("rel_path", ""), text, vocab), i, h)
                     for i, h in enumerate(hits)), key=lambda x: (-x[0], x[1]))
    return [h for s, _, h in scored if s > 0][:limit]


def _index_stage(workspace: Path, text: str, exclude: tuple[str, ...], kind: str = "system",
                 vocab: list[str] | None = None) -> tuple[list[dict], list[str], bool]:
    hits, seen, ran, has_index = [], set(), [], True
    for terms, path_like in queries(text, kind, vocab):
        cmd = [sys.executable, str(INDEX_SCRIPT), "--workspace", str(workspace), "search", terms, "--limit", "5", "--per-file", "1"]
        if path_like:
            cmd += ["--path-like", path_like]
        res = _run(cmd)
        if not res or res.get("status") != "OK":
            has_index = False
            break
        ran.append(terms + (f" [{path_like}]" if path_like else ""))
        for h in res.get("results", []):
            rel = h.get("rel_path", "")
            key = (rel, h.get("page_or_location"))
            if key in seen or any(n in rel for n in _NOISE_PATHS) or any(e and e in rel for e in exclude):
                continue
            if any(name in rel and not asks.search(text) for name, asks in _NOISE_UNLESS.items()):
                continue
            if len(h.get("evidence_excerpt", "")) < 20 or not relevant(h.get("evidence_excerpt", ""), text, vocab):
                continue
            seen.add(key)
            hits.append(h)
    return rank_hits(hits, text, vocab), ran, has_index


def _add_candidates(workspace: Path, dr_id: str, text: str, hits: list[dict], rejected: set[str]) -> list[str]:
    rows = [{
        "csa_area": "gap_lookup", "question": f"{dr_id}: {text}"[:400],
        "claim": f"Possible answer to {dr_id}: the source reads: {h['evidence_excerpt'][:260]}",
        "status": "UNCONFIRMED", "source_title": h["source_title"], "source_version": h.get("source_version", ""),
        "section": "", "page_or_location": h.get("page_or_location", ""), "evidence_excerpt": h["evidence_excerpt"][:1200],
        "inference_reason": "", "confidence": "low",
        "gap_or_action": (f"Found by the gap lookup for {dr_id}. Read it: if it answers the question, record a VERIFIED row "
                          "that states the answer; if not, reject this row (evidence_matrix.py review --state rejected)"),
    } for h in hits]
    ids: list[str] = []
    for row in rows:            # one call each, so a row the matrix refuses does not stop the others
        res = _run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "append", "--agent", "gap lookup",
                    "--context", dr_id, "--allow-new-area", "--row-json", json.dumps(row, ensure_ascii=False)])
        if not res:
            continue
        for w in res.get("written", []):
            ids.append(w["evidence_id"])
        for s in res.get("skipped_duplicates", []):
            dup = s.get("duplicate_of", "")
            if dup and dup.upper() not in rejected:
                ids.append(dup)
    return list(dict.fromkeys(ids))


def lookup_gap(workspace: Path, dr_id: str, text: str, *, exclude: tuple[str, ...] = ()) -> dict:
    """Search the matrix, then the index, for evidence on a gap; add what is found to the matrix."""
    workspace = Path(workspace)
    related: list[str] = []
    rejected = _rejected(workspace) | _acknowledged(workspace, dr_id)
    kind, owners = classify_gap(text), owners_in(text)
    text = strip_confirmers(text) or text
    matrix_state, matrix_ids = _matrix_stage(workspace, text, rejected)
    vocab, area = section_vocabulary(dr_id)          # the topic's own words find "Time source on X" for "time connections"
    if vocab:
        from csa_docx import evidence_live, matrix_candidates
        csv_path = workspace / "csa-work" / "evidence-matrix.csv"
        near = (matrix_candidates.candidates(evidence_live.get_verified_evidence(csv_path), text, vocab, area, limit=6, skip=rejected)
                if csv_path.is_file() else [])
        related = [c["id"] for c in near if c["id"] not in matrix_ids]     # rows to read: they never change the verdict
    hits, ran, has_index = _index_stage(workspace, text, exclude, kind, vocab)
    index_ids = _add_candidates(workspace, dr_id, text, hits, rejected) if hits else []
    found = list(dict.fromkeys(matrix_ids + [i for i in index_ids if i.upper() not in rejected]))
    if matrix_state == "ANSWERED" and not matrix_ids:
        matrix_state = "NONE"
    verdict = "ANSWERED" if matrix_state == "ANSWERED" else "CANDIDATES" if found else "NOT_FOUND"
    where = "documents only, since " + ("a person has to confirm it" if kind == "owner" else "it is about a policy, procedure or test") \
        if kind != "system" else "all sources"
    scope = ("evidence matrix" + ("" if matrix_state != "NO_MATRIX" else " (none)")
             + "; discovery index" + (f" ({where}; {len(ran)} searches: {'; '.join(ran)})" if has_index else " (no index built)"))
    return {"verdict": verdict, "matrix": matrix_ids, "index": index_ids, "evidence_ids": found,
            "related": related, "kind": kind, "owners": owners, "queries": ran, "searched": scope}


def confirm_gap(workspace: Path, dr_id: str, text: str, considered: list[str], *, ask: str,
                exclude: tuple[str, ...] = ()) -> dict:
    """Record that the evidence found for a gap was read and does not answer it: reject the candidate rows the
    lookup added, and append a NOT_FOUND row that names everything considered and what was searched."""
    workspace = Path(workspace)
    look = lookup_gap(workspace, dr_id, text, exclude=exclude)
    ids = sorted({i.upper() for i in considered} | {i.upper() for i in look["evidence_ids"]})
    from csa_docx import modelstore
    candidates = {r["evidence_id"].upper() for r in modelstore.read_csv(workspace / "csa-work" / "evidence-matrix.csv")
                  if r["status"] == "UNCONFIRMED" and r["claim"].startswith(f"Possible answer to {dr_id}")}
    to_reject = [i for i in ids if i in candidates]
    if to_reject:
        subprocess.run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "review", *to_reject,
                        "--by", "gap lookup", "--state", "rejected",
                        "--note", f"read for {dr_id}: does not answer the question"], capture_output=True, text=True)
    from csa_docx import evidence_live
    verified = {str(r["evidence_id"]).upper() for r in evidence_live.get_verified_evidence(workspace / "csa-work" / "evidence-matrix.csv")}
    known = [i for i in dict.fromkeys([*ids, *[x.upper() for x in look.get("related", [])]]) if i in verified]
    # a question can be answered in part: say which verified rows bear on it, so the record never reads as a total miss
    claim = (f"No evidence answers all of: {text[:300]}. Verified rows on this subject (not an answer to the whole): {', '.join(known)}"
             if known else f"No evidence in the matrix or the discovery index answers: {text[:300]}")
    row = {"csa_area": "discovery_required", "question": text[:400],
           "claim": claim,
           "status": "NOT_FOUND", "source_title": f"searched: {look['searched']}"[:1400], "source_version": "",
           "section": "8 Discovery Required", "page_or_location": "", "evidence_excerpt": "",
           "inference_reason": f"read and considered, not an answer to {dr_id}: {', '.join(ids)}" if ids else "",
           "confidence": "low", "gap_or_action": f"{dr_id} {ask}"}
    res = _run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "append", "--agent", "gap lookup",
                "--context", f"confirm {dr_id}", "--allow-new-area", "--row-json", json.dumps(row, ensure_ascii=False)])
    written = (res or {}).get("written", [])
    return {"status": "OK" if written or (res or {}).get("skipped_duplicates") else "ERROR",
            "dr_id": dr_id, "not_found_row": written[0]["evidence_id"] if written else "",
            "rejected": to_reject, "considered": ids}


_CAND_CLAIM = re.compile(r"^Possible answer to (DR-[A-Za-z0-9_.-]+): ")


def judge_pending(workspace: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """({DR id: the best pending candidate ids, at most ``_MAX_CANDIDATES``}, {reason: ids to reject}) for every pending
    "Possible answer to DR-x" row, judged with the current rules: it must be about the gap (``relevant``) and rank in
    the best few."""
    from csa_docx import modelstore
    workspace = Path(workspace)
    csv_path = workspace / "csa-work" / "evidence-matrix.csv"
    rows = modelstore.read_csv(csv_path) if csv_path.is_file() else []
    rejected = _rejected(workspace)
    by_dr: dict[str, list[dict]] = {}
    for r in rows:
        m = _CAND_CLAIM.match(r.get("claim", ""))
        if (m and r.get("status") == "UNCONFIRMED" and (r.get("review_state") or "pending").lower() == "pending"
                and r["evidence_id"].upper() not in rejected):
            by_dr.setdefault(m.group(1), []).append(r)
    keep: dict[str, list[str]] = {}
    drop: dict[str, list[str]] = {"not about the gap": [], "beyond the best five": []}
    for dr, cands in by_dr.items():
        text = strip_confirmers(re.sub(r"^DR-[^:]*:\s*", "", cands[0].get("question", "")))
        vocab, _ = section_vocabulary(dr)
        good = []
        for r in cands:
            ex = r.get("evidence_excerpt", "")
            if relevant(ex, text, vocab):
                good.append((hit_score(ex, r.get("source_title", ""), text, vocab), r["evidence_id"]))
            else:
                drop["not about the gap"].append(r["evidence_id"])
        good.sort(key=lambda x: (-x[0], x[1]))
        keep[dr] = [i for s, i in good[:_MAX_CANDIDATES] if s > 0]
        drop["beyond the best five"] += [i for _, i in good[_MAX_CANDIDATES:]]
    return keep, drop


def triage_pending(workspace: Path, apply: bool = False) -> dict:
    """Re-judge every pending candidate with the current rules (``judge_pending``). The rest are rejected: a review record,
    which the matrix never offers again; nothing is deleted and a later review can restore a row. Dry run unless
    ``apply``. Returns counts."""
    keep, drop = judge_pending(workspace)
    out = {"gaps": len(keep), "pending": sum(len(v) for v in keep.values()) + sum(len(v) for v in drop.values()),
           "keep": sum(len(v) for v in keep.values()), "reject": {k: len(v) for k, v in drop.items()}, "applied": False}
    if apply:
        for reason, ids in drop.items():
            for i in range(0, len(ids), 50):
                _run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "review", *ids[i:i + 50],
                      "--by", "gap triage", "--state", "rejected", "--note", f"triage: {reason}"])
        out["applied"] = True
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Search the evidence matrix and the discovery index for a gap.")
    ap.add_argument("action", choices=["check", "confirm", "triage"])
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--dr", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--apply", action="store_true", help="triage: reject the pending candidates that fail (default: dry run)")
    ap.add_argument("--considered", default="", help="confirm: evidence IDs read and judged not to answer it")
    ap.add_argument("--ask", default="Confirm with the site team or the application owner", help="confirm: who to ask")
    ap.add_argument("--legacy-docx", type=Path)
    a = ap.parse_args(argv)
    exclude = (a.legacy_docx.name,) if a.legacy_docx else ()
    if a.action == "triage":
        res = triage_pending(a.workspace, apply=a.apply)
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if not a.dr or not a.text:
        ap.error("check and confirm need --dr and --text")
    if a.action == "check":
        print(json.dumps(lookup_gap(a.workspace, a.dr, a.text, exclude=exclude), ensure_ascii=False))
        return 0
    considered = [x.strip() for x in a.considered.split(",") if x.strip()]
    res = confirm_gap(a.workspace, a.dr, a.text, considered, ask=a.ask, exclude=exclude)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["status"] == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
