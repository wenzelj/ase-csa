"""Citation check for the CSA discovery index: does every evidence-matrix row still point into the index?

E-ids live in csa-work/evidence-matrix.csv, never in the index, so a rebuild cannot renumber them; what a rebuild can
break is the pointer: the source file is no longer indexed, or its text got shorter than the cited line. ``verify_cites``
reports both, ``new_failures`` compares two reports, and a staged rebuild is published only when nothing newly fails.
Standard library only."""
import re

LINE_RE = re.compile(r"\blines?\s+(\d+)(?:\s*-\s*(\d+))?", re.I)


def _norm_excerpt(value):
    """Ignore extractor-only whitespace changes while retaining words and punctuation."""
    return re.sub(r"\s+", "", value or "").casefold()


def _excerpt_resolves(con, file_ids, excerpt):
    """True when every non-empty ``|``-separated quote is still in the named source file.

    PDF extractors lay tables out differently and can therefore change line counts without
    changing the source evidence. The matrix's quoted excerpt is the stable fallback for
    those legacy line references; it must resolve in the same file.
    """
    segments = [_norm_excerpt(s) for s in (excerpt or "").split("|") if _norm_excerpt(s)]
    if not segments:
        return False
    for file_id in file_ids:
        chunks = con.execute(
            "SELECT c.content FROM chunks c JOIN chunk_map m ON m.chunk_id=c.rowid "
            "WHERE m.file_id=? ORDER BY m.line_start", (file_id,)).fetchall()
        text = _norm_excerpt("\n".join(r[0] for r in chunks))
        if all(segment in text for segment in segments):
            return True
    return False


def _files(con):
    return [(r[0], r[1], r[2]) for r in con.execute("SELECT file_id, rel_path, COALESCE(dup_of, file_id) FROM files")]


def _match(files, part):
    """File ids a title part names: 'folder: file' by folder and file name, else a document by name."""
    part = part.strip()
    if ": " in part:
        folder, name = part.split(": ", 1)
        folder, name = folder.strip(), name.strip()
        return [f for f in files if f[1].endswith("/" + name) or f[1] == name if folder in f[1]]
    if len(part) < 6:
        return []
    low = part.lower()
    return [f for f in files if low in f[1].lower()]


def verify_cites(con, rows) -> dict:
    """{"total", "resolved", "unresolved": [ids], "line_out_of_range": [ids], "not_checkable"} for matrix ``rows``
    (dicts with evidence_id, source_title, page_or_location) against the index in ``con``."""
    files = _files(con)
    longest = {fid: end for fid, end in con.execute("SELECT file_id, MAX(line_end) FROM chunk_map GROUP BY file_id")}
    res = {"total": len(rows), "resolved": 0, "unresolved": [], "line_out_of_range": [], "not_checkable": 0}
    for r in rows:
        title = (r.get("source_title") or "").strip()
        if not title:
            res["not_checkable"] += 1
            continue
        parts = [p for p in re.split(r";\s+", title) if p.strip()]
        matched = [_match(files, p) for p in parts]
        if not all(matched):
            res["unresolved"].append(r["evidence_id"])
            continue
        m = LINE_RE.search(r.get("page_or_location") or "")
        if m and len(parts) == 1:
            n = int(m.group(2) or m.group(1))
            resolved_ids = [f[2] for f in matched[0]]
            if all(n > longest.get(fid, 0) for fid in resolved_ids) and not _excerpt_resolves(
                    con, resolved_ids, r.get("evidence_excerpt") or r.get("excerpt")):
                res["line_out_of_range"].append(r["evidence_id"])
                continue
        res["resolved"] += 1
    return res


def new_failures(before: dict, after: dict) -> list[str]:
    bad = lambda d: set(d["unresolved"]) | set(d["line_out_of_range"])
    return sorted(bad(after) - bad(before))
