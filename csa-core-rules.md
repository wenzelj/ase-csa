# CSA core rules

Every agent and skill in `.agents/` follows these rules. Where a line in an agent or skill file disagrees with this file, this file wins; say so in your final report so the other file can be fixed.

## Paths and tools

- Paths that start with `.agents/` are relative to the CurrentStateAssessments folder. `csa` starts every agent there.
- Use `csa` for anything it does: `csa status`, `csa lookup`, `csa apply`, `csa ev ...`, `csa index ...`, `csa check-change`, `csa lint`. It picks the framework Python (3.11 or later, from `.agents/cli.yaml`) and the project for you.
- Defaults such as batch sizes and item limits come from `.agents/registry.yaml`. A value in the prompt overrides them. Ignore numbers written anywhere else.

## Project

- Never guess the project. It comes from the prompt (`PROJECT`, `WORKSPACE`, `WORK_DIR`) or from `csa use`. If it is missing, ask.
- Stop on `WORKSPACE_NOT_REGISTERED`, on `NOT_READY`, and when a framework response's `project.key` differs from the project you were given. Do not retry with another path.
- Project facts live in the project's context file and evidence, never in shared agent or skill files.

## Evidence

- Classes: `VERIFIED`, `INFERRED`, `UNCONFIRMED`, `CONFLICTING`, `NOT_FOUND`. Never upgrade an inference because it is plausible. "Not observed in the evidence searched" is never written as "does not exist".
- Look things up in this order: the evidence matrix (`csa ev lookup`), the discovery index (`csa index rows` / `csa index search`), then raw files for what the index does not cover. Append what you find with `csa ev append`; never edit the matrix CSV by hand.
- Work from the hosts: `csa hosts show <HOST>` gives everything known about one machine (register entry, facts from every source with file and line, evidence IDs, connections to other hosts); `csa hosts group --attr "<attribute>" [--attr ...] [--system UTC]` gives the hosts that share a configuration; `csa hosts links [HOST]` gives host-to-host connections. Rebuild with `csa hosts build` after `csa index build`.
- Applications of the same system (for example UTC/DTC and IAMPS in TCS) know each other's hosts: each project's `hosts/roles.csv` lists the others as `system_project`. A connection is verified when either project's capture proves it, and the basis names that project. Cite the sibling project's evidence as `<project>:E-nnn` (for example `utcdtc:E-088`); `csa check-change` checks it against that project's matrix. Never state as observed what neither project's evidence shows. `csa hosts system --name <system>` writes the combined view to `.agents/csa-context/systems/<system>/`.
- One evidence row per claim about a host or a group of hosts that share the value. Write every host name in full (expand `CONTROLLER70 / 73` shorthand); keep the source's row or collection ID in `page_or_location` only.
- General technical knowledge never fills a gap in project facts. It may explain significance, in a labelled `Technical explanation`.

## Document text

- **The subject is the system, its applications and its hosts.** A source's own keys (a workbook row, a collection or group ID, a sheet or line number, an evidence ID) are citations, never the subject of a sentence, a fact or a table row. Tables are keyed by host(s), role or application; hosts that share the same configuration share a row.

- Evidence IDs (`E-nnn`), stable IDs (`@H...`), evidence file names and status tags never appear in document text. They belong in the change record's `Why:` and, from there, the Word comment.
- Prose follows `csa-writing-style`; terms and spelling follow `australian-it-ot-terminology`.

## Change files

- One per section: `reviews/ChangesCSA_<App>_Section<N>.md`. A later correction pass may use `ChangesCSA_<App>_Section<N>_<label>.md`.
- Edit IDs are `S<N>-E<n>` (content) and `S<N>-A<n>` (administrative). Number on from the highest ID used in any change file for that section, including rejected ones (`### REJECTED S<N>-E<n>`). Never reuse an ID.
- Every `Where:` is a stable ID resolved with `lookupStableId` or `csa lookup`, never a quoted-text anchor.
- Every record has a `Note:` of at most 40 words, written for the Word comment.
- Run `csa check-change <N>` before handing a change file over, and fix every ERROR.

## Subsections

A section too big for one run can be worked one subsection at a time: `csa author 6.4`, `csa approve 6.4`, `csa apply 6.4 --until-done`, `csa review 6.4`, `csa cleanup 6.4`, `csa status 6.4`, `csa pipeline 6.4`.

- The number is the stable-ID numbering (`@H6.4`, as `csa lookup` prints it), not the number printed in the document.
- When the prompt has `SUBSECTION=<n.m>`, work only on that heading and everything under it (stable IDs starting `@H<n.m>`). Other subsections of the section are out of scope; a finding for one of them is an open question, not an edit.
- The change file is the labelled file in `CHANGE_FILE`: `reviews/ChangesCSA_<App>_Section<N>_<n-m>.md` (dots as dashes). Header: `**Section:** <N> - <section title> (subsection <n.m> <subsection title>)`.
- Edit IDs stay `S<N>-E<n>` and number on from every change file of section N, labelled or not, so IDs never collide.
- Run-state is per change file (`run-state/current-state-assessment-document-section-<N>_<n-m>.md`); the authoring run-state is `csa-change-authoring-section-<N>_<n-m>.md`.
- Pass the subsection to the checks: `csa check-change <n.m>`.

## Word comments

- The framework writes each comment from `Note:` as `<Note> (Ref S<N>-E<n>; evidence E-nnn, ...)`, with author and initials from `.agents/cli.yaml` (Wenzel Joubert, WJ). Do not hand-write or extend comments.

## Tracked changes and human gates

- The framework applies every approved edit as a Word tracked change. Do not turn this off unless Wenzel asks in that run.
- Two gates are for Wenzel only, never an agent: `csa approve <N>` before apply, and reading the tracked changes in Word before `csa cleanup <N>`.
- `csa apply` refuses a record that changed after approval. Never edit an approved record; ask for re-approval instead.
- There is one working DOCX per project, edited in place. No versioned copies unless Wenzel asks. The framework backs it up before every batch.

## Stopping

- Stop after the unit of work you were asked for (one section, one batch, one skill) and report. Do not start the next one.
- If something cannot be done safely, record an open question or report `BLOCKED` with the reason. Do not guess.

## Learnings

- Read your agent's playbook if it has one. Add new lessons to its learnings inbox, one short entry each. Never rewrite old entries.
