# C-S-A-Change-Review Agent Learnings

This append-only file captures reusable lessons learned while reviewing Current State Assessment DOCX changes against approved Markdown change files.

Each entry should use this format:

```text
## YYYY-MM-DD - <short lesson title>

Context:
<section/document/task context>

Issue or risk observed:
<what made the review harder, failed, or required special handling>

Evidence used:
<what evidence identified or confirmed the issue>

Improved review approach:
<what the agent should do next time>

Validation:
<how to confirm the improved approach worked>
```

## 2026-09-14 - Initial learning log

Context:
Agent instruction update.

Issue or risk observed:
Reusable review lessons can be lost between runs if they are only mentioned in chat or buried in one reviewed section file.

Evidence used:
The review agent previously had no dedicated append-only place for review-method improvements.

Improved review approach:
After each completed review, record reusable lessons in this file and mention whether a lesson was added in the `## Change Review Report`.

Validation:
Confirm this file is updated when a review produces a reusable lesson, and confirm the change review report records either the lesson update or `No new reusable skill lesson identified`.

## 2026-09-15 - Use bounded review iterations for large sections

Context:
Agent instruction improvement after CSA review runs sometimes took too long trying to verify an entire large section and all document integrity checks in one pass.

Issue or risk observed:
A review can spend hours re-reading the same DOCX, retrying render/open checks, or rebuilding global comparison evidence without writing a partial review result.

Evidence used:
The review workflow previously had one-section scope but no review batch size, time box, run-state checkpoint, or no-progress stop condition.

Improved review approach:
For sections with more than 8 approved edit IDs, default to bounded review iteration mode. Parse the full verification inventory, select the next unreviewed batch, verify that batch's edits/comments/report claims, run the necessary DOCX integrity checks, update the `## Change Review Report`, and write `.agents/run-state/csa-change-review-section-<SECTION>.md` with the next edit ID.

Validation:
Confirm every review iteration writes durable evidence: reviewed DOCX path, current review edit IDs, statuses, integrity checks run, limitations, next edit ID, and status. If no durable review evidence changes during an iteration, stop with `NO_PROGRESS_STOP` rather than continuing indefinitely.

