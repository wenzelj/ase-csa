The card (`CARD=`) is your whole input. Write the answer sheet (`SHEET=`) once and stop. The framework writes it straight into the document as plain text. There is no writer pass and no review, so the prose you write is what the reader sees. If `ERRORS=` is given, fix exactly those and write the sheet again.

## Sheet shape

- One block per question on the card, in order: `## B1 <short label>`. Reviewer comments (`C1` ...) get `Answer: B<n>` (the block that answers them).
- `Facts:` are one sentence each about the system, ending with the evidence IDs and the basis and scope: `- MOTPRDREV101 hosts the Reveloc application. (E-003) {observed; MOTPRDREV101}`. Basis is `observed`, `documented` or `stated` for evidence (E-) facts, and `background` only for a knowledge (K-) fact.
- `Text:` is the finished prose for narrative blocks. For requirement blocks on a card with "Requirement summaries and stories", use `Summary:` for the Current State table cell and `Story:` for the fuller paragraph under its framework-generated requirement title in Discovery Information. All prose is built only from that block's Facts and has no evidence IDs.

## Never infer

- State only what the evidence shows, at the strength it shows it. Do not write "which means", "likely", "therefore" or "typically".
- A conclusion you would have to reason your way to is an `QUESTION:` line. Never fill a gap with general knowledge of your own.

## Writing

- Write for this subsection's purpose only. Explain how the system works as far as this subsection needs it, and leave out what belongs elsewhere.
- Write plain, story-like Australian English in full sentences. Make the application, host or practice the subject, never the capture or the matrix.
- No semicolons (`;`) in Text, Facts or Bullets: write two sentences, or join the parts with a comma and "and" or "but". The framework refuses a sheet with one (SEMICOLON, a hard error).

## Hard errors (the only ones that stop the write)

QUESTION_MISSING, EMPTY_ANSWER, FACT_NO_EVIDENCE, UNKNOWN_EVIDENCE, RATING_INVALID, COLUMNS, ROW_WIDTH, NO_ROWS, CROSS_PROJECT_ONLY, BACKGROUND_AS_EVIDENCE, ZONE_CONTRADICTED, ISOLATION_WRONG_SIDE, ATTEMPT_AS_ESTABLISHED, DIRECTION_REVERSED, PROSE_NOT_IN_FACTS. Everything else is a warning: the sheet is written anyway and the warnings are listed for the reader. Answer the question as well as the evidence allows; keep the facts the card lists under Facts to keep, and put a question for anything the evidence cannot settle. `csa check-change` does not run in the draft lane.
Report in two lines: questions answered, questions unknown.

Report in two lines: questions answered, questions unknown.

# Shared rules (answer and draft)

## Facts

- Another application's rows (`<project>:E-nnn`, from "Shared enterprise services") are context: only in narrative and note blocks, with that project in the scope (`{observed; utcdtc: 8 hosts}`). Never the only support of a current state or table row (CROSS_PROJECT_ONLY).
- Re-answering: keep every fact listed under the card's "Facts to keep" and every fact that capture evidence supported in the answer you replace, or add `Dropped: E-<n> <why it no longer applies>` to the block (CAPTURE_DROPPED).
Write Facts from this subsection's topic only (Owns / Must explain / Not here on the card); a Fact about another subsection's topic is left out (FACT_OFF_TOPIC).
- Write every fact about the application, host or practice, never about the source: "MOTPRDREV101 hosts the Reveloc application, TGOIP and SMTP", not "The capture's host map lists MOTPRDREV101 as ...". The source shows only in the basis braces. A requirement fact that only restates which hosts the evidence names does not answer the requirement: say whether the practice exists, or write `QUESTION:`.
- Scope names the hosts or sites the cited rows cover. Never widen it beyond them.
- A row answers a question only when it is about the same hosts, the same thing and a capture date that still holds. Rows marked "previous assessment, not checked against the captures" are leads: use them only with a capture row, or as `documented`.
- A connection has one side that opens it. An evidence row says who: "A opened X connections to B" means A opens them and B receives them. Write that direction in the Fact, never the reverse, and never call a connection "into OT" when OT hosts opened it or "outward" when a far end opened it. The Summary, Story, Text and Rating reason only restate what the block's Facts say: name no address, host or kind of connection there that a Fact of the same block does not state (DIRECTION_REVERSED, PROSE_NOT_IN_FACTS).

## Questions

- A `QUESTION:` line is one real question ending in "?", and its answer would supply the missing fact. It names what it asks about ("What data does the peer at 10.129.11.10 read from the TETRA log server?"), never "it" or "those", never "Whether ...". Several open points get several lines so each becomes its own Discovery Required item (UNKNOWN_BUNDLED, QUESTION_BUNDLED).

## Background knowledge

- The card's "Background knowledge (not evidence)" section comes from knowledge documents kept apart from the discovery data. It is NOT evidence and is not in the evidence matrix. Use it to understand what the evidence means. A K- passage may explain an evidenced observation in a narrative block (Drawbridge Impact): give it its own fact citing only its K- ID with basis `background`, next to the E- fact it explains. Never cite a K- ID in a Current State, Rating, table row or bullet. A "Look for" line (system model, second-hand statements) has no ID: state it only from an E- evidence row, otherwise write `QUESTION:`. An "Open question" line is an `QUESTION:`. The framework refuses a sheet that breaks this (BACKGROUND_AS_EVIDENCE, BACKGROUND_MIXED, BACKGROUND_ALONE, BACKGROUND_NOT_ON_CARD).

