---
name: csa-discovery-index
description: Query a CSA project's Discovery Data through a prebuilt SQLite index (structured tables across all hosts plus full-text search with file/line citations). Use when the evidence matrix has no answer and you would otherwise search raw Discovery Data files; also used to (re)build the index after new captures arrive.
---

# CSA Discovery Index (search aid, trial on UTC DTC)

The Discovery Data for a project can be thousands of files (UTC DTC: ~10,500 files, 7.7 GB). This skill replaces
"grep the raw folders" with one indexed query. The index is **a search aid, not evidence**: every result carries a
`cite` block pointing at the original file and line. You still cite the original file in the evidence matrix.

Order of use (extends `csa-evidence-matrix`):

```text
1. matrix lookup           (evidence_matrix.py lookup)        -> answered? use the E-id, stop
2. discovery index query   (discovery_index.py rows / search) -> found? append to the matrix using the cite block
3. raw files               only for what the index says it did not index (status -> not_indexed_reasons)
```

## Script

```text
X=".agents/skills/csa-discovery-index/scripts/discovery_index.py"
python3 "$X" --project utcdtc <command>
```

Through the `csa` command (preferred; resolves the project and interpreter for you):

```text
csa -p utcdtc index <command>          # same commands and options as below
```

Called directly, always pass `--project <key>` (from `csa-context/PROJECTS.yaml`). All output is JSON. Exit code 2 = error.

| command | use it for |
|---|---|
| `hosts` | which hosts were captured, when, and which capture is current (newer captures supersede older ones per host; `Archive`/`z_` folders are never current) |
| `tables [pattern]` | list structured tables (one per discovery file type, e.g. `services_inventory`, `listening_ports`, `local_admins_membership`, `firewall_rules`, `installed_software`, `windows_update_config`) with columns and host counts |
| `rows <table> [--where COL~text] [--where COL=text] [--where COL!~text] [--host H] [--cols a,b] [--distinct COL]` | cross-host questions: "which hosts run X", "who is a local admin", "which ports listen on all interfaces". `--distinct COL` returns each value with the hosts that have it |
| `search "<terms>" [--host H] [--path-like text] [--any]` | full-text search of everything indexed (all terms must appear in the same 30-line chunk unless `--any`); returns file, line numbers and matching lines |
| `sql "SELECT ..."` | read-only SQL for anything else (tables: `captures`, `files`, `rows(data JSON)`, `chunk_map`, `chunks`) |
| `status` | what was indexed, skipped and why |

Agents use --brief; raise --limit only when "more" matters to the question.

Scope defaults: **current captures only, archive excluded.** Add `--all-captures` to include superseded captures
(e.g. to compare March `tg_` with May `UTC_` captures) and `--include-archive` for archived ones.

Examples:

```text
python3 "$X" --project utcdtc rows services_inventory --where "Name~Splunk" --cols Name,State
python3 "$X" --project utcdtc rows listening_ports --distinct LocalPort
python3 "$X" --project utcdtc rows local_admins_membership --where "Name!~Administrator" --cols Name,ObjectClass
python3 "$X" --project utcdtc search "IPTPRDCCM202 8531" --host CONTROLLER36
```

## Turning a result into a matrix row

Copy `source_title`, `source_version`, `page_or_location` and `evidence_excerpt` from the result's `cite` block
into the matrix row. When a claim covers several hosts, state the host set and the number of current captures
that hold that file type (the `tables` output gives host counts - e.g. `services_inventory` exists for 12 hosts,
`listening_ports` for 42). Never claim "all hosts" from a table that only some captures contain.

Results with `source_class: derived` (e.g. `discovery_consolidated/*.md`) or analyst workbooks (`Analysis/*.xlsx`)
are secondary: use them to find the primary capture file, then cite that. Results with `superseded: true` come
from an older capture of the same host.

## What is not indexed

Binaries (DLL, EXE, DAT, W001, zips whose contents are extracted alongside), exact duplicate files (e.g. `UGL 2`
and `UTC 2` are copies of `UGL` and `UTC`), gpresult HTML/XML renderings (the text versions are indexed), and the
repeating I/O-mapping elements of large SIGMAP configuration XMLs (their structural elements - Builder, Ports,
Communication - are indexed). `status` lists every reason with counts.

## Building / refreshing

```text
python3 "$X" --project utcdtc build            # incremental: only new or changed files are read
python3 "$X" --project utcdtc build --rebuild  # from scratch
```

The index is written to `<work_dir>/discovery-index.sqlite` (UTC DTC: ~350 MB, ~45 s to build). It indexes the
parent of the project's `default_source_set` (`01 Current State AS Built`) unless `--source` is given. Rebuild after
new captures are added. If the build runs somewhere the work folder cannot host SQLite (e.g. a mounted share),
add `--stage-dir <local folder>`: it builds there and copies the finished file into `work_dir`. Queries open
the index read-only, so do not run a build while agents are querying.
