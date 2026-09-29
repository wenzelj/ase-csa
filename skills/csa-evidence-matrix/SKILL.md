---
name: csa-evidence-matrix
description: Matrix-first evidence lookup and append-only recording for the Current State Assessment pipeline. Use whenever a CSA agent (change-authoring, document, change-review) needs a technical fact about the assessed system - look up csa-work/evidence-matrix.csv first, search Discovery Data only if the matrix has no answer, then append the new finding back to the matrix.
---

# CSA Evidence Matrix (read + write skill)

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

The evidence matrix is the shared memory of what has already been established about the assessed system. It lives at `<work_dir>/evidence-matrix.csv`, where `<work_dir>` is the active project's `work_dir` from `csa-context/PROJECTS.yaml` (or the `WORK_DIR` supplied directly) -- never assume IAMPS. For example, IAMPS's matrix is at:

```text
/Users/wenzel/Work/ASE/CurrentStateAssessments/IAMPS/06 IAMPS/csa-work/evidence-matrix.csv
```

and UTC DTC's is at its own `csa-work/evidence-matrix.csv` under its project root. Always resolve this path per-project; writing one project's findings into another project's matrix is a data-integrity error.

**Built-in guard:** `evidence_matrix.py` validates the resolved `--workspace` (or cwd, if `--workspace`/`CSA_WORKSPACE` was omitted) against `csa-context/PROJECTS.yaml` before touching any file, for every command (`lookup`, `get`, `stats`, `verify`, `append`). If the workspace is not a registered project's `project_root` (or a path under it), the command fails loudly with `"status": "ERROR"` and a `WORKSPACE_NOT_REGISTERED` message instead of silently reading or writing the wrong project's matrix -- always pass `--workspace <this project's project_root>` explicitly rather than relying on the cwd default.

Each row is one atomic claim with a stable `E-nnn` ID, an evidence class, its source, and an exact excerpt. This skill is how the three pipeline agents read it and write to it, so a fact found once is never searched for twice and every claim can be traced to a source.

Agents that use this skill: **csa-change-authoring-agent**, **csa-document-agent**, **csa-change-review-agent**. The evidence-investigator and orchestrator agents write to the same file under their own rules; this skill is compatible with them.

## Purpose separation: matrix vs analysis vs CSA

Three artefacts, three jobs. Keep them separate and do not let one become the other.

- **Evidence matrix** (`csa-work/evidence-matrix.csv`): records, organises, locates and traces the evidence used during the assessment. One atomic claim per row, with an E-id, its source, and an exact excerpt. This is the *input and traceability mechanism*.
- **Analysis**: correlates the evidence and determines what it tells us about the application and system. This is the reasoning step (see `csa-section-writer/references/current-state-reasoning.md`).
- **Current State Assessment** (the DOCX): presents a technically accurate, understandable description of the application and its current IT/OT operating environment. This is the *current-state view derived from the evidence*.

The matrix is not the structure or subject of the CSA. The CSA body never takes the evidence as its subject; it states the system, and the matrix sits behind it as the traceability record. A reader of the CSA should be able to trace any material statement to an E-id in the matrix without the matrix being visible in the prose.

## Rows are about hosts, not source rows

Each row's claim names the host(s), role or application it is about, with every host name written in full. A source row that lists many hosts (a MECM collection, a GPO scope, an agent report) becomes one row per group of hosts that share the value, not one row per source row. The source's own row, collection or sheet key goes in `page_or_location`. `csa hosts build` derives `hosts/evidence_hosts.csv` (evidence ID -> hosts) from the claims, and `csa hosts show <HOST>` lists the evidence for a machine; a row that names no host counts as system-wide.

## The rule: matrix first, then data, then write back

See "Evidence matrix first" in .agents/csa-core-rules.md. The five steps:

```text
1. LOOKUP   -> search the matrix for the question
2. JUDGE    -> does a returned row answer THIS question for THIS host/date?
                 yes -> use it, cite its E-id, STOP searching for it
                 no  -> continue
3. SEARCH   -> search Discovery Data (only the part the matrix did not answer)
4. APPEND   -> record every finding, including NOT_FOUND with the scope searched
5. CITE     -> quote the E-id(s) in your Why / comment / report
```

Step 3 uses the discovery index first where the project has one (`csa-discovery-index` skill), then raw files only for what the index reports as not indexed.

## Script

One stdlib-only helper (Python 3.8+; `python3` or `/opt/homebrew/bin/python3.14` both work). All output is JSON. Exit code `2` means rejected and nothing was written.

```text
S=".agents/skills/csa-evidence-matrix/scripts/evidence_matrix.py"
```

Read:

```text
python3 "$S" lookup "<short keyword phrase>" [--area <csa_area>] [--status VERIFIED,INFERRED] [--host <substring>] [--limit 5]
python3 "$S" get E-002 E-019
python3 "$S" stats
python3 "$S" verify
```

Write (append-only):

