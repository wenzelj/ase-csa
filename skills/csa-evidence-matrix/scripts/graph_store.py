#!/usr/bin/env python3
"""CSA diagram graph store: append-only node/edge records derived from evidence.

Sibling to evidence_matrix.py, same discipline: matrix-first lookup, append-only
validated writes, one project's data only. Used by the technical-analyst skills
(ot-architecture-analysis, dependency-analysis, application-discovery,
network-connectivity-analysis, infrastructure-analysis) when they identify a
component or relationship during normal analysis, and read by csa-diagram-generator
when it later decides what to draw. Standard library only; runs on Python 3.8+.

This is a DERIVED store, not a replacement for evidence-matrix.csv: every node and
edge must cite at least one evidence_id that already exists in that project's
evidence-matrix.csv. Nothing here may invent a fact the matrix doesn't already carry.

Files (per project, under <workspace>/csa-work/graph/):
  nodes.csv   node_id, project, domain, label, node_type, purdue_level, zone,
              evidence_ids, confidence, review_state
  edges.csv   edge_id, project, domain, source_node_id, target_node_id,
              relationship_type, evidence_ids, confidence, review_state

Commands
  append-node   add new node rows, append-only, validated              (WRITE)
  append-edge   add new edge rows, append-only, validated               (WRITE)
  get-node      print node rows by node_id                              (READ)
  get-edge      print edge rows by edge_id                              (READ)
  list          list nodes/edges for a domain                           (READ)
  stats         counts by domain / node_type / relationship_type        (READ)
  verify        structural + referential-integrity health check        (READ)

Every command prints one JSON document to stdout. Exit code 0 = OK,
2 = rejected / error (nothing was written).
"""
import argparse
import csv
import datetime
import fcntl
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

NODE_COLUMNS = [
    "node_id", "project", "domain", "label", "node_type", "purdue_level",
    "zone", "evidence_ids", "confidence", "review_state",
]
EDGE_COLUMNS = [
    "edge_id", "project", "domain", "source_node_id", "target_node_id",
    "relationship_type", "evidence_ids", "confidence", "review_state",
]
NODE_TYPES = (
    "host", "service", "zone", "firewall", "idp", "directory",
    "backup_target", "vendor_path", "collector", "dns_server", "ntp_source",
    "hypervisor", "other",
)
PURDUE_LEVELS = ("0", "1", "2", "3", "3.5", "4", "5", "n/a")
RELATIONSHIP_TYPES = (
    "conduit", "dependency", "trust", "data-flow", "remote-access",
    "hosting", "replication", "other",
)
CONFIDENCES = ("high", "medium", "low")
REVIEW_STATES = ("pending", "reviewed", "accepted", "disputed")
MAX_FIELD = 1500
EVIDENCE_ID_RE = re.compile(r"^E-\d{3,}$")


# --------------------------------------------------------------------------- registry (mirrors evidence_matrix.py)
def _load_project_registry():
    """Parse csa-context/PROJECTS.yaml (fixed-shape, no PyYAML dependency).
    Returns [] if the registry can't be found or read -- callers then skip
    the cross-project check rather than blocking every command on a
    framework installation problem.

    This script's own location is .agents/skills/csa-evidence-matrix/scripts/
    -- three parents up is .agents/.
    """
    registry_path = Path(__file__).resolve().parents[3] / "csa-context" / "PROJECTS.yaml"
    if not registry_path.is_file():
        return []
    projects = []
    current = {}
    try:
        for raw_line in registry_path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if raw_line[:1] not in (" ", "\t"):
                continue
            if stripped.startswith("- key:"):
                if current:
                    projects.append(current)
                current = {}
                stripped = stripped[2:]
            if ":" not in stripped:
                continue
            key, _, value = stripped.partition(":")
            current[key.strip()] = value.strip().strip('"').strip("'")
        if current:
            projects.append(current)
    except OSError:
        return []
    return projects


def _resolve_registered_project(workspace):
    for project in _load_project_registry():
        root = project.get("project_root")
        if not root:
            continue
        try:
            root_path = Path(root).expanduser().resolve()
        except OSError:
            continue
        if workspace == root_path or root_path in workspace.parents:
            return project
    return None


