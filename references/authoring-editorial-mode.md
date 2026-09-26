# Reference for `csa-change-authoring.md`

Moved here from `csa-change-authoring.md` to keep the agent card short. The agent card links to each section by heading.

## Editorial Mode (`EDIT_MODE=editorial`)

Evidence mode deliberately never touches wording that is factually correct, so a section drafted in a fragmented, repetitive style stays that way through any number of evidence passes. Editorial mode is the fix: a concision pass over a section whose facts are settled, bringing the existing text into line with the "Say it once, say it first" rules in `csa-writing-style`. It runs only when the user asks for it.

**When:** after the section's evidence edits have been approved, applied and reviewed. If `reviews/` holds unapplied evidence edits for the section, stop and report that; do not condense text that is about to be corrected. If no evidence pass has ever been run on the section, proceed only when the user asked for the editorial pass explicitly, and say in `## Review position` that the facts have not yet been checked against evidence.

**Baseline:** before drafting, run the prose lint on the working DOCX for this section and record the result in the change file's `## Review position`:

```text
python3 .agents/skills/csa-writing-style/scripts/prose_lint.py "<working DOCX>" --section <N>
```

**Editorial edits may:**

- replace a lead-in line and its bullet fragments with one or two sentences (a range Replace from the lead-in through the last bullet);
- delete a paragraph or bullet whose facts are all stated elsewhere in the section;
- replace a paragraph that announces a conclusion ("This confirms...", "As a result...") with the conclusion itself;
- delete general technology explanation that says nothing specific about the assessed system;
- remove evidence file names, capture dates and per-host lists from prose, but only where the same detail is already in a table or the evidence appendix;
- move text to the subsection that owns its job, or delete text that belongs to another section once that section states it (see Out-Of-Place Content).

**Editorial edits must not:**

- add, change, strengthen or soften any fact, rating, risk, limitation or uncertainty label;
- remove the only statement of a fact;
- touch headings, table structure, controlled fields, or the Word comments of earlier edits;
- carry an evidence correction. A factual error found during the pass becomes a separate evidence edit with its own evidence `Why`, or an open question.

**Record format:** normal `S<N>-E<n>` numbering and the normal record layout (the framework parser only accepts E and A records). The `Why` starts with `Editorial --`, names the rule applied, lists every fact the removed text carried, and gives the stable ID (resolved with `lookupStableId`) where each fact is still stated after the change. For example:

```markdown
**Why:**
Editorial -- each fact once; sentences not fragments. The removed bullets restated the two enterprise time sources and the absence of a local fallback. Both remain stated in @H10-P4 (Findings paragraph). No fact is removed.
```

Editorial edits need no E-id unless the replacement text states a fact in new words; then cite the E-id that already supports it. Their `Note` says what was tightened and that no facts changed, for example "Wording tightened: five bullets joined into one sentence. No facts changed." Keep each edit small enough for a human to accept or reject on its own.

**Lessons from the first pilot (UTC DTC Security Services, 23 Sep 2026):**

- **Number edits bottom-up.** Stable IDs are positional within a heading, and a range Replace collapses several paragraphs into one. The apply agent works in ID order, so give the edit lowest in the section `S<N>-E1` and work upwards. Every later anchor then still points at unchanged text when its turn comes. Say so in one line above the first edit.
- **Range Replace format that parses:** `**Where:** \`@H<start-id>\`` and `**Do:** Replace this paragraph and all paragraphs through \`@H<end-id>\``. Check every record with `csa_docx.change_parser.parse_change_records` plus `ooxml._extract_range_spec` before finishing.
- **Replace keeps the first paragraph's style.** A run of List Paragraph bullets collapses to one bullet, not a body paragraph, so the bullet share cannot fall through change records. Make each bullet a complete statement, and raise restyling prose as body paragraphs as a `Structural suggestion`.
- **Raw log or command-output lines are evidence, not findings.** Replace them with the statement they support plus a short source reference (file name and date). List what was dropped (timestamps, process IDs, paths) in the `Why` with an "Approver check" line, so the human can reject the edit if they want the raw lines kept.
- **Interpretation needs an approver check.** When joining fragments means deciding what an ambiguous sentence refers to ("This is explicitly denied by design"), state the reading in the `Why` and ask the approver to reject the edit if it is wrong. When the meaning cannot be recovered at all (for example a host list with no lead-in), leave it and raise an open question.
- **Do not remove file-name lists that the appendix lacks.** Check the Evidence Appendix first. Missing entries become an open question, not a deletion.
- **Section numbers:** the framework's `Section<N>` counts every Heading 1, including empty or hidden ones, so it can differ from Word's visible numbering. Resolve the section from the manifest (`@H<N+1>` is Section N) and state both numbers in the change file header. Run the lint with `--heading "<title>"` rather than `--section`.
- **Expected-after metrics:** simulate the edits on the section text (apply each record's Text over its ID range) and lint the result, rather than estimating.

Put what change records cannot do (merging subsections, removing duplicate headings, consolidating summary sections, fixing heading numbering) under `## Open questions`, each labelled `Structural suggestion`.

In `## Expected result if approved`, give the section's prose word count and lint warnings before, and the expected values after, all editorial edits are applied.

## Example

For IAMPS, an example evidence folder is:

```text
/Users/wenzel/Work/ASE/CurrentStateAssessments/IAMPS/06 IAMPS/01 Current State AS Built/IAMPS Discovery Data/
```

containing `PROD/`, `UAT/`, and standalone `tg_discovery_*` runs, each with numbered per-host evidence files. Use this layout when it is the supplied workspace, but keep this agent generic for any other application's Current State Assessment and evidence layout.
