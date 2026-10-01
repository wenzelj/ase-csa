# CSA Agents (shared framework)

Shared rules for every agent: [csa-core-rules.md](csa-core-rules.md). Improvement plan and progress: ../improvements/REGISTER.md.

This folder contains the agent definitions, skills, and helper code for the Current State Assessment (CSA) workflow, shared across every CSA project under `/Users/wenzel/Work/ASE/CurrentStateAssessments/`. It moved here from inside the IAMPS project folder specifically so IAMPS and UTC DTC (and any future CSA project placed alongside them) use the exact same agents, skills, and framework code instead of drifting copies.

Project-specific facts live in each project's own file under `csa-context/` (`IAMPS_PROJECT_CONTEXT.yaml`, `UTC_DTC_PROJECT_CONTEXT.yaml`) -- always pass the right one via `PROJECT_CONTEXT` (see the orchestrator section below). Per-run working state (`csa-work/`, run-state, reviews, backups of the working DOCX) stays inside each project's own folder, not here, so runs for different projects never collide.

Current CSA projects:

- IAMPS: `/Users/wenzel/Work/ASE/CurrentStateAssessments/IAMPS/06 IAMPS`
- UTC DTC with KVM: `/Users/wenzel/Work/ASE/CurrentStateAssessments/UTC DTC/07 UTC DTC with KVM` (working document stays on its own pre-existing template -- see `known_constraints` in its project context file; do not run it through `csa-document-template` / `new_csa.py`)

## The `csa` command (start here)

`bin/csa` is one entry point for everything below. It keeps the long prompt blocks, paths and project selection out of your hands; the manual prompts further down still work. Plan and design: `csa-cli-plan.md`.

One-time setup on the Mac:

```bash
ln -s "/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/bin/csa" ~/.local/bin/csa   # or any folder on PATH
csa doctor              # checks Python, framework, registry, skills, Word locks, CLIs
csa use iamps           # active project (stored in .agents/.state/, git-ignored)
csa mcp                 # prints the csa-mcp config for Codex and the `claude mcp add` line
csa sync --codex-prompts  # wrapper skills, /csa-* slash commands, AGENTS.md (re-run after editing registry.yaml)
```

Daily use:

```text
csa status [N] | csa next                    where each section is, and what to do next
csa author 6 [EDIT_MODE=editorial]           step 1 (agent)
csa approve 6 --reject S6-E3                optional: keep an edit out before it is applied
csa apply 6 --until-done                     step 2, framework-first, batch after batch; stops on BLOCKED
csa apply 6 --agent                          step 2 through the document agent (for BLOCKED edits)
csa review 6 | csa cleanup 6                 steps 3 and 4 (agents)
csa pipeline 6                               walks one section through all steps, stopping at every gate
csa fleet "author 6" "author 7"              independent tasks in parallel, one worker per Codex profile
csa ask Network | evidence | gaps | analyse <skill> | write | summary | qa      analysis workflow
csa lookup "<text>" | csa ev lookup "<q>" | csa lint 6 | csa check --final      no-LLM helpers
```

Agent options: `--cli codex|claude|hermes` (default in `cli.yaml`), `--headless`, `--print` (show the prompt only), `-p <project>`, and `KEY=VALUE` overrides. Agents, their verbs, inputs and defaults are defined once in `registry.yaml`; edit that, then `csa sync`. There is no approval step between authoring and apply: `csa author N` applies its change file when the agent finishes, and `csa write` places its section file in the working DOCX (`csa place`). `csa apply` runs `csa check-change` and records what it applies; `--allow-unapproved` skips the check. Your approval is accepting or rejecting the tracked changes in Word, then `csa review N` and `csa cleanup N`. `--no-apply` on author/write stops after the agent.

## Agent Definitions

Four agents form the pipeline, run in this order (the fourth, cleanup, accepts the reviewed tracked changes after you have read them in Word):

```text
prepareDocument()  ->  csa-change-authoring.md  ->  current-state-assessment-document.md (csa apply, automatic)  ->  csa-change-review.md  ->  [human accepts/rejects in Word]  ->  cleanup
     step 0              step 1: draft                                     step 2: apply                            step 3: verify
```

- `csa-change-authoring.md`: **step 1**, authoring agent. Drafts the first proposed `ChangesCSA_*.md` for a section by comparing its current text against Discovery Data evidence. Creates the `reviews/` folder the first time it runs against a document that doesn't have one. Never touches the DOCX.
- `current-state-assessment-document.md`: **step 2**, implementation agent for applying approved Markdown change records to the working DOCX.
- `csa-change-review.md`: **step 3**, review agent for checking that the implementation agent applied approved changes correctly.

