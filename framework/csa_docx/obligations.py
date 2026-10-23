"""What each answered question of a section card owes: one contract the model's input and the checks both read.

A question owes three kinds of thing, each named by evidence IDs:

* ``must``  the analysis frame's "must address" findings for the question (SLOT_NOT_ANSWERED): each cited in the block,
            or raised on an Unknown: line that names it. An ``empty`` item (a slot the captures leave open) needs an
            Unknown: line in the block.
* ``flows`` the flows across the OT boundary this question owns (FLOW_NOT_COVERED). A flow that a requirement's
            must-address findings already carry is owed there (``must``), so it has no separate owner. A flow no
            requirement carries is owned by the narrative question (Drawbridge Impact), else the first requirement.
* ``kept``  the card's Facts to keep for the question (CAPTURE_DROPPED): restated with their capture evidence, or
            named on a Dropped: line with the reason.

``report`` shows, per question, whether each obligation is in the input the model gets, and, given an answer sheet,
which are unmet and why. It changes nothing.

    python3 -m csa_docx.obligations report <card.json> [--sheet <answer sheet>] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ANSWERED = ("requirement", "observation", "narrative")


def _up(ids) -> list[str]:
    return [str(i).upper() for i in ids or []]


def owners(card: dict) -> dict[int, str]:
    """{coverage index: owning question id} for the coverage flows no requirement's must-address findings carry."""
    qs = [q for q in card.get("questions", []) if q.get("kind") in ANSWERED]
    reqs = [q["id"] for q in qs if q["kind"] == "requirement"]
    narr = next((q["id"] for q in qs if q["kind"] == "narrative"), None)
    must = (card.get("frame") or {}).get("must_address") or {}
    must_ids = {qid: {i for x in must.get(qid, []) for i in _up(x.get("ids"))} for qid in reqs}
    out = {}
    for n, c in enumerate((card.get("frame") or {}).get("coverage") or []):
        ids = set(_up(c.get("ids")))
        if any(ids & must_ids[q] for q in reqs):
            continue                                  # owed in that requirement's must-address (SLOT_NOT_ANSWERED)
        owner = narr or (reqs[0] if reqs else None)
        if owner:
            out[n] = owner
    return out


def obligations(card: dict, qid: str) -> dict | None:
    """{"qid", "kind", "must": [item], "flows": [item], "kept": [item]} for an answered question, else None. Items keep
    the card's own fields (text, slot, ids, tokens, empty; fact, evidence_ids, capture_ids)."""
    q = next((x for x in card.get("questions", []) if x["id"] == qid), None)
    if not q or q.get("kind") not in ANSWERED:
        return None
    fr = card.get("frame") or {}
    own = owners(card)
    return {"qid": qid, "kind": q["kind"],
            "must": list((fr.get("must_address") or {}).get(qid, [])) if q["kind"] == "requirement" else [],
            "flows": [c for n, c in enumerate(fr.get("coverage") or []) if own.get(n) == qid],
            "kept": [k for k in card.get("keep") or [] if k.get("question") == qid]}


def shown_ids(card: dict, qid: str) -> set[str]:
    """The evidence IDs the model's input for ``qid`` carries (requirement_view, or compose_view before any verdict)."""
    from csa_docx import requirement_answer, section_card
    q = next((x for x in card.get("questions", []) if x["id"] == qid), {})
    if q.get("kind") == "requirement":
        v = section_card.requirement_view(card, qid) or {}
        return {i for f in v.get("findings", []) for i in _up(f.get("ids"))}
    v = requirement_answer.compose_view(card, qid, {}) or {}
    return set(_up(v.get("ids"))) | {i for f in v.get("findings", []) for i in _up(f.get("ids"))}


def _status(item: dict, block: dict | None, ids_key: str = "ids") -> str:
    from csa_docx import answer_sheet as A
    if block is None:
        return "no block"
    ids = set(_up(item.get(ids_key)))
    if ids & {i.upper() for i in A.block_ids(block)}:
        return "cited"
    if ids & set(_up(block.get("covers"))):
        return "raised as Unknown"
    unk = " ".join(block.get("unknown", []) + block.get("dropped", [])).lower()
    if any(i.lower() in unk for i in ids):
        return "named on an Unknown or Dropped line"
    if any(t and t.lower() in unk for t in item.get("tokens", [])):
        return "named on an Unknown line"
    if item.get("empty"):
        return "raised as Unknown" if block.get("unknown") else "open slot with no Unknown line"
    return "gap without identity" if block.get("unknown") else "unmet"


def report(card: dict, sheet: dict | None = None) -> dict:
    """{qid: {"kind", "must"|"flows"|"kept": [{"text", "ids", "shown", "status"?}], "counts"}}."""
    out = {}
    for q in card.get("questions", []):
        ob = obligations(card, q["id"])
        if not ob:
            continue
        seen = shown_ids(card, q["id"])
        b = (sheet or {}).get(q["id"]) if sheet is not None else None
        r = {"kind": ob["kind"]}
        for name, key in (("must", "ids"), ("flows", "ids"), ("kept", "capture_ids")):
            rows = []
            for x in ob[name]:
                ids = _up(x.get(key))
                row = {"text": (x.get("text") or x.get("fact") or "")[:140], "ids": ids,
                       "shown": bool(set(ids) & seen) or (not ids and name == "must")}
                if sheet is not None:
                    row["status"] = _status(x, b, key)
                rows.append(row)
            r[name] = rows
        r["counts"] = {n: {"owed": len(r[n]), "not shown": sum(1 for x in r[n] if not x["shown"]),
                           **({"unmet": sum(1 for x in r[n] if x.get("status") not in ("cited", "raised as Unknown",
                                                                                         "named on an Unknown or Dropped line",
                                                                                         "named on an Unknown line"))}
                              if sheet is not None else {})} for n in ("must", "flows", "kept")}
        out[q["id"]] = r
    return out


def markdown(rep: dict) -> str:
    lines = ["# Obligations per question", ""]
    for qid, r in rep.items():
        lines.append(f"## {qid} ({r['kind']})")
        for n in ("must", "flows", "kept"):
            c = r["counts"][n]
            lines.append(f"- {n}: {c['owed']} owed, {c['not shown']} not in the model's input"
                         + (f", {c['unmet']} unmet" if "unmet" in c else ""))
            for x in r[n]:
                bad = (not x["shown"]) or x.get("status") not in (None, "cited", "raised as Unknown",
                                                                  "named on an Unknown or Dropped line", "named on an Unknown line")
                if bad:
                    lines.append(f"  - {', '.join(x['ids']) or '(no evidence)'}: {'not shown; ' if not x['shown'] else ''}"
                                 f"{x.get('status', '')} {x['text'][:100]}".rstrip())
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("report",))
    ap.add_argument("card", type=Path)
    ap.add_argument("--sheet", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    from csa_docx import answer_sheet as A
    card = json.loads(a.card.read_text(encoding="utf-8"))
    sheet = A.parse(a.sheet.read_text(encoding="utf-8")) if a.sheet else None
    rep = report(card, sheet)
    print(json.dumps(rep, indent=1) if a.json else markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