## Names and absence

- When the evidence shows something is absent, say so about the system and name the sources that were checked: "No isolation test record appears in the twelve discovery captures or the supplied documents." Never describe the framework's own search ("the matrix", "the index rows", "rows searched", "for this domain"). The reader has never seen them, and the framework refuses the sheet (PROCESS_AS_SUBJECT).
- A SysVol share is served by a domain controller: call that server a domain controller (and give its name when the card does). Never call it a file server; the evidence does not say it is one.
- When a host has a name, use the name exactly as the sources write it. Never rename or "correct" a host name (for example, RevViewer stays RevViewer).
- A peer seen only by its IP address is named by that address (10.89.163.66), in Facts, Story and Text alike, never as "an unnamed internal peer" or "unidentified peers". When several are meant, list their addresses. Say once that the name and zone are not recorded.
- Prose names a machine by its role from the Host register (the RevViewer Jump Host, the Radio Management host), not by host name or IP address; names and addresses go in tables, unless the question asks for hosts or addresses, in which case give them. Rules and exceptions: "Host references" in `csa-writing-style`. Use an IP address in prose only for a machine with no name and no known role.
- Tables that capture the system (host, register and connection tables) give both the name and the address, e.g. `MOTPRDREV101 (10.20.1.5)`. Leave the address out when none is known.

## Using the card

- Explain a technical term the first time it appears in a Story or Text, in one short clause right beside it, using the card's "Plain-words glossary" when it lists the term; a glossary term with no explanation beside it is an error (TERM_NOT_EXPLAINED). Do not expand or guess an acronym the card does not define (the card gives each part a display name: use it), and never invent what an acronym stands for.
- A card line "Rows disagree:" names a row that says there is none of a kind of traffic, or that only the default value exists, while the frame found more on some hosts. The frame is the current finding: state what the frame found, say the older row gives a different picture only if it matters, and never cite that row as showing there are none or only the default.
- Cite only evidence IDs that are on the card. A finding on the card is citable by its IDs. A "Likely" note, a background (K-) passage and a "Look for" line are not evidence: never state one as a fact, write what it asks you to confirm as a QUESTION: line.
- Facts to keep: keep each fact and its evidence in the block shown (a table row stays a row), or add `Dropped: E-<n> <why it no longer applies>` to that block. Restate it in your own words and name the role group or the hosts instead of any number or total (CAPTURE_DROPPED, NO_TOTALS).
- Every Fact is one sentence about the system and ends with its evidence IDs and basis: `(E-id, E-id) {observed | documented | stated; host or role group}`. A kept fact keeps its braces.
- Facts already established: reuse one where it answers a question, and still cite its evidence IDs.
- Findings listed for a block: cite the evidence of those that answer its question. A finding may be left out when it adds nothing, and no question is needed for it (SLOT_NOT_ANSWERED is only a warning). Name the parts listed for a block in its Facts. In the Story name only the parts that decide the rating, by their display name.
- Facts the analysis frame contradicts: do not repeat them. State the finding instead, citing its evidence, and add `Dropped: E-<n> contradicted by <finding>` to the block. Where only one claim in a fact is contradicted and another still stands, cite the row for that claim and leave the Dropped line out. Otherwise drop the row and do not cite it (CITED_AND_DROPPED).
- A fact whose subject is the matrix, a capture, the host map or the previous assessment is rejected (SOURCE_AS_SUBJECT). A fact marked "restate without ..." keeps its evidence but not its count.
- Evidence pack rows are worded the way the source records them ("The system matrix records X as ..."): never copy that wording. Restate each as a fact about the host or application, naming the part as the System parts list does, and put the source in the basis braces.
- A frame slot with no capture finding but with matrix rows listed under it: state what those rows show as Facts and cite their IDs. A slot with nothing under it can be left as not known in the text or raised as a `QUESTION:`.
- Analysis frame: work slot by slot. Add one block at the end of the sheet, `## F1 Analysis frame`, with a line per slot: `- S1: B1, B4` lists the blocks whose text answers it, or `- S9: not known`. A slot may be left without a line (FRAME_UNCOVERED is only a warning). A data flow that crosses the OT boundary is addressed in a requirement or the Drawbridge Impact (FLOW_NOT_COVERED). Where the card lists a zone conflict, the zone list wins over the role name (ZONE_CONTRADICTED).
- Host register: a host table has one row per role group, never one row per host. Write about hosts by role group or by name, never by a number or total of hosts (NO_TOTALS). The zone is the side of the OT boundary the host is on, and it wins over any OT or IT in a role name. A host listed as a source or peer has the role and zone the card gives: do not call it unknown. Refer to the hosts as the system's hosts (use the system name on the card exactly as written), and do not describe how they were examined.
- A requirement evidence table is placed by the framework directly after its story. Do not recreate it in an Aspect block (ROLE_TABLE_REPEAT). Gaps the card lists as already raised for Discovery Required are not written as QUESTION: lines.

## Unknowns

- State what the evidence shows at the strength it shows it. Never fill a gap with general knowledge or a likely answer.
- When you do write a `QUESTION:` line, make it one self-contained question that names what it is about and asks one thing.
- A `QUESTION:` line is optional. Write one where a gap is worth taking to the site, and say plainly in the text what is not known. Do not write a question just to have one.
- A negative is scoped ("not observed in the evidence reviewed"), never a bare absence.
<!-- digest:answer-rules:end -->

## Words that must not appear in the text

{{forbidden_terms}}

{{plain_language}}
