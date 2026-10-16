"""Data flow figures (archetype F): the system's data stores and the flows between them, drawn from the
Discovery Information inventories (hosts/flows.csv, hosts/host_settings.csv, zones.csv and the analysis frame),
never from evidence-matrix connection rows. Every flow row is written from the side that opens the connection,
so an edge keeps who opens it (opens = "s") separately from which way the data goes (data)."""

from __future__ import annotations

import re

from csa_docx import flows as F

STATUS = {"observed": "seen", "both": "seen", "declared": "declared", "attempted": "attempted"}
# which way the data goes, by mechanism: to the opener (a backup server pulls), from the opener (a push), or both
DATA_DIRECTION = {"backup agent": "to_opener", "mail": "from_opener", "message/API": "from_opener",
                  "security agent telemetry": "from_opener", "log forwarding": "from_opener",
                  "monitoring": "from_opener", "file share": "both", "file transfer": "both",
                  "database": "both", "database replication": "both", "web/API": "both"}
_VIA = re.compile(r"\s+via\s+(.+)$", re.I)


def _ends(text: str) -> list[tuple[str, str]]:
    """[(end, via)] for one src or dst cell: declared rows list several ends and may say 'X via F5/Proxy'."""
    out = []
    for part in (p.strip() for p in (text or "").split(",")):
        if not part:
            continue
        m = _VIA.search(part)
        out.append((_VIA.sub("", part).strip(), m.group(1).strip() if m else ""))
    return out


def _data(mech: str) -> str:
    d = DATA_DIRECTION.get(mech)
    return {"to_opener": "to_s", "from_opener": "to_t", "both": "both"}.get(d, "unknown")


def edges(rows: list[dict], flt: dict | None = None, register: set[str] | None = None,
          frame: dict | None = None) -> list[dict]:
    """Directed data-flow edges, one per (opener, receiver, mechanism, status). flt: a flows.select filter.
    frame: the saved analysis frame (csa-work/topic-frames/<KEY>.json); its finding IDs become each edge's evidence."""
    if flt:
        rows = F.select(rows, flt, register)
    acc: dict[tuple, dict] = {}
    for r in rows:
        st = STATUS.get(r.get("status", ""), "seen")
        for s, via_s in _ends(r.get("src", "")):
            for t, via_t in _ends(r.get("dst", "")):
                k = (s, t, r["mechanism"], st)
                e = acc.setdefault(k, {"s": s, "t": t, "mechanism": r["mechanism"], "status": st, "opens": "s",
                                       "data": _data(r["mechanism"]), "flows": [], "ports": [], "via": "",
                                       "declared_id": "", "cross": r.get("cross_zone", ""),
                                       "zones": f"{r.get('src_zone') or 'zone not recorded'} to {r.get('dst_zone') or 'zone not recorded'}",
                                       "evidence": []})
                e["flows"].append(r["flow_id"])
                if r.get("port") and r["port"] not in e["ports"]:
                    e["ports"].append(r["port"])
                e["via"] = e["via"] or via_s or via_t
                e["declared_id"] = e["declared_id"] or r.get("declared_id", "")
    out = list(acc.values())
    for n, e in enumerate(out, 1):
        e["id"] = f"D{n}"
    if frame:
        for e in out:
            for s in frame.get("slots", []):
                for f in s.get("findings", []):
                    if f.get("mechanism") == e["mechanism"] and e["s"] in f.get("hosts", []) and e["t"] in f.get("hosts", []):
                        e["evidence"] += [i for i in f.get("ids", []) if i not in e["evidence"]]
    return out
