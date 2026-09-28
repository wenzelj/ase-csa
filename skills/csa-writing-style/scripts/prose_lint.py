#!/usr/bin/env python3
"""prose_lint.py -- measure CSA prose against csa-writing-style "Say it once, say it first".

Reads a .docx (python-docx) or a Markdown/plain-text draft and reports, per Heading 1
section, the patterns that make an assessment read as over-detailed and fragmented:

  - bullet share and nested bullets (fragmented prose)
  - lead-in lines ending in ':' that split a sentence across bullets
  - announcing connectors ("This confirms", "As a result", ...) and stock AI tells
  - identifiers (hostnames, IPs, FQDNs) repeated in prose within one section
  - sentences repeated verbatim within one section
  - evidence IDs and evidence file names in body prose
  - heading label noise ("(Evidence-Based)", "(Script Evidence)") and placeholder headings
  - duplicate Heading 1 titles, and prose word count against a section budget
  - readability: IP addresses in prose, identifier and port density per paragraph,
    long sentences, average sentence length, and stacked hedges

Tables are treated as the proper home for identifiers and detail: they count toward
nothing except the word total. The script only reads; it never modifies the input.

Usage:
  python3 prose_lint.py <file.docx|file.md> [--section N] [--max-words 900] [--json] [--strict]

--section N   report only the Nth Heading 1 section (1-based). Usually matches the csa_docx
              framework's Section<N>, but an empty or hidden Heading 1 can shift it by one:
              prefer --heading when in doubt
--heading T   report only the Heading 1 section whose title starts with T
--strict      exit 1 when any WARN is raised (for use as a gate)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- patterns
CONNECTORS = [
    r"\bthis (?:confirms|indicates|establishes|demonstrates|shows|means|highlights|underscores)\b",
    r"\bthis results in\b",
    r"\bthis represents\b",
    r"\bas a result\b",
    r"\bthe following (?:findings|recommendations|observations)[^.]{0,40}\b(?:derived|based)\b",
    r"\bthe analysis focuses on\b",
    r"\bit is (?:important|worth) (?:to note|noting)\b",
    r"\bit should be noted\b",
    r"\bmoreover\b",
    r"\bfurthermore\b",
    r"\bin order to\b",
    r"\bplays? an? (?:crucial|vital|key|critical) role\b",
    r"\bleverag(?:e|es|ed|ing)\b",
    r"\brobust\b",
    r"\bseamless(?:ly)?\b",
    r"\bholistic\b",
]
CONNECTOR_RE = re.compile("|".join(CONNECTORS), re.IGNORECASE)
HEADING_NOISE_RE = re.compile(
    r"\((?:evidence[- ]based|script (?:evidence|confirmed)|supporting evidence|design evidence|derived from table)\)",
    re.IGNORECASE,
)
PLACEHOLDER_HEADING_RE = re.compile(r"(\betc\.?\s*$|^finding comments\b|\[.*\])", re.IGNORECASE)
EVIDENCE_ID_RE = re.compile(r"\[?\bE-\d{2,}\b\]?")
EVIDENCE_FILE_RE = re.compile(r"\b[\w-]+\.(?:txt|csv|log|json|xml|ps1|evtx)\b", re.IGNORECASE)
# Evidence as subject: the sentence is about the collection, not the system.
EVIDENCE_SUBJECT_RE = re.compile(
    r"\b(?:the|these|this)\s+(?:"
    r"discovery (?:data|table|captures?|set|package|output)s?"
    r"|spreadsheets?"
    r"|workbooks?"
    r"|raw (?:output|resolver|file)s?"
    r"|capture(?:s)?(?:\s+output)?"
    r"|evidence (?:identifies?|shows?|indicates?|suggests?|reveals?|establishes?|confirms?)"
    r"|supplied data"
    r")\b"
    r"[^.;!?]{0,80}\b(?:contains?|lists?|shows?|indicates?|suggests?|reveals?|establishes?|confirms?|identifies?|covers?|includes?|records?|notes?|captures?|holds?|has|have)\b",
    re.IGNORECASE,
)
IDENT_RES = [
    re.compile(r"\b[A-Z]{3,}[A-Z0-9]*\d{2,}[A-Z0-9]*\b"),  # HOSTPRDSRV122 style
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),  # IPv4
    re.compile(r"\b[a-z][\w-]*(?:\.[a-z][\w-]*){2,}\b", re.IGNORECASE),  # FQDN
]
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# Readability (tell the story): detail that belongs in a table, and paragraphs that read like a data dump.
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b|\b\d{1,3}(?:\.\d{1,3}){2}\.x\b|\.\d{1,3}/\.\d{1,3}\b")
PORT_RE = re.compile(r"\b(?:tcp|udp)\s*/\s*\d{2,5}\b|\bports?\s+\d{2,5}\b", re.IGNORECASE)
HEDGE_RE = re.compile(r"\b(?:not (?:been )?(?:established|observed|confirmed|verified)|has not been|could not be|unclear|appears? to|may be|possibly)\b", re.IGNORECASE)
# Inference (never infer): wording that turns an observation into a conclusion the evidence does not state.
INFERENCE_RE = re.compile(r"\b(?:which means|this means|this suggests|suggests? that|implies|implying|presumably|probably|likely|"
                          r"we assume|assumed|is expected to|in practice|typically|usually|generally|normally|"
                          r"therefore|it follows|would be)\b", re.IGNORECASE)
MAX_SENTENCE_WORDS = 35
MAX_AVG_SENTENCE_WORDS = 24
MAX_IDENTIFIERS_PER_PARA = 3
MAX_PORTS_PER_PARA = 1
MAX_HEDGES_PER_PARA = 2

# ---------------------------------------------------------------- model
@dataclass
class Para:
    kind: str  # heading | bullet | text | table
    text: str
    level: int = 0  # heading level, or bullet nesting level (0 = top)


@dataclass
class Section:
    index: int
    title: str
    paras: list[Para] = field(default_factory=list)


# ---------------------------------------------------------------- readers
def read_docx(path: Path) -> list[Para]:
    try:
        import docx  # python-docx
        from docx.oxml.ns import qn
    except ImportError:
        sys.exit("python-docx is required for .docx input (pip install python-docx)")
    d = docx.Document(str(path))
    out: list[Para] = []
    style_names = {s.style_id: (s.name or s.style_id) for s in d.styles}
    body = d.element.body
    def blocks(el):
        # flatten content controls (w:sdt / w:sdtContent) so their paragraphs count,
        # matching the csa_docx stable-ID manifest
        for c in el.iterchildren():
            t = c.tag.rsplit("}", 1)[-1]
            if t in ("sdt", "sdtContent", "customXml"):
                yield from blocks(c)
            else:
                yield c

    for child in blocks(body):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            texts = []
            for t in child.iter(qn("w:t")):
                texts.append(t.text or "")
            out.append(Para("table", " ".join(texts)))
            continue
        if tag != "p":
            continue
        text = "".join(t.text or "" for t in child.iter(qn("w:t"))).strip()
        style = ""
        ppr = child.find(qn("w:pPr"))
        ilvl = None
        if ppr is not None:
            ps = ppr.find(qn("w:pStyle"))
            if ps is not None:
                sid = ps.get(qn("w:val")) or ""
                style = style_names.get(sid, sid)
            numpr = ppr.find(qn("w:numPr"))
            if numpr is not None:
                il = numpr.find(qn("w:ilvl"))
                ilvl = int(il.get(qn("w:val"))) if il is not None else 0
        m = re.match(r"(?:heading|Heading)\s*(\d)", style)
        if not text and not (m and m.group(1) == "1"):
            continue  # keep empty Heading 1s so Section<N> matches the csa_docx framework
        if m:
            out.append(Para("heading", text, int(m.group(1))))
        elif style.lower() == "title":
            out.append(Para("heading", text, 0))
        elif ilvl is not None or "list" in style.lower():
            lvl = ilvl if ilvl is not None else (1 if re.search(r"2|3", style) else 0)
            out.append(Para("bullet", text, lvl))
        else:
            out.append(Para("text", text))
    return out


def read_markdown(path: Path) -> list[Para]:
    out: list[Para] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        line = raw.rstrip()
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            out.append(Para("heading", m.group(2).strip(), len(m.group(1))))
            continue
        if line.lstrip().startswith("|"):
            out.append(Para("table", line.strip("| ")))
            continue
        m = re.match(r"^(\s*)(?:[-*+]|\d+\.)\s+(.*)", line)
        if m:
            out.append(Para("bullet", m.group(2).strip(), len(m.group(1).replace("\t", "    ")) // 2 and 1))
            continue
        out.append(Para("text", line.strip().lstrip("> ")))
    return out


# ---------------------------------------------------------------- analysis
def split_sections(paras: list[Para]) -> list[Section]:
    sections: list[Section] = []
    cur = Section(0, "(before first Heading 1)")
    for p in paras:
        if p.kind == "heading" and p.level == 1:
            if cur.paras or cur.index:
                sections.append(cur)
            cur = Section(len([s for s in sections if s.index]) + 1, p.text)
            continue
        cur.paras.append(p)
    sections.append(cur)
    return [s for s in sections if s.index or s.paras]


def words(t: str) -> int:
    return len(re.findall(r"\b\w[\w'.-]*\b", t))


def analyse(sec: Section, max_words: int) -> dict:
    prose = [p for p in sec.paras if p.kind in ("text", "bullet")]
    bullets = [p for p in prose if p.kind == "bullet"]
    headings = [p for p in sec.paras if p.kind == "heading"]
    prose_words = sum(words(p.text) for p in prose)
    table_words = sum(words(p.text) for p in sec.paras if p.kind == "table")

    nested = [p.text for p in bullets if p.level > 0]
    fragments = [p.text for p in bullets if words(p.text) <= 3]

    lead_ins = []
    for i, p in enumerate(sec.paras[:-1]):
        nxt = sec.paras[i + 1]
        if p.kind in ("text", "bullet") and p.text.endswith(":") and nxt.kind == "bullet":
            lead_ins.append(p.text)

    connectors = []
    for p in prose:
        for m in CONNECTOR_RE.finditer(p.text):
            connectors.append(m.group(0))

    idents: Counter = Counter()
    for p in prose:
        seen = set()
        for rx in IDENT_RES:
            for m in rx.finditer(p.text):
                tok = m.group(0).lower()
                if tok not in seen:
                    idents[tok] += 1
                    seen.add(tok)
    repeated_idents = {k: v for k, v in idents.items() if v > 3}

    sents: Counter = Counter()
    for p in prose:
        for s in SENTENCE_SPLIT_RE.split(p.text):
            n = re.sub(r"\W+", " ", s.lower()).strip()
            if words(n) >= 6:
                sents[n] += 1
    repeated_sents = [s for s, c in sents.items() if c > 1]

    ev_ids = [m.group(0) for p in prose for m in EVIDENCE_ID_RE.finditer(p.text)]
    ev_files = [m.group(0) for p in prose for m in EVIDENCE_FILE_RE.finditer(p.text)]
    noisy_headings = [h.text for h in headings if HEADING_NOISE_RE.search(h.text)]
    placeholder_headings = [h.text for h in headings if PLACEHOLDER_HEADING_RE.search(h.text)]

    # readability
    ips = [m.group(0) for p in prose for m in IP_RE.finditer(p.text)]
    sentences = [s for p in prose for s in SENTENCE_SPLIT_RE.split(p.text) if words(s) >= 3]
    long_sents = [s for s in sentences if words(s) > MAX_SENTENCE_WORDS]
    avg_sent = (sum(words(s) for s in sentences) / len(sentences)) if sentences else 0.0
    dense_paras, porty_paras, hedgy_paras = [], [], []
    inferred: list[str] = []
    for p in prose:
        ids = set()
        for rx in IDENT_RES:
            ids.update(m.group(0).lower() for m in rx.finditer(p.text))
        ports = PORT_RE.findall(p.text)
        ids.update(x.lower() for x in ports)
        if len(ids) > MAX_IDENTIFIERS_PER_PARA:
            dense_paras.append(p.text[:60])
        if len(ports) > MAX_PORTS_PER_PARA:
            porty_paras.append(p.text[:60])
        if len(HEDGE_RE.findall(p.text)) > MAX_HEDGES_PER_PARA:
            hedgy_paras.append(p.text[:60])
        for m in INFERENCE_RE.finditer(p.text):
            inferred.append(m.group(0).lower())

    share = (len(bullets) / len(prose)) if prose else 0.0
    warns = []
    if inferred:
        warns.append(f"inference wording ({', '.join(sorted(set(inferred)))}); state what the evidence shows, or move the conclusion to an open question")
    if ips:
        warns.append(f"{len(ips)} IP addresses or subnets in prose; move them to the discovery table or appendix")
    if dense_paras:
        warns.append(f"{len(dense_paras)} paragraphs name more than {MAX_IDENTIFIERS_PER_PARA} identifiers (hosts, addresses, ports); name components by role and put the detail in a table")
    if porty_paras:
        warns.append(f"{len(porty_paras)} paragraphs give more than {MAX_PORTS_PER_PARA} port number; keep a port only where it is the point")
    if long_sents:
        warns.append(f"{len(long_sents)} sentences over {MAX_SENTENCE_WORDS} words; split them")
    if avg_sent > MAX_AVG_SENTENCE_WORDS:
        warns.append(f"average sentence is {avg_sent:.0f} words (target {MAX_AVG_SENTENCE_WORDS} or fewer)")
    if hedgy_paras:
        warns.append(f"{len(hedgy_paras)} paragraphs carry more than {MAX_HEDGES_PER_PARA} hedges; state what is unknown once, at the end")
    if prose_words > max_words:
        warns.append(f"prose is {prose_words} words (budget {max_words}); cut restatement first")
    if share > 0.40 and len(prose) >= 8:
        warns.append(f"{share:.0%} of prose paragraphs are bullets (limit 40%)")
    if nested:
        warns.append(f"{len(nested)} nested bullets (none allowed)")
    if len(fragments) >= 3:
        warns.append(f"{len(fragments)} bullet fragments of <=3 words")
    if len(lead_ins) >= 2:
        warns.append(f"{len(lead_ins)} lead-in lines ending ':' that split a sentence across bullets")
    if connectors:
        warns.append(f"{len(connectors)} announcing connectors / stock phrases")
    if repeated_idents:
        warns.append(f"{len(repeated_idents)} identifiers stated in >3 prose paragraphs")
    if repeated_sents:
        warns.append(f"{len(repeated_sents)} sentences repeated verbatim")
    if ev_ids:
        warns.append(f"{len(ev_ids)} evidence IDs in body prose")
    ev_subject = [m.group(0) for p in prose for m in EVIDENCE_SUBJECT_RE.finditer(p.text)]
    if ev_files:
        warns.append(f"{len(ev_files)} evidence file names in body prose")
    if ev_subject:
        warns.append(f"{len(ev_subject)} evidence-as-subject passages (the sentence is about the data, not the system; rewrite around the application/component it tells us about)")
    if noisy_headings:
        warns.append(f"{len(noisy_headings)} headings carry evidence-label suffixes")
    if placeholder_headings:
        warns.append(f"{len(placeholder_headings)} placeholder/unfinished headings")

    return {
        "section": sec.index,
        "title": sec.title,
        "prose_words": prose_words,
        "table_words": table_words,
        "prose_paragraphs": len(prose),
        "bullet_share": round(share, 2),
        "nested_bullets": len(nested),
        "bullet_fragments": len(fragments),
        "lead_ins": len(lead_ins),
        "connectors": Counter(c.lower() for c in connectors).most_common(),
        "repeated_identifiers": sorted(repeated_idents.items(), key=lambda kv: -kv[1]),
        "repeated_sentences": repeated_sents[:5],
        "evidence_ids_in_prose": ev_ids[:10],
        "evidence_files_in_prose": sorted(set(ev_files))[:10],
        "noisy_headings": noisy_headings,
        "placeholder_headings": placeholder_headings,
        "ip_addresses_in_prose": ips[:10],
        "long_sentences": len(long_sents),
        "avg_sentence_words": round(avg_sent, 1),
        "dense_paragraphs": dense_paras[:5],
        "warnings": warns,
        "status": "WARN" if warns else "PASS",
    }


def doc_checks(sections: list[Section]) -> list[str]:
    warns = []
    titles = Counter(re.sub(r"\s+", " ", s.title.strip().lower()) for s in sections if s.index and s.title.strip())
    dups = [t for t, c in titles.items() if c > 1]
    if dups:
        warns.append(f"duplicate Heading 1 titles: {', '.join(dups)}")
    h2 = {re.sub(r"\s+", " ", p.text.strip().lower()) for s in sections for p in s.paras if p.kind == "heading" and p.level == 2}
    clash = [t for t in titles if t in h2]
    if clash:
        warns.append(f"same title used as Heading 1 and Heading 2: {', '.join(clash)}")
    summaries = [p.text for s in sections for p in s.paras if p.kind == "heading" and p.level <= 3 and re.search(r"summary|overview", p.text, re.I)]
    summaries += [s.title for s in sections if s.index and re.search(r"summary|overview", s.title, re.I)]
    if len(summaries) > 3:
        warns.append(f"{len(summaries)} summary/overview headings ({'; '.join(summaries[:6])}) -- check for overlapping summaries")
    return warns


# ---------------------------------------------------------------- output
def print_report(path: Path, results: list[dict], dwarns: list[str]) -> None:
    total = sum(r["prose_words"] for r in results)
    print(f"prose_lint: {path.name}")
    print(f"prose words: {total}   sections: {len(results)}   "
          f"WARN sections: {sum(r['status'] == 'WARN' for r in results)}")
    for w in dwarns:
        print(f"  DOC WARN: {w}")
    print()
    print(f"{'S':>3}  {'words':>5}  {'bul%':>4}  {'nest':>4}  {'conn':>4}  {'rep':>3}  status  title")
    for r in results:
        print(f"{r['section']:>3}  {r['prose_words']:>5}  {r['bullet_share']*100:>3.0f}%  {r['nested_bullets']:>4}  "
              f"{len(r['connectors']):>4}  {len(r['repeated_identifiers']):>3}  {r['status']:<6}  {r['title'][:60]}")
    for r in results:
        if not r["warnings"]:
            continue
        print(f"\n[Section {r['section']}] {r['title']}")
        for w in r["warnings"]:
            print(f"  - {w}")
        if r["connectors"]:
            print("    connectors: " + ", ".join(f"'{c}' x{n}" for c, n in r["connectors"][:6]))
        if r["repeated_identifiers"]:
            print("    repeated: " + ", ".join(f"{k} x{v}" for k, v in r["repeated_identifiers"][:6]))
        if r["noisy_headings"]:
            print("    headings: " + "; ".join(r["noisy_headings"][:4]))
        if r["placeholder_headings"]:
            print("    placeholders: " + "; ".join(r["placeholder_headings"][:4]))
        if r["evidence_files_in_prose"]:
            print("    files: " + ", ".join(r["evidence_files_in_prose"][:6]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--section", type=int)
    ap.add_argument("--heading", help="select the Heading 1 section whose title starts with this text (case-insensitive); safer than --section when the document has empty or hidden Heading 1s")
    ap.add_argument("--max-words", type=int, default=900)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    path = Path(a.path)
    if not path.exists():
        sys.exit(f"not found: {path}")
    paras = read_docx(path) if path.suffix.lower() in (".docx", ".dotx") else read_markdown(path)
    sections = split_sections(paras)
    if not any(s.index for s in sections):  # a draft with no H1: treat whole file as one section
        sections = [Section(1, path.stem, paras)]
    dwarns = doc_checks(sections) if a.section is None and not a.heading else []
    if a.heading:
        chosen = [s for s in sections if s.index and s.title.strip().lower().startswith(a.heading.strip().lower())]
        if not chosen:
            sys.exit(f"no Heading 1 section titled '{a.heading}'")
    else:
        chosen = [s for s in sections if s.index and (a.section is None or s.index == a.section)]
    if a.section is not None and not chosen:
        sys.exit(f"no Heading 1 section {a.section}")
    results = [analyse(s, a.max_words) for s in chosen]
    if a.json:
        print(json.dumps({"file": str(path), "document_warnings": dwarns, "sections": results}, indent=2))
    else:
        print_report(path, results, dwarns)
    if a.strict and (dwarns or any(r["status"] == "WARN" for r in results)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