def resolve_paths(args):
    ws = args.workspace or os.environ.get("CSA_WORKSPACE")
    if ws:
        workspace = Path(ws).expanduser().resolve()
    else:
        workspace = Path.cwd().resolve()

    # Cross-project safety guard, same as evidence_matrix.py: refuse to read
    # or write graph data for a workspace that isn't a registered project's
    # project_root (or a path under it). This is what makes application
    # isolation a property of the tool, not a convention someone can forget.
    registry = _load_project_registry()
    project = _resolve_registered_project(workspace) if registry else None
    if registry and project is None:
        fail(
            f"WORKSPACE_NOT_REGISTERED: {workspace} is not the project_root (or a "
            "path under it) of any project listed in csa-context/PROJECTS.yaml. "
            "Refusing to read or write graph data for an unregistered workspace -- "
            "pass --workspace <project_root> explicitly, or register this project "
            "in PROJECTS.yaml first.",
            workspace=str(workspace),
        )

    project_key = project.get("key") if project else args.project
    if not project_key:
        fail(
            "PROJECT_UNRESOLVED: could not resolve a project key from "
            "PROJECTS.yaml for this workspace, and no --project fallback was "
            "given. Every node/edge must be stamped with a project key.",
            workspace=str(workspace),
        )

    graph_dir = workspace / "csa-work" / "graph"
    nodes_path = args.nodes_file and Path(args.nodes_file).expanduser().resolve() or graph_dir / "nodes.csv"
    edges_path = args.edges_file and Path(args.edges_file).expanduser().resolve() or graph_dir / "edges.csv"
    matrix_path = workspace / "csa-work" / "evidence-matrix.csv"
    return workspace, project_key, nodes_path, edges_path, matrix_path


# --------------------------------------------------------------------------- io
def load_csv(path, columns):
    if not path.exists():
        return list(columns), [], False, "\n", b""
    raw = path.read_bytes()
    if not raw:
        return list(columns), [], False, "\n", b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    nl = "\r\n" if "\r\n" in text[:8192] else "\n"
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows:
        return list(columns), [], bom, nl, raw
    return rows[0], rows[1:], bom, nl, raw


def as_dict(columns, row):
    row = list(row) + [""] * (len(columns) - len(row))
    return dict(zip(columns, row[: len(columns)]))


def fail(msg, **extra):
    out = {"status": "ERROR", "message": msg}
    out.update(extra)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(2)


def emit(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def one_line(v):
    v = "" if v is None else str(v)
    return re.sub(r"\s*[\r\n]+\s*", " | ", v.strip())


def load_evidence_ids(matrix_path):
    """Every evidence_id that actually exists in this project's evidence
    matrix -- the set graph rows are allowed to cite. Empty set (not an
    error) if the matrix doesn't exist yet; that just means every citation
    will be rejected, which is the correct behaviour."""
    if not matrix_path.exists():
        return set()
    header, body, *_ = load_csv(matrix_path, [])
    if not header or "evidence_id" not in header:
        return set()
    idx = header.index("evidence_id")
    return {r[idx].strip().upper() for r in body if len(r) > idx and r[idx].strip()}


# --------------------------------------------------------------------------- shared validation
def validate_evidence_ids(raw_value, known_evidence_ids, errs):
    ids = [i.strip().upper() for i in re.split(r"[;,]", raw_value or "") if i.strip()]
    if not ids:
        errs.append("evidence_ids is required -- every node/edge must cite at least one real evidence_id")
        return ""
    bad_format = [i for i in ids if not EVIDENCE_ID_RE.match(i)]
    if bad_format:
        errs.append(f"evidence_ids not in E-nnn form: {bad_format}")
    unknown = [i for i in ids if EVIDENCE_ID_RE.match(i) and i not in known_evidence_ids]
    if unknown:
        errs.append(f"evidence_ids not found in this project's evidence-matrix.csv: {unknown}")
    return ";".join(ids)


def next_id(body, id_col_index, prefix):
    top = 0
    for r in body:
        if not r:
            continue
        m = re.fullmatch(rf"{prefix}-(\d+)", r[id_col_index])
        if m:
            top = max(top, int(m.group(1)))
    return top + 1


def backup_and_append(path, columns, header, body, bom, nl, raw, new_rows, workspace, kind, args):
    backup_dir = workspace / "csa-work" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if path.exists():
        backup = backup_dir / f"{path.stem}-{stamp}.csv"
        shutil.copy2(path, backup)
    else:
        backup = None
        path.parent.mkdir(parents=True, exist_ok=True)

    write_header = not path.exists() or not raw
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=nl)
    if write_header:
        w.writerow(columns)
    for r in new_rows:
        w.writerow([r[c] for c in columns])
    prefix = b"" if (not raw or raw.endswith(b"\n") or raw.endswith(b"\r\n")) else nl.encode()
    with open(path, "ab") as fh:
        fh.write(prefix + buf.getvalue().encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())

    audit = workspace / "csa-work" / "graph-audit.jsonl"
    with open(audit, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "agent": args.agent, "context": args.context, "kind": kind,
            "action": "append", "ids": [r[columns[0]] for r in new_rows],
            "backup": backup.name if backup else None,
        }, ensure_ascii=False) + "\n")
    return backup


