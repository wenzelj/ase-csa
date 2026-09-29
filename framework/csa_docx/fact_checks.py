"""Evidence gates for change records: every fact is observed, documented or stated, never inferred.

Each **Facts:** line cites evidence rows and may declare its basis and scope:

    - [B5, C1] OIA records a replay file on the TCSI machines. (E-011) {basis: observed; scope: ROKTCSILEFT}

Checks (evidence matrix = WORK_DIR/evidence-matrix.csv):
  FACT_NO_EVIDENCE       ERROR  a fact line cites no E-### row
  FACT_EVIDENCE_MISSING  ERROR  a cited row is not in the evidence matrix
  FACT_INFERRED          ERROR  basis is not observed / documented / stated
  FACT_NO_BASIS          WARN   no {basis: ...} on the fact line
  FACT_NOT_IN_EVIDENCE   ERROR  a host, path, port or frequency in the fact is not in the cited rows
  UNSUPPORTED_QUALIFIER  ERROR  Text uses a frequency (daily, weekly, ...) no cited row states
  SCOPE_WIDENED          ERROR  cited rows (or the declared scope) cover only some sites, and the paragraph
                                carrying the fact does not name them (WARN if another paragraph does)
  FACT_NO_SCOPE          WARN   a fact with site-specific evidence declares no {scope: ...}
  SCOPE_QUANTIFIER       WARN   'all', 'every', 'each', 'both' in Text while evidence covers part of the estate
  PROSE_UNSUPPORTED      WARN   a Text sentence shares no substance with any fact
  EVIDENCE_PENDING       INFO   cited rows not yet signed off
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

EID_RE = re.compile(r"(?<![\w-])(?:[a-z][a-z0-9-]*:)?E-\d{2,4}\b")   # E-042, or utcdtc:E-088 (sibling project)
BRACE_RE = re.compile(r"\{([^{}]*)\}\s*$")
TAG_RE = re.compile(r"^\s*[-*]\s*(\[[^\]]*\]\s*)?")
BASES = ("observed", "documented", "stated")
HOST_RE = re.compile(r"\b[A-Z][A-Z0-9-]{7,}\b|\b[A-Z][A-Z-]*\d[A-Z0-9-]*\b")
PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\s;,)]+")
PORT_RE = re.compile(r"\b(?:tcp|udp)/(\d{2,5})\b|\bport\s+(\d{2,5})\b", re.I)
FREQ_RE = re.compile(r"\b(?:hourly|daily|nightly|weekly|fortnightly|monthly|quarterly|annually|yearly|"
                     r"every (?:day|night|hour|week|month|year|\d+ \w+)|each (?:day|night|week|month)|real[- ]time|continuous(?:ly)?)\b", re.I)
QUANT_RE = re.compile(r"\b(?:all|every|each|both)\b", re.I)
GAP_RE = re.compile(r"\b(?:confirm|not captured|not seen|not found|unknown|not known|no evidence|was not|were not)\w*", re.I)
STOP = set("""about above after again against because before being below between cannot could doing during
further having other their there these those through under until which while would where whether shall
should system systems machines machine section""".split())


def load_matrix(path: Path | None) -> dict[str, dict]:
    """This project's evidence rows, plus those of the sibling projects of the same system
    (hosts/roles.csv kind=system_project) under '<project>:E-nnn'. A fact may cite either."""
    if not path or not Path(path).is_file():
        return {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        out = {r["evidence_id"].strip(): r for r in csv.DictReader(fh) if r.get("evidence_id")}
    roles = Path(path).parent / "hosts" / "roles.csv"
    if roles.is_file():
        try:
            from csa_docx.hostmodel import _project_work_dir
        except ImportError:
            return out
        with roles.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("kind") or "").strip() != "system_project":
                    continue
                key = (r.get("match") or "").strip()
                wd = _project_work_dir(key)
                m = wd / "evidence-matrix.csv" if wd else None
                if m and m.is_file():
                    with m.open(newline="", encoding="utf-8-sig") as fh2:
                        for row in csv.DictReader(fh2):
                            if row.get("evidence_id"):
                                out[f"{key}:{row['evidence_id'].strip()}"] = row
    return out


def parse_sites(spec: str | None) -> dict[str, str]:
    """'ROK=Rockhampton,MKY=Mackay' -> {'ROK': 'Rockhampton', 'MKY': 'Mackay'}"""
    out = {}
    for part in (spec or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().upper()] = v.strip()
    return out


def corpus(row: dict) -> str:
    return " ".join(row.get(k, "") or "" for k in ("claim", "evidence_excerpt", "page_or_location", "section", "source_title"))


def fact_lines(facts: str):
    """(kind, body, eids, meta) per fact line; kind is fact | unknown | table."""
    for raw in (facts or "").splitlines():
        ln = raw.strip()
        if not ln.startswith(("-", "*")):
            continue
        body = TAG_RE.sub("", ln, count=1)
        kind = "fact"
        m = re.match(r"^(Unknown|Table detail)\s*:\s*", body, re.I)
        if m:
            kind = "unknown" if m.group(1).lower() == "unknown" else "table"
            body = body[m.end():]
        meta = {}
        b = BRACE_RE.search(body)
        if b:
            for kv in b.group(1).split(";"):
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = body[:b.start()].rstrip()
        eids = EID_RE.findall(body)
        claim = re.sub(r"\((?:\s*(?:[a-z][a-z0-9-]*:)?E-\d+\s*,?)+\)", "", body).strip()
        yield kind, claim, eids, meta, ln


REQ_RE = re.compile(r"\b[A-Z]+-[A-Z]+-\d+\b")   # requirement IDs (SEP-STOR-03) are not evidence terms


def key_terms(claim: str) -> list[tuple[str, str]]:
    terms = [("host", h) for h in HOST_RE.findall(REQ_RE.sub(" ", claim))]
    terms += [("path", p.rstrip(".").lower()) for p in PATH_RE.findall(claim)]
    terms += [("port", a or b) for a, b in PORT_RE.findall(claim)]
    terms += [("frequency", f.lower()) for f in FREQ_RE.findall(claim)]
    return terms


def _in(term: tuple[str, str], text: str) -> bool:
    kind, val = term
    low = text.lower()
    if kind == "path":
        return val.replace("\\\\", "\\") in low.replace("\\\\", "\\") or val in low
    if kind == "port":
        return re.search(rf"\b{val}\b", text) is not None
    return val.lower() in low


def sites_in(text: str, sites: dict[str, str]) -> set[str]:
    return {name for pre, name in sites.items()
            if re.search(rf"\b{pre}[A-Z0-9-]*\b", text) or re.search(rf"\b{re.escape(name)}\b", text, re.I)}


def _words(t: str) -> set[str]:
    return {w[:6].lower() for w in re.findall(r"[A-Za-z][A-Za-z-]{4,}", t) if w.lower() not in STOP}


def fact_findings(records, matrix: dict[str, dict], sites: dict[str, str], finding) -> list[dict]:
    out = []
    if not matrix:
        return [finding("INFO", "FACT_CHECK_SKIPPED", "no evidence matrix found; facts were not checked against evidence")]
    pending = set()
    for r in records:
        text = (r.text or "").strip()
        if not r.facts and not text:
            continue
        rec_corpus, rec_sites_ev, fact_claims, fact_sites = "", set(), [], []
        for kind, claim, eids, meta, ln in fact_lines(r.facts or ""):
            short = claim[:70]
            if not eids:
                if kind != "unknown":
                    out.append(finding("ERROR", "FACT_NO_EVIDENCE", f"fact cites no evidence row: {short}", r.edit_id))
                continue
            rows = []
            for e in eids:
                if e not in matrix:
                    out.append(finding("ERROR", "FACT_EVIDENCE_MISSING", f"{e} is not in the evidence matrix: {short}", r.edit_id))
                else:
                    rows.append(matrix[e])
                    if (matrix[e].get("review_state") or "").strip().lower() not in ("approved", "accepted", "signed-off", "signed off"):
                        pending.add(e)
            ev = " ".join(corpus(x) for x in rows)
            rec_corpus += " " + ev
            if kind == "unknown":
                continue
            fact_claims.append(claim)
            basis = meta.get("basis", "").lower()
            if not basis:
                if kind == "fact":
                    out.append(finding("WARN", "FACT_NO_BASIS", f"no {{basis: observed|documented|stated}}: {short}", r.edit_id))
            elif basis not in BASES:
                out.append(finding("ERROR", "FACT_INFERRED", f"basis '{basis}' is not observed, documented or stated; move it to Open questions: {short}", r.edit_id))
            if rows:
                missing = [v for k, v in key_terms(claim) if not _in((k, v), ev)]
                if missing:
                    out.append(finding("ERROR", "FACT_NOT_IN_EVIDENCE",
                                       f"{', '.join(dict.fromkeys(missing))} not in {', '.join(eids)}: {short}", r.edit_id))
            scope = meta.get("scope", "")
            fs = sites_in(scope, sites) if scope else sites_in(ev, sites)
            if not scope and fs and kind == "fact":
                out.append(finding("WARN", "FACT_NO_SCOPE", f"evidence is site-specific ({', '.join(sorted(fs))}); add {{scope: ...}}: {short}", r.edit_id))
            rec_sites_ev |= fs
            fact_sites.append((claim, fs, bool(scope)))
        if not text or text.startswith("|"):
            continue
        # Text-level checks
        for f in dict.fromkeys(m.lower() for m in FREQ_RE.findall(text)):
            if rec_corpus and f not in rec_corpus.lower():
                out.append(finding("ERROR", "UNSUPPORTED_QUALIFIER", f"'{f}' in Text is not stated by any cited evidence row", r.edit_id))
        all_sites = set(sites.values())
        paras = [p for p in re.split(r"\n\s*>?\s*\n", text) if p.strip()]
        for claim, fs, declared in fact_sites:
            if not fs or fs >= all_sites:
                continue
            cw = _words(claim)
            best = max(paras, key=lambda p: len(_words(p) & cw))
            if len(_words(best) & cw) >= 2 and not sites_in(best, sites) & fs:
                # Hard error when the writer declared the scope, or nothing in the record names the site;
                # a warning when another paragraph of the same record already states it.
                level = "ERROR" if declared or not sites_in(text, sites) & fs else "WARN"
                out.append(finding(level, "SCOPE_WIDENED",
                                   f"evidence covers only {', '.join(sorted(fs))}; the paragraph must say so and that the rest is not confirmed: {claim[:60]}", r.edit_id))
        if sites and rec_sites_ev and len(rec_sites_ev) < len(all_sites):
            if QUANT_RE.search(text):
                out.append(finding("WARN", "SCOPE_QUANTIFIER",
                                   f"'{QUANT_RE.search(text).group(0)}' in Text while evidence covers only {', '.join(sorted(rec_sites_ev))}", r.edit_id))
        if fact_claims:
            fw = [_words(c) for c in fact_claims]
            for s in re.split(r"(?<=[.!?])\s+", text.replace("\n>", " ").replace(">", " ")):
                s = s.strip()
                if len(s.split()) < 6 or GAP_RE.search(s):
                    continue
                sw = _words(s)
                if not any(len(sw & w) >= 2 for w in fw):
                    out.append(finding("WARN", "PROSE_UNSUPPORTED", f"no fact behind: {s[:80]}", r.edit_id))
    if pending:
        out.append(finding("INFO", "EVIDENCE_PENDING", f"cited rows not yet signed off: {', '.join(sorted(pending, key=lambda e: int(e[2:])))}"))
    return out
