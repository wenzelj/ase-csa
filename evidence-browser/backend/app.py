from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENTS_DIR = Path(__file__).resolve().parents[2]
SYSTEMS = {
    "iamps": {"label": "IAMPS", "project_key": "iamps-08"},
    "utcdtc": {"label": "UTC DTC", "project_key": "utcdtc"},
    "tetra": {"label": "TETRA", "project_key": "tetra-reveloc"},
}
ANSWERED = "LIKELY_ANSWERED"
TEXT_EXTENSIONS = {
    "", ".txt", ".log", ".xml", ".csv", ".json", ".md", ".ps1", ".cfg",
    ".conf", ".ini", ".inf", ".bat", ".yaml", ".yml", ".html", ".htm",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx"}
FAMILY_RULES = (
    ("Host", ("host", "systeminfo", "computer")),
    ("Time", ("time", "ntp", "w32tm")),
    ("Network", ("network", "route", "listener", "port", "firewall", "flow")),
    ("DNS", ("dns", "resolver")),
    ("Software", ("software", "application", "installed")),
    ("Services", ("service", "process")),
    ("Identity", ("account", "admin", "group", "user", "identity")),
    ("Policy", ("policy", "gpo", "gpresult")),
    ("Storage", ("disk", "volume", "storage", "share")),
)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    host: str | None = None
    include_archive: bool = False
    all_captures: bool = False


class EvidenceDraft(BaseModel):
    csa_area: str
    question: str
    claim: str
    status: Literal["VERIFIED", "INFERRED", "UNCONFIRMED", "CONFLICTING", "NOT_FOUND"]
    source_title: str = ""
    source_version: str = ""
    section: str = ""
    page_or_location: str = ""
    evidence_excerpt: str = ""
    inference_reason: str = ""
    confidence: Literal["", "high", "medium", "low"] = ""
    gap_or_action: str = ""
    review_state: str = "pending"


class CommitRequest(BaseModel):
    draft: EvidenceDraft
    confirmed: bool


def agents_dir() -> Path:
    return Path(os.environ.get("CSA_AGENTS_DIR", DEFAULT_AGENTS_DIR)).resolve()


def _parse_registry(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise HTTPException(503, f"Project registry is unavailable: {path}")
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped == "projects:":
            continue
        if stripped.startswith("- key:"):
            if current:
                items.append(current)
            current = {"key": stripped.split(":", 1)[1].strip().strip("\"'")}
        elif current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = value.strip().strip("\"'")
    if current:
        items.append(current)
    return items


def projects() -> dict[str, dict[str, str]]:
    path = Path(os.environ.get("CSA_PROJECTS_FILE", agents_dir() / "csa-context" / "PROJECTS.yaml"))
    return {p["key"]: p for p in _parse_registry(path)}


def system_project(system_key: str) -> dict[str, str]:
    if system_key not in SYSTEMS:
        raise HTTPException(404, "Unknown evidence system")
    project_key = SYSTEMS[system_key]["project_key"]
    project = projects().get(project_key)
    if not project:
        raise HTTPException(503, f"Registered project '{project_key}' is unavailable")
    return project


def work_dir(project: dict[str, str]) -> Path:
    return Path(project["work_dir"]).expanduser()


def open_index(project: dict[str, str]) -> sqlite3.Connection:
    db = work_dir(project) / "discovery-index.sqlite"
    if not db.is_file():
        raise HTTPException(503, f"Discovery index is unavailable: {db}")
    con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def run_json(command: list[str], *, stdin: str | None = None) -> dict[str, Any]:
    process = subprocess.run(command, input=stdin, capture_output=True, text=True)
    output = process.stdout.strip()
    try:
        data = json.loads(output) if output else {}
    except json.JSONDecodeError:
        raise HTTPException(502, process.stderr.strip() or output or "CSA helper returned invalid output")
    if process.returncode:
        detail = data.get("message") or data.get("error") or process.stderr.strip() or "CSA helper failed"
        raise HTTPException(422, {"message": detail, "result": data})
    return data


def matrix_script() -> Path:
    return agents_dir() / "skills" / "csa-evidence-matrix" / "scripts" / "evidence_matrix.py"


def index_script() -> Path:
    return agents_dir() / "skills" / "csa-discovery-index" / "scripts" / "discovery_index.py"


def reviews_for(project: dict[str, str]) -> dict[str, dict[str, Any]]:
    path = work_dir(project) / "evidence-reviews.jsonl"
    reviews: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                reviews[row["evidence_id"].upper()] = row
    return reviews


def overlay_review(row: dict[str, Any], reviews: dict[str, dict[str, Any]]) -> dict[str, Any]:
    review = reviews.get(str(row.get("evidence_id", "")).upper())
    if review:
        row = {**row, "review_state": review.get("state", "pending"),
               "reviewed_by": review.get("by"), "reviewed_at": review.get("at")}
    return row


def scope_clause(all_captures: bool, include_archive: bool, alias: str = "f") -> tuple[str, list[Any]]:
    clauses: list[str] = []
    if not include_archive:
        clauses.append(f"{alias}.archived=0")
    if not all_captures:
        clauses.append(
            f"({alias}.capture_id IS NULL OR {alias}.capture_id IN "
            "(SELECT capture_id FROM captures WHERE superseded_by IS NULL))"
        )
    return " AND ".join(clauses) or "1=1", []


def family(value: str) -> str:
    lower = value.lower()
    for name, terms in FAMILY_RULES:
        if any(term in lower for term in terms):
            return name
    return "Other"


def source_roots(project: dict[str, str]) -> list[Path]:
    raw = [project.get("default_source_set", "")]
    raw.extend(project.get("index_extra_sources", "").split(";"))
    return [Path(p.strip()).expanduser().resolve() for p in raw if p.strip()]


def safe_file(project: dict[str, str], file_id: int) -> tuple[sqlite3.Row, Path]:
    con = open_index(project)
    row = con.execute("SELECT * FROM files WHERE file_id=?", (file_id,)).fetchone()
    con.close()
    if row is None:
        raise HTTPException(404, "Indexed file was not found")
    path = (Path(project["project_root"]) / row["rel_path"]).resolve()
    allowed = source_roots(project)
    if not any(path == root or root in path.parents for root in allowed):
        raise HTTPException(403, "Indexed path is outside configured evidence sources")
    if not path.is_file():
        raise HTTPException(404, f"Source file is unavailable: {path.name}")
    return row, path


def parse_anchor(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    match = re.search(r"lines?\s+(\d+)(?:-(\d+))?", value, re.I)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2) or match.group(1))


def text_preview(path: Path, anchor: str | None) -> dict[str, Any]:
    data = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    lines = (text or "").splitlines()
    start, end = parse_anchor(anchor)
    if start:
        first, last = max(1, start - 80), min(len(lines), (end or start) + 120)
    else:
        first, last = 1, min(len(lines), 2000)
    return {
        "kind": "text", "name": path.name, "line_start": first,
        "lines": [{"number": i, "text": lines[i - 1]} for i in range(first, last + 1)],
        "highlight": [start, end] if start else None,
        "truncated": last < len(lines), "total_lines": len(lines),
    }


def xlsx_preview(path: Path, anchor: str | None) -> dict[str, Any]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet_name, target_row = workbook.sheetnames[0], 1
    if anchor:
        match = re.search(r"(?:sheet!row\s+)?([^!]+)!(\d+)", anchor, re.I)
        if match and match.group(1) in workbook.sheetnames:
            sheet_name, target_row = match.group(1), int(match.group(2))
    sheet = workbook[sheet_name]
    first = max(1, target_row - 30)
    last = min(sheet.max_row, target_row + 70)
    sheet_names = list(workbook.sheetnames)
    total_rows = sheet.max_row
    rows = [["" if cell.value is None else str(cell.value) for cell in row[:40]]
            for row in sheet.iter_rows(min_row=first, max_row=last)]
    workbook.close()
    return {"kind": "grid", "name": path.name, "sheets": sheet_names,
            "sheet": sheet_name, "row_start": first, "rows": rows,
            "highlight_row": target_row, "total_rows": total_rows}


def extracted_document_preview(project: dict[str, str], file_id: int, path: Path, anchor: str | None) -> dict[str, Any]:
    con = open_index(project)
    file_row = con.execute("SELECT coalesce(dup_of,file_id) source_id FROM files WHERE file_id=?", (file_id,)).fetchone()
    chunks = con.execute(
        "SELECT m.line_start, c.content FROM chunk_map m JOIN chunks c ON c.rowid=m.chunk_id "
        "WHERE m.file_id=? ORDER BY m.line_start", (file_row["source_id"],)
    ).fetchall()
    con.close()
    line_map: dict[int, str] = {}
    for chunk in chunks:
        for offset, value in enumerate(chunk["content"].splitlines()):
            tagged = re.match(r"\x1f(\d+)\x1f(.*)", value)
            number = int(tagged.group(1)) if tagged else chunk["line_start"] + offset
            line_map.setdefault(number, tagged.group(2) if tagged else value)
    start, end = parse_anchor(anchor)
    keys = sorted(line_map)
    if start:
        keys = [key for key in keys if max(1, start - 80) <= key <= (end or start) + 120]
    else:
        keys = keys[:2000]
    return {"kind": "document", "name": path.name,
            "lines": [{"number": key, "text": line_map[key]} for key in keys],
            "highlight": [start, end] if start else None}


def render_office(path: Path) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise HTTPException(503, "LibreOffice preview runtime is unavailable")
    fingerprint = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}:{path.stat().st_size}".encode()).hexdigest()[:20]
    cache = Path(tempfile.gettempdir()) / "csa-evidence-preview" / fingerprint
    output = cache / f"{path.stem}.pdf"
    if output.is_file():
        return output
    cache.mkdir(parents=True, exist_ok=True)
    process = subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(cache), str(path)],
                             capture_output=True, text=True, timeout=120)
    if process.returncode or not output.is_file():
        raise HTTPException(502, process.stderr.strip() or "Document preview conversion failed")
    return output