# --------------------------------------------------------------------------- append-node
def validate_node_row(raw, known_evidence_ids, allow_new_type):
    errs = []
    unknown = set(raw) - set(NODE_COLUMNS)
    if unknown:
        errs.append(f"unknown field(s): {sorted(unknown)}")
    if raw.get("node_id"):
        errs.append("node_id is assigned by the tool; do not supply it")
    row = {c: one_line(raw.get(c, "")) for c in NODE_COLUMNS}
    row["node_id"] = ""
    row["node_type"] = row["node_type"].lower()
    row["purdue_level"] = row["purdue_level"].lower()
    row["confidence"] = row["confidence"].lower()
    row["review_state"] = row["review_state"].lower() or "pending"
    for req in ("project", "domain", "label", "node_type"):
        if not row[req]:
            errs.append(f"{req} is required")
    if row["node_type"] and row["node_type"] not in NODE_TYPES and not allow_new_type:
        errs.append(f"node_type {row['node_type']!r} is not a known type {list(NODE_TYPES)}; "
                    "use one of them, or pass --allow-new-type if a new type is truly needed")
    if row["purdue_level"] and row["purdue_level"] not in PURDUE_LEVELS:
        errs.append(f"purdue_level must be one of {list(PURDUE_LEVELS)} or blank")
    if row["confidence"] and row["confidence"] not in CONFIDENCES:
        errs.append("confidence must be high, medium, low or empty")
    if row["review_state"] not in REVIEW_STATES:
        errs.append(f"review_state must be one of {list(REVIEW_STATES)}")
    row["evidence_ids"] = validate_evidence_ids(raw.get("evidence_ids", ""), known_evidence_ids, errs)
    for f in NODE_COLUMNS:
        if len(row[f]) > MAX_FIELD:
            errs.append(f"{f} is too long ({len(row[f])} chars)")
    return row, errs


