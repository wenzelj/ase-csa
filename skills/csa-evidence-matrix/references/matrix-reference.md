# Evidence matrix: reference

Moved out of SKILL.md to keep the author's start-up reading small. Read it when you need an example row or the document and review agents' rules.

Example `rows.json` (illustrative values - always use what you actually found):

```json
[
  {
    "csa_area": "network_and_connectivity",
    "question": "Which NTP source does each host synchronise from?",
    "claim": "ROKPRDAMP101 synchronises from ROTPRDSRV122.internal.qr.com.au; time.windows.com is a Pending secondary peer (capture 2026-04-29)",
    "status": "VERIFIED",
    "source_title": "IAMPS_discovery_ROKPRDAMP101_20260429T023652Z: 03_time_status.txt",
    "source_version": "capture 2026-04-29T023652Z",
    "section": "time synchronisation",
    "page_or_location": "03_time_status.txt, w32tm peers",
    "evidence_excerpt": "Peer: ROTPRDSRV122.internal.qr.com.au State: Active | Peer: time.windows.com State: Pending",
    "confidence": "high"
  },
  {
    "csa_area": "security_posture",
    "question": "Are endpoint/monitoring agents present on MKYPRDAMP102?",
    "claim": "No service or installed-software inventory exists for MKYPRDAMP102 (capture 2026-03-17), so agent presence is not established",
    "status": "NOT_FOUND",
    "source_title": "tg_discovery_MKYPRDAMP102_20260317: all 13 files; no services/software inventory collected",
    "gap_or_action": "Collect services and installed-software inventory from MKYPRDAMP102"
  }
]
```


## Per-agent use

**csa-change-authoring-agent** (reads and writes): see "Evidence Matrix First" in its agent file.

**csa-document-agent** (reads; writes only when it verifies a fact)
- The approved change file remains the only source of edits. This skill never changes what is applied.
- After a batch, run `lookup` for each applied edit whose text asserts a technical fact. Report in the completion report under `Evidence check`: `supported (E-nnn)`, `no evidence on record`, or `contradicted by E-nnn`. A contradiction is reported, never a reason to alter or skip an approved edit.
- If you searched Discovery Data to settle a point, append what you found.

**csa-change-review-agent** (reads; writes only when it verifies a fact)
- Verifying the DOCX against the change file is unchanged. For factual claims in the reviewed text, `lookup` and compare. A matrix row is a lead, not proof: when you rely on it for a factual finding, open the cited source file and confirm.
- A claim contradicted by VERIFIED evidence is a finding (`P2 MEDIUM` unless the change file itself cites the wrong evidence, then `P1 HIGH`). A claim with no evidence anywhere is an `Evidence gap` note.
- If you searched Discovery Data, append what you found.
- The matrix is a working evidence file, not source evidence or the DOCX; appending to it does not breach the review agent's read-only rule.


## Known data-quality note

`verify` currently reports 6 legacy rows (E-006, E-007, E-008, E-009, E-011, E-014) whose `confidence` column holds gap text instead of high/medium/low. They are read normally and left untouched (append-only); a human can clean them.

