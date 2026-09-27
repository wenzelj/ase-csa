#!/usr/bin/env python3
"""CSA discovery index -- a rebuildable SQLite index of a project's Discovery Data.

Stdlib only (Python 3.8+, SQLite with JSON1; FTS5 used when available).

The index is a *search aid*, not evidence. Every result carries a `cite` block
(source_title / source_version / page_or_location / evidence_excerpt) that points
back to the original file and line, in the same shape as evidence-matrix.csv rows.

Commands (all output JSON):
  build   [--budget SECONDS] [--rebuild] [--stage-dir DIR]   build or refresh the index
  status                                                     what is indexed / skipped
  hosts                                                      captures per host, current vs superseded
  tables  [pattern]                                          structured tables and their columns
  rows    <table> [--where COL~text|COL=text|COL!~text ...] [--host H] [--cols a,b] [--distinct COL]
  search  "<terms>" [--host H] [--path-like PATTERN] [--any] [--all-captures] [--include-archive]
  sql     "SELECT ..."                                       read-only query

Always pass --project <key> (from csa-context/PROJECTS.yaml) or --workspace <project_root>.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

SCHEMA_VERSION = 1
FRAMEWORK_DIR = Path(__file__).resolve().parents[3]  # .agents
BASE_DIR = FRAMEWORK_DIR.parent
INDEX_NAME = "discovery-index.sqlite"

CAPTURE_RE = re.compile(r"^(?P<collector>[A-Za-z0-9]+)_discovery_(?P<host>.+)_(?P<ts>\d{8}T\d{6}Z)$")
# Captures whose folder carries no host name (e.g. tg_discovery_20260317T002415Z): the host is
# read from the capture's own 00_host_summary.txt ("Host: <name>").
HOSTLESS_CAPTURE_RE = re.compile(r"^(?P<collector>[A-Za-z0-9]+)_discovery_(?P<ts>\d{8}T\d{6}Z)$")
_HOST_LINE_RE = re.compile(r"^\s*(?:Host|HostName|Computer ?Name)\s*:\s*(\S+)", re.I | re.M)
_summary_host_cache = {}


def _host_from_summary(folder):
    """Host name from <capture folder>/00_host_summary.txt, or None."""
    if folder in _summary_host_cache:
        return _summary_host_cache[folder]
    host = None
    for name in ("00_host_summary.txt",):
        f = Path(folder) / name
        if f.is_file():
            m = _HOST_LINE_RE.search(decode(f.read_bytes()[:4096]))
            if m:
                host = m.group(1).strip().upper()
    _summary_host_cache[folder] = host
    return host
ARCHIVE_PARTS = {"archive", "z_archive", "_to_delete", "old", "superseded"}
DERIVED_PARTS = {"discovery_consolidated"}
SKIP_DIRS = {".git", "__MACOSX", ".pytest_cache", "__pycache__", "csa-work", "csa-authoring-active"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}
BINARY_EXT = {".dll", ".exe", ".dat", ".w001", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
              ".svg", ".msi", ".cab", ".pdb", ".sys", ".bin", ".iso", ".7z", ".gz", ".tar", ".lnk",
              ".mp4", ".mov", ".vsdx", ".pptx", ".xls", ".doc", ".db", ".sqlite", ".pyc", ".bak"}
# Large renderings that duplicate a text equivalent in the same capture.
SKIP_NAME_RE = re.compile(r"(gpresult\.html|gpresult\.xml|_logs_dns_ntp_auth\.xml)$", re.I)
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_CSV_BYTES = 64 * 1024 * 1024
SPARSE_XML_BYTES = 1024 * 1024      # larger XML: index only the structural (non-repeating) elements
SPARSE_TAG_REPEAT = 200
LINE_TAG = re.compile(r"^@(\d+)\| ")
CHUNK_LINES = 30
MAX_ROWS_PER_FILE = 20000
MAX_EXCERPT = 1200


# --------------------------------------------------------------------------- project resolution
def load_registry():
    path = (Path(os.environ["CSA_PROJECTS_FILE"]) if os.environ.get("CSA_PROJECTS_FILE")
            else FRAMEWORK_DIR / "csa-context" / "PROJECTS.yaml")
    projects, cur = [], {}
    if not path.is_file():
        return []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or raw[:1] not in (" ", "\t"):
            continue
        if s.startswith("- key:"):
            if cur:
                projects.append(cur)
            cur = {}
            s = s[2:]
        if ":" in s:
            k, _, v = s.partition(":")
            cur[k.strip()] = v.strip().strip('"').strip("'")
    if cur:
        projects.append(cur)
    return projects


def remap(p, project):
    """Registry paths are absolute on the author's Mac. If they do not exist here (for
    example the folder is mounted elsewhere), re-root them under this framework's parent."""
    path = Path(p).expanduser()
    if path.exists():
        return path
    ctx = project.get("project_context")
    if ctx:
        reg_base = Path(ctx).parents[2]
        try:
            return BASE_DIR / path.relative_to(reg_base)
        except ValueError:
            pass
    return path


