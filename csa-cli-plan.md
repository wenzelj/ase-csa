# CSA CLI Plan — one command for the agents, skills and framework

**Status:** Approved and implemented (phases 0–4) · 2026-09-23 · Scope: `/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents`

## 1. What is there today

| Layer | What exists | How you use it today |
| --- | --- | --- |
| Agent definitions (9) | Change pipeline: `csa-change-authoring.md` → `current-state-assessment-document.md` → `csa-change-review.md` → `csa-change-cleanup.md`. Analysis workflow: `csa-orchestrator-agent.md` → investigator / technical-analyst / writer / quality-reviewer | Paste a 6–8 line block: "Load this agent definition: <absolute path>… Act as… SECTION=… LIMIT=… RUN_SCOPE=…" |
| Skills (27 dirs) | 3 wrappers around agents (`csa-change-authoring-agent`, `csa-document-agent`, `csa-change-review-agent`), 16 OT skill-pack skills, tooling skills (evidence-matrix, document-template, writing-style, diagram-generator, create-table), library refs (docxengine, mistune, rapidfuzz) | `Use $csa-document-agent.` + the same parameter block (Codex native skills) |
| Framework code | `csa_docx` (MCP server `bin/csa-mcp` with 7 tools, `cli_apply_section.py`, `cli_create_table.py`, dry-run tool, tests) | MCP must be registered by hand in `~/.codex/config.toml`; CLI needs long `--change-file`/`--docx` relative paths and `/opt/homebrew/bin/python3.14` |
| Skill scripts (8) | `evidence_matrix.py`, `graph_store.py`, `prose_lint.py`, `new_csa.py`, `scaffold_csa.py`, `check_csa.py`, `build_diagram_model.py`, `analyze_public_egress.py` | Each called by full path with its own flags and its own way of finding the project |
| Project registry | `csa-context/PROJECTS.yaml` (iamps, utcdtc) + per-project context YAML; code-enforced `WORKSPACE_NOT_REGISTERED` guard | Orchestrator asks "which project?" every run unless you paste `PROJECT_CONTEXT` + `WORK_DIR` |

## 2. Friction points found