Before step 1, call `prepareDocument()` (the `csa-mcp` MCP tool -- see `framework/csa_docx/README.md`) with no arguments; it works even when nothing but the raw DOCX exists yet, and builds the stable-ID manifest (`@H...` anchors) both the authoring and review agents resolve edits against via `lookupStableId`.

Start an authoring run with:

```text
Load this agent definition:
.agents/csa-change-authoring.md

Act as the C-S-A-Change-Authoring Agent.

SECTION=<section-number>
AUTHOR_ITEM_LIMIT=6
RUN_SCOPE=next-authoring-batch

Draft change proposals for the requested section using the agent defaults.
```

To condense a section whose facts are already settled (after its evidence edits are applied and reviewed), run the same agent with `EDIT_MODE=editorial` added. It proposes concision edits only (no fact added, changed or dropped), each with a `Why` starting `Editorial --` that says where every removed fact is still stated. See `csa-change-authoring.md`, Editorial Mode, and the "Say it once, say it first" rules in `skills/csa-writing-style/SKILL.md`. To measure a section first: `python3 skills/csa-writing-style/scripts/prose_lint.py "<working DOCX>" --section <N>`.

`csa author` then applies the drafted `ChangesCSA_*.md` straight away as tracked changes (after `csa check-change`); the human decision is made in Word, change by change.

Start an implementation run with:

```text
Load this agent definition:
.agents/current-state-assessment-document.md

Act as the Current-State-Assessment-Document Agent.

SECTION=<section-number>
ITERATION_EDIT_LIMIT=2
RUN_SCOPE=next-batch

Apply the requested section using the agent defaults.
```

Start a review run with:

```text
Load this agent definition:
.agents/csa-change-review.md

Act as the C-S-A-Change-Review Agent.

SECTION=<section-number>
ITERATION_REVIEW_LIMIT=2
RUN_SCOPE=next-batch

Review the requested section using the agent defaults.
```

## CSA Analysis Agents And Skill Routing

