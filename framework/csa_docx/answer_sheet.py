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
on the card (or were appended by this run), a basis of observed / documented / stated (background for a K- knowledge passage), hosts in a fact's
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

_BLOCK = re.compile(r"^##\s+([BCF]\d+)\b[^\n]*$", re.M)
_FIELD = re.compile(r"^(Facts|Summary|Story|Text|Unknown|Rating reason|Rating|Rows|Bullets|Search|Keep|Answer|Dropped|Covers|None):\s*(.*)$", re.I)
_PFX = r"(?:[a-z0-9][a-z0-9-]*:)?"                # another project's row: utcdtc:E-041 (estate member or system sibling)
_ID = r"(?:" + _PFX + r"E-\d+|K-[0-9A-F]{6})"
_FACT = re.compile(r"^[-*]\s+(?P<text>.+?)\s*(?:\((?P<ids>" + _ID + r"(?:\s*,\s*" + _ID + r")*)\))?\s*(?:\{(?P<meta>[^}]*)\})?\s*$")
_EID = re.compile(r"(?<![\w:-])" + _PFX + r"E-\d+\b")
_XID = re.compile(r"^([a-z0-9][a-z0-9-]*):E-\d+$", re.I)   # a prefixed (other project's) ID
_KID = re.compile(r"\bK-[0-9A-F]{6}\b")           # background knowledge passages, never evidence (knowledge.py)
_QWORD = re.compile(r"\b(whether|which|what|how|where|who|when)\b", re.I)   # question clauses in an Unknown line
# not separate questions: ", which the network owner could confirm" (who can answer) and "to which servers" (a relative)
_QRELATIVE = re.compile(r",\s*(?:which|who)\b[^,]*?\b(?:could|can|would|will|should|may|must)\s+(?:confirm|answer|say|tell|"
                        r"provide|check|verify)\b[^,]*$|\b(?:to|of|in|from|on|at|by|for|with|through|under|behind)\s+which\b", re.I)
_ANYID = re.compile(r"(?<![\w:-])" + _ID + r"\b")
_HOST = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")
BASES = ("observed", "documented", "stated", "background")


# ---------------------------------------------------------------- parse

def parse(text: str) -> dict[str, dict]:
    """{question id: {facts: [...], unknown, rating, rating_reason, rows: [[...]], bullets: [...], search: [...], keep}}"""
    out: dict[str, dict] = {}
    marks = list(_BLOCK.finditer(text))
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        b = {"facts": [], "unknown": [], "rating": "", "rating_reason": "", "rows": [], "bullets": [],
             "search": [], "keep": "", "answer": "", "summary": "", "story": "", "text": "",
             "dropped": [], "none": "", "covers": [], "raw": body.strip()}
        if m.group(1).startswith("F"):          # the analysis frame: one line per slot, blocks or Unknown:
            b["frame"] = {}
            for line in body.splitlines():
                fm = re.match(r"^\s*[-*]?\s*(S\d+)\s*:\s*(.+?)\s*$", line)
                if fm:
                    b["frame"][fm.group(1)] = fm.group(2)
                    u = re.match(r"(?i)unknown:\s*(.+)$", fm.group(2))
                    if u:
                        b["unknown"].append(u.group(1).strip())
            out[m.group(1)] = b
            continue
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
                elif field == "dropped" and val:
                    b["dropped"].append(val)
                elif field == "covers":            # the evidence of findings this block raises as Unknown (framework-written)
                    b["covers"] += [i.upper() for i in _EID.findall(val)]
                elif field == "rating":
                    b["rating"] = val
                elif field == "rating reason":
                    b["rating_reason"] = val
                elif field == "search" and val:
                    b["search"].append(val)
                elif field == "keep":
                    b["keep"] = val or "yes"
                elif field == "none":                # note questions: nothing the table cannot show, remove the placeholder
                    b["none"] = val or "yes"
                elif field == "answer":
                    b["answer"] = val
                elif field in ("summary", "story") and val:
                    b[field] = b[field] + ("\n\n" if b[field] else "") + val
                elif field == "text" and val:     # one Text: line per paragraph adds a paragraph, never replaces
                    b["text"] = b["text"] + ("\n\n" if b["text"] else "") + val
                continue
            if field in ("summary", "story", "text"):
                b[field] = b[field] + ("\n\n" if b[field] else "") + s
                continue
            if field == "facts" and s.startswith(("-", "*")):
                fm = _FACT.match(s)
                meta = (fm.group("meta") or "") if fm else ""
                basis, _, scope = meta.partition(";")
                b["facts"].append({"text": (fm.group("text") if fm else s.lstrip("-* ")).strip(),
                                   "ids": _ANYID.findall(fm.group("ids") or "") if fm else _ANYID.findall(s),
                                   "basis": basis.strip().lower(), "scope": scope.strip(), "line": s})
            elif field == "rows" and (s.startswith("|") or len(re.split(r"\s*\|\s*", s)) == 3):
                raw = s if s.startswith("|") else "| " + s + " |"      # a row without pipe markers still answers the block
                cells = [c.strip() for c in raw.strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    b["rows"].append(cells)
            elif field == "bullets" and s.startswith(("-", "*")):
                b["bullets"].append(s.lstrip("-* ").strip())
            elif field == "unknown":
                b["unknown"].append(s.lstrip("-* "))
            elif field == "dropped":
                b["dropped"].append(s.lstrip("-* "))
            elif field == "search":
                b["search"].append(s.lstrip("-* "))
            elif field in ("rating reason",):
                b["rating_reason"] = (b["rating_reason"] + " " + s).strip()
        if b["story"] and not b["text"]:
            b["text"] = b["story"]          # existing prose-quality checks apply to the detailed story
        out[m.group(1)] = b
    return out


# ---------------------------------------------------------------- validate

def load_matrix(path: Path | None) -> dict[str, dict]:
    """This project's rows (E-nnn), plus the rows of the projects it may cite as <PROJECT>:E-nnn (estate members
    and system siblings, csa_docx.estate.citable_projects). Keys are upper case."""
    if not path or not Path(path).is_file():
        return {}
    from csa_docx import modelstore
    out = {r["evidence_id"].upper(): r for r in modelstore.read_csv(Path(path))}
    try:
        from csa_docx.estate import peer_rows
    except ImportError:
        return out
    out.update({k.upper(): v for k, v in peer_rows(Path(path).parent).items()})
    return out


def _prefix(i: str) -> str | None:
    m = _XID.match(i or "")
    return m[1].lower() if m else None


def _f(level: str, code: str, qid: str | None, message: str) -> dict:
    return {"level": level, "code": code, "question": qid, "message": message}



# A fact whose subject is the source (matrix, capture, host map, previous assessment) instead of the system.
_SOURCE_SUBJECT = re.compile(
    r"^\s*(?:the|these|this|a|an)?\s*(?:capture'?s?|captures|system matrix|evidence matrix|matrix|host map|target host map|"
    r"previous assessment|prior assessment|discovery (?:data|table|set|package|output)|spreadsheet|workbook|"
    r"current evidence|evidence|supplied data|document|register|index)\b[^.]{0,80}?\b"
    r"(?:records?|lists?|shows?|places?|contains?|notes?|states?|indicates?|identifies?|gives?|confirms?|describes?|has|holds?)\b",
    re.IGNORECASE)

# Wording about how the framework looked (the evidence matrix, the discovery index, the rows it searched) instead
# of about the system. The reader of the assessment never sees those; say what the system lacks, and where the
# sources were looked at (the captures and the supplied documents).
_PROCESS_WORDING = re.compile(
    r"\b(?:evidence matrix|discovery index|gap lookup|index rows?|matrix rows?|matrix (?:and|or) (?:the )?index|"
    r"(?:the )?(?:matrix|index) (?:search|lookup)|(?:search|lookup)(?:es)? of the (?:evidence )?(?:matrix|index)|"
    r"rows? (?:searched|reviewed|examined)|(?:searched|searching) the (?:evidence )?(?:matrix|index)|"
    r"(?:matrix|index) (?:rows? )?(?:searched|reviewed|examined)|for this domain|"
    r"(?:on|in|from|to) (?:the|this) (?:section )?card|section card|evidence pack|card's|answer sheet|"
    r"(?:not )?(?:stated|listed|shown|given|offered) (?:on|in) the card)\b", re.IGNORECASE)

_NUMWORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
             "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUM = re.compile(r"\b(\d{1,3}|" + "|".join(_NUMWORDS) + r")\b(?!\.\d)", re.IGNORECASE)
_HOSTNAME = re.compile(r"\b[A-Z]{3}PRD[A-Z]{3}\d{3}\b")


def _n(tok: str) -> int:
    return int(tok) if tok.isdigit() else _NUMWORDS[tok.lower()]


def count_mismatch(text: str) -> str | None:
    """'twelve hosts ...: two jump hosts, one server, six nodes' -> message when the parts do not add up.

    Only checked where a total is followed by a colon (or 'made up of' / 'comprising') and at least two counts."""
    m = re.search(r":|\bmade up of\b|\bcomprising\b|\bconsisting of\b", text)
    if not m:
        return None
    head = [x for x in _NUM.finditer(text[:m.start()])
            if not re.match(r"[\d.]", text[x.end():x.end() + 1] or " ")
            and not re.search(r"\b(?:port|ports|version|line|instance|vlan|site|row)\s*$", text[:x.start()], re.IGNORECASE)
            and _n(x.group(1)) <= 500]
    tail = [_n(x.group(1)) for x in _NUM.finditer(text[m.end():].split(".")[0])]
    if not head or len(tail) < 2:
        return None
    total = _n(head[-1].group(1))
    if sum(tail) != total:
        return f"the parts add up to {sum(tail)}, not {total}"
    return None


#: Draft lane (pre-V1): only these stop a sheet from being written into the document; every other ERROR is
#: reported as a WARN and left for the next pass or the V1 change lane.
HARD_CODES = {"CROSS_PROJECT_ONLY", "NOTE_TOO_LONG", "NOTE_NONE_AND_TEXT", "NOTE_NO_FACTS", "CAPTURE_DROPPED", "UNKNOWN_BUNDLED", "BACKGROUND_AS_EVIDENCE", "BACKGROUND_MIXED", "BACKGROUND_NOT_ON_CARD", "BACKGROUND_ALONE", "QUESTION_MISSING", "EMPTY_ANSWER", "FACT_NO_EVIDENCE", "UNKNOWN_EVIDENCE", "RATING_INVALID",
              "COLUMNS", "ROW_WIDTH", "NO_ROWS", "REQUIREMENT_NO_FACTS", "SEMICOLON", "PROCESS_AS_SUBJECT",
              "CITATION_OFF_TOPIC", "NO_TOTALS", "ROLE_TABLE_REPEAT", "FRAME_UNCOVERED", "ATTEMPT_AS_ESTABLISHED",
              "SLOT_NOT_ANSWERED", "FLOW_NOT_COVERED", "ZONE_CONTRADICTED", "PART_NOT_NAMED", "ISOLATION_WRONG_SIDE",
              "PART_MISATTRIBUTED", "CITED_AND_DROPPED", "LABEL_AS_NAME", "PART_NAME_LIST", "SUBJECT_NOT_THIS_SYSTEM",
              "PRACTICE_NOT_ADDRESSED", "PRACTICE_ATTRIBUTION_DROPPED", "APPLICATION_ZONE_CLAIM",
              "DRAWBRIDGE_CAUSAL_SCOPE",
              "EXAMPLE_COPIED", "SUMMARY_MISSING", "STORY_MISSING", "SUMMARY_TOO_LONG", "SUMMARY_TOO_MANY_SENTENCES",
              "SUMMARY_REPEATS_STORY", "STORY_AND_TEXT"}

#: Relaxed draft lane (cli.yaml draft_strictness: relaxed, the default for csa answer): the answer's job is to answer the
#: question from the evidence, so only what makes it wrong or unusable stops it: evidence it cannot cite, a missing or
#: invalid answer, a table that cannot be rendered, background used as evidence, a host put on the wrong side of OT, a
#: false isolation claim, an attempt reported as established, another project's evidence as the only basis, and owed
#: findings or kept facts silently lost. Wording, naming and style findings are warnings, and so is naming another
#: application (IAMPS consumes what this system produces: the text may say so).
RELAXED_HARD = {"CROSS_PROJECT_ONLY", "QUESTION_MISSING", "EMPTY_ANSWER", "FACT_NO_EVIDENCE", "UNKNOWN_EVIDENCE",
                "RATING_INVALID", "COLUMNS", "ROW_WIDTH", "NO_ROWS", "BACKGROUND_AS_EVIDENCE", "BACKGROUND_MIXED",
                "BACKGROUND_NOT_ON_CARD", "BACKGROUND_ALONE", "ZONE_CONTRADICTED", "ISOLATION_WRONG_SIDE",
                "ATTEMPT_AS_ESTABLISHED", "SLOT_NOT_ANSWERED", "CAPTURE_DROPPED", "SUMMARY_MISSING", "STORY_MISSING",
                "SUMMARY_TOO_LONG", "SUMMARY_TOO_MANY_SENTENCES", "SUMMARY_REPEATS_STORY", "STORY_AND_TEXT",
                "DRAWBRIDGE_CAUSAL_SCOPE"}

# counts and totals of hosts ("9 of 12", "all 12 captured hosts", "nine hosts", "two RevViewer Jump Hosts"): CSA text
# names the role groups instead. "stratum 5 hosts" and port numbers are not counts.
_NUMWORD = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|twenty)"
_TOTALS = re.compile(r"\b\d+\s+of\s+(?:the\s+)?\d+\b|(?<!stratum )(?<!port )(?<!ports )\b" + _NUMWORD +
                     r"\s+(?:[A-Za-z/-]+\s+){0,3}?(?:hosts?|servers?|nodes?|machines?)\b(?!-)", re.I)


