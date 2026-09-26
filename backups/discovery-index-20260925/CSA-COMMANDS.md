# CSA commands — quick reference

`csa` is the one command for the CSA agents, skills and framework. It lives in `.agents/bin/csa`.
Agents and their defaults are defined in `.agents/registry.yaml`; settings in `.agents/cli.yaml`.

## One-time setup (Mac)

```bash
mkdir -p ~/.local/bin
ln -s "/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/bin/csa" ~/.local/bin/csa
# make sure ~/.local/bin is on PATH (add to ~/.zshrc):  export PATH="$HOME/.local/bin:$PATH"

csa doctor                  # checks Python, framework, registry, skills, Word locks, CLIs
csa use iamps               # set the active project (iamps | utcdtc)
csa mcp                     # prints the csa-mcp block for ~/.codex/config.toml and the `claude mcp add` line
csa sync --codex-prompts    # wrapper skills, /csa-* slash commands, AGENTS.md, ~/.codex/prompts/csa-*.md
```

Re-run `csa sync` whenever you edit `.agents/registry.yaml`.

## Project

| Command | What it does |
| --- | --- |
| `csa projects` | List registered projects (`*` = active) |
| `csa use <key>` | Set the active project |
| `csa -p utcdtc <command>` | Run one command against another project |
| `csa agents` | List agent verbs, their files and inputs |
| `csa doctor` | Health check |

## Where am I?

| Command | What it does |
| --- | --- |
| `csa status` | Every section: edits, stage, next command |
| `csa status 6` | One section in detail |
| `csa next` | The single next action (blocked first, then applying, approvals, reviews, cleanups) |
| add `--json` | Machine-readable output |

## DOCX change pipeline (one section at a time)

```text
csa author 6                      1. draft ChangesCSA_*.md (agent)
csa author 6 EDIT_MODE=editorial     concision pass instead of evidence pass
   ...read the change file...
csa approve 6                     human gate: marks the change file approved (who/when)
csa approve 6 --revoke               undo the approval
csa apply 6 --until-done          2. apply batch after batch (framework, no LLM); stops on BLOCKED
csa apply 6 --limit 3             2. one batch of 3
csa apply 6 --edit S6-E3             only this edit
csa apply 6 --agent               2. hand the section to the document agent (use for BLOCKED edits)
csa apply 6 --until-done --agent-on-block   batches, then the agent if one blocks
csa review 6                      3. review agent (writes the Change Review Report + cleanup sign-off)
csa cleanup 6                     4. accept the signed-off tracked changes (agent)

csa pipeline 6                    walks all of the above, stopping at every gate
```

`csa apply` refuses a change file that is not approved. Existing change files still say "Proposed" — run `csa approve N` first (or `--allow-unapproved`).

## Analysis workflow (evidence -> analysis -> drafting -> review)

```text
csa ask "Network"                                     orchestrator picks the right agent/skill
csa evidence "Network"                                evidence investigator
csa gaps "Network"                                    gap register and questions
csa analyse network-connectivity-analysis SECTION=Network
csa write "Network"                                   draft from approved evidence
csa qa "Network"                                      quality review, READY / NOT READY
csa summary                                           executive summary (only after READY)
```

Analysis skills for `csa analyse`: application-discovery, infrastructure-analysis, ot-architecture-analysis,
dependency-analysis, network-connectivity-analysis, identity-access-analysis, resilience-analysis,
operations-support-analysis, security-posture-analysis.

## Parallel work — `csa fleet`

Runs independent tasks side by side. Each slot in `cli.yaml` (`fleet_slots: local-qwen, evo-x3-qwen`) is one
worker; a task starts a fresh `codex exec --profile <slot>` in a free slot, and the process exits when the task
is done. The next queued task then takes that slot.

```text
csa fleet "author 6" "author 7"                       two sections authored at the same time
csa fleet "evidence Network" "analyse infrastructure-analysis SECTION=Hosting" "qa 4"
csa fleet -f tasks.txt                                one task per line, # comments allowed
csa fleet ... --dry-run                               show tasks and locks, start nothing
csa fleet ... --print                                 also print every prompt
csa fleet ... --timeout 45                            stop a task after 45 minutes
csa fleet ... --slots local-qwen                     one worker only (e.g. while the other box is busy)
```

Rules it enforces (from `locks:` in `registry.yaml`):

- `apply`, `review`, `cleanup` hold the working DOCX, so they never overlap. `apply` runs framework-first
  (`--until-done`, no LLM) and still refuses an unapproved change file. `--agent` is not allowed in a fleet.
- Two tasks on the same section never overlap, and they run in the order you listed them.
- `ask` and `summary` hold `assessment-state.yaml`, so only one runs at a time.
- If a task fails or times out, later tasks on the same section are skipped.
- DOCX tasks are skipped if the working DOCX is open in Word.
- `csa approve` is never run by the fleet, and a fleet worker cannot start another fleet.

Logs, prompts, each task's final message (`*.last.md`) and `summary.json` go to `.agents/.state/fleet/<time>/`.
Your local model server must accept two requests at once, or the workers take turns
(Ollama `OLLAMA_NUM_PARALLEL`, llama.cpp `--parallel`); with one server per profile this does not apply.

## Agent options (any agent verb)

| Option | Effect |
| --- | --- |
| `--cli codex` / `claude` / `hermes` | Which CLI to launch (default in `.agents/cli.yaml`, or `CSA_CLI`) |
| `--headless` | Run to completion and exit (`codex exec`, `claude -p`, `hermes chat -q`) |
| `--print` | Only print the prompt, to paste anywhere |
| `KEY=VALUE` | Override an input, e.g. `ITERATION_EDIT_LIMIT=4`, `SOURCE_SET=...` |

## Framework and script helpers (no LLM)

```text
csa prepare [--force]                 readiness check + stable-ID manifest (prepareDocument)
csa lookup "text to change"           stable @H... ID for a Where: anchor  [--kind paragraph|table_row|heading]
csa validate 6                        DOCX integrity checks
csa refresh                           rebuild the section manifest
csa ev lookup "SQL Server version"    evidence matrix first  (also: get E-010 | stats | verify | append ...)
csa graph stats                       graph store (nodes/edges)
csa lint 6                            prose check on section 6 of the working DOCX  [--path draft.md] [--heading "DNS"]
csa check [--final]                   template compliance of the working DOCX
csa new --system-name X --out "..."   new CSA from the Word template
csa scaffold rows --docx ... --heading ... --set-count N
csa table ...                         new table matching document styling
csa diagram ...                       diagram model from the graph store
csa test                              framework tests (needs pytest)
```

Arguments after `ev`, `graph`, `new`, `scaffold`, `table`, `diagram`, `dry-run`, `test` pass straight to the script.
Put `-p <key>` before the command for these: `csa -p utcdtc ev stats`.

## Inside a CLI session

- Claude Code (started in this folder): `/csa-status`, `/csa-author 6`, `/csa-review 6`, `/csa-ask Network`, ... one per verb.
- Codex: `$csa-writer-agent`, `$csa-orchestrator-agent`, ... (wrapper skills), or `/prompts:csa-author 6` after `csa sync --codex-prompts`.

## Environment variables

`CSA_PROJECT` (override active project) · `CSA_CLI` (default CLI) · `CSA_PYTHON` (framework interpreter) · `CSA_FLEET_SLOTS` / `CSA_FLEET_CLI` (fleet overrides) · `NO_COLOR`
