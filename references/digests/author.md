# Rules digest: author stage

Draft `reviews/ChangesCSA_<App>_Section<N>.md` for one section from Discovery Data evidence, run `csa check-change <N>` and fix every ERROR, update run-state, report, stop. `csa author` then runs the Writer pass and applies the result as tracked changes.

## Order of work

1. `csa scope <domain>` and `csa brief <N>`: copy the brief skeleton into `## Section brief` (Purpose, Requirements, B/C questions, Not here) and refine it. Never drop a scope-map question without a one-line reason.
2. `prepareDocument()` once, no `section` argument. `NOT_READY` or `WORKSPACE_NOT_REGISTERED`: stop and report.
3. Look each B/C question up with `csa ev lookup "<terms>" --brief` (two or three wordings), then `csa index`, then raw files only for what the index does not cover.
4. Before recording a question as unanswered, run `python3 -m csa_docx.gap_lookup check --workspace <WORKSPACE> --dr <N>-B2 --text "<question>"` from `.agents/framework`. Only a `NOT_FOUND` verdict makes it an open question.
5. `lookupStableId(query)` once per edit. Never hand-derive an `@H...` ID. No unique match: an open question.
6. Write `WORK_DIR/author/<N>/search-notes.md` (40 lines at most): per question `Searched:`, `Found:` (with E-ids), `Not found:`.
7. Append every finding you rely on with `csa ev append --agent csa-change-authoring-agent --context "Section <N>"`, one atomic row per claim.

## Edit records

- Edit IDs `S<N>-E<n>` (administrative: `S<N>-A<n>`), numbered on from every existing change file for the section.
- Propose a change only when evidence shows what is wrong, missing or outdated. No wording or style opinion. Never change owner, reviewer, approver or signature fields. Structural changes go under `## Open questions`.
- `Why` names the evidence file, host and E-id(s). `Note` is the Word comment: 40 words at most; preview with `python3 -m csa_docx.comment_text <change file>`.
- Wrong subsection: move within the file (insert first, delete second). Wrong section: `Relocation: <stable ID> -> <target>` under Open questions.

## Facts and never infer

- Each edit has a `**Facts:**` list, each line starting with the brief item it answers: `- [B3] IAMPS opens the connection from the IT side (E-003) {basis: observed; scope: HOST01, HOST02}`. `Table detail:` and `Unknown:` lines are exempt; at most one `Unknown:` line.
- Basis is `observed`, `documented` or `stated`. There is no `inferred`: a conclusion you would have to reason your way to is an `Unknown:` and an open question.
- Scope names the hosts or sites the matrix row covers; never wider.
- Text is a draft for the Writer: no evidence ID, IP address or subnet in prose. Hosts by name; the IP address only where no name was found.
- Write `## Fact audit` (`| Record | Sentence | Evidence quote | Basis | Scope |`), one row per Text sentence. A sentence with no quote is deleted or becomes the unknown.

## Errors to fix

`csa check-change` ERRORs, including FACT_*, SCOPE_*, UNSUPPORTED_QUALIFIER, UNTAGGED_FACT, BRIEF_ITEM_UNANSWERED, NO_BRIEF, BRIEF_NO_QUESTIONS, and TERM_LINT findings. NO_SEARCH_NOTES is a warning: write the note.

## Open the full file only when

- `csa-core-rules.md`: an error code or rule above is unclear.
- `csa-change-authoring.md`: `EDIT_MODE=editorial`, or a Relocation or structural case is not covered here.
- `csa-writing-style/SKILL.md`: `check-change` reports PROSE_LINT structure warnings.
- `csa-evidence-matrix/SKILL.md`: a `csa ev` command fails.
- `csa-change-authoring-playbook.md`: a topic has no evidence and you need the evidence-to-topic mapping.
- `.agents/references/authoring-reference.md`: batch limits, run-state or the output format.
