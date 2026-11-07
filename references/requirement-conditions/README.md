# Requirement conditions

One JSON file per requirement family (for example `storage-data-transfer.json`). Each file maps a requirement ID to the
conditions its text sets and the logic that joins them:

```json
{"requirements": {"SEP-STOR-01": {"conditions": [{"id": "C1", "text": "..."}], "logic": "C1 and (C2 or C3)",
                                  "reviewed": false, "basis": "split from the requirement text"}}}
```

- `logic` uses the condition IDs with `and`, `or`, `not` and brackets.
- `reviewed` is set to true by the project owner once the split is checked. The framework uses an unreviewed entry, and
  says so on the card.
- A requirement with no entry has one condition: its own text.

`csa_docx/conditions.py` reads these files. `rating_range` turns the condition results into the ratings a judgement may
choose. Generic: requirement IDs and wording only, never project facts.
