"""System parts: the pieces of the system every section writes about.

A part is a role group of the system or something the system exchanges data with (the backup platform, messaging,
a monitoring service, peers nobody has identified, internet services), with its hosts or flow ends, its zones and its
side of the OT boundary. A system part is always named by its machines' role in the host register (hosts.csv), and
the parts are worked out afresh from the register and the flows every time a card is built, so a register change
(a role, a site) shows at once. ``csa-work/parts.json`` keeps only what the register cannot say: the other names the
sources use for a part (aliases), the name of a dependency, which part a flow end belongs to ("assign"), notes, and
whether a person has reviewed the parts.

    python3 -m csa_docx.parts build --work-dir <csa-work>
    python3 -m csa_docx.parts show --work-dir <csa-work>
    python3 -m csa_docx.parts approve --work-dir <csa-work>
    python3 -m csa_docx.parts applications --work-dir <csa-work>      propose (when none) and show the applications
    python3 -m csa_docx.parts chains --work-dir <csa-work>            propose (when none) and show the function chains
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


def display_name(p: dict) -> str:
    """The name the card and the review show for the part: the "display" value a person set in parts.json,
    else the first of the short names when the name holds two roles ("A, B" gives "A"), else the name itself."""
    d = (p.get("display") or "").strip()
    if d:
        return d
    if "," in p["name"]:
        return p["name"].split(",")[0].strip()
    return p["name"]


def _confusable_key(name: str) -> str:
    s = name.lower()
    if s.startswith("ot "):
        s = s[3:]
    for tail in (" servers", " server", " host"):
        if s.endswith(tail):
            s = s[: -len(tail)]
            break
    return s


def confusable(doc: dict) -> list[tuple[str, str]]:
    """Pairs of parts whose display names a reader would read as one thing: equal after lower-casing, dropping
    a leading "OT " and a trailing " server", " servers" or " host" - a two-role name compares on its first
    role ("TETRA log server" and "OT TETRA Log Server, DAAM Node Controller")."""
    parts = doc.get("parts") or []
    keys = [(display_name(p), {_confusable_key(p2) for p2 in (display_name(p), display_name(p).split(",")[0])})
            for p in parts]
    out = []
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            a, ka = keys[i]
            b, kb = keys[j]
            if ka & kb:
                out.append((a, b))
    return out


def _public(end: str) -> bool:
    try:
        return ipaddress.ip_address(end).is_global
    except ValueError:
        return False


def _address(end: str) -> bool:
    try:
        ipaddress.ip_address(end)
        return True
    except ValueError:
        return False


def dependency_of(end: str, zone: str, hints: dict, register: set[str]) -> tuple[str, str]:
    """(part name, basis) for a flow end that is not a host of the system."""
    h = hints.get(end) or hints.get(end.upper()) or {}
    if h.get("role"):
        return re.sub(r"\s+server$", "", h["role"].strip(), flags=re.I), "what the peer runs (flow signature)"
    if not _address(end) and end.upper() not in register:
        return re.split(r"\s+/\s+", end)[0].strip(), "named in the flow map"
    if "(" in zone:                                   # a service zone: Monitoring (SCOM), SIEM (Splunk)
        return zone, "service zone"
    if zone.lower() == "internet" or _public(end):
        return "Internet services", "public address"
    return "Unidentified internal peers", "no name, role or service zone recorded"


OTHER_APPLICATION = "{} (other application)"


def owners(work_dir: Path) -> dict[str, tuple[str, str]]:
    """{HOST: (project key, application name)} for the hosts of other applications in this register: same-system
    siblings (in_scope "system: <key>") and neighbours (source "neighbour:<key>"). The application name is the
    host's system for a sibling, the neighbour_project rule's system column for a neighbour, else the project's
    label without its bracketed note ("IAMPS (template v1.3)" -> "IAMPS")."""
    from csa_docx import estate
    work = Path(work_dir)
    named = {}
    rf = work / "hosts" / "roles.csv"
    if rf.is_file():
        for r in csv.DictReader(rf.open(encoding="utf-8-sig")):
            if (r.get("kind") or "").strip().lower() == "neighbour_project" and (r.get("system") or "").strip():
                named[(r.get("match") or "").strip()] = r["system"].strip()

    def app(key: str, system: str = "") -> str:
        return system or named.get(key) or re.sub(r"\s*\([^)]*\)\s*$", "", estate.label_of(key)).strip() or key

    out = {}
    f = work / "hosts" / "hosts.csv"
    if not f.is_file():
        return out
    from csa_docx import modelstore
    for r in modelstore.read_csv(f):
        host = (r.get("host") or "").strip().upper()
        scope = (r.get("in_scope") or "").strip()
        m = re.search(r"\bneighbour:([\w.-]+)", r.get("sources") or "")
        if scope.lower().startswith("system:"):
            key = scope.split(":", 1)[1].strip()
            out[host] = (key, app(key, (r.get("system") or "").strip()))
        elif m:
            out[host] = (m[1], app(m[1]))
    return out


# framework labels that were renamed: a parts.json written under the old label keeps its review
_RENAMED = {"peers-not-identified": "unidentified-internal-peers"}


def build(work_dir: Path) -> dict:
    """Write csa-work/parts.json (see assemble)."""
    doc = assemble(work_dir)
    path(Path(work_dir)).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return doc


def assemble(work_dir: Path) -> dict:
    """The parts from the host register and the flows, with a person's aliases, dependency names, notes and
    assignments from parts.json. A system part's name is its machines' register role (a name given to it in
    parts.json is ignored). ``reviewed`` stays true only while no part gains or loses a member."""
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
        from csa_docx import modelstore
        every = {r["host"].strip().upper() for r in modelstore.read_csv(f)}
    rows = F.load(work)
    hints = F.peer_hints(rows)
    other = owners(work)
    for r in rows:
        for col in ("src", "dst"):
            for e in (end_name(x) for x in (r.get(col) or "").split(",")):
                if not e or e.upper() in mine:
                    continue
                if e.upper() in other:                 # a host of another application: one part per application
                    key, app = other[e.upper()]
                    name = OTHER_APPLICATION.format(app)
                    add(name, "dependency", e, f"host of another application (project {key})")
                    parts[slug(assign.get(e, assign.get(e.upper(), name)))].update(owner=key, application=app)
                    continue
                zone = (r.get(f"{col}_zone") or zs.of(e).get("zone", "") or "").strip()
                name, basis = dependency_of(e, zone, hints, every)
                add(name, "dependency", e, basis)
    kept = {_RENAMED.get(p["id"], p["id"]): p for p in old.get("parts", [])}
    out = []
    for p in sorted(parts.values(), key=lambda p: (p["kind"] != "system", p["name"].lower())):
        p["members"].sort()
        zones = [(zs.of(m).get("zone", "") or "") for m in p["members"]]
        p["zones"] = list(dict.fromkeys(z for z in zones if z)) or ["zone not recorded"]
        sides = {side(m) for m in p["members"]}
        p["side"] = sides.pop() if len(sides) == 1 else "mixed"
        prev = kept.get(p["id"], {})
        if p["kind"] != "system":
            p["name"] = prev.get("name") or p["name"]
        p["aliases"] = list(dict.fromkeys((prev.get("aliases") or []) + [a for a in short_names(p["name"])]))
        if prev.get("note"):
            p["note"] = prev["note"]
        if prev.get("display"):
            p["display"] = prev["display"]
        out.append(p)
    was = {_RENAMED.get(p["id"], p["id"]): sorted(p.get("members", [])) for p in old.get("parts", [])}
    same = {p["id"]: p["members"] for p in out} == was
    doc = {"reviewed": bool(old.get("reviewed")) and same, "reviewed_on": old.get("reviewed_on", "") if same else "",
           "assign": assign, "parts": out}
    doc.update(_keep_applications(old, {p["id"]: p["members"] for p in out}, was))
    return doc


def _keep_applications(old: dict, now: dict[str, list[str]], was: dict[str, list[str]]) -> dict:
    """The applications and chains a person wrote in parts.json, kept through a rebuild. One whose part has gone, or
    gained or lost a member since the last build, goes back to reviewed false; nothing else about it changes."""
    keep: dict = {}
    for key, refs in (("applications", lambda a: a.get("parts") or []),
                      ("chains", lambda a: [s[e] for s in a.get("steps") or [] for e in ("from", "to") if s.get(e)])):
        if key not in old:
            continue
        keep[key] = []
        for a in old[key]:
            a = dict(a)
            if any(r not in now or now[r] != was.get(r) for r in refs(a)):
                a["reviewed"] = False
            keep[key].append(a)
    return keep


def index(doc: dict) -> dict[str, dict]:
    """{member (upper case): part} for every part."""
    return {m.upper(): p for p in doc.get("parts", []) for m in p["members"]}


_LABEL = re.compile(r"\b(?:not identified|unidentified)\b", re.I)
PLAIN_LABEL = "unidentified internal peers"


def is_label(p: dict) -> bool:
    """A dependency whose name is a label for "we do not know who" ("Peers not identified"), not a name to print."""
    return p.get("kind") == "dependency" and bool(_LABEL.search(p.get("name", "")))


def names(p: dict) -> list[str]:
    """The names that count as naming a part: its name, its aliases and, for a dependency, its members (an
    unidentified peer can only be named by its address)."""
    return ([p["name"]] + list(p.get("aliases") or []) + (list(p["members"]) if p["kind"] == "dependency" else [])
            + ([PLAIN_LABEL, "unidentified peers", "unnamed internal peers"] if is_label(p) else []))


def _norm(s: str) -> str:
    words = re.findall(r"[a-z0-9]+(?:[./][a-z0-9]+)*", s.lower())     # a full stop ending a sentence is not part of the word
    return " " + " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words) + " "


def parts_in(text: str, names_by_part: dict[str, list[str]]) -> set[str]:
    """The parts a text names, longest name first, so a name inside a longer one does not count twice
    ("RevBroadcast System Application Server" names that server, not also the part whose short name is RevBroadcast)."""
    t = _norm(text)
    out = set()
    owners: dict[str, set[str]] = {}
    for pid, ns in names_by_part.items():
        for n in ns:
            if _norm(n).strip():
                owners.setdefault(_norm(n), set()).add(pid)
    for n in sorted(owners, key=lambda x: -len(x)):
        if n in t:
            pids = owners[n]
            if len(pids) > 1:               # one part's alias is another's own name: the part that owns the name takes it
                own = {p for p in pids if names_by_part[p] and _norm(names_by_part[p][0]) == n}
                pids = own or pids
            out |= pids
            t = t.replace(n, " # ")
    return out


def named(text: str, ns: list[str]) -> bool:
    """True when ``text`` names a part by any of ``ns`` (case, plurals and punctuation ignored)."""
    t = _norm(text)
    return any(_norm(n).strip() and _norm(n) in t for n in ns)


# What each part keeps and loses when OT is isolated: worked out from the flows, never written by the model.
_LOSS_KEYS = ("cut", "may_cut")


def isolation(work_dir: Path, doc: dict | None = None) -> dict[str, dict]:
    """{part id: {"effect": one line, "kept": [...], "cut": [...], "may_cut": [...], "unaffected": [...]}}. Each item is
    {"mechanism", "port", "other" (the part at the far end), "flows"}. A flow is cut when one end is in OT and the other
    is outside it, may be cut when an end's zone is not recorded, kept when both ends are in OT, and not affected when
    neither end is in OT (an IT server talking to the internet is not touched by isolating OT)."""
    from csa_docx import flows as F
    work = Path(work_dir)
    doc = doc or load(work)
    idx, side = index(doc), F.ot_sides(work)
    out: dict[str, dict] = {p["id"]: {"kept": {}, "cut": {}, "may_cut": {}, "unaffected": {}} for p in doc.get("parts", [])}
    for r in F.load(work):
        for s in (end_name(x) for x in r["src"].split(",") if x.strip()):
            for d in (end_name(x) for x in r["dst"].split(",") if x.strip()):
                ps, pd = idx.get(s.upper()), idx.get(d.upper())
                if not ps or not pd:
                    continue
                sides = {side(s), side(d)}
                key = ("kept" if sides == {"ot"} else "cut" if sides == {"ot", "outside"}
                       else "unaffected" if "ot" not in sides and "unknown" not in sides else "may_cut")
                for me, other in ((ps, pd), (pd, ps)):
                    item = out[me["id"]][key].setdefault((r["mechanism"], other["id"]), {
                        "mechanism": r["mechanism"], "port": r["port"], "other": other["name"], "flows": []})
                    if r["flow_id"] not in item["flows"]:
                        item["flows"].append(r["flow_id"])
    res = {}
    for p in doc.get("parts", []):
        o = {k: list(v.values()) for k, v in out[p["id"]].items()}
        lost = [f"{x['mechanism']} with {x['other']}" for x in o["cut"]]
        maybe = [f"{x['mechanism']} with {x['other']}" for x in o["may_cut"]]
        if p["side"] == "outside":
            effect = ("loses its paths into OT: " + "; ".join(lost) if lost else "is not affected by isolating OT")
        elif lost:
            effect = "loses " + "; ".join(lost)
        elif o["kept"]:
            effect = "keeps working inside OT"
        else:
            effect = "" if maybe else "has no observed or declared flows"
        if maybe:
            effect += (", and may lose" if effect else "may lose") + " (zone not recorded): " + "; ".join(maybe)
        res[p["id"]] = {"effect": effect, **o}
    return res


def isolation_tokens(iso: dict) -> dict[str, list[str]]:
    """{"loss": words that name what the part loses, "safe": words that name only what it keeps}: the mechanisms and
    far-end parts of its cut flows against those of its unaffected flows, words shared by both left out."""
    def words(items: list[dict]) -> set[str]:
        ws = set()
        for x in items:
            ws |= {w for w in re.findall(r"[a-z]{4,}", (x["mechanism"] + " " + x["other"]).lower())}
        return ws
    loss = words(iso.get("cut", []) + iso.get("may_cut", []))
    safe = words(iso.get("unaffected", []) + iso.get("kept", [])) - loss
    return {"loss": sorted(loss), "safe": sorted(safe)}


# The part grid for one section: which of the section's findings are about which part, and which parts each
# requirement must name. Built from the analysis frame, so it only exists for a section with a frame.

def finding_basis(f: dict) -> str:
    """How a frame finding is known: observed in a capture, declared only (a flow map entry nobody saw), attempted
    (a connection that never got a reply) or not found (the capture was searched and holds nothing)."""
    st = f.get("status", "")
    if st == "declared":
        return "declared only"
    if st == "attempted":
        return "attempted, no reply seen"
    if any(e.get("status") == "NOT_FOUND" for e in f.get("evidence", [])):
        return "not found in the capture"
    return "observed"


def grid(doc: dict, fr: dict | None) -> dict:
    """{"by_part": {part id: [{"slot", "text", "ids", "requirements", "basis", "direction"}]}, "owed": {requirement ID: [part id]}}.
    A finding is about every part one of its hosts or flow ends belongs to. A requirement owes a part when one of
    the findings bound to it is about that part."""
    idx = index(doc)
    by_part: dict[str, list[dict]] = {}
    owed: dict[str, list[str]] = {}
    for s in (fr or {}).get("slots", []):
        for f in s["findings"]:
            pids = list(dict.fromkeys(idx[e.upper()]["id"] for h in f.get("hosts", [])
                                      for e in (end_name(x) for x in h.split(",")) if e.upper() in idx))
            for pid in pids:
                by_part.setdefault(pid, []).append({"slot": s["id"], "text": f["text"], "ids": list(f.get("ids", [])),
                                                    "requirements": list(f.get("requirements", [])),
                                                    "basis": finding_basis(f), "direction": f.get("direction", "")})
                for r in f.get("requirements", []):
                    if pid not in owed.setdefault(r, []):
                        owed[r].append(pid)
    return {"by_part": by_part, "owed": owed}


def card_view(work_dir: Path, fr: dict | None, qs: list[dict]) -> dict | None:
    """What the card shows and the checks need, or None when the project has no parts.json yet:
    {"reviewed", "names": {id: [names]}, "sides": {id: side}, "hosts": {host: id}, "owed": {question id: [id]},
    "isolation": {id: {"effect", "loss", "safe"}}, "lines": [card lines]}."""
    if not path(Path(work_dir)).is_file():
        return None
    doc = assemble(work_dir)
    if not doc.get("parts"):
        return None
    g = grid(doc, fr)
    iso = isolation(work_dir, doc)
    byq = {q["id"]: g["owed"].get(q.get("req_id", ""), []) for q in qs if q.get("kind") == "requirement"}
    parts = {p["id"]: p for p in doc["parts"]}
    touched = [p for p in doc["parts"] if p["id"] in g["by_part"] or p["kind"] == "system"]
    lines = ["", "## System parts (built by the framework from the host register and the flows)", "",
             "Write about the system as these parts, by these names (\"also\" gives accepted short names). A system part "
             "is named by its machines' role in the host register: a role written as two roles (\"A, B\") is one part, "
             "the same machines, never two; in a sentence write one of its roles (its first short name), not the whole \"A, B\" "
             "list, which reads as two things. A dependency's name is a label: write it as plain English (\"an unidentified "
             "internal peer at 10.1.2.3\"), never as a name in a sentence. Say something about a part only where a "
             "finding listed under that part shows it: a share, a setting or a connection belongs to the part whose "
             "machines the finding names (PART_MISATTRIBUTED). In Text: lines "
             "name the part, never a host of the system (HOST_IN_TEXT): the role table and the Discovery rows carry the "
             "hosts. Start each requirement's Text: with one lead sentence that gives the verdict and the part or parts "
             "that decide it, then one sentence for each part that differs. Every part listed under a requirement "
             "question must be named in its Text: (PART_NOT_NAMED), or covered by a short clause \"and every other part\" that "
             "adds no claim of its own. In the "
             "Discovery Information table, give each part its own Aspect row where the topic touches it. The Drawbridge "
             "Impact says, part by part, what each keeps or loses when OT is isolated, from the \"When OT is isolated\" "
             "lines below: a part outside OT loses only its paths into OT (ISOLATION_WRONG_SIDE).", ""]
    if not doc.get("reviewed"):
        lines += ["The parts have not been reviewed yet (csa parts approve): use them, and say nothing that depends on "
                  "a part's name being final.", ""]
    for p in touched:
        dn = display_name(p)
        also = [x for x in [p["name"]] + list(p.get("aliases") or []) if x != dn]
        al = f" (also: {', '.join(also[:3])})" if also else ""
        lines.append(f"### {dn}{al}")
        lines.append(f"- {p['kind']} part, {'in OT' if p['side'] == 'ot' else 'outside OT' if p['side'] == 'outside' else 'side of OT not settled (' + p['side'] + ')'}"
                     f" ({', '.join(p['zones'])}): {', '.join(p['members'][:8])}" + (" and more" if len(p["members"]) > 8 else ""))
        if p["kind"] == "system" and "," in p["name"]:
            lines.append(f"- one part: the same machines hold the roles {p['name']}")
        if p["kind"] == "system" and p["side"] == "outside" and re.match(r"(?:OT|IT)\b", p["name"]):
            short = re.sub(r"^(?:OT|IT)\s+", "", p["name"].split(",")[0])
            lines.append(f"- its role name says {p['name'].split()[0]} but its zone puts it outside OT: write \"the IT-hosted "
                         f"{short}\" in every sentence, never \"{p['name'].split(',')[0]}\" (NAME_CONTRADICTS_ZONE)")
        mine = g["by_part"].get(p["id"], [])
        if not mine:
            lines.append("- Findings about it: none in this section's analysis frame")
        for f in mine[:6]:
            ids = f" ({', '.join(f['ids'])})" if f["ids"] else ""
            lines.append(f"- {f['slot']}: {f['text'][:170]}{ids}")
        if len(mine) > 6:
            lines.append(f"- {len(mine) - 6} more findings about it under Analysis frame")
        lines.append(f"- When OT is isolated: {iso[p['id']]['effect'][:300]}")
        lines.append("")
    appview = application_view(work_dir, doc, byq)
    if appview:
        lines += appview["lines"]
    return {"reviewed": bool(doc.get("reviewed")),
            "applications": appview["apps"] if appview else [], "owed_applications": appview["owed"] if appview else {},
            "links": appview["links"] if appview else [],
            "names": {p["id"]: names(p) for p in doc["parts"]},
            "sides": {p["id"]: p["side"] for p in doc["parts"]},
            "hosts": {m.upper(): p["id"] for p in doc["parts"] if p["kind"] == "system" for m in p["members"]},
            "owed": byq, "findings": g["by_part"],
            "isolation": {pid: {"effect": v["effect"], **isolation_tokens(v)} for pid, v in iso.items()},
            "features": features(doc, fr),
            "labels": [{"label": p["name"], "plain": PLAIN_LABEL} for p in doc["parts"] if is_label(p)],
            "foreign": {p["id"]: {"application": p.get("application") or p["name"], "project": p["owner"],
                                  "names": list(dict.fromkeys([p.get("application") or p["name"]] + names(p)))}
                        for p in doc["parts"] if p.get("owner")},
            "lines": lines, "parts": {pid: (PLAIN_LABEL if is_label(parts[pid]) else parts[pid]["name"]) for pid in parts}}


APPLICATION_BLOCK_CHARS = 2400      # about 600 tokens: the Applications block never grows the card by more than this


def part_links(work_dir: Path, doc: dict) -> list[list[str]]:
    """Every pair of parts (ids, sorted) that some flow in flows.csv joins, whatever its status. Used to tell a link
    between two parts that the flows show from one nothing shows."""
    from csa_docx import flows as F
    where = index(doc)
    pairs = set()
    for r in F.load(work_dir):
        a = {where[end_name(x).upper()]["id"] for x in (r.get("src") or "").split(",") if end_name(x).upper() in where}
        b = {where[end_name(x).upper()]["id"] for x in (r.get("dst") or "").split(",") if end_name(x).upper() in where}
        pairs |= {tuple(sorted((x, y))) for x in a for y in b if x != y}
    return sorted([list(p) for p in pairs])


def application_view(work_dir: Path, doc: dict, byq: dict[str, list[str]]) -> dict | None:
    """The reviewed applications for the card: {"apps": [{id, name, names, parts, shared}], "owed": {question id:
    [application ids]}, "lines": [card lines]}. An application the person has not reviewed, and a model with problems
    (model_problems), give None: nothing about applications reaches the card until it is sound."""
    apps = [a for a in doc.get("applications") or [] if a.get("reviewed")]
    if not apps or model_problems(doc):
        return None
    pname = {p["id"]: p for p in doc.get("parts", [])}
    chains = [c for c in doc.get("chains") or [] if c.get("reviewed")]
    lines = ["", "## Applications (reviewed in csa-work/parts.json)", "",
             "An application is the set of parts that does one job for its users. Name the application where a requirement "
             "is about what the job needs (\"for Reveloc\"), and the parts under it by their names. A part marked shared "
             "serves more than one application: never say it belongs to one. A dependency is only the end of a chain, and "
             "another application is never described beyond its name. Say a step between parts only where it is listed "
             "below.", ""]
    view = []
    for a in apps:
        shared = {pid for pid, v in (a.get("role_in") or {}).items() if v == "shared"}
        mine = [pid for pid in a.get("parts") or [] if pid in pname]
        alias = [a["name"]] + list(a.get("aliases") or [])
        sides = {pname[pid]["side"] for pid in mine if pid not in shared}
        view.append({"id": a["id"], "name": a["name"], "names": alias, "parts": mine, "shared": sorted(shared),
                     "side": sides.pop() if len(sides) == 1 else "mixed"})
        lines.append(f"### {a['name']}" + (f" (also: {', '.join(a['aliases'][:3])})" if a.get("aliases") else ""))
        src = a.get("purpose_source")
        lines.append(f"- purpose{f' (background from {src}, not evidence of this installation)' if src and a.get('purpose') else ''}: "
                     f"{(a.get('purpose') or 'not recorded')[:160]}")
        lines.append("- parts: " + ", ".join(pname[pid]["name"] + (" (shared)" if pid in shared else "") for pid in mine))
        for c in (c for c in chains if c.get("application") == a["id"]):
            for st in chain_view(work_dir, doc, c)[:8]:
                lines.append(f"- {c.get('function') or 'chain'}: {pname[st['from']]['name']} -> {pname[st['to']]['name']} "
                             f"({', '.join(st.get('flows') or []) or 'no flow'}, {st['status']})")
        lines.append("")
    owed = {qid: [v["id"] for v in view if (set(v["parts"]) - set(v["shared"])) & set(pids)] for qid, pids in byq.items()}
    owed = {qid: ids for qid, ids in owed.items() if ids}
    if owed:
        lines += ["Applications behind each requirement: " + "; ".join(f"{qid}: {', '.join(ids)}" for qid, ids in owed.items()), ""]
    text = "\n".join(lines)
    if len(text) > APPLICATION_BLOCK_CHARS:
        keep, size = [], 0
        for ln in lines:
            size += len(ln) + 1
            if size > APPLICATION_BLOCK_CHARS - 40:
                keep.append("- more steps are listed in csa-work/parts.json")
                break
            keep.append(ln)
        lines = keep
    return {"apps": view, "owed": owed, "lines": lines, "links": part_links(work_dir, doc)}


# What a sentence says about a part must come from a finding about that part's machines: a share, a setting or a
# kind of connection named in a sentence, and the system parts whose machines the frame has a finding of that kind on.
FEATURES = {
    "shares": (r"\bshares\b|\bshare\b(?!\s+transfer)", ("Shares on",), ()),
    "removable storage": (r"\bremovable (?:storage|media)\b", ("Removable storage policy on",), ()),
    "transfer tools": (r"\btransfer tools?\b|\bWinSCP\b|\bFileZilla\b|\bTftpd64\b|\bPuTTY\b",
                       ("File transfer tools installed on",), ()),
    "proxy": (r"\bWinHTTP\b|\bproxy\b", ("Proxy setting on",), ()),
    "SMB": (r"\bSMB\b|\bfile[- ]share connections?\b", (), ("file share",)),
    "backup agent": (r"\bbackup agent\b", (), ("backup agent",)),
}


def features(doc: dict, fr: dict | None) -> dict[str, list[str]]:
    """{feature: [system part id]}: for each kind of fact in FEATURES, the system parts with at least one machine the
    analysis frame has a finding of that kind about (any value: a part whose machines were not captured has none)."""
    idx = index(doc)
    out: dict[str, list[str]] = {}
    for s in (fr or {}).get("slots", []):
        for f in s["findings"]:
            text, mech = f.get("text", ""), (f.get("mechanism") or "").lower()
            for name, (_, prefixes, mechs) in FEATURES.items():
                if any(text.startswith(x) for x in prefixes) or (mech and mech in mechs):
                    for h in f.get("hosts", []):
                        for e in (end_name(x) for x in h.split(",")):
                            p = idx.get(e.upper())
                            if p and p["kind"] == "system" and p["id"] not in out.setdefault(name, []):
                                out[name].append(p["id"])
    return out


def requirement_findings(view: dict | None, req_id: str) -> list[dict]:
    """The findings one requirement owes, one row per finding and part: [{"key" (unique, the verdict handle), "part", "part_id", "side", "slot", "text",
    "ids", "basis", "direction"}], in part order. A finding is owed when the frame bound it to ``req_id``."""
    out, used, by = [], set(), {}
    for pid, fs in ((view or {}).get("findings") or {}).items():
        for f in fs:
            if req_id not in f["requirements"]:
                continue
            row = by.get((f["slot"], f["text"]))
            if row:                                     # the same finding about another part: one row, both parts
                if view["parts"].get(pid, pid) not in row["part"].split(", "):
                    row["part"] += ", " + view["parts"].get(pid, pid)
                    row["part_ids"].append(pid)
                    if view["sides"].get(pid, "") != row["side"]:
                        row["side"] = "mixed"
                continue
            key = f"{f['slot']}-{f['ids'][0] if f['ids'] else 'n'}"
            n = 1
            while key in used:
                n += 1
                key = f"{f['slot']}-{f['ids'][0] if f['ids'] else 'n'}-{n}"
            used.add(key)
            row = {"key": key, "part": view["parts"].get(pid, pid), "part_id": pid, "part_ids": [pid], "side": view["sides"].get(pid, ""),
                   **{k: f[k] for k in ("slot", "text", "ids", "basis", "direction")}}
            by[(f["slot"], f["text"])] = row
            out.append(row)
    return out


def owed_lines(view: dict | None, qid: str) -> list[str]:
    """The line under a requirement question naming the parts its Text: must name."""
    pids = (view or {}).get("owed", {}).get(qid) or []
    if not pids:
        return []
    return ["  Parts to name in the Text: (PART_NOT_NAMED): " + ", ".join(view["parts"][p] for p in pids)]


# One name per part across the whole document: role-like names that end like a part's name but are none of its
# names ("Viewer Jump Hosts" where the part is "Operations Jump Host"). Reported, never changed.
_ROLE_PHRASE = re.compile(r"\b(?:[A-Z][\w/&-]*\s+){1,5}(?:Jump\s+Hosts?|Servers?|Hosts?|Groups?|Nodes?|Controllers?|"
                          r"Clients?|Workstations?|Managers?)\b")


_LEAD = {"the", "a", "an", "one", "two", "three", "four", "both", "each", "all", "ot", "it"}


def document_names(docx: Path, doc: dict) -> list[dict]:
    """[{"phrase", "like": part name, "sections": [heading], "count"}] for every role-like name in the document whose
    last two words are those of exactly one part's name or short name, but which is not one of that part's names.
    Leading articles, numbers and OT/IT are dropped first; a bare two-word ending ("Jump Host") is not reported."""
    import zipfile
    from csa_docx.figures import place as PL
    xb = zipfile.ZipFile(docx).read("word/document.xml")
    owners: dict[str, set[str]] = {}
    known = []
    for p in doc.get("parts", []):
        for n in [p["name"]] + list(p.get("aliases") or []):
            known.append(_norm(n))
            w = _norm(n).split()
            if len(w) >= 2:
                owners.setdefault(" ".join(w[-2:]), set()).add(p["name"])
    tails = {k: next(iter(v)) for k, v in owners.items() if len(v) == 1}     # an ending two parts share says nothing
    hits: dict[tuple, list[str]] = {}
    section = ""
    for s, e, t in PL._body_children(xb):
        chunk = xb[s:e]
        if t == b"w:p" and PL._heading_level(PL._style(chunk)):
            section = PL._text(chunk).strip()
            continue
        for para in re.findall(rb"<w:p[ >].*?</w:p>", chunk, re.S):
            for m in _ROLE_PHRASE.finditer(PL._text(para)):
                words = m.group(0).split()
                while len(words) > 2 and words[0].lower() in _LEAD:
                    words.pop(0)
                ph = _norm(" ".join(words))
                if len(ph.split()) <= 2 or any(k in ph for k in known):
                    continue
                like = tails.get(" ".join(ph.split()[-2:]))
                if like:
                    hits.setdefault((" ".join(words), like), []).append(section)
    return [{"phrase": k[0], "like": k[1], "sections": sorted(set(v)), "count": len(v)}
            for k, v in sorted(hits.items(), key=lambda kv: -len(kv[1]))]


_APP_KIND = r"(?:application|system|solution|service|platform|software)"


def document_application_names(docx: Path, doc: dict) -> list[dict]:
    """[{"phrase", "like": application name, "sections", "count"}] for every phrase in the document that starts with an
    application's product word and ends in application, system, solution, service, platform or software (RevBroadcast
    solution), but is not one of that application's names or aliases, nor a part's name (or the start of one). Applications nobody has
    reviewed are skipped, as are applications whose name has no product-like first word (a word under four letters)."""
    import zipfile
    from csa_docx.figures import place as PL
    apps = [a for a in doc.get("applications") or [] if a.get("reviewed")]
    if not apps:
        return []
    known = [_norm(n) for a in apps for n in [a["name"]] + list(a.get("aliases") or [])]
    known += [_norm(n) for p in doc.get("parts", []) for n in [p["name"]] + list(p.get("aliases") or [])]
    xb = zipfile.ZipFile(docx).read("word/document.xml")
    hits: dict[tuple, list[str]] = {}
    section = ""
    for s, e, t in PL._body_children(xb):
        chunk = xb[s:e]
        if t == b"w:p" and PL._heading_level(PL._style(chunk)):
            section = PL._text(chunk).strip()
            continue
        for para in re.findall(rb"<w:p[ >].*?</w:p>", chunk, re.S):
            text = PL._text(para)
            for a in apps:
                first = a["name"].split()[0]
                if len(first) < 4:
                    continue
                for m in re.finditer(rf"\b{re.escape(first)}(?:\s+[A-Za-z/]+){{0,2}}?\s+{_APP_KIND}\b", text):
                    ph = _norm(m.group(0))
                    if not any(ph.strip() and ph.strip() in k for k in known):          # a known name, or part of a longer one
                        hits.setdefault((m.group(0), a["name"]), []).append(section)
    return [{"phrase": k[0], "like": k[1], "sections": sorted(set(v)), "count": len(v)}
            for k, v in sorted(hits.items(), key=lambda kv: -len(kv[1]))]


def _declared_steps(work_dir: Path, doc: dict) -> list[dict]:
    """One {"from": part id, "to": part id, "flow": declared id, "rows": [flow ids]} per declared flow and pair of parts
    its ends fall in (a flow with several hosts at an end gives one pair per part, once). Ends in no part are skipped."""
    from csa_docx import flows as F
    where = index(doc)
    out: dict[tuple, dict] = {}
    for r in F.load(work_dir):
        did = (r.get("declared_id") or "").strip()
        if not did:
            continue
        ends = {col: {where[end_name(x).upper()]["id"] for x in (r.get(col) or "").split(",") if end_name(x).upper() in where}
                for col in ("src", "dst")}
        for a in sorted(ends["src"]):
            for b in sorted(ends["dst"] - {a}):
                step = out.setdefault((a, b, did), {"from": a, "to": b, "flow": did, "rows": []})
                step["rows"].append(r["flow_id"])
    return list(out.values())


def propose_applications(work_dir: Path, doc: dict) -> list[dict]:
    """Applications proposed from the register's process and service rules (roles.csv) and the declared flows.
    A system part with a process or service rule is an application's core, named as its register role is, without the
    machine-kind words ("Reveloc application / TGOIP server" -> "Reveloc application / TGOIP"); a core that is only ever the destination of declared flows is a data or
    log service, not an application. The system parts the declared flows join to a core are its parts, and one joined
    to more than one core is marked shared in each. Dependency parts are never inside an application: they are chain
    ends. Every proposal is reviewed false with an empty purpose, for a person to confirm; nothing here is a model's."""
    work = Path(work_dir)
    rf = work / "hosts" / "roles.csv"
    by_name = {p["name"]: p for p in doc.get("parts", []) if p["kind"] == "system"}
    pname = {p["id"]: p for p in doc.get("parts", [])}
    kind_of = {p["id"]: p["kind"] for p in doc.get("parts", [])}
    cores: dict[str, tuple[str, str]] = {}
    if rf.is_file():
        for r in csv.DictReader(rf.open(encoding="utf-8-sig")):
            k = (r.get("kind") or "").strip().lower()
            part = by_name.get(role_name((r.get("role") or "").strip()))
            if k in ("process", "service") and part:
                label = re.sub(r"\.exe$", "", (r.get("match") or "").strip(), flags=re.I)
                if part["id"] not in cores or (k == "process" and cores[part["id"]][1] == "service"):
                    cores[part["id"]] = (label, k)
    steps = _declared_steps(work, doc)
    src = {s["from"] for s in steps}
    dst = {s["to"] for s in steps}
    cores = {pid: v for pid, v in cores.items() if pid in src or pid not in dst}
    reach: dict[str, set[str]] = {pid: set() for pid in cores}
    for s in steps:
        for core in cores:
            for a, b in ((s["from"], s["to"]), (s["to"], s["from"])):
                if a == core and b not in cores and kind_of.get(b) == "system":
                    reach[core].add(b)
    users: dict[str, int] = {}
    for parts_ in reach.values():
        for pid in parts_:
            users[pid] = users.get(pid, 0) + 1
    out = []
    for core, (label, how) in cores.items():
        parts_ = [core] + sorted(reach[core])
        name = (short_names(pname[core]["name"]) or [pname[core]["name"]])[0]
        app = {"id": slug(name), "name": name, "purpose": "", "parts": parts_,
               "aliases": [], "basis": f"{how} rule {label} in roles.csv, declared flows "
               + (", ".join(sorted({s["flow"] for s in steps if core in (s["from"], s["to"])})) or "none"),
               "reviewed": False}
        shared = {pid: "shared" for pid in reach[core] if users[pid] > 1}
        if shared:
            app["role_in"] = shared
        out.append(app)
    return sorted(out, key=lambda a: a["name"].lower())


