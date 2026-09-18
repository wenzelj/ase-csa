# CSA DOCX Framework Robustness Plan

Status: DRAFT PLAN — not yet implemented. Written 2026-09-17 at Wenzel Joubert's request, after the framework kept blocking on new sections.

## 1. Why this plan exists (the evidence)

Sections 5–9 were pushed through by hand, one blocker at a time, over many runs. That does not scale to the 11 sections still untouched (1–4, 10–16; 160 of the project's 244 approved edits).

To find out how bad the real gap is, this plan is grounded in a real measurement, not guesswork: every edit in the 11 untouched sections was replayed against the actual `DocxEngineEditor.apply_change()` code path, on a disposable scratch copy of the current working DOCX (nothing in the real document or change files was touched). Unlike a normal run, the replay did **not** stop at the first BLOCKED edit — it kept going, so every blocker in a section is visible, not just the first.

**Result: 160 edits replayed, 62 applied cleanly (39%), 98 blocked (61%).**

By section:

| Section | Edits | Applied | Blocked |
|---|---|---|---|
| 1 | 14 | 9 | 5 |
| 2 | 24 | 3 | 21 |
| 3 | 31 | 0 | 31 |
| 4 | 8 | 2 | 6 |
| 10 | 16 | 9 | 7 |
| 11 | 16 | 12 | 4 |
| 12 | 15 | 8 | 7 |
| 13 | 14 | 6 | 8 |
| 14 | 17 | 12 | 5 |
| 15 | 3 | 1 | 2 |
| 16 | 2 | 0 | 2 |

Caveat: because the replay doesn't stop at a block, a later edit in the same section can itself fail *because* an earlier edit in that same section was skipped (its target text is still the old wording the later edit's own "Where" no longer matches, or vice versa). So 61% is a ceiling, not a clean measurement of independent bugs — but it is the right ceiling to design against, and Section 3 blocking on all 31 of its edits is a real, section-wide signal on its own (see 5.3).

Blocker taxonomy across all 98 blocks:

| Count | Reason | What it means |
|---|---|---|
| 68 | `Anchor match count was N; expected 1` | The `Where` locator text doesn't find exactly one paragraph — 0 (text drifted/not found) or >1 (ambiguous) |
| 9 | `Range boundaries not unique or out of order` | A "replace X through Y" edit can't uniquely place both ends |
| 8 | `Section body anchor match count was N; expected 1` | Same as the first row, for whole-subsection replacements |
| 4 | `Table row anchor not unique or not found` | Row-label lookup inside a table failed |
| 4 | `Could not extract labelled table replacement values` | The approved `Text:` table content didn't parse into rows the framework recognises |
| 4 | `Could not extract a unique anchor from Where` | The `Where` field's own prose didn't parse into a locator at all |
| 1 | `Could not find N following bullet/content paragraph(s)` | An "anchor + N following bullets" edit couldn't find N bullets after the anchor |

**The single dominant failure (68 of 98, 69%) is exact-text anchor matching failing to find the target.** That is the core problem this plan addresses first.

## 2. Root cause, in one sentence

The only address a change record has for its target is free-text prose ("text beginning exactly: `...`") written by a human/LLM reviewer against a snapshot of the document — there is no independent, durable identifier tying an Edit ID to a location that survives wording drift, prior edits, or paraphrasing. DocxEngine's own `P{ordinal}#{hash4}` anchors are recomputed live and are internally correct, but they are **content-derived** (the hash is over the paragraph's own text) — they were never meant to be a durable cross-reference for something authored outside the document.

This matches what you asked about directly: better markers, and whether the document itself should carry an invisible ID that lines up with the `.md` files.

## 3. Direction A — Stable, invisible anchors in the document, referenced by ID in the `.md` files

**What:** Retrofit every paragraph/table that an approved edit targets with an OOXML bookmark (`w:bookmarkStart`/`w:bookmarkEnd`), named deterministically from the Edit ID (e.g. `CSA_E160`). Bookmarks are content-independent — they survive rewording, spelling fixes, and comment additions; they only "break" (legitimately) if the whole paragraph is deleted, which is exactly the case that *should* stop and ask a human, not silently misfire.

