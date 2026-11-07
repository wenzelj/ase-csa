# Reference for `csa-change-authoring.md`

Moved here from `csa-change-authoring.md` to keep the agent card short. The agent card links to each section by heading.

## Generic Scope

This agent is generic for any application or system Current State Assessment.

Do not hard-code IAMPS, Aurizon, OT 3.5, section numbers, or project-specific technical assumptions into this agent definition. The IAMPS-specific facts you'll encounter (assessed system name, programme name, document date, discovery-data layout) are read from the document and the workspace each run, not assumed.

## Section Identification

When the prompt gives `SUBSECTION=<n.m>`, the unit of work is that subsection only: follow "Subsections" in `csa-core-rules.md` for its scope, change file, edit IDs and run-state. Everything below then applies to the subsection instead of the whole section.

One top-level (H1) heading in the stable-ID manifest is one "section", matching `manifest.py`'s `Section<N>` numbering in `ChangesCSA_..._Section<N>_...md` filenames -- the same convention `csa-document-agent` and `csa-change-review-agent` already use. The requested section's ordinal position among H1 headings (1st H1 = Section 1, 2nd H1 = Section 2, ...) is `<N>`.

## Bounded Authoring Iteration Mode

Default to small, restartable authoring iterations instead of attempting to fully evidence every claim in a large section in one uninterrupted run.

Use this mode whenever:

- the section has more than roughly 10 distinct claims/rows/paragraphs worth checking against evidence;
- the evidence search is spanning many hosts or many discovery-data files;
- the current context has already compacted;
- the agent has spent material time searching evidence without writing durable run-state.

Default limits:

- `AUTHOR_ITEM_LIMIT=6` (claims evaluated against evidence per iteration; default from `.agents/registry.yaml`)
- `AUTHOR_TIME_LIMIT_MINUTES=20`
- `RUN_SCOPE=next-authoring-batch`

Only complete a whole section in one pass when it is small enough that the limits above wouldn't bind, or the user explicitly requests `RUN_SCOPE=full-section`.

### Run-State

Run-state is kept **per section**, one file per section, the same pattern the other two agents already use:

```text
01 Current State AS Built/01 Final Version/run-state/csa-change-authoring-section-<SECTION>.md
```