def propose_chains(work_dir: Path, doc: dict) -> list[dict]:
    """One chain per application from the declared flows: the steps between its parts, ordered from the source end to
    the data end (by distance from the parts nothing in the chain feeds, then by flow id). A step between two parts
    the application only shares with others belongs to no single application and is left out. function is empty for a
    person to write; reviewed false."""
    work = Path(work_dir)
    steps = _declared_steps(work, doc)
    out = []
    for app in doc.get("applications") or []:
        mine = set(app.get("parts") or [])
        shared = {pid for pid, v in (app.get("role_in") or {}).items() if v == "shared"}
        kinds = {p["id"]: p["kind"] for p in doc.get("parts", [])}

        def inside(pid: str, other: str) -> bool:
            """In the application, or a dependency (a chain end) beside one of its parts that it does not share."""
            return pid in mine or (kinds.get(pid) == "dependency" and other in mine and other not in shared)

        own = [s for s in steps if inside(s["from"], s["to"]) and inside(s["to"], s["from"])
               and not (s["from"] in shared and s["to"] in shared)
               and not (kinds.get(s["from"]) == "dependency" and kinds.get(s["to"]) == "dependency")]
        merged: dict[tuple, dict] = {}
        for s in own:
            m = merged.setdefault((s["from"], s["to"]), {"from": s["from"], "to": s["to"], "flows": []})
            if s["flow"] not in m["flows"]:
                m["flows"].append(s["flow"])
        if not merged:
            continue
        every = {x for k in merged for x in k}
        depth = {pid: 0 for pid in every if not any(k[1] == pid for k in merged)}
        for _ in range(len(every)):
            for (a, b) in merged:
                if a in depth and depth.get(b, -1) < depth[a] + 1 and depth[a] + 1 < len(every):
                    depth[b] = depth[a] + 1
        ordered = sorted(merged.values(), key=lambda m: (depth.get(m["from"], 0), depth.get(m["to"], 0), m["flows"][0]))
        out.append({"id": f"{app['id']}-declared", "application": app["id"], "function": "", "steps": ordered,
                    "reviewed": False})
    return out


