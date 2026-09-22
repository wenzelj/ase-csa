# CSA Decisions Needed

Questions only Wenzel can answer. Agents add an entry here when an issue's bucket is `needs-decision`, and link it from `issues-open.md`. Keep each question answerable in under a minute: state the options, recommend one, and say what happens if it is left unanswered.

## How this file works

1. The agent adds a `D-<nnn>` entry with options and a recommended default. It does not act on the item.
2. Wenzel writes a choice in the `Answer:` line (a letter, or free text).
3. On the next run the agent reads the answered entry, applies it only as the answer states, sets `Applied:` to the date and the evidence, and updates the linked issue to `fixed-pending-verify`.
4. An answer is authority for that item only. If it requires editing an approved change record, the answer must say so explicitly; otherwise the agent reports and waits.
5. Entries with `Applied:` filled move to the Answered section at the bottom.

## Entry format

```text
### D-<nnn> - <question>
- Issue: <I-nnn>
- Asked: YYYY-MM-DD by <agent>
- Context: <one or two sentences>
- Options:
  - A: <option> - <consequence>
  - B: <option> - <consequence>
- Recommended: <letter and why>
- If unanswered: <what the agent does or does not do>
- Answer:
- Applied:
```

## Waiting for an answer

### D-003 - How should Section 1 be protected now that it was applied without a run-state?
- Issue: I-006
- Asked: 2026-09-21 by assessment
- Context: `ChangesCSA_IAMPS_Section1.md` has a Changes Report saying SECTION_COMPLETE (applied 2026-09-21), and the working DOCX matches it (Document Map rows added, renumbered and retitled). No Section 1 run-state file exists anywhere, so the framework would treat Section 1 as pending and replay `S1-E1` to `S1-E14`, duplicating the inserted rows.
- Options:
  - A: Backfill `01 Current State AS Built/01 Final Version/run-state/current-state-assessment-document-section-1.md` as SECTION_COMPLETE (completed IDs `S1-A1`, `S1-E1` to `S1-E14`), marked "backfilled from Changes Report, DOCX spot-checked" - stops any replay; the same fix used for Sections 1-4 on 2026-09-17.
  - B: Leave it without state and rely on a written rule not to run Section 1 - nothing enforces it.
  - C: Restore the pre-apply backup and re-apply through the framework after D-004 is settled - cleanest audit trail (a comment per edit, all seven validators), but discards the current applied result.
- Recommended: A now. Revisit C only if you want per-edit comments on Section 1.
- If unanswered: agents do not start a Section 1 apply run.
- Answer:
- Applied:

### D-004 - Fix the duplicate section numbers in the Document Map?
- Issue: I-007
- Asked: 2026-09-21 by assessment
- Context: `S1-E11` and `S1-E12` renumber Backup & Recovery to 16 and Infrastructure Dependencies to 17, but `S1-E13` and `S1-E14` insert Glossary and Acronyms as 16 and Appendixes as 17. The applied Document Map now lists 16 and 17 twice. In the DOCX the Heading 1 order is Backup & Recovery, Infrastructure Dependencies, Glossary and Acronyms, Appendixes.
- Options:
  - A: Author a corrective edit that sets Glossary and Acronyms to 18 and Appendixes to 19 (or whatever the rendered Word numbering shows, which needs a quick check first), approve it, then apply it - fixes the map.
  - B: Leave the map as it is - two pairs of duplicate numbers stay in the front matter.
- Recommended: A, after confirming the numbers Word shows on the Heading 1 paragraphs.
- If unanswered: agents leave the map untouched (the approved record above the report is not edited by agents).
- Answer:
- Applied:

## Answered

### D-001 - What should happen to the stale Section 1 run-state?
- Issue: I-001
- Asked: 2026-09-21 by assessment
- Answer: A (archive it and start fresh). Wenzel, 2026-09-21.
- Applied: 2026-09-21. When the archive step ran, the workspace-root `run-state/` folder and the stale Section 1 file were already gone (removed outside this session), so there was nothing left to rename. Outcome: no stale file remains. The replay risk that follows is tracked in I-006 / D-003.

### D-002 - Where should run-state files live, and which path is canonical?
- Issue: I-002
- Asked: 2026-09-21 by assessment
- Answer: B (keep run-state close to the .docx). Wenzel, 2026-09-21.
- Applied: 2026-09-21. Canonical location is `01 Current State AS Built/01 Final Version/run-state/`. Framework: `tools.py` (`apply_next_batch`, `get_section_status`, `_id_manifest_path`), `run_state.py` (comment) and `tools/dry_run_all_sections.py` now resolve run-state and the stable-ID cache from the working DOCX's folder. Two regression tests added; 58 tests pass (56 before). Documents updated: README.md, current-state-assessment-document.md, csa-change-authoring.md, csa-change-review.md, skills/csa-document-agent/SKILL.md, framework/csa_docx/README.md. The folder was created (empty). Originals are in `backups/feedback-loop-20260921/`.