def resolve_project(args):
    projects = load_registry()
    if args.project:
        for p in projects:
            if p.get("key") == args.project:
                return p, remap(p["project_root"], p)
        fail("PROJECT_NOT_REGISTERED", f"no project with key '{args.project}' in PROJECTS.yaml",
             known=[p.get("key") for p in projects])
    ws = Path(args.workspace or os.environ.get("CSA_WORKSPACE") or os.getcwd()).expanduser().resolve()
    for p in projects:
        root = remap(p["project_root"], p).resolve()
        if ws == root or root in ws.parents:
            return p, root
    fail("WORKSPACE_NOT_REGISTERED", f"{ws} is not under a registered project_root; pass --project",
         known=[p.get("key") for p in projects])


def fail(code, msg, **extra):
    print(json.dumps(dict(status="ERROR", code=code, message=msg, **extra), indent=2))
    sys.exit(2)


def emit(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- decoding / parsing
def decode(b):
    if b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        return b.decode("utf-16", "replace")
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace")
    head = b[:4096]
    if len(head) >= 8 and head[1::2].count(0) > len(head) // 4 and head[0::2].count(0) == 0:
        return b.decode("utf-16-le", "replace")
    if b"\x00" in head:
        return None  # binary
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1252", "replace")


DASH_RE = re.compile(r"^\s*-{2,}(\s+-{2,})*\s*$")
KV_RE = re.compile(r"^([A-Za-z][\w .\-/()#]{0,60}?)\s*:\s?(.*)$")


def uniq_names(names):
    out, seen = [], {}
    for i, n in enumerate(names):
        n = n or f"col{i + 1}"
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 1
        out.append(n)
    return out


def parse_format_table(lines):
    """PowerShell Format-Table: header line, dashed underline, rows until blank."""
    blocks, i = [], 0
    while i < len(lines) - 1:
        if lines[i].strip() and DASH_RE.match(lines[i + 1]):
            header, dash = lines[i], lines[i + 1]
            runs = [m.start() for m in re.finditer(r"-+", dash)]
            bounds = [(s, runs[k + 1] if k + 1 < len(runs) else None) for k, s in enumerate(runs)]
            names = uniq_names([(header[s:e] if e else header[s:]).strip() for s, e in bounds])
            rows, j = [], i + 2
            while j < len(lines) and lines[j].strip():
                l = lines[j]
                rows.append((j + 1, {n: (l[s:e] if e else l[s:]).strip() for n, (s, e) in zip(names, bounds)}))
                j += 1
            if rows:
                blocks.append(("table", rows))
            i = j
            continue
        i += 1
    return blocks


def parse_format_list(lines):
    """PowerShell Format-List: 'Key : value' records separated by blank lines."""
    records, cur, cur_line, last = [], {}, None, None
    for n, l in enumerate(lines + [""], start=1):
        if not l.strip():
            if len(cur) >= 2:
                records.append((cur_line, cur))
            cur, cur_line, last = {}, None, None
            continue
        if l[:1] in (" ", "\t") and last is not None and cur:
            cur[last] = (cur[last] + " " + l.strip()).strip()
            continue
        m = KV_RE.match(l)
        if not m:
            cur, cur_line, last = {}, None, None  # not a list block; abandon
            continue
        k = m.group(1).strip()
        if k in cur:  # repeated key inside one block -> start new record
            if len(cur) >= 2:
                records.append((cur_line, cur))
            cur, cur_line = {}, None
        cur[k] = m.group(2).strip()
        cur_line = cur_line or n
        last = k
    return [("list", records)] if records else []


def parse_csv_text(text):
    lines = text.splitlines()
    if lines and lines[0].startswith("#TYPE"):
        lines = lines[1:]
    rdr = csv.reader(io.StringIO("\n".join(lines)))
    try:
        header = next(rdr)
    except StopIteration:
        return []
    names = uniq_names([h.strip() for h in header])
    rows = []
    for n, rec in enumerate(rdr, start=2):
        if not any(c.strip() for c in rec):
            continue
        rows.append((n, dict(zip(names, rec))))
    return [("csv", rows)] if rows else []


XNS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref or "A")
    v = 0
    for ch in (letters.group(0) if letters else "A"):
        v = v * 26 + ord(ch) - 64
    return v - 1


