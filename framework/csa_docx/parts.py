"""System parts: the pieces of the system every section writes about.

A part is a role group of the system (from the host register) or something the system exchanges data with (the
backup platform, messaging, a monitoring service, peers nobody has identified, internet services), with its hosts or
flow ends, its zones and its side of the OT boundary. ``csa-work/parts.json`` holds them. A person reviews it once:
renames a part, adds the short names the sources use for it (aliases), and moves a flow end to another part with
"assign". A rebuild keeps those edits. Cards, checks and the document check then all use the same parts and names.

    python3 -m csa_docx.parts build --work-dir <csa-work>
    python3 -m csa_docx.parts show --work-dir <csa-work>
    python3 -m csa_docx.parts approve --work-dir <csa-work>
"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import re
import sys
from datetime import date
from pathlib import Path

_IP = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
# words at the end of a role name that say what kind of machine it is, not which part: dropped for the short name
_TAIL = {"always", "on", "availability", "group", "groups", "server", "servers", "cluster"}


def path(work_dir: Path) -> Path:
    return Path(work_dir) / "parts.json"


def load(work_dir: Path) -> dict:
    f = path(work_dir)
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {"reviewed": False, "parts": [], "assign": {}}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "part"


def role_name(role: str) -> str:
    """A register role as one line: 'OT Log Server\\nNode Controller' -> 'OT Log Server, Node Controller'."""
    return ", ".join(x.strip() for x in re.split(r"\s*\n\s*", role or "") if x.strip())


def end_name(end: str) -> str:
    """A flow end as the part lookup sees it: 'IT SOE Workstation via F5/Proxy' -> 'IT SOE Workstation'."""
    return re.sub(r"\s+via\s+.+$", "", (end or "").strip(), flags=re.I)


def short_names(name: str) -> list[str]:
    """Accepted short names for a part name: without a leading OT/IT, without the machine-kind words at the end
    ('AppServer Always On Availability Group' -> 'AppServer'), each comma-separated role on its own. A short name of
    one word is kept only when it is a product-like word (AppServer), never a plain word (Radio)."""
    from csa_docx.topic_tables import list_items
    out = []
    for piece in [name] + list_items(name):
        words = piece.split()
        for ws in (words, words[1:] if words[:1] in (["OT"], ["IT"]) else None):
            if not ws:
                continue
            cut = list(ws)
            while len(cut) > 1 and cut[-1].lower() in _TAIL:
                cut.pop()
            for c in (ws, cut):
                s = " ".join(c)
                if s and s != name and s not in out and (len(c) > 1 or re.search(r"[a-z][A-Z]", s)):
                    out.append(s)
    return out


def _public(end: str) -> bool:
    try:
        return ipaddress.ip_address(end).is_global
    except ValueError:
        return False


def dependency_of(end: str, zone: str, hints: dict, register: set[str]) -> tuple[str, str]:
    """(part name, basis) for a flow end that is not a host of the system."""
    h = hints.get(end) or hints.get(end.upper()) or {}
    if h.get("role"):
        return re.sub(r"\s+server$", "", h["role"].strip(), flags=re.I), "what the peer runs (flow signature)"
    if not _IP.match(end) and end.upper() not in register:
        return re.split(r"\s+/\s+", end)[0].strip(), "named in the flow map"
    if "(" in zone:                                   # a service zone: Monitoring (SCOM), SIEM (Splunk)
        return zone, "service zone"
    if zone.lower() == "internet" or _public(end):
        return "Internet services", "public address"
    return "Peers not identified", "no name, role or service zone recorded"


def build(work_dir: Path) -> dict:
    """Write csa-work/parts.json from the host register and the flows, keeping a person's names, aliases, notes and
    assignments from the previous file. ``reviewed`` stays true only while no part gains or loses a member."""
    from csa_docx import flows as F, zones as Z
    from csa_docx.topic_tables import register
    work = Path(work_dir)
    zs, side = Z.for_project(work), F.ot_sides(work)
    old = load(work)
    assign = dict(old.get("assign") or {})
    parts: dict[str, dict] = {}

    def add(name: str, kind: str, member: str, basis: str) -> None:
        name = assign.get(member, assign.get(member.upper(), name))
        p = parts.setdefault(slug(name), {"id": slug(name), "name": name, "kind": kind, "members": [], "basis": basis})
        if member not in p["members"]:
            p["members"].append(member)

    reg_rows = register(work)
    for h in reg_rows:
        add(role_name(h["role"]) or "Role not recorded", "system", h["host"], "host register")
    mine = {h["host"].upper() for h in reg_rows}
    every = set()
    f = work / "hosts" / "hosts.csv"
    if f.is_file():
        every = {r["host"].strip().upper() for r in csv.DictReader(f.open(encoding="utf-8"))}
    rows = F.load(work)
    hints = F.peer_hints(rows)
    for r in rows:
        for col in ("src", "dst"):
            for e in (end_name(x) for x in (r.get(col) or "").split(",")):
                if not e or e.upper() in mine:
                    continue
                zone = (r.get(f"{col}_zone") or zs.of(e).get("zone", "") or "").strip()
                name, basis = dependency_of(e, zone, hints, every)
                add(name, "dependency", e, basis)
    kept = {p["id"]: p for p in old.get("parts", [])}
    out = []
    for p in sorted(parts.values(), key=lambda p: (p["kind"] != "system", p["name"].lower())):
        p["members"].sort()
        zones = [(zs.of(m).get("zone", "") or "") for m in p["members"]]
        p["zones"] = list(dict.fromkeys(z for z in zones if z)) or ["zone not recorded"]
        sides = {side(m) for m in p["members"]}
        p["side"] = sides.pop() if len(sides) == 1 else "mixed"
        prev = kept.get(p["id"], {})
        p["name"] = prev.get("name") or p["name"]
        p["aliases"] = list(dict.fromkeys((prev.get("aliases") or []) + [a for a in short_names(p["name"])]))
        if prev.get("note"):
            p["note"] = prev["note"]
        out.append(p)
    same = {p["id"]: p["members"] for p in out} == {p["id"]: sorted(p.get("members", [])) for p in old.get("parts", [])}
    doc = {"reviewed": bool(old.get("reviewed")) and same, "reviewed_on": old.get("reviewed_on", "") if same else "",
           "assign": assign, "parts": out}
    path(work).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return doc


def index(doc: dict) -> dict[str, dict]:
    """{member (upper case): part} for every part."""
    return {m.upper(): p for p in doc.get("parts", []) for m in p["members"]}


def names(p: dict) -> list[str]:
    """The names that count as naming a part: its name, its aliases and, for a dependency, its members (an
    unidentified peer can only be named by its address)."""
    return [p["name"]] + list(p.get("aliases") or []) + (list(p["members"]) if p["kind"] == "dependency" else [])


def _norm(s: str) -> str:
    words = re.findall(r"[a-z0-9./]+", s.lower())
    return " " + " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words) + " "


def named(text: str, ns: list[str]) -> bool:
    """True when ``text`` names a part by any of ``ns`` (case, plurals and punctuation ignored)."""
    t = _norm(text)
    return any(_norm(n).strip() and _norm(n) in t for n in ns)


def show(doc: dict) -> str:
    out = [f"# System parts ({'reviewed ' + doc.get('reviewed_on', '') if doc.get('reviewed') else 'not reviewed yet'})", ""]
    for p in doc.get("parts", []):
        al = f" (also: {', '.join(p['aliases'])})" if p.get("aliases") else ""
        out.append(f"- **{p['name']}**{al}: {p['kind']}, {p['side']}, {', '.join(p['zones'])}; {', '.join(p['members'])}"
                   f" [{p['basis']}]")
    out += ["", "Edit csa-work/parts.json to rename a part (name), add the names the sources use for it (aliases), or move a "
            "flow end to another part (\"assign\": {\"<end>\": \"<part name>\"}), then build again and approve."]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["build", "show", "approve"])
    ap.add_argument("--work-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.action == "build":
        doc = build(a.work_dir)
        print(show(doc))
    elif a.action == "show":
        print(show(load(a.work_dir)))
    else:
        doc = load(a.work_dir)
        if not doc.get("parts"):
            print("no parts yet: build them first")
            return 1
        doc["reviewed"], doc["reviewed_on"] = True, date.today().isoformat()
        path(a.work_dir).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"parts approved ({len(doc['parts'])} parts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
