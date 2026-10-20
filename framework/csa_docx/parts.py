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
    return "Unidentified internal peers", "no name, role or service zone recorded"


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
        out.append(p)
    was = {_RENAMED.get(p["id"], p["id"]): sorted(p.get("members", [])) for p in old.get("parts", [])}
    same = {p["id"]: p["members"] for p in out} == was
    return {"reviewed": bool(old.get("reviewed")) and same, "reviewed_on": old.get("reviewed_on", "") if same else "",
            "assign": assign, "parts": out}


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


def parts_in(text: str, names_by_part: dict[str, list[str]]) -> set[str]:
    """The parts a text names, longest name first, so a name inside a longer one does not count twice
    ("RevBroadcast System Application Server" names that server, not also the part whose short name is RevBroadcast)."""
    t = _norm(text)
    out = set()
    for n, pid in sorted(((_norm(n), pid) for pid, ns in names_by_part.items() for n in ns if _norm(n).strip()),
                         key=lambda x: -len(x[0])):
        if n in t:
            out.add(pid)
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

def grid(doc: dict, fr: dict | None) -> dict:
    """{"by_part": {part id: [{"slot", "text", "ids", "requirements"}]}, "owed": {requirement ID: [part id]}}.
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
                                                    "requirements": list(f.get("requirements", []))})
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
             "the same machines, never two. A dependency's name is a label: write it as plain English (\"an unidentified "
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
        al = f" (also: {', '.join(p['aliases'][:3])})" if p.get("aliases") else ""
        lines.append(f"### {p['name']}{al}")
        lines.append(f"- {p['kind']} part, {'in OT' if p['side'] == 'ot' else 'outside OT' if p['side'] == 'outside' else 'side of OT not settled (' + p['side'] + ')'}"
                     f" ({', '.join(p['zones'])}): {', '.join(p['members'][:8])}" + (" and more" if len(p["members"]) > 8 else ""))
        if p["kind"] == "system" and "," in p["name"]:
            lines.append(f"- one part: the same machines hold the roles {p['name']}")
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
    return {"reviewed": bool(doc.get("reviewed")),
            "names": {p["id"]: names(p) for p in doc["parts"]},
            "sides": {p["id"]: p["side"] for p in doc["parts"]},
            "hosts": {m.upper(): p["id"] for p in doc["parts"] if p["kind"] == "system" for m in p["members"]},
            "owed": byq,
            "isolation": {pid: {"effect": v["effect"], **isolation_tokens(v)} for pid, v in iso.items()},
            "features": features(doc, fr),
            "lines": lines, "parts": {pid: parts[pid]["name"] for pid in parts}}


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
    ap.add_argument("action", choices=["build", "show", "approve", "check-doc"])
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
        out = Path(a.work_dir) / "draft" / "part-names.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 0
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
