# Rules digest: draft lane (pre-V1)

The card (`CARD=`) is your whole input. Write the answer sheet (`SHEET=`) once and stop. The framework writes it straight into the document as plain text. There is no writer pass and no review, so the prose you write is what the reader sees. If `ERRORS=` is given, fix exactly those and write the sheet again.

## Sheet shape

- One block per question on the card, in order: `## B1 <short label>`. Reviewer comments (`C1` ...) get `Answer: B<n>` (the block that answers them).
- `Facts:` are one sentence each about the system, ending with the evidence IDs and the basis and scope: `- MOTPRDREV101 hosts the Reveloc application. (E-003) {observed; MOTPRDREV101}`. Basis is `observed`, `documented` or `stated` for evidence (E-) facts, and `background` only for a knowledge (K-) fact.
- `Text:` is the finished prose for narrative blocks. For requirement blocks on a card with "Requirement summaries and stories", use `Summary:` for the Current State table cell and `Story:` for the fuller paragraph under its framework-generated requirement title in Discovery Information. All prose is built only from that block's Facts and has no evidence IDs.
- Split requirement blocks: `Facts:`, `Summary:` (one to three sentences, at most 80 words), `Story:` (the fuller evidence-backed narrative), `Rating:` and `Rating reason:`. Do not repeat the SEP label because the framework adds it to the story.
- Table blocks: `Rows:` starts with the header row exactly as the card gives the columns, then one row per item. Evidence IDs go in brackets in the last cell, and the framework strips them.
- Findings blocks: `Bullets:` with one finding per bullet.
- The optional note under a table (`note`): `None: <why>` removes it, or one or two evidenced sentences of a fact the rows cannot show (a host unlike its group, sources that disagree, fewer hosts covered). Start from the card's "Note candidates". Facts only, never a repeat of a row.
- Another application's rows (`<project>:E-nnn`, from "Shared enterprise services") are context: only in narrative and note blocks, with that project in the scope (`{observed; utcdtc: 8 hosts}`). Never the only support of a current state or table row (CROSS_PROJECT_ONLY).
- `QUESTION:` is one real question, ending in "?", whose answer would supply the missing fact (for example "Which zone is 10.86.160.4 in?"). Never write a statement, and never bundle two questions in one line. Several open points get several `QUESTION:` lines, one each, so each becomes its own Discovery Required item (UNKNOWN_BUNDLED). `Keep:` means the current text already answers the question correctly. `Search: <host, service, file>` asks for more evidence once, and only when a specific search would settle it.

## Never infer

- State only what the evidence shows, at the strength it shows it. Do not write "which means", "likely", "therefore" or "typically".
- A conclusion you would have to reason your way to is an `QUESTION:` line. Never fill a gap with general knowledge of your own.
- Drawbridge Impact names the system's functions, what stops, what keeps working and what that means for operations, not only the infrastructure that is lost. Take the functions from the card's "Declared dependencies and flows" rows: a function stops when something it needs is cut, stated only where a row names the need.
- Re-answering: keep every fact listed under the card's "Facts to keep" and every fact that capture evidence supported in the answer you replace, or add `Dropped: E-<n> <why it no longer applies>` to the block (CAPTURE_DROPPED).
- The card's "Background knowledge (not evidence)" section comes from knowledge documents kept apart from the discovery data. It is NOT evidence and is not in the evidence matrix. Use it to understand what the evidence means. A K- passage may explain an evidenced observation in a narrative block (Drawbridge Impact): give it its own fact citing only its K- ID with basis `background`, next to the E- fact it explains. Never cite a K- ID in a Current State, Rating, table row or bullet. A "Look for" line (system model, second-hand statements) has no ID: state it only from an E- evidence row, otherwise write `QUESTION:`. An "Open question" line is an `QUESTION:`. The framework refuses a sheet that breaks this (BACKGROUND_AS_EVIDENCE, BACKGROUND_MIXED, BACKGROUND_ALONE, BACKGROUND_NOT_ON_CARD).
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

QUESTION_MISSING, EMPTY_ANSWER, FACT_NO_EVIDENCE, UNKNOWN_EVIDENCE, RATING_INVALID, COLUMNS, ROW_WIDTH, NO_ROWS, CROSS_PROJECT_ONLY, BACKGROUND_AS_EVIDENCE, ZONE_CONTRADICTED, ISOLATION_WRONG_SIDE, ATTEMPT_AS_ESTABLISHED, DIRECTION_REVERSED, PROSE_NOT_IN_FACTS. Everything else is a warning: the sheet is written anyway and the warnings are listed for the reader. Answer the question as well as the evidence allows; keep the facts the card lists under Facts to keep, and put a question for anything the evidence cannot settle. `csa check-change` does not run in the draft lane.

Do not open other rule files. Report in two lines: questions answered, questions unknown.
- Drawbridge Impact: state each stop plainly and say what it means for operations in the function's own words (from the function map). Where a path's zone is not recorded, say so once in an `QUESTION:` line; do not hedge the Text with "if" or "may" (DRAWBRIDGE_HEDGE, a warning). Leave out a part outside OT whose only paths are its own outward internet paths unless it loses a path into OT.
- A card line "Rows disagree:" means a row says there is none of a kind of traffic while the frame found some: state both, and do not cite that row as showing there are none.

## Direction of connections

Write who opens a connection as its evidence row does ("A opened X to B": A opens). Summary, Story, Text and Rating reason restate the block's Facts only: no address, host or kind of connection a Fact of the block lacks.
Write Facts from this subsection's topic only (Owns / Must explain / Not here on the card); a Fact about another subsection's topic is left out (FACT_OFF_TOPIC).
