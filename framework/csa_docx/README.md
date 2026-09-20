# CSA DOCX Framework

Reusable helpers for applying approved Current State Assessment Markdown change records to Word `.docx` files.

The framework is intentionally conservative. It automates repeatable tasks and returns `BLOCKED` when an anchor, range, or edit instruction is ambiguous instead of guessing.

## Current Capabilities

- Parse approved Markdown change records into edit records.
- Select bounded edit batches by section and edit ID.
- Create verified timestamped DOCX backups.
- Inspect and edit `word/document.xml` in a DOCX package.
- Use the vendored open-source `docxengine` library by default for anchored paragraph, list, section-body, heading-bounded range, subsection-delete, paragraph-plus-following-line, and supported table-cell edits.
- Add Word comments with configured author and initials.
- Validate ZIP integrity, XML parseability, comment relationships, comment marker pairing, and unsafe direct table-row comment markers.
- Update `01 Current State AS Built/7 IAMPS/01 Final Version/run-state/current-state-assessment-document-section-<SECTION>.md`.
- Append/update `## Changes Report` in the approved Markdown change file.
- Replace `Observed` and `Assessment` cells for uniquely matched table rows.
- Replace multi-row table values when the approved text labels each row, for example `Network Services - Observed`.
- Replace paragraph ranges described as `replace the content beginning ... through ... with`.
- Replace paragraph ranges described as `Replace this sentence and all bullets through: <end anchor>`.
- Replace heading-bounded ranges described as `Replace all content from this heading through the sentence ending: <end anchor>`.
- Replace all body content in a subsection when the approved instruction says `Replace all content in Section X.Y.Z`, the `Where` anchor is unique, and the containing Word heading range is unambiguous.
- Replace entire subsection bodies when the approved instruction says `Replace the entire subsection`.
- Replace an anchor paragraph and a fixed number of following bullet/content paragraphs when the approved instruction says `Replace this sentence and its N bullets`.
- Replace an anchor paragraph plus the following line when the approved instruction says `Replace this paragraph and the following line`.
- Delete a contiguous heading range when the approved instruction says `Delete Sections ... up to <next heading>`.
- Convert Markdown bullet lines into separate Word paragraphs instead of collapsing adjacent bullets into one paragraph.
- Convert multi-paragraph Markdown *blockquote* replacement text (the project's standard way of writing a multi-paragraph `**Text:**` field - every line, including blank separators, prefixed with `>`) into separate Word paragraphs, stripping the `>` markers instead of leaking them into the applied text. Fixed 2026-09-17: a bare `>` separator line is non-empty and previously defeated blank-line paragraph splitting in `markdown_to_paragraph_texts`, collapsing an entire multi-paragraph/bulleted blockquote into one corrupted paragraph containing literal `>` characters (found via E-146 and E-153 in Section 9; both were applied under the buggy code and were subsequently repaired in place).
- Scope a non-unique anchor to the correct subsection by heading name even when the change file's section label and the document's heading use different British/American spelling (for example "Synchronisation" vs "Synchronization") via `ooxml.spelling_normalised_text`.
- Replace an entire table's content (header and/or row labels included) when the approved instruction says `Replace the table content`, even when the approved text renames row labels and the approved caption text isn't literally present in the document. Locates the table via its caption when that caption matches uniquely, otherwise via being the single unambiguous table inside the section-heading-scoped range; overwrites every cell positionally with `docx_table set_cells` once dimensions are confirmed to match, and refuses (BLOCKS) rather than reshapes a table whose row/column count differs from the replacement.
- Resolve a labelled table-row lookup (Observed/Assessment value update) with a fuzzy match on the row label when no exact/prefix match exists, via the vendored `rapidfuzz` (falling back to the standard-library `difflib` if rapidfuzz's vendored wheel doesn't match the running platform), accepting only a clear, unambiguous best match.

## Example

```bash
/opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_apply_section.py \
  --engine docxengine \
  --section 4 \
  --change-file "7 IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section4_E69_E76.md" \
  --docx "7 IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx" \
  --limit 3 \
  --comment-author "Wenzel Joubert" \
  --comment-initials "WJ"
```

The framework defaults to DocxEngine. The explicit engine flag is still shown here for clarity:

```bash
/opt/homebrew/bin/python3.14 .agents/framework/csa_docx/cli_apply_section.py \
  --engine docxengine \
  --section 6 \
  --change-file "7 IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section6_E95_E111.md" \
  --docx "7 IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx" \
  --limit 1 \
  --start-edit-id E-100 \
  --end-edit-id E-100
```

## Safety Model

The framework only edits the active working DOCX passed with `--docx`. It creates a `.bak` backup before mutation. It does not create new document versions by itself.

Supported edit operations are deliberately narrow:

- Insert before/after a uniquely matched paragraph anchor.
- Replace a uniquely matched paragraph anchor with approved text.
- Delete a uniquely matched paragraph anchor.
- Replace labelled table-row `Observed` and `Assessment` values through DocxEngine table cell writes.
- Replace labelled multi-row table values through DocxEngine table cell writes.
- Replace a uniquely bounded paragraph range with approved paragraphs or bullets.
- Replace a uniquely bounded sentence-plus-bullets range ending at an approved final bullet anchor.
- Replace all content below a containing subsection heading while preserving that heading and the next same-or-higher heading.
- Replace an anchor paragraph plus a declared number of following bullet/content paragraphs, stopping safely if a heading is encountered too early.

Unsupported, ambiguous, or non-unique operations are reported as `BLOCKED` instead of guessed. A blocker should now mean a real document or instruction ambiguity, not an unrecognised wording variant.

Use DocxEngine for paragraph, list, range, subsection-body, subsection-delete, paragraph-plus-following-line, and supported table-cell operations. Use `--engine legacy` only when explicitly testing or recovering an older legacy path.

## Vendored Third-Party Libraries

Alongside `docxengine`, `framework/vendor/` also carries:

- `mistune` (pure Python, MIT) - parses approved replacement Markdown tables for the whole-table-replace capability, instead of a hand-rolled pipe-table regex.
- `rapidfuzz` (MIT) - fuzzy row-label matching for the labelled table-row lookup. Vendored as a wheel built for the Mac's `/opt/homebrew/bin/python3.14` (macOS arm64, cp314); the adapter falls back to `difflib` if that wheel doesn't import on whatever interpreter actually runs it.

Both were fetched by running `python3.14 -m pip download <package> --no-deps -d .` on the Mac (network access to PyPI is not available from every environment this framework may run in) and unpacked directly into `framework/vendor/` the same way the `docxengine` wheel is - no system-wide `pip install` required on any machine that runs this framework.

## Function Factory / MCP Server

For a tool-calling model (including a small one, e.g. qwen3-4b) that can't reliably construct the `--change-file`/`--docx` paths above from a section number alone, the framework also exposes itself as a handful of named functions instead of a CLI to be constructed from prose:

- `manifest.py` - deterministically resolves `section -> (change_file, docx)` by scanning for `ChangesCSA_..._Section<N>_E<a>_E<b>.md` files under `reviews/` directories (skipping anything under an `archive`/`old*` folder) and pairing each with the one `.docx` in its `Final Version` folder. Fails loudly (`ManifestError`) on any ambiguity - never guesses. The manifest is derived fresh from the live folder layout on every call and is never cached to disk, so archiving an old Final Version folder and dropping in a new document is picked up automatically with no reset step (the old section_manifest.json cache was removed for exactly this reason: it silently pointed at dead paths once the workspace moved). refresh_manifest() is therefore just a re-scan that returns the current mapping; it no longer rebuilds any cache.
- `tools.py` - `list_sections()`, `get_section_status(section)`, `prepareDocument(section=None, force_regenerate=False)`, `lookupStableId(query, section=None, kind=None, limit=10, case_sensitive=False)`, `apply_next_batch(section, limit=3)`, `validate_section(section)`, `refresh_manifest()`. Each takes primitive arguments and a section number (never a path), returns plain JSON, and reports failures as `{"status": "ERROR", ...}` rather than raising. `apply_next_batch` is the same logic `cli_apply_section.py` runs (the CLI now calls into this module so there is exactly one implementation).
- **`prepareDocument()` - step 0, the very first call of a project.** This is meant to run before *anything else exists* - before a `reviews/` folder, before any `ChangesCSA_*.md` change file. At this point the workspace holds nothing but the raw working `.docx`, so `section` is not just optional, it's meaningless: there's no section manifest yet for it to name a section *from*. Call it with no arguments. `_resolve_shared_document` handles both states a workspace can be in:
  - **No `reviews/` change file exists anywhere yet (true step 0).** `_find_workspace_docx` finds the one `.docx` in the workspace directly (recursively, skipping Word lock files and anything under an `archive`/`old*` folder) and prepares that. `section` and `change_file` come back `null` in the response - there's nothing to report yet.
  - **`reviews/` change files already exist** (a later re-run, or a project that was already underway when `prepareDocument` was introduced). Every section normally resolves to the same working `.docx` (`manifest.py`'s one-docx-per-Final-Version-folder rule), so `_resolve_shared_document` scans the manifest and prepares that document directly; the lowest-numbered section is reported as a readable label, with no other significance.

  Either way it never silently guesses: if the workspace genuinely has more than one candidate `.docx` (no section to disambiguate with yet) or more than one distinct working `.docx` across sections (once they exist), `prepareDocument()` fails loud with `{"status": "ERROR", ...}` naming the ambiguity rather than picking one. Passing an explicit `section` still works once the section manifest exists, and resolves to the same document in the common one-docx case.

  The readiness checks and the stable structural ID manifest this builds or refreshes (`@H<section_path>-P<n>` / `@H<section_path>-T<n>-R<n>`, from `stable_ids.py`) both cover *every* heading, paragraph, and table row in the entire `.docx` - the same thing `cli_apply_section.py --dump-ids` prints, but written to disk and reachable over MCP. The manifest is cached at `run-state/stable-ids-<docx-filename>.json`, keyed by the resolved document path, so calling this again later - with or without a section, once `reviews/` exists or not - is an instant `"regenerated": false` no-op rather than a rebuild, as long as the heading structure hasn't drifted.

  Once the document is prepared, the `csa-change-review-agent` (`.agents/csa-change-review.md`) - the authoring step that creates the `reviews/` folder and walks the document section by section deciding what needs to change, writing that out as `ChangesCSA_*.md` files - looks up each change's `@H...` ID straight out of the one shared manifest via `lookupStableId` and drops it into `Where:` instead of quoting text (that decision - "walk the document and decide what needs to change" - is judgment work for a human or bigger model, same as `BLOCKED` resolution; `prepareDocument` only guarantees the ID each decision maps to is already sitting there waiting). Returns:

  ```json
  // prepareDocument() at true step 0 -- nothing but the raw .docx exists yet
  {
    "status": "READY",
    "reasons": [],
    "section": null,
    "change_file": null,
    "docx": ".../Current State Assessment - IAMPS.docx",
    "id_manifest_summary": {
      "paragraphs": 1918, "runs": 0, "headings": 217, "table_rows": 0,
      "regenerated": true, "reason": "created",
      "path": ".../run-state/stable-ids-Current_State_Assessment_IAMPS.json"
    },
    "validation": {"archive_integrity": "Pass", "...": "..."}
  }
  ```
  ```json
  // prepareDocument() again, later -- reviews/ now exists, structure unchanged
  {
    "status": "READY",
    "reasons": [],
    "section": "7",
    "docx": ".../Current State Assessment - IAMPS - v1.docx",
    "change_file": ".../reviews/ChangesCSA_IAMPS_Section7_E112_E135.md",
    "id_manifest_summary": {
      "paragraphs": 412, "runs": 96, "headings": 58, "table_rows": 96,
      "regenerated": false, "reason": "unchanged",
      "path": ".../run-state/stable-ids-Current_State_Assessment_IAMPS.json"
    },
    "validation": {"archive_integrity": "Pass", "...": "..."}
  }
  ```

  Regenerating is idempotent: the cached manifest is fingerprinted on the document's *heading skeleton* (heading count, level, and assigned section path), which is exactly what stable IDs are derived from. Body-text edits therefore leave it valid and a second call - from the same section or any other section sharing the document - is a reported no-op (`"regenerated": false, "reason": "unchanged"`); a heading added, removed, or reordered is drift, so the manifest is rebuilt and the response says so (`"reason": "structure_drift"`) rather than changing underfoot. `force_regenerate=True` rebuilds unconditionally (`"reason": "forced"`). `runs` counts the `-R<n>` table-row IDs and is the same number as `table_rows`.

- **`lookupStableId(query, section=None)` - the deterministic complement to `prepareDocument`, for drafting a change file.** `section` is optional here too, for the same reason: once the document has been prepared (`prepareDocument()`, no section needed), this is how an authoring step - a small model, a bigger one, or a human - turns "I found something to fix here" into the right `Where:` anchor, without shelling out to `jq` or hand-editing JSON or needing to know a section number at all. It never opens the DOCX itself; it only reads the manifest `prepareDocument` already cached, so it's cheap to call once per edit. Two query modes, auto-detected: a plain snippet of the paragraph/row text (case-insensitive substring match by default) returns the matching `@H...` ID(s); an `@H...` ID itself is looked up exactly, to confirm it's still current. `kind` optionally narrows to `"heading"` / `"paragraph"` / `"table_row"`; `limit` caps how many matches come back (`truncated: true` if there were more). It never BLOCKS and never picks among ambiguous matches for you - `unique_id` is only set when `match_count == 1`, so a caller can check that before trusting a lookup as safe to use unquoted; deciding which of several matches is the right one is the same kind of judgment call this framework always leaves to whoever is drafting the change, not something a deterministic tool should guess at.

  ```json
  // lookupStableId(query="DNS Location")
  {
    "status": "OK",
    "match_count": 1,
    "truncated": false,
    "unique_id": "@H2.1.4-P2",
    "matches": [{"id": "@H2.1.4-P2", "kind": "paragraph", "section_path": "2.1.4", "text": "DNS Location: Enterprise IT hosted...", "anchor": "..."}],
    "possibly_stale": false,
    "manifest_generated_at": "2026-09-19T11:02:26+00:00"
  }
  ```
  ```markdown
  **Where:** `@H2.1.4-P2`
  ```
  The framework resolves `@`-prefixed IDs before falling back to text matching, so no anchor sentence needs to be quoted at all once you have the ID. `possibly_stale` is a cheap mtime comparison (docx modified after the manifest was written) - it's advisory, not a block; re-run `prepareDocument` if it's `true` and you want a fresh manifest before trusting the result. Returns `{"status": "ERROR", ...}` if `prepareDocument` hasn't been run for this section yet - there is no implicit auto-prepare.
- **`NOT_READY` - the step-0 preconditions.** `prepareDocument` *and* `apply_next_batch` both run the same checks before anything is written; in `apply_next_batch` they run before `create_backup()`, so a `NOT_READY` result means the working DOCX was not touched at all - no backup, no partial batch, no run-state write. Checked cheapest-first, first failure wins, and the failing check's tag lands in `reasons`:

  | `reasons` entry | Meaning |
  | --- | --- |
  | `missing_docx` | The resolved path does not exist (dropped mount, moved file). |
  | `empty_docx` | Zero bytes - a failed copy or an in-progress write. |
  | `locked_by_word` | A Word owner/lock file sits beside the document, i.e. somebody has it open. Both naming conventions are checked: `~$<filename>.docx` and Word's usual truncated `~$` + filename-minus-first-two-characters (`Report.docx` -> `~$port.docx`). Close the document in Word and retry. |
  | `unreadable_archive` | The file does not open as a zip package, or `testzip()` finds a corrupt member - catches a corrupt or mid-write DOCX before DocxEngine does. |
  | `validation_failed` | `validate_docx()` already reports failures *before* any edit. The full `validation` dict comes back attached so the caller can see which check failed. |

  `validate_docx()` is therefore now a pre-flight check as well as the post-edit one it has always been.
- `mcp.py` + `bin/csa-mcp` - a small stdio JSON-RPC MCP server (same `tools/list`/`tools/call` shape as the vendored `docxengine-mcp`) exposing the seven functions above as MCP tools. Point any MCP-capable harness (Codex CLI, Claude Code, ...) at `bin/csa-mcp`'s absolute path via its `mcp_servers` config; set `CSA_MCP_WORKSPACE` to this workspace root if the server's default working directory isn't already there.

See `.agents/qwen-mcp-factory-plan.md` for the full design and rationale.
