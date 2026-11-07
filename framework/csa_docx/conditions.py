"""Requirement conditions and the ratings a judgement may choose.

A requirement's text often sets more than one condition ("OT-resident storage, independent of IT-hosted file shares,
or a documented fallback"). ``references/requirement-conditions/*.json`` splits each requirement into conditions and the
logic that joins them; a requirement with no entry has one condition, its own text. The judge answers each condition
yes, no or unknown with the findings that show it, and ``rating_range`` turns the answers into the ratings allowed:

* the logic holds on yes answers only -> Met or Partially Met
* the logic fails and nothing holds   -> Not Met
* the logic fails, something holds     -> Partially Met or Not Met
* the logic is open (unknown, or a condition true of only some parts: "partly") -> Partially Met or Not Met
* Not Applicable stays allowed (it needs a justification); a practice cap (S398) removes ratings above it.

    python3 -m csa_docx.conditions show SEP-STOR-01
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REF = Path(__file__).resolve().parents[2] / "references" / "requirement-conditions"
DEFAULT_RATINGS = ["Met", "Partially Met", "Not Met", "Not Applicable"]
_TOKEN = re.compile(r"\s*(\(|\)|and\b|or\b|not\b|C\d+)\s*", re.I)


def _all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(REF.glob("*.json")):
        try:
            out.update(json.loads(f.read_text(encoding="utf-8")).get("requirements") or {})
        except (OSError, ValueError):
            continue
    return out


def load(req_id: str, text: str = "") -> dict:
    """{"conditions": [{"id", "text"}], "logic", "reviewed", "default"} for a requirement."""
    e = _all().get(req_id)
    if e and e.get("conditions"):
        return {"conditions": list(e["conditions"]), "logic": e.get("logic") or " and ".join(c["id"] for c in e["conditions"]),
                "reviewed": bool(e.get("reviewed")), "default": False, "basis": e.get("basis", "")}
    return {"conditions": [{"id": "C1", "text": text or req_id}], "logic": "C1", "reviewed": False, "default": True, "basis": ""}


def evaluate(logic: str, values: dict[str, str]) -> str:
    """Three-valued result ("yes" | "no" | "unknown") of ``logic`` over {condition id: yes|no|partly|unknown}. "partly"
    (true of some parts of the system, not others) counts as open, like unknown."""
    toks = [m.group(1) for m in _TOKEN.finditer(logic or "") if m.group(1)]
    if "".join(toks).replace(" ", "").lower() != re.sub(r"\s+", "", logic or "").lower():
        raise ValueError(f"cannot read the condition logic: {logic!r}")
    pos = 0

    def val(t: str) -> int:                       # 1 yes, 0 no, -1 unknown
        v = (values.get(t.upper()) or values.get(t) or "unknown").lower()
        return 1 if v == "yes" else 0 if v == "no" else -1

    def atom() -> int:
        nonlocal pos
        t = toks[pos]; pos += 1
        if t == "(":
            r = expr()
            pos += 1                              # ")"
            return r
        if t.lower() == "not":
            r = atom()
            return -1 if r == -1 else 1 - r
        return val(t)

    def term() -> int:
        nonlocal pos
        r = atom()
        while pos < len(toks) and toks[pos].lower() == "and":
            pos += 1
            b = atom()
            r = 0 if 0 in (r, b) else (-1 if -1 in (r, b) else 1)
        return r

    def expr() -> int:
        nonlocal pos
        r = term()
        while pos < len(toks) and toks[pos].lower() == "or":
            pos += 1
            b = term()
            r = 1 if 1 in (r, b) else (-1 if -1 in (r, b) else 0)
        return r

    res = expr()
    return {1: "yes", 0: "no", -1: "unknown"}[res]


def rating_range(cond: dict, values: dict[str, str], ratings: list[str] | None = None, cap: str = "") -> list[str]:
    """The ratings a judgement may choose, in the template's order."""
    ratings = list(ratings or DEFAULT_RATINGS)
    res = evaluate(cond["logic"], values)
    some_yes = any((values.get(c["id"]) or "").lower() in ("yes", "partly") for c in cond["conditions"])
    if res == "yes":
        allowed = {"Met", "Partially Met"}
    elif res == "no":
        allowed = {"Partially Met", "Not Met"} if some_yes else {"Not Met"}
    else:
        allowed = {"Partially Met", "Not Met"}
    allowed.add("Not Applicable")
    if cap and cap in ratings:
        allowed = {r for r in allowed if r == "Not Applicable" or ratings.index(r) >= ratings.index(cap)}
    return [r for r in ratings if r in allowed]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("show",))
    ap.add_argument("req_id")
    a = ap.parse_args(argv)
    print(json.dumps(load(a.req_id), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
