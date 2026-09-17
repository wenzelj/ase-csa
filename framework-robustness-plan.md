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