def unassigned_steps(work_dir: Path, doc: dict) -> list[dict]:
    """Declared steps that join a dependency (a neighbour application, say) to a part that several applications share:
    which application they belong to is for a person to say, so no proposed chain takes them (until a person puts one in a chain)."""
    kinds = {p["id"]: p["kind"] for p in doc.get("parts", [])}
    shared = {pid for a in doc.get("applications") or [] for pid, v in (a.get("role_in") or {}).items() if v == "shared"}
    placed = {(st["from"], st["to"]) for c in doc.get("chains") or [] for st in c.get("steps") or []}
    return [s for s in _declared_steps(work_dir, doc) if (s["from"], s["to"]) not in placed
            and ((kinds.get(s["from"]) == "dependency" and s["to"] in shared)
                 or (kinds.get(s["to"]) == "dependency" and s["from"] in shared))]


def model_problems(doc: dict) -> list[str]:
    """What is wrong with the applications and chains in parts.json: a dependency part (a neighbour application
    included) inside an application, or a neighbour in the middle of a chain instead of at an end of it."""
    kinds = {p["id"]: p for p in doc.get("parts", [])}
    out = []
    for a in doc.get("applications") or []:
        out += [f"application {a['id']} lists {pid}, a dependency: a dependency is only ever the end of a chain"
                for pid in a.get("parts") or [] if kinds.get(pid, {}).get("kind") == "dependency"]
    for c in doc.get("chains") or []:
        st = c.get("steps") or []
        for pid in {x for s in st for x in (s["from"], s["to"])}:
            p = kinds.get(pid, {})
            if not p.get("owner"):
                continue
            fed = any(s["to"] == pid for s in st)
            feeds = any(s["from"] == pid for s in st)
            if fed and feeds:
                out.append(f"chain {c['id']} runs through {p['name']}, another application: it can only be a chain's first or last end")
    return out


