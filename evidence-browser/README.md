# CSA Evidence Workspace

## Add an application

Open **New application** in the left rail. Drop one application folder (or choose it with the folder picker). The folder must already contain `Discovery` and `00 Knowlege`, including the files and subfolders you want to retain. The browser uploads the entire tree into a temporary session. The folder picker cannot report empty directories; dragging the folder preserves them when the browser supports directory entries.

Review the detected files and configure the project key, scope, source paths, knowledge metadata, assessment lane and document paths, estate, sites, skills and working preferences. **Validate and preview** shows the paths and context that will be registered. **Create application** is a separate explicit action. An existing `00 Knowlege/sources.json` is retained; optional metadata must agree with it. The spelling `00 Knowlege` is the compatibility default used by the framework.

The application appears in the selector immediately after creation. Its setup page shows the next independent steps: run discovery ingest to build the index and prepare a working DOCX through the CSA document workflow. Registration itself does not index files or create an assessment document.

Use **Application setup** or **Assessment** to choose the working DOCX after registration. The browser lists DOCX files already in the application folder, or you can upload one (up to 50 MiB). The explicit selection is recorded as `working_docx` in `PROJECTS.yaml`; it does not change the DOCX content. Evidence intake remains available before indexing, while views that require an index explain the missing prerequisite in their own area.

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

## Draft answers (before V1)

While a project is at `stage: draft` (PROJECTS.yaml, the default), the rail shows **Draft answers**: ingest new data,
check for stale answers, refresh them, and answer any subsection with Claude, Codex or Evo. Each answer runs
`csa answer N --headless` as one tracked job and is written into the working DOCX as plain text. The page also
shows the recent draft changes and the open questions. The section map's author/review/cleanup workspace and the Word
review panel are hidden until the project is frozen at V1 (`Freeze at V1…` on the same page, or `csa freeze v1`).

## Evidence intake

**Evidence intake** (second in the rail) brings new data in and puts it to use, in five steps. Nothing on this page
changes the working DOCX.

1. **Bring in new data** runs `csa ingest`. The index build records what came in (`csa-work/intake/latest.json`):
   new, changed and removed files, plus the files the index cannot read (.doc, .pptx, images), listed with a request for
   a text or PDF copy.
2. **Turn new documents into evidence** runs `csa intake` with Claude, Codex or Evo as one tracked job. Its output is
   streamed into the job panel. The evidence agent (Intake mode in `csa-evidence-investigator-agent.md`) reads the new documents and appends
   source-checked rows through `evidence_matrix.py append` and graph items through `graph_store.py`. Its summary is
   `csa-work/intake/<id>.evidence.md`.
3. **Check open questions** runs `csa gap-check` (no model): every question in `csa-work/draft/open-questions.md` is
   looked up in the matrix and the index. What the index finds is added to `csa-work/intake/leads.jsonl`, not the
   evidence matrix. Evidence IDs, related evidence IDs and lead IDs are kept separate.
   Result: `csa-work/intake/gap-check-latest.json`.
4. **Settle what was found**: *Resolve and update answers* runs the evidence investigator over every lead's
   original source. It reuses the gap-check record already displayed on the page and streams framework progress from
   the selected model into the job panel. Supported findings become
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
