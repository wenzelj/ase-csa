# CSA Evidence Workspace

## Add an application

Open **New application** in the left rail. Drop one application folder (or choose it with the folder picker). The folder must already contain `Discovery` and `00 Knowlege`, including the files and subfolders you want to retain. The browser uploads the entire tree into a temporary session. The folder picker cannot report empty directories; dragging the folder preserves them when the browser supports directory entries.

Review the detected files and configure the project key, scope, source paths, knowledge metadata, assessment lane and document paths, estate, sites, skills and working preferences. **Validate and preview** shows the paths and context that will be registered. **Create application** is a separate explicit action. An existing `00 Knowlege/sources.json` is retained; optional metadata must agree with it. The spelling `00 Knowlege` is the compatibility default used by the framework.

The application appears in the selector immediately after creation. Its setup page shows the next independent steps: run discovery ingest to build the index and prepare a working DOCX through the CSA document workflow. Registration itself does not index files or create an assessment document.

Use **Application setup** or **Assessment** to choose the working DOCX after registration. The browser lists DOCX files already in the application folder, or you can upload one (up to 50 MiB). The explicit selection is recorded as `working_docx` in `PROJECTS.yaml`; it does not change the DOCX content. Evidence intake remains available before indexing, while views that require an index explain the missing prerequisite in their own area.

A `.dotx` is a template, not a working document. **Create a DOCX from a DOTX template** lists templates in the application folder and the shared `CSA Template` folder. The browser creates a new DOCX with the framework's `new_csa.py`, checks it against the chosen template, then records it as the working document. It refuses to overwrite a DOCX or register an incompatible template result. The original DOTX is read only. The current RMS-local `Current_State_Assessment_Template.dotx` passes conversion and template checking with expected draft warnings.

To move an old assessment into the new working DOCX, use **Old assessment to migrate from** to set a different existing DOCX as `legacy_docx`. Then run `csa -p <key> move --prepare` and `csa -p <key> move --all`. The old source document remains read only.

Uploads use 4 MiB request chunks and the per-file and total limits reported by `/api/new-application/defaults`. The interface reports validation or transfer failures while retaining the selected folder for retry.

Local evidence inventory, matrix-first search, source preview and reviewed evidence append for IAMPS, UTC DTC and TETRA.

## Build

```sh
cd .agents/evidence-browser/frontend
npm install
npm run build
```

Python dependencies can be installed in an isolated environment with `uv sync`. If `uvicorn` is not available, the launcher uses the included loopback-only server and does not download anything at startup.

## Run

```sh
csa -p iamps-08 browse
csa -p utcdtc browse
csa -p tetra-reveloc browse
```

The server accepts loopback connections only. Add `--no-open` for a server-only launch or `--port 9000` to select another local port.

## Hosts and connected devices

**Hosts & connected devices** in the left rail is the one place to find what the project's evidence names and to identify what it cannot. It has four separate views, and a row is never moved between them by guesswork:

| View | What it holds |
| --- | --- |
| Application hosts | Hosts in the host register (`hosts/hosts.csv`) that are part of the application under assessment. |
| Connected devices | Devices an assessor has identified (printers, switches, appliances and the like). They are **not** application hosts. |
| Unidentified addresses | Addresses seen in captures that no register host or device owns (`hosts/addresses.csv`). |
| Conflicts | An address claimed by two devices, or claimed by a device while a register host owns it. Nothing is resolved by guess. |

An observed connection (what a capture saw), a configured service (what a host is set to use, such as DNS or time) and a documented dependency (a verified statement) are labelled separately. None of them is a migration dependency on its own.

### Identify an unknown IP

1. Open **Unidentified addresses** and select the address. The detail shows the direction, ports, processes and evidence behind it.
2. Choose **Identify as a new device** (or **Attach to an existing device** if the device is already recorded). Give it a name, type, operational role, owner, site or zone, and classification.
3. The browser shows a **before and after** table for every alias change. Read it before confirming: it says what the address resolves to now and what it will resolve to after saving. An address a register host already owns, or another active device holds, is blocked with the reason.
4. Save. Only the connected-device register changes (`hosts/connected_devices.csv`, `hosts/device_addresses.csv`) with a timestamped backup and an audit entry in `hosts/device-audit.jsonl`. Generated host files, the evidence matrix, the graph, captures and the DOCX are never edited here.

Every edit sends the revision the editor last read. If someone else saved first, the browser says so and keeps what you typed; use **Use latest revision**, check the current values, then save again.

### Confirmation, source and provenance

A device is `unidentified`, `proposed`, `confirmed` or `disputed`. **Confirmed** needs a cited source (a document, register or capture reference) or a dated owner confirmation. That basis is stored as the device's provenance, with the reviewer and the date. Confirming a device never adds a VERIFIED evidence row: it is an assessor decision recorded in the register, not evidence from a capture. Only a confirmed, active device labels an observed peer in the Host network, System explorer and `endpoints.csv`; proposed, disputed and retired devices leave the address unidentified.

### Retire and restore

**Retire** removes the identification and its address aliases from the register after an explicit confirmation. It does not remove the observed connection, the capture or the evidence: the address goes back to the unidentified list. The row stays in the register with its history, and **Restore** (with *Show retired devices* ticked) brings it back. An address can be reused by another device later; only active aliases resolve.

### Application host or connected device

Creating, editing or confirming a device never makes it an application host. If a device proves to be one, the conversion is a separate, deliberate action: preview it (the plan names every collision with an existing host, address or decision), then apply it with the preview's ID, the device revision, a source and the operator. It records a decision in `hosts/host_scope.csv`; the next `csa hosts build` registers the host as in scope. The decision can be reversed with a reason, and the device and its aliases stay in the register throughout.

