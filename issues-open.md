# CSA Open Issues Register

The single place where blocked edits, defects and recurring problems are tracked until they are closed. Agents write here (rules are in `current-state-assessment-document.md`, section "Continuous Skill Improvement And Issue Feedback Loop"). Reusable lessons go to the learnings inbox instead: `skills/current-state-assessment-document-learnings.md`. Questions only Wenzel can answer go to `needs-decision.md`.

Register started: 2026-09-21.

## How this register works

**Lifecycle:** `open` -> `investigating` -> `needs-decision` or `fixed-pending-verify` -> `closed`.

**Buckets** (triage every issue into exactly one):

| Bucket | Meaning | Who acts |
| --- | --- | --- |
| framework-defect | The framework or DocxEngine adapter behaves wrongly | Fix in code, add a regression test |
| change-record-defect | The approved change record is malformed or its locator/text is wrong (missing `**Text:**`, non-unique `Where`, locator absent from the document) | Back to the authoring agent / Wenzel |
| document-mismatch | The document, run-state or Changes Report disagrees with the record (edit already applied, target subsumed by a broader edit, stale state) | Reconcile state, do not touch the DOCX |
| environment | Interpreter, paths, permissions, execution environment (Mac Terminal vs Cowork bridge) | Update the environment note or the tooling |
| process | A gap in the workflow or documentation itself | Update the agent definitions or playbook |
| needs-decision | Only Wenzel can decide; it has an entry in `needs-decision.md` | Wenzel |

**Fingerprint:** the normalised block message plus the edit shape, for example `Anchor match count was 0` on a paragraph replace. Before adding an issue, search this file for the fingerprint. If it exists, increment `Seen`, update `Last seen` and add the run reference. Do not create a duplicate.

**Promotion ladder:** first sighting = issue only. `Seen: 2` = propose a playbook rule. `Seen: 3`, or any silent-corruption class (wrong text applied without a block), = propose a validator or test.

**Closing:** an issue closes only with one of: (a) a code fix plus a named regression test or commit, (b) a playbook rule that is linked, or (c) an explicit won't-fix with a reason. Agents may set `fixed-pending-verify` with evidence but never `closed`; Wenzel closes. Closed issues move to the Closed section at the bottom.

**Never** resolve an issue by guessing (Anchor Mismatch Rule still applies).

## Entry format

```text
### ISSUE-<nnn> - <short title>
- Status: open | investigating | needs-decision | fixed-pending-verify
- Bucket: framework-defect | change-record-defect | document-mismatch | environment | process | needs-decision
- Source: <agent or person, and run/date>
- Fingerprint: <normalised symptom>
- Where: <section, edit ID, file>
- First seen: YYYY-MM-DD | Last seen: YYYY-MM-DD | Seen: <n>
- Symptom / evidence: <what was observed>
- Action: <next step, and who>
- Decision: <DECISION-nnn in needs-decision.md, or None>
- Closes when: <evidence that would close it>
```

## Open issues

## Closed issues

None yet.