(generalise the path prefix per project, same as the other agents' run-state paths)

Create the `run-state` directory if it does not exist. The run-state file must contain:

- section number and heading text;
- working DOCX path;
- Discovery Data folder used;
- highest `S<N>-E<n>`/`S<N>-A<n>` identified at the start of this run (before any new IDs were assigned);
- claims/paragraphs evaluated so far and their outcome (edit drafted / left unchanged / open question);
- edits drafted so far, by ID;
- evidence matrix E-ids used, and E-ids appended this run;
- open questions recorded so far;
- next claim/paragraph to evaluate;
- latest status: `PLANNED`, `IN_PROGRESS`, `PARTIAL_DRAFT_COMPLETE`, `DRAFT_COMPLETE`, `BLOCKED`, or `NO_PROGRESS_STOP`.

### No-Progress Stop

Do not work for hours without producing durable output. Stop and report `NO_PROGRESS_STOP` when:

- one full authoring attempt produces no change file and no run-state update;
- the same evidence search repeats without turning up new material;
- the time limit is reached before any claim in the selected batch has been evaluated;
- context compaction occurs and the run-state isn't current enough to continue safely;
- the working DOCX or the Discovery Data folder cannot be identified safely.

When stopping for no progress, write the blocker, what was checked, and the next recommended command to the run-state file, and return the exact resume prompt to the user (same shape as the review agent's resume prompt).

## Output Format

Write the change file at `reviews/ChangesCSA_<AppName>_Section<N>.md` -- one file per section, no edit-ID range in the filename. Edit IDs inside the file are section-scoped: `S<N>-E<n>` for content edits, `S<N>-A<n>` for administrative edits.

```text
# Changes to <Document Title>
## Section <N> <Section Title> Change Record

**File reviewed:** <document title>
**Section:** <N> - <section title>
**Suggested change set:** S<N>-E<a> to S<N>-E<b> (and S<N>-A<n> if any)
**Status:** Proposed changes for approval. This file is an approval record only.

---

## Confirmed context used for this review

- **Assessed system:** <read from the document's control page>
- **Programme:** <read from the document's control page>
- **Authoritative document date:** <read from the document's control page>
- **Document Owner, reviewers and approvers:** leave as currently recorded in the document

---

## Section brief

- **Purpose:** <what this subsection explains, in the parent section's terms>
- **Requirements:** <requirement IDs>
- **Questions:**
  - B1 <question from the section's Must explain line>
  - C1 <question raised by a reviewer comment, with a short quote>
- **Not here:** <topics owned by other sections>

---

## Review position

<one short paragraph on what this section's purpose is>

The main issues identified were:

- <bullet per distinct issue found, or "No factual gaps were found against the available evidence." if none>

---

## Proposed changes

### S<N>-E<n> - <short title>

**Where:** `@H<path>` -- currently: "<short quote of the current text, for human legibility only>"

**Do:** Replace / Insert before / Insert after / Delete

**Facts:**
- [B1] <one fact the text must carry, in the evidence's own terms> (E-nnn) {basis: observed|documented|stated; scope: <hosts or sites>}
- Table detail: <addresses, ports, host names that belong in a table, not the paragraph> (E-nnn)
- Unknown: <the one open point, if any, and who can confirm it>

**Text:**

> <the proposed replacement/insertion text, blockquoted; multiple paragraphs each on their own `>` line -- plain document prose, exactly as it should read in the DOCX. Never include an evidence ID, `E-nnn`, or any other citation marker inside this text. The document body is not a citation trail; the reader should not see "[E-042]" sitting in a paragraph. Evidence IDs belong only in `Why` below (and from there, in the Word comment the implementation agent attaches to this edit -- see current-state-assessment-document.md's Word Comments section).>

**Why:**
<EDIT_MODE=editorial only: start with `Editorial --` and follow the Editorial Mode record format instead. Otherwise: cite the specific evidence file(s) and host(s), and what they showed, plus the matrix E-id(s). This is the audit trail for the approver and the review agent, and the one place the E-id(s) for this edit are recorded. It is not shown in the document.>

**Note:**
<the Word comment reviewers will read in the document: one or two plain sentences, 40 words at most, saying what changed and why. Written to "Comment notes" in `csa-writing-style`: no file names, host lists, stable IDs, status tags, change IDs or E-ids (the framework appends the change ID and the E-ids from `Why` in brackets itself).>

---

<repeat per content edit>

## Administrative correction for approval

<same shape as above, using S<N>-A<n> instead of S<N>-E<n>, for non-content/metadata fields such as a cover date. Omit this heading entirely if there are none.>

---

## Items intentionally left unchanged

<bullet list of things reviewed but not changed, and briefly why -- omit only if genuinely nothing was reviewed-and-left-alone, which is rare>

---

## Open questions

<bullet list of unresolved items per the Review Method rules above, or "There are no open questions for Section <N>." if none>

---

## Expected result if approved

Approving <the S<N>-E<n> / S<N>-A<n> IDs> would:

- <bullet per net effect>
```

Do not write a `## Changes Report` or `## Change Review Report` heading yourself -- those are appended later by the implementation and review agents respectively. Your file ends at `## Expected result if approved`.

## Report Persistence

Write the change file directly (this agent creates it; there is nothing to append to). If a change file for this exact section already exists (a re-run, or resuming a partial draft), read it first and continue/update it rather than starting over and losing already-drafted edits.

## Continuous Skill Improvement

After every run, capture what was learned so future authoring runs are faster and more accurate.

Use this local skill-notes path for this agent:

```text
.agents/skills/csa-change-authoring-learnings.md
```

At the end of each run:

- record any evidence-to-topic mapping discovered or refined (required -- see Evidence Mapping above);
- record any other reusable lesson: a wording/anchor pattern that commonly fails `lookupStableId` and how it was resolved, a class of claim that's routinely ambiguous across hosts, a governance-field boundary that came up, etc.;
- keep project facts and specific technical findings out of the skill notes unless needed as a worked example;
- do not copy confidential discovery evidence into the skill notes beyond what's needed to illustrate the lesson;
- if the lesson changes how this agent should behave on every future run, update this agent `.md` with a small, controlled instruction change and mention that in your report to the user;
- if there was nothing reusable to learn, say so explicitly in your report rather than skipping the step silently.

The inbox is append-only. Only Wenzel moves entries into the playbook. Prefer short, evidence-backed entries over broad rules.

## Recovery And Repair Boundary

This agent is read-only with respect to the working DOCX, always -- it never opens it for writing, and `prepareDocument()`/`lookupStableId` are read-only by design. The only files this agent writes are its own change-proposal Markdown file, its run-state file, the shared skill-notes file, and new rows appended to `csa-work/evidence-matrix.csv` through the `csa-evidence-matrix` skill (append-only; backups and an audit log are kept by the skill).

If asked to also apply the changes it just drafted, decline and hand off to the Current-State-Assessment-Document Agent instead -- authoring and implementation stay separate roles, the same way implementation and review stay separate.

## Position In The Pipeline

```
prepareDocument()  ->  YOU (draft ChangesCSA_*.md)  ->  [human approves]  ->  csa-document-agent  ->  csa-change-review-agent
     step 0              step 1 -- this agent            not automated        (apply_next_batch)      (verify)
```

You are step 1. Before you, a document exists but has no `reviews/` folder and no change file -- `prepareDocument()` is the only thing that has run against it. After you, a human reads the file you wrote and decides whether to approve it; nothing in the framework applies a change file automatically just because it exists. You create the `reviews/` folder the first time you run against a document that doesn't have one yet.

## Simple Invocation Defaults

The user should be able to start authoring with a short instruction such as:

```text
SECTION=3
Draft change proposals for the requested section using the agent defaults.
```

`EDIT_MODE` defaults to `evidence`. Add `EDIT_MODE=editorial` only for a concision pass. When `EDIT_MODE=editorial`, read `.agents/references/authoring-editorial-mode.md` in full before drafting; it holds the editorial rules, the record format and the pilot lessons.

When a `SECTION=<number>` value is supplied, treat that value as the authored section everywhere in the run: identifying the section's current text, searching evidence, drafting edits, naming the output file, writing the run-state file, reporting to the user, and stopping. Do not require the section number to be repeated elsewhere in the prompt.
