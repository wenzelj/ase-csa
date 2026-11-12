# csa-work-v2 Storage Directory Documentation

This documentation explains the structure of the `csa-work-v2/` storage system that replaces the scattered files in `csa-work/`.

## Purpose

The csa-work-v2 system consolidates all CSA data into a single SQLite database (`csa.sqlite`) with a small CRUD API, replacing:
- `evidence-matrix.csv`
- `hosts/*.csv`, `graph/*.csv`, `intake/*.json`
- `discovery-index.sqlite`
- Scattered JSON and CSV files

## Directory Structure (per project)

When a project switches to v2 (S590), it creates:

```
<PROJECT_ROOT>/csa-work-v2/
├── csa.sqlite              # Single SQLite database with all tables
├── backups/                # Timestamped pre-mutation copies of csa.sqlite
├── exports/                # Human-readable CSV/Markdown exports for Excel review
│   ├── evidence.csv       # All evidence rows (for migration comparison)
│   ├── hosts.csv          # Host inventory
│   ├── addresses.csv      # IP addresses with scope
│   ├── services.csv       # Services per host
│   ├── flows.csv          # Network flows
│   ├── leads.csv          # Intake leads
│   ├── graph-nodes.csv    # Graph nodes
│   ├── graph-edges.csv    # Graph edges
│   ├── intake-files.csv   # Intake file status
│   ├── REPORT.md          # One-page summary of the database
│   └── hosts/<HOST>.md    # Per-host Markdown cards (on-demand)
├── cards/                  # Section cards (copied from csa-work/cards/, unchanged)
└── sections/               # Section source files (copied from csa-work/sections/, unchanged)
```

## Data Locations

- **Database:** `<PROJECT_ROOT>/csa-work-v2/csa.sqlite`
- **Exports:** `<PROJECT_ROOT>/csa-work-v2/exports/`
- **Cards:** `<PROJECT_ROOT>/csa-work-v2/cards/` (copied, not symlinked)
- **Sections:** `<PROJECT_ROOT>/csa-work-v2/sections/` (copied, not symlinked)

The `backups/` directory is auto-populated by the `tx()` context manager before each write operation.

## Data Flow

### 1. Migration (S586)
```bash
python3 -m csa_docx.v2migrate --project-root <ROOT> --v2-dir <PROJECT_ROOT>/csa-work-v2/
```
- Reads all old CSVs and JSON files from `<ROOT>/csa-work/`
- Builds the SQLite database with all tables
- Copies `cards/` and `sections/` directories (one-time copy)
- Creates exports for human review

### 2. Daily Operations
All CSA commands (`csa status`, `csa ingest`, `csa answer`, etc.) use the v2repo API:
```python
from csa_docx.v2repo import Repo

r = Repo("csa-work-v2/csa.sqlite")

# All writes must go through tx()
with r.tx():
    r.hosts.create("H1", role="server")
    r.evidence.create(..., ...)
    r.graph.refresh()
```

### 3. Exports (on-demand)
Run `csa v2 export --table evidence --out csa-work-v2/exports/evidence.csv` when you need fresh data. Exports are snapshots, not live views.

## API Usage Pattern

All code accesses the database via:

```python
from csa_docx.v2repo import Repo

r = Repo("<path>/csa.sqlite")

# Use transaction context manager for all writes
with r.tx():
    # Host operations
    r.hosts.create("H1", role="server", site="Site A")
    
    # Evidence operations
    r.evidence.create(claim="...", source_title="...", ...)
    
    # Graph refresh (read-only derived tables)
    r.graph.refresh()

# Read without transaction
nodes = r.nodes()
edges = r.edges()

# Review events
events = list(r.review_event().list())
```

## Important Rules

1. **Never write directly to csa.sqlite** — always use `r.tx()` context manager
2. **Exports are snapshots**, not live database views. They don't auto-refresh on mutations.
3. **cards/ and sections/ are copies**, not symlinks or database tables. They must exist for the DOCX pipeline.
4. **backups/** is auto-populated by `tx()` before each write operation. Timestamped copies prevent data loss.
5. **The discovery index mirror** (`discovery-index.sqlite`) is optional in v2. Falls back to plain-text search if missing.

## Rollback Procedure

If you need to revert to the old `csa-work/` path:

```bash
# Restore PROJECTS.yaml if edited (framework does this automatically on failure)
git -C .agents checkout -- .agents/csa-context/PROJECTS.yaml

# csa-work/ remains untouched, so projects immediately work with old path
# csa-work-v2/ can be left in place (inert) or deleted manually
```

## Testing

Run all v2 framework tests:

```bash
cd /Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/framework
python3 -m pytest -q csa_docx/tests/test_v2*.py
```

Expected result: **111 tests pass** (as of S586 migration).

## Related Files

- `.agents/framework/csa_docx/v2repo/` — Repository implementation and API
- `.agents/framework/csa_docx/v2migrate.py` — Migration CLI
- `.agents/framework/csa_docx/v2_ingest.py` — Ingest rewrite
- `.agents/bin/csa` — Main script with route handlers for all commands

## Version History

- **S582:** Created schema, transaction management, basic CRUD skeleton
- **S583:** Added full hosts/evidence CRUD with review events
- **S584:** Implemented graph refresh as derived view
- **S585:** Added intake, leads, gap-checks tables and API
- **S586:** Migration script from old csa-work/ files to v2 database
- **S587:** On-demand exports (CSV, Markdown cards, summary report)
- **S588:** Batched intake processing (5 files per model session)
- **S589:** Rewrote csa ingest commands for v2repo
- **S590:** Switch script to point projects at csa-work-v2/