app = FastAPI(title="CSA Evidence Workspace", version="0.1.0")


@app.get("/api/systems")
def get_systems() -> dict[str, Any]:
    registered = projects()
    return {"systems": [{"key": key, "label": cfg["label"], "project_key": cfg["project_key"],
                         "available": cfg["project_key"] in registered} for key, cfg in SYSTEMS.items()]}


@app.get("/api/systems/{system_key}/summary")
def get_summary(system_key: str) -> dict[str, Any]:
    project = system_project(system_key)
    con = open_index(project)
    meta = dict(con.execute("SELECT key,value FROM meta").fetchall())
    statuses = {row[0]: row[1] for row in con.execute("SELECT status,count(*) FROM files GROUP BY status")}
    captures = con.execute("SELECT count(*), sum(CASE WHEN superseded_by IS NULL AND archived=0 THEN 1 ELSE 0 END) FROM captures").fetchone()
    scope, _ = scope_clause(False, False)
    coverage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    capture_rows = con.execute(
        f"SELECT coalesce(f.host,'Documents') host, f.rel_path FROM files f WHERE {scope} AND f.status='indexed'"
    ).fetchall()
    for row in capture_rows:
        coverage[row["host"]][family(row["rel_path"])] += 1
    matrix = work_dir(project) / "evidence-matrix.csv"
    evidence_count = 0
    if matrix.is_file():
        with matrix.open(encoding="utf-8-sig", newline="") as handle:
            evidence_count = sum(1 for _ in csv.DictReader(handle))
    con.close()
    families = [name for name, _ in FAMILY_RULES] + ["Other"]
    return {"system": system_key, "label": SYSTEMS[system_key]["label"], "project_key": project["key"],
            "built_at_utc": meta.get("built_at_utc"), "index_complete": meta.get("complete") == "1",
            "captures": captures[0] or 0, "current_captures": captures[1] or 0,
            "files_by_status": statuses, "evidence_rows": evidence_count, "families": families,
            "coverage": [{"host": host, "families": dict(values)} for host, values in sorted(coverage.items())]}