def totals_in(text: str) -> str | None:
    """The first host count or total in ``text`` (None when there is none)."""
    m = _TOTALS.search(text or "")
    return m.group(0) if m else None


def frame_checks(sheet: dict[str, dict], card: dict) -> list[dict]:
    """FRAME_UNCOVERED: every slot of the card's analysis frame needs a line in the F1 block naming an answered
    block, or Unknown:. FLOW_NOT_COVERED (warning): a cross-zone data flow the frame found is named nowhere."""
    fr = card.get("frame") or {}
    slots = fr.get("slots") or []
    if not slots:
        return []
    fb = next((b for k, b in sheet.items() if k.startswith("F")), None)
    out = slot_answers(sheet, fr, fb)
    if fr.get("must_address"):
        slots = []                  # the requirement blocks answer the slots themselves: the F1 block is optional
    elif fb is None:
        return [_f("ERROR", "FRAME_UNCOVERED", None, f"no '## F1 Analysis frame' block: give every slot of the card's analysis "
                   f"frame ({', '.join(slots)}) a line naming the blocks that answer it, or Unknown: <what is not known>")]
    bad = []
    for s in slots:
        v = (fb.get("frame") or {}).get(s, "")
        if not v:
            bad.append(f"{s} has no line")
            continue
        if re.match(r"(?i)unknown:\s*\S", v):
            continue
        refs = re.findall(r"\b([BC]\d+)\b", v)
        ok = [r for r in refs if r in sheet and (sheet[r]["facts"] or sheet[r]["rows"] or sheet[r]["bullets"]
                                                  or sheet[r].get("text") or sheet[r]["keep"])]
        if not ok:
            bad.append(f"{s} names no answered block ({v[:40]})")
    if bad:
        out.append(_f("ERROR", "FRAME_UNCOVERED", "F1", "; ".join(bad) + ": name the B blocks that answer each slot, "
                      "or write Unknown: <what is not known>"))
    out += flow_coverage(sheet, card)
    out += zone_contradictions(sheet, card)
    out += rating_floor(sheet, card)
    out += part_checks(sheet, card)
    out += application_checks(sheet, card)
    out += chain_checks(sheet, card)
    return out


_HEDGE = re.compile(r"\b(?:may (?:also )?(?:stop|lose|be lost)|if (?:their|its|the) paths?|depends? on unresolved|"
                    r"might (?:stop|lose))\b", re.I)
_LOSS = re.compile(r"\b(?:lose|loses|losing|lost|stops?|is cut|are cut|cut off|no longer)\b", re.I)
_EVERY_PART = re.compile(r"\b(?:every|all)(?: other)? parts?\b", re.I)


_THIS_SYSTEM = re.compile(r"\b(?:this|the) system\b", re.I)
_ISOLATING = re.compile(r"\bisolat|\bunreachable\b|\bloses?\b|\blost\b", re.I)


def subject_checks(sheet: dict[str, dict], card: dict) -> list[dict]:
    """SUBJECT_NOT_THIS_SYSTEM (hard): a sentence, table row or bullet that names another application (a neighbour
    or a same-system sibling, card "parts" "foreign": its name or a host of it) but no part or host of this system.
    Each CSA describes its own application: another application appears only where this system meets it (a flow
    between a part of this system and that application), never on its own. In the Drawbridge Impact (narrative) a
    sentence about what is lost or cut when OT is isolated may name it among the links that stop."""
    from csa_docx.parts import named
    pc = card.get("parts") or {}
    foreign = pc.get("foreign") or {}
    if not foreign:
        return []
    hosts = pc.get("hosts") or {}
    own = list(hosts) + [n for pid in set(hosts.values()) for n in (pc.get("names") or {}).get(pid, [])]
    kinds = {q["id"]: q["kind"] for q in card.get("questions", [])}
    out = []
    for qid, b in sheet.items():
        if kinds.get(qid) == "comment":
            continue
        pieces = [f["text"] for f in b.get("facts", [])] + list(b.get("bullets") or [])
        pieces += [" | ".join(r) for r in (b.get("rows") or [])[1:]]
        pieces += [s for t in (b.get("text") or "", b.get("rating_reason") or "") for s in re.split(r"(?<=[.!?])\s+|\n+", t)]
        for s in (x for x in pieces if x and x.strip()):
            if kinds.get(qid) == "narrative" and (_LOSS.search(s) or _ISOLATING.search(s)):
                continue                    # the Drawbridge Impact: a link this system loses when OT is isolated
            hit = [v["application"] for v in foreign.values() if named(s, v["names"])]
            if hit and not named(s, own) and not _THIS_SYSTEM.search(s):
                out.append(_f("ERROR", "SUBJECT_NOT_THIS_SYSTEM", qid,
                              f"this is about {', '.join(dict.fromkeys(hit))}, another application with its own CSA: "
                              f"name it only where it meets a part of this system (which part, what moves), or leave "
                              f"it out: \"{s[:150]}\""))
                break
    return out


_FUNCTION_EFFECT = re.compile(
    r"\b(?:stops?|stopped|lose|loses|lost|unavailable|keeps? working|remain(?:s)? available)\b",
    re.IGNORECASE,
)


def drawbridge_topic_checks(sheet: dict[str, dict], card: dict) -> list[dict]:
    """Keep every requirement-domain Drawbridge narrative causal and in scope."""
    from csa_docx import scope_map
    domain = scope_map.for_section(card.get("number", ""), card.get("title", ""))
    if not domain or domain["key"] == "3.12":
        return []
    drawbridge_ids = {
        q["id"] for q in card.get("questions", [])
        if q.get("kind") == "narrative" and "drawbridge" in str(q.get("text") or "").lower()
    }
    out: list[dict] = []
    for qid, block in sheet.items():
        if qid not in drawbridge_ids:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", block.get("text") or ""):
            if not sentence.strip() or not _FUNCTION_EFFECT.search(sentence):
                continue
            if scope_map.dependency_matches(sentence, domain):
                continue
            out.append(_f(
                "ERROR",
                "DRAWBRIDGE_CAUSAL_SCOPE",
                qid,
                f"a {domain['title']} Drawbridge effect does not name a {domain['title']} cause. Describe only what "
                "loss or unavailability of this domain changes, or move the generic isolation consequence to its "
                f"owning domain: {sentence[:150]}",
            ))
    return out


def part_checks(sheet: dict[str, dict], card: dict) -> list[dict]:
    """The system-part checks (card "parts", from csa-work/parts.json):
    PART_NOT_NAMED (an error when the frame is strict, else a warning): a requirement's Facts name every part the card
    lists under it, by name, short name or, for a dependency, an address. HOST_IN_TEXT (warning): a requirement or narrative Text names a host of the
    system instead of its part. ISOLATION_WRONG_SIDE (hard): a sentence says a part outside OT loses something when
    OT is isolated, but names only what it keeps (its flows that never touch OT), none of its paths into OT.
    PART_MISATTRIBUTED (an error when the frame is strict, else a warning): a requirement or narrative sentence
    names a system part together with a kind of fact (shares, removable storage, transfer tools, the proxy, SMB or
    backup-agent connections) that no finding shows on any of that part's machines: naming a part does not make a
    fact about another part true of it."""
    from csa_docx.parts import FEATURES, named, parts_in
    pc = card.get("parts") or {}
    if not pc:
        return []
    strict = bool((card.get("frame") or {}).get("strict"))
    kinds = {q["id"]: q["kind"] for q in card.get("questions", [])}
    out = []
    for qid, pids in (pc.get("owed") or {}).items():
        b = sheet.get(qid)
        if not b or not pids:
            continue
        facts = " ".join(f["text"] for f in b.get("facts") or [])
        missing = [pc["parts"][p] for p in pids if not named(facts, pc["names"].get(p, []))]
        if missing:
            out.append(_f("ERROR" if strict else "WARN", "PART_NOT_NAMED", qid,
                          f"the Facts do not name these parts, which this requirement's findings are about: "
                          f"{', '.join(missing)}. Name each (see System parts on the card)"))
    hosts = pc.get("hosts") or {}
    for qid, b in sheet.items():
        if kinds.get(qid) in ("requirement", "narrative") and b.get("text"):
            hit = [h for h in hosts if re.search(rf"\b{re.escape(h)}\b", b["text"], re.I)]
            if hit:
                out.append(_f("WARN", "HOST_IN_TEXT", qid, "name the part, not the host: "
                              + ", ".join(f"{h} is part of {pc['parts'][hosts[h]]}" for h in hit[:4])))
    for qid, b in sheet.items():
        if kinds.get(qid) not in ("requirement", "narrative") or not b.get("text"):
            continue
        for pid, side in (pc.get("sides") or {}).items():
            if side != "outside":
                continue
            full = [n for n in pc["names"].get(pid, []) if re.match(r"(?:OT|IT)\s", n) and "," not in n]
            hit = next((n for n in full if re.search(rf"\b{re.escape(n)}\b", b["text"])), None)
            if hit and hit.startswith("OT "):
                out.append(_f("WARN", "NAME_CONTRADICTS_ZONE", qid,
                              f"{hit} is outside OT, so its OT-prefixed role name misleads: write \"the IT-hosted "
                              f"{hit[3:]}\" instead"))
    for qid, b in sheet.items():
        prose = [b.get("text") or "", b.get("rating_reason") or ""] + [f["text"] for f in b["facts"]]
        for pid, nm in pc["parts"].items():
            if pid in set(hosts.values()) and "," in nm and any(nm in s for s in prose):
                out.append(_f("ERROR", "PART_NAME_LIST", qid,
                              f"\"{nm}\" is one part with two roles, and the comma list reads as two things: write "
                              f"\"{nm.split(',')[0].strip()}\" in a sentence"))
        for lab in pc.get("labels") or []:
            if any(re.search(rf"\b{re.escape(lab['label'])}\b", s, re.I) for s in prose):
                out.append(_f("ERROR", "LABEL_AS_NAME", qid,
                              f"\"{lab['label']}\" is a label, not a name: write \"{lab['plain']}\" in a sentence"))
    feats = pc.get("features") or {}
    system = {pid for pid in pc.get("names", {}) if pid in set(hosts.values())}
    for qid, b in sheet.items():
        if kinds.get(qid) not in ("requirement", "narrative") or not feats:
            continue
        # one clause at a time: "X does A, while Y does B" says A of X and B of Y
        for s in re.split(r"(?<=[.!?])\s+|\n+|,?\s+(?:while|whereas|but|although)\s+|;\s*",
                          (b.get("text") or "") + "\n" + (b.get("rating_reason") or "")):
            said = [k for k, (rx, _, _) in FEATURES.items() if k in feats and re.search(rx, s, re.I)]
            if not said:
                continue
            ok_parts = {pid for k in said for pid in feats[k]}
            wrong = sorted(pc["parts"][pid] for pid in parts_in(s, {k: v for k, v in pc["names"].items() if k in system})
                           if pid not in ok_parts)
            if wrong:
                out.append(_f("ERROR" if strict else "WARN", "PART_MISATTRIBUTED", qid,
                              f"no finding shows {', '.join(said)} on {', '.join(wrong)}: say it only of the parts whose "
                              f"machines the findings name ({', '.join(sorted(pc['parts'][p] for p in ok_parts))}): \"{s[:170]}\""))
    for qid, b in sheet.items():
        if kinds.get(qid) != "narrative":
            continue
        for s in re.split(r"(?<=[.!?])\s+|\n+", b.get("text") or ""):
            if _HEDGE.search(s):
                out.append(_f("WARN", "DRAWBRIDGE_HEDGE", qid,
                              "say plainly what stops, what keeps working and what it means for operations; where a "
                              "path's zone is not recorded, say that once in an Unknown: line instead of \"if\" or \"may\" "
                              f"in the Text: \"{s[:140]}\""))
        texts = [b.get("text") or ""] + [f["text"] for f in b["facts"]]
        # one clause at a time: "its telemetry is not cut, but its paths into OT are lost" says the loss of one thing only
        for s in (s for t in texts for sent in re.split(r"(?<=[.!?])\s+", t)
                  for s in re.split(r",?\s+(?:but|while|whereas|although)\s+|;\s*", sent)):
            if not _LOSS.search(s):
                continue
            low = s.lower()
            for pid, iso in (pc.get("isolation") or {}).items():
                if pc["sides"].get(pid) != "outside" or not named(s, pc["names"].get(pid, [])):
                    continue
                own = set(re.findall(r"[a-z]{4,}", " ".join(pc["names"].get(pid, [])).lower()))   # the part's own name
                safe = [w for w in iso.get("safe", []) if w in low and w not in own]
                if safe and not any(w in low for w in iso.get("loss", []) if w not in own):
                    out.append(_f("ERROR", "ISOLATION_WRONG_SIDE", qid,
                                  f"{pc['parts'][pid]} is outside OT: isolating OT does not cut its {', '.join(safe[:3])} "
                                  f"paths, it {iso['effect'][:160]}: \"{s[:160]}\""))
                    break
    return out