**Why bookmarks specifically, not something bespoke:** they are OOXML's own purpose-built mechanism for a named, stable location reference, Word displays/preserves them transparently and invisibly, and they sit alongside DocxEngine's paragraph model without disturbing it (a bookmark is just extra markup inside/around a `w:p`, it doesn't change the paragraph's text or its content-hash anchor). DocxEngine itself has no bookmark tool in its 24-tool surface today (confirmed by inspecting its tool specs) — this is the one piece of the plan that has to be built as a small, explicit XML-level extension in the framework, matching the same pattern already used for the legacy `DocumentEditor` (`ooxml.py`) before DocxEngine was standardised on. Framework-first still holds: DocxEngine does the edit once the bookmark resolves a location; only *locating* the bookmark is new.

**How the ID gets into the `.md` files:** add a new field to every edit record, `**Anchor ID:**`, e.g.:

```
**Where:** Section 9.1, text beginning exactly:

`future-state design intends to transition relevant time services to OT-controlled infrastructure`

**Anchor ID:** CSA_E160
```

- For the 5 already-processed sections (5–9), and for going-forward change records, the **review/authoring agent** that produces or approves a change record is also responsible for tagging the *original, pre-edit* document with the bookmark and writing the ID back into the `.md` file at approval time — never against a working copy that's already partway through edits.
- For the 11 untouched sections, a one-off **retrofit pass** runs once: open the *original* analysed document (see 3.1), resolve each edit's existing free-text `Where` locator (today's matching logic, run once, with a human/review-agent spot-check of the results before they're trusted), insert a bookmark at the resolved location, and write the `Anchor ID` back into the change file. This is the *only* place the old fuzzy/exact text-matching logic is allowed to be authoritative rather than a fallback — because it's supervised, one-time, and against a clean, unmodified copy.
- The framework's `apply_change` then looks up `Anchor ID` first. If present and resolvable, use it — deterministic, no ambiguity. Text-based `Where` matching becomes the **fallback**, used only for edits that were never retrofitted, and any text-match success is still logged so it can be retrofitted with a bookmark automatically afterward (self-healing corpus).

### 3.1 Locating "the original document"

Per your framing, item 2, the original pre-edit document that was analysed to produce every `.md` file should exist independently of the working copy that's had Sections 5–9 already applied to it. Locating and confirming that file (vs. reconstructing one from backups) is the first concrete task under this direction — the plan does not assume it's `...v1.docx`, since that file already carries Sections 5–9's edits.

## 4. Direction B — Three-phase apply / verify / cleanup, using DocxEngine's own tracked-changes as the "marked for deletion" mechanism

You asked for phase 1 to never hard-delete, instead marking things for deletion as placeholders, with phase 2 review sign-off gating a phase 3 cleanup that does the real deletion. DocxEngine already has exactly the primitive this needs, natively — no bespoke placeholder scheme required:

- Every edit tool (`docx_delete`, `docx_edit_paragraph`, `docx_insert`, …) already accepts `track_changes: bool` + `author`. With it on, a "delete" becomes a genuine `w:del` redline (visibly struck through, fully reversible, nothing physically removed) instead of a silent physical change; likewise replacements become tracked `w:ins`/`w:del` pairs.
- `docx_revision` already supports `list` / `accept` / `reject` / `accept_all` / `reject_all`, filterable by author/date.

That maps the three phases onto three agents, two of which already exist:

- **Phase 1 — Apply (existing `iamps-csa-document-agent`, one change):** run every edit — including deletes — with `track_changes=True`. Nothing is physically removed or lost; the DOCX shows every pending change as a reviewable redline, same as a human editor would see in Word's Track Changes view. This directly removes the risk you're flagging: an over-eager delete under the current framework is permanent and unrecoverable the moment it's applied; under this model it's just marked, and any mistake is a `docx_revision reject` away from being undone, even after the fact.
- **Phase 2 — Verify and sign off (existing `iamps-csa-change-review-agent`, one addition):** this agent already reviews applied edits against the approved change record and reports PASS/PASS WITH NOTES/FAIL/BLOCKED, read-only. Add an explicit **sign-off** output once a section's edits are all PASS: a small `## Cleanup Authorisation` block appended to the run-state (or a new `.agents/run-state/csa-cleanup-<SECTION>.md`), naming the section, the reviewed edit IDs, the reviewer, and a timestamp. This is the gate — nothing in Phase 3 may run without it.
- **Phase 3 — Cleanup (new, small agent):** only for a section that has Phase 2 sign-off, call `docx_revision accept_all` (scoped to that section's author/date range) to finalise the tracked changes into normal text, save, validate, and report. This agent does no interpretation of content at all — it is mechanical, which keeps it low-risk to build and easy to trust.

This is a genuine improvement independent of Direction A — it's worth doing even before the bookmark work lands, since it removes the single scariest failure mode (an incorrect delete) at essentially zero new code, just a default flag flip plus one small new agent.

## 5. Direction C — Turn today's ad-hoc firefighting into a permanent, repeatable test suite

This is what makes the other two directions safe to build incrementally rather than as one big rewrite, and it's what you specifically asked for: analyse the `.md` files and the document, build tests from real data, run them against the framework, fix, repeat.

### 5.1 A permanent dry-run harness

Promote the throwaway script used to produce the table in §1 into a real, checked-in framework asset: `.agents/framework/csa_docx/tests/dry_run_all_sections.py` (or similar). It should:

- Copy the current working DOCX to a scratch path (never touch the real one or the real `.md` files).
- For every section's change file, replay every record through `DocxEngineEditor.apply_change()` **without stopping at the first block** (unlike the real CLI's batch loop, which deliberately does stop — that's correct behaviour for a real run, wrong for measuring coverage).
- Emit the same kind of table as §1: per-section applied/blocked counts, and a normalised taxonomy of blocker messages with example edit IDs.
- Be safe to run repeatedly and to run after every framework change, as the primary regression gate — "did this fix reduce the block count, and did it avoid introducing new blocks in already-passing sections?"

This turns "the framework keeps getting blocked" from a series of one-off firefights (which is what Sections 5–9 were) into a measurable, shrinking number.

### 5.2 Unit tests for each blocker category, from real failing records

For each row in the §1 taxonomy, pull 2–3 real failing edit records (already identified — see the "e.g." examples in the taxonomy) into `tests/test_change_parser.py` as fixtures, the same way the E-150 (table) and E-149 (spelling) fixes were built and verified earlier. Concretely, in priority order (highest count first, matching §1):

1. **Anchor match count (68)** — the dominant case. Needs two sub-fixes: (a) once Direction A lands, most of these disappear because lookup goes by bookmark, not text; (b) for the fallback path and for edits not yet retrofitted, generalise the section-heading-scoping + spelling-normalisation fix already built for Section 9 (E-149) and verify it against the other sections' real 0-match and multi-match cases — several are likely the same British/American spelling class of bug, not yet confirmed for Sections 1–4/10–16.
2. **Range boundaries not unique or out of order (9)** and **Section body anchor match count (8)** — same family as #1; same fix direction, applied to the range/section-body code paths.
3. **Table extraction failures (4 + 4)** — the mistune/rapidfuzz-based table capability already exists (built for E-150) but clearly doesn't cover every table shape used in the untouched sections. Pull the actual failing `Text:` blocks from Sections 1, 3, 11, 12 and extend the parser/matcher against them specifically, the same test-first way E-150 was fixed.
4. **`Could not extract a unique anchor from Where` (4)** — a `find_anchor()` parsing gap, not an anchor-matching gap: the `Where` field's own prose isn't recognised. This is exactly the kind of thing a better `.md` schema (§6) removes at the source rather than needing ever-more regex patterns to parse free prose.
5. **Following-bullet-count edge case (1)** — low priority, single occurrence.

### 5.3 Section 3 deserves its own look before anything else

31 of 31 edits blocked is not "many independent small bugs" — it's a strong signal of one systemic issue specific to that section (a structural mismatch between how Section 3 is written in the `.md` file vs. every other section, or a document-side quirk unique to that section, e.g. numbering/heading style). Diagnosing Section 3 first, before broad rule changes, both fixes a likely single root cause and gives a second real, independent-of-Section-9 dataset to validate any general fix against.

## 6. Should the `.md` schema itself change?

Yes, in two narrow, additive ways — nothing that breaks what already works:

1. **`**Anchor ID:**`** (Direction A) — the durable cross-reference field, populated once at authoring/retrofit time.
2. **A separate `**Text:**` field, always** — several existing blockers (including E-160, fixed last session) trace back to replacement content being embedded inline inside `**Do:**` instead of its own `**Text:**` field, which the parser silently can't extract. Auditing all 244 records for this specific structural inconsistency (cheap: a script, not a rewrite) and normalising them is a small, high-value, non-controversial cleanup that removes an entire blocker class outright.

Everything else about today's schema (`Where` / `Do` / `Text` / `Why`, Markdown blockquote for multi-paragraph text, the Edit ID numbering) stays as-is — it's human-readable, it's what every existing approved change record already uses, and rewriting it wholesale would touch all 244 approved records for no gain proportional to the risk.

## 7. Sequencing

Recommended order, each step independently valuable and each verified by the Direction C harness before moving on:

1. Build the Direction C dry-run harness (§5.1) — needed as the measurement tool for everything after it, and it already exists in prototype form from this planning pass.
2. Fix the `.md` structural issue (§6.2, inline-Text-in-Do) across all 244 records — cheap, mechanical, removes a known blocker class immediately, no document changes needed.
3. Diagnose and fix Section 3 specifically (§5.3) — validates the general anchor-matching fixes against a second independent real dataset.
4. Generalise the spelling/heading-scoping fix and extend table extraction, driven by the remaining real failing records (§5.2, items 1–4) — re-run the harness after each fix to confirm the block count drops and nothing regresses.
5. Flip Phase 1 to `track_changes=True` by default and build the Phase 3 cleanup agent, gated on Phase 2 sign-off (§4) — independent of the anchor work, safe to land at any point once the review agent's sign-off addition is written.
6. Locate the true original pre-edit document (§3.1) and build the bookmark-retrofit pass; add `Anchor ID` lookup as the primary addressing path in `apply_change`, text-matching demoted to fallback (§3) — the largest single piece of work, done last because everything before it should have already driven the remaining *organic* text-matching failure rate down close to the floor, making the bookmark retrofit's own success easy to verify against the harness.

## 8. Out of scope / deliberately deferred

- Rewriting the `.md` schema beyond the two additive fields in §6 — not needed, and risks re-litigating every already-approved change record.
- Replacing DocxEngine or building a parallel editing engine — the data doesn't support that; the dominant problem is addressing/lookup, not DocxEngine's edit primitives, which already do everything Direction B needs.
- Sections 5–9: already applied and verified clean; nothing here proposes touching them again except as the harness's known-good baseline.

---

## §9. Section 3 diagnosis (Task: "implement the plan" step 3) - CORRECTED, see below

**This section's original diagnosis was wrong and has been retracted.** It
concluded Section 3 needed all 31 change records re-authored against
"independently rewritten" document text. The real cause, found immediately
after: Sections 1-4 were already fully applied and review-agent-signed-off in
earlier work sessions (real timestamped backups exist for all four, and each
change file's own "Changes Report"/"Edit verification" section records every
edit as Applied/CORRECT with full DOCX-integrity and unauthorised-change
validation) - but `.agents/run-state/` had no run-state file for any of
Sections 1-4 (only Sections 5 onward were ever tracked there). The dry-run
harness's "is this section already complete" check
(`_section_is_complete()`) therefore treated all four sections as pending and
replayed their change records against the *already-edited* document, which
correctly can't find the old (now-superseded) anchor text - hence 31/31
"blocked" for Section 3, and confusingly-partial results for Sections 1, 2
and 4 (an INSERT-type edit's anchor is often stable text that wasn't itself
replaced, so those falsely came back APPLIED - which would have silently
duplicated content if this had been a real, non-dry-run apply rather than a
harness replay).

**Fix applied:** backfilled `.agents/run-state/current-state-assessment-document-section-{1,2,3,4}.md`
from each change file's own completion evidence, marking all four
`SECTION_COMPLETE`. No change-file re-authoring was needed or performed -
the user's initial approval ("Re-author the 31 records") was given before
this correction was found and does not apply; Wenzel was notified of the
retraction directly. This is now also flagged as a real framework gap worth
carrying into Direction B (§4): completion tracking should not depend solely
on a side-channel run-state file that can silently go missing - the change
file's own embedded Changes Report should be treated as an authoritative
alternate source of truth for "is this section already done", and the
harness/CLI should check both before ever treating a section as pending.

<details>
<summary>Original (incorrect) diagnosis, kept for the record</summary>



**Finding: Section 3's 31/31 block rate is a document-content mismatch, not a framework bug.**

Every one of Section 3's 31 change records quotes a "Where" anchor sentence that
is claimed to exist verbatim in the reviewed document (e.g. *"The IAMPS platform
is assessed as an OT-hosted operational integration and processing system"*,
*"Running RabbitMQ / Erlang services, with ports:"*, *"Supporting multi-protocol
communication, including:"*). None of these strings - or anything close to them
- exist anywhere in the current working DOCX's "System Assessment Overview"
section (verified by direct substring search across all 1,731 paragraphs, not
just the section-scoped range).

The section-heading scope itself resolves correctly (`System Assessment
Overview` appears exactly once, at paragraph 144, so `_section_scope` is not
picking the wrong occurrence). The actual paragraphs inside that scope cover
the same *topics* the change records discuss (RabbitMQ/Erlang messaging,
multi-protocol integration interfaces, AMP servers, enterprise dependencies)
but in **entirely different, much terser wording** - short bullet fragments
("Messaging services (RabbitMQ / Erlang)", "Provides asynchronous
communication between systems") rather than the fuller narrative sentences the
change records quote. A near-miss of one anchor phrase ("RabbitMQ / Erlang
services active:") does exist in the document, but sits in Section 2's
inventory content (paragraph 103), outside Section 3 entirely - i.e. even the
closest match is in the wrong place, not just reworded.

**Conclusion:** the live working DOCX's Section 3 body was substantively
rewritten/condensed at some point after these 31 change records were drafted
against an earlier draft of that section. Improving anchor-matching
(fuzzy/partial matching, scope fallback, etc. - Task #22) will not safely fix
this: the target sentences don't exist in any recognisable form, so a fuzzy
matcher would either find nothing (safe, same as today) or risk matching the
wrong bullet fragment to the wrong instruction (unsafe - silently misapplying
an approved edit's comment/rationale to unrelated text).

**This is a document-quirk, not a framework-gap**, and needs a human decision
before any further automated work on Section 3:
1. Re-author the 31 Section 3 change records against the *current* wording of
   "System Assessment Overview" in the working DOCX (the review intent -
   "don't mix evidence levels, don't over-interpret ports, don't state
   untested failure behaviour as fact, don't drift into migration planning" -
   likely still applies to the new wording, but the specific sentence-level
   instructions need to be re-targeted), or
2. Locate whichever intermediate draft of the CSA document these 31 records
   were actually written against, confirm what changed between that draft and
   the current working DOCX's Section 3, and reconcile from there.

No framework code change is proposed for this specific finding. Section 3 is
left untouched (still 31/31 blocked) pending that decision - forcing a
"fix" here would mean guessing which document content each instruction should
land on, which is exactly the failure mode the review/sign-off phases (§4,
Direction B) exist to prevent.


</details>

---

## §10. Step 4 progress: anchor-matching generalisation (Sections 10-16)

A second instance of the same "false block from an already-completed edit"
bug was found, this time at the *individual edit* level rather than whole
sections: Section 10 is genuinely in progress (run-state `Status: BLOCKED`)
but its run-state correctly lists E-161 through E-165 as already `APPLIED`.
The dry-run harness didn't check per-edit completion for a non-`SECTION_COMPLETE`
section, so it replayed all 16 of Section 10's records from scratch and
reported five already-done edits as newly blocked. Fixed: `replay_section()`
now consults `run_state.read_completed_ids()` for every section (not only as
a whole-section skip gate) and skips already-completed edit IDs individually.

Also closed three `find_anchor()` pattern gaps (`immediately before/after
[...]:` with optional filler words before the colon, and `standalone text
exactly:`), which fixed E-190 and E-196 outright and moved E-177 from a
mis-extraction failure to a distinct, real DocxEngine stale-anchor-hash
error worth its own investigation.

Corrected baseline for the only sections with real remaining work (10-16):
**78 edits exercised, 60 applied (77%), 18 genuinely blocked (23%)**. The
remaining blockers split into distinct categories - not a single root cause -
logged in `.agents/skills/current-state-assessment-document-learnings.md`
under "2026-09-17 - Harness fix (partial-completion skip) and find_anchor
pattern generalisation". Most notable: a whole new problem class -
**sequential/dependent edits** whose Where clause refers to another edit's
own output ("after the revised Section 10.2.2", "after the revised Findings
text from E-189") rather than to literal document text. No current anchor
pattern can resolve this safely, and it should not be pattern-matched (doing
so risks anchoring to the wrong, unrelated text) - it needs the editor to
track and expose each edit's resulting paragraph anchor within a single
batch run, which is a real design addition, not a regex fix.

### §10.1 Additional fixes this pass

- **Real bug fixed:** `_result_anchor()` didn't recognise `docx_insert`'s actual
  result shape (`{"new_anchors": [...]}`, plural/list) and always fell back to
  a now-stale pre-insert anchor for the immediately-following comment-attach
  call. Fixed to also read `new_anchors`/`anchors`. This affects every
  insert-before/insert-after edit in the framework, not just the one that
  surfaced it (E-177) - see learnings file for the full diagnosis trail.
- **New recognised pattern (not a bug):** a fine-grained edit blocks because
  an *earlier* edit in the same file already replaced the whole subsection
  containing its target ("supersession"). Confirmed for E-170/E-176 (Section
  10) and E-199 (Section 12). Deliberately not auto-detected/auto-skipped -
  each needs a one-line human check that the broader edit's approved text
  really does cover the finer edit's intent before marking it skipped.
- **Remaining open, genuinely ambiguous:** E-213 (Section 13), E-224/226/230
  (Section 14) - a short generic anchor phrase repeats 2-3 times within
  section scope with no current tie-breaker, in both isolated and sequential
  replay. Not attempted - a wrong automatic guess here is worse than the
  current clear block.
- E-241 (Section 15): table-cell extraction gap, not yet investigated this
  pass.

**Final baseline for this step:** Sections 10-16, 78 edits exercised, 61
applied (78%), 17 genuinely blocked (22%) - up from 59/71% before this pass.

---

## §11. Step 5 complete: Phase 1 tracked changes, review sign-off, Phase 3 cleanup agent

`DocxEngineEditor` now defaults to `track_changes=True` (constructor param,
threaded through every mutation call site: `doc.insert`, `doc.delete`,
`doc.edit_paragraph`). `cli_apply_section.py` exposes `--track-changes`
(default) / `--no-track-changes` on the same switch. Verified end-to-end on a
real section: applying with tracked changes on produces real `w:ins`/`w:del`
markup (75 insertions / 79 deletions on Section 11's batch), the file stays a
valid DOCX zip throughout, and `docx_revision accept_all` cleanly finalises
all of it (154 revisions accepted, zero `w:ins`/`w:del` remaining
afterwards, zip still valid). Confirmed via the regression harness that
flipping the default doesn't change which edits apply or block (same 78
replayed / 61 applied / 17 blocked as before the flip) - tracked-changes mode
only changes *how* an already-successful edit is written into the XML, not
whether it succeeds.

`csa-change-review.md` (Phase 2) gained a `## Sign-Off For Cleanup` section
and a `Sign-off for cleanup: YES/NO/NOT APPLICABLE` + `Edit IDs covered by
this sign-off:` line in its report format. `PASS`/`PASS WITH NOTES` sign off;
`FAIL`/`BLOCKED` do not; an ambiguous "can't tell if tracked changes are even
on" case signs off `NOT APPLICABLE` rather than guessing.

New file `.agents/csa-change-cleanup.md` - the Phase 3 cleanup agent.
Deliberately small and mechanical: it does not decide anything is correct
(that's Phase 2's job, expressed only through the sign-off line), it only
finalises what's already been signed off, via `docx_revision accept_all`
(whole-section sign-off) or a scoped `docx_revision accept` per revision
(batch sign-off). Six explicit Hard Stop Conditions cover every way a sign-off
could be missing, negative, ambiguous, or scoped narrower than what's being
asked of it - the agent stops and reports rather than guessing in every one
of those cases. Full text delivered to Wenzel and saved to
`.agents/csa-change-cleanup.md`.

This completes plan step 5 of §7's sequencing.

---

## §12. Step 6 in progress: Direction A (bookmark-based Anchor ID retrofit)

DocxEngine has no bookmark tool, so this is a small raw-XML extension:
`csa_docx/bookmarks.py`. It splices real OOXML `w:bookmarkStart`/`w:bookmarkEnd`
tags directly into `word/document.xml` bytes, using
`docxengine._anchors.build_anchor_index()` to locate a paragraph's byte span.
Two functions: `add_bookmark_at_anchor(editor, anchor, edit_id)` (writes a
bookmark named `CSA_<sanitised edit id>` around the paragraph at `anchor`) and
`find_bookmark(editor, edit_id)` (looks up that bookmark's current anchor, or
`None` if it was never tagged).

**Why this matters:** DocxEngine's own anchors (`P{ordinal}#{hash4}`) are
deliberately ephemeral - ordinal shifts the moment any earlier paragraph is
inserted or deleted, and the docstring for `Paragraph` says so explicitly.
Every blocker this project has hit so far where an edit's `**Where:**` text
still matches but the anchor doesn't is exactly this problem one level removed
- literal text matching is more durable than the anchor, but still breaks
when a supersedeing edit changes the wording nearby. A bookmark tied to the
edit ID itself is immune to both: it moves with its paragraph regardless of
ordinal or nearby text changes, and is looked up by the edit ID, not by
matching text at all.

**Wired into the framework** (`docxengine_adapter.py`):
- `_apply_simple_paragraph_change()` now checks `find_bookmark(self,
  record.edit_id)` *first*. If a bookmark exists, it resolves the target
  paragraph directly from the bookmark's current anchor, skipping
  `find_anchor()`/`_matching_paragraphs()` (and every text-matching failure
  mode) entirely. Only when no bookmark exists yet does it fall back to the
  original text-matching path.
- After every successful insert-before / insert-after / replace in that
  method, a new best-effort helper `_tag_bookmark(edit_id, anchor)` writes a
  bookmark for that edit ID, so the *next* touch of the same edit (a re-run,
  a repair, a review-driven correction) goes through the bookmark path
  instead of text-matching again. Swallows exceptions deliberately - this is
  a durability improvement, not a requirement, and must never turn a
  successful edit into a failure.
- **Scope, honestly stated:** only `_apply_simple_paragraph_change` has this
  integration so far. The other six dispatch methods (table-row, full
  section-body replacement, explicit range replacement, anchor+bullets
  replacement, delete-until-heading, full-table replacement,
  subsection-end-insert) do not yet look up or write bookmarks. Confirmed
  directly in a live test on Section 11: simple insert/replace edits
  (E-177, E-179, E-180) got bookmarks; paragraph-*range* replacements
  (E-178, E-181, which dispatch elsewhere) did not. This is a real gap, not
  an oversight to paper over - extending bookmark integration to the other
  six dispatch methods is the natural next unit of work, each one small but
  needing its own verification the way this one got.

**Verified, not just written:**
1. *Round-trip durability*: a bookmark written for a paragraph, after the
   document is saved and reopened, still resolves to the same paragraph.
2. *Survives upstream shifts*: bookmarked E-177 resolved to anchor
   `P1166#4751` right after being tagged; after two more edits were applied
   earlier in the document (shifting every later paragraph's ordinal),
   `find_bookmark` correctly resolved it to the new anchor `P1172#4751` -
   proving the bookmark, not the stale ordinal-based anchor, is what's doing
   the work.
3. *Re-apply through the bookmark path*: re-invoking `apply_change()` for
   the same edit ID after that shift succeeded by resolving through
   `find_bookmark` rather than re-matching text.
4. *No regression*: full regression harness re-run across Sections 10-16
   after wiring this in - **78 edits replayed, 61 applied (78%), 17 blocked
   (22%)**, identical counts and identical blocker set to the pre-bookmark
   baseline in §10.1. The bookmark-first path changes *how* an edit is
   re-resolved, not whether today's first-time applies succeed.

**Not yet done, left for the next pass:**
- Extend bookmark-first lookup + auto-tagging to the other six dispatch
  methods listed above.
- Decide whether a human-authored "Anchor ID" field is still needed in the
  `.md` change-file schema (plan §6's original idea) now that auto-tagging
  exists - auto-tagging means the *first successful apply* self-assigns the
  durable anchor without needing a human to pre-author one, which may
  substantially reduce or eliminate the need for that schema field. Worth
  revisiting once bookmark coverage is complete across all dispatch paths,
  not before.

**Coverage extended (same session, second pass):** wired bookmark-first
lookup + auto-tagging into four more dispatch methods, and auto-tagging-only
into a fifth:

- `_apply_anchor_plus_bullets_replacement`, `_apply_section_body_replacement`,
  `_apply_anchor_plus_following_content` - all three resolve a single anchor
  paragraph via `_matching_paragraphs()`, so they now share a new
  `_resolve_paragraph_index()` helper that checks `find_bookmark()` first,
  exactly like `_apply_simple_paragraph_change`.
- `_replace_range_by_index()` - the shared range-replacement helper used by
  all four of the methods above plus `_apply_explicit_range_replacement` -
  now auto-tags a bookmark on the replacement's resulting anchor after every
  successful replace. This gives all four callers auto-tagging in one place;
  `_apply_explicit_range_replacement` gets auto-tagging but not
  bookmark-first lookup on entry, since it resolves a *range* (start anchor
  and end anchor via `_scoped_unique_index`) rather than a single anchor, and
  extending the helper to a two-boundary case wasn't judged worth the added
  risk this pass.
- `_apply_subsection_end_insert` - bookmark-first lookup added directly (own
  shape: resolves a numbered-subsection heading, not free text), with a
  fix alongside it: the method's success message referenced
  `paragraphs[heading_index]`, which would have raised `TypeError` when the
  bookmark path resolved without ever computing `heading_index`. Caught before
  it could ship, via a guarded `heading_label` computed once up front.

**Still untouched, with reasons:**
- `_apply_delete_until_heading` - deletes the range; there is no paragraph
  left afterwards to bookmark for a future re-lookup.
- `_apply_table_row_change` / `_apply_full_table_replacement` - table cells
  are addressed by `(table_anchor, row_index, cell_index)`, not by paragraph
  anchor; the current `bookmarks.py` only bookmarks paragraphs. Extending
  Direction A to tables is a distinct, not-yet-designed piece of work.

**Verified again after this extension:** live test on Section 11 confirmed
the two previously-untagged edits in that batch (E-178, E-181 - both dispatch
through `_apply_explicit_range_replacement`) now get bookmarks too, alongside
the three simple-paragraph edits already covered. Full regression harness
re-run across Sections 10-16: **78 replayed, 61 applied (78%), 17 blocked
(22%)** - identical to both the pre-bookmark baseline and the first-pass
bookmark baseline above. No behavioural change to first-time applies; only
re-resolution durability changed, now across six of the eight dispatch
methods.

**Genuinely not yet done, left for the next pass:**
- Table-cell bookmarking (`_apply_table_row_change`,
  `_apply_full_table_replacement`) and delete-range handling
  (`_apply_delete_until_heading`, which has no post-edit paragraph to tag) -
  two different problems, neither trivially an extension of the paragraph
  bookmark mechanism.
- Decide whether a human-authored "Anchor ID" field is still needed in the
  `.md` change-file schema (plan §6's original idea) now that auto-tagging
  covers six of eight dispatch paths - likely much less necessary now, but
  worth a deliberate revisit rather than a default keep/drop.

**Decided:** no human-authored Anchor ID field. Auto-tagging and a
human-authored field would have solved the same problem twice - a bookmark
for an edit ID, present before the edit is first resolved. The distinction
that actually matters is *when* the anchor needs to exist:

- For an edit that has *already* applied successfully once, auto-tagging
  writes the bookmark itself, at zero authoring cost. A human field here
  would be redundant - the system now assigns it, correctly, every time.
- For an edit that has *never* applied - the 17 current blockers - there is
  no bookmark yet, because none was ever written, and a human-authored field
  would only exist if a person manually resolved that edit's location and
  typed the ID in. That is not a schema improvement; it is doing the
  resolution work by hand and recording the answer. The `.md` schema was
  never actually the bottleneck for these - the resolution judgment is
  (disambiguating a repeated phrase, fixing a drifted `Where` clause,
  confirming a supersession). A field would not have saved that judgment,
  only given it somewhere to be written down after the fact.

So this closes plan §6's original idea cleanly: dropped, superseded by
auto-tagging for the case it actually covers, with no replacement needed for
the case it doesn't (that case is human judgment, tracked per-edit in the
blockers list below, not a schema gap).