def xlsx_sheets(path):
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(XNS + "si"):
                shared.append("".join(t.text or "" for t in si.iter(XNS + "t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap = {r.get("Id"): r.get("Target") for r in rels}
        rid_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        for s in wb.iter(XNS + "sheet"):
            target = (relmap.get(s.get(rid_attr)) or "").lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            if target not in names:
                continue
            grid = []
            for row in ET.fromstring(z.read(target)).iter(XNS + "row"):
                vals = {}
                for c in row.iter(XNS + "c"):
                    t, v = c.get("t"), c.find(XNS + "v")
                    if t == "s" and v is not None:
                        val = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(XNS + "t"))
                    else:
                        val = v.text if v is not None and v.text is not None else ""
                    if val != "":
                        vals[col_index(c.get("r"))] = val
                if vals:
                    width = max(vals) + 1
                    grid.append((int(row.get("r") or len(grid) + 1), [vals.get(i, "") for i in range(width)]))
                if len(grid) >= MAX_ROWS_PER_FILE:
                    break
            yield s.get("name"), grid


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = []
    for p in re.split(r"</w:p>", xml):
        t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
        if t.strip():
            paras.append(t)
    import html
    return "\n".join(html.unescape(x) for x in paras)


def pdf_text(path):
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-layout", str(path), "-"], capture_output=True, timeout=120)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


# --------------------------------------------------------------------------- schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS captures(
  capture_id INTEGER PRIMARY KEY, folder TEXT UNIQUE, host TEXT, collector TEXT, capture_utc TEXT,
  archived INTEGER DEFAULT 0, superseded_by INTEGER, file_count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS files(
  file_id INTEGER PRIMARY KEY, rel_path TEXT UNIQUE, capture_id INTEGER, host TEXT, ext TEXT,
  size INTEGER, mtime REAL, sha1 TEXT, status TEXT, reason TEXT, dup_of INTEGER,
  source_class TEXT, archived INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS files_sha1 ON files(sha1);
CREATE TABLE IF NOT EXISTS rows(
  file_id INTEGER, table_name TEXT, fmt TEXT, block_no INTEGER, line_no INTEGER, data TEXT);
CREATE INDEX IF NOT EXISTS rows_table ON rows(table_name);
CREATE INDEX IF NOT EXISTS rows_file ON rows(file_id);
CREATE TABLE IF NOT EXISTS chunk_map(chunk_id INTEGER PRIMARY KEY, file_id INTEGER, line_start INTEGER, line_end INTEGER);
CREATE INDEX IF NOT EXISTS chunk_file ON chunk_map(file_id);
"""


def has_fts5(con):
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp._fts_probe USING fts5(x)")
        con.execute("DROP TABLE temp._fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def init_db(con):
    con.executescript(SCHEMA)
    if has_fts5(con):
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(content, tokenize='unicode61')")
        fts = "1"
    else:
        con.execute("CREATE TABLE IF NOT EXISTS chunks(rowid INTEGER PRIMARY KEY, content TEXT)")
        fts = "0"
    con.execute("INSERT OR REPLACE INTO meta VALUES('fts5', ?)", (fts,))
    con.execute("INSERT OR REPLACE INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))


# --------------------------------------------------------------------------- build
def classify(rel_parts, root=None):
    low = [p.lower() for p in rel_parts]
    archived = int(any(p in ARCHIVE_PARTS or p.startswith("z_") for p in low[:-1]))
    derived = any(p in DERIVED_PARTS for p in low[:-1])
    capture = None
    for i, p in enumerate(rel_parts[:-1]):
        m = CAPTURE_RE.match(p)
        if m:
            capture = (p, m.group("host").upper(), m.group("collector"), m.group("ts"))
            continue
        m = HOSTLESS_CAPTURE_RE.match(p)
        if m:
            folder = Path(*rel_parts[: i + 1])
            if root is not None and not folder.is_absolute():
                folder = Path(root) / folder
            host = _host_from_summary(folder)
            if host:
                capture = (p, host, m.group("collector"), m.group("ts"))
    return archived, derived, capture


def table_name_for(fname):
    stem = Path(fname).stem
    return re.sub(r"^\d+[A-Z]?_", "", stem).lower()


def drop_content(con, file_id):
    ids = [r[0] for r in con.execute("SELECT chunk_id FROM chunk_map WHERE file_id=?", (file_id,))]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        con.execute(f"DELETE FROM chunks WHERE rowid IN ({q})", part)
    con.execute("DELETE FROM chunk_map WHERE file_id=?", (file_id,))
    con.execute("DELETE FROM rows WHERE file_id=?", (file_id,))


def add_sparse(con, file_id, numbered):
    """numbered: [(line_no, text)] - non-contiguous lines; each stored as '@<n>| text'."""
    for s in range(0, len(numbered), CHUNK_LINES):
        part = numbered[s:s + CHUNK_LINES]
        cur = con.execute("INSERT INTO chunks(content) VALUES(?)", ("\n".join(f"@{n}| {t}" for n, t in part),))
        con.execute("INSERT INTO chunk_map VALUES(?,?,?,?)", (cur.lastrowid, file_id, part[0][0], part[-1][0]))


def sparse_xml(lines):
    tags = [re.match(r"\s*<([A-Za-z_][\w.:-]*)", l) for l in lines]
    freq = {}
    for m in tags:
        if m:
            freq[m.group(1)] = freq.get(m.group(1), 0) + 1
    return [(i + 1, l.strip()) for i, (l, m) in enumerate(zip(lines, tags))
            if l.strip() and m and freq[m.group(1)] <= SPARSE_TAG_REPEAT]


def add_text(con, file_id, text):
    lines = text.splitlines()
    for s in range(0, len(lines), CHUNK_LINES):
        part = lines[s:s + CHUNK_LINES]
        if not any(x.strip() for x in part):
            continue
        cur = con.execute("INSERT INTO chunks(content) VALUES(?)", ("\n".join(part),))
        con.execute("INSERT INTO chunk_map VALUES(?,?,?,?)", (cur.lastrowid, file_id, s + 1, s + len(part)))
    return lines


def add_rows(con, file_id, tname, blocks):
    n = 0
    for b, (fmt, rows) in enumerate(blocks, start=1):
        for line_no, data in rows:
            if n >= MAX_ROWS_PER_FILE:
                return n
            con.execute("INSERT INTO rows VALUES(?,?,?,?,?,?)",
                        (file_id, tname, fmt, b, line_no,
                         json.dumps({k: v for k, v in data.items() if v not in ("", None)}, ensure_ascii=False)))
            n += 1
    return n


def index_file(con, file_id, path, ext, fname):
    """Returns (status, reason)."""
    tname = table_name_for(fname)
    if ext == ".xlsx":
        count = 0
        for sheet, grid in xlsx_sheets(path):
            if not grid:
                continue
            header = uniq_names([str(h).strip() for h in grid[0][1]])
            rows = [(rn, {h: (vals[i] if i < len(vals) else "") for i, h in enumerate(header)}) for rn, vals in grid[1:]]
            count += add_rows(con, file_id, f"{tname}/{sheet.lower()}", [("xlsx", rows)])
            text = "\n".join(f"[{sheet}!{rn}] " + "\t".join(vals) for rn, vals in grid)
            add_text(con, file_id, text)
        return "indexed", f"xlsx rows={count}"
    if ext == ".docx":
        add_text(con, file_id, docx_text(path))
        return "indexed", "docx text"
    if ext == ".pdf":
        t = pdf_text(path)
        if t is None:
            return "skipped", "pdf (pdftotext not available)"
        add_text(con, file_id, t)
        return "indexed", "pdf text"
    raw = path.read_bytes()
    text = decode(raw)
    if text is None:
        return "skipped", "binary content"
    if ext == ".xml" and len(raw) > SPARSE_XML_BYTES:
        lines = text.splitlines()
        kept = sparse_xml(lines)
        add_sparse(con, file_id, kept)
        return "indexed", f"large xml: {len(kept)} structural lines of {len(lines)} (repeating elements not indexed)"
    lines = add_text(con, file_id, text)
    if ext == ".csv":
        blocks = parse_csv_text(text)
    elif ext in (".txt", ".log", ""):
        blocks = parse_format_table(lines) + parse_format_list(lines)
    else:
        blocks = []
    n = add_rows(con, file_id, tname, blocks) if blocks else 0
    return "indexed", f"text lines={len(lines)} rows={n}"


def cmd_build(args, project, root):
    work_dir = remap(project["work_dir"], project)
    final_db = Path(args.db) if args.db else work_dir / INDEX_NAME
    if args.stage_dir:
        db_path = Path(args.stage_dir).expanduser() / f"{project['key']}-{INDEX_NAME}"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if not db_path.exists() and final_db.exists() and not args.rebuild:
            shutil.copyfile(final_db, db_path)
    else:
        db_path = final_db
    if args.rebuild and db_path.exists():
        db_path.unlink()
    sources = [Path(s).expanduser() for s in args.source] if args.source else \
        [remap(project["default_source_set"], project).parent]
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=OFF" if args.stage_dir else "PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA synchronous=OFF")
    init_db(con)
    t0, done, stats, seen = time.time(), True, {}, set()
    capture_ids = {}
    for src in sources:
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for fname in sorted(filenames):
                if fname in SKIP_FILES or fname.startswith("~$"):
                    continue
                path = Path(dirpath) / fname
                rel = path.relative_to(root).as_posix() if root in path.parents else path.as_posix()
                seen.add(rel)
                if time.time() - t0 > args.budget:
                    done = False
                    continue
                try:
                    st = path.stat()
                except OSError:
                    continue
                ext = path.suffix.lower()
                archived, derived, cap = classify(Path(rel).parts, root)
                cap_id = None
                if cap:
                    folder = str(Path(rel).parent) if Path(rel).parent.name == cap[0] else \
                        next(str(Path(*Path(rel).parts[:i + 1])) for i, p in enumerate(Path(rel).parts) if p == cap[0])
                    cap_id = capture_ids.get(folder)
                    if cap_id is None:
                        con.execute("INSERT OR IGNORE INTO captures(folder, host, collector, capture_utc, archived) VALUES(?,?,?,?,?)",
                                    (folder, cap[1], cap[2], cap[3], archived))
                        cap_id = con.execute("SELECT capture_id FROM captures WHERE folder=?", (folder,)).fetchone()[0]
                        capture_ids[folder] = cap_id
                host = cap[1] if cap else None
                sclass = "capture" if cap else ("derived" if derived else "other")
                prev = con.execute("SELECT file_id, size, mtime, status FROM files WHERE rel_path=?", (rel,)).fetchone()
                if prev and prev[1] == st.st_size and abs((prev[2] or 0) - st.st_mtime) < 1:
                    stats[prev[3]] = stats.get(prev[3], 0) + 1
                    continue
                if prev:
                    drop_content(con, prev[0])
                    con.execute("DELETE FROM files WHERE file_id=?", (prev[0],))
                status, reason, sha, dup = None, None, None, None
                if ext in BINARY_EXT:
                    status, reason = "skipped", f"binary type {ext}"
                    if ext == ".zip":
                        reason = "zip (extracted alongside)" if path.with_suffix("").is_dir() else "zip (NOT extracted - contents not indexed)"
                elif SKIP_NAME_RE.search(fname):
                    status, reason = "skipped", "rendering duplicated by a text file in the same capture"
                elif st.st_size > (MAX_CSV_BYTES if ext == ".csv" else 64 * 1024 * 1024 if ext == ".xml" else MAX_TEXT_BYTES) \
                        and ext not in (".xlsx", ".docx", ".pdf"):
                    status, reason = "skipped", f"too large ({st.st_size} bytes)"
                elif st.st_size == 0:
                    status, reason = "skipped", "empty"
                cur = con.execute(
                    "INSERT INTO files(rel_path, capture_id, host, ext, size, mtime, source_class, archived) VALUES(?,?,?,?,?,?,?,?)",
                    (rel, cap_id, host, ext, st.st_size, st.st_mtime, sclass, archived))
                fid = cur.lastrowid
                if status is None:
                    h = hashlib.sha1()
                    with open(path, "rb") as fh:
                        for blk in iter(lambda: fh.read(1 << 20), b""):
                            h.update(blk)
                    sha = h.hexdigest()
                    d = con.execute("SELECT file_id FROM files WHERE sha1=? AND status='indexed' AND file_id<>? LIMIT 1", (sha, fid)).fetchone()
                    if d:
                        status, reason, dup = "duplicate", "identical content indexed elsewhere", d[0]
                    else:
                        try:
                            status, reason = index_file(con, fid, path, ext, fname)
                        except Exception as e:  # keep going; record why
                            drop_content(con, fid)
                            status, reason = "error", f"{type(e).__name__}: {e}"[:300]
                con.execute("UPDATE files SET sha1=?, status=?, reason=?, dup_of=? WHERE file_id=?", (sha, status, reason, dup, fid))
                stats[status] = stats.get(status, 0) + 1
                if sum(stats.values()) % 200 == 0:
                    con.commit()
    if done:
        stale = [r for r in con.execute("SELECT file_id, rel_path FROM files") if r[1] not in seen]
        for fid, _ in stale:
            drop_content(con, fid)
            con.execute("DELETE FROM files WHERE file_id=?", (fid,))
        stats["removed"] = len(stale)
    # current vs superseded captures, per host (archived captures never current)
    con.execute("UPDATE captures SET superseded_by=NULL, file_count=(SELECT COUNT(*) FROM files f WHERE f.capture_id=captures.capture_id)")
    for (host,) in con.execute("SELECT DISTINCT host FROM captures").fetchall():
        caps = con.execute("SELECT capture_id, capture_utc, archived FROM captures WHERE host=? ORDER BY archived, capture_utc DESC", (host,)).fetchall()
        live = [c for c in caps if not c[2]]
        latest = live[0][0] if live else None
        for c in caps:
            if c[0] != latest:
                con.execute("UPDATE captures SET superseded_by=? WHERE capture_id=?", (latest, c[0]))
    con.execute("INSERT OR REPLACE INTO meta VALUES('project', ?)", (project["key"],))
    con.execute("INSERT OR REPLACE INTO meta VALUES('sources', ?)", (json.dumps([str(s) for s in sources]),))
    con.execute("INSERT OR REPLACE INTO meta VALUES('complete', ?)", ("1" if done else "0",))
    con.execute("INSERT OR REPLACE INTO meta VALUES('built_at_utc', ?)", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
    con.commit()
    if done and has_fts5(con):
        con.execute("INSERT INTO chunks(chunks) VALUES('optimize')")
        con.commit()
    con.close()
    copied = None
    if args.stage_dir and done:
        tmp = final_db.with_name(final_db.name + ".new")
        shutil.copyfile(db_path, tmp)
        os.replace(tmp, final_db)
        copied = str(final_db)
    emit(dict(status="OK" if done else "INCOMPLETE", message=None if done else "time budget reached - run build again to continue",
              db=str(db_path), published_to=copied, seconds=round(time.time() - t0, 1), files=stats))


# --------------------------------------------------------------------------- queries
def open_ro(project):
    work_dir = remap(project["work_dir"], project)
    db = work_dir / INDEX_NAME
    if not db.is_file():
        fail("NO_INDEX", f"no index at {db}; run: discovery_index.py build --project {project['key']}")
    con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    return con, meta


def scope_sql(args, alias="f"):
    """Default scope: current captures only (plus non-capture files), archive excluded."""
    parts, params = [], []
    if not getattr(args, "include_archive", False):
        parts.append(f"{alias}.archived=0")
    if not getattr(args, "all_captures", False):
        parts.append(f"({alias}.capture_id IS NULL OR {alias}.capture_id IN (SELECT capture_id FROM captures WHERE superseded_by IS NULL))")
    if getattr(args, "host", None):
        parts.append(f"UPPER({alias}.host) LIKE ?")
        params.append(f"%{args.host.upper()}%")
    if getattr(args, "path_like", None):
        parts.append(f"{alias}.rel_path LIKE ?")
        params.append(f"%{args.path_like}%")
    return (" AND ".join(parts) or "1=1"), params


def cite(con, file_id, lines, excerpt):
    f = con.execute("SELECT f.rel_path, f.host, f.source_class, c.folder, c.capture_utc, c.superseded_by FROM files f "
                    "LEFT JOIN captures c ON c.capture_id=f.capture_id WHERE f.file_id=?", (file_id,)).fetchone()
    rel = f["rel_path"]
    name = Path(rel).name
    if f["folder"]:
        title = f"{Path(f['folder']).name}: {name}"
        version = f"capture {f['capture_utc']}"
    else:
        title = rel
        version = ""
    xl = re.match(r"\[([^\]]+)\]", excerpt or "") if rel.lower().endswith(".xlsx") else None
    if xl:
        return dict(source_title=title, source_version=version, page_or_location=f"{name} sheet!row {xl.group(1)}",
                    evidence_excerpt=excerpt[:MAX_EXCERPT], rel_path=rel, host=f["host"],
                    source_class=f["source_class"], superseded=bool(f["superseded_by"]))
    loc = f"{name} line {lines[0]}" if lines and lines[0] == lines[-1] else (f"{name} lines {lines[0]}-{lines[-1]}" if lines else name)
    return dict(source_title=title, source_version=version, page_or_location=loc,
                evidence_excerpt=excerpt[:MAX_EXCERPT], rel_path=rel, host=f["host"],
                source_class=f["source_class"], superseded=bool(f["superseded_by"]))


def fts_query(terms, any_mode):
    toks = [t for t in re.findall(r'"[^"]+"|\S+', terms)]
    quoted = ['"' + t.strip('"').replace('"', '""') + '"' for t in toks]
    return (" OR " if any_mode else " AND ").join(quoted), [t.strip('"').lower() for t in toks]


def cmd_search(args, project, root):
    con, meta = open_ro(project)
    where, params = scope_sql(args)
    q, words = fts_query(args.terms, args.any)
    if meta.get("fts5") == "1":
        sql = (f"SELECT m.file_id, m.line_start, chunks.content AS content, bm25(chunks) AS score FROM chunks "
               f"JOIN chunk_map m ON m.chunk_id=chunks.rowid JOIN files f ON f.file_id=m.file_id "
               f"WHERE chunks MATCH ? AND {where} ORDER BY score LIMIT ?")
        rows = con.execute(sql, [q] + params + [args.limit * 4]).fetchall()
    else:
        like = " AND ".join("LOWER(chunks.content) LIKE ?" for _ in words)
        sql = (f"SELECT m.file_id, m.line_start, chunks.content AS content, 0 AS score FROM chunks "
               f"JOIN chunk_map m ON m.chunk_id=chunks.rowid JOIN files f ON f.file_id=m.file_id WHERE {like} AND {where} LIMIT ?")
        rows = con.execute(sql, [f"%{w}%" for w in words] + params + [args.limit * 4]).fetchall()
    out, per_file = [], {}
    for r in rows:
        if per_file.get(r["file_id"], 0) >= args.per_file:
            continue
        hits = []
        for off, line in enumerate(r["content"].split("\n")):
            m = LINE_TAG.match(line)
            n, line = (int(m.group(1)), line[m.end():]) if m else (r["line_start"] + off, line)
            low = line.lower()
            if any(w in low for w in words):
                hits.append((n, line.rstrip()))
        if not hits:
            continue
        per_file[r["file_id"]] = per_file.get(r["file_id"], 0) + 1
        nums = [h[0] for h in hits[:8]]
        excerpt = " | ".join(h[1].strip() for h in hits[:8])
        out.append(dict(score=round(r["score"], 2), **cite(con, r["file_id"], nums, excerpt)))
        if len(out) >= args.limit:
            break
    emit(dict(status="OK", query=args.terms, fts=q, scope=scope_label(args), count=len(out), results=out,
              note=None if out else "no hits in scope; try --any, fewer terms, --all-captures or --include-archive"))


def scope_label(args):
    return dict(current_captures_only=not args.all_captures, include_archive=args.include_archive,
                host=args.host, path_like=getattr(args, "path_like", None))


WHERE_RE = re.compile(r"^(?P<col>[^=~!]+?)(?P<op>!~|~|=|!=)(?P<val>.*)$")


def cmd_rows(args, project, root):
    con, _ = open_ro(project)
    where, params = scope_sql(args)
    tables = [r[0] for r in con.execute("SELECT DISTINCT table_name FROM rows")]
    if args.table in tables:
        tsel = [args.table]
    else:
        tsel = [t for t in tables if args.table.lower() in t]
    if not tsel:
        fail("NO_TABLE", f"no table matching '{args.table}'", hint="run: tables")
    conds, cparams = [], []
    for w in args.where or []:
        m = WHERE_RE.match(w)
        if not m:
            fail("BAD_WHERE", f"cannot parse --where '{w}' (use COL~text, COL=text, COL!~text, COL!=text)")
        path = '$."' + m.group("col").strip().replace('"', '\\"') + '"'
        op, val = m.group("op"), m.group("val")
        if op == "~":
            conds.append("LOWER(json_extract(r.data, ?)) LIKE ?"); cparams += [path, f"%{val.lower()}%"]
        elif op == "!~":
            conds.append("LOWER(COALESCE(json_extract(r.data, ?),'')) NOT LIKE ?"); cparams += [path, f"%{val.lower()}%"]
        elif op == "=":
            conds.append("LOWER(json_extract(r.data, ?)) = ?"); cparams += [path, val.lower()]
        else:
            conds.append("LOWER(COALESCE(json_extract(r.data, ?),'')) <> ?"); cparams += [path, val.lower()]
    q = ",".join("?" * len(tsel))
    sql = (f"SELECT r.file_id, r.table_name, r.line_no, r.data FROM rows r JOIN files f ON f.file_id=r.file_id "
           f"WHERE r.table_name IN ({q}) AND {where}" + "".join(" AND " + c for c in conds) +
           " ORDER BY f.host, f.rel_path, r.line_no")
    res = con.execute(sql, tsel + params + cparams).fetchall()
    cols = [c.strip() for c in args.cols.split(",")] if args.cols else None
    if args.distinct:
        agg = {}
        for r in res:
            d = json.loads(r["data"])
            v = d.get(args.distinct, "")
            host = con.execute("SELECT host FROM files WHERE file_id=?", (r["file_id"],)).fetchone()[0]
            agg.setdefault(v, set()).add(host or "-")
        emit(dict(status="OK", tables=tsel, distinct=args.distinct, count=len(agg),
                  values=[dict(value=k, hosts=sorted(v)) for k, v in sorted(agg.items(), key=lambda x: (-len(x[1]), str(x[0])))][:args.limit]))
        return
    out = []
    for r in res[:args.limit]:
        d = json.loads(r["data"])
        if cols:
            d = {k: d.get(k) for k in cols}
        excerpt = "; ".join(f"{k}={v}" for k, v in d.items() if v not in (None, ""))
        c = cite(con, r["file_id"], [r["line_no"]], excerpt)
        out.append(dict(table=r["table_name"], host=c["host"], row=d, cite=c))
    emit(dict(status="OK", tables=tsel, scope=scope_label(args), total=len(res), shown=len(out), results=out))


def cmd_tables(args, project, root):
    con, _ = open_ro(project)
    pat = f"%{(args.pattern or '').lower()}%"
    res = []
    for t, fmt, n, h in con.execute(
            "SELECT r.table_name, GROUP_CONCAT(DISTINCT r.fmt), COUNT(*), COUNT(DISTINCT f.host) FROM rows r "
            "JOIN files f ON f.file_id=r.file_id WHERE r.table_name LIKE ? GROUP BY r.table_name ORDER BY r.table_name", (pat,)):
        cols = []
        for (d,) in con.execute("SELECT data FROM rows WHERE table_name=? LIMIT 50", (t,)):
            for k in json.loads(d):
                if k not in cols:
                    cols.append(k)
        res.append(dict(table=t, format=fmt, rows=n, hosts=h, columns=cols[:40]))
    emit(dict(status="OK", count=len(res), tables=res))


def cmd_hosts(args, project, root):
    con, _ = open_ro(project)
    res = {}
    for r in con.execute("SELECT c.*, s.folder AS superseded_by_folder FROM captures c LEFT JOIN captures s ON s.capture_id=c.superseded_by ORDER BY c.host, c.capture_utc"):
        res.setdefault(r["host"], []).append(dict(folder=r["folder"], collector=r["collector"], capture_utc=r["capture_utc"],
                                                  files=r["file_count"], archived=bool(r["archived"]),
                                                  current=r["superseded_by"] is None and not r["archived"],
                                                  superseded_by=r["superseded_by_folder"]))
    emit(dict(status="OK", hosts=len(res), captures=res))


def cmd_status(args, project, root):
    con, meta = open_ro(project)
    by = [dict(status=s, files=n, mb=round((b or 0) / 1e6, 1)) for s, n, b in
          con.execute("SELECT status, COUNT(*), SUM(size) FROM files GROUP BY status ORDER BY 2 DESC")]
    reasons = [dict(reason=r, files=n) for r, n in
               con.execute("SELECT reason, COUNT(*) FROM files WHERE status<>'indexed' GROUP BY reason ORDER BY 2 DESC LIMIT 20")]
    errors = [dict(path=p, reason=r) for p, r in con.execute("SELECT rel_path, reason FROM files WHERE status='error' LIMIT 20")]
    emit(dict(status="OK", meta=meta,
              captures=con.execute("SELECT COUNT(*) FROM captures").fetchone()[0],
              current_captures=con.execute("SELECT COUNT(*) FROM captures WHERE superseded_by IS NULL AND archived=0").fetchone()[0],
              text_chunks=con.execute("SELECT COUNT(*) FROM chunk_map").fetchone()[0],
              table_rows=con.execute("SELECT COUNT(*) FROM rows").fetchone()[0],
              files_by_status=by, not_indexed_reasons=reasons, errors=errors))


def cmd_sql(args, project, root):
    con, _ = open_ro(project)
    if not re.match(r"^\s*(SELECT|WITH)\b", args.query, re.I):
        fail("READ_ONLY", "only SELECT / WITH queries are allowed")
    rows = con.execute(args.query).fetchmany(args.limit)
    emit(dict(status="OK", count=len(rows), rows=[dict(r) for r in rows]))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project")
    p.add_argument("--workspace")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--budget", type=float, default=3600, help="seconds before stopping; rerun to continue")
    b.add_argument("--rebuild", action="store_true")
    b.add_argument("--source", action="append", help="folder to index (default: parent of default_source_set)")
    b.add_argument("--db", help="override index path")
    b.add_argument("--stage-dir", help="build in a local folder, then copy into work_dir when complete")

    def scope(sp):
        sp.add_argument("--host")
        sp.add_argument("--path-like")
        sp.add_argument("--all-captures", action="store_true", help="include superseded captures")
        sp.add_argument("--include-archive", action="store_true")
        sp.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("search"); s.add_argument("terms"); scope(s)
    s.add_argument("--any", action="store_true", help="match any term instead of all")
    s.add_argument("--per-file", type=int, default=2)
    r = sub.add_parser("rows"); r.add_argument("table"); scope(r)
    r.add_argument("--where", action="append"); r.add_argument("--cols"); r.add_argument("--distinct")
    t = sub.add_parser("tables"); t.add_argument("pattern", nargs="?")
    sub.add_parser("hosts"); sub.add_parser("status")
    q = sub.add_parser("sql"); q.add_argument("query"); q.add_argument("--limit", type=int, default=200)
    args = p.parse_args()
    project, root = resolve_project(args)
    dict(build=cmd_build, search=cmd_search, rows=cmd_rows, tables=cmd_tables, hosts=cmd_hosts,
         status=cmd_status, sql=cmd_sql)[args.cmd](args, project, root)


if __name__ == "__main__":
    main()
