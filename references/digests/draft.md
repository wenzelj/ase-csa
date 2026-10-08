# Rules digest: draft lane (pre-V1)

The card (`CARD=`) is your whole input. Write the answer sheet (`SHEET=`) once and stop. The framework writes it straight into the document as plain text. There is no writer pass and no review, so the prose you write is what the reader sees. If `ERRORS=` is given, fix exactly those and write the sheet again.

## Sheet shape

- One block per question on the card, in order: `## B1 <short label>`. Reviewer comments (`C1` ...) get `Answer: B<n>` (the block that answers them).
- `Facts:` are one sentence each about the system, ending with the evidence IDs and the basis and scope: `- MOTPRDREV101 hosts the Reveloc application. (E-003) {observed; MOTPRDREV101}`. Basis is `observed`, `documented` or `stated`.
- `Text:` (requirement and narrative blocks) is the finished prose for the document: one line per paragraph, built only from that block's Facts, with no evidence IDs.
- Requirement blocks: `Facts:`, `Text:` (the current state, one to three sentences), `Rating:` (one of the card's ratings) and `Rating reason:` (one sentence).
- Table blocks: `Rows:` starts with the header row exactly as the card gives the columns, then one row per item. Evidence IDs go in brackets in the last cell, and the framework strips them.
- Findings blocks: `Bullets:` with one finding per bullet.
- `Unknown:` is one sentence saying what is not known and who could confirm it. `Keep:` means the current text already answers the question correctly. `Search: <host, service, file>` asks for more evidence once, and only when a specific search would settle it.

## Never infer

- State only what the evidence shows, at the strength it shows it. Do not write "which means", "likely", "therefore" or "typically".
- A conclusion you would have to reason your way to is an `Unknown:` line. Never fill a gap with general knowledge.
- Requirement blocks judge the organisation's practice: whether the tool or process exists (name it, or say none was identified), and rate on that.

## Writing

- Write for this subsection's purpose only. Explain how the system works as far as this subsection needs it, and leave out what belongs elsewhere.
- Write plain, story-like Australian English in full sentences. Make the application, host or practice the subject, never the capture or the matrix.
- Group hosts by role. One table row per role group, and prose names the role group. Every count must add up.

## Names and addresses

- When a host has a name, use the name exactly as the sources write it. Never rename or "correct" a host name (for example, RevViewer stays RevViewer).
- Use an IP address in prose only when it describes the system and no host name is known for it.
- Tables that capture the system (host, register and connection tables) give both the name and the address, e.g. `MOTPRDREV101 (10.20.1.5)`. Leave the address out when none is known.

## Hard errors (the only ones that stop the write)

QUESTION_MISSING, EMPTY_ANSWER, FACT_NO_EVIDENCE, UNKNOWN_EVIDENCE, RATING_INVALID, COLUMNS, ROW_WIDTH, NO_ROWS, REQUIREMENT_NO_FACTS. Everything else is reported as a warning. `csa check-change` does not run in the draft lane.

Do not open other rule files. Report in two lines: questions answered, questions unknown.
