"""S588: batched intake on the csa-work-v2 repository.

One model session handles a batch of files (`MAX_FILES`, default 1) instead of one file.
`build_batch` assembles the payload the model reads (indexed text chunks, the matrix rows and
hosts already known for each file, and the INTAKE mode rules). The model answers with one JSON
object per file. `apply_batch` validates every candidate row with evidence_matrix.py's quote
check (imported through `v2repo`, never copied), skips duplicates, applies structured observations,
and marks each file processed or failed. The caller can reuse one quote index for the whole intake
and defer the repository-wide graph refresh until intake completes. The model proposes rows and
structured items; only this validator writes the matrix and graph.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .v2repo import Repo  # noqa: F401  (re-exported for callers)
from . import v2repo as _pkg
import csa_docx.v2repo.intake  # noqa: F401  # registers r.intake
import csa_docx.v2repo.graph  # noqa: F401  # registers r.graph

MAX_FILES = 1  # files per model session; tune here only
SMALL_FILE_MAX_BYTES = 10_000  # compatible tiny files may share a session
SMALL_FILE_BATCH_MAX = 5
MAX_FILE_CHARS = 60000  # keep one large capture below local-model prompt limits

_AGENT_FILE = Path(__file__).resolve().parents[2] / "csa-evidence-investigator-agent.md"
_ROW_FIELDS = ("claim", "source_title", "page_or_location", "excerpt", "area", "confidence",
               "gap_or_action", "status", "question")
_STATUSES = ("VERIFIED", "INFERRED", "UNCONFIRMED", "CONFLICTING", "NOT_FOUND")
_POINTER_LINE = re.compile(r"^generated:\s*(?:[a-z]:[\\/]|/|\\\\)", re.I)
_EVIDENCE_ID = re.compile(r"\bE-\d+\b", re.I)
_GRAPH_KINDS = {"host", "address", "flow", "service"}
_ZONE_KINDS = {"ot", "it", "internet", "cloud", "vendor", "unknown"}


def batches(file_rel_paths, max_files: int = MAX_FILES, *, repo=None, adaptive=False) -> list[list[str]]:
    """Split paths into model sessions, optionally grouping compatible tiny files.

    The default remains one file per session. Adaptive grouping is opt-in and only groups
    files <= ``SMALL_FILE_MAX_BYTES`` sharing a directory and extension, preserving the
    per-file rel_path in the model response and evidence audit trail.
    """
    paths = list(file_rel_paths)
    n = max(1, int(max_files))
    if not adaptive or repo is None:
        return [paths[i:i + n] for i in range(0, len(paths), n)]
    sizes = {p: (repo.con.execute("SELECT size FROM indexed_file WHERE rel_path=?", (p,)).fetchone() or (None,))[0]
             for p in paths}
    groups = []
    current = []
    current_key = None
    for path in paths:
        size = sizes.get(path)
        parent, _, base = path.rpartition("/")
        suffix = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        key = (parent, suffix)
        shareable = size is not None and size <= SMALL_FILE_MAX_BYTES
        if not shareable:
            if current:
                groups.append(current); current = []; current_key = None
            groups.append([path])
            continue
        if current and (key != current_key or len(current) >= max(n, SMALL_FILE_BATCH_MAX)):
            groups.append(current); current = []
        current.append(path)
        current_key = key
    if current:
        groups.append(current)
    return groups


def intake_instructions() -> str:
    """The INTAKE mode section of the investigator agent definition, verbatim."""
    text = _AGENT_FILE.read_text(encoding="utf-8")
    m = re.search(r"^## Intake mode.*?(?=^## )", text, re.S | re.M)
    return m.group(0).strip() if m else ""


def deterministic_batch(file_rel_paths, *, repo) -> list[dict]:
    """Return safe no-model outputs for files that only point to another capture.

    These files contain no assessment fact of their own: they are the generated-path
    sidecars created beside HTML/XML captures. Anything else stays on the model path.
    """
    outputs = []
    for rel in file_rel_paths:
        base = rel.rsplit("/", 1)[-1].lower()
        if not base.endswith("_path.txt"):
            return []
        chunks = [t or "" for (t,) in repo.con.execute(
            "SELECT text FROM indexed_chunk WHERE rel_path=? ORDER BY id", (rel,))]
        lines = [line.strip() for line in "\n".join(chunks).splitlines() if line.strip()]
        if not lines or len(lines) > 8 or not all(_POINTER_LINE.match(line) for line in lines):
            return []
        outputs.append({"rel_path": rel, "rows": [], "graph_items": []})
    return outputs


def build_batch(record_id, file_rel_paths, max_files: int = MAX_FILES, *, repo) -> dict:
    """Payload for one model session: the first `max_files` of `file_rel_paths`.

    Use `batches()` to split a longer list; call this once per batch.
    """
    con = repo.con
    hosts = [h[0] for h in con.execute("SELECT name FROM host ORDER BY name")]
    files = []
    for rel in list(file_rel_paths)[:max(1, int(max_files))]:
        source_chunks = [t or "" for (t,) in con.execute(
            "SELECT text FROM indexed_chunk WHERE rel_path=? ORDER BY id", (rel,))]
        # Large CSV exports can contain hundreds of thousands of indexed characters.
        # Preserve chunk boundaries and source order, but keep the model payload bounded;
        # the validator still checks every returned quote against the complete V2 index.
        chunks = []
        chars = 0
        truncated = False
        for text in source_chunks:
            remaining = MAX_FILE_CHARS - chars
            if remaining <= 0:
                truncated = True
                break
            if len(text) > remaining:
                chunks.append(text[:remaining])
                chars += remaining
                truncated = True
                break
            chunks.append(text)
            chars += len(text)
        base = rel.rsplit("/", 1)[-1]
        ids = [e[0] for e in con.execute(
            "SELECT id FROM evidence WHERE source_title LIKE ? ORDER BY id", (f"%{base}%",))]
        blob = "\n".join(chunks).lower()
        known = [h for h in hosts if h.lower() in blob]
        files.append({"rel_path": rel, "chunks": chunks,
                      "source_chars": sum(len(t) for t in source_chunks),
                      "payload_chars": chars, "truncated": truncated,
                      "existing_evidence_ids": ids, "existing_hosts": known})
    return {"record_id": record_id, "files": files, "instructions": intake_instructions()}


# ---------------------------------------------------------------------------
def _quote_index(repo) -> sqlite3.Connection:
    """An in-memory index in the shape evidence_matrix.source_check reads, built from the
    repository's indexed_file / indexed_chunk mirror."""
    idx = sqlite3.connect(":memory:")
    idx.executescript(
        "create table files(file_id integer primary key, rel_path text, dup_of integer, archived integer default 0);"
        "create table chunk_map(chunk_id integer, file_id integer, line_start integer);"
        "create table chunks_content(id integer primary key, c0 text);")
    fid = 0
    for (rel,) in repo.con.execute("SELECT rel_path FROM indexed_file ORDER BY rel_path").fetchall():
        fid += 1
        idx.execute("insert into files(file_id, rel_path) values (?, ?)", (fid, rel))
        for n, (cid, text) in enumerate(repo.con.execute(
                "SELECT id, text FROM indexed_chunk WHERE rel_path=? ORDER BY id", (rel,)).fetchall()):
            idx.execute("insert into chunks_content(id, c0) values (?, ?)", (cid, text))
            idx.execute("insert into chunk_map values (?, ?, ?)", (cid, fid, n))
    return idx


