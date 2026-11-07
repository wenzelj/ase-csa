# Rules digest: answer stage

The card (`CARD=`) is your whole input. Write the answer sheet (`SHEET=`) and stop. If `ERRORS=` is given, fix exactly those and write the sheet again.

## Sheet shape

- One block per question, in order: `## B1 <short label>`. Use the fields the card needs: `Facts:`, split-requirement `Summary:` and `Story:`, `Rating:` and `Rating reason:`, `Rows:`, `Bullets:`, `QUESTION:`, `Keep:`, `Search:` or `Dropped:`. Reviewer comments (`C1` ...) get `Answer:` naming the B block, or their own facts.
- A fact is one sentence about the system, ends with its evidence IDs in brackets and its basis and scope in braces: `- The log server synchronises from the Rockhampton time server. (E-003) {observed; ROTPRDLOG102}`.
- Basis is `observed` (a capture shows it), `documented` (a document says it), or `stated` (a person said it). `background` is only for a knowledge (K-) fact. There is no `inferred`.
- `Rows:` starts with the table's header row exactly as the card gives the columns, then one row per aspect, host or item. Evidence IDs go in brackets in the last cell.
- The optional note under a table (`note`): `None: <why>` removes it, or one or two evidenced sentences of a fact the rows cannot show (a host unlike its group, sources that disagree, fewer hosts covered). Start from the card's "Note candidates". Facts only, never a repeat of a row.
- Split requirements: `Summary:` is decision-first table prose (up to three sentences and 80 words) ending `The requirement is <Rating> because ...`. `Story:` tells how the capability works now and ends with what the evidence leaves unknown or the gap that decided the rating. It does not state the rating, and every sentence says something the Summary does not (STORY_RESTATES_RATING, STORY_REPEATS_SUMMARY). Keep `QUESTION:` separate.
- Rating is one of the ratings on the card, judged against the requirement text, with a one-sentence reason. Not Applicable needs a reason that says why the requirement does not apply.

## Naming

- In facts, name a host by its role from the Host register and keep the host name in the fact for the table; the Writer chooses the prose form. Use an IP address only where no host name is known.

## Errors the framework reports (fix every one)

QUESTION_MISSING, EXTRA_BLOCK, EMPTY_ANSWER, REQUIREMENT_NO_FACTS, FACT_NO_EVIDENCE, UNKNOWN_EVIDENCE, EVIDENCE_NOT_ON_CARD, BAD_BASIS, SCOPE_OUTSIDE_EVIDENCE (a host in the fact's scope is not in the cited evidence), RATING_INVALID, RATING_NO_REASON, COLUMNS and ROW_WIDTH (table shape), NO_ROWS, IP_IN_PROSE, COUNT_MISMATCH (a total whose parts do not add up), HOSTS_NOT_GROUPED (one role spread over several rows), HOSTS_MISSING (a captured host left out of a host table), SOURCE_AS_SUBJECT (the sentence is about the matrix, capture or host map: rewrite it about the system), SEMICOLON (a semicolon in a fact, Text or bullet: write two sentences, or join the parts with a comma and "and" or "but"). NEEDS_SEARCH means a `Search:` line was written: the framework adds results once.

## Searching

- If the card's evidence is not enough and one specific search would settle it, write `Search: <host, service, file, setting>` in that block instead of facts. It is run once.
- Revise lane: if the current text already answers a question correctly, write `Keep: <why>`.

`csa check-change` is not run at this stage; the framework validates the sheet.

The full rules are the files listed under REQUIRED_READING in the prompt: read them, this digest only summarises.