```text
python3 "$S" append --agent <your-agent-name> --context "<section / edit id>" --rows-file rows.json
python3 "$S" append --agent <your-agent-name> --context "<...>" --row-json '{...}'
python3 "$S" append ... --dry-run          # validate and preview IDs without writing
```

### How to query

Use a short phrase of the topic plus the concrete names that matter: hosts, ports, services, file names. Good: `RabbitMQ listening ports application hosts`, `NTP source time.windows.com`, `CSFalconService ROKPRDAMP101`. Bad: a whole sentence copied from the document. Use `--host` to restrict to one host, `--area` to restrict to one CSA area. Run two or three differently-worded queries before concluding the matrix has no answer. Agents use --brief (and get --brief) by default; drop it only to read a row's full excerpt.

### What the verdict means

| verdict | meaning | what to do |
|---|---|---|
| `LIKELY_ANSWERED` | a VERIFIED/INFERRED row covers the question | read the row; confirm host, capture date and wording match your claim; use it and cite the E-id. Do not re-search Discovery Data for it. |
| `PRIOR_NOT_FOUND` | an earlier search found nothing | read the row's `source_title` (the scope searched); search only outside that scope or in newer captures; append the result. |
| `OPEN_ON_RECORD` | a CONFLICTING/UNCONFIRMED row exists | do not present the point as settled; look for deciding evidence; append the outcome citing the earlier E-id in `gap_or_action`. |
| `PARTIAL_MATCH` | related rows, none clearly answers | search Discovery Data for the remainder; append. |
| `NO_MATCH` | nothing on record | search Discovery Data; append what you find. |

The verdict is a ranking aid, not a judgement. **You** decide whether a row answers the question. A row about `ROKPRDAMP101` does not answer a question about `MKYPRDAMP102`.

## Writing rows

Append only when you have actually established something from a primary source in this run (a Discovery Data file, or the source document named in `source_title`). Do not append your own opinions, general knowledge, or claims copied from the CSA document under review.

One atomic claim per row. Put the host and capture date in the claim so it can be reused safely. Fields:

| field | rule |
|---|---|
| `csa_area` | one of the existing areas (`application_overview`, `application_architecture`, `infrastructure_and_hosting`, `network_and_connectivity`, `security_posture`, `identity_and_access`, `integrations_and_dependencies`, `operations_and_support`, `availability_and_resilience`, `backup_and_recovery`, `business_and_operational_use`) |
| `question` | the question the claim answers, phrased generically so a later lookup finds it |
| `claim` | one atomic statement, with host(s) and date/capture |
| `status` | `VERIFIED` (directly stated in an authoritative source), `INFERRED` (reasoned from verified facts - fill `inference_reason`), `UNCONFIRMED` (asserted, not supported), `CONFLICTING` (sources disagree - name them), `NOT_FOUND` (absent after a proportionate search) |
| `source_title` | `<capture folder>: <file name(s)>`, or the document title. For `NOT_FOUND`, the **scope searched** (which captures, which files) |
| `source_version` | capture timestamp / document version and date |
| `section` | topic area within the source |
| `page_or_location` | file name and command/line region, or document section/page |
| `evidence_excerpt` | the exact supporting lines, max 1200 chars. Multi-line is collapsed to ` \| `. **Never include passwords, keys, tokens or other secrets** - the tool rejects them |
| `inference_reason` | required for `INFERRED` |
| `confidence` | `high`, `medium`, `low` or empty. Nothing else - put gaps in `gap_or_action` |
| `gap_or_action` | what is missing or who must confirm. Required for `NOT_FOUND`, `UNCONFIRMED`, `CONFLICTING` |
| `review_state` | leave empty; the tool sets `pending`. Only a human changes review state |

The tool assigns the next `E-nnn`, backs the matrix up to `csa-work/backups/` before each write, keeps the file's BOM and CRLF format, skips exact duplicates, rejects bad rows as a batch, and logs every write to `csa-work/evidence-matrix-audit.jsonl`.

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

### Append-only rules

- **Never edit, renumber or delete an existing row.** If a new finding contradicts a row, append a new row (`CONFLICTING`, or a corrected `VERIFIED`) and cite the earlier E-id in `gap_or_action`.
- **Never upgrade an inference** to VERIFIED because it is plausible.
- Never fill in hostnames, addresses, versions or dates from prior knowledge.
- Record `NOT_FOUND` with the scope, so the next run does not repeat the same empty search.
- If `append` rejects a row, fix the row; do not work around the validator.
- Run `verify` if a write fails unexpectedly. It reports structural problems; do not hand-edit the CSV to fix them.

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

## Concurrency and safety

Writes take an exclusive file lock, so two agents can append at the same time without colliding. IDs are assigned under the lock. Each write makes a timestamped backup under `csa-work/backups/`.

## Known data-quality note

`verify` currently reports 6 legacy rows (E-006, E-007, E-008, E-009, E-011, E-014) whose `confidence` column holds gap text instead of high/medium/low. They are read normally and left untouched (append-only); a human can clean them.

- `review E-nnn ... --by "<name>"` - records a review in `csa-work/evidence-reviews.jsonl`.