@app.post("/api/systems/{system_key}/search")
def search(system_key: str, request: SearchRequest) -> dict[str, Any]:
    project = system_project(system_key)
    matrix = run_json([sys.executable, str(matrix_script()), "--workspace", project["project_root"],
                       "lookup", request.query, "--limit", "12"])
    reviews = reviews_for(project)
    matrix["matches"] = [overlay_review(row, reviews) for row in matrix.get("matches", [])]
    stages: list[dict[str, Any]] = [{"kind": "matrix", "state": "complete", **matrix}]
    if matrix.get("verdict") != ANSWERED:
        command = [sys.executable, str(index_script()), "--project", project["key"], "search", request.query,
                   "--limit", "40", "--per-file", "3"]
        if request.host:
            command += ["--host", request.host]
        if request.include_archive:
            command.append("--include-archive")
        if request.all_captures:
            command.append("--all-captures")
        index = run_json(command)
        con = open_index(project)
        for hit in index.get("results", []):
            file_row = con.execute("SELECT file_id FROM files WHERE rel_path=?", (hit.get("rel_path"),)).fetchone()
            hit["file_id"] = file_row[0] if file_row else None
        con.close()
        stages.append({"kind": "index", "state": "complete", **index})
    return {"system": system_key, "query": request.query, "stages": stages}


