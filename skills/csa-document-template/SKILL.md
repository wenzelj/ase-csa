---
name: csa-document-template
description: Use when creating a new Current State Assessment (CSA) DOCX from the CSA Word template, preparing or filling a template-based CSA through the csa_docx framework, or checking that a CSA still matches the template's look, layout and section structure. Covers new_csa.py, scaffold_csa.py and check_csa.py.
---

# CSA Document Template

Every Current State Assessment must look and be laid out the same: cover, header, styles, table designs and section skeleton come from one Word template, and each CSA supplies only its own content. This skill is how agents create, fill and check a CSA from that template. It works with the existing pipeline (`prepareDocument` -> `csa-change-authoring` -> human approval -> `csa-document-agent` -> `csa-change-review`); it does not replace it.

## Where things are

Shared across every project (fixed paths):

```text
Scripts (Python 3.8+, stdlib):     /Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-document-template/scripts/
Structure and framework notes:     /Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-document-template/references/template-structure.md  (read it before drafting)
```

Per-project (resolve `<project_root>` from the active project's entry in `csa-context/PROJECTS.yaml`, or from a `WORK_DIR`/workspace path supplied directly -- never assume IAMPS):

```text
Template (read-only, never edit):  <project_root>/CSA Template/CSA_Template_v<highest>.dotx
Template guide + preview:          <project_root>/CSA Template/README.md, CSA_Template_v<highest>_preview.pdf
```

For IAMPS example: `/Users/wenzel/Work/ASE/CurrentStateAssessments/IAMPS/06 IAMPS/CSA Template/CSA_Template_v<highest>.dotx`. Before using this skill on any project, confirm that project actually wants a template-based build -- e.g. UTC DTC's project context records that its existing working document keeps its own pre-existing template and must not be run through this skill; check `known_constraints` in the active project's context file first.

The scripts pick the highest `CSA_Template_v*.dotx` in `CSA Template/` unless `--template` is given. Run them from that project's workspace root (its `project_root`, e.g. `/Users/wenzel/Work/ASE/CurrentStateAssessments/IAMPS/06 IAMPS` for IAMPS) or pass `--workspace`. Relative `--out` paths are resolved under `--workspace`: check the path before running.

## Rules

- Never edit the `.dotx`, and never start a CSA by copying another CSA. Use `new_csa.py`.
- One working DOCX per folder: the framework refuses to guess between two. `new_csa.py` refuses to write next to another `.docx`.
- The look comes from styles only. Do not apply direct formatting, type heading numbers (numbering is automatic), add blank paragraphs for spacing, or insert manual page breaks (every Heading 1 already starts a new page).
- Keep every template heading and every domain block. A domain that does not apply keeps its heading and records `Not Applicable` with justification.
- Req ID and Requirement text are the OT35 checklist text: do not edit them. Rating is exactly one of `Met`, `Partially Met`, `Not Met`, `Not Applicable`.
- Cover, page header and Section 1.1 come from document properties. Never change them with change records; set them in `new_csa.py` or, later, in Word (File > Info > Properties > Advanced > Custom) followed by Ctrl+A, F9.
- Never record passwords or where credentials are stored (accounts table: name, type, purpose only).
- The content itself follows the existing evidence workflow: evidence first (`csa-evidence-matrix`), drafting from approved evidence, human approval of every change file. This skill covers form, not facts.

## 1. Create a new CSA

```bash
python3 /Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-document-template/scripts/new_csa.py \
  --system-name "<System>" \
  --out "<folder>/Current State Assessment - <System>.docx" \
  [--date dd/mm/yyyy] [--doc-version 0.1] [--status "..."] [--prepared-by "..."] [--author "Wenzel Joubert"]
```

Take the system name and any program values from the user or the active project's context file in `csa-context/` (e.g. `IAMPS_PROJECT_CONTEXT.yaml` for IAMPS, `UTC_DTC_PROJECT_CONTEXT.yaml` for UTC DTC -- resolve via `PROJECTS.yaml`, never assume IAMPS); do not invent them. Prepared For, Prepared By, Project and Reference Standard default to the template's program values. The script sets the `CSA_*` properties, rewrites the cached text of every field, removes the template guidance comments, asks Word to refresh fields on first open, and refuses to overwrite (`--force` only if the user asked). It prints JSON; require `"status": "CREATED"` and an empty `properties_without_fields`.

Then run `check_csa.py` (section 3) once: on a fresh file it must report 0 errors and only the placeholder and rating warnings.

## 2. Prepare and fill

1. `prepareDocument()` (no `section`). Stop on `NOT_READY`.
2. Read `references/template-structure.md`. Sections for change files are the Heading 1 ordinals: 1 Document Control, 2 Executive Overview, 3 Requirement Domain Assessments, 4 Migration Discovery, 5 Appendix A, 6 Appendix B. Filenames `ChangesCSA_<System>_Section<N>.md`, header `**Section:** 3 - Requirement Domain Assessments`.
3. **Scaffold before drafting.** Change records fill only what exists. Decide from the evidence how many hosts, accounts, glossary terms, coverage rows or bullets a block needs, then set the count. It is idempotent, backs up first, and only removes placeholder-only rows or bullets:

   ```bash
   python3 /Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-document-template/scripts/scaffold_csa.py rows    --docx "<docx>" --heading "Workstation and Server Discovery Coverage" --set-count 26
   python3 /Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-document-template/scripts/scaffold_csa.py bullets --docx "<docx>" --heading "Discovery Information" --heading-occurrence 5 --set-count 4
   ```

   `--heading` is the exact heading text without its number; `--heading-occurrence N` picks the Nth heading with that text (Discovery Information repeats once per domain: 3.1 is occurrence 1, 3.2 is 2, and so on). `rows` also takes `--table N`. Afterwards call `prepareDocument(force_regenerate=True)`: the manifest only rebuilds by itself when headings change, and IDs have moved.
4. Draft change records as usual, with `lookupStableId` for every `Where` (never derive an ID from a heading number: the framework's IDs are ordinal with a +1 offset). Shapes that are tested and keep the template's formatting:

   | To fill | Where | Do / Text |
   | --- | --- | --- |
   | Requirement Current State and Rating | the row, `@H..-T1-R<n>` | `Replace`; Text: `> Observed: <current state>` and `> Assessment: Met` (Observed = column 3, Assessment = column 4) |
   | A supporting-table row | the row | `Replace`; Text: one pipe row with every cell, `> \| host \| environment \| role \|` |
   | A bullet (Discovery Information, Migration Discovery) | the placeholder bullet paragraph | `Replace`; Text: the bullet sentence, no leading `- `, one bullet per edit |
   | Any other paragraph (summary, Drawbridge Impact, caption, source) | the placeholder paragraph | `Replace`; Text: plain sentences |

   Do not use `Insert after` for bullets, multi-bullet Text blocks, or `Replace the table content` on template tables: they either lose the bullet formatting or cannot find the table (details in the reference). One edit per placeholder.
5. Approval, apply (`csa-document-agent`) and review (`csa-change-review-agent`) run unchanged. Use interpreter `/opt/homebrew/bin/python3.14` for the framework and comment author `Wenzel Joubert` / `WJ`.
6. Append new bullets or leftover unfilled placeholders to the change record's open questions rather than leaving them silently.

Things a change record cannot do (report them, do not work around them): add or delete headings, sections or whole tables, delete a domain, change table columns, place a figure. A figure is inserted by a human in Word into the Figure placeholder, with the caption and source line filled.

## 3. Check

```bash
python3 /Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-document-template/scripts/check_csa.py "<docx>" [--final]
```

Read-only, JSON output, exit 1 on errors. Run it after `new_csa.py`, after every applied batch, and with `--final` as the pre-issue gate. Errors: unknown styles, typed heading numbers, missing template headings or requirements, default or missing properties, stale field text, non-CSA tables, invalid Rating. Warnings: unfilled placeholders (by section), guidance comments, direct formatting, empty paragraphs, manual page breaks, missing header-row repeat. Info: extra headings you added, other comments, pending tracked changes. With `--final`, placeholders, unset ratings, guidance comments and pending tracked changes become errors.

Report the `status` and `counts` in the completion report, and list every ERROR. Do not "fix" an error by editing around the check.

## Known limits

- Tested with the framework on 21 Sep 2026 (Python 3.10 on Linux; `datetime.UTC` needs 3.11+, so use the Mac's 3.14). Not yet opened in desktop Word: the first time a human opens a generated CSA, Word asks to update fields (say yes), which also corrects the contents list's page numbers.
- The contents list and its page numbers are cached from the template until Word refreshes them.
- Filling the Rating through the framework replaces the dropdown with plain text (Table Rating style). That is expected and passes the check.
- Word must be closed while a script or the framework runs (`locked_by_word`).

## Learnings

Append short, reusable lessons (a pattern that failed, a check that misfired, a template change needed) to `/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/current-state-assessment-document-learnings.md`. Template layout changes are made in the template and versioned, never in a single CSA.