_CLAIM_ZONE = re.compile(r"\b(?:in|within|inside|hosted in|sits in|sit in)\s+(?:the\s+)?(OT|IT)\b(?!\s+(?:isolation|isolated|is isolated))")


READ_WORDS = 45


def read_checks(sheet: dict[str, dict], card: dict) -> list[dict]:
    """The reading checks on a requirement or narrative Text (both warn, never block):
    READ_LONG: a sentence over 45 words (the S408 sentence that read badly was 49).
    READ_REPEAT: a part or application name used twice in one sentence (\"the RevBroadcast application server opens
    sessions to the RevBroadcast availability group\" says RevBroadcast twice)."""
    pc = card.get("parts") or {}
    names = sorted({n for ns in (pc.get("names") or {}).values() for n in ns} |
                   {n for a in pc.get("applications") or [] for n in a.get("names", [])}, key=len, reverse=True)
    names = [n for n in names if len(n) > 3]
    out = []
    for q in card.get("questions", []):
        b = sheet.get(q["id"])
        if not b or q["kind"] not in ("requirement", "narrative") or not b.get("text"):
            continue
        for sent in re.split(r"(?<=[.!?])\s+|\n+", b["text"]):
            words = len(sent.split())
            if words > READ_WORDS:
                out.append(_f("WARN", "READ_LONG", q["id"], f"a sentence of {words} words (over {READ_WORDS}): split it in two: \"{sent[:70]}...\""))
            rest = sent.lower()
            for n in names:
                k = len(re.findall(r"(?<!\w)" + re.escape(n.lower()) + r"(?!\w)", rest))
                if k >= 2:
                    out.append(_f("WARN", "READ_REPEAT", q["id"], f"\"{n}\" is used {k} times in one sentence: say it once and "
                                  f"refer back with 'it' or 'the same part': \"{sent[:70]}...\""))
                rest = re.sub(r"(?<!\w)" + re.escape(n.lower()) + r"(?!\w)", " ", rest)
    return out



_STORY_WORDS = 90
_RATING_FIRST = re.compile(r"\b(?:Met|Partially Met|Not Met|Not Applicable|meets|does not meet|partially meets)\b", re.I)
_ENDPOINT_GAP = re.compile(r"\bunidentified\b|\bnot identified\b|\bzone not recorded\b", re.I)


def readability_checks(sheet: dict[str, dict], card: dict) -> list[dict]:
    """Story and narrative readability checks (all warn, never block, the draft lane's relaxed checks):
    READ_LIST: a Story, Text or Summary sentence names more than 3 parts (parts.parts_in on the card's part names).
    STORY_NO_REASON: a requirement block's Story first sentence contains none of Met, Partially Met, Not Met,
    Not Applicable, meets, does not meet or partially meets.
    TWO_ROLE_NAME: a sentence contains ", also the " or ", also " followed by a part name, or the full "A, B"
    name of a two-role part.
    STORY_TOO_LONG: a Story is over 90 words.
    ENDPOINT_UNDERSTATED: a sentence says "unidentified", "not identified" or "zone not recorded" and names an end
    (or the part grouping it) that endpoints.load gives a name or zone.
    NARRATIVE_NEW_ENDPOINT: the Drawbridge Impact Text names a dependency part that no requirement block's Facts
    mention."""
    pc = card.get("parts") or {}
    if not pc:
        return []
    from csa_docx import parts as _parts
    from csa_docx import endpoints as _endpoints
    names = pc.get("names") or {}
    # card's parts view: {pid: name} when the card was built against a parts.json, else
    # {pid: {"names": [...], ...}} (the parts.json row directly)
    _pview = pc.get("parts") or {}
    parts_names: dict[str, str] = {}
    for _pid, _v in _pview.items():
        if isinstance(_v, dict):
            _n = _v.get("name") or (_v.get("names") or [None])[0]
        else:
            _n = _v
        if _n:
            parts_names[_pid] = str(_n)
    # full names of two-role parts: those with a comma in their display name
    two_role_full = sorted({nm for nm in parts_names.values() if "," in nm})
    out: list[dict] = []

    def _sentences(t: str) -> list[str]:
        return [s for s in re.split(r"(?<=[.!?])\s+|\n+", t or "") if s.strip()]

    def _parts_named(s: str) -> set[str]:
        return _parts.parts_in(s, names)

    # endpoint register: keyed by end upper-cased -> row with name/zone (empty without csa-work)
    ends: dict[str, dict] = {}
    for cand in (Path.cwd(), Path.cwd() / "csa-work"):
        if (cand / "hosts" / "endpoints.csv").is_file():
            ends = _endpoints.load(cand)
            break

    # build end tokens (the end itself, its name, its zone) to match in prose
    end_tokens: list[tuple[str, dict]] = []
    for endk, row in (ends or {}).items():
        nm = (row.get("name") or "").strip()
        zn = (row.get("zone") or "").strip()
        if not nm and not zn:
            continue
        end_tokens.append((endk, row))
        if nm:
            end_tokens.append((nm, row))
        if zn:
            end_tokens.append((zn, row))

    req_qids = [q for q in card.get("questions", []) if q.get("kind") == "requirement"]
    narr_qids = [q for q in card.get("questions", []) if q.get("kind") == "narrative"]

    # collect Facts text per requirement block (for NARRATIVE_NEW_ENDPOINT)
    req_facts_text = {}
    for q in req_qids:
        b = sheet.get(q["id"]) or {}
        req_facts_text[q["id"]] = " ".join((f.get("text") or "") for f in (b.get("facts") or []))

    # the Drawbridge Impact narrative Text (narrative kind)
    narrative_texts = {q["id"]: (sheet.get(q["id"]) or {}).get("text") or "" for q in narr_qids}

    for q in card.get("questions", []):
        b = sheet.get(q["id"])
        if not b:
            continue
        kind = q.get("kind")
        story = (b.get("story") or "")
        text = (b.get("text") or "")
        summary = (b.get("summary") or "")
        story_sentences = _sentences(story)

        # STORY_TOO_LONG
        if kind == "requirement" and story:
            words = len(" ".join(story.split()).split())
            if words > _STORY_WORDS:
                out.append(_f("WARN", "STORY_TOO_LONG", q["id"],
                              f"Story is {words} words (over {_STORY_WORDS}): keep it under {_STORY_WORDS} words"))

        # STORY_NO_REASON
        if kind == "requirement" and story_sentences:
            first = story_sentences[0]
            if not _RATING_FIRST.search(first):
                out.append(_f("WARN", "STORY_NO_REASON", q["id"],
                              "the Story's first sentence should state the rating and its deciding condition "
                              "(Met / Partially Met / Not Met / Not Applicable): \"" + first[:70] + "...\""))

        # READ_LIST, TWO_ROLE_NAME, ENDPOINT_UNDERSTATED
        if kind not in ("requirement", "narrative"):
            continue
        pieces: list[tuple[str, str]] = []
        if story:
            pieces += [("Story", s) for s in story_sentences]
        if summary:
            pieces += [("Summary", s) for s in _sentences(summary)]
        if text:
            pieces += [("Text", s) for s in _sentences(text)]

        for where, s in pieces:
            pids = _parts_named(s)
            # READ_LIST: more than 3 parts in one sentence
            if len(pids) > 3:
                nm_list = ", ".join(dict.fromkeys(parts_names.get(p, p) for p in pids))
                out.append(_f("WARN", "READ_LIST", q["id"],
                              f"a {where} sentence names {len(pids)} parts (more than 3): split the sentence so "
                              f"each names at most 3: {nm_list}"))
            # TWO_ROLE_NAME: ", also the <part>" lists a second role of the same part as if it were a new one
            m = re.search(r",\s*also\s+(?:the\s+)?([A-Z][^,]{2,120})", s)
            if m and _parts_named(m.group(1)):
                out.append(_f("WARN", "TWO_ROLE_NAME", q["id"],
                              "the " + where + " sentence lists a part's second role as a new part ('"
                              + m.group(1).strip() + "'): it is the same part; write its full name once or name "
                              "it by its first role only"))
            # the full "A, B" two-role name in a sentence
            for full in two_role_full:
                if re.search(r"(?<!\w)" + re.escape(full) + r"(?!\w)", s):
                    out.append(_f("WARN", "TWO_ROLE_NAME", q["id"],
                                  f"the {where} sentence uses the full two-role name \"{full}\": it reads as two "
                                  f"parts; write \"{full.split(',')[0].strip()}\" in the sentence and the second "
                                  f"role once elsewhere if it matters"))
                    break
            # ENDPOINT_UNDERSTATED
            if _ENDPOINT_GAP.search(s) and end_tokens:
                low = s.lower()
                hit: dict[str, dict] = {}
                for tok, row in end_tokens:
                    tk = tok.lower()
                    if len(tk) < 4 or tk not in low:
                        continue
                    key = row.get("end") or tok
                    if key not in hit:
                        hit[key] = row
                if hit:
                    named = []
                    for key in sorted(hit):
                        row = hit[key]
                        disp = row.get("name") or key
                        zn = (row.get("zone") or "").strip()
                        named.append(disp + (f" ({zn})" if zn else ""))
                    out.append(_f("WARN", "ENDPOINT_UNDERSTATED", q["id"],
                                  "the sentence understates an end the register already names or zones: "
                                  + "; ".join(named[:4]) + " - name it as the register does, or say what is still "
                                  "unknown in an Unknown: line"))

    # NARRATIVE_NEW_ENDPOINT: narrative Text names a part no requirement block's Facts mention
    all_facts = " ".join(req_facts_text.values())
    mentioned = _parts_named(all_facts) if all_facts else set()
    for qid, ntext in narrative_texts.items():
        if not ntext:
            continue
        nparts = _parts_named(ntext)
        if not nparts:
            continue
        dep = nparts - mentioned
        if dep:
            nm_list = ", ".join(dict.fromkeys(parts_names.get(p, p) for p in dep))
            out.append(_f("WARN", "NARRATIVE_NEW_ENDPOINT", qid,
                          "the Drawbridge Impact Text names a part no requirement block's Facts mention: "
                          + nm_list + " - either cover it in a requirement's Facts or drop it from the narrative"))
    return out

def application_checks(sheet: dict[str, dict], card: dict) -> list[dict]:
    """The application checks (card "parts" applications, from csa-work/parts.json):
    APPLICATION_NOT_NAMED (warning): a requirement the card ties to an application (through a part that only that
    application uses) has a Text that names none of the applications behind it, only parts.
    APPLICATION_ZONE_CLAIM (hard): a clause puts a part or an application "in OT" when its register zone puts it outside
    OT, or "in IT" when its parts are in OT, and names nothing on the other side of the line: the role name of the
    part never decides which side of OT it is on (an OT-prefixed name for a server in IT is the mistake)."""
    from csa_docx.parts import named
    pc = card.get("parts") or {}
    apps = pc.get("applications") or []
    if not apps:
        return []
    kinds = {q["id"]: q["kind"] for q in card.get("questions", [])}
    byid = {a["id"]: a for a in apps}
    out = []
    for qid, ids in (pc.get("owed_applications") or {}).items():
        b = sheet.get(qid)
        if not b or kinds.get(qid) != "requirement":
            continue
        text = b.get("text") or " ".join(f["text"] for f in b["facts"])
        if text and not any(named(text, byid[i]["names"]) for i in ids if i in byid):
            out.append(_f("WARN", "APPLICATION_NOT_NAMED", qid,
                          f"the Text names parts but not the application they serve: "
                          f"{', '.join(byid[i]['name'] for i in ids if i in byid)} (see Applications on the card)"))
    ends = {"OT": "outside", "IT": "ot"}          # the zone a claim contradicts, as a part's side
    things = [(pid, nm, pc["sides"].get(pid)) for pid, nm in (pc.get("names") or {}).items() for nm in nm
              if pc["sides"].get(pid) in ("ot", "outside") and pid in set((pc.get("hosts") or {}).values())]
    things += [(a["id"], nm, a["side"]) for a in apps for nm in a["names"] if a["side"] in ("ot", "outside")]
    for qid, b in sheet.items():
        if kinds.get(qid) not in ("requirement", "narrative") or not b.get("text"):
            continue
        for clause in re.split(r"(?<=[.!?])\s+|\n+|,?\s+(?:but|while|whereas|although)\s+|;\s*", b["text"]):
            claim = _CLAIM_ZONE.search(clause)
            if not claim:
                continue
            sides = {side for _, nm, side in things if re.search(rf"\b{re.escape(nm)}\b", clause, re.I)}
            if sides == {ends[claim[1]]}:
                who = sorted({nm for _, nm, side in things if re.search(rf"\b{re.escape(nm)}\b", clause, re.I)}, key=len)[-1]
                out.append(_f("ERROR", "APPLICATION_ZONE_CLAIM", qid,
                              f"{who} is {'outside OT' if sides == {'outside'} else 'in OT'} in the register, not in "
                              f"{claim[1]}: say where it is from its zone, never from its role name: \"{clause[:160]}\""))
    return out


