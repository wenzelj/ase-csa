# CSA Agent Run State

This directory is reserved for resumable agent checkpoints.

The Current-State-Assessment-Document Agent writes:

```text
current-state-assessment-document-section-<SECTION>.md
```

The C-S-A-Change-Review Agent writes:

```text
csa-change-review-section-<SECTION>.md
```

Each file records the active document, change file, selected batch, completed IDs, blocked IDs, validation evidence, next ID, and latest status so a later run can continue safely after compaction, interruption, or a no-progress stop.
