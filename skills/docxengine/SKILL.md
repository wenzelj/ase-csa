---
name: docxengine
description: Use when reading, editing, or generating .docx Word documents with the DocxEngine library/MCP server — covers its hash-anchored addressing, 24-tool surface, tracked-changes/comment model, Python/CLI/MCP integration, and validation gate.
---

# DocxEngine

## What it is

DocxEngine is a deterministic OOXML editing library built for AI agents. It edits `word/document.xml` directly rather than going through a lossy docx library, so existing tracked changes, comments, and footnotes survive edits instead of being dropped — the problem most docx tooling has. Open source (Apache-2.0), `github.com/ruwadgroup/docxengine`, Python ≥ 3.12 package `docxengine`.

Three interchangeable surfaces sit over the same core:

1. **MCP server** (`docxengine-mcp`, entry point `docxengine.mcp:main`) — file-first: every tool takes a file `path`; each edit is validated and saved back automatically, no handle/save step. Install with `pip install docxengine` or run zero-install with `uvx docxengine-mcp`; register with `claude mcp add docx -- uvx docxengine-mcp`.
2. **Python `Document` class** (`docxengine.Document`) — an in-memory handle with explicit `.save()`/`.to_bytes()`, for embedding DocxEngine inside another program rather than running it as a separate MCP process.
3. **Line-oriented JSON CLI** (`python -m docxengine.cli`) — one JSON request per stdin line (`{"tool": "docx_replace", "args": {...}}`), one JSON response per stdout line; doc_ids persist for the process lifetime.

All three dispatch through the same `_dispatch.call(tool, args, session)` function and the same 24-tool contract (defined in `spec/tools/*.json`, vendored as `docxengine/_specdata/tools/*.json`), so behavior — anchors, tracked changes, validation — is identical regardless of which surface drives it.

## Core model: hash-anchored addressing

Every body-level paragraph and table gets a stable, content-addressed anchor instead of a raw index or XPath:

- **Paragraph anchor**: `P{ordinal}#{hash4}` — 1-based position among body-level `w:p` elements, plus the first 4 lowercase hex chars of SHA-256 over the paragraph's *normalized* text (NFC-normalized, whitespace runs collapsed to one space, trimmed; `w:delText` excluded, so the hash reflects the document as-if-accepted).
- **Table anchor**: `T{ordinal}` — 1-based position among body-level `w:tbl` elements.
- Anchors are returned by `docx_outline`, `docx_search`, `docx_read`, and by every edit tool's result (`new_anchor`/`new_anchors`).
- Anchors go stale the instant their paragraph's text changes — editing through a stale anchor raises `anchor_stale`. Always fetch a fresh anchor immediately before editing; never reuse an anchor captured earlier in a multi-step plan.

This addressing is also why reading stays cheap: `docx_outline` returns the heading tree + table list (the map), `docx_search` finds text and returns matching anchors with snippets, `docx_read` pulls a Markdown-projected window/range around an anchor — never the whole document — so an agent can navigate and edit a large document within a small token budget.

## Standard workflow

1. `docx_open` (path or base64 bytes) → `doc_id`. Never mutates the file.
2. `docx_outline` → heading tree + tables, to get oriented.
3. `docx_search` / `docx_read` → locate the target anchor(s).
4. One of the edit tools (below), addressed by anchor — returns a fresh anchor.
5. `docx_save` (MCP/CLI path — the Python `Document` API instead calls `.save(path)` / `.to_bytes()` explicitly) — runs the full validation gate first and **refuses to write a package that would trigger Word's repair dialog**. Writes atomically, preserves untouched parts byte-for-byte, and does not close the doc_id — keep editing and save again as needed.

## Tool surface (24 tools)

- **Read**: `docx_open`, `docx_outline`, `docx_read`, `docx_search`
- **Edit**: `docx_edit_paragraph` (rewrite whole paragraph, automatic word-level diff redline), `docx_insert` (Markdown/plain text before/after an anchor), `docx_delete` (anchor or range), `docx_replace` (in-paragraph or all-paragraph text substitution)
- **Revisions**: `docx_revision` (`list`/`accept`/`reject`/`accept_all`/`reject_all`, filterable by author/date)
- **Comments**: `docx_comment` (`add`/`reply`/`resolve`/`list`/`delete`, threaded)
- **Structure**: `docx_table` (one consolidated tool: `create`/`set_cells`/`insert_row`/`insert_col`/`delete_row`/`delete_col`/`merge`/`style`/`delete`), `docx_list` (`create`/`restart`/`set_level`/`convert`), `docx_section` (`list`/`set_geometry`/`set_header`/`set_footer`/`insert_break`), `docx_media` (`insert`/`extract`/`replace` images), `docx_field` (`insert_toc`/`insert_page_number`/`update`)
- **Styling**: `docx_style` (`list`/`define`/`apply`), `docx_format` (direct or style-wide formatting props: color/bold/italic/size/alignment/spacing)
- **Lifecycle**: `docx_validate`, `docx_repair`, `docx_save`
- **Document-level**: `docx_create` (from Markdown or a structured spec), `docx_convert` (to `md`/`html` inline, or `pdf`/`png` via a render adapter to a path), `docx_template_fill` (mustache placeholders/loops/conditions), `docx_render_preview` (render pages to images for visual self-check)

