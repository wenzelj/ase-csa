# CSA MCP Function Factory — Plan for Small-Model (qwen3-4b) Execution

## The problem, concretely

The transcript from today's Codex CLI run against qwen3-4b confirms the failure mode directly: given the full `iamps-csa-document-agent` skill text (now `csa-document-agent`) as its instructions, the model never reaches the framework call. It spends its whole turn reasoning out loud about which of Codex's *default* tools (`get_goal`, `create_goal`, `web_search`) it's supposed to invoke, because nothing in its context tells it there is a specific, narrow function for this job — it only has a long natural-language spec describing a workflow, a CLI invocation pattern with placeholders (`<SECTION>`, `<n>`, `<a>`, `<b>`) it has to fill in by inventing file paths, and a list of prose rules ("do not overthink it", "make a verified backup") it has no way to act on directly.

This is not a prompting problem that a better-worded skill file fixes. A 4B model is weak exactly where the current design leans on it:

- **Path construction.** `cli_apply_section.py` needs `--change-file` and `--docx` as real paths, but the skill only gives a *pattern* (`01 Current State AS Built/<n> IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section<N>_E<a>_E<b>.md`). Filling in `<n>`, `<a>`, `<b>` means listing a directory and pattern-matching filenames — small models are unreliable at this and will confabulate a plausible-looking path that doesn't exist. (The actual working docx today is `Current State Assessment - IAMPS.docx` — no `-v1` suffix, even though the skill text's example command has `- v1`. A model guessing from the skill text alone would build a wrong path right now.)
- **No callable surface.** The model has no tool named anything like "apply the next CSA batch." It has a shell/exec tool (if Codex gives it one) and a wall of English telling it what command to type. Every run re-derives the same call from scratch, in free text, with no schema to keep it honest.
- **Unbounded judgment calls.** The skill text also tells it what to do on `BLOCKED`, when to stop, when to update learning notes — open-ended decisions a 4B model shouldn't be making at all.

The framework itself (`csa_docx/`) is already in good shape for this — `cli_apply_section.py` is a single deterministic entry point that returns structured JSON (`status`, `applied`, `blocked`, `next_edit_id`, `validation`, ...). The gap is entirely in *how that capability is exposed* to the model: as 450 lines of prose to be interpreted, instead of as a function to be called.

## Precedent already in this repo

`framework/vendor/docxengine/` ships exactly the pattern we want: `mcp.py` + `_mcp_facade.py` implement a small, dependency-free stdio MCP server — `tools/list` returns JSON-schema'd tool definitions, `tools/call` dispatches to plain Python functions, results come back as structured JSON, errors come back as `isError: true` tool results instead of exceptions the model has to parse out of stack traces. `bin/docxengine-mcp` is the launcher Codex/Claude would point at.

We build the equivalent for `csa_docx`: a `csa-mcp` server exposing a handful of high-level tools (`list_sections`, `get_section_status`, `apply_next_batch`, `validate_section`, ...), backed by the same Python modules `cli_apply_section.py` already uses. No rewrite of the editing engine — only a new, thin calling surface on top of it, plus one piece of real new work: a deterministic section manifest so nothing ever has to guess a filename again.

## Design

### 1. Section manifest (removes all path-guessing)

