# Fixed Issues Log

Append-only log of issues that were raised to Wenzel during a run and resolved. Its only purpose is recurrence-checking: before raising a new issue, skim this file for a similar one, so we don't re-litigate (or re-introduce) something already fixed. It is not a queue and nothing here is "open" - by the time an entry is added, it is already done.

Log started: 2026-09-22. Earlier history lived in `issues-open.md` / `needs-decision.md`, retired on 2026-09-22 and kept at `backups/issue-register-retired-20260922/` for reference.

## How to use this file

**Before raising an issue:** search this log for a similar symptom (same error text, same edit shape, same file/section). If you find one, say so when you raise the new issue ("this looks like the same thing fixed on <date>: <one line>") so Wenzel has that context for the decision - do not silently treat it as already handled.

**After Wenzel decides and the fix is applied:** append one entry, in the format below, to the bottom of this file. Only log issues that were actually resolved this run - do not log something still waiting on Wenzel (that stays in the run's response, not here).

Keep entries short. No status field, no bucket, no promotion ladder - just enough to recognise the same problem next time.

## Entry format

```text
## YYYY-MM-DD - <short title>
Where: <section, edit ID, or file>
Symptom: <what was observed, one or two lines>
Fix: <what Wenzel decided and what was done>
```

## Log