Separate from the three-step DOCX change pipeline above, five agents run the evidence-led content workflow (evidence -> analysis -> drafting -> quality review). They use the generic Current State Assessment (CSA) Operational Technology (OT) skill pack installed under `.agents/skills/`. They never edit the working DOCX; any DOCX change still goes through `csa-change-authoring.md` -> human approval -> `current-state-assessment-document.md` -> `csa-change-review.md`. These two pipelines are not silos: `csa-change-authoring.md` checks `WORK_DIR/analysis/*.md` and `WORK_DIR/drafts/*.md` (this workflow's output) for its section's topic before searching Discovery Data from scratch, treating a match as a synthesized pointer into the evidence matrix rather than evidence in itself -- see its Evidence Mapping section. If this workflow hasn't been run for a given topic, that's a normal no-op, not a gap.

Entry point: `csa-orchestrator-agent.md` (native skill `$csa-orchestrator`). It selects the smallest relevant agent and skill for the active section; it does not load specialist skills itself.

| Agent definition | Skills it may load | Loaded when |
| --- | --- | --- |
| `csa-orchestrator-agent.md` | `csa-orchestrator` | always (this is the coordinator) |
| `csa-evidence-investigator-agent.md` | `evidence-investigator`; `csa-gap-analysis` | evidence work; gap mode only |
| `csa-technical-analyst-agent.md` | `application-discovery`; `infrastructure-analysis`; `ot-architecture-analysis` + `dependency-analysis`; `dependency-analysis`; `network-connectivity-analysis`; `identity-access-analysis`; `resilience-analysis`; `operations-support-analysis`; `security-posture-analysis` | one task at a time, as named by the orchestrator (`ANALYSIS_SKILL`) |
| `csa-writer-agent.md` | `csa-writing-style`; `csa-section-writer`; `technical-explainer`; `executive-summary` | section drafting; explanation on request; executive summary only after the detailed assessment is stable and reviewed |
| `csa-quality-reviewer-agent.md` | `csa-quality-review`; `technical-explainer` | content review; explanation on request |

Routing rules:

- No agent loads all skills. Specialist skills are loaded one task at a time.
- `csa-section-writer` writes from approved evidence and does not search sources independently.
- `csa-writing-style` is the single style guide for any prose landing in a CSA document (human-sounding, not AI-sounding). The CSA Writer Agent owns it. The C-S-A-Change-Authoring Agent (the separate change-file pipeline, see below) also loads and follows it when drafting an edit's replacement/insertion text -- it borrows the Writer Agent's voice rather than defining its own, so document prose reads consistently regardless of which pipeline produced a given sentence.
- `australian-it-ot-terminology` is a foundational skill: every agent that analyses, writes, edits or reviews CSA text loads it (evidence investigator, technical analyst, writer, change authoring, quality reviewer). It sets the technical term for each thing, IT/OT classification, heading choice, evidence phrasing and Australian English; `references/terminology.md` is the controlled terminology table and `scripts/term_lint.py` flags wording for review without changing it.
- `csa-quality-review` reports findings and does not silently rewrite approved content for style. Its check 12 (Section fit) tests whether each paragraph sits in the right section and subsection, against `skills/csa-quality-review/references/section-scope.md`; `csa-section-writer` and `csa-change-authoring` read the same map so new text lands in the right place. Deterministic starting point: `skills/csa-quality-review/scripts/section_fit_scan.py <docx> --heading "<title>"`.
- `technical-explainer` output is a labelled `Technical explanation`, kept separate from project evidence. General technical knowledge is never presented as verified project evidence.
- `executive-summary` is used only after the detailed assessment is stable and the reviewer verdict is `READY` or `READY WITH DECLARED GAPS`.
- Skills and agent definitions stay generic. Project facts live in each project's own `csa-context/<PROJECT>_PROJECT_CONTEXT.yaml` and in that project's assessment evidence -- never in the shared agent/skill files.

Working files: `csa-context/` holds every project's context file (one YAML per project, named `<PROJECT>_PROJECT_CONTEXT.yaml`); `csa-templates/` holds blank templates (project context, assessment state, evidence matrix, section coverage guide) copied from the skill pack. Per-run working files (`assessment-state.yaml`, `evidence-matrix.csv`, `analysis/`, `drafts/`, `reviews/`) go in `WORK_DIR`, which must be set to that project's own `csa-work/` folder (created from the templates on first use) -- since `.agents` is shared, there is no single "project root" to default to, so always pass `WORK_DIR` as an absolute path inside the right project.

Start a CSA analysis run with:

```text
Load this agent definition:
.agents/csa-orchestrator-agent.md

Act as the CSA Orchestrator Agent.

SECTION=<section-name>

Progress the requested section using the routing table in the agent definition.
```

Since `PROJECT_CONTEXT` and `SOURCE_SET` are not given, the orchestrator's Project Selection step reads `csa-context/PROJECTS.yaml`, lists the available projects (currently IAMPS and UTC DTC with KVM), and asks which one this run is for before doing anything else -- reply with the project name or key. To skip the question, supply `PROJECT_CONTEXT`/`WORK_DIR` directly instead, exactly as before:

```text
PROJECT_CONTEXT=.agents/csa-context/IAMPS_PROJECT_CONTEXT.yaml
WORK_DIR=/Users/wenzel/Work/ASE/CurrentStateAssessments/IAMPS/06 IAMPS/csa-work
SOURCE_SET=<documents or folders that count as evidence>
```

Or, with native skills: `Use $csa-orchestrator.` followed by the same inputs (or nothing, to be asked). To run one specialist directly for a narrow task, load its agent definition (for example `csa-evidence-investigator-agent.md`) or invoke the skill by name (for example `$evidence-investigator`) -- these agents assume the orchestrator (or the caller) already resolved `PROJECT_CONTEXT`/`WORK_DIR`, so pass them through explicitly when invoking a specialist directly rather than via the orchestrator.

Adding a new CSA project later: create its project root under `/Users/wenzel/Work/ASE/CurrentStateAssessments/`, add its `<PROJECT>_PROJECT_CONTEXT.yaml` to `csa-context/` (copy `csa-templates/PROJECT_CONTEXT_TEMPLATE.yaml`), and add one block for it to `csa-context/PROJECTS.yaml` -- nothing else in this shared framework needs to change.

## Folder Roles

- `skills/`: native skill directories (`<name>/SKILL.md`) plus append-only project learning notes used by the agents after each task.
- `csa-templates/`: blank CSA working templates copied from the skill pack. Not skills; do not treat them as evidence.
- `csa-context/`: working project context for the CSA analysis agents.
- `backups/`: timestamped backups taken before files are replaced or edited by installs.
- `01 Current State AS Built/01 Final Version/run-state/`: resumable checkpoints for section authoring, implementation, and review runs (moved out of .agents so it lives next to the document being changed); the shared stable-ID manifest `prepareDocument()` builds also lives here (`stable-ids-<docx-filename>.json`).
- `framework/`: reusable deterministic helper code for repeated DOCX and Markdown mechanics.

## Native Codex Skills

The `.agents` files are project-local prompts. They are not native Codex skills by themselves.

This workspace also contains repo-scoped native Codex skill wrappers:

```text
.agents/skills/csa-change-authoring-agent/SKILL.md
.agents/skills/csa-document-agent/SKILL.md
.agents/skills/csa-change-review-agent/SKILL.md
.agents/skills/it-ot-current-state-assessment/SKILL.md
.agents/skills/docxengine/SKILL.md
.agents/skills/csa-evidence-matrix/SKILL.md
.agents/skills/csa-document-template/SKILL.md
```

The CSA OT skill pack (16 skills: `csa-orchestrator`, `evidence-investigator`, `application-discovery`, `infrastructure-analysis`, `ot-architecture-analysis`, `network-connectivity-analysis`, `identity-access-analysis`, `dependency-analysis`, `resilience-analysis`, `operations-support-analysis`, `security-posture-analysis`, `csa-gap-analysis`, `csa-section-writer`, `csa-quality-review`, `technical-explainer`, `executive-summary`) is also installed under `.agents/skills/`; see `CSA Analysis Agents And Skill Routing` above for which agent loads which.

`csa-evidence-matrix` is a shared read + write skill used by the authoring, document and review agents. It makes `csa-work/evidence-matrix.csv` the first place every agent looks for a technical fact (`lookup`), sends them to Discovery Data only for what the matrix does not answer, and has them write new findings back (`append`, append-only, validated, backed up to `csa-work/backups/`, audited in `csa-work/evidence-matrix-audit.jsonl`). Helper: `.agents/skills/csa-evidence-matrix/scripts/evidence_matrix.py` (`lookup`, `get`, `stats`, `verify`, `append`).

`csa-document-template` is the skill for the CSA Word template (`CSA Template/CSA_Template_v*.dotx`, highest version wins). It gives agents three scripts under `.agents/skills/csa-document-template/scripts/` (run with Python 3.10+, Word closed): `new_csa.py` creates a new CSA `.docx` from the template and fills the cover and Document Control properties; `scaffold_csa.py` adds table rows or bullets to a domain section before `prepareDocument()` and the change records fill them (the framework cannot add bullets or rows cleanly through change records); `check_csa.py` verifies a CSA still matches the template's structure and styles (use `--final` before release). `references/template-structure.md` lists the section skeleton, the 17 domain blocks, styles and framework limits. Use it before step 1 of the pipeline when starting a new CSA, and after step 3 to check the result. Prompt: `Use $csa-document-template.` followed by the system name and output path.

`it-ot-current-state-assessment` and `docxengine` are different from the other three: they are general reference skills, not wrappers around a project-local execution agent definition.

- `it-ot-current-state-assessment` covers scoping, discovery, Purdue/IEC 62443/NIST CSF/TOGAF/TIME framework mapping, gap analysis, and deliverable structure for IT and OT current state assessments. Use it for framing scope or checking coverage alongside the authoring, document, and review agents.
- `docxengine` documents the vendored DocxEngine library itself (`framework/vendor/docxengine/`) that `csa_docx/engines/docxengine_adapter.py` wraps: its hash-anchored paragraph/table addressing, the 24-tool contract, tracked-changes/comment model, the Python `Document` API, and the validation/repair/save gate. Read it before touching `docxengine_adapter.py` or debugging a DocxEngine `BLOCKED`/error result.

They allow shorter prompts such as:

```text
Use $csa-change-authoring-agent.

SECTION=6
AUTHOR_ITEM_LIMIT=6
RUN_SCOPE=next-authoring-batch
Draft change proposals for the requested section using the agent defaults.
```

then (`csa author` does this for you straight after drafting; run it by hand only after `--no-apply`):

```text
Use $csa-document-agent.

SECTION=6
ITERATION_EDIT_LIMIT=2
RUN_SCOPE=next-batch
Apply the requested section using the agent defaults.
```

and:

```text
Use $csa-change-review-agent.

SECTION=6
ITERATION_REVIEW_LIMIT=2
RUN_SCOPE=next-batch
Review the requested section using the agent defaults.
```

User-level native Codex skills can also live under:

```text
/Users/wenzel/.codex/skills/<skill-name>/SKILL.md
```

The native skill wrappers for this workspace should load these project-local agent definitions instead of duplicating their full contents.

## Cross-Project Safety Guard

This `.agents` framework is shared by every CSA project. Two independent layers stop one project's agent run from reading or writing another project's evidence, DOCX, or run-state:

1. **Human-facing:** the orchestrator's Project Selection step (see `csa-orchestrator-agent.md`) asks which project a run is for whenever it isn't supplied explicitly, and every agent definition resolves `PROJECT_CONTEXT`/`WORK_DIR`/`workspace` from that answer rather than guessing.
2. **Code-enforced, independent of what any agent or instruction says:** every `csa_docx` framework function that takes a `workspace` argument (`prepareDocument`, `lookupStableId`, `apply_next_batch`, `get_section_status`, `list_sections`, `validate_section`, `refresh_manifest` -- so every `csa-mcp` tool call and every `cli_apply_section.py` run) and `evidence_matrix.py` (`lookup`, `get`, `stats`, `verify`, `append`) validate the resolved workspace against `csa-context/PROJECTS.yaml` before touching any file. If the workspace is not a registered project's `project_root` (or a path under it), the call refuses with `"status": "ERROR"` and a `WORKSPACE_NOT_REGISTERED` message -- it does not fall back to a guessed path, an empty default, or whatever the cwd happens to be. `evidence_matrix.py`'s old fallback (a hardcoded relative path from its own script location, stale since the framework was consolidated into one shared folder) has been replaced by this same check.

`prepareDocument()`'s successful response additionally carries `"project": {"key": ..., "label": ...}` -- the agent definitions require checking this against the project the run was confirmed for before trusting anything else in the response, so a wrong-but-technically-registered workspace (e.g. the other project, passed by mistake) is still caught even though it wouldn't trigger `WORKSPACE_NOT_REGISTERED`.

Layer 2 is the one that actually prevents contamination if layer 1 is ever bypassed, skipped, or gets a wrong answer -- it does not depend on any agent correctly following its instructions. Adding a new project only requires registering it in `PROJECTS.yaml`; no code change is needed for either layer.

## Safety Rules

- A drafted `ChangesCSA_*.md` is applied as soon as it is authored (tracked changes, each with its evidence comment). It is not accepted until Wenzel accepts it in Word; rejected changes simply do not survive `csa cleanup`.
- The Markdown change file is the source of truth for implementation and review; its Status line and `.approval.json` record what was applied.
- The active working DOCX must be backed up before every mutation.
- Process one section at a time.
- For CLI, EVO, or Ollama runs, use small bounded batches and stop immediately after updating the DOCX, report, and run-state.
- Do not create duplicate comments when resuming.
- Do not create another DOCX copy when a valid working DOCX already exists.

## Converting an old-format CSA

`csa convert` moves a pre-template CSA into the CSA template one subsection at a time, only the parts that map. Set `legacy_docx:` for the project in `csa-context/PROJECTS.yaml`, then run `csa convert --prepare` and read `csa-work/legacy/map-report.md`. Correct the map in `csa-work/legacy/legacy-map.csv` (it overrides `skills/csa-document-template/references/legacy-map-default.csv`). Then `csa convert 3.4` (or `csa fleet "convert 3.4" "convert 3.5"`): brief, evidence pre-pass, evidence agent, writer, placement as tracked changes, ledger. Recommendations and scores go to `csa-work/convert/parked.md`, figures to `csa-work/convert/figures.md`. Design: `docs/convert-old-template-plan.md`.

The conversion is requirement-led. `csa convert --prepare` also splits the old document into facts, gives each a requirement ID (`skills/csa-document-template/references/requirement-map.csv`) and writes `csa-work/convert/requirement-audit.md`: can each requirement be answered, and from what? Per subsection the evidence agent writes `csa-work/convert/<N>/answer-plan.csv` (legacy ID → requirement ID → fact → evidence scope → destination field → confidence → transformation → gap), checked by `python3 -m csa_docx.answer_plan`; the writer writes from it; gaps become Appendix E rows. Facts move, narratives do not; qualifiers stay; recommendations go to the roadmap list.

## Moving an old-format CSA into the template

`csa move` populates the new document quickly from the old one, one subsection at a time, as plain text. It is not a change process: no tracked changes, no evidence matrix, no review. Set `legacy_docx:` for the project, then:

- `csa move --prepare` extracts and maps the old document (no facts, no audit).
- `csa move N` writes the brief, runs one writer agent (`MODE=move`), inserts the section as plain text and records what moved.
- `csa move --all` does every mapped subsection in order, then Section 8, then 2.1.

Ratings are left blank; where the old content says nothing the cell reads `Not stated in previous assessment`. The writer's open questions become Section 8 (Discovery Required). Rework the populated document afterwards with the build and revise lane (evidence investigator, tracked changes, review, cleanup). The one-page prompt for a manual run is `references/move-subsection-prompt.md`. Plan: `docs/move-old-template-plan.md`.
