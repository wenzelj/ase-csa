"""Estate view: the enterprise DNS and time servers that several CSA projects' hosts share.

An *estate* is the set of projects whose hosts sit in one enterprise domain (``estate:`` in
PROJECTS.yaml, e.g. ``internal.qr.com.au``). It is not a system: an estate member's hosts are never
this project's hosts, and its evidence is context for another member, never that member's current
state (answer_sheet CROSS_PROJECT_ONLY).

``build(estate)`` reads every member's ``hosts/host_services.csv`` (hostmodel) and writes, under
``$CSA_ESTATES_DIR/<estate>/`` (default ``.agents/csa-context/estates/<estate>/``):

* ``servers.csv``   one row per server: one identity across projects (the short host name; an
                    address one member leaves unnamed takes the name another gives it; an address
                    named differently by two members is kept as two servers and reported in
                    ``conflicts``, never merged). ``shared`` = yes when two or more members use it.
* ``services.csv``  one row per server, service and member: client hosts, preference counts and
                    the member's own evidence rows as ``<project>:E-nnn``.

Derived and rebuilt on every ``csa ingest``; never evidence itself. Standard library only.

    python3 -m csa_docx.estate build|list|show [SERVER] --project KEY [--json]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2]
SERVICES = ("dns", "time")
POSITION = {1: "primary", 2: "secondary", 3: "tertiary"}
QUESTION = {"dns": re.compile(r"^Which DNS servers is (\S+) configured to use\?$"),
            "time": re.compile(r"^Which time source does (\S+) synchronise from\?$")}
SERVER_COLS = ["server", "fqdn", "ips", "services", "projects", "shared", "conflicts"]
SERVICE_COLS = ["server", "service", "project", "clients", "client_hosts", "preference", "evidence_ids"]
# ---------------------------------------------------------------- registry

def _registry() -> list[dict]:
    """Projects in $CSA_PROJECTS_FILE (else csa-context/PROJECTS.yaml), read like hostmodel._project_work_dir."""
    reg = Path(os.environ["CSA_PROJECTS_FILE"]) if os.environ.get("CSA_PROJECTS_FILE") \
        else AGENTS / "csa-context" / "PROJECTS.yaml"
    if not reg.is_file():
        return []
    out, cur = [], None
    for line in reg.read_text(encoding="utf-8").splitlines():
        st = line.strip()
        if not st or st.startswith("#"):
            continue
        if st.startswith("- key:"):
            cur = {}
            out.append(cur)
            st = st[2:]
        if cur is not None and ":" in st:
            k, _, v = st.partition(":")
            cur[k.strip()] = v.strip().strip('"').strip("'")
    return [p for p in out if p.get("key")]


def _project(key: str) -> dict | None:
    return next((p for p in _registry() if p["key"] == key), None)


def estate_of(key: str) -> str | None:
    p = _project(key)
    return (p or {}).get("estate") or None


def label_of(key: str) -> str:
    p = _project(key)
    return (p or {}).get("label") or key


def members(key: str) -> list[tuple[str, Path]]:
    """(key, work_dir) of every project in the same estate as ``key``, in registry order (``key`` included)."""
    est = estate_of(key)
    if not est:
        return []
    return [(p["key"], Path(p["work_dir"])) for p in _registry() if p.get("estate") == est and p.get("work_dir")]


def estate_members(estate: str) -> list[tuple[str, Path]]:
    return [(p["key"], Path(p["work_dir"])) for p in _registry() if p.get("estate") == estate and p.get("work_dir")]


def estate_dir(estate: str) -> Path:
    base = Path(os.environ["CSA_ESTATES_DIR"]) if os.environ.get("CSA_ESTATES_DIR") \
        else AGENTS / "csa-context" / "estates"
    return base / estate


def key_for_work_dir(work_dir) -> str | None:
    """The registry key of the project whose work_dir is ``work_dir``."""
    try:
        want = Path(work_dir).resolve()
    except OSError:
        return None
    for p in _registry():
        try:
            if p.get("work_dir") and Path(p["work_dir"]).resolve() == want:
                return p["key"]
        except OSError:
            continue
    return None


def citable_projects(work_dir) -> dict[str, Path]:
    """{project key: work_dir} of the other projects whose evidence this project may cite as <key>:E-nnn: the
    members of its estate (context only) and its system siblings (hosts/roles.csv kind=system_project)."""
    out: dict[str, Path] = {}
    own = key_for_work_dir(work_dir)
    if own:
        for k, wd in members(own):
            if k != own:
                out[k] = wd
    roles = Path(work_dir) / "hosts" / "roles.csv"
    for r in _read(roles):
        if (r.get("kind") or "").strip() == "system_project" and (r.get("match") or "").strip():
            k = r["match"].strip()
            p = _project(k)
            if p and p.get("work_dir") and k != own:
                out.setdefault(k, Path(p["work_dir"]))
    return out


def peer_rows(work_dir) -> dict[str, dict]:
    """Evidence rows of the citable projects, keyed '<project>:E-nnn' (the project key as written in the registry)."""
    out: dict[str, dict] = {}
    for k, wd in citable_projects(work_dir).items():
        for r in _read(Path(wd) / "evidence-matrix.csv"):
            if r.get("evidence_id"):
                out[f"{k}:{r['evidence_id'].strip()}"] = r
    return out


# ---------------------------------------------------------------- build

def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    if path.name == "evidence-matrix.csv":           # every matrix read carries the latest review
        from csa_docx import evidence_live
        return evidence_live.read(path)
    from csa_docx import modelstore
    return modelstore.read_csv(path)


def _short(name: str) -> str:
    return (name or "").strip().split(".")[0].upper()


def _preference(positions: list[int]) -> str:
    counts = defaultdict(int)
    for p in positions:
        counts[p] += 1
    return ", ".join(f"{POSITION.get(p, f'position {p}')} {n}" for p, n in sorted(counts.items()))


def _evidence(work_dir: Path, project: str) -> dict[tuple[str, str], list[str]]:
    """{(client, service): [<project>:E-nnn]} from the member's matrix rows in the graph-sync grammar."""
    out = defaultdict(list)
    for r in _read(work_dir / "evidence-matrix.csv"):
        if (r.get("review_state") or "") == "rejected":
            continue
        for svc, rx in QUESTION.items():
            m = rx.match((r.get("question") or "").strip())
            if m:
                out[(m[1].upper(), svc)].append(f"{project}:{r['evidence_id']}")
    return out