Every section's change file already follows one fixed, greppable pattern: `ChangesCSA_IAMPS_Section<N>_E<a>_E<b>[_Suggested].md` inside a `.../01 Final Version/reviews/` directory, one file per section, no ambiguity — confirmed against the actual `7 IAMPS/01 Final Version/reviews/` folder (16 files, sections 1–16, exactly this shape). So path resolution doesn't need fuzzy matching (rapidfuzz stays reserved for what it's already used for — table/label similarity inside a document); it needs one deterministic scan.

Add `csa_docx/manifest.py`:

- `build_manifest(workspace: Path) -> dict[str, SectionEntry]` — globs for `**/reviews/ChangesCSA_*_Section*_*.md` under the workspace, regex-extracts the section number and edit-ID range from each filename, and pairs each with the one `.docx` that sits in the same `01 Final Version` folder (today: `Current State Assessment - IAMPS.docx`; the function resolves this by listing `*.docx` in that folder rather than hardcoding the name, so a rename doesn't silently break it — if more than one `.docx` is found it returns an explicit `AMBIGUOUS_DOCX` error rather than guessing).
- `SectionEntry`: `{section, change_file, docx, edit_id_range}`.
- Cached to `/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/framework/csa_docx/section_manifest.json` and rebuilt on demand (`refresh_manifest()`), so repeated calls are cheap and a human can eyeball the resolved paths.

This one file is what turns "the model has to know the folder-naming convention" into "the model passes `section=7`."

### 2. A thin function layer (`csa_docx/tools.py`)

Extract the body of `cli_apply_section.main()` into an importable function so the CLI and the MCP server share one implementation (no forked logic):

```python
def apply_next_batch(section: str, limit: int = 3, engine: str = "docxengine",
                      track_changes: bool = True, workspace: Path | None = None) -> dict:
    """Resolves section -> (change_file, docx) via the manifest, then does exactly
    what cli_apply_section.py's main() does today, returning the same JSON payload
    print_summary() already builds."""
```

Alongside it, a small fixed set of other functions, each doing one thing and returning JSON — deliberately not a general-purpose "run arbitrary command" tool:

- `list_sections()` — manifest contents plus each section's current status (`SECTION_COMPLETE` / `PARTIAL_COMPLETE` / `BLOCKED` / `not started`) read from its run-state file. This is the one call a small model needs to pick what to work on next, with zero path knowledge required.
- `get_section_status(section)` — run-state + change-report summary for one section.
- `apply_next_batch(section, limit=3)` — the main one; wraps the existing apply pipeline.
- `validate_section(section)` — just `validate_docx()` on the resolved docx, for a cheap standalone integrity check.
- `refresh_manifest()` — rescan for new/renamed change files.

Every function takes a small number of primitive arguments (strings/ints/bools), returns a plain JSON-serializable dict, and raises nothing the caller has to interpret — errors come back as `{"status": "ERROR", "message": "..."}` in the same shape as success, matching how `docxengine`'s facade turns exceptions into `isError` tool results rather than letting a traceback reach the model.

### 3. `csa_docx/mcp.py` — the MCP server itself

Same shape as `docxengine/mcp.py`, much smaller: stdio JSON-RPC, `initialize` / `tools/list` / `tools/call`, no HTTP transport needed for a local Codex CLI setup. `tools/list` returns one schema per function above, e.g.:

```json
{
  "name": "apply_next_batch",
  "description": "Apply the next bounded batch of approved edits for a CSA section to the working DOCX. Creates a timestamped backup first, applies up to `limit` pending edits as tracked changes, validates the result, and updates the run-state and change-report files. Returns status: SECTION_COMPLETE | PARTIAL_COMPLETE | BLOCKED, plus which edit IDs were applied/blocked and the next edit ID if any.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "section": {"type": "string", "description": "Section number, e.g. \"7\"."},
      "limit": {"type": "integer", "default": 3, "description": "Max edits to apply this call."}
    },
    "required": ["section"]
  }
}
```

`bin/csa-mcp` launcher mirrors `bin/docxengine-mcp` (same shebang/interpreter pin — recall the existing note that the framework needs `/opt/homebrew/bin/python3.14` for dataclass `slots`, not the system `python3`).

### 4. Wiring into Codex CLI

Codex CLI's MCP servers are registered in `~/.codex/config.toml` under `[mcp_servers.<name>]` (`command`, `args`, optional `env`) — I can't see or edit that file myself since it's outside the folder connected to this session (only `06 IAMPS` is mounted), so this is the one step you'd do by hand:

```toml
[mcp_servers.csa]
command = "/opt/homebrew/bin/python3.14"
args = ["/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/framework/csa_docx/bin/csa-mcp"]
```

Once that's in place, `list_sections` / `apply_next_batch` / etc. show up as ordinary callable tools in Codex CLI's tool list for any model you point at it, qwen3-4b included — no different from how it already sees `get_goal` / `create_goal`.

### 5. What the small model actually needs to be told

With the manifest and the MCP tools doing the path work and the mechanics, the "skill" text a 4B model needs shrinks from ~450 lines to something like:

```
You have tools: list_sections, get_section_status, prepareDocument, apply_next_batch, validate_section.

Call prepareDocument with no arguments (it prepares the whole document, not one
section — never pass `section` unless it errors asking you to disambiguate).
If the result status is NOT_READY, stop and report its `reasons` — do not call
apply_next_batch. (reasons: locked_by_word means the document is open in Word and
the user must close it; the others mean the document is missing or damaged.)
If it is not READY, stop.
Call list_sections. Pick the first section whose status is not SECTION_COMPLETE.
Call apply_next_batch with that section and limit=10.
If the result status is BLOCKED, stop and report it — do not attempt to fix it yourself.
If it is NOT_READY, stop and report it; the document was not modified.
If it is PARTIAL_COMPLETE or SECTION_COMPLETE, stop; the batch is done.
Do not call anything else. Do not inspect the DOCX directly.
```

That's a fixed control loop with four tool calls and two branches — well inside what a 4B tool-calling model can execute reliably, because every hard decision (which file, how to edit OOXML, whether the document is even safe to open, whether a batch validated) has already been made by the deterministic code behind the tool, not by the model reading prose.

`prepareDocument` is the step-0 readiness gate added after the first implementation pass: it refuses to proceed on a document that is open in Word, zero-byte, corrupt, or already failing `validate_docx`, and it builds/refreshes the `stable_ids.py` structural-ID manifest the `@H...` anchors resolve against. `apply_next_batch` enforces the same preconditions internally (before `create_backup()`), so a model that forgets the step-0 call still cannot start editing a locked document — the explicit call just turns a mid-run surprise into a clean up-front answer, and is the only way to (re)generate the ID manifest over MCP.

`section` is optional and, per the loop above, deliberately left out: the manifest it builds covers every heading/paragraph/table-row in the *whole* document and is cached by the resolved docx path (`run-state/stable-ids-<docx-filename>.json`), not by section number, so there's nothing section-specific to ask the model for. With no `section`, it resolves the one working `.docx` every CSA section's change file already points at directly — no `list_sections` call needed first just to pick an arbitrary section number to hand it. It only fails (`{"status": "ERROR", ...}`) if the workspace genuinely has more than one distinct working `.docx`, in which case it names the ambiguity and asks for an explicit `section` rather than guessing — the same "never guess" discipline `manifest.py` already applies everywhere else. Because the loop calls it once, before picking a section to work on, one `prepareDocument` call prepares the document for the whole run; every later call against the same file (if the model or a human calls it again) is a free `regenerated: false` no-op rather than a rebuild.

This also gives the *authoring* side a deterministic building block it didn't have before, without turning "decide what in the document needs to change" into a tool call (that stays out of scope for the same reason `BLOCKED` resolution does — see below). Whoever drafts `ChangesCSA_*.md` — human or a bigger model — runs `prepareDocument()` once, then as they walk the document deciding what to improve, calls `lookupStableId(query)` for each edit instead of quoting anchor text or hand-grepping the manifest JSON. It's the deterministic sibling to `prepareDocument`, `section` optional for the same reason: read-only, never opens the DOCX (just the cached manifest), matches a text snippet (or an `@H...` ID itself, to confirm it) and hands back the ID(s) to drop into `Where:`. It doesn't disambiguate for you — `unique_id` is only set on an exact single match, so a caller still has to recognize and narrow an ambiguous result, which is exactly the judgment this framework leaves to the caller everywhere else. That authoring role — walking the document, deciding what needs to change, creating the `reviews/` folder and the `ChangesCSA_*.md` files — is the `csa-change-review-agent` (see the review-agent note below on why judging document content isn't a function-factory fit); `prepareDocument` + `lookupStableId` only guarantee the ID that decision needs is already there and cheap to fetch.

## What stays out of scope for the small model (on purpose)

- **`BLOCKED` resolution.** Manual repair of a blocked edit is real semantic judgment over document structure — that stays a job for you or a bigger model, triggered by the small model simply reporting `BLOCKED` and stopping, per the loop above.
- **The review agent (`csa-change-review.md` / `csa-change-review-agent`).** Unlike the apply side, review today has *no deterministic backing code at all* — it's 100% "read the DOCX, read the comments, read the change report, judge PASS/FAIL" prose. That can't be turned into a small-model function call without first writing real verification code (diff applied paragraph text against the approved `**Text:**` field, confirm a comment ID exists per completed edit ID, re-run `validate_docx`). That's a separate, larger follow-on — call it Phase 2 — and even then the output should probably be `PASS_MECHANICAL` / `NEEDS_HUMAN_REVIEW` rather than a real sign-off, since judging whether wording is *correct*, not just present, is exactly the kind of thing a 4B model shouldn't be trusted with.
- **Cleanup / sign-off** (framework-robustness-plan.md Phase 2–3) is downstream of review being trustworthy, so it waits too.

## Implementation phases

1. **Manifest** — `csa_docx/manifest.py`, tested against the real `reviews/` folder for all 16 current sections; confirms the single-docx-per-folder assumption holds and fails loudly (not silently) if it ever doesn't.
2. **Extract `apply_next_batch()`** out of `cli_apply_section.main()` as an importable function with the same behavior; repoint the CLI at it so there is exactly one implementation, not two to keep in sync.
3. **`tools.py`** — the other four functions, each a thin read of run-state/manifest/`validate_docx`.
4. **`mcp.py` + `bin/csa-mcp`** — the stdio server, modeled directly on the vendored `docxengine/mcp.py` (reuse its JSON-RPC boilerplate rather than reinventing it).
5. **Smoke test** — run the MCP server by hand (`echo '{"jsonrpc":"2.0","id":1,"method":"tools/list",...}' | csa-mcp`) and confirm `tools/list`/`tools/call` round-trip before wiring it into Codex CLI's config.
6. **You add the `config.toml` entry** and give qwen3-4b the short control-loop prompt above instead of the full skill text; a first live run on a section that's already known-complete (e.g. Section 1) is the cheapest way to confirm the loop terminates correctly on `SECTION_COMPLETE` before trying it on a section with real pending edits.
7. **(Later, separate effort) Phase 2** — mechanical review-verification functions, only after Phase 1 is proven out.

## Risk notes

- The manifest's one-docx-per-folder assumption should be asserted, not trusted — `build_manifest()` must hard-fail with a clear error on any section folder with zero or multiple `.docx` files rather than picking one.
- Keep `apply_next_batch`'s `limit` defaulting low (3, as today) even though the function layer makes it easy to raise — the batch-size discipline is what keeps a bad small-model run cheap to recover from.
- The MCP server should never expose a generic "run this shell command" tool; every capability the small model gets should be one of the fixed, reviewed functions above. That's what makes this safe to hand to a 4B model in the first place.
