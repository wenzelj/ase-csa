"""Two checks on a requirement domain's Drawbridge Impact block, from what the card already holds.

ISOLATION_PATH_KEPT         a sentence says an OT part keeps a path that the card's isolation digest says it loses or may lose
                            ("keep their SQL and Azure message bus paths" when the Azure endpoint is outside OT)
DRAWBRIDGE_FUNCTION_MISSING a function the card lists for this domain ("Function with an explicit ... dependency to assess") is
                            neither written about nor raised as a QUESTION: the block answers only some of what depends on it
"""
from __future__ import annotations

import re

_KEEP = re.compile(r"\b(?:keeps?|kept|continues?|remains?|stays?|still (?:works?|runs?|reaches|has)|unaffected|survives?|retains?)\b", re.I)
_LOST = re.compile(r"\b(?:lose|loses|lost|loss|cut|stops?|unreachable|unavailable|no longer|severed|fail|fails)\b", re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|,?\s+(?:but|while|whereas|although)\s+|;\s*")
#: words that name a kind of path (a mechanism), as against a far end's name ("dell") or a thing a host holds locally
#: ("database"): only these decide that a sentence keeps a path the digest says is lost
_MECHANISM = {"message", "mail", "email", "smtp", "web", "backup", "monitoring", "directory", "management", "forwarding", "logging",
              "telemetry", "patch", "remote", "share", "platform", "internet", "azure", "proxy", "broker", "dns", "time"}
_STAYS_IN_OT = re.compile(r"\b(?:remains?|stays?|keeps?|kept)\s+(?:running\s+|working\s+)?(?:inside|within|in)\s+(?:the\s+)?OT\b", re.I)
_PATH = re.compile(r"\b(?:paths?|connections?|links?|routes?|channels?|bus|conduits?|feeds?|access)\b", re.I)
_CAUSE = re.compile(r"^\s*(?:with|when|if|during|after)\b[^,]{0,120},\s*", re.I)
_GENERIC = {"server", "servers", "service", "services", "records", "alerts", "data", "view", "system", "path", "paths", "access",
            "with", "from", "that", "this", "their", "which"}


def path_kept_checks(sheet: dict, card: dict, finding) -> list[dict]:
    from csa_docx.parts import named
    pc = card.get("parts") or {}
    iso = pc.get("isolation") or {}
    if not iso:
        return []
    drawbridge = {q["id"] for q in card.get("questions", []) if q.get("kind") == "narrative" and "drawbridge" in str(q.get("text") or "").lower()}
    out = []
    for qid in drawbridge:
        b = sheet.get(qid)
        if not b:
            continue
        for clause in _SPLIT.split(b.get("text") or ""):         # the Drawbridge Text says what keeps working; the Facts state evidence
            clause = _CAUSE.sub("", clause)           # "With the storage path cut, ..." is the cause, not a loss in the sentence
            if not _KEEP.search(clause) or _LOST.search(clause) or not _PATH.search(clause) or _STAYS_IN_OT.search(clause):
                continue
            low = clause.lower()
            for pid, d in iso.items():
                if pc.get("sides", {}).get(pid) != "ot" or not named(clause, pc.get("names", {}).get(pid, [])):
                    continue
                own = set(re.findall(r"[a-z]{4,}", " ".join(pc["names"].get(pid, [])).lower()))
                lost = [w for w in d.get("loss", []) if w in _MECHANISM and w in low and w not in own and w not in d.get("safe", [])]
                if lost:
                    out.append(finding("ERROR", "ISOLATION_PATH_KEPT", qid,
                                       f"{pc['parts'][pid]} {d.get('effect', '')[:170]}: the sentence says it keeps its {', '.join(lost[:3])} "
                                       f"path, which isolation cuts or may cut. Say what is cut, or raise whether it survives as a "
                                       f"QUESTION: \"{clause.strip()[:150]}\""))
                    break
    return out


def _addressed(function: str, dependency: str, text: str) -> bool:
    """The block is about the function when it uses the function's own words (two of them, or the only one) or enough of the
    words of its recorded dependency ("RevBroadcast", "Azure"): a block names "the RevBroadcast server loses its Azure
    connection" for the function "Broadcast and external data"."""
    own = [w for w in re.findall(r"[a-z]{4,}", function.lower()) if w not in _GENERIC]
    dep = {w for w in re.findall(r"[a-z]{6,}", dependency.lower()) if w not in _GENERIC} - set(own)
    if not own and not dep:
        return True
    hit_own = sum(1 for w in own if w[:5] in text)
    hit_dep = sum(1 for w in dep if w[:5] in text)
    need = 1 if len(own) <= 2 else 2            # a short name ("Downstream FCC data to IAMPS") is met by one of its words
    return hit_own >= need or hit_own + hit_dep >= 3


def function_checks(sheet: dict, card: dict, finding) -> list[dict]:
    out = []
    for qid, fns in (card.get("drawbridge_functions") or {}).items():
        b = sheet.get(qid)
        if not b:
            continue
        text = " ".join([b.get("text") or ""] + [f["text"] for f in b.get("facts", [])] + list(b.get("unknown") or [])).lower()
        missing = [f["function"] for f in fns if not _addressed(f["function"], f.get("dependency", ""), text)]
        if missing:
            out.append(finding("WARN", "DRAWBRIDGE_FUNCTION_MISSING", qid,
                               f"the card lists {len(fns)} function(s) that depend on {fns[0].get('domain', 'this domain')}; the block "
                               f"does not cover: {'; '.join(missing)}. Write what stops or keeps working for each, from this domain's "
                               "evidence, or raise it as a QUESTION"))
    return out


_STOPS = re.compile(r"\b(?:stops?|stopped|lose[sd]?|lost|no longer|cannot|unavailable|ceases?|fails?)\b", re.I)
_HEDGE = re.compile(r"\b(?:may|might|could|whether|if|unless|not established|unknown|undetermined|at risk|"
                    r"cannot be (?:established|determined)|not (?:been )?(?:established|determined))\b", re.I)


def effect_checks(sheet: dict, card: dict, finding) -> list[dict]:
    """FUNCTION_STOP_NOT_ESTABLISHED: a Drawbridge sentence says a function stops, and the card's own working-out from the flows
    ("The flows establish") finds no cut path for it in this domain. A function that only has paths whose zone is not recorded
    may stop; saying it stops needs a cut path, or the sentence says "may" and the open question is asked."""
    out = []
    for qid, fns in (card.get("drawbridge_functions") or {}).items():
        b = sheet.get(qid)
        if not b:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", b.get("text") or ""):
            low = sentence.lower()
            if not _STOPS.search(sentence) or _HEDGE.search(sentence):
                continue
            for fn in fns:
                if fn.get("cut") or not (fn.get("may_cut") or fn.get("kept")) or not _named(fn["function"], low):
                    continue            # a domain whose mechanism the flows do not carry (DNS, time) gives no verdict either way
                state = ("only paths whose zone is not recorded" if fn.get("may_cut") else
                         "its paths stay inside OT" if fn.get("kept") else "no path in this domain")
                out.append(finding("ERROR", "FUNCTION_STOP_NOT_ESTABLISHED", qid,
                                   f"the sentence says {fn['function']} stops, but the flows establish no cut path for it ({state}). "
                                   f"Say what is established (it may stop, or it keeps working), and ask what would settle the rest "
                                   f"as a QUESTION: \"{sentence.strip()[:150]}\""))
                break
    return out


def _named(function: str, low: str) -> bool:
    """The sentence uses the function's own words, whole ("operations" is not "operator")."""
    own = [w for w in re.findall(r"[a-z]{4,}", function.lower()) if w not in _GENERIC]
    words = set(re.findall(r"[a-z0-9]+", low))
    need = 1 if len(own) <= 2 else 2
    return bool(own) and sum(1 for w in own if w in words or w + "s" in words) >= need
