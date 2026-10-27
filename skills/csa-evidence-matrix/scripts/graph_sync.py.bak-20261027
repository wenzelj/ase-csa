#!/usr/bin/env python3
"""Keep the evidence graph in step with the evidence matrix and the captures (stdlib, 3.8+).

  python3 graph_sync.py --workspace <project_root> [--dry-run] [--no-captures]

Runs automatically after every successful `evidence_matrix.py append` (set CSA_NO_GRAPH_SYNC=1
to skip). Idempotent; each step only acts on what changed:

1. captures  - a host capture newer than the last sync is profiled with host_profile.py
               `record` (matrix rows, nodes and edges for its links).
2. links     - a VERIFIED connection row in host_profile's link grammar ("A ... has an ...
               connection to B on ..." / "A has an ... connection from P to B ...") that no
               edge cites yet gets an edge A -> B. Free-text rows are never guessed into edges.
3. services  - each host's configured DNS and time servers (hosts/host_services.csv, from its
               resolver and time-status captures) become one VERIFIED matrix row per host and
               service, a node per server and name-resolution / time-source edges (sync_services).
4. prune     - evidence IDs no longer in the matrix are dropped from nodes and edges; an
               edge left with no evidence is removed; a node left with no evidence and no
               edge is removed. A backup is taken before any rewrite.
5. hosts     - hosts/evidence_hosts.csv is rebuilt from the matrix (csa hosts build).

State: csa-work/graph/.sync-state.json (last capture timestamp per host).
"""
import argparse, csv, datetime, json, os, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve()
AGENTS = HERE.parents[3]
GS = HERE.parent / "graph_store.py"
HP = AGENTS / "skills/evidence-investigator/scripts/host_profile.py"


def read_csv(p):
    if not p.is_file():
        return [], []
    with open(p, encoding="utf-8-sig", newline="") as fh:
        r = csv.DictReader(fh)
        return list(r.fieldnames or []), list(r)


def write_csv(p, fields, rows, stamp):
    bk = p.parent.parent / "backups"
    bk.mkdir(exist_ok=True)
    shutil.copy2(p, bk / f"{p.stem}-{stamp}-pre-sync.csv")
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\r\n")
        w.writeheader(); w.writerows(rows)


def run(cmd, payload=None):
    env = dict(os.environ, CSA_NO_GRAPH_SYNC="1")          # never recurse into another sync
    r = subprocess.run([sys.executable, *map(str, cmd)], input=json.dumps(payload) if payload is not None else None,
                       capture_output=True, text=True, env=env)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"status": "ERROR", "stderr": r.stderr[-500:], "stdout": r.stdout[-500:]}


EM = HERE.parent / "evidence_matrix.py"
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth")
SERVICE = {
    "dns": {"question": "Which DNS servers is {c} configured to use?", "section": "3.5 DNS",
            "relationship": "name-resolution", "node_type": "dns_server"},
    "time": {"question": "Which time source does {c} synchronise from?", "section": "3.4 Time Synchronisation",
             "relationship": "time-source", "node_type": "ntp_source"},
}
CAP_TS = re.compile(r"_(\d{8}T\d{6}Z)$")


def _server_label(r):
    return f"{r['server_host']} ({r['server_ip']})" if r.get("server_host") else r["server_ip"]


def _service_claim(client, service, servers):
    names = [_server_label(r) for r in servers]
    if service == "time":
        return f"{client} synchronises its time from {names[0]}."
    if len(names) == 1:
        return f"{client} is configured to resolve names through {names[0]}."
    parts = [f"{n} {ORDINALS[i] if i < len(ORDINALS) else f'number {i + 1}'}" for i, n in enumerate(names)]
    return f"{client} is configured to resolve names through {', '.join(parts[:-1])} and {parts[-1]}."