def _check_row(row: dict, idx) -> tuple[bool, str]:
    status = row.get("status") or "VERIFIED"
    if status not in _STATUSES:
        return False, f"unknown status {status!r}"
    if not str(row.get("claim") or "").strip():
        return False, "no claim"
    if not str(row.get("source_title") or "").strip():
        return False, "no source_title"
    if status != "VERIFIED":
        return True, ""  # rests on reasoning or a search scope, not one quoted source
    em = _pkg._EM
    if em is None:
        return False, "evidence_matrix.py quote check not importable"
    res = em.source_check({"status": "VERIFIED", "source_title": row["source_title"],
                           "evidence_excerpt": row.get("excerpt")}, idx)
    if res.get("verdict") == "SOURCE_OK":
        return True, ""
    detail = {k: v for k, v in res.items() if k != "verdict"}
    return False, f"{res.get('verdict')}: {detail}" if detail else str(res.get("verdict"))


def _parse(agent_output_json):
    """Return {rel_path: entry-or-error-string}, or raise ValueError when nothing is usable."""
    data = agent_output_json
    if isinstance(data, (str, bytes)):
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        text = text.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
        data = json.loads(fence.group(1) if fence else text)
    if isinstance(data, dict) and isinstance(data.get("files"), list):
        data = data["files"]
    if isinstance(data, dict) and "rel_path" in data:
        data = [data]
    if not isinstance(data, list):
        raise ValueError("agent output must be a list of per-file objects (or an empty batch)")
    out = {}
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("rel_path"), str):
            out[item["rel_path"]] = item
    return out


def _item_evidence_ids(item, row_ids, evidence_ids):
    """Resolve provenance supplied by the model without allowing invented IDs.

    New evidence rows are not assigned IDs until this validator writes them, so the
    contract permits ``evidence_row_indexes`` alongside existing ``evidence_ids``.
    """
    ids = []
    for value in item.get("evidence_ids", []) if isinstance(item.get("evidence_ids", []), list) else [item.get("evidence_ids")]:
        ids.extend(_EVIDENCE_ID.findall(str(value or "")))
    for index in item.get("evidence_row_indexes", []) or []:
        if isinstance(index, int) and 0 <= index < len(row_ids):
            ids.append(row_ids[index])
    known = set(evidence_ids)
    return sorted({eid.upper() for eid in ids if eid.upper() in known or eid in row_ids})


