# Rules digest: draft lane (pre-V1)

The card (`CARD=`) is your whole input. Write the answer sheet (`SHEET=`) once and stop. The framework writes it straight into the document as plain text. There is no writer pass and no review, so the prose you write is what the reader sees. If `ERRORS=` is given, fix exactly those and write the sheet again.

## Sheet shape

- One block per question on the card, in order: `## B1 <short label>`. Reviewer comments (`C1` ...) get `Answer: B<n>` (the block that answers them).
- `Facts:` are one sentence each about the system, ending with the evidence IDs and the basis and scope: `- MOTPRDREV101 hosts the Reveloc application. (E-003) {observed; MOTPRDREV101}`. Basis is `observed`, `documented` or `stated` for evidence (E-) facts, and `background` only for a knowledge (K-) fact.
- `Text:` (requirement and narrative blocks) is the finished prose for the document: one line per paragraph, built only from that block's Facts, with no evidence IDs.
- Requirement blocks: `Facts:`, `Text:` (the current state, one to three sentences), `Rating:` (one of the card's ratings) and `Rating reason:` (one sentence).
- Table blocks: `Rows:` starts with the header row exactly as the card gives the columns, then one row per item. Evidence IDs go in brackets in the last cell, and the framework strips them.
- Findings blocks: `Bullets:` with one finding per bullet.
- The optional note under a table (a `note` question): either `None: <why>`, which removes the placeholder, or one or two sentences in `Facts:` (and `Text:` in the draft lane) for a fact the table rows cannot show: a host or role group that differs from the others in its group, sources that disagree, or evidence that covers fewer hosts than the table. Start from the card's "Note candidates". Facts only: no rating, risk or recommendation, and never a repeat of a row (NOTE_TOO_LONG, NOTE_NONE_AND_TEXT, NOTE_NO_FACTS, NOTE_NOT_A_FACT, NOTE_REPEATS_ROW).
- `Unknown:` is one sentence holding one question: what is not known and who could confirm it. Several open points get several `Unknown:` lines, one each, so each becomes its own Discovery Required item (UNKNOWN_BUNDLED). `Keep:` means the current text already answers the question correctly. `Search: <host, service, file>` asks for more evidence once, and only when a specific search would settle it.

## Never infer

- State only what the evidence shows, at the strength it shows it. Do not write "which means", "likely", "therefore" or "typically".
- A conclusion you would have to reason your way to is an `Unknown:` line. Never fill a gap with general knowledge of your own.
- Drawbridge Impact names the system's functions, what stops, what keeps working and what that means for operations, not only the infrastructure that is lost. Take the functions from the card's "Declared dependencies and flows" rows: a function stops when something it needs is cut, stated only where a row names the need.
- Re-answering: keep every fact listed under the card's "Facts to keep" and every fact that capture evidence supported in the answer you replace, or add `Dropped: E-<n> <why it no longer applies>` to the block (CAPTURE_DROPPED).
- The card's "Background knowledge (not evidence)" section comes from knowledge documents kept apart from the discovery data. It is NOT evidence and is not in the evidence matrix. Use it to understand what the evidence means. A K- passage may explain an evidenced observation in a narrative block (Drawbridge Impact): give it its own fact citing only its K- ID with basis `background`, next to the E- fact it explains. Never cite a K- ID in a Current State, Rating, table row or bullet. A "Look for" line (system model, second-hand statements) has no ID: state it only from an E- evidence row, otherwise write `Unknown:`. An "Open question" line is an `Unknown:`. The framework refuses a sheet that breaks this (BACKGROUND_AS_EVIDENCE, BACKGROUND_MIXED, BACKGROUND_ALONE, BACKGROUND_NOT_ON_CARD).
- Drawbridge Impact names the system's functions (from the function map), what stops, what keeps working and what that means for operations, not only the infrastructure that is lost.
- Requirement blocks judge the organisation's practice: whether the tool or process exists (name it, or say none was identified), and rate on that.

## Writing

- Write for this subsection's purpose only. Explain how the system works as far as this subsection needs it, and leave out what belongs elsewhere.
- Write plain, story-like Australian English in full sentences. Make the application, host or practice the subject, never the capture or the matrix.
- No semicolons (`;`) in Text, Facts or Bullets: write two sentences, or join the parts with a comma and "and" or "but". The framework refuses a sheet with one (SEMICOLON, a hard error).
- When the evidence shows something is absent, say so about the system and name the sources that were checked: "No isolation test record appears in the twelve discovery captures or the supplied documents." Never describe the framework's own search ("the matrix", "the index rows", "rows searched", "for this domain"). The reader has never seen them, and the framework refuses the sheet (PROCESS_AS_SUBJECT).
- Group hosts by role. One table row per role group, and prose names the role group. Every count must add up.

## Names and addresses

- When a host has a name, use the name exactly as the sources write it. Never rename or "correct" a host name (for example, RevViewer stays RevViewer).
- Prose names a machine by its role from the Host register (the RevViewer Jump Host, the Radio Management host), not by host name or IP address; names and addresses go in tables, unless the question asks for hosts or addresses, in which case give them. Rules and exceptions: "Host references" in `csa-writing-style`. Use an IP address in prose only for a machine with no name and no known role.
- Tables that capture the system (host, register and connection tables) give both the name and the address, e.g. `MOTPRDREV101 (10.20.1.5)`. Leave the address out when none is known.

## Hard errors (the only ones that stop the write)

QUESTION_MISSING, EMPTY_ANSWER, FACT_NO_EVIDENCE, UNKNOWN_EVIDENCE, RATING_INVALID, COLUMNS, ROW_WIDTH, NO_ROWS, REQUIREMENT_NO_FACTS, NOTE_TOO_LONG, NOTE_NONE_AND_TEXT, NOTE_NO_FACTS, SEMICOLON, PROCESS_AS_SUBJECT, CITATION_OFF_TOPIC, CAPTURE_DROPPED, UNKNOWN_BUNDLED and the BACKGROUND_ codes. Everything else is reported as a warning. `csa check-change` does not run in the draft lane.

Do not open other rule files. Report in two lines: questions answered, questions unknown.
