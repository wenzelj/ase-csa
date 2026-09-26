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
- General technical knowledge never fills a gap in project facts. It may explain significance, in a labelled `Technical explanation`.

## Document text

- Evidence IDs (`E-nnn`), stable IDs (`@H...`), evidence file names and status tags never appear in document text. They belong in the change record's `Why:` and, from there, the Word comment.
- Prose follows `csa-writing-style`; terms and spelling follow `australian-it-ot-terminology`.

## Change files

- One per section: `reviews/ChangesCSA_<App>_Section<N>.md`. A later correction pass may use `ChangesCSA_<App>_Section<N>_<label>.md`.
- Edit IDs are `S<N>-E<n>` (content) and `S<N>-A<n>` (administrative). Number on from the highest ID used in any change file for that section, including rejected ones (`### REJECTED S<N>-E<n>`). Never reuse an ID.
- Every `Where:` is a stable ID resolved with `lookupStableId` or `csa lookup`, never a quoted-text anchor.
- Every record has a `Note:` of at most 40 words, written for the Word comment.
- Run `csa check-change <N>` before handing a change file over, and fix every ERROR.

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
