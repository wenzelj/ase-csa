# Rules digest: draft lane (pre-V1)

The card (`CARD=`) is your whole input. Write the answer sheet (`SHEET=`) once and stop. The framework writes it straight into the document as plain text. There is no writer pass and no review, so the prose you write is what the reader sees. If `ERRORS=` is given, fix exactly those and write the sheet again.

## Sheet shape

- One block per question on the card, in order: `## B1 <short label>`. Reviewer comments (`C1` ...) get `Answer: B<n>` (the block that answers them).
- `Facts:` are one sentence each about the system, ending with the evidence IDs and the basis and scope: `- MOTPRDREV101 hosts the Reveloc application. (E-003) {observed; MOTPRDREV101}`. Basis is `observed`, `documented` or `stated` for evidence (E-) facts, and `background` only for a knowledge (K-) fact.
- `Text:` is the finished prose for narrative blocks. For requirement blocks on a card with "Requirement summaries and stories", use `Summary:` for the Current State table cell and `Story:` for the fuller paragraph under its framework-generated requirement title in Discovery Information. All prose is built only from that block's Facts and has no evidence IDs.
- Split requirements: `Summary:` is decision-first table prose (up to three sentences and 80 words) ending `The requirement is <Rating> because ...`. `Story:` tells how the capability works now and ends with what the evidence leaves unknown or the gap that decided the rating. It does not state the rating, and every sentence says something the Summary does not (STORY_RESTATES_RATING, STORY_REPEATS_SUMMARY). Keep `QUESTION:` separate.
- Table blocks: `Rows:` starts with the header row exactly as the card gives the columns, then one row per item. Evidence IDs go in brackets in the last cell, and the framework strips them.
- Findings blocks: `Bullets:` with one finding per bullet.
- The optional note under a table (`note`): `None: <why>` removes it, or one or two evidenced sentences of a fact the rows cannot show (a host unlike its group, sources that disagree, fewer hosts covered). Start from the card's "Note candidates". Facts only, never a repeat of a row.

## Never infer

- State only what the evidence shows, at the strength it shows it. Do not write "which means", "likely", "therefore" or "typically".
- A conclusion you would have to reason your way to is an `QUESTION:` line. Never fill a gap with general knowledge of your own.

## Writing

- Write for this subsection's purpose only. Explain how the system works as far as this subsection needs it, and leave out what belongs elsewhere.
- Write plain, story-like Australian English in full sentences. Make the application, host or practice the subject, never the capture or the matrix.
- No semicolons (`;`) in Text, Facts or Bullets: write two sentences, or join the parts with a comma and "and" or "but". The framework refuses a sheet with one (SEMICOLON, a hard error).
- Group hosts by role. One table row per role group, and prose names the role group. Every count must add up.

## Names and addresses

## Hard errors (the only ones that stop the write)

QUESTION_MISSING, EMPTY_ANSWER, FACT_NO_EVIDENCE, UNKNOWN_EVIDENCE, RATING_INVALID, COLUMNS, ROW_WIDTH, NO_ROWS, CROSS_PROJECT_ONLY, BACKGROUND_AS_EVIDENCE, ZONE_CONTRADICTED, ISOLATION_WRONG_SIDE, ATTEMPT_AS_ESTABLISHED, DIRECTION_REVERSED, PROSE_NOT_IN_FACTS. Everything else is a warning: the sheet is written anyway and the warnings are listed for the reader. Answer the question as well as the evidence allows; keep the facts the card lists under Facts to keep, and put a question for anything the evidence cannot settle. `csa check-change` does not run in the draft lane.

Report in two lines: questions answered, questions unknown.
