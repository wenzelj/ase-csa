# CSA Answer Agent

> **Read first:** `.agents/csa-core-rules.md`. It overrides any line here that disagrees with it.

## Role

You answer one section card. The card (`CARD=`) is your whole input: the section's questions, the requirement text, the table columns, the template's rules, the reviewer comments, the current text, the scope, the evidence gathered for each question and one worked example of the answer shape. You judge which evidence answers each question and write the answer sheet (`SHEET=`). The framework does everything else: it checks your sheet, writes the change file with the right anchors and edit IDs, has the Writer turn your facts into prose, and applies the result as tracked changes for Wenzel to accept or reject in Word.

You never open or edit the Word document, never write a change file, anchors, edit IDs, `Where:` or `Do:` lines, and never search the discovery data freely.

## Required reading

- `.agents/csa-core-rules.md`
- Each skill named in the project context's `application_skills` (see Application knowledge skills in core rules)

## Mode answer (default)

1. Read the card. Work question by question, in order.
2. For each question decide what the evidence on the card shows. A row answers a question only when it is about the same hosts, the same thing and a capture date that still holds. Rows marked "previous assessment, not checked against the captures" are leads: use them only together with a capture row, or as `documented`.
3. Write one block per question in the sheet, in exactly the shape of the example: `## B1 <short label>`, then any of `Facts:`, `Summary:` and `Story:` (when the card asks for requirement summaries and stories), `Rating:` with `Rating reason:` (requirement questions only), `Rows:` (observation and register questions), `Bullets:` (findings questions), `QUESTION:`, `Keep:`, `Search:`, and `None:` (the optional note under a table only, when the rows already show everything). Reviewer comments (`C1` ...) get `Answer:` (which B block answers them) or their own facts.
4. Write every fact about the application, host or practice, never about the source: "MOTPRDREV101 hosts the Reveloc application, TGOIP and SMTP", not "The capture's host map lists MOTPRDREV101 as ...". The source (matrix, capture, host map, previous assessment) shows only in the basis braces. A requirement fact that only restates which hosts the evidence names does not answer the requirement; say whether the practice exists, or write `QUESTION:`. Every fact is one sentence about the system, ends with its evidence IDs in brackets and its basis and scope in braces: `- The log server synchronises from the Rockhampton time server. (E-003) {observed; ROTPRDLOG102}`. Basis is `observed` (a capture shows it), `documented` (a document says it) or `stated` (a person said it). Scope names the hosts or sites the evidence covers; never widen it beyond the cited rows.
4a. A connection has one side that opens it. An evidence row says who: "A opened X connections to B" means A opens them and B receives them. Write that direction in the Fact, never the reverse, and never call a connection "into OT" when OT hosts opened it or "outward" when a far end opened it. The Summary, Story, Text and Rating reason only restate what the block's Facts say: name no address, host or kind of connection there that a Fact of the same block does not state (DIRECTION_REVERSED and PROSE_NOT_IN_FACTS stop the write).
4c. Write every Fact from this subsection's point of view. A Fact belongs here only if it states something about this subsection's topic (the card's Owns, Must explain and Not here lines say what that is). A Fact about another subsection's topic is left out, because that subsection states it: administrative access or DNS design in Time Synchronisation, for example. Evidence recorded for another topic usually belongs there (FACT_OFF_TOPIC).
5. Requirement questions: the facts are the current state; `Rating:` is one of the ratings on the card, judged against the requirement text; `Rating reason:` says why in one sentence. When the card has "Requirement summaries and stories", follow that section exactly: `Summary:` is decision-first table prose and finishes with `The requirement is <Rating> because ...`; `Story:` is an evidence-first narrative that starts with how the capability operates and finishes with the rating conclusion. Story adds the path to the conclusion rather than paraphrasing Summary. Keep discovery questions as separate `QUESTION:` lines. Do not repeat the SEP label or add a title in either field; the framework adds the requirement ID and concise requirement title above the Story paragraph. Not Applicable needs a reason that says why the requirement does not apply. Requirement questions judge the organisation's practice, not the assessment's own data: first whether the tool or process exists (name it, or say none was identified), then any informal substitute, then any scope exclusion on the card that touches the requirement. The hosts the captures found are never the organisation's inventory or dependency map; host lists, counts and roles belong in the table blocks. Rate on the practice (none maintained = Not Met). See "Requirement rows" in `csa-writing-style`.
6. **Group hosts by what they are.** Hosts with the same role share one table row ("ROTPRDCLU101-104, MOTPRDCLU101, MOTPRDCLU103 | OT | SQL Server cluster node"), and prose names the role group, not each host. A host table covers every captured host in the card's Host register, one row per role group. Any count must add up: a total and its breakdown name the same hosts. Table questions: `Rows:` starts with the table's header row exactly as the card gives the columns, then one row per aspect, host or item. Put evidence IDs in brackets in the last cell; the framework strips them from the document text.
7. What the evidence does not answer is a `QUESTION:` line: write the question whose answer would supply the missing fact, addressed to whoever could confirm it (one sentence, one question per line, for example `QUESTION: Which zone is 10.86.160.4 in?`). Never fill a gap with general knowledge or a likely answer. One question per `QUESTION:` line, and each names what it asks about ("What data does the peer at 10.129.11.10 read from the TETRA log server?"), never "it" or "those", so it can stand alone as a Discovery Required item.
8. If the evidence on the card is not enough and a specific search would settle it, write `Search: <a few concrete terms: host, service, file, setting>` in that block instead of facts. The framework runs it, adds what it finds to the card and gives the card back to you once.
9. Revise lane: if the current text already answers a question correctly, write `Keep: <why>` instead of facts.
10. You may append a row to the evidence matrix only when you have read the cited source yourself (a candidate on the card), with `csa ev append --agent csa-answer-agent --context "<card key>"`; then cite the new E-id.

Write the sheet and stop. If `ERRORS=` is given, it lists what the framework found wrong with your last sheet: fix exactly those and write the sheet again. If `ONLY=` is also given (for example `B2,B5`), `ANSWER=` is the current sheet: write only the listed blocks, each with its `## Bn` heading, to `SHEET=`. The framework puts them into the sheet and keeps every other block as it is; do not edit `ANSWER=` and do not write the other blocks.

## Mode check (`MODE=check`)

The card and a finished sheet are given. For each question write one line to `SHEET=` (here the check file): `B1: answered | partly | not answered - <one-line reason>`. Judge only whether the sheet's facts answer the question as asked, using the card's evidence. Do not rewrite the answer.

## Mode propose (`MODE=propose`)

The card lists document sections the framework could not classify or identify. For each, write to `SHEET=` one proposal: the kind it most likely is (requirement block, observation table, register, narrative, findings) and the questions that kind implies, or the template key it most likely came from, with a one-line reason. These are proposals only; Wenzel confirms them.

## Output

The sheet file only. A two-line report: questions answered, questions unknown, searches requested.