def cmd_append_node(args):
    workspace, project_key, nodes_path, _, matrix_path = resolve_paths(args)
    payload = _read_payload(args)
    data = _as_list(payload)
    known_evidence_ids = load_evidence_ids(matrix_path)

    lock_path = workspace / "csa-work" / ".graph-store.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            header, body, bom, nl, raw = load_csv(nodes_path, NODE_COLUMNS)
            if body and header != NODE_COLUMNS:
                fail("nodes.csv header differs from the expected schema; repair before appending", found=header)

            prepared, errors = [], []
            for i, item in enumerate(data):
                item = dict(item)
                item.setdefault("project", project_key)
                if item.get("project") != project_key:
                    errors.append({"index": i, "errors": [
                        f"project {item.get('project')!r} does not match this workspace's registered "
                        f"project {project_key!r} -- refusing to write a row for another application"]})
                    continue
                row, errs = validate_node_row(item, known_evidence_ids, args.allow_new_type)
                if errs:
                    errors.append({"index": i, "label": (item.get("label") or "")[:80], "errors": errs})
                else:
                    prepared.append(row)
            if errors:
                fail("rows rejected; nothing written", rejected=errors)

            n = next_id(body, NODE_COLUMNS.index("node_id"), "N")
            written = []
            for row in prepared:
                row["node_id"] = f"N-{n:03d}"
                n += 1
                written.append(row)

            if args.dry_run or not written:
                emit({"status": "DRY_RUN" if args.dry_run else "NOTHING_TO_WRITE",
                      "would_write": [{"node_id": r["node_id"], "label": r["label"]} for r in written]})
                return

            backup = backup_and_append(nodes_path, NODE_COLUMNS, header, body, bom, nl, raw,
                                        written, workspace, "node", args)
            emit({"status": "APPENDED", "nodes_file": str(nodes_path),
                  "backup": str(backup) if backup else None,
                  "written": [{"node_id": r["node_id"], "label": r["label"], "node_type": r["node_type"]}
                              for r in written]})
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# --------------------------------------------------------------------------- append-edge
def validate_edge_row(raw, known_evidence_ids, known_node_ids, allow_new_type):
    errs = []
    unknown = set(raw) - set(EDGE_COLUMNS)
    if unknown:
        errs.append(f"unknown field(s): {sorted(unknown)}")
    if raw.get("edge_id"):
        errs.append("edge_id is assigned by the tool; do not supply it")
    row = {c: one_line(raw.get(c, "")) for c in EDGE_COLUMNS}
    row["edge_id"] = ""
    row["relationship_type"] = row["relationship_type"].lower()
    row["confidence"] = row["confidence"].lower()
    row["review_state"] = row["review_state"].lower() or "pending"
    for req in ("project", "domain", "source_node_id", "target_node_id", "relationship_type"):
        if not row[req]:
            errs.append(f"{req} is required")
    if row["source_node_id"] and row["source_node_id"] not in known_node_ids:
        errs.append(f"source_node_id {row['source_node_id']!r} does not exist in nodes.csv -- "
                    "referential integrity requires the node to already be appended")
    if row["target_node_id"] and row["target_node_id"] not in known_node_ids:
        errs.append(f"target_node_id {row['target_node_id']!r} does not exist in nodes.csv")
    if row["source_node_id"] == row["target_node_id"] and row["source_node_id"]:
        errs.append("source_node_id and target_node_id are the same node -- an edge needs two distinct nodes")
    if row["relationship_type"] and row["relationship_type"] not in RELATIONSHIP_TYPES and not allow_new_type:
        errs.append(f"relationship_type {row['relationship_type']!r} is not a known type "
                    f"{list(RELATIONSHIP_TYPES)}; use one of them, or pass --allow-new-type")
    if row["confidence"] and row["confidence"] not in CONFIDENCES:
        errs.append("confidence must be high, medium, low or empty")
    if row["review_state"] not in REVIEW_STATES:
        errs.append(f"review_state must be one of {list(REVIEW_STATES)}")
    row["evidence_ids"] = validate_evidence_ids(raw.get("evidence_ids", ""), known_evidence_ids, errs)
    for f in EDGE_COLUMNS:
        if len(row[f]) > MAX_FIELD:
            errs.append(f"{f} is too long ({len(row[f])} chars)")
    return row, errs


def cmd_append_edge(args):
    workspace, project_key, nodes_path, edges_path, matrix_path = resolve_paths(args)
    payload = _read_payload(args)
    data = _as_list(payload)
    known_evidence_ids = load_evidence_ids(matrix_path)
    node_header, node_body, *_ = load_csv(nodes_path, NODE_COLUMNS)
    known_node_ids = {r[0] for r in node_body if r}

    lock_path = workspace / "csa-work" / ".graph-store.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            header, body, bom, nl, raw = load_csv(edges_path, EDGE_COLUMNS)
            if body and header != EDGE_COLUMNS:
                fail("edges.csv header differs from the expected schema; repair before appending", found=header)

            prepared, errors = [], []
            for i, item in enumerate(data):
                item = dict(item)
                item.setdefault("project", project_key)
                if item.get("project") != project_key:
                    errors.append({"index": i, "errors": [
                        f"project {item.get('project')!r} does not match this workspace's registered "
                        f"project {project_key!r} -- refusing to write a row for another application"]})
                    continue
                row, errs = validate_edge_row(item, known_evidence_ids, known_node_ids, args.allow_new_type)
                if errs:
                    errors.append({"index": i, "errors": errs})
                else:
                    prepared.append(row)
            if errors:
                fail("rows rejected; nothing written", rejected=errors)

            n = next_id(body, EDGE_COLUMNS.index("edge_id"), "R")
            written = []
            for row in prepared:
                row["edge_id"] = f"R-{n:03d}"
                n += 1
                written.append(row)

            if args.dry_run or not written:
                emit({"status": "DRY_RUN" if args.dry_run else "NOTHING_TO_WRITE",
                      "would_write": [{"edge_id": r["edge_id"], "source_node_id": r["source_node_id"],
                                       "target_node_id": r["target_node_id"]} for r in written]})
                return

            backup = backup_and_append(edges_path, EDGE_COLUMNS, header, body, bom, nl, raw,
                                        written, workspace, "edge", args)
            emit({"status": "APPENDED", "edges_file": str(edges_path),
                  "backup": str(backup) if backup else None,
                  "written": [{"edge_id": r["edge_id"], "source_node_id": r["source_node_id"],
                               "target_node_id": r["target_node_id"],
                               "relationship_type": r["relationship_type"]} for r in written]})
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# --------------------------------------------------------------------------- read commands
def _read_payload(args):
    if args.rows_file:
        text = sys.stdin.read() if args.rows_file == "-" else Path(args.rows_file).read_text(encoding="utf-8")
    elif args.row_json:
        text = args.row_json
    else:
        fail("supply --row-json '<json>' or --rows-file <path|->")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        fail(f"input is not valid JSON: {e}")


