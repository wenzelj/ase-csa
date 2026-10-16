"""Where does the CSA need a figure? One answer per section, read from the document and the evidence.

    assess(spec, work_dir, project_key) -> [{key, number, title, status, reason, profile, archetype, slot, ...}]

status: needed | helpful | not-useful | not-built | placed | none (containers and front matter)
Deterministic: no model, no section numbers. A section is matched to a figure profile
(csa-context/figure-profiles.json) by its requirement family or its key.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from csa_docx import doc_spec
from csa_docx.figures import relations as R

AGENTS = Path(__file__).resolve().parents[3]
PROFILES = AGENTS / "csa-context" / "figure-profiles.json"
LAYOUTS = AGENTS / "csa-context" / "system-diagrams.json"
ARCHETYPE = {"A": "system overview", "B": "service dependency", "C": "zones and conduits", "D": "access path",
             "E": "numbered flow", "F": "data flow"}
SERVICE_WORD = {"time": "time", "dns": "name resolution"}


def load_profiles() -> list[dict]:
    return json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]


def load_layout(project_key: str) -> dict:
    try:
        return json.loads(LAYOUTS.read_text(encoding="utf-8")).get(project_key) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def match(node: dict, profiles: list[dict]) -> dict | None:
    fams = set(doc_spec.families(node))
    for p in profiles:
        if node.get("key") in p.get("keys", []) or fams & set(p.get("families", [])):
            return p
    return None


def _requirements(node: dict) -> list[dict]:
    return [r for p in node["parts"] if p["kind"] == "requirement" for r in p.get("requirements", [])]


def _text(node: dict) -> str:
    return json.dumps(node["parts"], ensure_ascii=False)


def vital_hosts(ev: dict) -> set[str]:
    """Hosts that belong to the assessed system (the register's system column), never peers."""
    return {h for h, r in ev["register"].items() if (r.get("system") or "").strip() and (r.get("in_scope") or "") != "peer"}


def scope_relations(service: str, ev: dict, layout: dict, rel: dict | None = None) -> list[dict]:
    rows = (rel or R.relations(Path("."), [service], ev=ev)).get(service, [])
    vital = vital_hosts(ev)
    out = []
    for r in rows:
        if r["consumer"] not in vital:
            continue
        side, why = R.residency(r["provider"], ev, layout)
        out.append({**r, "side": side, "side_reason": why})
    return out


def _lc(q: str) -> str:
    """Lower-case the first letter only, so acronyms (OT, IT, DNS) keep their case."""
    return q[:1].lower() + q[1:] if q and not q[:2].isupper() else q


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def _who(rows: list[dict]) -> str:
    by: dict[str, set] = {}
    for r in rows:
        if r["state"] == "active":
            by.setdefault(r["provider"], set()).add(r["consumer"])
    parts = [f"{len(c)} from {p}" for p, c in sorted(by.items(), key=lambda kv: -len(kv[1]))]
    return "; ".join(parts[:4]) + ("; …" if len(parts) > 4 else "")


def assess(spec: dict, work_dir: Path, project_key: str, ev: dict | None = None) -> list[dict]:
    profiles = load_profiles()
    layout = load_layout(project_key)
    ev = ev or R.load(work_dir)
    rel = R.relations(work_dir, ev=ev)
    names = set(ev["register"])
    out = []
    for n in spec["nodes"]:
        reqs = _requirements(n)
        ids = [r["id"] for r in reqs]
        text = _text(n)
        hosts = sorted(h for h in names if re.search(rf"\b{re.escape(h)}\b", text))
        slot = n.get("figures") or []
        row = {"key": n["key"], "number": n.get("number") or "", "title": n["title"], "level": n["level"],
               "kind": n["kind"], "requirements": [{"id": r["id"], "text": r["text"], "current_state": r["current_state"],
                                                    "rating": r["rating"]} for r in reqs],
               "hosts_in_text": hosts, "slot": slot[0] if slot else None, "profile": None, "archetype": None}
        p = match(n, profiles)
        if p is not None and p.get("archetype") != "none":
            row.update(profile=p["id"], archetype=p["archetype"], question=p.get("question"), must_show=p.get("must_show", []),
                       caption=p.get("caption"))
        if any(f.get("image") for f in slot):
            row.update(status="placed", reason="A figure is already in the document here.")
        elif p is None:
            if n["kind"] in ("container", "empty", "reference", "controlled") or n["level"] == 1 and not reqs:
                row.update(status="none", reason="")
            elif n["kind"] == "register":
                row.update(status="not-useful", reason="A register: a table lists these better than a figure.")
            else:
                row.update(status="not-useful", reason="No figure profile matches what this section asks.")
        elif p.get("archetype") == "none":
            row.update(status="not-useful", profile=p["id"], reason=f"{', '.join(ids) or 'This section'}: {p.get('why', '')}.")
        else:
            row.update(profile=p["id"], archetype=p["archetype"], question=p.get("question"), must_show=p.get("must_show", []),
                       caption=p.get("caption"))
            ask = f"{', '.join(ids)} ask{'s' if len(ids) == 1 else ''}" if ids else "This section asks"
            if not p.get("built"):
                row.update(status="not-built", reason=f"{ask}: {_lc(p['question'])}. {_a(ARCHETYPE[p['archetype']]).capitalize()} "
                                                      f"figure fits, but drawing that kind is not built yet.")
            elif p["archetype"] == "A":
                row.update(status="needed", reason="The document has a figure slot here for the system overview."
                           if slot else "An overview helps the reader see the whole system.")
            elif p["archetype"] in ("C", "D", "F"):
                row.update(status="needed", reason=f"{ask}: {_lc(p['question'])}. {_a(ARCHETYPE[p['archetype']]).capitalize()} "
                                                   "figure answers it, drawn from the captured connections.")
            else:
                rows = scope_relations(p["service"], ev, layout, rel)
                active = [r for r in rows if r["state"] == "active"]
                crossing = [r for r in active if r["side"] != "ot"]
                consumers = {r["consumer"] for r in active}
                row["relations"] = len(rows)
                if len(active) >= 2 or crossing:
                    word = SERVICE_WORD.get(p["service"], p["service"])
                    side = (f" {len({r['consumer'] for r in crossing})} of them rely on IT or unnamed providers."
                            if crossing else "")
                    row.update(status="needed", reason=f"{ask}: {_lc(p['question'])}. Evidence: {len(consumers)} "
                                                       f"vital hosts take {word} ({_who(active)}).{side}")
                else:
                    row.update(status="helpful", reason=f"{ask}: {_lc(p['question'])}. The evidence names no "
                                                        f"provider yet, so the figure would show the gap.")
        out.append(row)
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Where the CSA needs a figure")
    ap.add_argument("docx"); ap.add_argument("--work-dir", required=True); ap.add_argument("--project", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = assess(doc_spec.read(a.docx), Path(a.work_dir), a.project)
    if a.json:
        print(json.dumps(rows, indent=1)); return 0
    for r in rows:
        if r["status"] != "none":
            print(f"{r['number']:>5} {r['title'][:44]:44} {r['status']:10} {r['reason'][:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
