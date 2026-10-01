# Plan: move old-format CSA content into the CSA template (`csa move`)

Status: agreed 1 Oct 2026. Replaces the requirement-led conversion (S203–S215, `docs/convert-old-template-plan.md`) as the way to **populate** a new document. That work is kept for the rework phase (see section 7).

## 1. Principle

Moving is copy-and-reshape. It is not a change process. For each subsection: take the old content the map assigns to it, fit it to the template tables and wording, write it into the document as normal text. Evidence checking, ratings, review and cleanup all happen later, in the rework of the populated document, using the existing build and revise lane.

## 2. Decisions (Wenzel, 1 Oct 2026)

1. **Plain text, not tracked changes.** The document is reworked afterwards.
2. **Ratings are left blank** on every moved requirement row. The old readiness scores are not carried.
3. **Section 8 (Discovery Required) is built automatically** from the writer's open questions.

## 3. What one subsection run does

`csa move 3.5`:

1. **Gather (framework, no agent).** Block-mode brief: the old blocks the map assigns to the subsection, the requirement list from the scope map, the host register. One file, `csa-work/move/3.5/brief.md`.
2. **Write (one agent).** The writer, in `MODE=move`, writes the section file from the brief. Requirement rows, Discovery Information rows, one Drawbridge Impact paragraph. Where the old content says nothing: `Not stated in previous assessment`. Open questions are listed in an `open_items` block at the end of the file.
3. **Insert (framework).** Structure check only (the tables must load); content findings are warnings. The section goes into the document as plain text.
4. **Record (framework, no agent).** `csa-work/move/moved.csv` (old block ID, subsection), `csa-work/convert/parked.md` (recommendations, scores), `csa-work/move/open-items.csv`.

`csa move --all` runs every mapped subsection in order: 3.1 to 3.17, 5.2 to 5.6, Section 8 (from open items), 2.1 last. Glossary (7) and Discovery Coverage (5.1) stay agent-free as today.

## 4. What is not part of the move

Fact extraction, requirement assignment and clustering; the requirement audit; the evidence pre-pass and matrix rows; the evidence investigator; the answer plan and plan-check; the ledger and `outcomes.csv`; tracked changes; per-section review and cleanup.

## 5. Writer rules in move mode

- Facts, not narrative; each fact once; full sentences.
- No recommendations (they go to `parked.md`).
- Keep qualifiers: "not tested", "not observed", "not confirmed".
- Never mention the previous assessment, its headings or version.
- Do not carry old readiness scores. Leave Rating empty.
- Every requirement row of the subsection is present, even when its Current State is `Not stated in previous assessment`.
- Content belonging to another subsection is left out (it stays in `moved.csv` under its mapped target).
- No IP addresses in prose; host detail goes in the table.

## 6. Check relaxations (`mode: move` in the section-file front matter)

`csa check-section` keeps every structural ERROR (headings, tables, columns, requirement IDs). In move mode: an empty Rating cell is allowed; the Evidence table may be absent or empty; E-ids are not required; prose-lint and style findings are warnings.

## 7. After the move: the rework

The populated document is reworked with the full lane: evidence investigator, evidence matrix, tracked changes, review, cleanup. Use the requirement-led tools there: `csa convert --prepare` facts and `requirement-audit.md` show which requirements the old content cannot answer; the 3.5 answer plan stays the worked example. Section 3.5 is already placed through the earlier process and is left as is.

## 8. Stories

| Story | Content |
| --- | --- |
| S216 | `csa_docx/move.py`: `move_prepare` (extract + map only), `move(section)` stages brief, write, insert, record |
| S217 | Plain placement: `csa place --plain` (no tracked changes, no evidence comments, no approval record) |
| S218 | Writer `MODE=move` instructions; `mode: move` check-section relaxations; `open_items` block |
| S219 | Recording: `moved.csv`, `open-items.csv`, parked list, Section 8 from open items |
| S220 | CLI: `csa move N`, `--all`, `--status`, `--print`, `--prepare`; fleet task `move N` |
| S221 | Docs and prompt: one-page move prompt, README, CSA-COMMANDS, banner on the convert plan |

Expected effort per subsection: one agent session, against seven steps before.