_LINK_VERB = re.compile(r"\b(?:connects?|connected|connecting|communicates?|talks?|sends?|reads?|writes?|queries|queried|"
                        r"replicates?|replicated|reaches|reached|feeds?|forwards?|pulls?|pushes?)\b", re.I)
_OWNS = re.compile(r"\b(?:belongs? to|is part of|are part of|is dedicated to|dedicated to|serves only|used only by|owned by)\b|[\w)]'s\b", re.I)


def chain_checks(sheet: dict[str, dict], card: dict) -> list[dict]:
    """Two warnings on how a clause joins parts and applications (card "parts" links and applications):
    CHAIN_STEP_UNSUPPORTED: a clause names two or more parts and a verb that links them (sends, reads, replicates,
    connects), but no flow joins any two of the parts it names.
    SHARED_PART_CLAIMED: a clause names a part several applications share, with exactly one of them, in words that
    make it that application's own (belongs to, is part of, dedicated to, the application's ...)."""
    from csa_docx.parts import parts_in
    pc = card.get("parts") or {}
    apps = pc.get("applications") or []
    if not apps:
        return []
    kinds = {q["id"]: q["kind"] for q in card.get("questions", [])}
    links = {tuple(x) for x in pc.get("links") or []}
    names = {pid: pc["names"][pid] for pid in pc.get("names", {}) if pid in pc.get("parts", {})}
    users: dict[str, list[dict]] = {}
    for a in apps:
        for pid in a["shared"]:
            users.setdefault(pid, []).append(a)
    out = []
    for qid, b in sheet.items():
        if kinds.get(qid) not in ("requirement", "narrative") or not b.get("text"):
            continue
        for clause in re.split(r"(?<=[.!?])\s+|\n+|,?\s+(?:but|while|whereas|although)\s+|;\s*", b["text"]):
            ps = sorted(parts_in(clause, names))
            if len(ps) >= 2 and _LINK_VERB.search(clause) and not _EVERY_PART.search(clause) \
                    and not any(tuple(sorted((x, y))) in links for x in ps for y in ps if x < y):
                out.append(_f("WARN", "CHAIN_STEP_UNSUPPORTED", qid,
                              f"no flow joins {' and '.join(pc['parts'][p] for p in ps[:3])}: say the link only where a "
                              f"flow or a chain step on the card shows it: \"{clause[:160]}\""))
            if _OWNS.search(clause):
                for pid, served in users.items():
                    hit = [a for a in served if any(re.search(rf"\b{re.escape(n)}\b", clause, re.I) for n in a["names"])]
                    if pid in parts_in(clause, names) and len(hit) == 1 and len(served) > 1:
                        out.append(_f("WARN", "SHARED_PART_CLAIMED", qid,
                                      f"{pc['parts'][pid]} is shared by {', '.join(a['name'] for a in served)}, so it does not "
                                      f"belong to {hit[0]['name']} alone: \"{clause[:160]}\""))
    return out


def rating_floor(sheet: dict[str, dict], card: dict) -> list[dict]:
    """RATING_ABOVE_FLOOR (warning): "Met" while something the requirement owes is still Unknown, or while the frame
    found data pulled out of OT or brought into OT for this requirement. The rating reason must then say what
    controls those flows, or the rating comes down."""
    out = []
    for qid, items in ((card.get("frame") or {}).get("must_address") or {}).items():
        b = sheet.get(qid)
        if not b or b.get("rating") != "Met":
            continue
        why = []
        cited = block_ids(b)
        if b.get("unknown") or any(x["ids"] and not ({i.upper() for i in x["ids"]} & cited) for x in items):
            why.append("part of what it must address is Unknown")
        moves = [x for x in items if x.get("direction") in ("pull_into_ot", "into_ot")]
        if moves:
            why.append(f"the frame found data moved across the OT boundary for it ({moves[0]['text'][:90]})")
        if why:
            out.append(_f("WARN", "RATING_ABOVE_FLOOR", qid, "rated Met although " + " and ".join(why)
                          + ": say in the rating reason what controls this, or lower the rating"))
    return out


def practice_checks(sheet: dict[str, dict], card: dict) -> list[dict]:
    """Require configured practice evidence or an Unknown, retain statement attribution and enforce its rating cap."""
    out = []
    view = card.get("practice") or {}
    strict = bool((card.get("frame") or {}).get("strict"))
    ratings = card.get("ratings") or ["Met", "Partially Met", "Not Met", "Not Applicable"]
    by_req = {q.get("req_id"): q["id"] for q in card.get("questions", []) if q.get("req_id")}
    for req, item in view.items():
        qid = by_req.get(req)
        b = sheet.get(qid) if qid else None
        if not b: continue
        cited = block_ids(b)
        accepted = [o for o in item.get("observations", []) if o.get("evidence_id", "").upper() in cited]
        if item.get("needs") and not accepted and not b.get("unknown"):
            out.append(_f("ERROR" if strict else "WARN", "PRACTICE_NOT_ADDRESSED", qid,
                          "practice evidence is neither cited nor retained as an Unknown"))
        facts = " ".join(f.get("text", "") for f in b.get("facts", []))
        for obs in accepted:
            if obs.get("kind") == "stated" and (obs.get("person", "") not in facts or obs.get("observed_on", "") not in facts):
                out.append(_f("ERROR", "PRACTICE_ATTRIBUTION_DROPPED", qid,
                              f"{obs['evidence_id']} is an attributed statement: retain {obs.get('person')} and {obs.get('observed_on')}"))
        missing = item.get("missing_strengths") or []
        cap = item.get("cap_without", "")
        if missing and b.get("rating") in ratings and cap in ratings and ratings.index(b["rating"]) < ratings.index(cap):
            out.append(_f("WARN", "RATING_ABOVE_PRACTICE_FLOOR", qid,
                          f"rated {b['rating']} although {', '.join(missing)} evidence is missing; cap is {cap}"))
    return out


_WRONG_SIDE = {"IT": re.compile(r"\bOT[- ](?:resident|hosted|side)\b|\b(?:in|inside|within) (?:the )?OT\b", re.I),
               "OT": re.compile(r"\bIT[- ](?:resident|hosted|side)\b|\b(?:in|inside|within) (?:the )?IT\b", re.I)}


def zone_contradictions(sheet: dict[str, dict], card: dict) -> list[dict]:
    """ZONE_CONTRADICTED (hard): a sentence that names a host the zone list puts on one side of the OT boundary (or its
    role) and places it on the other ("OT-resident", "in OT") although its role name says so. The zone list wins."""
    out = []
    for c in (card.get("frame") or {}).get("zone_conflicts", []):
        rx = _WRONG_SIDE.get(c["side"])
        if not rx:
            continue
        for k, b in sheet.items():
            if k.startswith("F"):
                continue
            texts = [b.get("text") or ""] + [f["text"] for f in b["facts"]] + [" | ".join(r) for r in b["rows"]] + b["bullets"]
            for s in (s for t in texts for s in re.split(r"(?<=[.!?])\s+", t)):
                if (c["host"] in s or c["role"] in s) and rx.search(s):
                    out.append(_f("ERROR", "ZONE_CONTRADICTED", k,
                                  f"{c['host']} ({c['role']}) is in {c['zone']}, an {c['side']} zone, but this says otherwise: "
                                  f"\"{s[:180]}\". Write about it as {c['side']}-hosted"))
                    break
    return out


def flow_coverage(sheet: dict[str, dict], card: dict) -> list[dict]:
    """FLOW_NOT_COVERED (an error when the frame is "strict", else a warning): every flow that crosses the OT boundary (the frame's coverage targets) is cited in a
    requirement or narrative block (Drawbridge Impact), or named on an Unknown: line there; a table row alone does not
    cover it. NOT_OT_FLOW_IN_REQUIREMENT (warning): a requirement block cites a flow with no OT end, which is context."""
    fr = card.get("frame") or {}
    kinds = {q["id"]: q["kind"] for q in card.get("questions", [])}
    blocks = [b for k, b in sheet.items() if kinds.get(k) in ("requirement", "narrative")]
    cited = set().union(*[block_ids(b) | {i.upper() for i in b.get("covers", [])} for b in blocks]) if blocks else set()
    unk = " ".join(u for b in blocks for u in b.get("unknown", [])).lower()
    prose = " ".join(" ".join([b.get("text") or ""] + [f["text"] for f in b["facts"]] + b["unknown"]) for b in blocks)
    out = []
    for c in fr.get("coverage", []):
        if c.get("ids"):
            hit = {i.upper() for i in c["ids"]} & cited or any(t and t.lower() in unk for t in c.get("tokens", []))
        else:                       # a card from before flows carried their evidence IDs: the names are enough
            hit = any(t and t in prose for t in c.get("tokens", []))
        if not hit:
            out.append(_f("ERROR" if fr.get("strict") else "WARN", "FLOW_NOT_COVERED", None, f"a flow across the OT boundary is not addressed in a requirement or "
                                                             f"the Drawbridge Impact: {c['text'][:150]}"
                          + (f" ({', '.join(c['ids'][:3])})" if c.get("ids") else "")))
    ctx = {i.upper() for i in fr.get("context_ids", [])}
    for k, b in sheet.items():
        if kinds.get(k) == "requirement" and block_ids(b) & ctx:
            out.append(_f("WARN", "NOT_OT_FLOW_IN_REQUIREMENT", k,
                          f"{', '.join(sorted(block_ids(b) & ctx))} is a flow with no OT end (context): it is not an OT push "
                          "or pull and does not answer an OT requirement"))
    return out


def slot_answers(sheet: dict[str, dict], fr: dict, fb: dict | None = None) -> list[dict]:
    """SLOT_NOT_ANSWERED (an error when the frame is "strict", else a warning): each requirement block cites the evidence of every frame finding the card says it must
    address, or has an Unknown: line naming it (one of its hosts, addresses or evidence IDs). A slot the captures do
    not answer needs an Unknown: line in the block (or on its F1 line)."""
    out = []
    level = "ERROR" if fr.get("strict") else "WARN"      # a frame tuned for its topic ("strict": true) blocks; others warn
    f1 = (fb or {}).get("frame") or {}
    for qid, items in (fr.get("must_address") or {}).items():
        b = sheet.get(qid)
        if b is None:
            continue                                  # QUESTION_MISSING reports it
        cited = block_ids(b) | {i.upper() for i in b.get("covers", [])}       # Covers: a finding raised as Unknown
        unk = " ".join(b.get("unknown", []) + b.get("dropped", [])).lower()      # a Dropped: line names the finding and says why
        miss = []
        for x in items:
            if x["ids"] and {i.upper() for i in x["ids"]} & cited:
                continue
            if x.get("empty"):
                if b.get("unknown") or re.match(r"(?i)unknown:", f1.get(x["slot"], "")):
                    continue
            elif unk and any(t and t.lower() in unk for t in list(x.get("tokens", [])) + list(x["ids"])):
                continue
            miss.append(x)
        if miss:
            listed = "; ".join(f"{x['slot']} {x['text'][:110]}" + (f" ({', '.join(x['ids'][:3])})" if x["ids"] else "")
                               for x in miss[:6])
            out.append(_f(level, "SLOT_NOT_ANSWERED", qid,
                          f"{len(miss)} finding(s) the card lists under 'Must address' are neither cited nor raised as Unknown: "
                          f"{listed}{' …' if len(miss) > 6 else ''}. Cite each one's evidence in this block, or add an "
                          "Unknown: line naming it"))
    return out


def role_table_tokens(card: dict) -> set[str]:
    """Host and server names the card's role tables already show (empty when the card has none)."""
    out = set()
    for r in [r for t in (card.get("role_tables") or [card.get("role_table") or {}]) for r in t.get("rows", [])]:
        out |= {h.rstrip("\u2020\u2021") for h in r.get("hosts", [])}
        for c in r.get("cells", []) + r.get("hosts", []):
            out |= set(_HOSTTOKEN.findall(c))
    return out


# a discovery capture, however the row names it: one capture folder (REVELOC_discovery_HOST_20260605T031609Z),
# the multi-host form (REVELOC_discovery_<host>_<timestamp>: 41_dns_query_tests.txt for ...), or capture file
# names (NN_name.txt, alone or "in HOST_<timestamp>"). A NOT_FOUND row's "searched ..." scope is not a capture.
_CAPTURE_SRC = re.compile(r"_discovery_[^:\s]+_\d{8}T\d{6}Z|_discovery_<host>|(?:^|[\s:;,/(])\d{2}_[a-z0-9_]+\.txt\b")
_NOT_CAPTURE = re.compile(r"^\s*(?:searched\b|search scope\b|discovery index\b)", re.I)
_PREVIOUS_SRC = re.compile(r"current[ _]state[ _]assessment", re.IGNORECASE)
_ATTEMPTED = re.compile(r"\battempted\b.*\bSYN_SENT\b|\bSYN_SENT\b.*\bno reply\b", re.I)
_REQ_KEY = re.compile(r"\b[A-Z]{2,5}-([A-Z][A-Z_]*)-[A-Z]?\d+\b")
_HOSTTOKEN = re.compile(r"\b[A-Z][A-Z0-9]{5,}\d{2,3}\b")