### Rebuilds and reviewed endpoint labels

`csa hosts build` regenerates `hosts.csv` and `addresses.csv` but never writes the connected-device register, so decisions, revisions and the audit log survive every rebuild. After a rebuild, a confirmed device's observed addresses move out of `addresses.csv` into `hosts/device_peers.csv`, which carries the device ID, revision and provenance. If a new capture shows that a register host now owns an address a device claims, the host keeps it and the clash is reported; the saved identity is not overwritten.

Reviewed `endpoints.csv` labels can be brought in with `python3 -m csa_docx.connected_devices import-endpoints <project root>` (run from `.agents/framework`). The dry run lists what would be created and what needs a person (host-owned, uncited, conflicting or ambiguous rows); adding `--apply --plan-id <id> --operator <name>` creates them as `proposed` devices, and running it again creates nothing. `endpoints.csv` is only read.

## Draft answers (before V1)

While a project is at `stage: draft` (PROJECTS.yaml, the default), the rail shows **Draft answers**: ingest new data,
check for stale answers, refresh them, and answer any subsection with Claude, Codex or Evo. Each answer runs
`csa answer N` as one tracked interactive job in the browser terminal and is written into the working DOCX as plain text. The page also
shows the recent draft changes and the open questions. The section map's author/review/cleanup workspace and the Word
review panel are hidden until the project is frozen at V1 (`Freeze at V1…` on the same page, or `csa freeze v1`).

## Evidence intake

Interactive agent jobs launched from Evidence Browser use the terminal dock in the main window, including evidence
intake and settlement, draft answers and refresh, section authoring and review, and figure agents. The dock shows
the active job across pages. It reconnects after a page refresh while the server is still running. Terminal screen
bytes are held in bounded memory; they are not written to the job logs. A structured review result is saved for the
existing review outcome screen. Restarting the server interrupts an unfinished terminal job.

For a live macOS check, use a disposable registered project: run Claude Evidence Intake and confirm its interface,
typing, approval prompts and resizing in the dock; refresh the page and reconnect to the same job; then check the
intake report, evidence rows and graph after the CSA command exits. Repeat with a draft or section agent using another
CLI. In a separate disposable run, use Stop and confirm the child process and evidence lock are gone. This manual
check is tracked by Improvements story S559 and is separate from the synthetic tests.

**Evidence intake** (second in the rail) brings new data in and puts it to use, in five steps. Nothing on this page
changes the working DOCX.

1. **Bring in new data** runs `csa ingest`. The index build records what came in (`csa-work/intake/latest.json`):
   new, changed and removed files, plus the files the index cannot read (.doc, .pptx, images), listed with a request for
   a text or PDF copy.
2. **Turn new documents into evidence** runs `csa intake` with Claude, Codex or Evo as one tracked job. Agent prompts and output appear in the terminal dock inside Evidence Browser. The dock stays available while navigating the workspace; reopen it after a page refresh to reconnect to a running job. Stop ends the tracked process and releases its lock. The evidence agent (Intake mode in `csa-evidence-investigator-agent.md`) reads the new documents and appends
   source-checked rows through `evidence_matrix.py append` and graph items through `graph_store.py`. Its summary is
   `csa-work/intake/<id>.evidence.md`.
3. **Check open questions** runs `csa gap-check` (no model): every question in `csa-work/draft/open-questions.md` is
   looked up in the matrix and the index. What the index finds is added to `csa-work/intake/leads.jsonl`, not the
   evidence matrix. Evidence IDs, related evidence IDs and lead IDs are kept separate.
   Result: `csa-work/intake/gap-check-latest.json`.
4. **Settle what was found**: *Resolve and update answers* runs the evidence investigator over every lead's
   original source. It reuses the gap-check record already displayed on the page and shows the selected model in the browser terminal. Supported findings become
   source-checked VERIFIED evidence, irrelevant leads are marked `not_an_answer`, and a
   bounded search that still has no answer becomes a scoped NOT_FOUND row. The individual *Not an answer* and *Write
   the fact* controls remain available for recovery or manual review.
5. **Use it in the document**: the resolve operation reruns each affected subsection through Draft answers (draft
   lane) or tracked authoring (V1). The subsection links remain available for inspection and follow-up.

Routes: `GET /api/systems/{key}/intake` (snapshot), `POST /api/systems/{key}/leads/{id}/review` for lead settlement,
and `POST /api/systems/{key}/evidence/{id}/review` for actual evidence only. Jobs: `ingest`, `intake`, `gap_check`.

## Authoring decisions

The Assessment workspace uses the framework's card-first author route by default and always submits proposals with
`--no-apply`. The advanced controls can request a fresh answer, an advisory answer check, an explicit legacy run, or
an automatic/forced/skipped writer pass. None of these controls applies changes to the working DOCX.

The author ledger reads the framework answer-cache manifest, established-fact store, timing record and repair audit.
It shows which questions are reused or regenerated, where reused facts originated, why the writer ran or was skipped,
which working artifacts changed, and whether the result is current enough to enter proposal validation. Author runs
are classified as workspace writes and locked per project section; DOCX operations retain their separate document lock.

During frontend development, run the backend and Vite separately:

```sh
cd /Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/evidence-browser
uv run python -m backend.server

cd .agents/evidence-browser
uv run python -m backend.server --no-open
cd frontend
npm run dev
```

Set `CSA_AGENTS_DIR` or pass `--agents-dir` when running the patch against a separate CSA framework checkout.
