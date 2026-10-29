"""Which way a connection goes, checked against the evidence rows that state it.

An evidence row for a connection names who opened it and to whom ("A and B opened file share connections on TCP 445
to C"). A sentence in an answer that says the opposite, or says the connection came "into OT" when every row shows
OT opening it, is wrong however well the rest reads. Three checks, all blocking in the draft lane:

DIRECTION_REVERSED     a Fact, or a sentence of the Summary / Story / Text / Rating reason, gives a connection the
                       wrong direction for the rows it rests on (the rows of that Fact, or of the block's Facts)
PROSE_NOT_IN_FACTS     the Summary / Story / Text / Rating reason names an address, host or kind of connection that no
                       Fact of the block states: the prose says more than the evidence the block cites

The checks only fire when they are sure: an end that cannot be placed (an unnamed peer, a part the card does not list)
is never a reason to object.
"""
from __future__ import annotations

import re

_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_HOST = re.compile(r"\b[A-Z]{6,}\d{3}\b")

#: kind of connection -> how a sentence or an evidence row names it
KINDS = {
    "file share": re.compile(r"\bfile[- ]?shares?\b|\bServer Message Block\b|\bSMB\b", re.I),
    "backup agent": re.compile(r"\bbackup[- ]agent\b", re.I),
    "MySQL": re.compile(r"\bMySQL\b|\b(?:TCP|port) 3306\b", re.I),
    "replication": re.compile(r"\breplication\b", re.I),
    "SQL Server": re.compile(r"\bSQL(?: Server)?\b|\b(?:TCP|port) (?:56420|1433)\b", re.I),
    "web": re.compile(r"\bweb\b", re.I),
    "message": re.compile(r"\bmessage\b", re.I),
}
#: an evidence row that says "database connections" without a word for the kind
_GENERIC_DB = re.compile(r"\bdatabase connections?\b", re.I)

_EDGE = re.compile(r"^(?P<op>.+?)\s+(?:opened|opens)\s+(?P<mid>.+?)\s+(?:to|into)\s+(?P<tg>.+)$", re.S)
_CLAIM = re.compile(r"^(?P<subj>.+?)\s+(?:opens?|opened)\s+(?P<mid>.+?)\s+(?:to|into)\s+(?P<obj>[^,;]+)", re.S)
_CLAUSES = re.compile(r";\s*|,\s+and\s+|,?\s+(?:while|whereas|but|even though|even if|although)\s+")
_INTO_OT = re.compile(r"\binto (?:the )?OT\b(?!-)|\bfrom (?:far-end|outside)\b", re.I)
_OUTWARD = re.compile(r"\boutward\b|\bout of OT\b|\bleav(?:e|es|ing) OT\b|\bfrom OT to\b", re.I)
_PROSE = ("summary", "story", "text", "rating_reason")


def kinds_in(text: str, row: bool = False) -> set[str]:
    """The kinds of connection a sentence or an evidence row names. A row's "database connections" is the SQL Server kind
    unless the row names MySQL (port 3306)."""
    out = {k for k, rx in KINDS.items() if rx.search(text or "")}
    if row and _GENERIC_DB.search(text or "") and "MySQL" not in out and "replication" not in out:
        out.add("SQL Server")
    if row and "replication" in out:
        out.discard("SQL Server")
    return out


class Places:
    """Where an address, host or part sits for this card: the part it belongs to and that part's side of OT."""

    def __init__(self, card: dict):
        pc = card.get("parts") or {}
        self.names: dict[str, list[str]] = pc.get("names") or {}
        self.sides: dict[str, str] = pc.get("sides") or {}
        self.hosts: dict[str, str] = pc.get("hosts") or {}
        self.ok = bool(self.names or self.hosts)

    def keys(self, text: str) -> set[str]:
        """Identities in a text: each address, each host (and its part), each part named."""
        from csa_docx.parts import parts_in
        out = set(_IP.findall(text or "")) | {h.upper() for h in _HOST.findall(text or "")}
        out |= {f"part:{self.hosts[h]}" for h in list(out) if h in self.hosts}
        out |= {f"part:{p}" for p in parts_in(text or "", self.names)}
        return out

    def in_ot(self, text: str) -> tuple[bool, bool]:
        """(every address and host named is in OT, at least one is): addresses and hosts only, since a part named
        in a row's text is its host."""
        units = set(_IP.findall(text or "")) | {h.upper() for h in _HOST.findall(text or "")}
        if not units:
            return False, False
        flags = [self.sides.get(self.hosts.get(u, ""), "") == "ot" for u in units]
        return all(flags), any(flags)


def edges(claim: str, pl: Places) -> list[dict]:
    """The connection a row states: {"kind", "opener", "target", "dir"}; empty when the row is not one."""
    first = (claim or "").split(". ")[0]
    m = _EDGE.match(first)
    if not m:
        return []
    tg = re.split(r";|\s\(", m["tg"])[0]
    kinds = kinds_in(m["mid"], row=True) or kinds_in(first, row=True)
    if not kinds:
        return []
    op_all, op_any = pl.in_ot(m["op"])
    tg_all, tg_any = pl.in_ot(tg)
    direction = ("outbound" if op_all and not tg_any else "inbound" if tg_any and not op_any
                 else "inside" if op_all and tg_all else "mixed")
    return [{"kind": k, "opener": pl.keys(m["op"]), "target": pl.keys(tg), "dir": direction} for k in sorted(kinds)]