def source_class(row: dict | None) -> str:
    """Where a matrix row comes from: capture (a discovery capture file), previous (the previous assessment),
    user (a confirmation), or document (any other supplied document)."""
    if not row:
        return ""
    src = row.get("source_title") or ""
    if _CAPTURE_SRC.search(src) and not _NOT_CAPTURE.match(src):
        return "capture"
    if (row.get("gap_or_action") or "").startswith("legacy L-") or _PREVIOUS_SRC.search(src):
        return "previous"
    if src.lower().startswith("user confirmation"):
        return "user"
    return "document"


def block_ids(b: dict) -> set[str]:
    """Every evidence ID a block cites, in facts, table rows and bullets."""
    ids = {i.upper() for f in b["facts"] for i in f["ids"]}
    ids |= {i.upper() for r in b["rows"] for c in r for i in _EID.findall(c)}
    ids |= {i.upper() for x in b["bullets"] for i in _EID.findall(x)}
    return ids


def dropped_ids(sheet: dict[str, dict]) -> set[str]:
    """Evidence IDs on a ``Dropped:`` line that also gives a reason."""
    out = set()
    for b in sheet.values():
        for dropped in b.get("dropped", []):
            found = list(_EID.finditer(dropped))
            if found and dropped[found[-1].end():].strip(" \t,;:-"):
                out |= {m.group(0).upper() for m in found}
    return out


_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def table_covers(claim: str, card: dict | None) -> bool:
    """True when a per-host fact is what the card's role tables state: the hosts it is about are table rows and a
    value it gives (a server name or an address) is in the table's cells or its common line."""
    tables = [t for t in ((card or {}).get("role_tables") or [(card or {}).get("role_table") or {}]) if t]
    if not tables:
        return False
    row_hosts, values = set(), set()
    for t in tables:
        for r in t.get("rows", []):
            row_hosts |= {h.rstrip("\u2020\u2021") for h in r.get("hosts", [])}
            for c in r.get("cells", []):
                values |= set(_HOSTTOKEN.findall(c)) | set(_IPV4.findall(c))
        values |= set(_HOSTTOKEN.findall(t.get("common", ""))) | set(_IPV4.findall(t.get("common", "")))
    hosts = set(_HOSTTOKEN.findall(claim or ""))
    about = hosts & row_hosts
    given = (hosts - about) | set(_IPV4.findall(claim or ""))
    return bool(about) and bool(given & values) and not (hosts - row_hosts - values)


def regression(old: dict[str, dict], new: dict[str, dict], matrix: dict[str, dict] | None = None,
               card: dict | None = None) -> list[dict]:
    """What a re-answer lost against the sheet it replaces: evidence no longer cited, fewer table rows, fewer
    capture-sourced citations (WARN). A VERIFIED capture row cited before and dropped without a 'Dropped:' line
    saying why is an ERROR (CAPTURE_DROPPED): a re-answer should add or correct, not quietly thin out."""
    matrix = matrix or {}
    out: list[dict] = []
    for qid, nb in new.items():
        ob = old.get(qid)
        if not ob:
            continue
        o_ids, n_ids = block_ids(ob), block_ids(nb)
        dropped = sorted(o_ids - n_ids)
        if dropped:
            out.append(_f("WARN", "EVIDENCE_DROPPED", qid,
                          f"{len(dropped)} evidence ID(s) cited before are no longer cited: {', '.join(dropped[:8])}"))
        if len(nb["rows"]) < len(ob["rows"]):
            out.append(_f("WARN", "ROWS_DROPPED", qid,
                          f"the table has {len(nb['rows']) - 1} row(s), the answer it replaces had {len(ob['rows']) - 1}"))
        lost = [i for i in dropped if source_class(matrix.get(i)) == "capture"
                and matrix.get(i, {}).get("status") == "VERIFIED"
                and not any(i in d for d in nb.get("dropped", []))]
        tabled = [i for i in lost if table_covers(matrix.get(i, {}).get("claim", ""), card)]
        if tabled:                      # per-host facts the role table states now: not lost, and not to be repeated
            out.append(_f("WARN", "CAPTURE_IN_TABLE", qid,
                          f"{', '.join(tabled[:8])}{' and others' if len(tabled) > 8 else ''} (capture evidence) are no longer "
                          f"cited in the prose: the role table under Discovery Information states them"))
            lost = [i for i in lost if i not in tabled]
        if lost and (card or {}).get("frame"):
            # with an analysis frame, only evidence on the frame or on the card's Facts to keep must stay: an old fact
            # on another topic's evidence (or one the frame contradicts) may go without a 'Dropped:' line
            relevant = {i.upper() for i in card["frame"].get("ids", [])}
            relevant |= {i.upper() for k in card.get("keep", []) for i in k.get("capture_ids", [])}
            off = [i for i in lost if i.upper() not in relevant]
            if off:
                out.append(_f("WARN", "CAPTURE_LEFT_OUT", qid,
                              f"{', '.join(off[:8])}{' and others' if len(off) > 8 else ''} (capture evidence) supported the "
                              "answer this replaces but is not on this topic's analysis frame: left out"))
                lost = [i for i in lost if i.upper() in relevant]
        if lost and nb.get("keep") == "":
            said = [f["text"] for f in ob["facts"] if set(f["ids"]) & set(lost)]
            out.append(_f("ERROR", "CAPTURE_DROPPED", qid,
                          f"{', '.join(lost)} (capture evidence) supported the answer this replaces and is no longer cited: keep "
                          f"the fact it supports, or add 'Dropped: {lost[0]} <why it no longer applies>'"
                          + (f". The fact was: \"{said[0][:200]}\"" if said else "")))
        cap = lambda ids: sum(1 for i in ids if source_class(matrix.get(i)) == "capture")
        if matrix and cap(n_ids) < cap(o_ids):
            out.append(_f("WARN", "SOURCE_DOWNGRADE", qid,
                          f"capture-sourced citations fell from {cap(o_ids)} to {cap(n_ids)}: facts that were observed in the "
                          "captures are now supported by documents or the previous assessment"))
    return out


def kept_facts(sheet: dict[str, dict], card: dict, already: list[dict] | None = None) -> list[dict]:
    """The card's "Facts to keep" (section_card.facts_to_keep): each capture-backed fact an applied answer of this
    subsection stated must still be cited in a fact, evidence-bearing table row or evidence-bearing bullet anywhere in
    the merged section, or named on a 'Dropped:' line with a reason. ERROR CAPTURE_DROPPED is attributed to the fact's
    recorded question."""
    reported = {(f.get("question"), i) for f in (already or []) if f["code"] == "CAPTURE_DROPPED"
                for i in _EID.findall(f["message"].split(" (capture")[0])}
    out: list[dict] = []
    cited = set().union(*(block_ids(b) for b in sheet.values())) if sheet else set()
    dropped = dropped_ids(sheet)
    for k in card.get("keep", []):
        qid, b = k["question"], sheet.get(k["question"])
        if b is not None and b.get("keep"):
            continue
        capture_ids = {i.upper() for i in k["capture_ids"]}
        if capture_ids & (cited | dropped):
            continue
        caps = [i for i in k["capture_ids"] if (qid, i) not in reported]
        if caps:
            out.append(_f("ERROR", "CAPTURE_DROPPED", qid,
                          f"{', '.join(caps)} (capture evidence): the card's Facts to keep lists \"{k['fact'][:200]}\" for {qid} "
                          f"and the answer no longer states it: keep it with its capture evidence, or add "
                          f"'Dropped: {caps[0]} <why it no longer applies>'"))
    return out


def _background_checks(qid: str, q: dict, b: dict, background: set[str]) -> list[dict]:
    """Knowledge (knowledge.py) is background, never evidence. A K- passage may only sit on its own fact with basis
    background, in a narrative block, next to at least one fact from real (E-) evidence, and must be on the card."""
    out: list[dict] = []
    stray = [x for x in [c for r in b["rows"] for c in r] + b["bullets"] if _KID.search(x)]
    if stray:
        out.append(_f("ERROR", "BACKGROUND_AS_EVIDENCE", qid, f"background knowledge (K-) cited in a table row or bullet, "
                      f"which need evidence: {stray[0][:80]}"))
    bg_facts = [f for f in b["facts"] if f["basis"] == "background" or any(_KID.fullmatch(i) for i in f["ids"])]
    if not bg_facts:
        return out
    if q["kind"] != "narrative":
        out.append(_f("ERROR", "BACKGROUND_AS_EVIDENCE", qid, f"background knowledge (K-) cannot support a {q['kind']} "
                      f"answer, only a narrative such as Drawbridge Impact: {bg_facts[0]['text'][:80]}"))
    for f in bg_facts:
        kids = [i for i in f["ids"] if _KID.fullmatch(i)]
        if f["basis"] != "background" or not kids or len(kids) != len(f["ids"]):
            out.append(_f("ERROR", "BACKGROUND_MIXED", qid, "a background fact cites only K- IDs with basis background, "
                          f"and an evidence fact cites only E- IDs: {f['line'][:90]}"))
        off = [i for i in kids if i.upper() not in background]
        if off:
            out.append(_f("ERROR", "BACKGROUND_NOT_ON_CARD", qid, f"{', '.join(off)} is not among the card's knowledge passages"))
    if not any(f["ids"] and all(_EID.fullmatch(i) for i in f["ids"]) for f in b["facts"]):
        out.append(_f("ERROR", "BACKGROUND_ALONE", qid, "background knowledge explains evidence, it never stands alone: "
                      "add the fact from an E- evidence row that it explains, or write Unknown"))
    return out


_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z(]|\s*$)")
_JUDGEMENT = re.compile(r"\b(should|recommend\w*|must|risks?|risky|rated|rating|(?:non-?)?compliant|adequate|inadequate|"
                        r"poor|weak|good practice|best practice)\b", re.I)
_CONTENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]")
_FILLER = set("the and are was were for with from this that has have but not its into one two all only".split())


def note_text(b: dict) -> str:
    """The note as it goes into the document: Text if written, else the facts as sentences."""
    if b.get("text"):
        return no_ids(" ".join(b["text"].split()))
    return " ".join(_sentence(f) for f in b["facts"]).strip()


def _content(s: str) -> set[str]:
    return {w.lower().strip(".") for w in _CONTENT.findall(no_ids(s or "")) if len(w) >= 3 and w.lower() not in _FILLER}


def _note_checks(qid: str, q: dict, b: dict, sheet: dict[str, dict], qs: dict[str, dict]) -> list[dict]:
    """The optional note under a table: None, or one or two sentences of evidenced fact the rows do not show."""
    out: list[dict] = []
    text = note_text(b)
    if b["none"]:
        if b["facts"] or b.get("text"):
            out.append(_f("ERROR", "NOTE_NONE_AND_TEXT", qid, "write either 'None: <why>' or the note, not both"))
        return out
    if b.get("text") and not b["facts"]:
        out.append(_f("ERROR", "NOTE_NO_FACTS", qid, "the note's Text needs the Facts (with evidence) it is built from"))
    if not text:
        return out
    n = len(_SENTENCE_END.findall(text)) or 1
    if n > 2:
        out.append(_f("ERROR", "NOTE_TOO_LONG", qid, f"the note is {n} sentences: one or two only, or put the detail in a table row"))
    m = _JUDGEMENT.search(text)
    if m:
        out.append(_f("ERROR", "NOTE_NOT_A_FACT", qid, f"the note judges or recommends (\"{m.group(0)}\"): Discovery Information "
                      "holds facts only. Ratings belong in the requirement rows and impact in Drawbridge Impact"))
    words = _content(text)
    rows = list(q.get("table_rows") or [])
    for oid, oq in qs.items():               # the table rows this same sheet writes
        if oq["kind"] == "observation" and oq.get("part") is not None and oq["part"] < (q.get("part") or 0):
            rows += [" | ".join(r) for r in (sheet.get(oid) or {}).get("rows", [])[1:]]
    for r in rows:
        rw = _content(r)
        if words and rw and len(words & rw) / len(words) >= 0.75:
            out.append(_f("ERROR", "NOTE_REPEATS_ROW", qid, f"the note repeats a table row (\"{_quote(r, 80)}\"): "
                          "say what the rows cannot show, or write 'None: <why>'"))
            break
    return out


#: the worked examples section_card.py appends to every card ("## Example answer (<kind>)"). Their hosts, facts
#: and evidence IDs (E-0nnn, a form the matrix never issues) are invented: a line copied from one into a real
#: answer is format mistaken for evidence, so EXAMPLE_COPIED stops it.
EXAMPLES = Path(__file__).resolve().parents[2] / "references" / "answer-examples"
_EXAMPLE_MIN_WORDS = 6
_example_cache: set[str] | None = None


