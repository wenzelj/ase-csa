"""Topic analysis frames: work through a section topic before the agent writes.

A frame (references/topic-frames/*.json, matched by heading text) turns a topic's "Must explain" and the
OT guidance tests into slots: explicit sub-questions, each fed by an inventory slice (host settings or data
flows). The framework fills every slot it can from the captures, makes each finding citable (one evidence
matrix row per finding, quoting the capture lines; a NOT_FOUND row for what was searched and not found),
and puts the frame on the section card. The agent must answer every slot in a `## F1 Analysis frame`
block: the B blocks that answer it, or an Unknown: line (FRAME_UNCOVERED otherwise).

"Likely" notes come from references/signal-signatures.json: what a process usually is and what to
confirm. They are background, never evidence.

    python3 -m csa_docx.topic_frames build --workspace <project root> --heading "Storage & Data Transfer" [--key STOR] [--no-evidence]
    python3 -m csa_docx.topic_frames show  --workspace <project root> --heading "Storage & Data Transfer"
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

from csa_docx import flows as flows_mod
from csa_docx import host_settings

FRAMES = Path(__file__).resolve().parents[2] / "references" / "topic-frames"
MATRIX_SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "csa-evidence-matrix" / "scripts" / "evidence_matrix.py"
MAX_HOSTS_PER_ROW = 6
LABELS = {"storage.database": "Database service", "storage.shares": "Shares", "transfer.tools": "File transfer tools installed",
          "transfer.removable": "Removable storage policy", "transfer.proxy": "Proxy setting",
          "agent.edr": "Endpoint detection and response", "agent.antivirus": "Antivirus", "agent.log_forwarding": "Log forwarding",
          "agent.monitoring": "Monitoring agent", "agent.security_telemetry": "Workload security telemetry",
          "agent.backup": "Backup agent", "agent.backup_account": "Backup service account",
          "agent.patch_management": "Patch and configuration management client",
          "agent.vulnerability_scanner": "Vulnerability scanning agent", "agent.application_control": "Application control service",
          "appcontrol.policy": "Application control policy", "agent.remote_support": "Remote support or remote control software",
          "agent.virtualisation_tools": "Virtualisation guest tools",
          "identity.domain": "Domain membership", "identity.kdc": "Domain controller that issued the Kerberos tickets",
          "identity.kerberos": "Kerberos ticket encryption", "identity.local_users": "Enabled local accounts",
          "identity.service_accounts": "Service logon accounts (not built-in)",
          "admin.local_admins": "Local Administrators members", "admin.rdp_users": "Remote Desktop Users members",
          "admin.listeners": "Remote administration listeners",
          "platform.os": "Operating system", "platform.support": "Microsoft extended support",
          "platform.hardware": "Platform", "patch.latest": "Latest installed update",
          "patch.source": "Update source", "patch.auto": "Automatic Updates setting", "patch.client": "Patch client",
          "admin.rdp_port": "Port the Remote Desktop service listens on", "net.address": "IPv4 address",
          "net.zone": "Zone (project zone list)", "net.gateway": "Default gateway", "fw.profiles": "Host firewall",
          "fw.custom_inbound": "Inbound allow rules that are not stock Windows rules",
          "fw.exposed": "Services listening on every interface",
          "time.source": "Time source", "time.service": "Time service", "time.stratum": "Host stratum",
          "time.source_stratum": "Source stratum", "time.fallback": "Fallback time peer", "time.poll": "Time poll interval",
          "dns.primary": "Primary DNS server", "dns.secondary": "Secondary DNS server"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower().replace("&", " and ")).strip()


def frame_for(heading: str) -> dict | None:
    want = _norm(re.sub(r"^\d+(\.\d+)*\s+", "", heading or ""))
    for f in sorted(FRAMES.glob("*.json")):
        try:
            fr = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if want in {_norm(h) for h in fr.get("headings", [])}:
            fr["_file"] = f.name
            return fr
    return None


def _fit(lines: list[str], limit: int = 1150) -> str:
    """Quoted capture lines joined with ' | ', keeping whole lines while they fit the evidence matrix limit
    (every line kept is still an exact line of a cited file)."""
    out, n = [], 0
    for l in lines:
        if out and n + len(l) + 3 > limit:
            break
        out.append(l[:limit])
        n += len(l) + 3
    return " | ".join(out)


def _join(xs: list[str]) -> str:
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


def _register(work_dir: Path) -> dict[str, dict]:
    f = Path(work_dir) / "hosts" / "hosts.csv"
    return {r["host"].upper(): r for r in csv.DictReader(f.open(encoding="utf-8"))} if f.is_file() else {}


def _src_title(cites: list[str]) -> str:
    """'folder: file; folder2: file' from 'folder/file line N' or 'folder: file line N' citations (one file name)."""
    out = []
    for c in cites:
        c = re.sub(r"\s+line\s+\d+$", "", c.strip())
        folder, _, fname = c.replace(": ", "/").partition("/")
        out.append(f"{folder}: {fname}")
    return "; ".join(dict.fromkeys(out))


def _chunks(xs: list, n: int) -> list[list]:
    return [xs[i:i + n] for i in range(0, len(xs), n)] or [[]]


def settings_findings(work_dir: Path, attr: str, req: str, area: str, section: str) -> list[dict]:
    """One finding per (value, capture file) of a host setting, hosts grouped; absences become NOT_FOUND rows."""
    data = host_settings.load(work_dir)
    reg = _register(work_dir)
    groups: dict[tuple, list[tuple[str, dict]]] = {}
    for h, attrs in data.items():
        r = attrs.get(attr)
        if not r:
            continue
        fname = re.sub(r"\s+line\s+\d+$", "", r["source"]).rsplit("/", 1)[-1]
        groups.setdefault((r["value"], fname, bool(r["excerpt"])), []).append((h, r))
    out = []
    label = LABELS.get(attr, attr)
    for (value, fname, quoted), members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][0])):
        members.sort(key=lambda x: x[0])
        hosts = [h for h, _ in members]
        roles = list(dict.fromkeys((reg.get(h) or {}).get("role", "") for h in hosts if (reg.get(h) or {}).get("role")))
        text = f"{label} on {_join(hosts)}: {value}"
        ev = []
        for part in _chunks(members, MAX_HOSTS_PER_ROW):
            ph = [h for h, _ in part]
            if quoted:
                ev.append({"csa_area": area, "question": f"{req}: {label.lower()} on {', '.join(ph)}",
                           "claim": f"{label} on {_join(ph)}: {value}", "status": "VERIFIED",
                           "source_title": _src_title([r["source"] for _, r in part]), "source_version": "",
                           "section": section, "page_or_location": f"{fname}", "confidence": "high",
                           "evidence_excerpt": _fit(list(dict.fromkeys(x for _, r in part for x in r["excerpt"].split(" | ")))),
                           "inference_reason": "", "gap_or_action": ""})
            else:
                ev.append({"csa_area": area, "question": f"{req}: {label.lower()} on {', '.join(ph)}",
                           "claim": f"{label} on {_join(ph)}: {value} (searched {fname})", "status": "NOT_FOUND",
                           "source_title": f"searched: {fname} in the captures of {', '.join(ph)}", "source_version": "",
                           "section": section, "page_or_location": "", "confidence": "medium", "evidence_excerpt": "",
                           "inference_reason": "",
                           "gap_or_action": f"confirm the {label.lower()} on {', '.join(ph)} with the system owner (nothing in {fname})"})
        out.append({"text": text, "hosts": hosts, "roles": roles, "evidence": ev, "hint": "", "tokens": hosts,
                    "value": value})
    return out


# which way a flow crosses the OT boundary, worked out from the side that opens it and the way its data goes
DIRECTION_LABEL = {"ot_push": "OT push", "pull_into_ot": "Pull out of OT", "into_ot": "Into OT",
                   "inside_ot": "Inside OT", "unknown_zone": "Zone not recorded", "not_ot": "Outside OT, context only"}
CROSSING = ("ot_push", "pull_into_ot", "into_ot", "unknown_zone")


def flow_direction(g: dict, side) -> tuple[str, bool]:
    """(direction, far_end_unknown) for a flow group. ``side`` is flows.ot_sides(work_dir).
    ot_push: OT opens and data leaves OT. pull_into_ot: a system outside OT opens and data leaves OT (a backup
    server pulling, a database client reading). into_ot: data comes into OT. inside_ot: both ends in OT.
    not_ot: neither end is in OT (IT to the internet): context, never an OT push. unknown_zone: no end is known
    to be in OT and at least one end has no zone recorded."""
    from csa_docx.figures.flowview import DATA_DIRECTION

    def one(ends: list[str]) -> str:
        ss = {side(p.strip()) for e in ends for p in e.split(",") if p.strip()}
        if ss == {"ot"}:
            return "ot"
        if "ot" in ss:
            return "mixed"
        return "outside" if ss == {"outside"} else "unknown"
    s, t = one(g["srcs"]), one(g["dsts"])
    if s in ("ot", "mixed") and t in ("ot", "mixed"):
        return "inside_ot", "mixed" in (s, t)
    if s not in ("ot", "mixed") and t not in ("ot", "mixed"):
        return ("not_ot", False) if (s, t) == ("outside", "outside") else ("unknown_zone", True)
    d = DATA_DIRECTION.get(g["mechanism"], "both")
    if s in ("ot", "mixed"):                       # OT opens the connection
        return ("ot_push" if d in ("from_opener", "both") else "into_ot"), t != "outside"
    return ("pull_into_ot" if d in ("to_opener", "both") else "into_ot"), s != "outside"


def flow_findings(work_dir: Path, flt: dict, req: str, area: str, section: str) -> list[dict]:
    rows = flows_mod.select(flows_mod.load(work_dir), flt, {h.upper() for h in _register(work_dir)})
    side = flows_mod.ot_sides(work_dir)
    # group within one pair of sides only: a client in OT and a client outside OT of the same listener are two findings
    parts: dict[tuple, list[dict]] = {}
    for r in rows:
        k = tuple(sorted({side(x.strip()) for x in r["src"].split(",") if x.strip()})),             tuple(sorted({side(x.strip()) for x in r["dst"].split(",") if x.strip()}))
        parts.setdefault(k, []).append(r)
    grouped = [g for rs in parts.values() for g in flows_mod.groups(rs)]
    out = []
    for g in grouped:
        zones = f"{'/'.join(g['src_zones']) or 'zone not recorded'} to {'/'.join(g['dst_zones']) or 'zone not recorded'}"
        port = f"TCP {g['port']}" if str(g["port"]).isdigit() else f"ports {g['port']}"
        if g["status"] == "declared":
            text = (f"Declared in the flow map as {g['declared_id']} ({g['declared_flow']}, {port}): {_join(g['srcs'])} to "
                    f"{_join(g['dsts'])} ({zones}). No matching connection appeared in the sampled process connections.")
            f0 = g["flows"][0]
            ev = [{"csa_area": area, "question": f"{req}: declared flow {g['declared_id']}",
                   "claim": f"The expected flow map declares {g['declared_id']}: {g['declared_flow']} from {g['srcs'][0]} to {g['dsts'][0]}, {port}",
                   "status": "VERIFIED", "source_title": f0["sources"], "source_version": "", "section": section,
                   "page_or_location": "expected flow map", "evidence_excerpt": f0["excerpt"], "confidence": "high",
                   "inference_reason": "", "gap_or_action": ""},
                  {"csa_area": area, "question": f"{req}: is declared flow {g['declared_id']} seen in the captures?",
                   "claim": f"No connection matching declared flow {g['declared_id']} ({_join(g['srcs'])} to {_join(g['dsts'])}, {port}) "
                            f"appeared in the sampled process connection captures",
                   "status": "NOT_FOUND", "source_title": "searched: 23_process_connection_mapping.txt in the captures of the hosts named",
                   "source_version": "", "section": section, "page_or_location": "", "evidence_excerpt": "",
                   "confidence": "medium", "inference_reason": "",
                   "gap_or_action": f"confirm with the system owner whether declared flow {g['declared_id']} runs; the connection "
                                    f"captures are samples and may have missed it"}]
        else:
            seen = "declared in the flow map as " + g["declared_id"] if g["status"] == "both" else "not in the flow map"
            proc = f" ({g['process']})" if g["process"] else ""
            tried = g["status"] == "attempted"
            verb = ("attempt" if len(g["srcs"]) > 1 else "attempts") if tried else ("open" if len(g["srcs"]) > 1 else "opens")
            if tried:
                seen += ", and only a connection request (SYN_SENT) was seen, with no reply"
            mech = g["mechanism"][:1].upper() + g["mechanism"][1:]
            text = (f"{mech}{proc}, {port}: {_join(g['srcs'])} {verb} connections to {_join(g['dsts'])} "
                    f"({zones}{', crosses zones' if g['cross_zone'] == 'yes' else ''}); {seen}.")
            ev = []
            for part in _chunks(g["flows"], MAX_HOSTS_PER_ROW):
                cites = [f["sources"].split("; ")[0] for f in part if f["sources"]]     # the capture each excerpt line is from
                ev.append({"csa_area": area, "question": f"{req}: {g['mechanism']} connections on {port}",
                           "claim": f"{_join(list(dict.fromkeys(f['src'] for f in part)))} "
                                    f"{'attempted (SYN_SENT, no reply seen)' if tried else 'opened'} {g['mechanism']} connections on {port} "
                                    f"to {_join(list(dict.fromkeys(f['dst'] for f in part)))}{proc}",
                           "status": "VERIFIED", "source_title": _src_title(cites), "source_version": "", "section": section,
                           "page_or_location": re.sub(r"\s+line\s+\d+$", "", cites[0]).split(": ")[-1] if cites else "",
                           "evidence_excerpt": _fit(list(dict.fromkeys(f["excerpt"] for f in part))),
                           "confidence": "high", "inference_reason": "", "gap_or_action": ""})
        hint = f"Likely: {g['signature']}. Confirm {g['confirm']}." if g["signature"] else ""
        toks = [x for x in g["srcs"] + g["dsts"]]
        direction, far_unknown = flow_direction(g, side)
        text = f"[{DIRECTION_LABEL[direction]}] {text}"
        if far_unknown and direction in CROSSING:
            text += " The zone of the far end is not recorded: say so and raise it as Unknown."
        out.append({"text": text, "hosts": g["srcs"] + g["dsts"], "evidence": ev, "hint": hint, "tokens": toks,
                    "cross_zone": g["cross_zone"], "mechanism": g["mechanism"], "status": g["status"],
                    "direction": direction, "far_unknown": far_unknown})
    order = {"pull_into_ot": 0, "ot_push": 1, "into_ot": 2, "unknown_zone": 3, "inside_ot": 4, "not_ot": 5}
    out.sort(key=lambda f: order.get(f["direction"], 9))     # stable: crossings first, context last
    return out


def build(workspace: Path, heading: str, key: str = "", evidence: bool = True) -> dict:
    """The filled frame for ``heading``: {"status", "key", "slots": [{id, question, requirements, findings}]}."""
    workspace = Path(workspace)
    work = workspace / "csa-work"
    fr = frame_for(heading)
    if not fr:
        return {"status": "NO_FRAME", "heading": heading}
    key = key or fr.get("key", "")
    area, section = fr.get("area", "storage_and_data_transfer"), fr.get("section", heading.lower())
    slots = []
    for s in fr["slots"]:
        req = ", ".join(s.get("requirements", [])) or key
        src = s.get("source", {})
        found = []
        for attr in src.get("settings", []):
            found += settings_findings(work, attr, req, area, section)
        if "flows" in src:
            found += flow_findings(work, src["flows"], req, area, section)
        bind_requirements(s, found)
        slots.append({"id": s["id"], "question": s["question"], "requirements": s.get("requirements", []),
                      "findings": found, "cross_zone": bool(src.get("flows", {}).get("cross_zone"))})
    res = {"status": "OK", "key": key, "heading": heading, "frame": fr.get("_file", ""), "slots": slots,
           "strict": bool(fr.get("strict")), "zone_conflicts": zone_conflicts(work)}
    if evidence:
        _ensure_evidence(workspace, res)
    out = work / "topic-frames"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{key or 'frame'}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return res


def _ensure_evidence(workspace: Path, res: dict) -> None:
    """Append every finding's rows to the evidence matrix (duplicates come back as their existing IDs). A finding
    that feeds two slots is sent once; rows are matched back on the full claim."""
    items = list({e["claim"]: e for s in res["slots"] for f in s["findings"] for e in f["evidence"]}.values())
    if not items:
        return
    ids: dict[str, str] = {}

    def run(rows: list[dict]) -> dict:
        proc = subprocess.run([sys.executable, str(MATRIX_SCRIPT), "--workspace", str(workspace), "append",
                               "--agent", "csa topic-frame", "--context", f"topic frame {res['key']}", "--allow-new-area",
                               "--rows-file", "-"], input=json.dumps(rows, ensure_ascii=False), capture_output=True, text=True)
        try:
            out = json.loads(proc.stdout or "{}")
        except ValueError:
            out = {}
        # the script reports each accepted row, in order, as written or as a duplicate, with the claim cut to
        # 100 characters: walk the rows in order so two claims that share their first 100 characters stay apart
        written, skipped = list(out.get("written", [])), list(out.get("skipped_duplicates", []))
        for e in rows:
            head = e["claim"][:100]
            if written and written[0]["claim"] == head:
                ids[e["claim"]] = written.pop(0)["evidence_id"]
            elif skipped and skipped[0]["claim"] == head:
                d = skipped.pop(0)
                if str(d.get("duplicate_of", "")).startswith("E-"):
                    ids.setdefault(e["claim"], d["duplicate_of"])
        return out

    out = run(items)
    res["evidence_status"] = out.get("status") or ("ERROR" if out.get("rejected") else "OK")
    if out.get("rejected"):
        # a row the source check refused: keep the finding, without a citable ID, and say why
        res["evidence_rejected"] = out["rejected"][:20]
        bad = {(r.get("claim") or "")[:100] for r in out["rejected"]}       # the script reports claims cut to 100
        good = [e for e in items if e["claim"][:100] not in bad]
        if good and len(good) < len(items):
            run(good)
    for s in res["slots"]:
        for f in s["findings"]:
            f["ids"] = list(dict.fromkeys(ids[e["claim"]] for e in f["evidence"] if ids.get(e["claim"])))


def zone_conflicts(work_dir: Path) -> list[dict]:
    """Hosts whose role name says OT (or IT) while the zone list puts them on the other side: [{host, role, zone,
    side, text}]. The zone list wins: the text says how to write about the host."""
    from csa_docx import zones as Z
    zs = Z.for_project(work_dir)
    out = []
    for h, r in sorted(_register(work_dir).items()):
        role = (r.get("role") or "").strip()
        if not role or (r.get("in_scope") or "").strip() == "peer":
            continue
        words = set(re.findall(r"\b(OT|IT)\b", role))
        z = zs.of(r.get("host") or h)
        kind = z.get("kind", "unknown")
        if "OT" in words and kind in ("it", "internet", "cloud", "vendor"):
            side, said = "IT", "OT"
        elif "IT" in words and kind == "ot":
            side, said = "OT", "IT"
        else:
            continue
        host = r.get("host") or h
        out.append({"host": host, "role": role, "zone": z.get("zone", ""), "side": side,
                    "text": f"{host} ({role}) is in {z.get('zone', '')}, an {side} zone, although its role name says {said}: "
                            f"write about it as {side}-hosted. Never call it {said}-resident or say it is in {said}."})
    return out


def bind_requirements(slot: dict, findings: list[dict]) -> None:
    """Give each finding the requirements its answer must address. A flow takes the slot's "bind" entry for its
    direction (e.g. a pull out of OT binds to the outward-only requirement), else the slot's requirements. A flow
    with no OT end, and a setting whose value is one of the slot's "baseline_values" (None found, default shares
    only), binds to none: it is context, shown on the card but owed by no requirement."""
    base = {v.lower() for v in slot.get("baseline_values", [])}
    bind = slot.get("bind", {})
    for f in findings:
        if f.get("direction") == "not_ot" or (f.get("value") or "").lower() in base:
            f["requirements"] = []
        elif f.get("direction"):
            f["requirements"] = list(bind.get(f["direction"], slot.get("requirements", [])))
        else:
            f["requirements"] = list(slot.get("requirements", []))


def must_address(res: dict | None) -> dict[str, list[dict]]:
    """{requirement ID: [{slot, text, ids, direction, tokens, empty}]}: what each requirement's answer must cite, or
    raise as Unknown. A slot the captures do not answer asks each of its requirements for an Unknown: line (empty)."""
    out: dict[str, list[dict]] = {}
    for s in (res or {}).get("slots", []):
        if not s["findings"]:
            for r in s.get("requirements", []):
                out.setdefault(r, []).append({"slot": s["id"], "text": s["question"], "ids": [], "direction": "",
                                              "tokens": [], "empty": True})
            continue
        for f in s["findings"]:
            for r in f.get("requirements", []):
                items = out.setdefault(r, [])
                if not any(x["slot"] == s["id"] and x["text"] == f["text"] for x in items):
                    items.append({"slot": s["id"], "text": f["text"], "ids": list(f.get("ids", [])),
                                  "direction": f.get("direction", ""), "tokens": list(f.get("tokens", [])), "empty": False})
    return out


def scope_conflicts(res: dict | None, not_here: str) -> list[str]:
    """Card lines for a scope "Not here" clause that sends elsewhere a mechanism this section's own requirements owe
    (backup storage goes to 3.11, while the backup agent pulling data out of OT answers SEP-STOR-03 here)."""
    clauses = [c.strip() for c in re.split(r";|\.(?=\s|$)", (not_here or "").lower()) if re.search(r"\bgo(?:es)? to\b", c)]
    out, seen = [], set()
    for s in (res or {}).get("slots", []):
        for f in s["findings"]:
            mech = (f.get("mechanism") or "").lower()
            word = mech.split()[0] if mech else ""
            if not f.get("requirements") or not word or mech in seen:
                continue
            hit = next((c for c in clauses if re.search(rf"\b{re.escape(word)}", c)), None)
            if hit:
                seen.add(mech)
                out.append(f"Scope note: \"{hit}\" does not cover the {mech} flows this section's requirements owe "
                           f"({', '.join(f['requirements'])}): answer them here.")
    return out


def row_disagreements(res: dict | None, rows: list[dict]) -> list[str]:
    """Card lines for an evidence row that says there is none of a kind of traffic ("no flow moves operational data
    by file or share transfer") while the frame found connections of that kind. Both are shown; the answer states
    the difference and does not cite the row as proof that none exist."""
    mechs: dict[str, list[str]] = {}
    for s in (res or {}).get("slots", []):
        for f in s["findings"]:
            m = (f.get("mechanism") or "").lower()
            if m and f.get("requirements") and f.get("ids"):
                mechs.setdefault(m, []).extend(f["ids"])
    out, seen = [], set()
    for r in rows:
        claim = r.get("claim", "")
        for m, ids in mechs.items():
            words = [w for w in re.findall(r"[a-z]{4,}", m) if w not in ("connection", "connections")]
            if r["id"] in seen or not words:
                continue
            if re.search(r"\bno\b[^.;]{0,100}\b(?:" + "|".join(map(re.escape, words)) + r")\b", claim, re.I):
                seen.add(r["id"])
                out.append(f"Rows disagree: {r['id']} says \"{claim[:150]}\", yet the frame found {m} connections "
                           f"({', '.join(sorted(set(ids))[:3])}). State both; do not cite {r['id']} as showing there are none.")
    return out


def all_ids(res: dict | None) -> set[str]:
    return {i for s in (res or {}).get("slots", []) for f in s["findings"] for i in f.get("ids", [])}


def card_lines(res: dict) -> list[str]:
    out = ["", "## Analysis frame (built by the framework from the captures)", "",
           "Work through this topic slot by slot before you write. Each finding below is citable by its evidence IDs. "
           "A 'Likely' note is background, not evidence: never state it as a fact, write what it asks you to confirm as an "
           "Unknown: line. Answer every slot in one extra block at the end of the sheet:", "",
           "    ## F1 Analysis frame", "    - S1: B1, B4", "    - S9: Unknown: how long the recordings are kept", "",
           "List the blocks whose text answers the slot, or write Unknown: with what is not known (it becomes Discovery "
           "Required). Every slot needs a line (FRAME_UNCOVERED). Cross-zone data flows must be addressed in a requirement "
           "or the Drawbridge Impact (FLOW_NOT_COVERED).", ""]
    if res.get("zone_conflicts"):
        out += ["Zone conflicts (the zone list wins over the role name; ZONE_CONTRADICTED):"]
        out += [f"- {c['text']}" for c in res["zone_conflicts"]] + [""]
    for s in res["slots"]:
        reqs = f" ({', '.join(s['requirements'])})" if s["requirements"] else ""
        out.append(f"### {s['id']} {s['question']}{reqs}")
        if not s["findings"]:
            out.append("- nothing in the captures answers this: answer from the evidence pack or write Unknown:")
        for f in s["findings"][:25]:
            ids = f" ({', '.join(f.get('ids', []))})" if f.get("ids") else " (no citable row: state it only with other evidence)"
            out.append(f"- {f['text']}{ids}")
            if f.get("hint"):
                out.append(f"  {f['hint']}")
        if len(s["findings"]) > 25:
            out.append(f"- {len(s['findings']) - 25} more in csa-work/topic-frames/{res['key']}.json")
        out.append("")
    return out


def coverage_targets(res: dict | None) -> list[dict]:
    """Data flows that cross the OT boundary (or may: far end with no zone) the answer must address:
    [{text, tokens, ids, direction}]. A flow with no OT end (IT to the internet) is context, never a target."""
    out, seen = [], set()
    for s in (res or {}).get("slots", []):
        for f in s["findings"]:
            if f.get("direction") in CROSSING and f["text"] not in seen:
                seen.add(f["text"])
                out.append({"text": f["text"], "tokens": f.get("tokens", []), "ids": f.get("ids", []),
                            "direction": f["direction"]})
    return out


def context_ids(res: dict | None) -> list[str]:
    """Evidence IDs of flows with no OT end: context for an OT section, never an OT push or pull."""
    return sorted({i for s in (res or {}).get("slots", []) for f in s["findings"] if f.get("direction") == "not_ot"
                   for i in f.get("ids", [])})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "show"):
        s = sub.add_parser(name); s.add_argument("--workspace", type=Path, required=True); s.add_argument("--heading", required=True)
        s.add_argument("--key", default="")
        if name == "build":
            s.add_argument("--no-evidence", action="store_true")
    a = ap.parse_args(argv)
    res = build(a.workspace, a.heading, a.key, evidence=not getattr(a, "no_evidence", False))
    if a.cmd == "show" or res["status"] != "OK":
        print("\n".join(card_lines(res)) if res["status"] == "OK" else json.dumps(res))
    else:
        print(json.dumps({"status": "OK", "key": res["key"], "slots": len(res["slots"]),
                          "findings": sum(len(s["findings"]) for s in res["slots"]), "evidence_ids": len(all_ids(res)),
                          "evidence_status": res.get("evidence_status"), "rejected": res.get("evidence_rejected", [])[:5]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