def chain_view(work_dir: Path, doc: dict, chain: dict) -> list[dict]:
    """Each step of a chain with what the flows say about it: ``status`` is "observed" (a captured connection joins the
    two parts), "attempted only" (connections were tried and never completed), "declared only" (only the flow map
    says so) or "unevidenced" (the step lists no flow), and ``support`` the flow ids behind it. A step's own flows are
    declared ids or flow ids from flows.csv."""
    from csa_docx import flows as F
    where = index(doc)
    rows = F.load(work_dir)

    def ends(r: dict, col: str) -> set[str]:
        return {where[end_name(x).upper()]["id"] for x in (r.get(col) or "").split(",") if end_name(x).upper() in where}

    out = []
    for st in chain.get("steps") or []:
        listed = set(st.get("flows") or [])
        between = [r for r in rows if st["from"] in ends(r, "src") and st["to"] in ends(r, "dst")]
        seen = [r["flow_id"] for r in between if r.get("status") in ("observed", "both")]
        tried = [r["flow_id"] for r in between if r.get("status") == "attempted"]
        named = [r["flow_id"] for r in rows if listed & {r.get("declared_id"), r.get("flow_id")}]
        status = ("observed" if seen else "attempted only" if tried else "declared only" if named else "unevidenced")
        out.append(dict(st, status=status, support=seen or tried or named))
    return out


