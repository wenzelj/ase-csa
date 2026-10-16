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


# ------------------------------------------------------------------ stores, markers, controls
_SHARE = re.compile(r"\s*([^,()]+?)\s+\(([^)]*)\)")
_WHOLE_DRIVE = re.compile(r"^[A-Z]:\\?$", re.I)
_USERS = re.compile(r"\\Users(?:\\|$)", re.I)
_ITEMS = re.compile(r",(?![^()]*\))")              # split on commas that are not inside brackets
MARK_LABEL = {"edr": "EDR", "av": "Antivirus", "tools": "Transfer tools", "usb": "USB storage not restricted"}


def stores(settings: list[dict]) -> dict[str, list[dict]]:
    """{host: [{"kind": "database" | "share", "what", "flag", "source"}]} from storage.database and storage.shares.
    flag: a share of a whole drive or of user folders (drawn with a muted orange edge)."""
    out: dict[str, list[dict]] = {}
    for r in settings:
        if r["attribute"] == "storage.database" and r["value"] != "None found":
            out.setdefault(r["host"], []).append({"kind": "database", "what": r["value"], "flag": False, "source": r["source"]})
        elif r["attribute"] == "storage.shares" and r["value"] != "Default and administrative shares only":
            for m in _SHARE.finditer(r["value"]):
                name, p = m.group(1).strip(), m.group(2).strip()
                out.setdefault(r["host"], []).append({"kind": "share", "what": f"Share {name} ({p})",
                                                      "flag": bool(_WHOLE_DRIVE.match(p) or _USERS.search(p)),
                                                      "source": r["source"]})
    return out


def markers(settings: list[dict]) -> dict[str, dict]:
    """{host: {"edr", "av", "tools", "usb"}}: products running (stopped ones left out), transfer tools, and
    "not restricted" when removable storage is not set in applied Group Policy. A key is absent when none is found."""
    out: dict[str, dict] = {}
    for r in settings:
        a, v = r["attribute"], r["value"]
        m = out.setdefault(r["host"], {})
        if a == "agent.edr" and v != "None found":
            run = [x.strip() for x in _ITEMS.split(v) if x.strip() and "stopped" not in x]
            if run:
                m["edr"] = ", ".join(run)
        elif a == "agent.antivirus" and v != "None found":
            m["av"] = v
        elif a == "transfer.tools" and v != "None found":
            m["tools"] = v
        elif a == "transfer.removable":
            m["usb"] = "not restricted" if v == "Not set in applied Group Policy" else "policy set"
    return {h: m for h, m in out.items() if m}


def common(marks: dict[str, dict]) -> dict[str, str]:
    """The markers every host shares, with the same value: drawn once, on a legend line, not on each tile."""
    if not marks:
        return {}
    keys = set.intersection(*(set(m) for m in marks.values()))
    return {k: next(iter(marks.values()))[k] for k in sorted(keys) if len({m[k] for m in marks.values()}) == 1}


def controls(edges: list[dict], kinds: dict[str, str] | None = None) -> list[dict]:
    """What is evidenced or declared on each edge that crosses (or may cross) a zone: a proxy or broker the flow map
    names ("via ..."), a boundary firewall at one end in the host register, or "not captured"."""
    kinds = kinds or {}
    out = []
    for e in edges:
        if e.get("cross") not in ("yes", "unknown"):
            continue
        if e.get("via"):
            kind = "proxy" if re.search(r"proxy", e["via"], re.I) else "broker"
            out.append({"edge": e["id"], "kind": kind, "label": e["via"], "basis": "declared in the flow map"})
        elif any(kinds.get(x) == "firewall" for x in (e["s"], e["t"])):
            out.append({"edge": e["id"], "kind": "firewall", "label": "Boundary firewall", "basis": "in the host register"})
        else:
            out.append({"edge": e["id"], "kind": "not captured", "label": "Boundary device not captured",
                        "basis": "the captures do not cover the boundary"})
    return out