def sync_services(workspace, dry_run=False):
    """Step 3: hosts/host_services.csv -> one VERIFIED matrix row per (host, service), a node per server
    (an existing node is reused only when its label is the name or starts with "<NAME> "), and one
    name-resolution / time-source edge per (host, server). Re-running adds nothing new.
    Returns {"status", "rows", "nodes", "edges"} counting what this run added (or would add)."""
    ws = Path(workspace).resolve()
    wd = ws / "csa-work"
    gdir = wd / "graph"
    _, S = read_csv(wd / "hosts" / "host_services.csv")
    out = {"status": "OK", "rows": 0, "nodes": 0, "edges": 0}
    groups = {}
    for r in S:
        if r.get("service") in SERVICE and r.get("client_host") and r.get("server_ip"):
            groups.setdefault((r["client_host"], r["service"]), []).append(r)
    if not groups:
        return out
    _, M = read_csv(wd / "evidence-matrix.csv")
    have_q = {r["question"]: r["evidence_id"] for r in M if r.get("review_state") != "rejected"}

    # 1. matrix rows
    rows, keys = [], []
    for (client, service), rs in sorted(groups.items()):
        rs = sorted(rs, key=lambda r: int(r.get("preference") or 0))
        q = SERVICE[service]["question"].format(c=client)
        if q in have_q:
            continue
        cap = rs[0].get("capture", "")
        src = rs[0].get("source", "")
        fname = src.split("/")[-1].split(" line ")[0] if src else ("14_resolver.txt" if service == "dns" else "03_time_status.txt")
        line = src.rsplit(" line ", 1)[-1] if " line " in src else ""
        ts = CAP_TS.search(cap)
        excerpts = list(dict.fromkeys(r["excerpt"].strip() for r in rs if r.get("excerpt", "").strip()))
        rows.append({"csa_area": "network_and_connectivity", "question": q,
                     "claim": _service_claim(client, service, rs if service == "dns" else rs[:1]),
                     "status": "VERIFIED", "source_title": f"{cap}: {fname}",
                     "source_version": f"capture {ts[1]}" if ts else "", "section": SERVICE[service]["section"],
                     "page_or_location": f"{fname} line {line}" if line else fname,
                     "evidence_excerpt": " | ".join(excerpts), "confidence": "high"})
        keys.append(q)
    out["rows"] = len(rows)
    if rows and not dry_run:
        res = run([EM, "--workspace", ws, "append", "--agent", "graph-sync", "--context", "graph-sync services",
                   "--rows-file", "-"], rows)
        if res.get("status") != "APPENDED":
            return {"status": "ERROR", "step": "matrix rows", "detail": res, "rows": 0, "nodes": 0, "edges": 0}
        _, M = read_csv(wd / "evidence-matrix.csv")
        have_q = {r["question"]: r["evidence_id"] for r in M if r.get("review_state") != "rejected"}

    # 2. nodes
    _, N = read_csv(gdir / "nodes.csv")

    def find(name):
        for n in N:
            lab = n.get("label", "")
            if lab == name or lab.startswith(name + " "):
                return n["node_id"]
        return None

    want = {}                                      # label -> (node_type, domain, evidence)
    for (client, service), rs in sorted(groups.items()):
        eid = have_q.get(SERVICE[service]["question"].format(c=client), "")
        for name, typ in [(client, "host")] + [(r.get("server_host") or r["server_ip"], SERVICE[service]["node_type"]) for r in rs]:
            if not find(name) and name not in want:
                want[name] = (typ, SERVICE[service]["section"], eid)
    new_nodes = [{"domain": d, "label": lab, "node_type": t, "purdue_level": "n/a", "evidence_ids": e,
                  "confidence": "high", "review_state": "pending"} for lab, (t, d, e) in want.items()]
    out["nodes"] = len(new_nodes)
    if new_nodes and not dry_run:
        res = run([GS, "--workspace", ws, "append-node", "--agent", "graph-sync", "--context", "graph-sync services",
                   "--rows-file", "-"], new_nodes)
        if res.get("status") != "APPENDED":
            return {**out, "status": "ERROR", "step": "nodes", "detail": res}
        _, N = read_csv(gdir / "nodes.csv")
    if dry_run:                                     # what step 3 would add, with no node ids yet
        out["edges"] = sum(len({r.get("server_host") or r["server_ip"] for r in rs}) for rs in groups.values())
        return out

    # 3. edges
    _, E = read_csv(gdir / "edges.csv")
    have_e = {(e["source_node_id"], e["target_node_id"], e["relationship_type"]) for e in E}
    edges = []
    for (client, service), rs in sorted(groups.items()):
        eid = have_q.get(SERVICE[service]["question"].format(c=client), "")
        a = find(client)
        for r in rs:
            b = find(r.get("server_host") or r["server_ip"])
            k = (a, b, SERVICE[service]["relationship"])
            if a and b and a != b and eid and k not in have_e:
                have_e.add(k)
                edges.append({"domain": SERVICE[service]["section"], "source_node_id": a, "target_node_id": b,
                              "relationship_type": SERVICE[service]["relationship"], "evidence_ids": eid,
                              "confidence": "high", "review_state": "pending"})
    out["edges"] = len(edges)
    if edges:
        res = run([GS, "--workspace", ws, "append-edge", "--agent", "graph-sync", "--context", "graph-sync services",
                   "--rows-file", "-"], edges)
        if res.get("status") != "APPENDED":
            return {**out, "status": "ERROR", "step": "edges", "detail": res}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-captures", action="store_true", help="skip step 1")
    a = ap.parse_args()
    ws = Path(a.workspace).resolve()
    wd = ws / "csa-work"
    gdir = wd / "graph"; gdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {"status": "OK", "dry_run": a.dry_run}

    # 1. new captures
    state_p = gdir / ".sync-state.json"
    state = json.loads(state_p.read_text()) if state_p.is_file() else {}
    if not a.no_captures and HP.is_file():
        lst = run([HP, "--workspace", ws, "list"])
        caps = lst.get("captured_hosts", {})
        new = [h for h, d in caps.items() if state.get(h) != d]
        report["captures_new"] = new
        if new and not a.dry_run:
            done = []
            for h in new:
                r = run([HP, "--workspace", ws, "record", h, "--agent", "graph-sync"])
                if r.get(h, {}).get("matrix", {}).get("status") != "ERROR":
                    state[h] = caps[h]; done.append(h)
            state_p.write_text(json.dumps(state, indent=1))
            report["captures_recorded"] = done

    # 2. link rows without an edge
    _, M = read_csv(wd / "evidence-matrix.csv")
    ids = {r["evidence_id"] for r in M}
    nf, N = read_csv(gdir / "nodes.csv")
    ef, E = read_csv(gdir / "edges.csv")
    on_edge = {i for e in E for i in e["evidence_ids"].split(";") if i}
    by_name = {}
    for n in N:
        if n["node_type"] == "host":
            by_name.setdefault(n["label"].split(" ")[0], n["node_id"])
    # only claims in the link grammar host_profile.py writes are graphed: a free-text row that
    # names two hosts does not say which way the link runs, so it is never turned into an edge
    IN = re.compile(r"^(\S+) (?:\([^)]*\) )?has an .*?connection to (\S+) on ")
    OUT = re.compile(r"^(\S+) has an .*?connection from \S+ to (\S+) ")
    want = []
    for r in M:
        if r["status"] != "VERIFIED" or r["evidence_id"] in on_edge:
            continue
        m = IN.match(r["claim"]) or OUT.match(r["claim"])
        if not m or m[1] not in by_name or m[2] not in by_name or m[1] == m[2]:
            continue
        want.append({"domain": "3.6 Network / Segmentation", "source_node_id": by_name[m[1]],
                     "target_node_id": by_name[m[2]], "relationship_type": "data-flow",
                     "evidence_ids": r["evidence_id"], "confidence": "high", "review_state": "pending"})
    report["edges_from_rows"] = len(want)
    if want and not a.dry_run:
        report["edges_append"] = run([GS, "--workspace", ws, "append-edge", "--agent", "graph-sync",
                                      "--context", "graph-sync link rows", "--rows-file", "-"], want).get("status")
        ef, E = read_csv(gdir / "edges.csv")

    # 3. configured DNS and time servers
    report["services"] = sync_services(ws, a.dry_run)
    if not a.dry_run:                     # the prune below rewrites the files: start from what step 3 wrote
        _, M = read_csv(wd / "evidence-matrix.csv")
        ids = {r["evidence_id"] for r in M}
        nf, N = read_csv(gdir / "nodes.csv")
        ef, E = read_csv(gdir / "edges.csv")

    # 4. prune references to removed evidence
    def clean(x):
        keep = [i for i in x["evidence_ids"].split(";") if i and i in ids]
        changed = ";".join(keep) != x["evidence_ids"]
        x["evidence_ids"] = ";".join(keep)
        return changed
    e_changed = sum(clean(e) for e in E)
    E2 = [e for e in E if e["evidence_ids"]]
    used = {e["source_node_id"] for e in E2} | {e["target_node_id"] for e in E2}
    n_changed = sum(clean(n) for n in N)
    N2 = [n for n in N if n["evidence_ids"] or n["node_id"] in used]
    report["prune"] = {"edge_refs_changed": e_changed, "edges_removed": len(E) - len(E2),
                       "node_refs_changed": n_changed, "nodes_removed": len(N) - len(N2)}
    if not a.dry_run:
        if e_changed or len(E2) != len(E):
            write_csv(gdir / "edges.csv", ef, E2, stamp)
        if n_changed or len(N2) != len(N):
            write_csv(gdir / "nodes.csv", nf, N2, stamp)

    # 4b. relabel address nodes the host register has since named
    hp = wd / "hosts" / "hosts.csv"
    if hp.is_file():
        _, H = read_csv(hp)
        owner = {ip: h["host"] for h in H for ip in (h.get("ips") or "").split(";") if ip}
        nf, N = read_csv(gdir / "nodes.csv")
        renamed = []
        for n in N:
            first = n["label"].split(" ")[0]
            if first in owner and "name not captured" in n["label"]:
                renamed.append((n["node_id"], first, owner[first]))
                n["label"] = f"{owner[first]} ({first})"
        report["relabelled"] = [f"{a}: {b} -> {c}" for a, b, c in renamed]
        if renamed and not a.dry_run:
            write_csv(gdir / "nodes.csv", nf, N, stamp)

    # 5. host index
    if not a.dry_run:
        try:
            sys.path.insert(0, str(AGENTS / "framework"))
            from csa_docx import hostmodel
            hostmodel.build(wd)
            report["hosts_index"] = "rebuilt"
            # the rebuild writes hosts/host_services.csv: record what it adds now, not at the next sync
            late = sync_services(ws)
            if late.get("rows") or late.get("nodes") or late.get("edges"):
                report["services_after_index"] = late
                hostmodel.build(wd)
        except Exception as ex:                      # the framework may need a newer Python
            report["hosts_index"] = f"skipped: {type(ex).__name__}: {ex}"[:200]
        with open(wd / "graph-audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                 "agent": "graph-sync", "action": "sync", "report": report}) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