def _validate_graph_items(items):
    errors = []
    for n, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"graph_items[{n}] must be an object")
            continue
        kind = item.get("kind")
        if kind not in _GRAPH_KINDS:
            errors.append(f"graph_items[{n}] has unsupported kind {kind!r}")
            continue
        required = {
            "host": ("name",),
            "address": ("ip", "owner_host"),
            "flow": ("src_host", "dst_host"),
            "service": ("host", "name"),
        }[kind]
        missing = [key for key in required if not str(item.get(key) or "").strip()]
        if missing:
            errors.append(f"graph_items[{n}] {kind} missing {', '.join(missing)}")
        if kind in {"flow", "service"} and item.get("port") is not None:
            try:
                if not 0 <= int(item["port"]) <= 65535:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"graph_items[{n}] invalid port")
        if kind == "host":
            classification = item.get("classification") or item.get("zone_kind")
            if classification is not None and str(classification).strip().lower() not in _ZONE_KINDS:
                errors.append(f"graph_items[{n}] invalid classification {classification!r}")
    return errors


def _apply_graph_items(r, items, rel, record_id, row_ids, summary):
    """Apply structured intake observations after evidence rows exist.

    Hosts are applied first. Endpoint hosts for a flow are explicit observations rather
    than inferred application ownership, and are labelled accordingly so an IP flow can
    be represented without losing the connection merely because its peer was not yet in
    the host register.
    """
    evidence_ids = [row[0] for row in r.con.execute("SELECT id FROM evidence").fetchall()]
    zone_updates = []
    ordered_items = sorted(items, key=lambda item: {"host": 0, "address": 1, "flow": 2, "service": 3}[item["kind"]])
    for item in ordered_items:
        kind = item["kind"]
        ids = _item_evidence_ids(item, row_ids, evidence_ids)
        note = f"intake {record_id} {rel}" + (f" evidence={','.join(ids)}" if ids else "")
        if kind == "host":
            if not r.con.execute("SELECT 1 FROM host WHERE name=?", (item["name"],)).fetchone():
                r.hosts.create(item["name"], role=item.get("role"), site=item.get("site"),
                               os=item.get("os"), actor="csa-evidence-investigator", note=note)
            classification = item.get("classification") or item.get("zone_kind")
            if classification:
                classification = str(classification).strip().lower()
                zone_updates.append({
                    "zone": item.get("zone") or ("OT" if classification == "ot" else "IT" if classification == "it" else ""),
                    "kind": classification,
                    "match": f"host:{item['name']}",
                    "basis": item.get("classification_basis") or note,
                    "reviewed": "no",
                })
                summary["zone_items"] += 1
            summary["host_items"] += 1
        elif kind == "address":
            owner = item["owner_host"]
            if not r.con.execute("SELECT 1 FROM host WHERE name=?", (owner,)).fetchone():
                r.hosts.create(owner, role="Observed network endpoint",
                               actor="csa-evidence-investigator", note=note)
            existing = r.con.execute("SELECT owner_host, scope FROM address WHERE ip=?", (item["ip"],)).fetchone()
            if existing and existing[0] not in (None, owner):
                raise ValueError(f"address {item['ip']} already belongs to {existing[0]}")
            r.con.execute("INSERT OR REPLACE INTO address(ip, scope, owner_host) VALUES (?, ?, ?)",
                          (item["ip"], item.get("scope"), owner))
            r._audit("csa-evidence-investigator", "intake.address", "address", item["ip"], note)
            summary["address_items"] += 1
        elif kind == "flow":
            for endpoint in (item["src_host"], item["dst_host"]):
                if not r.con.execute("SELECT 1 FROM host WHERE name=?", (endpoint,)).fetchone():
                    r.hosts.create(endpoint, role="Observed network endpoint",
                                   actor="csa-evidence-investigator", note=note)
            purpose = str(item.get("purpose") or "")
            if ids:
                purpose = (purpose + "; " if purpose else "") + "evidence=" + ",".join(ids)
            values = (item["src_host"], item["dst_host"], item.get("port"), item.get("protocol"), purpose)
            if not r.con.execute("SELECT 1 FROM flow WHERE src_host=? AND dst_host=? AND port IS ? AND protocol IS ? AND purpose=?", values).fetchone():
                r.con.execute("INSERT INTO flow(src_host,dst_host,port,protocol,purpose) VALUES (?,?,?,?,?)", values)
            summary["flow_items"] += 1
        elif kind == "service":
            host = item["host"]
            if not r.con.execute("SELECT 1 FROM host WHERE name=?", (host,)).fetchone():
                r.hosts.create(host, role="Observed network endpoint",
                               actor="csa-evidence-investigator", note=note)
            values = (host, item.get("provider_host"), item.get("port"), item.get("protocol"), item["name"])
            if not r.con.execute("SELECT 1 FROM service WHERE host=? AND provider_host IS ? AND port IS ? AND protocol IS ? AND name=?", values).fetchone():
                r.con.execute("INSERT INTO service(host,provider_host,port,protocol,name,configured) VALUES (?,?,?,?,?,?)",
                              (*values, int(bool(item.get("configured", False)))))
            r._audit("csa-evidence-investigator", "intake.service", "service", f"{host}/{item['name']}", note)
            summary["service_items"] += 1
    return zone_updates