def _row_claims(card: dict, matrix: dict | None) -> dict[str, str]:
    out = {r["id"].upper(): r.get("claim", "") for p in (card.get("evidence") or {}).values() for r in p.get("rows", [])}
    for i, r in (matrix or {}).items():
        out.setdefault(i.upper(), r.get("claim", ""))
    return out


def _ids(facts: list[dict]) -> list[str]:
    seen: list[str] = []
    for f in facts:
        for i in f.get("ids") or []:
            if i.upper() not in seen:
                seen.append(i.upper())
    return seen


def _reversed(sentence: str, rows: list[tuple[str, dict]], pl: Places) -> str | None:
    """A message when the sentence gives a connection the opposite end-to-end direction to the rows."""
    m = _CLAIM.match(sentence)
    if m:
        kinds = kinds_in(m["mid"])
        subj, obj = pl.keys(m["subj"]), pl.keys(m["obj"])
        if kinds and subj and obj:
            same = [(i, e) for i, e in rows if e["kind"] in kinds]
            agree = [1 for _, e in same if subj & e["opener"] or obj & e["target"]]
            flip = [(i, e) for i, e in same if (obj & e["opener"] and not subj & e["opener"] and not obj & e["target"])
                    or (subj & e["target"] and not subj & e["opener"] and not obj & e["target"])]
            if flip and not agree:
                return (f"the evidence ({', '.join(sorted({i for i, _ in flip}))}) says the connection is opened the other "
                        f"way round: swap who opens it and who it goes to")
    for clause in _CLAUSES.split(sentence):
        inward, outward = _INTO_OT.search(clause), _OUTWARD.search(clause)
        if bool(inward) == bool(outward):
            continue
        for k in sorted(kinds_in(clause)):
            dirs = {e["dir"] for _, e in rows if e["kind"] == k}
            ids = sorted({i for i, e in rows if e["kind"] == k})
            if inward and dirs == {"outbound"}:
                return (f"the {k} connections are opened by OT hosts to far ends outside it ({', '.join(ids[:4])}), not "
                        f"into OT: say OT opens them")
            if outward and dirs == {"inbound"}:
                return (f"the {k} connections are opened by far ends into OT ({', '.join(ids[:4])}), not outward from OT: "
                        f"say the far end opens them")
    return None


def direction_checks(sheet: dict[str, dict], card: dict, matrix: dict | None, finding) -> list[dict]:
    """DIRECTION_REVERSED and PROSE_NOT_IN_FACTS findings (``finding`` builds a finding dict)."""
    pl = Places(card)
    if not pl.ok:
        return []
    claims = _row_claims(card, matrix)
    out: list[dict] = []
    for qid, b in sheet.items():
        if qid.startswith("F") or not b.get("facts"):
            continue
        by_id = {i: edges(claims.get(i, ""), pl) for i in _ids(b["facts"])}
        block_rows = [(i, e) for i, es in by_id.items() for e in es]
        if not block_rows:
            continue
        for f in b["facts"]:
            rows = [(i.upper(), e) for i in f.get("ids") or [] for e in by_id.get(i.upper(), [])]
            msg = _reversed(f["text"], rows, pl) if rows else None
            if msg:
                out.append(finding("ERROR", "DIRECTION_REVERSED", qid, f"a Fact has the connection the wrong way round: "
                                   f"{msg}: \"{f['text'][:150]}\""))
        fields = [x for x in _PROSE if not (x == "text" and b.get("text") == b.get("story"))]    # Story is copied into Text
        for field in fields:
            for s in re.split(r"(?<=[.!?])\s+|\n+", b.get(field) or ""):
                msg = _reversed(s, block_rows, pl) if s.strip() else None
                if msg:
                    out.append(finding("ERROR", "DIRECTION_REVERSED", qid, f"the {field.replace('_', ' ').title()} "
                                       f"contradicts the Facts: {msg}: \"{s[:150]}\""))
        stated = " ".join(f.get("line") or f["text"] for f in b["facts"]) + " " + " ".join(b.get("unknown") or [])
        known = set(_IP.findall(stated)) | {h.upper() for h in _HOST.findall(stated)}
        kinds_stated = kinds_in(stated) | {k for _, e in block_rows for k in [e["kind"]]}
        for field in fields:
            prose = b.get(field) or ""
            extra = sorted((set(_IP.findall(prose)) | {h.upper() for h in _HOST.findall(prose)}) - known)
            more = sorted(kinds_in(prose) - kinds_stated)
            if extra or more:
                what = ", ".join(extra[:4] + [f"{k} connections" for k in more[:3]])
                out.append(finding("WARN", "PROSE_NOT_IN_FACTS", qid, f"the {field.replace('_', ' ').title()} names "
                                   f"{what}, which no Fact of this block states: add the Fact with its evidence ID, or take "
                                   f"it out of the {field.replace('_', ' ').title()}"))
    return out