def _norm(s: str) -> str:
    """Lower-case words only, evidence and knowledge IDs removed, for comparing a sentence across sheets."""
    s = re.sub(r"\b(?:[\w-]+:)?(?:E-\d+|K-[0-9A-F]{6})\b", " ", s or "")
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def _sheet_sentences(b: dict) -> list[tuple[str, str]]:
    """(where, text) for every line of a parsed block that can carry a claim into the document."""
    out = [("fact", f["text"]) for f in b["facts"]] + [("bullet", x) for x in b["bullets"]]
    out += [("row", " ".join(c)) for c in b["rows"][1:]]
    out += [("Summary", s) for s in re.split(r"(?<=[.!?])\s+", b.get("summary") or "") if s.strip()]
    for para in (b.get("text") or "").split("\n\n"):
        out += [("Text", s) for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
    return out


def example_sentences(folder: Path | None = None) -> set[str]:
    """Normalised fact, bullet, Text and table-row sentences of the worked examples (long enough to be a claim)."""
    global _example_cache
    if folder is None and _example_cache is not None:
        return _example_cache
    found: set[str] = set()
    d = folder or EXAMPLES
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        for b in parse(f.read_text(encoding="utf-8")).values():
            for _, s in _sheet_sentences(b):
                n = _norm(s)
                if len(n.split()) >= _EXAMPLE_MIN_WORDS:
                    found.add(n)
    if folder is None:
        _example_cache = found
    return found


def example_checks(sheet: dict[str, dict], examples: set[str] | None = None) -> list[dict]:
    """EXAMPLE_COPIED: a sentence of the answer repeats one from the card's worked example."""
    examples = example_sentences() if examples is None else examples
    findings: list[dict] = []
    if not examples:
        return findings
    for qid, b in sheet.items():
        for where, s in _sheet_sentences(b):
            if _norm(s) in examples:
                findings.append(_f("ERROR", "EXAMPLE_COPIED", qid,
                                   f"this {where} is copied from the worked example on the card, which is invented to show "
                                   f"the format and says nothing about this system: answer from this section's evidence: {s[:80]}"))
    return findings


def block_checks(blk: str, card: dict, qid: str, matrix: dict[str, dict] | None = None, relaxed: bool = False) -> list[dict]:
    """The sheet checks for one block alone: ``validate`` (draft lane) on a sheet holding only ``qid``'s block, keeping the
    errors that name that block. Flow coverage and kept-fact retention span blocks and are left until the merged sheet is
    validated. The per-requirement path runs this on every block it writes."""
    sheet = parse(blk)
    if qid not in sheet:
        return [_f("ERROR", "QUESTION_MISSING", qid, f"no '## {qid}' block")]
    res = validate({qid: sheet[qid]}, card, matrix, draft=True, relaxed=relaxed)
    deferred = {"FLOW_NOT_COVERED", "CAPTURE_DROPPED"}
    return [f for f in res["findings"] if f["level"] == "ERROR" and f.get("question") == qid and f["code"] not in deferred]


def validate(sheet: dict[str, dict], card: dict, matrix: dict[str, dict] | None = None,
             ratings: list[str] | None = None, new_ids: set[str] | None = None, draft: bool = False,
             previous: dict[str, dict] | None = None, relaxed: bool = False) -> dict:
    """Findings for a parsed sheet against its card. ERROR blocks rendering; WARN is reported.
    ``draft`` keeps only HARD_CODES as errors (the draft lane)."""
    findings: list[dict] = []
    matrix = matrix or {}
    allowed = {r["id"].upper() for p in card.get("evidence", {}).values() for r in p.get("rows", [])}
    # rows the card lists as "more rows not shown" are this section's evidence too: the card cut them
    # for length, not relevance, so citing one is allowed (UNKNOWN_EVIDENCE still checks the matrix)
    allowed |= {i.upper() for p in card.get("evidence", {}).values() for i in p.get("cut", [])}
    allowed |= {i.upper() for p in card.get("evidence", {}).values() for i in p.get("digest_ids", [])}
    allowed |= {i.upper() for i in (new_ids or set())}
    allowed |= {i.upper() for k in card.get("keep", []) for i in k.get("evidence_ids", [])}
    allowed |= {i.upper() for i in (card.get("frame") or {}).get("ids", [])}   # the analysis frame's findings
    background = {i.upper() for i in card.get("background_ids", [])}   # K- passages on the card's background section
    ratings = ratings or card.get("ratings") or ["Met", "Partially Met", "Not Met", "Not Applicable"]
    qs = {q["id"]: q for q in card["questions"]}
    searches = {qid: b["search"] for qid, b in sheet.items() if b["search"]}
    for qid, q in qs.items():
        b = sheet.get(qid)
        if b is None:
            findings.append(_f("ERROR", "QUESTION_MISSING", qid, f"no '## {qid}' block"))
            continue
        has = (b["facts"] or b["unknown"] or b["keep"] or b["rows"] or b["bullets"] or b["answer"]
               or b["search"] or b["none"] or b.get("summary") or b.get("story") or b.get("text"))
        if not has:
            findings.append(_f("ERROR", "EMPTY_ANSWER", qid, "no Facts, Rows, Bullets, Unknown, Keep, Search"
                               + (" or None" if q["kind"] == "note" else "")
                               + " - every Rows: line must start with a pipe: | column | column |"))
        if q["kind"] == "note":
            findings += _note_checks(qid, q, b, sheet, qs)
        elif b["none"]:
            findings.append(_f("WARN", "NONE_IGNORED", qid, "'None:' answers only the optional note under a table"))
        for fact in b["facts"]:
            if not fact["ids"]:
                findings.append(_f("ERROR", "FACT_NO_EVIDENCE", qid, f"a fact cites no evidence ID: {fact['text'][:80]}"))
            if fact["basis"] == "background":
                continue                            # knowledge passage: _background_checks covers it
            cited_rows = [matrix[i.upper()] for i in fact["ids"] if i.upper() in matrix]
            card_key = str(card.get("key") or "").upper()
            frame_ids = {i.upper() for i in (card.get("frame") or {}).get("ids", [])}
            tried = [r_["evidence_id"] for r_ in cited_rows if _ATTEMPTED.search(r_.get("claim") or "")]
            if tried and re.search(r"\bestablished\b", fact["text"], re.I) and not re.search(r"\battempt", fact["text"], re.I):
                findings.append(_f("ERROR", "ATTEMPT_AS_ESTABLISHED", qid,
                                   f"{', '.join(tried[:6])} record only connection attempts (SYN_SENT, no reply seen), but the fact "
                                   f"says established: say attempted for those endpoints, or split the fact: {fact['text'][:70]}"))
            for r_ in cited_rows:
                if r_.get("status") == "NOT_FOUND" and card_key and r_["evidence_id"].upper() not in frame_ids:
                    keys = set(_REQ_KEY.findall(r_.get("question") or ""))
                    if keys and card_key not in keys:
                        findings.append(_f("ERROR", "CITATION_OFF_TOPIC", qid,
                                           f"{r_['evidence_id']} records an absence for {'/'.join(sorted(keys))}, not for this "
                                           f"subsection ({card_key}); a NOT_FOUND row supports only the question it was recorded for: "
                                           f"{fact['text'][:70]}"))
            if fact["basis"] == "observed" and cited_rows and all(source_class(r_) != "capture" for r_ in cited_rows):
                classes = sorted({source_class(r_) for r_ in cited_rows})
                findings.append(_f("WARN", "BASIS_NOT_OBSERVED", qid,
                                   f"basis is observed but the cited rows come from {'/'.join(classes)}, not a capture: use "
                                   f"documented or stated: {fact['text'][:70]}"))
            if cited_rows and all(source_class(r_) == "previous" for r_ in cited_rows):
                tokens = set(_HOSTTOKEN.findall(fact["text"]))
                better = [r["id"] for r in card.get("evidence", {}).get(qid, {}).get("rows", [])
                          if r.get("status") == "VERIFIED" and source_class(matrix.get(r["id"].upper())) == "capture"
                          and (tokens & set(_HOSTTOKEN.findall(r.get("claim", ""))))]
                if better:
                    findings.append(_f("WARN", "PREFER_CAPTURE", qid,
                                       f"the fact rests on the previous assessment only, while capture rows on the card "
                                       f"cover the same host(s): {', '.join(better[:4])}: {fact['text'][:60]}"))
            if fact["basis"] not in BASES:
                findings.append(_f("ERROR", "BAD_BASIS", qid, f"basis must be one of {', '.join(BASES)}: {fact['line'][:90]}"))
            cm = count_mismatch(fact["text"])
            if cm:
                findings.append(_f("ERROR", "COUNT_MISMATCH", qid, f"{cm}: {fact['text'][:90]}"))
            if q["kind"] in ("requirement", "narrative", "findings", "note") and _SOURCE_SUBJECT.search(fact["text"]):
                findings.append(_f("ERROR", "SOURCE_AS_SUBJECT", qid, f"the fact is about the source, not the system: make the application, host or practice the subject and keep the source in the basis braces: {fact['text'][:80]}"))
            if q["kind"] in ("requirement", "narrative", "findings", "note") and _IP.search(fact["text"]):
                findings.append(_f("WARN", "IP_IN_PROSE", qid, f"address in a prose fact: name the host if it has a name; an address alone is right only where no host name is known: {fact['text'][:80]}"))
        findings += _background_checks(qid, q, b, background)
        for u in b["unknown"]:
            n = len(_QWORD.findall(_QRELATIVE.sub(" ", u)))
            if n >= 3:
                findings.append(_f("ERROR", "UNKNOWN_BUNDLED", qid, f"one Unknown: line holds {n} questions: write one "
                                   f"Unknown: line per question, so each becomes its own Discovery Required item: {u[:90]}"))
        if q["kind"] in ("requirement", "narrative", "findings", "note"):
            # no semicolons in anything that becomes document prose: Text, the facts it is built from, bullets
            for where, s in [("Summary", b.get("summary") or ""), ("Text", b.get("text") or "")] + [("fact", f["text"]) for f in b["facts"]] + \
                    [("bullet", x) for x in b["bullets"]]:
                if ";" in s:
                    i = s.find(";")
                    findings.append(_f("ERROR", "SEMICOLON", qid, f"semicolon in a {where} (\"{s[max(0, i - 30):i + 30].strip()}\"): "
                                       "write two sentences, or join the parts with a comma and 'and' or 'but'"))
                    break
        # nothing about the framework's own search may reach the document, whatever the question kind
        prose = [("Summary", b.get("summary") or ""), ("Text", b.get("text") or "")] + [("fact", f["text"]) for f in b["facts"]] + \
                [("bullet", x) for x in b["bullets"]] + [("unknown", u) for u in b["unknown"]] + \
                [("row", " | ".join(c)) for c in b["rows"]]
        for where, s_ in prose:
            m = _PROCESS_WORDING.search(s_ or "")
            if m:
                findings.append(_f("ERROR", "PROCESS_AS_SUBJECT", qid,
                                   f"a {where} describes the framework's search (\"{m.group(0)}\"), not the system: say what the "
                                   "system lacks and name the real sources checked (the discovery captures, the supplied "
                                   f"documents, the previous assessment): {s_[:80]}"))
                break
        cited = {i.upper() for fact in b["facts"] for i in fact["ids"] if _EID.fullmatch(i)}
        cited |= {i.upper() for row in b["rows"] for c in row for i in _EID.findall(c)}
        cited |= {i.upper() for x in b["bullets"] for i in _EID.findall(x)}
        # another project's evidence (estate member or system sibling) is context about that project's hosts
        for fact in b["facts"]:
            pf = sorted({_prefix(i) for i in fact["ids"]} - {None})
            low = (fact["scope"] or "").lower()
            missing = [x for x in pf if not re.search(rf"(?<![\w-]){re.escape(x)}\s*:", low)]
            if missing:
                findings.append(_f("ERROR", "CROSS_PROJECT_SCOPE", qid,
                                   f"the fact cites {', '.join(missing)} evidence: name that project in its scope, e.g. "
                                   f"{{observed; {missing[0]}: <its hosts>}}: {fact['text'][:70]}"))
        own = lambda ids: [i for i in ids if _EID.fullmatch(i) and not _prefix(i)]
        other = lambda ids: [i for i in ids if _prefix(i)]
        if q["kind"] == "requirement":
            ids = [i for f in b["facts"] for i in f["ids"]]
            if other(ids) and not own(ids):
                findings.append(_f("ERROR", "CROSS_PROJECT_ONLY", qid,
                                   "the current state rests only on another project's evidence: state this system's own "
                                   "evidence, or write Unknown. Another application's rows are context for narrative and note blocks"))
        if q["kind"] in ("observation", "register"):
            for row in b["rows"][1:]:
                ids = [i for c in row for i in _EID.findall(c)]
                if other(ids) and not own(ids):
                    findings.append(_f("ERROR", "CROSS_PROJECT_ONLY", qid,
                                       f"a table row rests only on another project's evidence; the table describes this system: "
                                       f"{' | '.join(row)[:80]}"))
        for i in sorted(cited):
            if matrix and i not in matrix:
                findings.append(_f("ERROR", "UNKNOWN_EVIDENCE", qid, f"{i} is not in the evidence matrix"))
            elif allowed and i not in allowed:
                findings.append(_f("ERROR", "EVIDENCE_NOT_ON_CARD", qid,
                                   f"{i} was not on the card; ask for it with 'Search:' or append it to the matrix first"))
        p = card.get("evidence", {}).get(qid, {})
        if p.get("digest_ids") and p.get("need") in ("inventory", "dependencies", "isolation") \
                and not (cited & {i.upper() for i in p["digest_ids"]}):
            findings.append(_f("WARN", "DIGEST_UNUSED", qid, f"the card gave a {p['need']} digest for this question "
                               "but the answer cites none of it; use it or say why it does not answer the question"))
        for fact in b["facts"]:
            hosts = set(_HOST.findall(fact["scope"])) | set(_HOST.findall(fact["text"]))
            if not hosts or not matrix or fact["basis"] == "background":
                continue
            seen = " ".join((matrix.get(i.upper(), {}).get("claim", "") + " " +
                             matrix.get(i.upper(), {}).get("evidence_excerpt", "") + " " +
                             matrix.get(i.upper(), {}).get("source_title", "")) for i in fact["ids"])
            outside = sorted(h for h in hosts if h not in seen)
            if outside:
                findings.append(_f("ERROR", "SCOPE_OUTSIDE_EVIDENCE", qid,
                                   f"{', '.join(outside)} named but not in the cited evidence ({', '.join(fact['ids'])})"))
        for d in b.get("dropped", []):
            for i in {x.upper() for x in _EID.findall(d)[:1]}:
                if i in {x.upper() for f in b["facts"] for x in f["ids"]} or any(i in " ".join(r).upper() for r in b["rows"]):
                    findings.append(_f("ERROR", "CITED_AND_DROPPED", qid,
                                       f"{i} is dropped and cited in the same block: cite it for the claim that still stands "
                                       f"and remove the Dropped: line, or drop it and stop citing it"))
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
            if card.get("requirement_stories") and not b["search"] and not b["keep"]:
                summary = " ".join((b.get("summary") or "").split())
                story = " ".join((b.get("story") or "").split())
                if not summary:
                    findings.append(_f("ERROR", "SUMMARY_MISSING", qid,
                                       "write Summary: for the short Current State table cell"))
                if not story:
                    findings.append(_f("ERROR", "STORY_MISSING", qid,
                                       "write Story: for this requirement under Discovery Information"))
                if b.get("story") and re.search(r"(?im)^Text:\s*", b.get("raw") or ""):
                    findings.append(_f("ERROR", "STORY_AND_TEXT", qid,
                                       "use Story: for a split requirement answer; do not also provide legacy Text:"))
                if summary and len(summary.split()) > 80:
                    findings.append(_f("ERROR", "SUMMARY_TOO_LONG", qid,
                                       f"Summary is {len(summary.split())} words; the Current State cell allows at most 80"))
                sentences = [s for s in re.split(r"(?<=[.!?])\s+", summary) if s.strip()]
                if len(sentences) > 3:
                    findings.append(_f("ERROR", "SUMMARY_TOO_MANY_SENTENCES", qid,
                                       f"Summary has {len(sentences)} sentences; use no more than three"))
                if summary and story and _norm(summary) == _norm(story):
                    findings.append(_f("ERROR", "SUMMARY_REPEATS_STORY", qid,
                                       "Summary and Story are identical; keep the table concise and put the detail in the story"))
        rendered = [("Summary", b.get("summary") or ""), ("Text", b.get("text") or "")] + [("fact", f["text"]) for f in b["facts"]] + \
                   [("bullet", x) for x in b["bullets"]] + [("row", " | ".join(c)) for c in b["rows"][1:]]
        for where, s_ in rendered:
            hit = totals_in(s_)
            if hit:
                findings.append(_f("ERROR", "NO_TOTALS", qid, f"a {where} counts hosts (\"{hit}\"): name the role groups "
                                   f"or the hosts instead of giving a number or total: {s_[:80]}"))
                break
        shown = role_table_tokens(card)
        if q["kind"] == "observation" and shown:
            for r in b["rows"][1:]:
                named = sorted(set(_HOSTTOKEN.findall(" | ".join(r))) & shown)
                if len(named) >= 2:
                    findings.append(_f("ERROR", "ROLE_TABLE_REPEAT", qid,
                                       f"this row repeats per-host settings the role table above already shows ({', '.join(named[:4])}): "
                                       "keep Aspect rows for points that are not per host, or drop the row: " + " | ".join(r)[:80]))
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
            reg = card.get("host_register")
            if reg and want and want[0].startswith("host") and data:
                role_of = {h: g["role"] for g in reg["groups"] for h in g["hosts"]}
                listed: dict[str, list[int]] = {}
                for n, r in enumerate(data):
                    for h in _HOSTNAME.findall(r[0]):
                        listed.setdefault(role_of.get(h, h), []).append(n)
                split = sorted(role for role, ns in listed.items() if len(set(ns)) > 1 and role in {g["role"] for g in reg["groups"]})
                if split:
                    findings.append(_f("ERROR", "HOSTS_NOT_GROUPED", qid,
                                       f"one row per role group: these roles are spread over several rows: {', '.join(split)}"))
                seen = {h for r in data for h in _HOSTNAME.findall(r[0])}
                missing = sorted(set(role_of) - seen)
                if missing:
                    findings.append(_f("ERROR", "HOSTS_MISSING", qid,
                                       f"captured hosts not in the table (see the card's host register): {', '.join(missing)}"))
    for qid, q in qs.items():
        b = sheet.get(qid)
        pack_rows = card.get("evidence", {}).get(qid, {}).get("rows", [])
        if b and (b["facts"] or b["rows"] or b["bullets"]) and pack_rows:
            used = block_ids(b)
            unused = [r["id"] for r in pack_rows if r.get("status") == "VERIFIED" and not r.get("established")
                      and r["id"].upper() not in used]
            if unused:
                findings.append(_f("WARN", "EVIDENCE_UNUSED", qid,
                                   f"VERIFIED rows on the card for this question are not cited: {', '.join(unused[:5])}. "
                                   "Use one that adds a fact the answer lacks, or leave it out knowingly."))
    if previous:
        findings += regression(previous, sheet, matrix, card)
    findings += kept_facts(sheet, card, findings)
    findings += frame_checks(sheet, card)
    findings += read_checks(sheet, card)
    findings += readability_checks(sheet, card)
    findings += practice_checks(sheet, card)
    findings += subject_checks(sheet, card)
    findings += drawbridge_topic_checks(sheet, card)
    findings += example_checks({k: v for k, v in sheet.items() if not k.startswith("F")})
    for qid in sheet:
        if qid not in qs and not qid.startswith("F"):
            findings.append(_f("WARN", "EXTRA_BLOCK", qid, "this question is not on the card"))
    if draft:
        hard = RELAXED_HARD if relaxed else HARD_CODES
        for x in findings:
            if x["level"] == "ERROR" and x["code"] not in hard:
                x["level"] = "WARN"
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


_EID_PAREN = re.compile(r"\s*\((?:" + _PFX + r"E-\d+(?:\s*,\s*)?)+\)")
_EID_RUN = re.compile(r"\s*(?<![\w:-])" + _PFX + r"E-\d+\b(?:\s*,\s*" + _PFX + r"E-\d+\b)*")
_EMPTY_BR = re.compile(r"[\[\(][\s,;]*[\]\)]")


def no_ids(s: str) -> str:
    """Document text never carries evidence IDs: they stay in Facts, Why and the Fact audit.

    Brackets or parentheses that hold only evidence IDs and punctuation are removed with them,
    so a cell like "hosts [E-043, E-097]" or "events [E-487]" loses the ID reference without
    leaving ``[,]`` or ``[]`` behind. Brackets that carry real content are left alone."""
    s = _EID_PAREN.sub("", s)
    s = _EID_RUN.sub("", s)
    while True:
        t = _EMPTY_BR.sub("", s)
        t = re.sub(r"\s+([;,.|])", r"\1", t)
        t = re.sub(r"(?<=\w),+", ",", t)
        t = re.sub(r"\s{2,}", " ", t).strip(" ,;")
        if t == s:
            break
        s = t
    return s


_REQ_TITLES: dict[str, str] | None = None


def requirement_story_title(req_id: str, fallback: str) -> str:
    """Return the concise controlled description used as a story title."""
    global _REQ_TITLES
    if _REQ_TITLES is None:
        path = (Path(__file__).resolve().parents[2] / "skills" / "csa-document-template" /
                "references" / "requirement-map.csv")
        _REQ_TITLES = {}
        if path.exists():
            with path.open(encoding="utf-8", newline="") as handle:
                _REQ_TITLES = {row["req_id"].strip(): row["requirement"].strip().rstrip(".")
                               for row in csv.DictReader(handle) if row.get("req_id") and row.get("requirement")}
    return _REQ_TITLES.get(req_id, fallback.strip().rstrip("."))


def _quote(s: str, n: int = 90) -> str:
    s = " ".join((s or "").split()).replace('"', "'")
    return s[:n]


def render_records(sheet: dict[str, dict], card: dict, node: dict, section: str, start: int,
                   *, stories_only: bool = False) -> dict:
    """Change-file records for a valid sheet. Returns {records: [markdown], open: [...], keep: [...],
    scaffold: [...], audit: [...]}. Anchors come from the document spec node."""
    recs, open_q, keep, scaffold, audit = [], [], [], [], []
    requirement_stories: list[dict] = []
    n = start
    parts = node["parts"]

    def record(title, where, current, facts, text, why, note, do="Replace"):
        nonlocal n
        eid = f"S{section}-E{n}"
        n += 1
        fl = "\n".join(facts) if facts else "- (no facts: see Why)"
        body = ("" if do == "Delete" else "**Text:**\n\n" + "\n".join("> " + x for x in text.splitlines()) + "\n\n")
        recs.append(f"### {eid} - {title}\n\n**Where:** `{where}` -- currently: \"{_quote(current)}\"\n\n**Do:** {do}\n\n"
                    f"**Facts:**\n\n{fl}\n\n" + body + f"**Why:** {why}\n\n**Note:** {note}\n\n---\n")
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
        if stories_only and q["kind"] != "requirement":
            continue
        p = parts[q["part"]] if q.get("part") is not None and q["part"] < len(parts) else {}
        facts = [f"- [{q['id']}] {f['text']} ({', '.join(f['ids'])}) {{basis: {f['basis']}; scope: {f['scope'] or 'see evidence'}}}"
                 for f in b["facts"]] + [f"- Unknown: {u}" for u in b["unknown"][:1]]
        ids = sorted({i for f in b["facts"] for i in f["ids"] if _EID.fullmatch(i)})
        bg = sorted({i for f in b["facts"] for i in f["ids"] if _KID.fullmatch(i)})
        why = (f"Evidence {', '.join(ids)}." if ids else "No evidence row; see the open question.") + (
            f" Background knowledge (not evidence): {', '.join(bg)}." if bg else "") + (
            f" Rating: {b['rating_reason']}" if b["rating_reason"] else "")
        if q["kind"] == "requirement":
            req = next((r for r in p.get("requirements", []) if r["id"] == q["req_id"]), None)
            if not req:
                continue
            observed = " ".join(_sentence(f) for f in b["facts"]) or "Not Applicable to the system in scope."
            if card.get("requirement_stories") and b.get("summary"):
                observed = no_ids(" ".join(b["summary"].split()))
            elif b.get("text"):
                observed = no_ids(" ".join(b["text"].split()))
            elif b["unknown"]:
                observed += f" Not established: {b['unknown'][0].rstrip('.')}."
            if not stories_only:
                eid = record(f"{q['req_id']} current state and rating", f"{p['table']}-R{req['row']}",
                             (p.get("row_texts") or [""] * req["row"])[req["row"] - 2] if len(p.get("row_texts", [])) >= req["row"] - 1 else q["req_id"],
                             facts, f"Observed: {observed}\nAssessment: {b['rating']}", why,
                             f"Current state and rating of {q['req_id']} from the evidence.")
                audit += [f"| {eid} | {_quote(_sentence(f), 160)} | {', '.join(f['ids'])} | {f['basis']} | {f['scope'] or '-'} |" for f in b["facts"]]
            if card.get("requirement_stories") and b.get("story"):
                requirement_stories.append({"req_id": q["req_id"], "qid": q["id"],
                                            "title": requirement_story_title(
                                                q["req_id"], req.get("text") or q.get("text") or "Requirement"),
                                            "text": no_ids(" ".join(b["story"].split())), "facts": facts,
                                            "why": why, "fact_rows": list(b["facts"])})
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
            if b.get("text"):
                text = "\n".join(no_ids(" ".join(par.split())) for par in b["text"].split("\n\n") if par.strip())
            elif b["unknown"]:
                text += f" Not established: {b['unknown'][0].rstrip('.')}."
            if not text.strip():
                continue
            eid = record(f"{p.get('facet') or node['title']}", p.get("pid", node["hid"] + "-P1"), p.get("current", ""),
                         facts, text, why, f"{p.get('facet') or node['title']} from the evidence.")
            audit += [f"| {eid} | {_quote(_sentence(f), 160)} | {', '.join(f['ids'])} | {f['basis']} | {f['scope'] or '-'} |" for f in b["facts"]]
        elif q["kind"] == "note":
            # The optional note: the note replaces the placeholder (or the note there), 'None' removes it. A
            # placeholder is never left behind: with no note and no pending search, it is removed too.
            text = note_text(b)
            where = p.get("pid") or f"{node['hid']}-P1"
            label = f"{p.get('facet') or node['title']}: note"
            if text and not b["none"]:
                eid = record(label, where, p.get("current", ""), facts, text, why,
                             f"Note under the {p.get('facet') or node['title']} table from the evidence.")
                audit += [f"| {eid} | {_quote(_sentence(f), 160)} | {', '.join(f['ids'])} | {f['basis']} | {f['scope'] or '-'} |" for f in b["facts"]]
            elif b["none"] or (not p.get("answered") and not b["search"]):
                reason = b["none"] if b["none"] not in ("", "yes") else "the table rows show everything the evidence holds"
                record(label, where, p.get("current", ""), [], "", f"No note: {reason.rstrip('.')}.",
                       "Optional note placeholder removed.", do="Delete")
        elif q["kind"] == "findings":
            holders = [(pid, t) for pid, t in zip(p.get("pids", []), p.get("bullets", []))]
            free = [(pid, t) for pid, t in holders if t.startswith("[")]
            bullets = b["bullets"] or [_sentence(f) for f in b["facts"]]
            if len(bullets) > len(free):
                scaffold.append({"kind": "bullets", "heading": p.get("facet") or node["title"], "occurrence": 1,
                                 "set_count": len(holders) - len(free) + len(bullets)})
            for (pid, cur), text in zip(free, bullets):
                record(f"{node['title']}: finding", pid, cur, facts, no_ids(text), why, f"Finding for {node['title']}.")
    if requirement_stories:
        existing = {p.get("req_id"): p for p in node.get("parts", []) if p.get("kind") == "requirement-story"}
        discovery = next((v for k, v in (node.get("facets") or {}).items()
                          if k.strip().lower() == "discovery information"), None)

        def story_record(item: dict, where: str, current: str, do: str) -> None:
            text = f"{item['req_id']} — {item['title']}\n\n{item['text']}"
            # A format-only record still carries one existing evidence-backed
            # fact so the ordinary change-file evidence gate remains intact.
            facts = item["facts"][:1] if stories_only else item["facts"]
            why = ("Formatting only: separated the requirement title from the unchanged story paragraph."
                   if stories_only else item["why"])
            note = ("Reformatted the requirement story with a descriptive title and the narrative underneath."
                    if stories_only else f"Evidence-backed story for {item['req_id']} under Discovery Information.")
            eid = record(f"{item['req_id']} discovery story", where, current, facts, text, why, note, do=do)
            audit.extend(f"| {eid} | {_quote(_sentence(f), 160)} | {', '.join(f['ids'])} | {f['basis']} | {f['scope'] or '-'} |"
                         for f in item["fact_rows"])

        # Existing managed stories are replaced in place. Missing contiguous runs are inserted relative to the
        # next existing story, or in reverse after the previous story/Discovery heading so document order is stable.
        for item in requirement_stories:
            part = existing.get(item["req_id"])
            if part:
                action = "Replace this paragraph and the following line" if part.get("body_pid") else "Replace"
                story_record(item, part["pid"], part.get("current") or item["req_id"], action)
        missing = [i for i, item in enumerate(requirement_stories) if item["req_id"] not in existing]
        while missing:
            start_i = missing[0]
            run = [start_i]
            while len(run) < len(missing) and missing[len(run)] == run[-1] + 1:
                run.append(missing[len(run)])
            missing = missing[len(run):]
            next_i = next((i for i in range(run[-1] + 1, len(requirement_stories))
                           if requirement_stories[i]["req_id"] in existing), None)
            if next_i is not None:
                anchor = existing[requirement_stories[next_i]["req_id"]]
                for i in run:
                    story_record(requirement_stories[i], anchor["pid"], anchor.get("current") or anchor["req_id"],
                                 "Insert Before")
                continue
            prev_i = next((i for i in range(run[0] - 1, -1, -1)
                           if requirement_stories[i]["req_id"] in existing), None)
            if prev_i is not None:
                anchor = existing[requirement_stories[prev_i]["req_id"]]
                where, current = anchor["pid"], anchor.get("current") or anchor["req_id"]
            else:
                if not discovery:
                    raise ValueError("requirement stories need a Discovery Information heading")
                where, current = discovery["hid"], discovery["title"]
            for i in reversed(run):
                story_record(requirement_stories[i], where, current, "Insert After")

    return {"records": recs, "open": open_q, "keep": keep, "scaffold": scaffold, "audit": audit, "next": n}


def render_change_file(sheet: dict[str, dict], card: dict, node: dict, spec: dict, *, app: str, docx_name: str,
                       section: str, start: int, brief: str, existing: str | None = None,
                       stories_only: bool = False) -> dict:
    """A new change file, or `existing` with the new records, audit rows, unchanged items and open questions added
    (earlier records are never touched; the brief is replaced by the one from the document)."""
    r = render_records(sheet, card, node, section, start, stories_only=stories_only)
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
        text = supersede(text, r["records"])
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


_TARGET = re.compile(r"\*\*Where:\*\*\s*`(@H[\w.\-]+)")
_RECORD = re.compile(r"(?ms)^### (S\d+(?:\.\d+)?-E\d+)\b.*?(?=^### |^## |\Z)")


def supersede(text: str, new_records: list[str]) -> str:
    """Remove earlier records that are still pending (not on an Applied: line) and target the same anchor as a
    new record, so one cell or paragraph never carries two pending replacements (apply would stack them).
    Applied records stay as history. The removed IDs are noted under Proposed changes."""
    targets = {m.group(1) for rec in new_records for m in [_TARGET.search(rec)] if m}
    if not targets:
        return text
    applied = set()
    for line in re.findall(r"(?m)^Applied:\s*(.+)$", text):
        applied |= {x.strip(" .") for x in line.split(",")}
    gone = []
    def drop(m: re.Match) -> str:
        t = _TARGET.search(m.group(0))
        if t and t.group(1) in targets and m.group(1) not in applied:
            gone.append(m.group(1))
            return ""
        return m.group(0)
    text = _RECORD.sub(drop, text)
    if gone:
        span = _section_span(text, "Proposed changes")
        note = f"\n_Superseded by the newer answer and removed before apply: {', '.join(gone)}._\n"
        if span:
            text = text[:span[1]].rstrip() + "\n" + note + text[span[1]:]
    return text


def next_edit_number(reviews: Path, section: str) -> int:
    """The next S<N>-E<n> after every one already used for this section in reviews/."""
    used = [0]
    for f in Path(reviews).glob(f"ChangesCSA_*_Section{section}*.md"):
        used += [int(x) for x in re.findall(rf"\bS{section}-E(\d+)\b", f.read_text(encoding="utf-8", errors="ignore"))]
    return max(used) + 1


_LEAD_STOP = set("""a an and any are as at be been by can could did do does for from has have how in into is it its of on or
that the their there these this to was were what when where whether which who whose will with would owner owners confirm confirmed
confirms provide record records team service system systems held each every which""".split())


def _lead_words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in _LEAD_STOP}