## 2026-09-23 — IAMPS Section 1 (Document Control) — self-correcting change set
- **Context:** Section 1's change file contains a self-correcting sequence: S1-E1/S1-E2 (renumber two Document Map rows to 16/17, "17-section document") followed by S1-E3/S1-E4 (renumber them back to 15/16, "16-section document"). S1-E1/S1-E2 were applied in an earlier run; S1-E3/S1-E4 were the current iteration.
- **Lesson:** When a change file is self-correcting (a later edit reverses an earlier one), review at the **net state**, not at each intermediate step. The authoritative question is "does the live DOCX now read what the *final* edit says it should?" — here 15/16, confirmed by independent H1 enumeration of the live DOCX (16 content Heading-1 sections). The intermediate 16/17 state is a historical artifact and is not a defect.
- **Validation that worked:** (1) `prepareDocument()` → READY, manifest current. (2) Independent H1 enumeration of the live DOCX via `word/document.xml` to settle the 16-vs-17 fact the change file hinges on. (3) Read the two Document Map rows in the live DOCX (15/16 ✓). (4) Read the two Document Map rows in the immediate pre-apply backup (16/17) to confirm the S1-E3/E4 transition was exactly the two authorised rows and nothing else. (5) Comments 296/297 present, author Wenzel Joubert / WJ, anchored to the correct rows, edit ID + Why-aligned reason, range markers all present. (6) `validate_section` → all Pass. (7) No `E-nnn` marker in the applied cells (expected: document-internal consistency correction, not evidence-cited).
- **Pitfall avoided:** Comparing the live DOCX to a backup that predates *other* sections' applies (e.g. Section 17's content) produces false "unauthorised change" signals. Always use the **immediate pre-apply backup** for the section under review (the one named in that section's Changes Report / apply run-state), and treat other sections' additions as out of scope.
- **Sign-off:** Tracked changes present → cleanup sign-off applies. Reviewed S1-E3/S1-E4 only → sign-off YES for those two IDs only, not the whole document.

## 2026-09-23 — IAMPS Section 4 (Discovery activity) — Replace applied as Insert + no delete
- **Context:** S4-E1 was approved as a Replace of a trailing "No evidence was identified for:" list with a corrected single-line statement. The implementation instead INSERTED the corrected line into the Data Sources list (wrong location) and left the old list in place.
- **Lesson (FAIL pattern to check for on every Replace edit):** A "Do: Replace" must both (a) remove the old text and (b) place the new text at the authorised location. Verify **both** independently:
  1. Is the old text **gone** from where it was? (diff the pre-apply backup against the live DOCX for that specific list/paragraph region).
  2. Is the new text at the **authorised** location, not merely "present somewhere in the section"?
  A corrected statement that is present but in the wrong place, with the old contradictory text still there, is an INCORRECT application even though the package validates and the comment is well-formed.
- **Validation that caught it:** linear-scan the section in the live DOCX and in the immediate pre-apply backup; compare the Data Sources region and the trailing list region. The live had BOTH the inserted corrected line (in Data Sources) AND the unchanged old 4-item list (at the end). That is the defect.
- **Do not let a passing `validate_section` or a well-formed comment mask a content-application defect.** Those confirm the package is sound and the comment is correct; they say nothing about whether the approved Replace was actually performed.

## 2026-09-23 — IAMPS Section 5 (Architectural Review) — multi-column row: approved text landed in the wrong column
- **Context:** S5-E1 approved a Replace of a 4-column Design-vs-Observed row (Domain / Design / Observed / Assessment). The approved text carried an "Assessment: Partially Observed…" clause. The implementation updated the Observed column with the corrected text (including the "Assessment: …" clause) but left the dedicated Assessment column as the old "Not Observed (gap)".
- **Lesson (FAIL pattern for table-row edits with an Assessment/verdict column):** When the approved Replace text contains an assessment/verdict clause and the table has a dedicated Assessment (or verdict) column, verify the clause landed in the **Assessment column**, not folded into the Observed/Description column. A row where Observed says "Partially Observed" and Assessment says "Not Observed (gap)" is self-contradictory even though each column individually looks plausible.
- **How to check:** read the row's header (Domain / Design / Observed / Assessment), then read each cell of the target row in the live DOCX and in the earliest pre-apply backup. Compare the Assessment cell specifically. If the approved text's assessment clause is missing from the Assessment cell, that is an INCORRECT application.
- **Backup selection for multi-iteration sections:** a section may have been applied across multiple runs (S5-E1 in one, S5-E2 in a later one). The immediate pre-apply backup for the *current* iteration (S5-E2 here) already reflects the *prior* iteration (S5-E1). To see S5-E1's original state, use the earliest Section 5 backup (06:10:18), not the latest (06:33:37).

## 2026-09-24 — IAMPS Sections 10, 13, 6 — recurring failure patterns (consolidated)
- **Context:** Across the review queue (11 sections), two independent failure patterns recurred: (1) the apply agent placed the `Why`'s "(Evidence: E-nnn, …)" clause into the **applied body text** (S10-E4, S13-E2); (2) change reports cited comment IDs that do not exist or are wrong (S13 report claimed C233, actual comment is 292; S6 report claimed C229, actual is 122). Section 17 was the counter-example: its report's C311 was correct and the body text was clean.
- **Lesson 1 (check on every edit, not just suspected ones):** After locating the anchored text of any applied edit, grep the paragraph/cell text for `E-\d+` (and `S\d+-E\d+`). Evidence citations belong in the Word comment, never in the visible body. A passing `validate_section` and a well-formed comment give no signal on this — it is a content defect, not a package defect.
- **Lesson 2 (resolve comments by anchor, never by reported ID):** The change report's "comment ID C###" field is an apply-agent claim. To verify a comment, find the comment whose **anchor range covers the changed text** (commentRangeStart/End around it) and check that comment's content. Then cross-check the ID. Two of eleven sections had wrong reported IDs; only one had it right.
- **Validation that worked for both:** `re.search(r'<w:commentRangeStart[^>]*w:id="CID"', doc)` + matching End, then text-between = anchored text; count Start/End/Reference per ID (all must be exactly 1). For the E-nnn check: extract the paragraph via `rfind('<w:p ')` / `find('</w:p>')` around the anchor, then `re.findall(r'E-\d+', text)`.
- **Section 17 confirmation (PASS):** clean body text (no E-ids, no edit IDs), correct comment ID in report, and six post-apply layout-fix backups that were all text-identical (layout-only) — the unauthorised-change check must compare **text and table structure**, not raw XML, when post-apply formatting repairs exist.

## 2026-09-24 - IAMPS quality-review: structural issues NOTED, not fixed (per user)

- Context: user asked to "make a note of the issue. I don't want to move structure around now. I want to see how complete the document is and the quality, carry on with csa qa." So the structural items below are RECORDED only — no relocations, no heading moves, no subsection promotions in this pass.
- Sections §6–§14 (DNS, Identity, Network, Time Sync, Security, Monitoring, Patch, Backup, Infra) are all CONTENT-COMPLETE and relevant (Findings / Drawbridge Impact / Operational Behaviour / Assessment / Recommendations all populated). None are stubs. Confirmed by full read.
- DEFERRED structural items (revisit later, via csa-change-authoring change records, NOT silent edits):
  1. Container heading "Findings and Recommendations" holds DIRECT body text in §12 Patch, §13 Backup, §14 Infra (scope map: container "Accepts: Nothing directly"; verdict SPLIT). In §6–§11 it holds only a one-line intro before proper H3 children.
  2. §14 Infra: "This results in:" is promoted to an H3 (para ~2798). It is a bullet lead-in, not a subsection title (MISPLACED_HEADING / MINOR).
  3. §11 Monitoring: a bare "Recommendations" line (NOT a heading) sits directly under the container between the findings body and the Short-Term H3 — inconsistent heading level vs §6/§7 (standalone H2 Recommendations) and §8/§9/§10 (Recommendations as H3s).
  4. Heading-level inconsistency across the nine domains for where Recommendations and Assessment live: standalone H2 (§6, §7, §12, §13, §14) vs H3 under the container (§8, §9, §10, §11). NOTE: standalone H2 "Recommendations" and H2 "Assessment" are BOTH acceptable per the section-scope legacy-structure table — this is a uniformity preference, not a defect.
- EDIT MADE THIS SESSION THAT MAY WALK BACK: renamed all nine findings headings to "Findings and Recommendations". This cleared the prose_lint placeholder rule (PLACEHOLDER_HEADING_RE matches any heading starting "finding comments"). If the user prefers the prior "Finding comments, recommendations, drawbridge findings" wording (or the original per-section variants), the backups are:
  - before_findings_heading_rename_20260924.bak  (after the "etc"/variant normalization + Achieves fix, BEFORE the rename)
  - before_s11_heading_fix_20260924.bak  (original mixed headings, before any of this session's heading work)
  Both in /Users/wenzel/Work/ASE/CurrentStateAssessments/IAMPS/06 IAMPS/01 Current State AS Built/01 Final Version/
- OPEN (not yet reviewed): the earlier skeleton dump showed Glossary (771 body words) and Appendixes (438 body words) with substantial prose, even though the prior fact-review recorded Glossary as "table only" and Appendixes as "heading only, empty." Verify what prose is actually in §15 Glossary and §16 Appendixes — Appendixes should have no assessment prose per the scope map.

## IAMPS DOCX — csa-quality-review final state (2026-09-24 13:58)

- Scope: quality + completeness, section by section. Structural reorg explicitly deferred by user ("don't move structure around now").
- VERDICT: READY WITH DECLARED GAPS. All 16 sections content-complete and topically relevant; no stubs.
- Confirmed MAJOR (finding-wording in Observed subsections — content relocations, HOLD for sign-off):
  - §7 Identity @H8.3.2 "This confirms that authentication for IAMPS systems is performed via Active Directory domain services…"
  - §11 Monitoring @H12.3.3 "Observed configuration indicates that IAMPS operates under a centralised monitoring architecture…"
  - §11 Monitoring also @H12.3.1 "This confirms that IAMPS hosts: …"
- Confirmed MAJOR (mis-placed H3s under 'Design and functionality expected' in §13 Backup & Recovery):
  - 'Host-Level Observations', 'Supporting Context', 'Interpretation' sit under Expected (REQUIREMENT) rather than Observed (FACT).
- MINOR (announcing lead-ins / general-tech explanation in domain sections): §9 Time Sync "critical service that supports:" and "foundational service that supports:"; recurring "This confirms/indicates/establishes" connectors in Observed/Expected across §6–§14.
- MINOR (noted): §14 "This results in:" promoted to H3; §11 bare non-heading "Recommendations" line under container.
- NOT defects (do not re-flag): <Image place holder> (keep); 16× TBA in §1 (governance); §15/§16 table-only content; standalone H2 Recommendations/Assessment (acceptable per scope map).
- Applied earlier this session (backup .before_findings_heading_rename_20260924.bak): normalised 9 findings-heading variants + 'Benefit: Achieves:' dangling colon; then renamed headings to 'Findings and Recommendations' (may be walked back per user query).
