from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

from fastapi import HTTPException


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
DC = "{http://purl.org/dc/elements/1.1/}"
DCTERMS = "{http://purl.org/dc/terms/}"
CUSTOM = "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}"


def _archived(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        return True
    return any("archive" in part.lower() or part.lower().lstrip().startswith("old")
               or part.lower().startswith("backup") or part == "_to_delete" for part in parts)


def candidates(project: dict[str, str]) -> list[Path]:
    """Apply the framework working-document ownership rule without choosing among ties."""
    root = Path(project["project_root"]).expanduser().resolve()
    change_files = [path for path in root.rglob("reviews/ChangesCSA_*.md") if not _archived(path, root)]
    version_dirs = sorted({path.parent.parent for path in change_files})
    found: list[Path] = []
    for folder in version_dirs:
        for path in folder.glob("*.docx"):
            resolved = path.resolve()
            if path.name.startswith("~$") or _archived(resolved, root) or root not in resolved.parents:
                continue
            found.append(resolved)
    return sorted(set(found), key=str)


def resolve(project: dict[str, str]) -> dict[str, Any]:
    found = candidates(project)
    if len(found) == 1:
        return {"state": "ready", "path": found[0], "candidates": [str(found[0])]}
    return {"state": "blocked", "path": None, "candidates": [str(path) for path in found],
            "reason": "No authoritative working DOCX was found." if not found else
            "More than one authoritative working DOCX candidate exists; resolve the duplicate before editing."}


def _xml(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(archive.read(name))
    except (KeyError, ET.ParseError):
        return None


def _properties(archive: zipfile.ZipFile) -> dict[str, str]:
    values: dict[str, str] = {}
    core = _xml(archive, "docProps/core.xml")
    if core is not None:
        for name, tag in {"title": DC + "title", "subject": DC + "subject", "version": CP + "version",
                          "revision": CP + "revision", "status": CP + "contentStatus",
                          "modified": DCTERMS + "modified"}.items():
            element = core.find(tag)
            if element is not None and element.text:
                values[name] = element.text
    custom = _xml(archive, "docProps/custom.xml")
    if custom is not None:
        for prop in custom.findall(CUSTOM + "property"):
            name = prop.attrib.get("name", "").strip().lower()
            child = next(iter(prop), None)
            if name in {"status", "version", "document status", "document version"} and child is not None:
                values[name.replace("document ", "")] = child.text or ""
    return values


def _revision_counts(document: ET.Element | None) -> tuple[int, int]:
    return (0, 0) if document is None else (len(document.findall(".//" + W + "ins")),
                                            len(document.findall(".//" + W + "del")))


def _comments(archive: zipfile.ZipFile, document: ET.Element | None) -> list[dict[str, Any]]:
    comments_xml = _xml(archive, "word/comments.xml")
    if comments_xml is None:
        return []
    anchored: dict[str, str] = {}
    if document is not None:
        for paragraph in document.findall(".//" + W + "p"):
            text = "".join((node.text or "") for node in paragraph.findall(".//" + W + "t"))
            for marker in paragraph.findall(".//" + W + "commentRangeStart"):
                anchored[marker.attrib.get(W + "id", "")] = text[:240]
    rows = []
    for item in comments_xml.findall(".//" + W + "comment"):
        cid = item.attrib.get(W + "id", "")
        rows.append({"id": cid, "author": item.attrib.get(W + "author", ""),
                     "date": item.attrib.get(W + "date"),
                     "text": "".join((node.text or "") for node in item.findall(".//" + W + "t")),
                     "anchored_text": anchored.get(cid, "")})
    return rows


def word_lock(path: Path) -> Path | None:
    matches = [path.with_name(f"~${path.name}")]
    if len(path.name) > 2:
        matches.append(path.with_name(f"~${path.name[2:]}"))
    return next((candidate for candidate in matches if candidate.exists()), None)


def _manifest(project: dict[str, str], document: Path) -> dict[str, Any]:
    manifests = sorted((Path(project["work_dir"]).expanduser() / "run-state").glob("stable-ids-*.json"),
                       key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if not manifests:
        return {"state": "missing", "path": None, "modified_at": None}
    path = manifests[0]
    state = "fresh" if path.stat().st_mtime_ns >= document.stat().st_mtime_ns else "stale"
    return {"state": state, "path": str(path),
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def metadata(project: dict[str, str]) -> dict[str, Any]:
    selected = resolve(project)
    if selected["state"] != "ready":
        return selected
    path: Path = selected["path"]
    try:
        with zipfile.ZipFile(path) as archive:
            document = _xml(archive, "word/document.xml")
            inserted, deleted = _revision_counts(document)
            comments = _comments(archive, document)
            properties = _properties(archive)
    except (OSError, zipfile.BadZipFile) as error:
        return {"state": "blocked", "path": None, "candidates": [str(path)],
                "reason": f"The authoritative DOCX cannot be read: {error}"}
    stat = path.stat()
    lock = word_lock(path)
    return {"state": "ready", "filename": path.name, "path": str(path), "candidates": [str(path)],
            "size": stat.st_size, "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "properties": properties, "word_locked": lock is not None,
            "word_lock_file": lock.name if lock else None,
            "tracked_changes": {"insertions": inserted, "deletions": deleted, "total": inserted + deleted},
            "comment_count": len(comments), "manifest": _manifest(project, path),
            "preview": {"pdf_representation": "document_only", "revisions_in_pdf": not bool(inserted or deleted),
                        "comments_in_pdf": not bool(comments)}}


def document_comments(project: dict[str, str]) -> list[dict[str, Any]]:
    selected = resolve(project)
    if selected["state"] != "ready":
        raise HTTPException(409, {"message": selected["reason"], "candidates": selected["candidates"]})
    with zipfile.ZipFile(selected["path"]) as archive:
        return _comments(archive, _xml(archive, "word/document.xml"))


def revision_view(project: dict[str, str]) -> dict[str, Any]:
    selected = resolve(project)
    if selected["state"] != "ready":
        raise HTTPException(409, {"message": selected["reason"], "candidates": selected["candidates"]})
    path: Path = selected["path"]
    with zipfile.ZipFile(path) as archive:
        document = _xml(archive, "word/document.xml")
    if document is None:
        raise HTTPException(422, "The DOCX has no readable main document part")
    paragraphs: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    for paragraph in document.findall(".//" + W + "body/" + W + "p"):
        style_node = paragraph.find("./" + W + "pPr/" + W + "pStyle")
        style = style_node.attrib.get(W + "val", "") if style_node is not None else ""
        tokens: list[dict[str, str]] = []
        inserted_nodes = {id(node) for insertion in paragraph.findall(".//" + W + "ins") for node in insertion.iter()}
        deleted_nodes = {id(node) for deletion in paragraph.findall(".//" + W + "del") for node in deletion.iter()}
        for node in paragraph.iter():
            if node.tag not in {W + "t", W + "delText"} or not node.text:
                continue
            kind = "inserted" if id(node) in inserted_nodes else "deleted" if id(node) in deleted_nodes else "normal"
            tokens.append({"kind": kind, "text": node.text})
        text = "".join(token["text"] for token in tokens).strip()
        if not text:
            continue
        index = len(paragraphs)
        paragraphs.append({"index": index, "style": style, "tokens": tokens})
        if re.match(r"(?i)^heading\s*[1-6]$", style):
            sections.append({"index": index, "title": text})
    return {"filename": path.name, "representation": "extracted_revision_text",
            "notice": "This view exposes tracked insertions and deletions from the DOCX XML; it is not a page-layout rendering.",
            "sections": sections, "paragraphs": paragraphs}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _page_count(path: Path) -> int | None:
    try:
        count = len(re.findall(rb"/Type\s*/Page\b", path.read_bytes()))
    except OSError:
        return None
    return count or None


def render_pdf(project: dict[str, str], *, converter: Callable[[Path, Path], None] | None = None) -> tuple[Path, str, int | None]:
    selected = resolve(project)
    if selected["state"] != "ready":
        raise HTTPException(409, {"message": selected["reason"], "candidates": selected["candidates"]})
    document: Path = selected["path"]
    fingerprint = _sha256(document)
    folder = Path(project["work_dir"]).expanduser() / "ui-preview" / fingerprint
    output = folder / "assessment.pdf"
    if not output.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        if converter is not None:
            converter(document, output)
        else:
            soffice = shutil.which("soffice") or shutil.which("libreoffice")
            if not soffice:
                raise HTTPException(503, "LibreOffice preview runtime is unavailable")
            result = subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(folder), str(document)],
                                    capture_output=True, text=True, timeout=180)
            produced = folder / f"{document.stem}.pdf"
            if result.returncode or not produced.is_file():
                raise HTTPException(502, result.stderr.strip() or "Document preview conversion failed")
            produced.replace(output)
    return output, fingerprint, _page_count(output)


def preview_descriptor(project: dict[str, str], system_key: str,
                       *, converter: Callable[[Path, Path], None] | None = None) -> dict[str, Any]:
    info = metadata(project)
    if info["state"] != "ready":
        return info
    path, fingerprint, pages = render_pdf(project, converter=converter)
    base = f"/api/systems/{system_key}/document/preview"
    return {"state": "ready", "filename": info["filename"], "cache_key": fingerprint,
            "page_count": pages, "pdf_url": base + "?mode=pdf", "revision_url": base + "?mode=revisions",
            "revisions_in_pdf": info["preview"]["revisions_in_pdf"],
            "comments_in_pdf": info["preview"]["comments_in_pdf"]}