def unknown_leads(sheet: dict[str, dict], matrix: dict[str, dict], limit: int = 4) -> list[dict]:
    """Matrix rows that may already answer an Unknown: line: [{question, unknown, rows: [{id, status, claim}]}].
    A row is a lead when it is not cited in the block and either names the same host or address as the Unknown and
    shares a content word with it, or shares at least three content words with it. A NOT_FOUND row counts: it is the
    evidenced "no such record", which is a finding the block can state. Nothing here is inferred; the rows are only
    shown to the agent, which cites one or keeps the Unknown."""
    out = []
    for qid, b in sheet.items():
        cited = block_ids(b)
        for u in b.get("unknown", []):
            ids = {x.upper() for x in _IP.findall(u)} | {x.upper() for x in _HOST.findall(u)}
            words = _lead_words(u) - {w.lower() for w in ids}
            scored = []
            for rid, r in matrix.items():
                if rid.upper() in cited or _prefix(rid) or r.get("status") not in ("VERIFIED", "NOT_FOUND", "UNCONFIRMED", "CONFLICTING"):
                    continue                          # another project's rows are context, never this system's answer
                claim = r.get("claim", "")
                shared = len(words & _lead_words(claim))
                named = any(re.search(rf"(?<![\w.]){re.escape(i)}(?![\w]|\.\d)", claim, re.I) for i in ids)
                vague = claim.lower().startswith("possible answer to")      # a pointer to a question, not a finding
                if (named and shared >= 1) or (shared >= 4 and not vague):
                    scored.append((named, shared, r.get("status") == "VERIFIED", rid, r))
            scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
            if scored:
                out.append({"question": qid, "unknown": u,
                            "rows": [{"id": s[3], "status": s[4].get("status", ""), "claim": s[4].get("claim", "")[:420]}
                                     for s in scored[:limit]]})
    return out