def _as_list(data):
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data or not all(isinstance(x, dict) for x in data):
        fail("input must be a JSON object or a non-empty array of objects")
    return data


def cmd_get_node(args):
    _, _, nodes_path, _, _ = resolve_paths(args)
    header, body, *_ = load_csv(nodes_path, NODE_COLUMNS)
    ids = {i.strip().upper() for i in args.ids}
    rows = [as_dict(NODE_COLUMNS, r) for r in body if r and r[0].upper() in ids]
    found = {r["node_id"].upper() for r in rows}
    emit({"status": "OK", "rows": rows, "not_found": sorted(ids - found)})


def cmd_get_edge(args):
    _, _, _, edges_path, _ = resolve_paths(args)
    header, body, *_ = load_csv(edges_path, EDGE_COLUMNS)
    ids = {i.strip().upper() for i in args.ids}
    rows = [as_dict(EDGE_COLUMNS, r) for r in body if r and r[0].upper() in ids]
    found = {r["edge_id"].upper() for r in rows}
    emit({"status": "OK", "rows": rows, "not_found": sorted(ids - found)})


def cmd_list(args):
    _, project_key, nodes_path, edges_path, _ = resolve_paths(args)
    nh, nb, *_ = load_csv(nodes_path, NODE_COLUMNS)
    eh, eb, *_ = load_csv(edges_path, EDGE_COLUMNS)
    nodes = [as_dict(NODE_COLUMNS, r) for r in nb]
    edges = [as_dict(EDGE_COLUMNS, r) for r in eb]
    if args.domain:
        nodes = [n for n in nodes if n["domain"] == args.domain]
        edges = [e for e in edges if e["domain"] == args.domain]
    emit({"status": "OK", "project": project_key, "domain": args.domain,
          "node_count": len(nodes), "edge_count": len(edges),
          "nodes": nodes, "edges": edges})


def cmd_stats(args):
    _, project_key, nodes_path, edges_path, _ = resolve_paths(args)
    nh, nb, *_ = load_csv(nodes_path, NODE_COLUMNS)
    eh, eb, *_ = load_csv(edges_path, EDGE_COLUMNS)
    nodes = [as_dict(NODE_COLUMNS, r) for r in nb]
    edges = [as_dict(EDGE_COLUMNS, r) for r in eb]
    def count(rows, key):
        out = {}
        for r in rows:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items()))
    emit({"status": "OK", "project": project_key,
          "nodes": len(nodes), "edges": len(edges),
          "nodes_by_domain": count(nodes, "domain"), "nodes_by_type": count(nodes, "node_type"),
          "edges_by_domain": count(edges, "domain"), "edges_by_relationship_type": count(edges, "relationship_type")})