def show_chains(work_dir: Path, doc: dict) -> str:
    names = {p["id"]: p["name"] for p in doc.get("parts", [])}
    out = ["# Function chains", ""]
    for c in doc.get("chains") or []:
        out.append(f"- **{c['id']}** ({c.get('application')}, {'reviewed' if c.get('reviewed') else 'not reviewed'}): "
                   f"{c.get('function') or 'no function yet'}")
        out += [f"  - {names.get(s['from'], s['from'])} -> {names.get(s['to'], s['to'])} "
                f"[{', '.join(s.get('flows') or []) or 'no flow'}; {s['status']}]" for s in chain_view(work_dir, doc, c)]
    loose = unassigned_steps(work_dir, doc)
    if loose:
        out += ["", "Steps that join a dependency to a shared part (no chain takes them; say which application):"]
        out += [f"- {names.get(s['from'], s['from'])} -> {names.get(s['to'], s['to'])} [{s['flow']}]" for s in loose]
    out += ["", *[f"PROBLEM: {x}" for x in model_problems(doc)]]
    return "\n".join(out + ([] if doc.get("chains") else ["- none"]))


def show_applications(doc: dict) -> str:
    apps = doc.get("applications") or []
    names = {p["id"]: p["name"] for p in doc.get("parts", [])}
    out = ["# Applications", ""]
    for a in apps:
        out.append(f"- **{a['name']}** ({'reviewed' if a.get('reviewed') else 'not reviewed'}): {a.get('purpose') or 'no purpose yet'}")
        out += [f"  - {names.get(pid, pid)}{' (shared)' if (a.get('role_in') or {}).get(pid) == 'shared' else ''}"
                for pid in a.get("parts", [])]
    return "\n".join(out + ([] if apps else ["- none"]) + ["", "Edit csa-work/parts.json to correct the name, write the purpose "
            "(one plain sentence) and the parts, then approve."])