def leads_text(leads: list[dict]) -> str:
    lines = ["Evidence rows that may already answer an Unknown: line. Read each row. If it answers the question, state "
             "what it shows as a fact, cite its E- ID with its basis, and keep an Unknown: line only for the part it "
             "does not answer (say what the row states is missing, e.g. a name that was not captured). A NOT_FOUND row "
             "is an evidenced absence: state it as one. If a row does not answer, leave the Unknown: line as it is. "
             "When a row says what a source describes the subject as, state that as a documented fact in the source's "
             "own words (\"described in the earlier assessment as ...\") and keep the Unknown: only for what the row "
             "says was not captured. "
             "Do not carry a count or total of hosts from a row (\"twelve hosts\", \"eleven hosts\"): name the role groups or "
             "the hosts instead (NO_TOTALS). Change nothing else in the sheet.", ""]
    for l in leads:
        lines.append(f"- {l['question']} Unknown: {l['unknown']}")
        lines += [f"  - {r['id']} {r['status']}: {r['claim']}" for r in l["rows"]]
    return "\n".join(lines) + "\n"


def sheet_hash_drift(sheet_path: Path) -> dict | None:
    """A warning when the manifest beside the sheet records another sheet than the one being validated: the document was
    last written from the recorded sheet, not this one. None without a manifest or without a recorded hash."""
    import hashlib
    path = Path(sheet_path)
    manifest = path.with_name(path.name[: -len(".answer.md")] + ".manifest.json") if path.name.endswith(".answer.md") else None
    if not manifest or not manifest.is_file() or not path.is_file():
        return None
    try:
        recorded = json.loads(manifest.read_text(encoding="utf-8")).get("sheet_sha256")
    except (OSError, ValueError):
        return None
    live = hashlib.sha256(path.read_bytes()).hexdigest()
    if not recorded or recorded == live:
        return None
    return _f("WARN", "SHEET_HASH_DRIFT", "",
              f"manifest records {recorded[:8]} (applied sheet) but the live sheet is {live[:8]}; "
              "the document was last written from the recorded sheet")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["validate", "parse", "render", "leads"])
    ap.add_argument("sheet", type=Path)
    ap.add_argument("--card", type=Path, required=True)
    ap.add_argument("--matrix", type=Path)
    ap.add_argument("--new-ids", default="", help="validate: evidence IDs appended during this run")
    ap.add_argument("--draft", action="store_true", help="validate: draft lane, only the hard checks are errors")
    ap.add_argument("--relaxed", action="store_true", help="validate --draft: only RELAXED_HARD are errors (cli.yaml draft_strictness)")
    ap.add_argument("--previous", type=Path, help="validate: the sheet this one replaces (regression report)")
    ap.add_argument("--docx", type=Path, help="render: the working document")
    ap.add_argument("--section", help="render: framework section number (3)")
    ap.add_argument("--change-file", type=Path, help="render: the change file to write (merged when it exists)")
    ap.add_argument("--app", default="")
    ap.add_argument("--stories-only", action="store_true",
                    help="render only requirement-story title/body records")
    a = ap.parse_args(argv)
    sheet = parse(a.sheet.read_text(encoding="utf-8"))
    if a.action == "parse":
        print(json.dumps(sheet, indent=1))
        return 0
    card = json.loads(a.card.read_text(encoding="utf-8"))
    if a.action == "leads":
        leads = unknown_leads(sheet, load_matrix(a.matrix))
        print(json.dumps({"leads": leads, "text": leads_text(leads) if leads else ""}, indent=1))
        return 0
    if a.action == "validate":
        prev = parse(a.previous.read_text(encoding="utf-8")) if a.previous and a.previous.is_file() else None
        res = validate(sheet, card, load_matrix(a.matrix), new_ids={x.strip() for x in a.new_ids.split(",") if x.strip()},
                       draft=a.draft, previous=prev, relaxed=getattr(a, "relaxed", False))
        drift = sheet_hash_drift(a.sheet)
        if drift:
            res["findings"].append(drift)
            res["warnings"] += 1
        print(json.dumps(res, indent=1))
        return 0 if res["status"] == "OK" else 1
    from csa_docx import doc_spec, section_card, spec_cli
    spec = spec_cli.load(a.docx)
    node = doc_spec.resolve(spec, card["key"])
    cf = a.change_file
    existing = cf.read_text(encoding="utf-8") if cf and cf.is_file() else None
    start = next_edit_number(cf.parent, a.section) if cf else 1
    out = render_change_file(sheet, card, node, spec, app=a.app, docx_name=a.docx.name if a.docx else "",
                             section=a.section, start=start, brief=section_card.brief_markdown(node, spec), existing=existing,
                             stories_only=a.stories_only)
    if cf and not out["scaffold"]:
        cf.parent.mkdir(parents=True, exist_ok=True)
        cf.write_text(out["text"], encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "text"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