Every edit tool accepts `track_changes: bool` + `author: str`. With `track_changes: true` the edit becomes a genuine `w:ins`/`w:del` redline under that author instead of a silent physical change — this is how DocxEngine produces reviewable Word tracked changes.

## Error model

Every failure is a `ToolError` with a stable `code`, human `message`, and `suggestions` list — `{"error": code, "message": ..., "suggestions": [...]}` at the CLI/MCP boundary, a Python exception in-process. Common codes: `doc_not_found` (unknown/expired doc_id — call `docx_open` again), `anchor_stale` / `anchor_invalid` / `anchor_not_found` (re-fetch the anchor), `not_found` (search/replace target missing), `ambiguous_target` (more than one match — narrow the query or supply an anchor), `style_unknown`, `validation_failed`, `path_denied`, `save_failed`, `open_failed`, `doc_too_large`, `malicious_content`, `template_syntax`, `placeholder_unfilled`, `render_unavailable`/`render_failed`, `repair_incomplete`.

## Validation, repair, and preview

- `docx_validate` checks package integrity (duplicate IDs, broken relationships, revision well-formedness) and returns `valid: bool` plus an `issues` list with `severity` (`error`/`warning`), `part`, `message`, `fix_hint`. Warnings never block a save.
- `docx_repair` mechanically fixes what's safe (orphaned references, missing content-type entries, duplicate-ID renumbering) and reports `fixed` vs `remaining`. Run it after `docx_validate` reports errors, then re-validate.
- `docx_render_preview` renders pages to images (LibreOffice-backed when available, otherwise a structural text fallback with an estimated page count) so an agent can check its own layout-affecting work. Use it at checkpoints after a batch of edits, not after every single edit — renders cost real time.

## Python API shape (`docxengine.Document`)

A thin object wrapper over the same `call()` dispatcher — useful when embedding DocxEngine in another Python program instead of running it as a standalone MCP server:

```python
from docxengine import Document

doc = Document.open("contract.docx")             # or Document.create(content_md=...), Document.fill_template(...)
doc.outline()
hit = doc.find("five (5) years")                  # first paragraph containing the text -> Paragraph
hit.replace("five (5) years", "three (3) years", track_changes=True, author="Wenzel Joubert")
doc.table("create", after=hit.anchor, rows=2, cols=3, data=[["a","b","c"],["1","2","3"]], header=True)
doc.comment("add", anchor=hit.anchor, text="Confirm term length", author="Wenzel Joubert")
doc.save("contract-amended.docx")                 # or doc.to_bytes() for in-memory use
```

`Document.paragraphs()` returns fresh `Paragraph` objects (anchor, normalized text, styleId) on every call — re-fetch after any edit rather than reusing an old list. Every `Document` method name mirrors its `docx_*` tool 1:1 (`doc.replace` → `docx_replace`, `doc.table` → `docx_table`, etc.), so the tool JSON specs double as the Python method reference.

## How this workspace uses it

`framework/vendor/docxengine/` is the vendored copy; `framework/csa_docx/engines/docxengine_adapter.py` wraps it as the default engine for this workspace's CSA document framework (see the `iamps-csa-document-agent` / `iamps-csa-change-review-agent` skills). Notable local integration details:

- Imported as a library (`from docxengine import Document`), not run as a separate MCP process — the adapter inserts `framework/vendor` onto `sys.path` and imports directly.
- Requires a Python interpreter matching DocxEngine's `Requires-Python: >=3.12` with dataclass `slots` support; this workspace's default `python3` is too old and fails with `dataclass() got an unexpected keyword argument 'slots'` — use `/opt/homebrew/bin/python3.14` (see `framework/csa_docx/README.md`).
- The adapter classifies each approved change record (insert/delete/replace/table-cell/range/etc.), calls the matching `Document` method, adds a Word comment recording the edit (author "Wenzel Joubert", initials "WJ"), and returns `APPLIED`/`BLOCKED` rather than guessing at ambiguous instructions — mirroring DocxEngine's own philosophy of raising `ambiguous_target`/`anchor_stale` rather than silently picking a match.
- A timestamped `.bak` backup is taken before every mutating run, independent of DocxEngine's own validation gate.

## Practical tips

- Always re-search/re-read for a fresh anchor immediately before an edit; never carry an anchor across an edit boundary.
- Prefer `docx_edit_paragraph` (whole-paragraph rewrite with automatic word-level diff) over `docx_replace` when replacing most of a paragraph; prefer `docx_replace` for small in-paragraph substitutions.
- Turn `track_changes` on whenever the output needs to be reviewable/approvable in Word — edits with it off are physical changes with no redline trail.
- Call `docx_save` (or `Document.save`) even mid-task; it doesn't close the doc_id, so it's safe to save after each logical batch rather than only once at the end — and it's the only tool that refuses to persist a package that would trigger Word repair.
- Don't call `docx_render_preview` after every edit — batch it at verification checkpoints.
- When `docx_validate` reports errors, run `docx_repair` once and re-validate rather than hand-patching XML.
