"""Small, deterministic fact-layer checks run before prose-quality checks."""
from __future__ import annotations

import re

_HOST = re.compile(r"\b[A-Z][A-Z0-9-]{5,}\b")


def findings(sheet: dict, card: dict, allowed: set[str] | None = None) -> list[dict]:
    """Return focused findings for facts that cannot be grounded in the card.

    Cards without S608 obligations are left to the legacy validator unchanged.
    """
    if not card.get("obligations"):
        return []
    allowed = allowed or {str(r.get("id", "")).upper()
                          for p in (card.get("evidence") or {}).values()
                          for r in p.get("rows", [])}
    rows = {str(r.get("id", "")).upper(): r
            for p in (card.get("evidence") or {}).values() for r in p.get("rows", [])}
    out = []
    for qid, block in sheet.items():
        if qid.startswith("F"):
            continue
        for fact in block.get("facts", []):
            ids = {str(x).upper() for x in fact.get("ids", [])}
            if not ids:
                out.append({"level": "ERROR", "code": "FACT_NO_EVIDENCE", "question": qid,
                            "message": "this fact has no evidence ID; add a cited row or write QUESTION:"})
                continue
            unknown = sorted(ids - allowed)
            if unknown:
                out.append({"level": "ERROR", "code": "UNKNOWN_EVIDENCE", "question": qid,
                            "message": f"these evidence IDs are not on the card: {', '.join(unknown)}"})
            if re.search(r"\bin\s+OT\b", fact.get("text", ""), re.I):
                cited = " ".join((rows.get(i, {}).get("claim") or "") for i in ids)
                unsupported = [h for h in _HOST.findall(fact.get("text", ""))
                               if h.upper() not in cited.upper()]
                if unsupported:
                    out.append({"level": "ERROR", "code": "ZONE_FACT_NOT_BACKED", "question": qid,
                                "message": f"the cited evidence does not place {', '.join(unsupported)} in OT"})
    return out
