# CSA Evidence Workspace

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
