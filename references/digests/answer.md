# Rules digest: answer stage

The card (`CARD=`) is your whole input. Write the answer sheet (`SHEET=`) and stop. If `ERRORS=` is given, fix exactly those and write the sheet again.

## Sheet shape

- One block per question, in order: `## B1 <short label>`. Use the fields the card needs: `Facts:`, split-requirement `Summary:` and `Story:`, `Rating:` and `Rating reason:`, `Rows:`, `Bullets:`, `Unknown:`, `Keep:`, `Search:` or `Dropped:`. Reviewer comments (`C1` ...) get `Answer:` naming the B block, or their own facts.
- A fact is one sentence about the system, ends with its evidence IDs in brackets and its basis and scope in braces: `- The log server synchronises from the Rockhampton time server. (E-003) {observed; ROTPRDLOG102}`.
- Write every fact about the application, host or practice, never about the source: "MOTPRDREV101 hosts the Reveloc application, TGOIP and SMTP", not "The capture's host map lists MOTPRDREV101 as ...". The source (matrix, capture, host map, previous assessment) shows only in the basis braces. A requirement fact that only restates which hosts the evidence names does not answer the requirement; say whether the practice exists, or write `Unknown:`.
- Basis is `observed` (a capture shows it), `documented` (a document says it), or `stated` (a person said it). `background` is only for a knowledge (K-) fact. There is no `inferred`.
- Scope names the hosts or sites the cited rows cover. Never widen it beyond them.
- **Group hosts by role.** One role group per table row, and prose names the role group. A host table covers every captured host in the card's Host register. Any total and breakdown must name the same hosts and add up.
- `Rows:` starts with the table's header row exactly as the card gives the columns, then one row per aspect, host or item. Evidence IDs go in brackets in the last cell.
- The optional note under a table (`note`): `None: <why>` removes it, or one or two evidenced sentences of a fact the rows cannot show (a host unlike its group, sources that disagree, fewer hosts covered). Start from the card's "Note candidates". Facts only, never a repeat of a row.
- Another application's rows (`<project>:E-nnn`, from "Shared enterprise services") are context: only in narrative and note blocks, with that project in the scope (`{observed; utcdtc: 8 hosts}`). Never the only support of a current state or table row (CROSS_PROJECT_ONLY).
- Requirement questions judge the organisation's practice, not the assessment's data: say whether the tool or process exists, then any informal substitute and relevant scope exclusion. Capture host lists are not the organisation's inventory; put lists, counts and roles in table blocks. Rate the practice and keep it to one to three facts. See "Requirement rows" in `csa-writing-style`.
- For a split requirement, `Summary:` is the Current State cell (one to three sentences and at most 80 words), while `Story:` is the fuller evidence-backed narrative placed under Discovery Information. Do not repeat the SEP label in either field.
- Rating is one of the ratings on the card, judged against the requirement text, with a one-sentence reason. Not Applicable needs a reason that says why the requirement does not apply.

## Never infer

- State what the evidence shows at the strength it shows it: no "which means", "likely", "therefore", "typically".
- Use the evidence's own words for frequency, timing, direction, content and quantity.
- A conclusion you would have to reason your way to is an `Unknown:` line (what is not known, who could confirm it), never a fact. Never fill a gap with general knowledge of your own.
- The card's "Background knowledge (not evidence)" section comes from knowledge documents kept apart from the discovery data. It is NOT evidence and is not in the evidence matrix. Use it to understand what the evidence means. A K- passage may explain an evidenced observation in a narrative block (Drawbridge Impact): give it its own fact citing only its K- ID with basis `background`, next to the E- fact it explains. Never cite a K- ID in a Current State, Rating, table row or bullet. A "Look for" line (system model, second-hand statements) has no ID: state it only from an E- evidence row, otherwise write `Unknown:`. An "Open question" line is an `Unknown:`. The framework refuses a sheet that breaks this (BACKGROUND_AS_EVIDENCE, BACKGROUND_MIXED, BACKGROUND_ALONE, BACKGROUND_NOT_ON_CARD).
- Drawbridge Impact names the system's functions, what stops, what keeps working and what that means for operations, not only the infrastructure that is lost. Take the functions from the card's "Declared dependencies and flows" rows: a function stops when something it needs is cut, stated only where a row names the need.
- Re-answering: keep every fact listed under the card's "Facts to keep" and every fact that capture evidence supported in the answer you replace, or add `Dropped: E-<n> <why it no longer applies>` to the block (CAPTURE_DROPPED).
- One question per `Unknown:` line: several open points get several lines (UNKNOWN_BUNDLED).
- A row answers a question only when it is about the same hosts, the same thing and a capture date that still holds. Rows marked "previous assessment, not checked against the captures" are leads: use them only with a capture row, or as `documented`.

## Naming

- In facts, name a host by its role from the Host register and keep the host name in the fact for the table; the Writer chooses the prose form. Use an IP address only where no host name is known. Prose names a machine by its role from the Host register (the RevViewer Jump Host, the Radio Management host), not by host name or IP address; names and addresses go in tables, unless the question asks for hosts or addresses, in which case give them. Rules and exceptions: "Host references" in `csa-writing-style`. Tables that capture the system give both, e.g. `MOTPRDREV101 (10.20.1.5)`; names are written exactly as the sources write them (RevViewer stays RevViewer).
- Evidence IDs never appear in document text; the framework strips them from rows.

## Errors the framework reports (fix every one)

QUESTION_MISSING, EXTRA_BLOCK, EMPTY_ANSWER, REQUIREMENT_NO_FACTS, FACT_NO_EVIDENCE, UNKNOWN_EVIDENCE, EVIDENCE_NOT_ON_CARD, BAD_BASIS, SCOPE_OUTSIDE_EVIDENCE (a host in the fact's scope is not in the cited evidence), RATING_INVALID, RATING_NO_REASON, COLUMNS and ROW_WIDTH (table shape), NO_ROWS, IP_IN_PROSE, COUNT_MISMATCH (a total whose parts do not add up), HOSTS_NOT_GROUPED (one role spread over several rows), HOSTS_MISSING (a captured host left out of a host table), SOURCE_AS_SUBJECT (the sentence is about the matrix, capture or host map: rewrite it about the system), SEMICOLON (a semicolon in a fact, Text or bullet: write two sentences, or join the parts with a comma and "and" or "but"). NEEDS_SEARCH means a `Search:` line was written: the framework adds results once.

## Searching and the matrix

- If the card's evidence is not enough and one specific search would settle it, write `Search: <host, service, file, setting>` in that block instead of facts. It is run once.
- Revise lane: if the current text already answers a question correctly, write `Keep: <why>`.
- Append a matrix row (`csa ev append --agent csa-answer-agent --context "<card key>"`) only after reading the cited source yourself.

## Open the full file only when

- `csa-core-rules.md`: an error code or rule above is unclear.
- `csa-answer-agent.md`: MODE=check or MODE=propose is requested.
- An application skill: the card names a product you do not recognise.

`csa check-change` is not run at this stage; the framework validates the sheet.

## Absence

- When the evidence shows something is absent, say so about the system and name the sources that were checked: "No isolation test record appears in the twelve discovery captures or the supplied documents." Never describe the framework's own search ("the matrix", "the index rows", "rows searched", "for this domain"). The reader has never seen them, and the framework refuses the sheet (PROCESS_AS_SUBJECT).
