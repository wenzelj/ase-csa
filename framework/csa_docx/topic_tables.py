"""Topic tables: the role-grouped table that describes the system for a section's topic.

A CSA section describes how the system works for its topic and answers the requirement. Most of that is
per host: which time source each host follows, which DNS server it asks first. A list of aspects cannot
show it cleanly, so the framework builds this table itself from the captures (no model call) and puts it
under the Discovery Information heading, above the Aspect table. The Aspect table keeps only the points
that are not per host.

The table's shape follows the data:

* rows are role groups from the host register (hosts.csv); a role is split into sub-rows only where its
  captured hosts differ, with the role cell merged across them;
* columns are the profile's attributes (references/topic-tables/*.json); a column whose value is the
  same for every captured host moves into one "common" sentence under the table, a column with no data
  is dropped;
* a host with no capture for this topic takes its role's values and is marked "†" (one Discovery
  Required item per role asks to confirm it); when the captured hosts of its role differ it is marked
  "‡" and shows "Not captured"; a role with no captured host gets no row, only a Discovery Required item;
* no counts or totals anywhere: host names and role groups carry it.

Every cell keeps the capture lines it came from in ``csa-work/topic-tables/<KEY>.json``.

    python3 -m csa_docx.topic_tables build --work-dir <work_dir> --heading "Time Synchronisation" [--key TIME] [--json]
    python3 -m csa_docx.topic_tables place --work-dir <work_dir> --docx <docx> --heading "Time Synchronisation" [--key TIME]
    python3 -m csa_docx.topic_tables profiles
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

PROFILES = Path(__file__).resolve().parents[2] / "references" / "topic-tables"
CAPTION = "csa-topic-table"
ASSUMED, VARIES = "†", "‡"          # † ‡
MAX_COLUMNS = 4
IN_SCOPE = {"yes", "true", "listed", "1", "y"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower().replace("&", " and ")).strip()


# ---------------------------------------------------------------- profiles

def profiles() -> list[dict]:
    out = []
    for f in sorted(PROFILES.glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        p["_file"] = f.name
        out.append(p)
    return out


def profile_for(heading: str) -> dict | None:
    """The profile whose headings match ``heading`` (by text, never by section number)."""
    want = _norm(re.sub(r"^\d+(\.\d+)*\s+", "", heading or ""))
    for p in profiles():
        if want in {_norm(h) for h in p.get("headings", [])}:
            return p
    return None


# ---------------------------------------------------------------- inputs

def _site_order(work_dir: Path) -> list[str]:
    f = Path(work_dir) / "hosts" / "sites.txt"
    if f.is_file():
        return [x.strip() for x in f.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
    return []


def register(work_dir: Path) -> list[dict]:
    """In-scope hosts from hosts.csv: [{host, role, site, capture}] (role may be empty; capture: the host has one)."""
    f = Path(work_dir) / "hosts" / "hosts.csv"
    if not f.is_file():
        return []
    from csa_docx import modelstore
    out = []
    for r in modelstore.read_csv(f):
        if (r.get("in_scope") or "").strip().lower() not in IN_SCOPE:
            continue
        out.append({"host": r["host"].strip().upper(), "role": (r.get("role") or "").strip(),
                    "site": (r.get("site") or "").strip(), "capture": bool((r.get("capture") or "").strip())})
    return out


# ---------------------------------------------------------------- grouping

def list_items(value: str) -> list[str]:
    """The members of a list value ('A, B (x, y), C' -> ['A', 'B (x, y)', 'C']): commas inside brackets stay."""
    out, depth, cur = [], 0, ""
    for ch in value:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def build(work_dir: Path, heading: str, key: str = "", profile: dict | None = None,
          hosts: list[dict] | None = None, settings: dict | None = None) -> dict:
    """The topic table for ``heading``: {"status", "columns", "rows", "common", "markers", "gaps", ...}.

    ``rows`` are [{"role", "hosts": [display names], "cells": [...], "sources": [...], "first": bool}];
    ``status`` is NO_PROFILE when the topic has none, EMPTY when no in-scope host has a role and a capture."""
    from csa_docx import host_settings
    work_dir = Path(work_dir)
    profile = profile or profile_for(heading)
    if not profile:
        return {"status": "NO_PROFILE", "heading": heading}
    key = key or profile.get("key") or re.sub(r"[^A-Z0-9]+", "", heading.upper())[:6]
    hosts = register(work_dir) if hosts is None else hosts
    settings = host_settings.load(work_dir) if settings is None else settings
    cols = profile["columns"]
    attrs = [c["attribute"] for c in cols]
    # a column with "flows" takes its value from the flow inventory: what each host opened that the filter selects
    fcols = [c for c in cols if c.get("flows")]
    if fcols:
        from csa_docx import flows as flows_mod
        allf = flows_mod.load(work_dir)
        reg = {h["host"].upper() for h in hosts}
        settings = {h: dict(v) for h, v in settings.items()}
        for c in fcols:
            sel = [r for r in flows_mod.select(allf, c["flows"], reg) if r["status"] in ("observed", "both", "attempted")]
            for h in list(settings):
                if not settings[h]:
                    continue
                hits = [r for r in sel if h in {x.strip().upper() for x in r["src"].split(",")}]
                seen_m = sorted({r["mechanism"] for r in hits if r["status"] != "attempted"})
                tried_m = sorted({r["mechanism"] for r in hits if r["status"] == "attempted"} - set(seen_m))
                mechs = [", ".join(seen_m)] if seen_m else []
                if tried_m:
                    mechs.append(("attempted only: " if seen_m else "Attempted only: ") + ", ".join(tried_m))
                first = hits[0] if hits else {}
                settings[h][c["attribute"]] = {
                    "value": "; ".join(mechs) if hits else c.get("none", "None seen"),
                    "source": (first.get("sources") or "").split("; ")[0], "excerpt": first.get("excerpt", "")}
    sites = _site_order(work_dir)
    rank = lambda s: (sites.index(s) if s in sites else len(sites), s)          # noqa: E731
    hsort = lambda h: (rank(h["site"]), h["host"])                               # noqa: E731

    captured = {h["host"]: settings[h["host"]] for h in hosts
                if h["role"] and any(a in settings.get(h["host"], {}) for a in attrs)}
    unassigned = sorted(h["host"] for h in hosts if not h["role"])
    if not captured:
        return {"status": "EMPTY", "heading": heading, "key": key, "unassigned": unassigned}

    # list columns ("list": true): members every captured host has go to the common sentence, cells keep the rest
    common, shown = [], []
    captured = {h: dict(v) for h, v in captured.items()}
    for c in cols:
        if not c.get("list"):
            continue
        a = c["attribute"]
        have = [h for h in captured if captured[h].get(a, {}).get("value")]
        if len(have) < 2 or len({captured[h][a]["value"] for h in have}) == 1:
            continue
        items = {h: list_items(captured[h][a]["value"]) for h in have}
        shared = [x for x in items[have[0]] if all(x in items[h] for h in have)]
        if not shared:
            continue
        common.append(c | {"value": _join(shared), "shared": True, "count": len(shared),
                           "missing": sorted(h for h in captured if h not in have)})
        for h in have:
            rest = [x for x in items[h] if x not in shared]
            captured[h][a] = captured[h][a] | {"value": ", ".join(rest) or c.get("rest_none", "No others")}

    # columns: same value for every captured host -> the common sentence; no value at all -> dropped
    for c in cols:
        vals = {captured[h].get(c["attribute"], {}).get("value", "") for h in captured}
        if vals == {""}:
            continue
        known = vals - {""}
        if len(known) == 1 and c.get("list") and known == {c.get("rest_none", "No others")}:
            continue                   # every member is shared: the common sentence already says it
        if len(known) == 1 and not c.get("keep"):   # one value wherever captured: the common sentence, naming the gaps
            missing = sorted(h for h in captured if not captured[h].get(c["attribute"], {}).get("value"))
            common.append(c | {"value": known.pop(), "missing": missing})
        else:
            shown.append(c)
    warnings = []
    if len(shown) > MAX_COLUMNS:
        warnings.append(f"{len(shown)} columns vary; the profile allows {MAX_COLUMNS} on an A4 page")

    by_role: dict[str, list[dict]] = {}
    for h in hosts:
        if h["role"]:
            by_role.setdefault(h["role"], []).append(h)
    rows, gaps, markers = [], [], set()
    topic = profile.get("topic", heading)
    tname = topic if topic.isupper() else topic.lower()
    nd = 0

    def gap(text: str, hosts_: list[str], role: str) -> None:
        nonlocal nd
        nd += 1
        gaps.append({"dr_id": f"DR-{key}-T{nd:02d}", "text": text, "reqs": list(profile.get("requirements", [])),
                     "fact": f"{role}: {', '.join(hosts_)}", "section": heading, "hosts": hosts_, "role": role})

    for role in sorted(by_role, key=lambda r: (min(rank(h["site"]) for h in by_role[r]), r.lower())):
        members = sorted(by_role[role], key=hsort)
        cap = [h for h in members if h["host"] in captured]
        unc = [h for h in members if h["host"] not in captured]
        if not cap:
            names = [h["host"] for h in unc]
            held = [h["host"] for h in unc if h.get("capture")]      # captured, but the capture holds no such settings
            rest = [n for n in names if n not in held]
            if not held:
                why = "no host of this role was captured."
            else:
                why = (f"the {'captures' if len(held) > 1 else 'capture'} of {_join(held)} "
                       f"{'hold' if len(held) > 1 else 'holds'} no {tname} settings"
                       + (f", and {_join(rest)} {'were' if len(rest) > 1 else 'was'} not captured." if rest else "."))
            gap(f"Capture the {tname} settings of {_join(names)} ({role}): {why}", names, role)
            continue
        variants: dict[tuple, list[dict]] = {}
        for h in cap:
            vals = tuple(captured[h["host"]].get(c["attribute"], {}).get("value", "") or "Not in capture" for c in shown)
            variants.setdefault(vals, []).append(h)
        order = sorted(variants.items(), key=lambda kv: (rank(kv[1][0]["site"]), kv[1][0]["host"]))
        for i, (vals, hs) in enumerate(order):
            names = [h["host"] for h in hs]
            if unc and len(order) == 1:
                names += [h["host"] + ASSUMED for h in unc]
                markers.add(ASSUMED)
            srcs = [captured[h["host"]][c["attribute"]]["source"] for h in hs for c in shown
                    if c["attribute"] in captured[h["host"]]]
            srcs += [captured[h["host"]][c["attribute"]]["source"] for h in hs for c in common
                     if c["attribute"] in captured[h["host"]]]
            rows.append({"role": role, "first": i == 0, "hosts": names, "cells": list(vals), "sources": sorted(set(srcs))})
        if unc and len(order) == 1:
            names = [h["host"] for h in unc]
            gap(f"Confirm that {_join(names)} ({role}) {'use' if len(names) > 1 else 'uses'} the same {tname} settings "
                f"as the captured hosts of that role.", names, role)
        elif unc:
            rows.append({"role": role, "first": False, "hosts": [h["host"] + VARIES for h in unc],
                         "cells": ["Not captured"] * len(shown), "sources": []})
            markers.add(VARIES)
            gap(f"Capture the {tname} settings of {_join([h['host'] for h in unc])} ({role}): "
                f"the captured hosts of this role differ.", [h["host"] for h in unc], role)

    common_line = ""
    if common:
        cv = profile.get("common_values", {})
        def phrase(c: dict) -> str:
            if c.get("shared"):
                return (c.get("common_shared") or f"have {{value}} in {c['label'].lower()}").format(
                    value=c["value"], s="s" if c.get("count", 1) > 1 else "")
            if c["value"] in cv:
                return cv[c["value"]]
            if c["value"] in ("None", "None found"):
                return c.get("common_none") or f"have no {c.get('noun', c['label'].lower())} found"
            return (c.get("common") or f"have {c['label'].lower()} {{value}}").format(value=c["value"])
        parts = [phrase(c) for c in common]
        common_line = f"All hosts in this table {_join(parts)}."
        gaps_ = sorted({h for c in common for h in c.get("missing", [])})
        if gaps_:
            common_line = common_line[:-1] + f", where captured ({_join(gaps_)} not captured for this)."
    marker_lines = []
    if ASSUMED in markers:
        marker_lines.append(f"{ASSUMED} Not captured, assumed to match the captured hosts of its role.")
    if VARIES in markers:
        marker_lines.append(f"{VARIES} Not captured, and the captured hosts of its role differ.")
    return {"status": "OK", "heading": heading, "key": key, "profile": profile.get("_file", ""),
            "columns": ["Role", "Hosts"] + [c["label"] for c in shown],
            "explains": {c["label"]: c.get("explains", "") for c in shown},
            "rows": rows, "common": common_line, "common_sources": sorted({captured[h][c["attribute"]]["source"]
                                                                           for h in captured for c in common
                                                                           if c["attribute"] in captured[h]}),
            "markers": marker_lines, "gaps": gaps, "unassigned": unassigned, "warnings": warnings}


def build_flows(work_dir: Path, heading: str, profile: dict | None = None) -> dict:
    """The data-flow table for a topic whose profile has "flows": rows grouped by mechanism (merged cell), the side
    that opens the connection, the other end, the port and whether the flow map declares it. No counts."""
    from csa_docx import flows as flows_mod
    profile = profile or profile_for(heading)
    flt = (profile or {}).get("flows")
    if not flt:
        return {"status": "NO_FLOWS"}
    rows = flows_mod.select(flows_mod.load(work_dir), flt, {h["host"].upper() for h in register(work_dir)})
    if not rows:
        return {"status": "EMPTY"}
    def zone(zs: list[str]) -> str:
        return "/".join(zs) or "zone not recorded"
    out, last = [], None
    gs = sorted(flows_mod.groups(rows), key=lambda g: (g["mechanism"], g["status"] == "declared", g["srcs"][0]))
    for g in gs:
        seen = {"both": f"Declared ({g['declared_id']}) and seen", "observed": "Seen, not in the flow map",
                "declared": f"Declared ({g['declared_id']}), not seen",
                "attempted": "Attempted, no reply seen"}[g["status"]]
        dsts = g["dsts"] if len(g["dsts"]) <= 4 else g["dsts"][:3] + ["other addresses"]   # every one stays in the sources
        to = f"{', '.join(dsts[:-1]) + ' and ' + dsts[-1] if dsts[-1] == 'other addresses' else ', '.join(dsts)} " \
             f"({zone(g['dst_zones'])}{', crosses zones' if g['cross_zone'] == 'yes' else ''})"
        out.append({"role": g["mechanism"][:1].upper() + g["mechanism"][1:], "first": g["mechanism"] != last,
                    "hosts": [f"{', '.join(g['srcs'])} ({zone(g['src_zones'])})"],
                    "cells": [to, str(g["port"]), seen],
                    "sources": [c for f in g["flows"] for c in f["sources"].split("; ") if c]})
        last = g["mechanism"]
    return {"status": "OK", "heading": heading, "key": (profile or {}).get("key", ""),
            "columns": ["Mechanism", "From (opens the connection)", "To", "Port", "Flow map"], "rows": out,
            "common": "From is the side that opens the connection. Seen means it appeared in the sampled process "
                      "connections. Attempted means the host sent a connection request and no reply was seen in the "
                      "netstat samples. Zones come from the project zone list.", "markers": [], "gaps": [], "unassigned": [],
            "warnings": []}


def build_all(work_dir: Path, heading: str, key: str = "") -> list[dict]:
    """Every framework-built table for the topic.

    A profile may declare ``evidence_tables`` to project capture data into one table per requirement. The placer
    keeps each projection immediately after that requirement's story. One-requirement profiles get the same
    behaviour automatically; older multi-requirement profiles retain their combined tables.
    """
    profile = profile_for(heading)
    if not profile:
        return [{"status": "NO_PROFILE", "heading": heading}]
    specs = profile.get("evidence_tables") or []
    out: list[dict] = []
    if specs:
        for spec in specs:
            projected = dict(profile)
            projected["requirements"] = [spec["requirement"]]
            if spec.get("kind", "roles") == "flows":
                if spec.get("flows") is not None:
                    projected["flows"] = spec["flows"]
                table = build_flows(work_dir, heading, projected)
            else:
                attrs = set(spec.get("attributes") or [])
                projected["columns"] = [c for c in profile.get("columns", []) if c.get("attribute") in attrs]
                table = build(work_dir, heading, key, projected)
            table["requirement"] = spec["requirement"]
            table["evidence_title"] = spec.get("title", "Discovery evidence")
            table["replace_observation_table"] = bool(profile.get("replace_observation_table"))
            if table.get("status") == "OK":
                out.append(table)
    else:
        t = build(work_dir, heading, key, profile)
        out = [t]
        if t.get("status") != "NO_PROFILE":
            f = build_flows(work_dir, heading, profile)
            if f.get("status") == "OK":
                out.append(f)
        reqs = profile.get("requirements") or []
        if len(reqs) == 1:
            for table in out:
                table["requirement"] = reqs[0]

    gaps: dict[tuple, dict] = {}
    for table in out:
        for gap in table.get("gaps", []):
            sig = (gap.get("text", ""), tuple(gap.get("hosts", [])), gap.get("role", ""))
            if sig not in gaps:
                gaps[sig] = dict(gap)
                gaps[sig]["reqs"] = []
            gaps[sig]["reqs"] = sorted(set(gaps[sig]["reqs"]) | set(gap.get("reqs", [])))
        table["gaps"] = []
    merged = list(gaps.values())
    for i, gap in enumerate(merged, 1):
        gap["dr_id"] = f"DR-{key or profile.get('key', '')}-T{i:02d}"
    if out:
        out[0]["gaps"] = merged
    return out


def markdown(t) -> str:
    """The table (or a list of tables) as Markdown (for the section card and the run log)."""
    if isinstance(t, list):
        parts = []
        for x in t:
            body = markdown(x)
            if not body:
                continue
            label = x.get("requirement")
            parts.append((f"### {label} — {x.get('evidence_title', 'Discovery evidence')}\n\n" if label else "") + body)
        return "\n\n".join(parts)
    if t.get("status") != "OK":
        return ""
    out = ["| " + " | ".join(t["columns"]) + " |", "| " + " | ".join("---" for _ in t["columns"]) + " |"]
    for r in t["rows"]:
        out.append("| " + " | ".join([r["role"] if r["first"] else "", ", ".join(r["hosts"])] + r["cells"]) + " |")
    lines = [l for l in [t["common"], *t["markers"]] if l]
    return "\n".join(out + ([""] + lines if lines else []))


def save(work_dir: Path, t: dict) -> Path:
    """csa-work/topic-tables/<KEY>.json (the table with every cell's sources) and gaps.json (all keys)."""
    d = Path(work_dir) / "topic-tables"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{t['key']}.json"
    f.write_text(json.dumps(t, indent=1, ensure_ascii=False), encoding="utf-8")
    allg = load_gaps(work_dir)
    if t.get("gaps"):
        allg[t["key"]] = t["gaps"]
    else:
        allg.pop(t["key"], None)
    (d / "gaps.json").write_text(json.dumps(allg, indent=1, ensure_ascii=False), encoding="utf-8")
    return f


def load_gaps(work_dir: Path) -> dict:
    try:
        return json.loads((Path(work_dir) / "topic-tables" / "gaps.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def all_gaps(work_dir: Path) -> list[dict]:
    return [g for gs in load_gaps(work_dir).values() for g in gs]


def merge_gaps(gaps: list[dict]) -> list[dict]:
    """One Discovery Required item per role group and action, not one per topic: gaps with the same role, hosts and
    action (capture or confirm) become one item that names every topic it covers. The first topic's DR ID leads and
    every per-topic DR ID stays in ``fact`` as a reference. A group of one gap is returned unchanged."""
    groups: dict[tuple, list[dict]] = {}
    for g in gaps:
        verb = g["text"].split(" ", 1)[0].lower()
        groups.setdefault((g.get("role", ""), tuple(sorted(g.get("hosts", []))), verb), []).append(g)
    out = []
    for (role, hosts, verb), gs in groups.items():
        if len(gs) == 1:
            out.append(gs[0])
            continue
        topics = list(dict.fromkeys(g.get("section", "") or g["dr_id"] for g in gs))
        names = _join(list(hosts))
        what = (f"Confirm that {names} ({role}) {'use' if len(hosts) > 1 else 'uses'} the same settings as the captured "
                f"hosts of that role" if verb == "confirm" else f"Capture the settings of {names} ({role})")
        reqs = list(dict.fromkeys(r for g in gs for r in g.get("reqs", [])))
        out.append({**gs[0], "text": f"{what}, for {len(topics)} topics: {_join(topics)}.", "reqs": reqs,
                    "fact": f"{gs[0].get('fact', '')}. Topic items: {', '.join(g['dr_id'] for g in gs)}",
                    "section": ", ".join(topics)})
    return out


# ---------------------------------------------------------------- into the document

_P = re.compile(r"<w:p\b[^>]*/>|<w:p\b(?:(?!</w:p>).)*?</w:p>", re.S)
_TBL = re.compile(r"<w:tbl>.*?</w:tbl>", re.S)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _text(xml: str) -> str:
    import html
    return html.unescape("".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>",
                                            re.sub(r"<w:delText.*?</w:delText>", "", xml, flags=re.S))))


def _blocks(xml: str, start: int, end: int) -> list[tuple[str, int, int, str]]:
    """Top-level body blocks between start and end: (kind 'p'|'tbl', start, end, xml)."""
    out, i = [], start
    while i < end:
        mt = xml.find("<w:tbl>", i)
        m = _P.search(xml, i)
        nxt = [x for x in ((mt, "tbl"), (m.start() if m else -1, "p")) if 0 <= x[0] < end]
        if not nxt:
            break
        pos, kind = min(nxt)
        if kind == "tbl":
            depth, j = 0, pos
            for t in re.finditer(r"<w:tbl>|</w:tbl>", xml[pos:]):
                depth += 1 if t.group(0) == "<w:tbl>" else -1
                if depth == 0:
                    j = pos + t.end()
                    break
            out.append(("tbl", pos, j, xml[pos:j]))
            i = j
        else:
            # a paragraph can hold others (a figure drawn as Word shapes has text boxes): match to its own </w:p>
            depth, j = 0, m.end()
            for t in _PTAG.finditer(xml, pos):
                if t.group(0).endswith("/>"):
                    continue
                depth += -1 if t.group(0) == "</w:p>" else 1
                if depth == 0:
                    j = t.end()
                    break
            out.append(("p", pos, j, xml[pos:j]))
            i = j
    return out


_PTAG = re.compile(r"<w:p(?=[\s>/])[^>]*>|</w:p>")


def _heading_level(p: str) -> int | None:
    m = re.search(r'<w:pStyle w:val="Heading\s?(\d)"', p)
    return int(m[1]) if m else None


def _locate(xml: str, heading: str) -> tuple[int, int, int] | None:
    """(insert offset after the Discovery Information heading, end of that facet, H2 level) for ``heading``."""
    want = _norm(re.sub(r"^\d+(\.\d+)*\s+", "", heading))
    body_s = xml.find("<w:body>")
    heads = [(m.start(), m.end(), _heading_level(m.group(0)), _text(m.group(0)))
             for m in _P.finditer(xml, body_s) if _heading_level(m.group(0))]
    for i, (s, e, lvl, t) in enumerate(heads):
        if _norm(t) != want:
            continue
        end = next((h[0] for h in heads[i + 1:] if h[2] <= lvl), len(xml))
        for k in range(i + 1, len(heads)):
            s2, e2, l2, t2 = heads[k]
            if s2 >= end:
                break
            if l2 > lvl and _norm(t2) == "discovery information":
                fend = next((h[0] for h in heads[k + 1:] if h[2] <= l2), end)
                return e2, fend, lvl
        return None
    return None


def _cell(width: int, text: str, style: str, vmerge: str | None = None, fill: str = "") -> str:
    vm = "" if vmerge is None else ('<w:vMerge w:val="restart"/>' if vmerge == "restart" else "<w:vMerge/>")
    shd = f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>' if fill else ""
    run = f'<w:r><w:t xml:space="preserve">{_esc(text)}</w:t></w:r>' if text else ""
    return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{vm}{shd}</w:tcPr>'
            f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{run}</w:p></w:tc>')


def band_fill(styles_xml: str, style_id: str) -> str:
    """The table style's banded-row fill (band1Horz), so a role group's sub-rows can share one band."""
    m = re.search(rf'<w:style [^>]*w:styleId="{re.escape(style_id)}".*?</w:style>', styles_xml or "", re.S)
    if not m:
        return ""
    b = re.search(r'<w:tblStylePr w:type="band1Horz">.*?<w:shd [^>]*w:fill="([0-9A-Fa-f]{6})"', m.group(0), re.S)
    return b.group(1) if b else ""


def table_xml(t: dict, reference: str, fill: str = "") -> str:
    """The role table as WordprocessingML, styled from ``reference`` (the Aspect table under the same heading):
    its tblPr (plus the hidden caption that marks the table as framework-built), its header and banded row
    properties and its cell paragraph styles."""
    tblpr = re.search(r"<w:tblPr>.*?</w:tblPr>", reference, re.S)
    tblpr = tblpr.group(0) if tblpr else '<w:tblPr><w:tblW w:w="9638" w:type="dxa"/></w:tblPr>'
    tblpr = re.sub(r"<w:tblCaption\b[^>]*/>", "", tblpr).replace("</w:tblPr>", f'<w:tblCaption w:val="{CAPTION}"/></w:tblPr>')
    if fill:          # bands follow role groups, not rows: the style's row banding is off and each group is shaded itself
        tblpr = re.sub(r'w:noHBand="[01]"', 'w:noHBand="1"', tblpr)
        tblpr = re.sub(r'(<w:tblLook\b[^>]*\bw:val=")([0-9A-Fa-f]{4})"',
                       lambda m: f'{m.group(1)}{int(m.group(2), 16) | 0x0200:04X}"', tblpr)   # 0x0200 = no row bands
    total = sum(int(w) for w in re.findall(r'<w:gridCol w:w="(\d+)"', reference)) or 9638
    rows = re.findall(r"<w:tr\b.*?</w:tr>", reference, re.S)
    trpr = lambda r: (re.search(r"<w:trPr>.*?</w:trPr>", r, re.S) or [""])[0]           # noqa: E731
    head_pr = trpr(rows[0]) if rows else ""
    band = [re.sub(r"<w:cnfStyle\b[^>]*/>", "", trpr(r)) for r in rows[1:3]] or [""]
    style = lambda r, d: (re.search(r'<w:pStyle w:val="([^"]+)"', r) or [None, d])[1]    # noqa: E731
    hs = style(rows[0], "TableHeader") if rows else "TableHeader"
    ds = style(rows[1], "TableText") if len(rows) > 1 else "TableText"
    n = len(t["columns"])
    if n > 2:
        # Role and Hosts get a fixed share; the value columns share the rest by how long their text runs (at least 12 %)
        fixed = [0.20, 0.24] if n > 4 else [0.22, 0.28]
        lens = []
        for i in range(n - 2):
            cells = [len(t["columns"][i + 2])] + [len(r["cells"][i]) for r in t["rows"] if i < len(r["cells"])]
            lens.append(max(8, min(60, sorted(cells)[len(cells) // 2] if cells else 8)) + max(cells) / 6)
        # never narrower than the longest word of the header (bold, about 125 twips a character) or of a cell
        # (about 110 twips a character; a backslash is a break point; words over 18 characters may wrap)
        def word(texts: list[str]) -> int:
            """Twips of the widest word: capitals and digits about 125 each, other characters about 100; a word
            longer than 18 characters may wrap."""
            ws = [w[:18] for x in texts for w in re.split(r"[\s\\]+", x) if w]
            return max([sum(125 if (c.isupper() or c.isdigit()) else 100 for c in w) for w in ws] or [0])
        floor = [max(0.10, (max(len(w) for w in t["columns"][i + 2].split()) * 125 + 300) / total,
                     (word([r["cells"][i] for r in t["rows"] if i < len(r["cells"])]) + 300) / total)
                 for i in range(n - 2)]
        # Role and Hosts give up width (down to 15 % and 18 %) when the value columns need it
        over = sum(floor) - (1 - sum(fixed))
        if over > 0:
            give = [max(0.0, fixed[0] - 0.15), max(0.0, fixed[1] - 0.18)]
            take = min(over, sum(give))
            fixed = [f - take * g / sum(give) if sum(give) else f for f, g in zip(fixed, give)]
        rest = 1 - sum(fixed)
        share = [max(f, rest * x / sum(lens)) for f, x in zip(floor, lens)]
        scale = rest / sum(share)
        fracs = fixed + [x * scale for x in share]
    else:
        fracs = [0.4, 0.6]
    widths = [int(total * f) for f in fracs]
    widths[-1] += total - sum(widths)
    grid = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"
    out = [f"<w:tr>{head_pr}" + "".join(_cell(w, c, hs) for w, c in zip(widths, t["columns"])) + "</w:tr>"]
    role_no = -1
    for r in t["rows"]:
        if r["first"]:
            role_no += 1
        cont = [x for x in t["rows"] if x["role"] == r["role"]]
        merge = None if len(cont) == 1 else ("restart" if r["first"] else "continue")
        f = fill if fill and role_no % 2 == 0 else ""
        cells = [_cell(widths[0], r["role"] if r["first"] else "", ds, merge, f),
                 _cell(widths[1], ", ".join(r["hosts"]), ds, None, f)]
        cells += [_cell(w, v, ds, None, f) for w, v in zip(widths[2:], r["cells"])]
        out.append(f"<w:tr>{band[role_no % len(band)]}" + "".join(cells) + "</w:tr>")
    return f"<w:tbl>{tblpr}{grid}{''.join(out)}</w:tbl>"


def _note(text: str, style: str = "TableNote") -> str:
    run = f'<w:r><w:t xml:space="preserve">{_esc(text)}</w:t></w:r>' if text else ""
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{run}</w:p>'


def place_xml(xml: str, t, heading: str, styles_xml: str = "") -> tuple[str, str]:
    """(new document.xml, what happened). ``t`` is one table or a list of tables (role table, flows table).
    Replaces the framework-built tables and their note lines under the same heading; removes them when there is
    nothing to show. The Aspect table that follows is never touched."""
    tables = [x for x in (t if isinstance(t, list) else [t]) if x.get("status") == "OK" and x.get("rows")]
    loc = _locate(xml, heading)
    if not loc:
        raise ValueError(f"no 'Discovery Information' heading under '{heading}'")
    ins, fend, _lvl = loc
    blocks = _blocks(xml, ins, fend)
    ours_tbl = lambda k, b: k == "tbl" and f'w:tblCaption w:val="{CAPTION}"' in b
    is_note = lambda k, b: k == "p" and 'w:val="TableNote"' in b and not _heading_level(b)
    raw_tables = [(ins + m.start(), ins + m.end(), m.group(0)) for m in _TBL.finditer(xml[ins:fend])]
    reference_entry = next(((s, e, b) for s, e, b in raw_tables
                            if f'w:tblCaption w:val="{CAPTION}"' not in b), None)
    reference = reference_entry[2] if reference_entry else None
    if reference is None:
        reference = next((m.group(0) for m in _TBL.finditer(xml) if "CSATable" in m.group(0)), None) or ""

    # Requirement stories may now be the first paragraphs below Discovery Information. Previously the placer
    # only recognised a framework table when it was the first block, so a rerun inserted a second copy ahead of
    # the stories. Remove every framework table (and its generated notes) before the first ordinary table, then
    # place one fresh set after the leading SEP stories. Figures and all other content stay where they are.
    first_reference = next((i for i, (k, _s, _e, b) in enumerate(blocks)
                            if k == "tbl" and not ours_tbl(k, b)), len(blocks))
    replace_observation = any(x.get("replace_observation_table") for x in tables)
    remove = [(s, e) for i, (k, s, e, b) in enumerate(blocks)
              if ours_tbl(k, b) or (i < first_reference and is_note(k, b))]
    if replace_observation and reference_entry:
        remove.append(reference_entry[:2])
    replaced = any(ours_tbl(k, b) for k, _s, _e, b in blocks)
    clean = xml
    for s, e in reversed(remove):
        clean = clean[:s] + clean[e:]

    if not tables:
        return clean, "removed" if replaced else "nothing to place"

    clean_loc = _locate(clean, heading)
    if not clean_loc:
        raise ValueError(f"no 'Discovery Information' heading under '{heading}' after table refresh")
    clean_ins, clean_fend, _ = clean_loc
    insert_at = clean_ins
    story = re.compile(r"^SEP-[A-Z0-9-]+\s*(?:—|:|-)\s+", re.I)
    clean_blocks = _blocks(clean, clean_ins, clean_fend)
    story_ends: dict[str, int] = {}
    for kind, _s, e, b in clean_blocks:
        text = _text(b).strip() if kind == "p" else ""
        m = re.match(r"^(SEP-[A-Z0-9-]+)\s*(?:—|:|-)\s+", text, re.I)
        if m:
            story_ends[m.group(1).upper()] = e
    for kind, _s, e, b in clean_blocks:
        if kind == "p" and story.match(_text(b).strip()):
            insert_at = e
            continue
        break
    sid = (re.search(r'<w:tblStyle w:val="([^"]+)"', reference) or [None, ""])[1]

    def rendered(x: dict) -> str:
        lines = [y for y in [x.get("common", ""), *x.get("markers", [])] if y] or [""]
        return table_xml(x, reference, band_fill(styles_xml, sid)) + "".join(_note(y) for y in lines)

    insertions: dict[int, str] = {}
    for x in tables:
        pos = story_ends.get((x.get("requirement") or "").upper(), insert_at)
        insertions[pos] = insertions.get(pos, "") + rendered(x)
    for pos in sorted(insertions, reverse=True):
        clean = clean[:pos] + insertions[pos] + clean[pos:]
    return clean, "replaced" if replaced else "inserted"


def place(work_dir: Path, docx: Path, heading: str, key: str = "", backup: bool = True) -> dict:
    tables = build_all(work_dir, heading, key)
    t = tables[0]
    if t["status"] == "NO_PROFILE":
        return {"status": "SKIPPED", "message": f"no topic-table profile for '{heading}'"}
    from csa_docx.tables import _read_document_xml, _write_document_xml
    docx = Path(docx)
    xml = _read_document_xml(docx)
    with zipfile.ZipFile(docx) as z:
        styles = z.read("word/styles.xml").decode("utf-8") if "word/styles.xml" in z.namelist() else ""
    try:
        new, what = place_xml(xml, tables, heading, styles)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
    bak = None
    if new != xml:
        if backup:
            bak = docx.with_name(f"{docx.name}.before_topic_table_{datetime.now():%Y%m%d-%H%M%S}.bak")
            shutil.copy2(docx, bak)
        _write_document_xml(docx, new)
    if t["status"] == "OK":
        save(work_dir, t)
    from csa_docx.validator import validate_docx
    v = validate_docx(docx)
    return {"status": "OK", "action": what, "rows": len(t.get("rows", [])), "columns": t.get("columns", []),
            "tables": [{"requirement": x.get("requirement"), "columns": x.get("columns", []),
                        "rows": len(x.get("rows", []))} for x in tables if x.get("status") == "OK"],
            "gaps": [g["dr_id"] for g in t.get("gaps", [])], "unassigned": t.get("unassigned", []),
            "warnings": t.get("warnings", []), "backup": str(bak) if bak else None, "validation": v}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("build"); s.add_argument("--work-dir", type=Path, required=True)
    s.add_argument("--heading", required=True); s.add_argument("--key", default=""); s.add_argument("--json", action="store_true")
    s = sub.add_parser("place"); s.add_argument("--work-dir", type=Path, required=True)
    s.add_argument("--docx", type=Path, required=True); s.add_argument("--heading", required=True)
    s.add_argument("--key", default=""); s.add_argument("--no-backup", action="store_true")
    sub.add_parser("profiles")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        t = build(a.work_dir, a.heading, a.key)
        if a.json or t["status"] != "OK":
            print(json.dumps(t, indent=1, ensure_ascii=False))
        else:
            print(markdown(t))
            for g in t["gaps"]:
                print(f"\n{g['dr_id']}: {g['text']}", end="")
            if t["unassigned"]:
                print(f"\n\nIn scope but no role in hosts.csv (left out): {', '.join(t['unassigned'])}")
            print()
        return 0 if t["status"] in ("OK", "NO_PROFILE", "EMPTY") else 1
    if a.cmd == "place":
        out = place(a.work_dir, a.docx, a.heading, a.key, backup=not a.no_backup)
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0 if out["status"] in ("OK", "SKIPPED") else 1
    print(json.dumps([{k: p[k] for k in ("_file", "topic", "headings")} | {"columns": [c["label"] for c in p["columns"]]}
                      for p in profiles()], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
