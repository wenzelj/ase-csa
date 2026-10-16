"""The figure brief: what one section's figure must show, tied to the section's own words and to evidence.

    build(row, node, ev, layout, rel_rows=None, model=None, old=None) -> brief
    wording_check(brief, purpose, caption) -> [problems]       (an agent's wording, checked before it is used)
    load(work_dir, key) / save(work_dir, key, brief)

A brief has:
  purpose  one sentence on what the figure shows (framework draft; an agent or you may reword it)
  caption  the finding the figure shows, for the Caption line
  source   the evidence the figure is drawn from, for the FigureSource line
  items    what the figure must show: each tied to the requirement IDs, the sentence of the section that says it
           (when there is one), its evidence, and its status: shown | absent (the evidence shows there is none:
           that is the finding) | gap (not captured: drawn as a gap and sent to Discovery Required)
  gaps     what the figure needs but the evidence does not hold

Nothing is invented: every item comes from evidence rows; wording from an agent may not name a host, address or
number that the items do not hold. Edits you make on the Figures page (wording, include or leave out an item)
are kept when the brief is rebuilt, as long as they still pass the checks.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

SERVICE_WORD = {"time": "time", "dns": "name resolution"}
SIDE_WORD = {"it": "enterprise (IT)", "ot": "OT-resident", "internet": "Internet", "unknown": "location not captured"}
HOSTLIKE = re.compile(r"\b[A-Z][A-Z0-9-]{5,30}\d\b")
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
FQDN = re.compile(r"\b[a-z][a-z0-9-]*(?:\.[a-z0-9-]+){1,5}\.(?:com|net|org|au|local|int)\b", re.I)
NUMBER = re.compile(r"\b\d+\b")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "twenty": 20}


# ------------------------------------------------------------------ the section's own words
def section_text(node: dict) -> list[str]:
    """Every sentence the section says: requirement current state, observation rows, prose."""
    chunks = []
    for p in node.get("parts", []):
        for r in p.get("requirements", []) or []:
            chunks.append(r.get("current_state") or "")
        if p.get("kind") == "observation":
            chunks += [" ".join(t.split(" | ")[:2]) + "." for t in p.get("row_texts", [])]
        if p.get("kind") == "text":
            chunks.append(p.get("current") or p.get("text") or "")
    out = []
    for c in chunks:
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", c) if s.strip()]
    return out


def says(sentences: list[str], *names: str) -> str | None:
    """The first sentence of the section that names every one of `names`."""
    for s in sentences:
        if all(re.search(rf"\b{re.escape(n)}\b", s, re.I) for n in names):
            return s
    return None


def _says_any(sentences: list[str], host: str, ev: dict) -> str | None:
    """A sentence that names the host, or one of its addresses from the host register."""
    ips = [i for i in re.split(r"[;,\s]+", (ev["register"].get(host) or {}).get("ips") or "") if IPV4.fullmatch(i)]
    return next((s for s in (says(sentences, x) for x in [host, *ips]) if s), None)


def number_word(s: str) -> int | None:
    s = s.lower()
    return int(s) if s.isdigit() else WORDS.get(s)


# ------------------------------------------------------------------ helpers
def _ranges(ids: list[str]) -> str:
    """E-067, E-068, E-069, E-071 -> E-067–E-069, E-071. Other citations (capture file lines) follow as they are."""
    nums = sorted({int(i[2:]) for i in ids if re.fullmatch(r"E-\d+", i)})
    other = sorted({i for i in ids if not re.fullmatch(r"E-\d+", i)})
    runs: list[list[int]] = []
    for n in nums:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    out = [f"E-{a:03d}" if a == b else f"E-{a:03d}–E-{b:03d}" for a, b in runs]
    text = ", ".join(out + other)
    if len(text) > 140 and nums:                         # a long list reads as a range in a figure source line
        text = f"E-{nums[0]:03d} to E-{nums[-1]:03d} ({len(nums)} rows)" + (f", {', '.join(other)}" if other else "")
    return text


def _dates(hosts: list[str], ev: dict) -> str:
    ds = []
    for h in hosts:
        m = re.search(r"_(\d{4})(\d{2})(\d{2})T", (ev["register"].get(h) or {}).get("capture") or "")
        if m:
            ds.append(m.groups())
    if not ds:
        return ""
    fmt = lambda d: time.strftime("%-d %B %Y", time.strptime("-".join(d), "%Y-%m-%d"))
    lo, hi = min(ds), max(ds)
    return fmt(lo) if lo == hi else f"{fmt(lo)} to {fmt(hi)}"


def _names_in(text: str) -> set[str]:
    return {m.upper() for m in HOSTLIKE.findall(text or "")} | set(IPV4.findall(text or "")) | {m.lower() for m in FQDN.findall(text or "")}


# ------------------------------------------------------------------ build
def build(row: dict, node: dict, ev: dict, layout: dict, rel_rows: list[dict] | None = None, model: dict | None = None,
          old: dict | None = None) -> dict:
    reqs = [r["id"] for r in row.get("requirements", [])]
    sentences = section_text(node)
    if row.get("archetype") == "B":
        b = _service(row, reqs, sentences, ev, layout, rel_rows or [])
    elif row.get("archetype") in ("C", "D"):
        b = _paths(row, reqs, sentences, ev, model or {})
    elif row.get("archetype") == "A":
        b = _overview(row, reqs, sentences, ev, model or {})
    elif row.get("archetype") == "F":
        b = _flows(row, reqs, sentences, ev, model or {})
    else:
        b = {"purpose": f"Shows {_lc(row.get('question') or row['title'])}.", "caption": row.get("caption") or row["title"],
             "source": "Source: discovery captures.", "items": [], "gaps": [], "allowed": []}
    brief = {"key": row["key"], "number": row.get("number"), "title": row["title"], "profile": row.get("profile"),
             "archetype": row.get("archetype"), "question": row.get("question"), "requirements": reqs,
             "purpose": {"text": b["purpose"], "by": "framework"}, "caption": {"text": b["caption"], "by": "framework"},
             "source": {"text": b["source"], "by": "framework"}, "items": b["items"], "gaps": b["gaps"],
             "allowed": sorted(set(b.get("allowed", []))), "built": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return _keep_edits(brief, old) if old else brief


def _lc(q: str) -> str:
    return q[:1].lower() + q[1:] if q and not q[:2].isupper() else q


def _service(row, reqs, sentences, ev, layout, rows) -> dict:
    from csa_docx.figures import need
    service = next((p.get("service") for p in need.load_profiles() if p["id"] == row.get("profile")), "")
    word = SERVICE_WORD.get(service, service)
    prof = next((p for p in need.load_profiles() if p["id"] == row.get("profile")), {})
    ot_gap = prof.get("ot_gap") or f"OT-resident {word} provider"
    vital = sorted(need.vital_hosts(ev))
    active = [r for r in rows if r["state"] == "active"]
    items, gaps, allowed = [], [], set()
    by: dict[tuple, list[dict]] = {}
    for r in active:
        by.setdefault((r["provider"], r["side"], r["side_reason"]), []).append(r)
    n = 0
    for (p, side, why), rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        n += 1
        cons = sorted({r["consumer"] for r in rs})
        allowed |= {p, *cons}
        items.append({"id": f"I{n}", "what": f"{len(cons)} vital host{'s' if len(cons) != 1 else ''} take{'s' if len(cons) == 1 else ''} "
                      f"{word} from {p} ({SIDE_WORD.get(side, side)})", "hosts": cons, "provider": p, "state": "active",
                      "side": side, "side_reason": why, "requirements": reqs, "status": "shown",
                      "evidence": sorted({e for r in rs for e in r["evidence"]}), "section_says": _says_any(sentences, p, ev), "include": True})
    inactive: dict[str, list[dict]] = {}
    for r in rows:
        if r["state"] != "active":
            inactive.setdefault(r["provider"], []).append(r)
    for p, rs in inactive.items():
        n += 1
        cons = sorted({r["consumer"] for r in rs})
        allowed |= {p, *cons}
        items.append({"id": f"I{n}", "what": f"{p} configured on {', '.join(cons)} but not in use", "hosts": cons, "provider": p,
                      "state": "inactive", "side": rs[0]["side"], "requirements": reqs, "status": "shown",
                      "evidence": sorted({e for r in rs for e in r["evidence"]}), "section_says": says(sentences, p), "include": True})
    ot = sorted({r["provider"] for r in active if r["side"] == "ot"})
    n += 1
    if ot:
        items.append({"id": f"I{n}", "what": f"{ot_gap[:1].upper() + ot_gap[1:]}: {', '.join(ot)}", "requirements": reqs, "status": "shown",
                      "evidence": sorted({e for r in active if r["side"] == "ot" for e in r["evidence"]}), "section_says": None, "include": True})
    else:
        stated = next((s for s in sentences if re.search(r"\bno (OT|OT-local|OT-resident)\b", s, re.I)), None)
        items.append({"id": f"I{n}", "what": f"No {ot_gap} in the evidence", "requirements": reqs, "status": "absent",
                      "evidence": sorted({e for r in active for e in r["evidence"]}), "section_says": stated, "include": True})
    # gaps: vital hosts with no captured provider, providers whose side is not captured
    taken = {r["consumer"] for r in active}
    g = 0
    for h in vital:
        if h not in taken:
            g += 1
            uncaptured = not (ev["register"].get(h) or {}).get("capture")
            gaps.append({"id": f"G{g}", "what": f"{h}: " + (f"not in the discovery captures, so its {word} source is not known"
                                                         if uncaptured else f"{word} source not captured"), "host": h, "requirements": reqs,
                         "why": f"Needed to show where {h} takes {word} from in the {row['number']} figure."})
    for (p, side, why) in by:
        if side == "unknown":
            g += 1
            gaps.append({"id": f"G{g}", "what": f"Where {p} sits (IT or OT) is not captured", "host": p, "requirements": reqs,
                         "why": f"Needed to place {p} on the IT or OT side in the {row['number']} figure."})
    sides = {r["side"] for r in active}
    if not active:
        caption = f"No {word} source is captured for the vital OT hosts"
    elif ot and sides == {"ot"}:
        caption = f"Vital OT hosts take {word} from OT-resident providers"
    else:
        parts = [{"it": "enterprise (IT) providers", "internet": "Internet providers",
                  "unknown": "providers whose location is not captured"}[x] for x in ("it", "internet", "unknown") if x in sides]
        if ot:
            parts.insert(0, "OT-resident providers")
        caption = f"Vital OT hosts take {word} from " + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0])
        caption += "" if ot else f"; no {ot_gap} is evidenced"
    hosts = sorted(taken)
    when = _dates(hosts, ev)
    source = f"Source: discovery captures{(', ' + when) if when else ''}; evidence {_ranges([e for r in rows for e in r['evidence']])}."
    purpose = (f"Shows which provider each of the {len(hosts)} vital OT hosts takes {word} from, and whether that "
               "provider is OT-resident or outside OT.")
    return {"purpose": purpose, "caption": caption, "source": source, "items": items, "gaps": gaps, "allowed": allowed}


def _overview(row, reqs, sentences, ev, model) -> dict:
    nodes = model.get("nodes", [])
    zones = {z["id"]: z["label"] for z in model.get("zones", [])}
    items, gaps, allowed = [], [], set()
    for i, (z, label) in enumerate(zones.items(), 1):
        members = [n for n in nodes if n.get("zone") == z]
        if members:
            items.append({"id": f"I{i}", "what": f"{label}: {len(members)} system{'s' if len(members) != 1 else ''}",
                          "requirements": reqs, "status": "shown", "evidence": [], "section_says": None, "include": True})
    unrecorded = [n["label"] for n in nodes if n.get("kind") == "unknown" and n.get("host")]
    for g, h in enumerate(sorted(unrecorded), 1):
        gaps.append({"id": f"G{g}", "what": f"{h}: role not recorded", "host": h, "requirements": reqs,
                     "why": "Needed to show what this system is in the system overview."})
    allowed |= {n["label"] for n in nodes}
    hosts = [n["id"] for n in nodes if n.get("host")]
    when = _dates(hosts, ev)
    return {"purpose": "Shows the whole system: both data centres with their systems by tier, the shared services, and the links to IT and the Internet.",
            "caption": row.get("caption") or "System overview", "source": f"Source: discovery captures{(', ' + when) if when else ''}.",
            "items": items, "gaps": gaps, "allowed": allowed}


def _paths(row, reqs, sentences, ev, model) -> dict:
    """C (zones and conduits) and D (access path): one item per drawn path, from the captured connections."""
    names = {n["id"]: n["label"] for n in model.get("nodes", [])}
    names.update({g["id"]: g["label"] for g in model.get("groups", [])})
    names.update({f"Z:{z['id']}": z["label"] for z in model.get("zones", [])})
    nm = lambda x: names.get(x, x)
    items, gaps, allowed = [], [], set()
    edges = model.get("edges", [])
    for n, e in enumerate(edges, 1):
        label = " · ".join(l for l in (e.get("label") or "").split("\n") if l)
        arrow = "↔" if e.get("dir") == "both" else "→"
        named = [x for x in (e["s"], e["t"]) if not x.startswith(("Z:", "G-", "SG:"))]
        tail = {"unenforced": " (no boundary control evidenced)", "direct": " (from outside OT, not through a jump host)",
                "via-jump": " (through a jump host)"}.get(e["status"], "")
        items.append({"id": f"I{n}", "what": f"{nm(e['s'])} {arrow} {nm(e['t'])}: {label}{tail}", "requirements": reqs,
                      "status": "shown", "evidence": list(e.get("evidence", []))[:40], "include": True,
                      "section_says": says(sentences, *named) if named else None})
        allowed |= {e["s"], e["t"], *(e.get("detail") or {}).get("hosts", [])}
    allowed |= {n["label"] for n in model.get("nodes", [])}
    g = 0
    if row.get("archetype") == "C":
        u = sum(1 for e in edges if e["status"] == "unenforced")
        # A boundary device recorded in the register but not on any captured path: the captions must not
        # claim "no boundary control is evidenced" -- that would contradict the register and the evidence rows.
        fw_in_register = {n["id"]: n for n in model.get("nodes", []) if n.get("kind") == "firewall"}
        if u:
            g += 1
            if fw_in_register:
                what = ("A boundary firewall is recorded in the host register (" + fw_in_register[next(iter(fw_in_register))]["role"] + ") "
                        "but its address was not captured, so no individually captured path is shown crossing it")
            else:
                what = "Boundary devices (firewalls, proxies) between these zones are not in the discovery captures"
            gaps.append({"id": f"G{g}", "what": what,
                         "requirements": reqs, "why": f"Needed to show whether the {u} cross-zone paths in the {row['number']} figure are controlled."})
        if edges:
            if fw_in_register and u == len(edges):
                caption = (f"{len(edges)} captured flows cross a zone boundary; a boundary firewall is evidenced in the register "
                           "but no captured flow has a recorded firewall address")
            else:
                caption = (f"Captured flows that cross a zone boundary; the boundary devices on "
                           f"{'them' if u == len(edges) else 'some of them'} are not in the captures")
        else:
            caption = "No captured flow crosses a zone boundary"
        purpose = "Shows the captured flows that cross a zone boundary, and whether a boundary device is captured on each."
    else:
        jumps = [n["label"] for n in model.get("nodes", []) if n.get("kind") == "jump_host"]
        d = sum(1 for e in edges if e["status"] == "direct")
        if any("inbound side" in x for x in model.get("notes", [])):
            g += 1
            gaps.append({"id": f"G{g}", "what": "Who connects to the jump hosts (the inbound side of the access path) is not captured",
                         "requirements": reqs, "why": f"Needed to show where admin access starts in the {row['number']} figure."})
        if row.get("profile") == "vendor-access":
            g += 1
            gaps.append({"id": f"G{g}", "what": "Vendor entry points (remote access gateway, accounts) are not captured",
                         "requirements": reqs, "why": f"Needed to show how vendors reach the vital hosts in the {row['number']} figure."})
        caption = (f"{len(jumps)} jump host{'s are' if len(jumps) != 1 else ' is'} evidenced" if jumps else "No jump host is evidenced") + \
            (f"; {d} path{'s carry' if d != 1 else ' carries'} admin protocols from outside OT to OT hosts without one" if d else "")
        purpose = "Shows the admin protocols that reach the vital OT hosts, and whether each path passes through a jump host."
    hosts = [h for e in edges for h in (e.get("detail") or {}).get("hosts", [])]
    when = _dates(sorted(set(hosts)), ev)
    ids = [i for e in edges for i in e.get("evidence", [])]
    source = f"Source: connection captures{(', ' + when) if when else ''}" + (f"; evidence {_ranges(ids)}." if ids else ".")
    return {"purpose": purpose, "caption": caption, "source": source, "items": items, "gaps": gaps, "allowed": allowed}


def _flows(row, reqs, sentences, ev, model) -> dict:
    """F (data flow): one item per data store and per drawn line; gaps for what the captures do not show."""
    items, gaps, allowed = [], [], set()
    k = 0
    for n in model.get("nodes", []):
        for s in n.get("stores", []):
            k += 1
            items.append({"id": f"I{k}", "what": f"{n['id']} holds {s['what']}", "requirements": reqs, "status": "shown",
                          "evidence": [], "include": True, "section_says": says(sentences, n["id"])})
    for e in model.get("edges", []):
        k += 1
        st = {"declared": " (declared in the flow map, not seen)", "attempted": " (attempted, no reply seen)"}.get(e["status"], "")
        way = {"to_s": f"data goes to {e['s']}", "to_t": f"data goes to {e['t']}",
               "both": "data can go either way"}.get(e.get("data"), "data direction not known")
        ends = [x for x in (e["s"], e["t"]) if not x.startswith(("VIA:", "GAP:"))]
        items.append({"id": f"I{k}", "what": f"{e['s']} opens {e['mechanism']} connections to {e['t']}, {way}{st}",
                      "requirements": reqs, "status": "shown", "evidence": list(e.get("evidence", []))[:40], "include": True,
                      "section_says": says(sentences, *ends) if ends else None})
        allowed |= {e["s"], e["t"]}
    allowed |= {n["label"] for n in model.get("nodes", [])}
    g = 0
    not_captured = any(c["kind"] == "not captured" for c in model.get("controls", []))
    if not_captured:
        g += 1
        gaps.append({"id": f"G{g}", "what": "Boundary devices (firewalls, proxies, transfer or scanning servers) on the flows that "
                                            "cross a zone are not in the discovery captures", "requirements": reqs,
                     "why": f"Needed to show whether the data entering or leaving OT in the {row['number']} figure is controlled or scanned."})
    unz = sorted({n["id"] for n in model.get("nodes", []) if n.get("zone") == "outside"})
    if unz:
        g += 1
        gaps.append({"id": f"G{g}", "what": "The zone of " + ", ".join(unz[:6]) + (" and other addresses" if len(unz) > 6 else "")
                                            + " is not recorded", "requirements": reqs,
                     "why": f"Needed to show whether these flows in the {row['number']} figure cross the IT/OT boundary."})
    for n in model.get("nodes", []):
        if "(likely, confirm)" in (n.get("role") or ""):
            g += 1
            gaps.append({"id": f"G{g}", "what": f"The role of {n['id']} is not recorded ({n['role']})", "requirements": reqs,
                         "why": f"Needed to name the system at that end of the {row['number']} figure's flows."})
    caption = "Data stores and data flows in and out of OT"
    if not_captured:
        caption += ". No proxy, firewall or scanning point is captured on the crossing flows"
    hosts = sorted({n["id"] for n in model.get("nodes", []) if not n["id"].startswith(("VIA:", "GAP:"))})
    when = _dates(hosts, ev)
    ids = [i for e in model.get("edges", []) for i in e.get("evidence", [])]
    source = (f"Source: flow inventory and host settings from the discovery captures{(', ' + when) if when else ''}"
              + (f"; evidence {_ranges(ids)}." if ids else "."))
    return {"purpose": "Shows where the system holds its data, the data flows that enter or leave OT, which side opens each "
                       "one, and what is evidenced on each crossing.",
            "caption": caption, "source": source, "items": items, "gaps": gaps, "allowed": allowed}

# ------------------------------------------------------------------ wording from an agent or from you
def wording_check(brief: dict, **texts: str) -> list[str]:
    """Problems with proposed wording: names a host, address or number the brief's items do not hold, or too long."""
    allowed = {a.upper() for a in brief.get("allowed", [])} | {a.lower() for a in brief.get("allowed", [])}
    known_text = " ".join([i["what"] for i in brief["items"]] + [brief["source"]["text"], brief["caption"]["text"],
                                                                 brief["purpose"]["text"]])
    known_numbers = set(NUMBER.findall(known_text))
    problems = []
    for field, text in texts.items():
        if text is None:
            continue
        if not text.strip():
            problems.append(f"{field} is empty")
            continue
        for name in _names_in(text):
            if name not in allowed and name.upper() not in allowed:
                problems.append(f"{field} names {name}, which is not in the figure")
        bare = IPV4.sub(" ", HOSTLIKE.sub(" ", text))
        for num in dict.fromkeys(NUMBER.findall(bare)):
            if num not in known_numbers and field != "source":
                problems.append(f"{field} gives the number {num}, which the brief does not hold")
        if field in ("caption", "purpose") and len(text.split()) > (30 if field == "caption" else 45):
            problems.append(f"{field} is too long")
    return problems


