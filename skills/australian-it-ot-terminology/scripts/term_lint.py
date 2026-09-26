#!/usr/bin/env python3
"""term_lint.py -- flag CSA wording that needs a terminology decision. Never rewrites.

Reads a CSA .docx or a Markdown draft and reports, per Heading 1 section:

  TERM_REVIEW_REQUIRED  consulting or data-analysis phrase ("estate and discovery coverage",
                        "dataset", "landscape"): decide what technical concept is meant
  SPECIFICITY_REVIEW    vague generic term ("technology asset", "storage resource") where a
                        specific one (application server, network share) may be supported
  EVIDENCE_CENTRIC      evidence phrase opening a sentence ("The evidence shows ...") or used
                        three or more times in one section
  IT_OT_REVIEW          an enterprise IT service described as OT or as part of the application
                        ("OT DNS", "Active Directory is part of the application")
  AU_SPELLING           US spelling outside code, quotes, paths and product names

The phrase lists come from ../references/terminology.md (parts 12, 13 and 14), so the
reference and the lint cannot drift apart. Every result needs a person to decide: the
lint cannot tell a legitimate use (an appendix really about discovery; a target-state
"OT DNS") from a wrong one.

Usage:
  python3 term_lint.py <file.docx|file.md> [--heading T | --section N] [--json] [--strict]

--strict  exit 1 when anything is reported (for use as a gate)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TERMS = HERE.parent / "references" / "terminology.md"
PROSE_LINT_DIR = HERE.parents[1] / "csa-writing-style" / "scripts"
sys.path.insert(0, str(PROSE_LINT_DIR))
from prose_lint import Section, read_docx, read_markdown, split_sections  # noqa: E402

# product and proper names that keep US spelling
ALLOW = [
    "Organizational Unit", "Authorization Manager", "Center for Internet Security", "Security Center",
    "Network and Sharing Center", "Action Center", "Software Center", "Endpoint Configuration Manager",
    "Microsoft Defender", "Windows Defender", "Defender for Endpoint", "Data Center Edition", "Datacenter",
    "Cybersecurity and Infrastructure Security Agency", "National Cyber Security Centre",
    "Local Administrator Password Solution", "Solution Design", "System Center", "Service Center",
]
IT_SERVICE = (r"Active Directory|AD DS|\bAD\b|DNS|NTP|W32Time|domain controllers?|SCCM|MECM|Configuration Manager|"
              r"WSUS|PKI|certificate authorit(?:y|ies)|backup|vCenter|hypervisors?|ESXi|Exchange|SMTP relay")
IT_OT_RES = [
    re.compile(rf"\b(?:OT|operational technology)[- ](?:{IT_SERVICE})\b", re.I),
    re.compile(rf"\b(?:{IT_SERVICE})\b[^.]{{0,40}}\b(?:is|are) (?:part of|an? (?:component|part) of|within) the (?:OT )?(?:application|OT system)\b", re.I),
]
TARGET_STATE_RE = re.compile(r"\b(?:target[- ]state|migrat\w*|future|OT[- ]resident|will be|to be|OT 3\.5)\b", re.I)


def _table(md: str, heading_re: str) -> list[list[str]]:
    m = re.search(rf"^##\s+{heading_re}.*?$(.*?)(?=^##\s|\Z)", md, re.M | re.S)
    if not m:
        sys.exit(f"terminology table '{heading_re}' not found in {TERMS}")
    rows = []
    for line in m.group(1).splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*:?-{3,}", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[1:]  # drop header


def load_terms() -> tuple[list[tuple[str, str, str]], list[str], list[tuple[re.Pattern, str]]]:
    md = TERMS.read_text(encoding="utf-8")
    review = []
    for row in _table(md, r"12\. Terms that need review"):
        phrase, why, ask = (row + ["", "", ""])[:3]
        code = "SPECIFICITY_REVIEW" if why.lower().startswith("vague") else "TERM_REVIEW_REQUIRED"
        review.append((phrase.lower(), code, ask))
    review.sort(key=lambda r: len(r[0]), reverse=True)  # longest phrase wins
    evidence = [re.compile(rf"(?<!\w){r[0].replace(chr(92) + '|', '|')}(?!\w)", re.I)
                for r in _table(md, r"13\. Evidence-centric phrases")]
    spelling = []
    for row in _table(md, r"14\. Australian spelling"):
        stem, au = row[0].strip("`"), row[1]
        spelling.append((re.compile(rf"(?<![\w_-])({stem})\w*", re.I), au))
    return review, evidence, spelling


def _mask(text: str) -> str:
    """Blank out spans that must keep their spelling: code, quotes, paths, LDAP paths, allowed names."""
    t = re.sub(r"`[^`]*`", lambda m: " " * len(m.group()), text)
    t = re.sub(r"[\"“][^\"”]{0,200}[\"”]", lambda m: " " * len(m.group()), t)
    t = re.sub(r"(?:\\\\|[A-Za-z]:\\)[^\s,;]+|\b[\w.-]+\.(?:exe|cfg|ps1|txt|csv|xlsx|docx|json|xml|bat)\b|\b(?:OU|DC|CN)=[^\s,;]+",
               lambda m: " " * len(m.group()), t)
    for name in ALLOW:
        t = re.sub(re.escape(name), lambda m: " " * len(m.group()), t, flags=re.I)
    return t


def _snip(text: str, start: int, end: int) -> str:
    a, b = max(0, start - 40), min(len(text), end + 40)
    return ("..." if a else "") + text[a:b].replace("\n", " ") + ("..." if b < len(text) else "")


def lint_section(sec: Section, review, evidence, spelling) -> list[dict]:
    out: list[dict] = []
    ev_hits: list[tuple[int, str, int, bool]] = []
    for i, p in enumerate(sec.paras):
        text = p.text or ""
        if not text.strip():
            continue
        masked = _mask(text)
        low = masked.lower()
        where = "heading" if p.kind == "heading" else p.kind
        taken: list[tuple[int, int]] = []
        for phrase, code, ask in review:
            for m in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", low):
                if any(m.start() < e and m.end() > s for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                out.append({"code": code, "where": where, "para": i, "found": text[m.start():m.end()],
                            "ask": ask, "context": _snip(text, m.start(), m.end())})
        for rx in evidence:
            for m in rx.finditer(masked):
                sentence_start = m.start() == 0 or bool(re.search(r"[.!?:]\s*$|^\s*$", masked[: m.start()][-3:]))
                ev_hits.append((i, text[m.start():m.end()], m.start(), sentence_start))
        for rx in IT_OT_RES:
            for m in rx.finditer(masked):
                target = bool(TARGET_STATE_RE.search(masked[max(0, m.start() - 60): m.end() + 60]))
                out.append({"code": "IT_OT_REVIEW", "where": where, "para": i, "found": text[m.start():m.end()],
                            "ask": ("target-state wording nearby: fine if it describes the target state" if target else
                                    "is this enterprise IT infrastructure? state it as a dependency, and where it sits"),
                            "context": _snip(text, m.start(), m.end())})
        for rx, au in spelling:
            for m in rx.finditer(masked):
                word = text[m.start():m.end()]
                if re.search(r"[_]|[a-z][A-Z]", word):  # identifiers: analyze_public_egress, organizationId
                    continue
                out.append({"code": "AU_SPELLING", "where": where, "para": i, "found": word, "ask": au,
                            "context": _snip(text, m.start(), m.end())})
    total = len(ev_hits)
    for i, phrase, pos, start in ev_hits:
        if start or total >= 3:
            txt = sec.paras[i].text
            out.append({"code": "EVIDENCE_CENTRIC", "where": sec.paras[i].kind, "para": i, "found": phrase,
                        "ask": ("opens the sentence: make the system the subject" if start else
                                f"{total} evidence phrases in this section: keep only those where the qualification matters"),
                        "context": _snip(txt, pos, pos + len(phrase))})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--section", type=int)
    ap.add_argument("--heading")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    path = Path(a.path)
    if not path.exists():
        sys.exit(f"not found: {path}")
    review, evidence, spelling = load_terms()
    paras = read_docx(path) if path.suffix.lower() == ".docx" else read_markdown(path)
    sections = split_sections(paras)
    if not any(s.index for s in sections):
        sections = [Section(1, path.stem, paras)]
    if a.heading:
        chosen = [s for s in sections if s.index and s.title.strip().lower().startswith(a.heading.strip().lower())]
        if not chosen:
            sys.exit(f"no Heading 1 titled '{a.heading}'")
    else:
        chosen = [s for s in sections if s.index and (a.section is None or s.index == a.section)]
    results = []
    for s in chosen:
        items = lint_section(s, review, evidence, spelling)
        results.append({"section": s.index, "title": s.title, "counts": dict(Counter(i["code"] for i in items)), "items": items})
    if a.json:
        print(json.dumps({"file": str(path), "sections": results}, indent=2))
    else:
        total = Counter(c for r in results for c in [i["code"] for i in r["items"]])
        print(f"term_lint: {path.name}   " + (", ".join(f"{k} {v}" for k, v in sorted(total.items())) or "nothing to review"))
        for r in results:
            if not r["items"]:
                continue
            print(f"\n[Section {r['section']}] {r['title']}")
            for i in r["items"]:
                print(f"  {i['code']:<21} {i['where']:<9} \"{i['found']}\"  -> {i['ask']}")
                print(f"      {i['context']}")
        print("\nFlags only: decide what each passage describes (australian-it-ot-terminology, part 1). Nothing was changed.")
    return 1 if a.strict and any(r["items"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