def collect(estate: str) -> tuple[dict, list[dict]]:
    """(servers, uses) before writing: servers {server: {...}}, uses [{server, service, project, client, preference}]."""
    raw = []                                            # (project, row)
    for key, wd in estate_members(estate):
        for r in _read(wd / "hosts" / "host_services.csv"):
            if r.get("service") in SERVICES and r.get("server_ip") and r.get("client_host"):
                raw.append((key, r))
    # names each member gives each address
    named = defaultdict(lambda: defaultdict(set))       # ip -> name -> {projects}
    fqdn = {}
    for key, r in raw:
        if r.get("server_host"):
            n = _short(r["server_host"])
            named[r["server_ip"]][n].add(key)
            if "." in r["server_host"]:
                fqdn.setdefault(n, r["server_host"].lower())
    servers, uses = {}, []
    for key, r in raw:
        ip = r["server_ip"]
        if r.get("server_host"):
            name = _short(r["server_host"])
        elif len(named.get(ip, {})) == 1:
            name = next(iter(named[ip]))                # the one name any member gives this address
        else:
            name = ip                                   # unnamed, or named two ways: keep the address
        s = servers.setdefault(name, {"server": name, "fqdn": fqdn.get(name, ""), "ips": set(), "services": set(),
                                      "projects": set(), "conflicts": set()})
        s["ips"].add(ip)
        s["services"].add(r["service"])
        s["projects"].add(key)
        try:
            pref = int(r.get("preference") or 1)
        except ValueError:
            pref = 1
        uses.append({"server": name, "service": r["service"], "project": key, "client": r["client_host"].upper(),
                     "preference": pref})
    for ip, names in named.items():
        if len(names) > 1:
            for n, projs in names.items():
                for other, oprojs in names.items():
                    if other != n and n in servers:
                        servers[n]["conflicts"].add(f"{ip} also named {other} in {';'.join(sorted(oprojs))}")
    return servers, uses


