# CSA card rules

For the card-based lanes (`csa answer`, `csa draft`). Your evidence is the card, you write only the answer sheet, and you run no `csa` tools. The sections below are copied word for word from `csa-core-rules.md`, which stays the authority for every other agent. Edit them there and copy them here (a test checks they match). Where an agent file disagrees with this file, this file wins.

## Project

- Never guess the project. It comes from the prompt (`PROJECT`, `WORKSPACE`, `WORK_DIR`) or from `csa use`. If it is missing, ask.
- Project facts live in the project's context file and evidence, never in shared agent or skill files.

## Evidence

- Classes: `VERIFIED`, `INFERRED`, `UNCONFIRMED`, `CONFLICTING`, `NOT_FOUND`. Never upgrade an inference because it is plausible. "Not observed in the evidence searched" is never written as "does not exist".
- General technical knowledge never fills a gap in project facts. It may explain significance, in a labelled `Technical explanation`.
- **Source precedence when evidence disagrees about a concrete value (address, hostname, port, version, role):** a live capture, connection log, resolver/DNS or asset/inventory record (non-diagram, log-derived evidence) confirms the value and outranks a network-diagram transcription, which may be out of date. When they conflict, record the log/inventory value as `VERIFIED` and reject the diagram row as superseded; note the rule in `gap_or_action` and name the winning E-id. Do not carry a diagram-vs-log disagreement as an unresolved `CONFLICTING` item — the diagram is the stale source, not a second credible reading.
- The card is your evidence. A card row answers a question only when it is about the same hosts and the same thing. Anything the card cannot settle is a `QUESTION:` line, or one `Search:` line when a specific search would settle it.

## Document text

- **The subject is the system, its applications and its hosts.** A source's own keys (a workbook row, a collection or group ID, a sheet or line number, an evidence ID) are citations, never the subject of a sentence, a fact or a table row. Tables are keyed by host(s), role or application; hosts that share the same configuration share a row. **Group hosts by what they are.** Hosts with the same role share one table row ("ROTPRDCLU101-104, MOTPRDCLU101, MOTPRDCLU103 | OT | SQL Server cluster node"), and prose names the role group, not each host. A host table covers every captured host in the card's Host register, one row per role group. Any count must add up: a total and its breakdown name the same hosts.

- Stable IDs (`@H...`), evidence file names and status tags never appear in document text either (see Evidence IDs never in document text).
- Prose follows `csa-writing-style`; terms and spelling follow `australian-it-ot-terminology`.

## Never infer

- State what the evidence shows at the strength it shows it. No conclusions the evidence does not state ("which means", "likely", "therefore", "typically").
- Use the evidence's own words for frequency, timing, direction, content and quantity: "copies yesterday's file" is not "daily".
- Keep the scope of the capture: name the hosts or sites it covers, and never widen to "all", "every", "both" or "the system".
- A conclusion you would have to reason your way to is an unknown and an open question, never a fact. A gap stated plainly is good writing.
- A consequence the evidence records is not an inference: a function map or flow row that says a function needs DNS, and a cut path that removes it, lets you write what stops and what that means for operations in the function's own words. Without that record, the consequence is an open question.
- `prose_lint` flags inference wording; `csa check-change` checks every fact against the evidence matrix.

## Evidence IDs never in document text

- Evidence IDs (`E-nnn`) belong in the change record's `Why:` and, from there, the Word comment; never inline in a sentence or table cell (no "`[E-042]`").
- Uncertainty is said in plain words ("has not been directly observed", "reported inconsistently across hosts"), never as a bracketed status tag.

## Stopping

- Stop after the unit of work you were asked for (one section, one batch, one skill) and report. Do not start the next one.
- If something cannot be done safely, record an open question or report `BLOCKED` with the reason. Do not guess.