1. **Prompts are long and path-heavy.** Every run repeats absolute paths, the agent name and 3–4 parameters. Easy to paste the wrong project or stale defaults.
2. **No "active project".** The project is asked for or pasted every run. The safety guard is good, but the selection step is manual each time.
3. **Uneven entry points.** Only 3 of 9 agents have skill wrappers. Cleanup, orchestrator-as-agent, investigator, analyst, writer and quality-reviewer must be loaded by path. Wrapper names don't match agent file names (`csa-document-agent` ↔ `current-state-assessment-document.md`).
4. **Deterministic steps go through an LLM.** Status, prepare, lookup, validate, lint, evidence stats and template checks are pure scripts, but are usually reached by asking an agent to run them.
5. **No "what's next?" view.** State is spread across `run-state/*.md`, `reviews/ChangesCSA_*.md` status lines, `csa-work/assessment-state.yaml` and the evidence matrix. You have to know where to look to see which section is at which pipeline step.
6. **Tool-specific wiring is manual.** Codex reads `.agents/skills`; Claude Code reads `.claude/skills|agents|commands` and `.mcp.json`; Hermes/Ollama need their own prompt. None is generated.
7. **Small hygiene items.** `skills/csa-docx-create-table/SKILL.md` has no frontmatter (won't be discovered as a skill); four `*.bak` files sit inside `framework/csa_docx/` instead of `backups/`; there is no root `AGENTS.md`, so a fresh CLI session has no orientation.

## 3. Target experience

```text
$ csa use iamps                      # set active project once (checked against PROJECTS.yaml)
$ csa status                         # table: section → authored / approved / applied / reviewed / cleaned
$ csa next                           # "Section 6: 2 approved edits not applied → csa apply 6"

$ csa author 6                       # launches the authoring agent in your chosen CLI, prompt pre-built
$ csa approve 6                      # flips the ChangesCSA status line after you've read it (human gate)
$ csa apply 6 --limit 2              # framework-first: deterministic batch, no LLM unless BLOCKED
$ csa review 6
$ csa cleanup 6

$ csa ask infrastructure "hosting section"   # orchestrator/analysis workflow
$ csa ev lookup "SQL Server version"         # evidence matrix, no LLM
$ csa lint 6 · csa check --final · csa doctor
```

Inside an interactive CLI session the same verbs exist as slash commands (`/csa-author 6`, `/csa-status`) generated from the same source.

## 4. Design

### 4.1 One registry drives everything — `.agents/registry.yaml`

Single source of truth for every agent: short verb, agent file, skills it may load, required inputs and defaults, pipeline step, and whether it can run framework-first.

```yaml
agents:
  author:   { file: csa-change-authoring.md, step: 1, inputs: {SECTION: required, AUTHOR_ITEM_LIMIT: 6, RUN_SCOPE: next-authoring-batch, EDIT_MODE: evidence} }
  apply:    { file: current-state-assessment-document.md, step: 2, framework_first: true, inputs: {SECTION: required, ITERATION_EDIT_LIMIT: 2, RUN_SCOPE: next-batch} }
  review:   { file: csa-change-review.md, step: 3, inputs: {SECTION: required, ITERATION_REVIEW_LIMIT: 2, RUN_SCOPE: next-batch} }
  cleanup:  { file: csa-change-cleanup.md, step: 4, inputs: {SECTION: required} }
  ask:      { file: csa-orchestrator-agent.md, inputs: {SECTION: required, SOURCE_SET: project-default} }
  evidence: { file: csa-evidence-investigator-agent.md, ... }
  analyse:  { file: csa-technical-analyst-agent.md, inputs: {ANALYSIS_SKILL: required, ...} }
  write:    { file: csa-writer-agent.md, ... }
  qa:       { file: csa-quality-reviewer-agent.md, ... }
```

The README's usage blocks, the skill wrappers and the slash commands are generated from this file, so they cannot drift from each other again.

### 4.2 `csa` command — `.agents/bin/csa` (Python ≥3.10, stdlib + vendored libs only)

Three groups of subcommands:

**a) Project context (no LLM)**
- `csa projects` — list PROJECTS.yaml.
- `csa use <key>` — write the active project to `.agents/.state/active-project` (git-ignored). Override per call with `--project` or `CSA_PROJECT`. Every command prints `[IAMPS]` first so a wrong pick is visible.
- The resolved `PROJECT_CONTEXT`, `WORK_DIR`, `SOURCE_SET`, workspace and working DOCX are passed explicitly to every agent and script, so the orchestrator's "which project?" question is only asked when nothing is set. The existing code guard stays as the backstop.

**b) Deterministic framework and script wrappers (no LLM)**

| Command | Wraps |
| --- | --- |
| `csa status [N]`, `csa next` | reads run-state, ChangesCSA status lines, Changes Reports, `assessment-state.yaml`, `evidence_matrix.py stats` |
| `csa prepare`, `csa lookup "<text>"`, `csa validate N`, `csa refresh` | `csa_docx.tools` (same functions the MCP server exposes) |
| `csa apply N [--limit] [--edit S6-E3]` | `apply_next_batch` / `cli_apply_section.py`; paths resolved from the section manifest |
| `csa approve N` | changes `**Status:** Proposed changes for approval` → approved, records who/when; refuses if the file has no edits or was never authored |
| `csa ev lookup|get|stats|verify|append` | `evidence_matrix.py` |
| `csa lint N`, `csa new`, `csa scaffold`, `csa check [--final]`, `csa table`, `csa diagram` | `prose_lint.py`, template scripts, `cli_create_table.py`, diagram model |
| `csa test`, `csa dry-run` | framework tests and `dry_run_all_sections.py` |
| `csa doctor` | Python version, vendored wheels match platform, Word lock on the DOCX, MCP registered, every skill has frontmatter, registry files exist |

All commands take `--json` so agents (including small local models) can call them as ordinary shell tools with the same safety as the MCP tools.

