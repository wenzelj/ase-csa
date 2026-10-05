# Rules digest: writer pass (MODE=records)

The author has written the change file; you rewrite only the `**Text:**` of prose records from their `**Facts:**`. Then run `csa check-change <N>` and fix every ERROR.

## What to write

- Read `WORK_DIR/author/<N>/search-notes.md` if it exists: do not repeat a search it records as done; keep each `Not found:` line as an `Unknown:`, never a definite absence.
- Read the change file's `## Section brief`: the Purpose is the story, the questions are its order. Open with the Purpose in the parent section's terms, answer the questions in brief order, end with the consequence for the section's requirements and the one unknown (said once).
- Use every fact in the list except `Table detail:` lines, which stay out of prose. Add no fact that is not in the list. A true fact that answers no brief question stays out.
- Rewrite only `**Text:**`. Do not change `Where`, `Do`, `Facts`, `Why` or `Note`. Leave applied records alone.
- A requirement row is written as `<current state> | <rating>` or as `Observed:` and `Assessment:` lines. Rating is one of the document's own: Met, Partially Met, Not Met, Not Applicable. Req ID and Requirement are never rewritten.
- If the facts need more than one paragraph, use more than one.

## Never infer

- Write each fact at the strength of its evidence: keep its scope (name the site when the scope covers part of the estate), use the evidence's own words for frequency, timing and content.
- No "which means", "likely", "therefore" or other conclusion. Connecting words may order facts; they may not add a claim.
- Every sentence traces to a fact line. Update the `## Fact audit` table so each rewritten sentence has its evidence quote.

## Style and naming

- Answer the requirement's question first, in terms of the systems it concerns, and name the server, resolver or host it points to.
- Say each fact once, in full sentences (no bullet fragments, no lead-ins, no evidence as the subject), no general technology explanation. Host-level detail goes in tables.
- Host name first in prose; the IP address only where no name was found. No IP address, subnet or evidence ID in prose Text.
- Keep current state, interpretation, gap and risk observation distinct. No recommendation, no future-state design.
- Australian English. Technical explanations only in a labelled `Technical explanation` note.

## Errors and warnings

Fix every ERROR from `csa check-change`. Fix PROSE_LINT warnings about structure (fragments, lead-ins, evidence as subject, repetition). Length, sentence-size and identifier notes are advice: never drop or blur a fact that describes the system to meet them. Fix TERM_LINT findings.

## Open the full file only when

- `csa-writing-style/SKILL.md`: `check-change` reports PROSE_LINT structure warnings you cannot fix from the list above.
- `australian-it-ot-terminology/SKILL.md`: `check-change` reports TERM_LINT findings, or you are unsure of a component's name.
- `csa-section-writer/SKILL.md`: the record is not a prose paragraph or table row.
- `csa-core-rules.md`: an ERROR code is unclear.

Report which records you rewrote, then stop.
