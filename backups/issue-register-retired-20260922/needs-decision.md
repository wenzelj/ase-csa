# CSA Decisions Needed

Questions only Wenzel can answer. Agents add an entry here when an issue's bucket is `needs-decision`, and link it from `issues-open.md`. Keep each question answerable in under a minute: state the options, recommend one, and say what happens if it is left unanswered.

## How this file works

1. The agent adds a `DECISION-<nnn>` entry with options and a recommended default. It does not act on the item.
2. Wenzel writes a choice in the `Answer:` line (a letter, or free text).
3. On the next run the agent reads the answered entry, applies it only as the answer states, sets `Applied:` to the date and the evidence, and updates the linked issue to `fixed-pending-verify`.
4. An answer is authority for that item only. If it requires editing an approved change record, the answer must say so explicitly; otherwise the agent reports and waits.
5. Entries with `Applied:` filled move to the Answered section at the bottom.

## Entry format

```text
### DECISION-<nnn> - <question>
- Issue: <ISSUE-nnn>
- Asked: YYYY-MM-DD by <agent>
- Context: <one or two sentences>
- Options:
  - A: <option> - <consequence>
  - B: <option> - <consequence>
- Recommended: <letter and why>
- If unanswered: <what the agent does or does not do>
- Answer:
- Applied:
```

## Waiting for an answer