def cmd_verify(args):
    workspace, project_key, nodes_path, edges_path, matrix_path = resolve_paths(args)
    known_evidence_ids = load_evidence_ids(matrix_path)
    nh, nb, nbom, nnl, _ = load_csv(nodes_path, NODE_COLUMNS)
    eh, eb, ebom, enl, _ = load_csv(edges_path, EDGE_COLUMNS)
    issues = []

    if nb and nh != NODE_COLUMNS:
        issues.append({"file": "nodes.csv", "row": 0, "issue": "header differs from schema", "found": nh})
    if eb and eh != EDGE_COLUMNS:
        issues.append({"file": "edges.csv", "row": 0, "issue": "header differs from schema", "found": eh})

    node_ids, node_seen = set(), set()
    for i, r in enumerate(nb, start=2):
        if not r:
            continue
        d = as_dict(NODE_COLUMNS, r)
        if not re.fullmatch(r"N-\d{3,}", d["node_id"]):
            issues.append({"file": "nodes.csv", "row": i, "issue": f"node_id not N-nnn: {d['node_id']!r}"})
        if d["node_id"] in node_seen:
            issues.append({"file": "nodes.csv", "row": i, "issue": "duplicate node_id"})
        node_seen.add(d["node_id"])
        node_ids.add(d["node_id"])
        if d["project"] != project_key:
            issues.append({"file": "nodes.csv", "row": i, "node_id": d["node_id"],
                           "issue": f"project {d['project']!r} does not match registered project {project_key!r}"})
        if d["node_type"] not in NODE_TYPES:
            issues.append({"file": "nodes.csv", "row": i, "node_id": d["node_id"],
                           "issue": f"unrecognised node_type {d['node_type']!r}"})
        cited = [c.strip().upper() for c in d["evidence_ids"].split(";") if c.strip()]
        if not cited:
            issues.append({"file": "nodes.csv", "row": i, "node_id": d["node_id"], "issue": "no evidence_ids cited"})
        unknown = [c for c in cited if c not in known_evidence_ids]
        if unknown:
            issues.append({"file": "nodes.csv", "row": i, "node_id": d["node_id"],
                           "issue": f"cites evidence_id(s) not found in evidence-matrix.csv: {unknown}"})

    edge_seen = set()
    for i, r in enumerate(eb, start=2):
        if not r:
            continue
        d = as_dict(EDGE_COLUMNS, r)
        if not re.fullmatch(r"R-\d{3,}", d["edge_id"]):
            issues.append({"file": "edges.csv", "row": i, "issue": f"edge_id not R-nnn: {d['edge_id']!r}"})
        if d["edge_id"] in edge_seen:
            issues.append({"file": "edges.csv", "row": i, "issue": "duplicate edge_id"})
        edge_seen.add(d["edge_id"])
        if d["project"] != project_key:
            issues.append({"file": "edges.csv", "row": i, "edge_id": d["edge_id"],
                           "issue": f"project {d['project']!r} does not match registered project {project_key!r}"})
        if d["source_node_id"] not in node_ids:
            issues.append({"file": "edges.csv", "row": i, "edge_id": d["edge_id"],
                           "issue": f"source_node_id {d['source_node_id']!r} does not exist in nodes.csv"})
        if d["target_node_id"] not in node_ids:
            issues.append({"file": "edges.csv", "row": i, "edge_id": d["edge_id"],
                           "issue": f"target_node_id {d['target_node_id']!r} does not exist in nodes.csv"})
        cited = [c.strip().upper() for c in d["evidence_ids"].split(";") if c.strip()]
        if not cited:
            issues.append({"file": "edges.csv", "row": i, "edge_id": d["edge_id"], "issue": "no evidence_ids cited"})
        unknown = [c for c in cited if c not in known_evidence_ids]
        if unknown:
            issues.append({"file": "edges.csv", "row": i, "edge_id": d["edge_id"],
                           "issue": f"cites evidence_id(s) not found in evidence-matrix.csv: {unknown}"})

    emit({"status": "OK" if not issues else "ISSUES", "project": project_key,
          "nodes_file": str(nodes_path), "edges_file": str(edges_path),
          "node_count": len(nb), "edge_count": len(eb),
          "issue_count": len(issues), "issues": issues})


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", help="project root (default: cwd)")
    ap.add_argument("--project", help="fallback project key if PROJECTS.yaml can't resolve one (rare)")
    ap.add_argument("--nodes-file", help="explicit nodes.csv path (default: <workspace>/csa-work/graph/nodes.csv)")
    ap.add_argument("--edges-file", help="explicit edges.csv path (default: <workspace>/csa-work/graph/edges.csv)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("append-node", help="append new node rows (append-only)")
    p.add_argument("--agent", required=True)
    p.add_argument("--context", default="")
    p.add_argument("--row-json"); p.add_argument("--rows-file")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-new-type", action="store_true")
    p.set_defaults(fn=cmd_append_node)

    p = sub.add_parser("append-edge", help="append new edge rows (append-only)")
    p.add_argument("--agent", required=True)
    p.add_argument("--context", default="")
    p.add_argument("--row-json"); p.add_argument("--rows-file")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-new-type", action="store_true")
    p.set_defaults(fn=cmd_append_edge)

    p = sub.add_parser("get-node"); p.add_argument("ids", nargs="+"); p.set_defaults(fn=cmd_get_node)
    p = sub.add_parser("get-edge"); p.add_argument("ids", nargs="+"); p.set_defaults(fn=cmd_get_edge)

    p = sub.add_parser("list"); p.add_argument("--domain"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("stats"); p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("verify"); p.set_defaults(fn=cmd_verify)

    args = ap.parse_args()
    try:
        args.fn(args)
    except FileNotFoundError as e:
        fail(f"file not found: {e.filename}")
    except ValueError as e:
        fail(str(e))


if __name__ == "__main__":
    main()