def apply_batch(record_id, agent_output_json, *, repo, rel_paths=None, quote_index=None,
                refresh_graph=True) -> dict:
    """Validate and append one batch's agent output; returns the summary dict.

    `rel_paths` limits the batch to those files; by default every pending file of the record.
    """
    r = repo
    pending = [f["rel_path"] for f in r.intake.pending(record_id)]
    if rel_paths is not None:
        keep = set(rel_paths)
        pending = [p for p in pending if p in keep]
    summary = {"files_total": len(pending), "files_ok": 0, "files_failed": 0, "rows_added": 0,
               "rows_rejected": 0, "graph_nodes": 0, "graph_edges": 0,
               "host_items": 0, "address_items": 0, "flow_items": 0, "service_items": 0,
               "zone_items": 0,
               "rejected": [], "errors": {}}
    try:
        entries = _parse(agent_output_json)
        parse_error = None
    except (ValueError, TypeError) as e:
        entries, parse_error = {}, f"agent output is not usable JSON: {e}"
    owns_index = quote_index is None
    idx = quote_index or _quote_index(r)
    try:
        with r.tx():
            seen = {(c or "", s or "", p or "") for c, s, p in r.con.execute(
                "SELECT claim, source_title, page_or_location FROM evidence")}
            zone_updates = []
            for rel in pending:
                entry = entries.get(rel)
                error = parse_error
                rows = None
                if error is None:
                    if entry is None:
                        error = "no output for this file"
                    elif not isinstance(entry.get("rows", []), list) or \
                            not isinstance(entry.get("graph_items", []), list):
                        error = "malformed output: rows and graph_items must be lists"
                    else:
                        rows = entry.get("rows", [])
                        if any(not isinstance(x, dict) for x in rows):
                            error = "malformed output: every row must be an object"
                        else:
                            graph_errors = _validate_graph_items(entry.get("graph_items", []))
                            if graph_errors:
                                error = "malformed graph_items: " + "; ".join(graph_errors)
                if error is not None:
                    r.intake.complete_file(record_id, rel, error=error)
                    summary["files_failed"] += 1
                    summary["errors"][rel] = error
                    continue
                added = 0
                row_ids = []
                for row in rows:
                    ok, reason = _check_row(row, idx)
                    if not ok:
                        summary["rows_rejected"] += 1
                        summary["rejected"].append({"rel_path": rel, "claim": row.get("claim"),
                                                    "reason": reason})
                        continue
                    key = (row.get("claim") or "", row.get("source_title") or "",
                           row.get("page_or_location") or "")
                    if key in seen:
                        continue
                    seen.add(key)
                    evidence_id = r.evidence.create(
                        **{k: row.get(k) for k in _ROW_FIELDS if k != "status" and k in row},
                        status=row.get("status") or "VERIFIED",
                        actor="csa-evidence-investigator", note=f"intake {record_id} {rel}")
                    row_ids.append(evidence_id)
                    added += 1
                zone_updates.extend(_apply_graph_items(r, entry.get("graph_items", []), rel, record_id, row_ids, summary))
                if r.con.execute("SELECT 1 FROM evidence_source WHERE rel_path=?", (rel,)).fetchone() is None:
                    sha = r.con.execute("SELECT sha256 FROM intake_file WHERE record_id=? AND rel_path=?",
                                        (record_id, rel)).fetchone()
                    r.con.execute("INSERT INTO evidence_source (rel_path, sha256, indexed_at) VALUES (?, ?, ?)",
                                  (rel, sha[0] if sha else None, r._now()))
                r.intake.complete_file(record_id, rel, rows_added=added)
                summary["files_ok"] += 1
                summary["rows_added"] += added
            if zone_updates:
                from csa_docx import zones
                summary["zone_rules_changed"] = zones.upsert_host_rules(r.path.parent, zone_updates)
            if refresh_graph:
                counts = r.graph.refresh()
                summary["graph_nodes"] = counts["graph_node"]
                summary["graph_edges"] = counts["graph_edge"]
    finally:
        if owns_index:
            idx.close()
    return summary