**c) Agent launcher**
- `csa <verb> <args>` builds the prompt from the registry (agent path, resolved project, defaults, overrides like `--limit 4` or `EDIT_MODE=editorial`) and launches the configured CLI:
  - Codex: `codex "<prompt>"` (interactive) or `codex exec "<prompt>"` (headless)
  - Claude Code: `claude "<prompt>"` or `claude -p "<prompt>"`
  - Hermes / Ollama: configurable command template in `.agents/cli.yaml`
- `--print` only prints the prompt (for pasting into any tool); `--headless` for batch runs.
- `apply` runs framework-first by default: it calls the deterministic batch and only opens an LLM session when the result is `BLOCKED` or invalid — matching the existing `EXECUTION_MODE=framework-first` rule.

### 4.3 Native integration — `csa sync`

Generated from `registry.yaml`, never hand-edited (header says so):
- **Codex:** one wrapper skill per agent in `.agents/skills/csa-<verb>/` (fills the 6 missing ones); optional user-level prompts in `~/.codex/prompts/` for `/prompts:csa-author`; prints the `[mcp_servers.csa]` block for `~/.codex/config.toml`.
- **Claude Code:** `.claude/skills` → symlink to `../.agents/skills`; `.claude/commands/csa-*.md` slash commands; `.claude/agents/*.md` subagents for the analysis agents; `.mcp.json` registering `csa-mcp` with `CSA_WORKSPACE` from the active project.
- **Root `AGENTS.md`** (with `CLAUDE.md` pointing to it): ten lines — what this folder is, run `csa status` first, never edit the DOCX outside the pipeline, the approval gate, where learnings go.

### 4.4 Guided pipeline — `csa pipeline N`

Walks one section through author → (stop for human approval) → apply batches until done or BLOCKED → review → cleanup, stopping at every gate and showing `csa status N` between steps. It never auto-approves and never runs two sections at once — both existing safety rules stay intact.

## 5. Implementation phases

| Phase | Work | Risk | Effort |
| --- | --- | --- | --- |
| 0 Hygiene | Add frontmatter to `csa-docx-create-table`; move the 4 `.bak` files to `backups/`; add `.state/` to `.gitignore`; write `registry.yaml` from the current README | Low | 1 session |
| 1 Deterministic CLI | `bin/csa` with `projects/use/status/next/prepare/lookup/apply/validate/approve/ev/lint/check/doctor`; `--json`; unit tests on a copy of IAMPS run-state | Low — wraps existing functions, no behaviour change | 1–2 sessions |
| 2 Agent launcher | Prompt builder + CLI adapters + `--print`; `cli.yaml` for Codex / Claude / Hermes / Ollama | Low | 1 session |
| 3 Native sync | `csa sync`, generated wrappers, slash commands, `.mcp.json`, `AGENTS.md`; regenerate README usage section | Medium — touches the files agents read; back up first, as for previous installs | 1 session |
| 4 Pipeline + next | `csa pipeline N`, richer `csa next` across both workflows | Medium | 1 session |

Install: `ln -s "/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/bin/csa" ~/.local/bin/csa` (or a shell alias) — one manual step, like the MCP registration.

Verification per phase: framework tests pass unchanged; `csa dry-run` output identical before and after; `csa status` for IAMPS matches what the run-state files say; one real `csa apply` on a backup copy of the IAMPS DOCX; `WORKSPACE_NOT_REGISTERED` still fires for an unregistered path.

## 6. Decisions (Wenzel, 2026-09-23)

1. **CLIs:** several. Codex, Claude Code and Hermes are all first-class adapters; `--cli` picks one per call, `cli.yaml` holds the default. `csa sync` generates native files for both Codex and Claude Code.
2. **Approval:** `csa approve N` is the approval gate. It flips the change file's status line and records who/when; it never runs automatically.
3. **Batches:** `csa apply` / `csa pipeline` may run many batches unattended for one section (`--until-done`), stopping on `BLOCKED`, `NOT_READY`, an error, or when no approved edits remain. Still one section at a time.
4. **Naming:** agent files keep their long names; short verbs live only in `registry.yaml`.

## 7. Implementation status (2026-09-23)

Phases 0–4 are built. Nothing is committed to git; review the diff and commit when happy.

