"""Direction A (framework-robustness-plan.md section 3): OOXML bookmark tagging.

DocxEngine's anchors (P{ordinal}#{hash}) are content-addressed and
deliberately ephemeral - by design, per its own docstring, any edit to a
paragraph invalidates every anchor referencing it. That is exactly right for
DocxEngine's own operations (it forces callers to re-fetch rather than
operate on stale state), but it means an anchor is useless as a durable,
across-runs identifier for "this is where edit E-166 belongs" - which is
what the change records need. OOXML's own w:bookmarkStart/w:bookmarkEnd
markers are the standard mechanism for that: invisible in Word, survive
arbitrary edits to surrounding text, and can be looked up by name directly
regardless of how many paragraphs have shifted around them.

DocxEngine has no bookmark tool (confirmed by inspecting every tool's JSON
spec), so this is a small, self-contained raw-XML extension living alongside
the DocxEngine adapter, in the same spirit as the pre-DocxEngine
DocumentEditor class in ooxml.py. It reads/writes word/document.xml directly
through the package DocxEngine already has open, and is careful to mark the
document dirty afterwards so DocxEngine's own save path picks up the change.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Self-contained vendor bootstrap (mirrors engines/docxengine_adapter.py):
# this module is imported both via docxengine_adapter.py and, potentially,
# directly (tests, scratch scripts). It must not rely on the *importer*
# having already put vendor/ on sys.path - that ordering bug is exactly
# what broke this module's real-world bootstrap once (see learnings file,
# 2026-09-17: "bookmarks import ordering bug").
_VENDOR_DIR = Path(__file__).resolve().parents[1] / "vendor"
if _VENDOR_DIR.exists() and str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

from docxengine._anchors import build_anchor_index

_BOOKMARK_ID_RE = re.compile(rb'<w:bookmarkStart\b[^>]*\bw:id="(\d+)"')
_NAME_SANITISE_RE = re.compile(r"[^A-Za-z0-9_]")

BOOKMARK_PREFIX = "CSA_"  # OOXML bookmark names may not start with a digit


def sanitise_bookmark_name(edit_id: str) -> str:
    """Turn an edit ID like "E-166" into a valid, stable OOXML bookmark name.

    Word bookmark names: start with a letter or underscore, contain only
    letters/digits/underscores, max 40 characters. "E-166" -> "CSA_E_166".
    """
    name = BOOKMARK_PREFIX + _NAME_SANITISE_RE.sub("_", edit_id)
    return name[:40]


def _next_bookmark_id(data: bytes) -> int:
    ids = [int(m.group(1)) for m in _BOOKMARK_ID_RE.finditer(data)]
    return (max(ids) + 1) if ids else 0


def add_bookmark_at_anchor(editor, anchor: str, edit_id: str) -> str:
    """Wrap the paragraph identified by anchor in a named bookmark.

    Returns the bookmark name used. Raises ValueError if the anchor can't be
    resolved to a current paragraph (call this immediately after resolving
    the anchor via the normal find/match path - don't hold onto an anchor
    across other mutations, for the same staleness reason DocxEngine anchors
    themselves warn about).
    """
    package = editor.doc._doc.package
    part_name = package.main_document_part()
    data = package.part(part_name)

    entries = build_anchor_index(package, part_name)
    entry = next((e for e in entries if e.anchor == anchor), None)
    if entry is None:
        raise ValueError(f"Anchor {anchor!r} not found - it may already be stale; re-resolve and retry")

    name = sanitise_bookmark_name(edit_id)
    bookmark_id = _next_bookmark_id(data)
    start_tag = f'<w:bookmarkStart w:id="{bookmark_id}" w:name="{name}"/>'.encode("utf-8")
    end_tag = f'<w:bookmarkEnd w:id="{bookmark_id}"/>'.encode("utf-8")

    span = entry.span
    # Splice end tag first so the earlier inner_start offset stays valid.
    new_data = data[: span.inner_end] + end_tag + data[span.inner_end :]
    new_data = new_data[: span.inner_start] + start_tag + new_data[span.inner_start :]

    package.set_part(part_name, new_data)
    editor.doc._doc.mark_dirty()
    return name


def find_bookmark(editor, edit_id: str) -> str | None:
    """Return the current anchor of the paragraph containing edit_id's bookmark, or None.

    This is the Direction-A lookup path: resolve a location by durable
    bookmark name first, falling back to text-matching only when no bookmark
    exists yet (an un-retrofitted record) - see apply_change's dispatch.
    """
    name = sanitise_bookmark_name(edit_id)
    package = editor.doc._doc.package
    part_name = package.main_document_part()
    data = package.part(part_name)

    marker = f'w:name="{name}"'.encode("utf-8")
    pos = data.find(marker)
    if pos == -1:
        return None

    entries = build_anchor_index(package, part_name)
    for entry in entries:
        if entry.span.start <= pos <= entry.span.end:
            return entry.anchor
    return None
