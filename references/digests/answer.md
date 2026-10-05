# Rules digest: answer stage

The card (`CARD=`) is your whole input. Write the answer sheet (`SHEET=`) and stop. If `ERRORS=` is given, fix exactly those and write the sheet again.

## Sheet shape

- One block per question, in order: `## B1 <short label>`. Fields: `Facts:`, `Rating:` with `Rating reason:` (requirement questions only), `Rows:` (table questions), `Bullets:` (findings), `Unknown:`, `Keep:`, `Search:`. Reviewer comments (`C1` ...) get `Answer:` (which B block answers them) or their own facts.
- A fact is one sentence about the system, ends with its evidence IDs in brackets and its basis and scope in braces: `- The log server synchronises from the Rockhampton time server. (E-003) {observed; ROTPRDLOG102}`.
- Basis is `observed` (a capture shows it), `documented` (a document says it) or `stated` (a person said it). There is no `inferred`.
- Scope names the hosts or sites the cited rows cover. Never widen it beyond them.
- `Rows:` starts with the table's header row exactly as the card gives the columns, then one row per aspect, host or item. Evidence IDs go in brackets in the last cell.
- Rating is one of the ratings on the card, judged against the requirement text, with a one-sentence reason. Not Applicable needs a reason that says why the requirement does not apply.

## Never infer

- State what the evidence shows at the strength it shows it: no "which means", "likely", "therefore", "typically".
- Use the evidence's own words for frequency, timing, direction, content and quantity.
- A conclusion you would have to reason your way to is an `Unknown:` line (what is not known, who could confirm it), never a fact. Never fill a gap with general knowledge.
- A row answers a question only when it is about the same hosts, the same thing and a capture date that still holds. Rows marked "previous assessment, not checked against the captures" are leads: use them only with a capture row, or as `documented`.

## Naming

- Name hosts by host name in full, never an IP address, unless no name was found. No IP address or subnet in a fact or row text beyond that.
- Evidence IDs never appear in document text; the framework strips them from rows.

## Errors the framework reports (fix every one)

QUESTION_MISSING, EXTRA_BLOCK, EMPTY_ANSWER, REQUIREMENT_NO_FACTS, FACT_NO_EVIDENCE, UNKNOWN_EVIDENCE, EVIDENCE_NOT_ON_CARD, BAD_BASIS, SCOPE_OUTSIDE_EVIDENCE (a host in the fact's scope is not in the cited evidence), RATING_INVALID, RATING_NO_REASON, COLUMNS and ROW_WIDTH (table shape), NO_ROWS, IP_IN_PROSE. NEEDS_SEARCH means a `Search:` line was written: the framework adds results once.

## Searching and the matrix

- If the card's evidence is not enough and one specific search would settle it, write `Search: <host, service, file, setting>` in that block instead of facts. It is run once.
- Revise lane: if the current text already answers a question correctly, write `Keep: <why>`.
- Append a matrix row (`csa ev append --agent csa-answer-agent --context "<card key>"`) only after reading the cited source yourself.

## Open the full file only when

- `csa-core-rules.md`: an error code or rule above is unclear.
- `csa-answer-agent.md`: MODE=check or MODE=propose is requested.
- An application skill: the card names a product you do not recognise.

`csa check-change` is not run at this stage; the framework validates the sheet.