def _keep_edits(new: dict, old: dict) -> dict:
    for f in ("purpose", "caption", "source"):
        o = old.get(f) or {}
        if o.get("by") in ("agent", "you") and not wording_check(new, **{f: o.get("text", "")}):
            new[f] = o
    left_out = {i["what"] for i in old.get("items", []) if not i.get("include", True)}
    for i in new["items"]:
        if i["what"] in left_out:
            i["include"] = False
    return new


def edit(brief: dict, purpose: str | None = None, caption: str | None = None, source: str | None = None,
         include: dict[str, bool] | None = None, by: str = "you") -> tuple[dict, list[str]]:
    problems = wording_check(brief, purpose=purpose, caption=caption, source=source)
    if problems:
        return brief, problems
    for f, v in (("purpose", purpose), ("caption", caption), ("source", source)):
        if v is not None:
            brief[f] = {"text": v.strip(), "by": by}
    for i in brief["items"]:
        if include and i["id"] in include:
            i["include"] = bool(include[i["id"]])
    return brief, []


def excluded(brief: dict | None) -> set[tuple[str, str]]:
    """(provider, state) pairs of items you left out: the figure does not draw those lines."""
    if not brief:
        return set()
    return {(i["provider"], i["state"]) for i in brief.get("items", []) if not i.get("include", True) and i.get("provider")}


# ------------------------------------------------------------------ files
def path(work_dir: Path, key: str) -> Path:
    return Path(work_dir) / "figures" / key / "brief.json"


def load(work_dir: Path, key: str) -> dict | None:
    try:
        return json.loads(path(work_dir, key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save(work_dir: Path, key: str, brief: dict) -> Path:
    p = path(work_dir, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(brief, indent=1, ensure_ascii=False), encoding="utf-8")
    return p