@app.get("/api/systems/{system_key}/evidence")
def evidence(system_key: str, q: str = "", status: str = "", area: str = "", offset: int = 0,
             limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    project = system_project(system_key)
    matrix = work_dir(project) / "evidence-matrix.csv"
    if not matrix.is_file():
        raise HTTPException(404, "Evidence matrix is unavailable")
    reviews = reviews_for(project)
    with matrix.open(encoding="utf-8-sig", newline="") as handle:
        rows = [overlay_review(dict(row), reviews) for row in csv.DictReader(handle)]
    if q:
        words = q.casefold().split()
        rows = [row for row in rows if all(word in " ".join(row.values()).casefold() for word in words)]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if area:
        rows = [row for row in rows if row.get("csa_area") == area]
    return {"total": len(rows), "rows": rows[offset:offset + limit],
            "areas": sorted({row.get("csa_area", "") for row in rows if row.get("csa_area")})}


@app.get("/api/systems/{system_key}/files")
def files(system_key: str, q: str = "", host: str = "", ext: str = "", status: str = "", source_class: str = "",
          all_captures: bool = False, include_archive: bool = False, offset: int = 0,
          limit: int = Query(150, ge=1, le=500)) -> dict[str, Any]:
    project = system_project(system_key)
    con = open_index(project)
    scope, params = scope_clause(all_captures, include_archive)
    clauses = [scope]
    if q:
        clauses.append("(f.rel_path LIKE ? OR coalesce(f.host,'') LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    for field, value in (("host", host), ("ext", ext), ("status", status), ("source_class", source_class)):
        if value:
            clauses.append(f"f.{field} LIKE ?")
            params.append(f"%{value}%")
    where = " AND ".join(clauses)
    total = con.execute(f"SELECT count(*) FROM files f WHERE {where}", params).fetchone()[0]
    rows = [dict(row) for row in con.execute(
        "SELECT f.file_id,f.rel_path,f.host,f.ext,f.size,f.status,f.reason,f.source_class,f.archived,"
        "c.capture_utc,c.superseded_by,CASE WHEN c.capture_id IS NULL OR c.superseded_by IS NULL THEN 1 ELSE 0 END current "
        f"FROM files f LEFT JOIN captures c ON c.capture_id=f.capture_id WHERE {where} "
        "ORDER BY coalesce(f.host,''),f.rel_path LIMIT ? OFFSET ?", params + [limit, offset]
    )]
    facets = {
        "statuses": [row[0] for row in con.execute("SELECT DISTINCT status FROM files ORDER BY status")],
        "extensions": [row[0] for row in con.execute("SELECT DISTINCT ext FROM files ORDER BY ext")],
        "source_classes": [row[0] for row in con.execute("SELECT DISTINCT source_class FROM files ORDER BY source_class")],
    }
    con.close()
    return {"total": total, "files": rows, "facets": facets}


@app.get("/api/systems/{system_key}/files/{file_id}/preview")
def preview(system_key: str, file_id: int, anchor: str | None = None, mode: str = "preview"):
    project = system_project(system_key)
    row, path = safe_file(project, file_id)
    ext = path.suffix.lower()
    if mode == "raw":
        return FileResponse(path, filename=path.name, content_disposition_type="inline")
    if mode == "pdf":
        if ext == ".pdf":
            return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")
        if ext in OFFICE_EXTENSIONS:
            return FileResponse(render_office(path), media_type="application/pdf", content_disposition_type="inline")
        raise HTTPException(400, "This file does not have a PDF preview")
    if ext in TEXT_EXTENSIONS:
        result = text_preview(path, anchor)
    elif ext == ".xlsx":
        result = xlsx_preview(path, anchor)
    elif ext == ".pdf" or ext in OFFICE_EXTENSIONS:
        result = extracted_document_preview(project, file_id, path, anchor)
        result["pdf_url"] = f"/api/systems/{system_key}/files/{file_id}/preview?mode=pdf"
    elif ext in IMAGE_EXTENSIONS:
        result = {"kind": "image", "name": path.name,
                  "raw_url": f"/api/systems/{system_key}/files/{file_id}/preview?mode=raw"}
    else:
        result = {"kind": "unsupported", "name": path.name, "reason": row["reason"],
                  "raw_url": f"/api/systems/{system_key}/files/{file_id}/preview?mode=raw"}
    result.update({"file_id": file_id, "rel_path": row["rel_path"], "status": row["status"],
                   "reason": row["reason"], "size": row["size"]})
    return result


@app.get("/api/systems/{system_key}/evidence/{evidence_id}/sources")
def evidence_sources(system_key: str, evidence_id: str) -> dict[str, Any]:
    project = system_project(system_key)
    data = evidence(system_key, q="", limit=500)
    target = next((row for row in data["rows"] if row["evidence_id"].upper() == evidence_id.upper()), None)
    if not target:
        raise HTTPException(404, "Evidence row was not found")
    names = re.findall(r"[\w.\-]+\.(?:txt|csv|xlsx|docx|doc|pdf|md|log|json|xml|ps1|pptx)\b",
                       target.get("source_title", ""), re.I)
    con = open_index(project)
    matches: list[dict[str, Any]] = []
    for name in sorted(set(names)):
        rows = con.execute("SELECT file_id,rel_path,host,status FROM files WHERE rel_path LIKE ?", (f"%/{name}",)).fetchall()
        matches.extend(dict(row) for row in rows)
    con.close()
    return {"evidence": target, "sources": matches,
            "state": "found" if len(matches) == 1 else "ambiguous" if matches else "unavailable"}


@app.get("/api/systems/{system_key}/tables")
def tables(system_key: str, table: str = "", host: str = "", where: str = "", limit: int = 100) -> dict[str, Any]:
    project = system_project(system_key)
    if not table:
        return run_json([sys.executable, str(index_script()), "--project", project["key"], "tables"])
    command = [sys.executable, str(index_script()), "--project", project["key"], "rows", table,
               "--limit", str(min(max(limit, 1), 500))]
    if host:
        command += ["--host", host]
    if where:
        command += ["--where", where]
    return run_json(command)


def evidence_command(project: dict[str, str], draft: EvidenceDraft, dry_run: bool) -> dict[str, Any]:
    command = [sys.executable, str(matrix_script()), "--workspace", project["project_root"], "append",
               "--agent", "csa evidence workspace", "--context", "browser evidence review", "--rows-file", "-"]
    if dry_run:
        command.append("--dry-run")
    return run_json(command, stdin=json.dumps(draft.model_dump(), ensure_ascii=False))


@app.post("/api/systems/{system_key}/evidence-drafts/validate")
def validate_evidence(system_key: str, draft: EvidenceDraft) -> dict[str, Any]:
    return evidence_command(system_project(system_key), draft, True)


@app.post("/api/systems/{system_key}/evidence-drafts/commit")
def commit_evidence(system_key: str, request: CommitRequest) -> dict[str, Any]:
    if not request.confirmed:
        raise HTTPException(409, "Evidence append requires explicit confirmation")
    return evidence_command(system_project(system_key), request.draft, False)


DIST = APP_ROOT / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="workspace")