def build(estate: str) -> dict:
    servers, uses = collect(estate)
    d = estate_dir(estate)
    d.mkdir(parents=True, exist_ok=True)
    order = [k for k, _ in estate_members(estate)]
    rank = {k: i for i, k in enumerate(order)}
    with (d / "servers.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SERVER_COLS)
        w.writeheader()
        for name in sorted(servers):
            s = servers[name]
            w.writerow({"server": name, "fqdn": s["fqdn"], "ips": ";".join(sorted(s["ips"])),
                        "services": ";".join(x for x in SERVICES if x in s["services"]),
                        "projects": ";".join(sorted(s["projects"], key=lambda k: rank.get(k, 99))),
                        "shared": "yes" if len(s["projects"]) > 1 else "no",
                        "conflicts": " | ".join(sorted(s["conflicts"]))})
    ev = {k: _evidence(wd, k) for k, wd in estate_members(estate)}
    grouped = defaultdict(list)
    for u in uses:
        grouped[(u["server"], u["service"], u["project"])].append(u)
    with (d / "services.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SERVICE_COLS)
        w.writeheader()
        for (server, service, project) in sorted(grouped, key=lambda k: (k[0], k[1], rank.get(k[2], 99))):
            us = grouped[(server, service, project)]
            clients = sorted({u["client"] for u in us})
            ids = sorted({i for c in clients for i in ev.get(project, {}).get((c, service), [])},
                         key=lambda x: int(x.rsplit("-", 1)[-1]) if x.rsplit("-", 1)[-1].isdigit() else 0)
            w.writerow({"server": server, "service": service, "project": project, "clients": str(len(clients)),
                        "client_hosts": ";".join(clients), "preference": _preference([u["preference"] for u in us]),
                        "evidence_ids": ";".join(ids)})
    return {"status": "OK", "estate": estate, "dir": str(d), "servers": len(servers),
            "shared": sum(1 for s in servers.values() if len(s["projects"]) > 1)}


# ---------------------------------------------------------------- read

def servers(estate: str) -> list[dict]:
    return _read(estate_dir(estate) / "servers.csv")


def services(estate: str) -> list[dict]:
    return _read(estate_dir(estate) / "services.csv")


def shared_servers(key: str) -> dict:
    """{server: {"services", "projects", "labels", "ips"}} for the shared servers this project's hosts use;
    ``projects`` are the other members that use it (registry order) and ``labels`` their registry labels."""
    est = estate_of(key)
    if not est:
        return {}
    order = [k for k, _ in estate_members(est)]
    used = {(u["server"], u["service"]) for u in services(est) if u["project"] == key}
    out = {}
    for s in servers(est):
        if s.get("shared") != "yes" or not any(srv == s["server"] for srv, _ in used):
            continue
        mine = [svc for svc in SERVICES if (s["server"], svc) in used]
        others = [p for p in order if p != key and p in s["projects"].split(";")]
        out[s["server"]] = {"services": mine, "projects": others, "labels": [label_of(p) for p in others],
                            "ips": [i for i in s["ips"].split(";") if i]}
    return out


def uses_for(key: str, service: str) -> list[dict]:
    """For one service: [{server, ips, mine: services row, others: [services rows of other members]}] for each
    server this project's hosts use that another member also uses for that service."""
    est = estate_of(key)
    if not est:
        return []
    svc = [u for u in services(est) if u["service"] == service]
    ips = {s["server"]: s["ips"] for s in servers(est)}
    out = []
    for mine in (u for u in svc if u["project"] == key):
        others = [u for u in svc if u["server"] == mine["server"] and u["project"] != key]
        if others:
            out.append({"server": mine["server"], "ips": ips.get(mine["server"], ""), "mine": mine, "others": others})
    return out


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("build", "list", "show"))
    ap.add_argument("server", nargs="?")
    ap.add_argument("--project", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    est = estate_of(a.project)
    if not est:
        out = {"status": "NONE", "message": f"{a.project} has no estate: add estate: \"<AD domain>\" to it in PROJECTS.yaml"}
    elif a.cmd == "build":
        out = build(est)
    elif a.cmd == "list":
        out = {"status": "OK", "estate": est, "servers": servers(est)}
    else:
        want = (a.server or "").upper()
        row = next((s for s in servers(est) if s["server"].upper() == want or want in s["ips"].split(";")), None)
        out = ({"status": "OK", "estate": est, "server": row, "uses": [u for u in services(est) if u["server"] == row["server"]]}
               if row else {"status": "NOT_FOUND", "message": f"{a.server} is not in the {est} estate register"})
    print(json.dumps(out, indent=2))
    return 0 if out["status"] in ("OK", "NONE") else 1


if __name__ == "__main__":
    sys.exit(main())