def _proposed(work_dir: Path) -> list[dict]:
    """The identity rows a person must still confirm (endpoints.build proposed, nothing reviewed):
    [{end, label, evidence}]."""
    from csa_docx import endpoints as E
    try:
        res = E.build(work_dir)
    except Exception:
        return []
    rows = E.load(work_dir)
    out = []
    for end in res.get("proposed") or []:
        r = rows.get(end.upper(), {})
        out.append({"end": end, "label": E.label(r), "evidence": (r.get("evidence") or "").strip()})
    return out


def show(doc: dict, proposed: list[dict] | None = None) -> str:
    out = [f"# System parts ({'reviewed ' + doc.get('reviewed_on', '') if doc.get('reviewed') else 'not reviewed yet'})", ""]
    for p in doc.get("parts", []):
        dn = display_name(p)
        al = f" (also: {', '.join(p['aliases'])})" if p.get("aliases") else ""
        out.append(f"- **{dn}**{al}: {p['kind']}, {p['side']}, {', '.join(p['zones'])}; {', '.join(p['members'])}"
                   f" [{p['basis']}]")
    if proposed:
        out += ["", "Identities to confirm (hosts/endpoints.csv):"]
        out += [f'- {r["end"]}: {r["label"]} [{r["evidence"]}]  (set reviewed=yes in hosts/endpoints.csv to accept, or correct the name)'
                for r in proposed]
    pairs = confusable(doc)
    if pairs:
        out += ["", "Names a reader could confuse:"]
        out += [f'- "{a}" and "{b}": set "display" on one of them in parts.json' for a, b in pairs]
    out += ["", "Edit csa-work/parts.json to rename a part (name), add the names the sources use for it (aliases), or move a "
            "flow end to another part (\"assign\": {\"<end>\": \"<part name>\"}), then build again and approve."]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["build", "show", "approve", "check-doc", "applications", "chains"])
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--docx", type=Path, help="check-doc: the working DOCX")
    a = ap.parse_args(argv)
    if a.action == "check-doc":
        found = document_names(a.docx, load(a.work_dir))
        lines = ["# Names in the document that are not a part's name", "",
                 "Each ends like a part's name but is none of its names. Use the part's name in the text, or, if the "
                 "sources rightly call the part this, add it to that part's aliases in csa-work/parts.json.", ""]
        lines += [f"- \"{x['phrase']}\" (like {x['like']}): {x['count']} time(s), in {'; '.join(x['sections'][:6])}"
                  for x in found] or ["- none"]
        apps = document_application_names(a.docx, load(a.work_dir))
        if apps:
            lines += ["", "# Names in the document that are not an application's name", "",
                      "Each starts with an application's name but is none of its names. Use the application's name, or add "
                      "it to that application's aliases in csa-work/parts.json.", ""]
            lines += [f"- \"{x['phrase']}\" (like {x['like']}): {x['count']} time(s), in {'; '.join(x['sections'][:6])}"
                      for x in apps]
        out = Path(a.work_dir) / "draft" / "part-names.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 0
    if a.action == "applications":
        doc = load(a.work_dir)
        if not doc.get("parts"):
            print("no parts yet: build them first")
            return 1
        if not doc.get("applications"):
            doc["applications"] = propose_applications(a.work_dir, doc)
            path(a.work_dir).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        print(show_applications(doc))
        return 0
    if a.action == "chains":
        doc = load(a.work_dir)
        if not doc.get("applications"):
            print("no applications yet: run `applications` first")
            return 1
        if not doc.get("chains"):
            doc["chains"] = propose_chains(a.work_dir, doc)
            path(a.work_dir).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        print(show_chains(a.work_dir, doc))
        return 0
    if a.action == "build":
        doc = build(a.work_dir)
        print(show(doc, _proposed(a.work_dir)))
    elif a.action == "show":
        print(show(load(a.work_dir), _proposed(a.work_dir)))
    else:
        doc = load(a.work_dir)
        if not doc.get("parts"):
            print("no parts yet: build them first")
            return 1
        doc["reviewed"], doc["reviewed_on"] = True, date.today().isoformat()
        for key in ("applications", "chains"):
            for item in doc.get(key) or []:
                item["reviewed"] = True
        path(a.work_dir).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"parts approved ({len(doc['parts'])} parts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