| Phase | Delivered |
| --- | --- |
| 0 Hygiene | Frontmatter added to `csa-docx-create-table`; 4 stray `.bak` files moved to `backups/csa-cli-install-20260923/framework-stray-bak/`; `.state/` git-ignored; `registry.yaml` (11 verbs) and `cli.yaml` created |
| 1 Deterministic CLI | `bin/csa`: projects, use, agents, status, next, prepare, lookup, validate, refresh, approve, apply (`--until-done`, `--agent`, `--agent-on-block`), ev, graph, lint, check, new, scaffold, table, diagram, dry-run, test, mcp, doctor |
| 2 Agent launcher | `csa <verb> [arg] [KEY=VALUE] [--cli codex|claude|hermes] [--headless] [--print]`; project, context, work dir and source set injected into every prompt |
| 3 Native sync | `csa sync [--codex-prompts]`: 8 generated wrapper skills (hand-written ones kept), 13 `.claude/commands/csa-*.md`, `.claude/skills` → `.agents/skills`, root `AGENTS.md` + `CLAUDE.md`; README "start here" section |
| 4 Pipeline | `csa pipeline N`: author → approve (prompt) → apply batches → agent on BLOCKED → review → cleanup, stopping when a gate is not met |

Tested on a copy of IAMPS: `prepare`, `lookup`, `validate`, `ev stats/lookup` against the real framework; `apply 10 --until-done` ran 3 batches to SECTION_COMPLETE; approve/revoke round-trip leaves the change file byte-identical; launcher passes the prompt as one argument; unknown project and unregistered workspace are both refused.

Open items:

- `csa test` needs pytest in the framework interpreter (not verified here - no package index in the test sandbox).
- `framework/csa_docx/tools/dry_run_all_sections.py` still derives its workspace from its own location (`parents[4]`), stale since `.agents` moved to the shared folder; `csa dry-run` fails until it takes `--workspace`.
- Hermes command lines in `cli.yaml` (`hermes chat -q`) should be confirmed on your install.
- Existing IAMPS/UTC change files all still say "Proposed"; run `csa approve N` before the next apply on each.

## 8. Parallel workers — `csa fleet` (added 2026-09-23)

`csa fleet "author 6" "author 7"` (or `-f tasks.txt`) runs independent tasks side by side. One worker per slot in `cli.yaml` (`fleet_slots: local-qwen, evo-x3-qwen`, each a Codex profile). Each task starts a fresh `codex exec --profile <slot> --skip-git-repo-check --output-last-message <file> "<prompt>"`, which exits when the task is done, and the next queued task takes the slot. The manager is a plain script (no LLM).

- **Locks** (`locks:` per verb in `registry.yaml`): `docx` for apply/review/cleanup (never overlap), `section:<N>` (same-section tasks never overlap and keep list order), `state` for ask/summary (`assessment-state.yaml`), `analysis:<skill>`. Missing `locks:` defaults to `docx, section`. Evidence matrix and graph store already use `flock`, so parallel appends are safe.
- **Safety:** `apply` in a fleet is framework-first `--until-done` and still refuses unapproved files; `--agent` / `--agent-on-block` / `--allow-unapproved` are refused. A failed or timed-out task skips later tasks on the same section. DOCX tasks are skipped if Word has the file open. A worker (`CSA_FLEET_SLOT` set) cannot start another fleet. `csa approve` is never run.
- **Output:** `.agents/.state/fleet/<time>/` holds per-task log, prompt, `*.last.md` final message and `summary.json`. Options: `--dry-run`, `--print`, `--timeout MIN`, `--slots`, `--cli`, `--log-dir`.
- **Docs:** `CSA-COMMANDS.md` "Parallel work" section, README line, `AGENTS.md` rule regenerated ("DOCX steps one at a time; fleet runs other tasks under locks"). Backups in `.agents/backups/csa-fleet-install-20260923/`.
- **Tested** in the VM with a stand-in `codex`: two slots filled, DOCX reviews serialized, same-section order kept, dependent skip on failure, timeout, nested-fleet guard, input validation, task file. Not yet run against the real Codex profiles.
- **Open:** confirm `codex exec --profile` + `--output-last-message` on the installed Codex version; check the local model server accepts 2 concurrent requests if both profiles point at the same server.
