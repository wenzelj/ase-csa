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
3. prune     - evidence IDs no longer in the matrix are dropped from nodes and edges; an
               edge left with no evidence is removed; a node left with no evidence and no
               edge is removed. A backup is taken before any rewrite.
4. hosts     - hosts/evidence_hosts.csv is rebuilt from the matrix (csa hosts build).

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

    # 3. prune references to removed evidence
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

    # 4. host index
    if not a.dry_run:
        try:
            sys.path.insert(0, str(AGENTS / "framework"))
            from csa_docx import hostmodel
            hostmodel.build(wd)
            report["hosts_index"] = "rebuilt"
        except Exception as ex:                      # the framework may need a newer Python
            report["hosts_index"] = f"skipped: {type(ex).__name__}: {ex}"[:200]
        with open(wd / "graph-audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                 "agent": "graph-sync", "action": "sync", "report": report}) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
