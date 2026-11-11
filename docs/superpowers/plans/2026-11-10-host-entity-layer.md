# Host Entity Layer (piece 1, Identity slice) Implementation Plan

**Superseded implementation direction, 11 November 2026:** Wenzel requested a simpler database refresh and editing model. Use [the revised plan](2026-11-11-simple-host-data.md) before implementing or dispatching the stories below. This document is retained for its capture findings and detailed test cases.

**Historical status:** Approved on 11 November 2026 before Wenzel simplified the direction later that day. Not started; do not implement these tasks as written.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load every structured capture row into host-scoped entities in `model.sqlite`, derive host properties and dependencies from them, and prove the Identity slice (accounts, groups, memberships, domain controllers) is complete and correct for all 19 TETRA hosts.

**Architecture:** Declarative map files (`references/entity-maps/*.json`) turn capture tables into `entity` rows, reading every current capture file including ones the index marked duplicate. Rule files derive `host_property` rows (keeping today's 74 setting names) and `dependency` rows. A `csa entities` command builds and shows them. Derived tables only; the old extractors keep running until parity is shown.

**Tech Stack:** Python 3.14 (`.agents/.venv`), sqlite3, pytest. Code in `.agents/framework/csa_docx/`, CLI verb in `.agents/bin/csa`.

**Spec:** `.agents/docs/superpowers/specs/2026-11-10-host-entity-layer-design.md`

**Part B, editing and the Host screen (spec section 17):** Tasks 11 to 16. Entities must be easy to edit: assessor input is a durable overlay with a basis and source reference, and the Evidence Browser gets a Host screen to look a host up and add or edit information. Part A (Tasks 1 to 10) is the Identity slice. Part B can start once Tasks 6 and 8 are done and may run alongside Tasks 9 and 10.

**Part C, data management foundations (spec sections 14.1 to 14.3 and the read-only part of 14.8):** Tasks 17 to 21, and "Part C" additions inside Tasks 1 to 10. They add the capture manifest and collector profiles, no silent absence (`unparsed`, `suspect`, sentinels and probes), data releases with lineage, and `csa data status | diff`. The plan is not built yet, so the additions are written into the tasks they change.

**Build order:** 1, 2, 17, 3, 4, 18, 5, 6, 19, 7, 20, 8, 21, 9, 10, then Part B (11 to 16). A task's `Consumes` line is the dependency rule.

**Stories:** `improvements/stories/S560` to `S581` implement this plan. Part A: S560 to S570 (Task 9 is split into S568 known values and S569 parity; Task 10 is S570, a human decision). Part B (Tasks 11 to 16): S571 to S576 (S576 is a human walkthrough). Part C (Tasks 17 to 21): S577 to S581. Part C also amends S560 to S568 and S570. Run them with `improvements/tools/run-story.sh` or read `python3 improvements/tools/story.py next`.

## Global Constraints

- Current captures only: `captures.archived = 0 and superseded_by is null`. Keep `capture_utc` on every row.
- Read every current capture file for each host, including `files.status = 'duplicate'`: copy the rows of `files.dup_of`, credit them to this host's own file, `origin = 'copied'`.
- Dates are never guessed: keep the raw string, store ISO only when unambiguous (day over 12, or a month name), otherwise flag `ambiguous`.
- States of a property: `value`; `none evidenced` (the source file was captured, the parser is trusted, and it shows none); `not captured` with a `reason` of `not_collected` (the capture's collector version never writes that file), `missing` or `collector_error`; `suspect` (raw text hints at data the parser did not return); `unmapped`. NOT_FOUND never becomes a stated absence, and `suspect` is never worded as absence.
- Nothing is silent: a source file with content that yields no entities is ledger `unparsed`, not `empty`; a probe hit with an empty property is `suspect`; a capture from an unknown collector never claims `not_collected`.
- Every build writes one `data_release` and keeps entity history; `release_first` and `release_last` survive rebuilds.
- Collector version comes from `90_run_summary.txt` (UTF-16 without BOM in the July captures, UTF-8 in the October ones), falling back to the file set. Verified: July is `Discovery_Windows_Controlled_REVELOC.ps1` version `v18-safe`; October is `Discovery_Windows_Controlled_REVELOC_AllServers_v3.ps1`, wrapper `TETRA-REVELOC-TGOIP-AllServers-v2-low-impact`, baseline `Default-v4-low-impact`. The October capture has 24 files the July one lacks (for example `13_dns_client_cache`, `42A` to `42E`, `85*`, `88A`, `88B`) and lacks 19 the July one has (for example `61_gpresult_verbose`).
- Maps and rules are generic (capture formats and classification), never project facts. Project extensions go in `csa-context`.
- Derived tables are dropped and rebuilt; a build that makes any kind lose rows is refused unless that kind is named in `--allow-shrink`.
- Do not change existing extractors, `observation`, or `host_settings` in this plan. Back up any shared framework file before editing it (`<name>.bak-<date>-<tag>`).
- Run tests from `.agents/framework`: `../.venv/bin/python -m pytest csa_docx/tests -q`. Baseline: 1 failure, `test_doc_spec.py::test_every_part_of_the_template_is_classified_by_structure`, present before this work.
- Commits stage only the files named in the task; the user chooses the branch.
- Part B: captured attribute values are never edited. Assessor knowledge is an overlay (`hosts/entity_edits.csv`, `hosts/entity-audit.jsonl`) with `basis_type` (`document`, `interview`, `site_visit`, `other`) and a `source_ref`, always worded `stated`, never `observed`.
- Part B: a build never drops or edits the overlay; the shrink guard covers it. Every change checks the expected revision, takes the lock, writes atomically and appends to the audit file.
- Part B: edits attach to host, kind and key (key lower-cased), not to an entity id, so they survive a re-capture.
- Part B: backend tests run from `.agents/evidence-browser` with the system `python3 -m pytest -q tests/<file>` (the framework venv lacks fastapi: 16 of 26 `test_assets.py` tests fail there). Frontend: the repo has vitest-style static-markup tests but no runner and no DOM testing library, so Task 14 adds them (`npm test`). Follow the existing Assets page and `connected_devices.py` patterns for errors, revisions and styling.

## Review Focus

1. A duplicate file whose original host is not a current capture: copied rows must still load (the original's rows are read by `dup_of`, not by host).
2. A capture whose mapped column is renamed (collector version): the source is `failed` in the ledger, never silently empty.
3. The same account written `SrvAdmin` and `srvadmin` on different hosts: keys compare case-insensitively, the original spelling is kept as label. A domain-qualified name (`INTERNAL\srvadmin`) is a different principal and stays a different key.
4. A host captured twice (older capture superseded): the older capture must not add entities or double counts.
5. Two rows with the same key in one file (for example two services of the same name): both load, with different ids.

Part B adds four more, with a test each (Tasks 11 to 15):

6. An edit whose target entity the newest capture no longer lists is kept and shown as `orphaned`, never deleted or applied silently.
7. Two browser tabs edit the same row: the second gets the stale-revision error and keeps its typed text; nothing is lost.
8. A pasted table with a wrong header, a duplicate key or 500 rows is rejected whole with row and column errors; nothing is written.
9. A person tries to change a captured attribute (for example `Enabled`): it is refused with a message that says to annotate or dispute instead.

Part C adds five more, each with a test:

10. A run summary encoded as UTF-16 without a BOM is decoded, not read as mojibake.
11. A capture from an unknown collector must never be labelled `not_collected`.
12. A probe hits in a file the map does not read: reported as `suspect` for the property that names that probe, not ignored.
13. Two builds of unchanged data give the same release hashes and an empty diff, and `release_first` does not move.
14. An accepted suspect stays accepted across rebuilds and does not return.

---

## File Structure

| File | Responsibility |
|---|---|
| `csa_docx/entity_maps.py` (create) | Map schema, validation, loading, value typing, date parsing |
| `csa_docx/entity_store.py` (create) | `model.sqlite` tables for entity, entity_source, host_property, dependency; ids; shrink guard |
| `csa_docx/entity_loader.py` (create) | Index to entities: table mode, text mode, duplicates, ledger |
| `csa_docx/entity_properties.py` (create) | Rule files to `host_property` rows with the five states and reasons |
| `csa_docx/entity_dependencies.py` (create) | Dependencies and the application rollup |
| `csa_docx/entity_cli.py` (create) | `build`, `status`, `host`, `show`, `coverage`, `deps` |
| `references/entity-maps/*.json` (create) | Identity maps (section 5 of the spec) |
| `references/entity-properties/identity.json` (create) | Identity property rules |
| `bin/csa` (modify) | `cmd_entities` verb, same pattern as `cmd_model` (line 3769) |
| `CSA-COMMANDS.md` (modify) | Document `csa entities` |
| `csa_docx/tests/test_entity_*.py` (create) | One file per module, plus known-value tests |
| `csa_docx/entity_captures.py` (create, Part C) | Run summary reader, collector detection, `capture` rows, profile generator |
| `references/collector-profiles/*.json` (create, Part C) | The files each collector version writes, and how to detect it |
| `csa_docx/entity_probes.py` (create, Part C) | Sentinels, probes, `suspect`, accepted-suspect reviews |
| `csa_docx/entity_release.py` (create, Part C) | `data_release`, entity history, `supersedes`, release diff |
| `csa_docx/data_cli.py` (create, Part C) | `csa data status | diff` |
| `csa_docx/entity_edits.py` (create, Part B) | The durable edit store: add, annotate, state, retire, restore, audit |
| `csa_docx/entity_overlay.py` (create, Part B) | Merges the edit store into `entity_effective` |
| `evidence-browser/backend/host_entities.py` (create, Part B) | Host lookup, host page, effective entities and edit endpoints |
| `evidence-browser/frontend/src/components/HostPage.tsx`, `EntityTable.tsx`, `EntityForm.tsx`, `PasteImport.tsx`, `host-page.css` (create, Part B) | The Host screen and its editing |

---

### Task 1: Map schema, typing and date parsing

**Files:**
- Create: `csa_docx/entity_maps.py`
- Test: `csa_docx/tests/test_entity_maps.py`

**Interfaces:**
- Produces:
  - `@dataclass EntityMap`: `name: str`, `mode: str` (`"table"` or `"text"`), `source: str` (index table name, or parser name in text mode), `file: str` (capture file name, e.g. `"44_local_users.txt"`), `kind: str`, `key: list[str]`, `label: str`, `attrs: dict[str, dict]` (`{"col": str | list[str], "type": str}`), `const: dict[str, str]`, `view: str | None`.
  - `load_maps(maps_dir: Path) -> list[EntityMap]`
  - `validate_map(raw: dict) -> list[str]` (error messages, empty when valid)
  - `coerce(value: str, type_: str) -> object` (`bool`, `int`, `text`, `list` split on `;` and `,`)
  - `parse_date(raw: str) -> tuple[str | None, bool]` (ISO `YYYY-MM-DDTHH:MM:SS` or date, ambiguous flag)

- [ ] **Step 1: Write the failing tests** in `test_entity_maps.py`:
  - `test_parse_date_unambiguous`: `parse_date("24/06/2026 1:58:30 PM") == ("2026-06-24T13:58:30", False)`; `parse_date("6/13/2024 10:37:29 AM") == ("2024-06-13T10:37:29", False)`; `parse_date("09-Nov-17") == ("2017-11-09", False)`; `parse_date("18-Sep-26") == ("2026-09-18", False)`; `parse_date("15/10/2019 5:23:28 PM") == ("2019-10-15T17:23:28", False)`.
  - `test_parse_date_ambiguous_is_not_guessed`: `parse_date("12/09/2016 9:36:18 PM") == (None, True)`; `parse_date("4/05/2023 9:00:00 AM") == (None, True)`.
  - `test_parse_date_empty`: `parse_date("") == (None, False)`.
  - `test_coerce`: `coerce("True","bool") is True`; `coerce("False","bool") is False`; `coerce("a; b, c","list") == ["a","b","c"]`; `coerce("7","int") == 7`.
  - `test_validate_map_reports_missing_fields`: a dict without `kind` gives an error naming `kind`; an `attrs` type of `"colour"` gives an error naming the type.
  - `test_load_maps_reads_all_json`: two valid files in `tmp_path` load as two `EntityMap`.
- [ ] **Step 2: Run** `../.venv/bin/python -m pytest csa_docx/tests/test_entity_maps.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `entity_maps.py`.** `parse_date` splits the first two numeric parts: a part over 12 fixes day or month; both 12 or under means ambiguous; month names (`Jan`..`Dec`) are unambiguous; two-digit years add 2000; 12-hour clock converted to 24-hour.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `git add csa_docx/entity_maps.py csa_docx/tests/test_entity_maps.py && git commit -m "entity layer: map schema, typing, safe date parsing"`.

**Part C additions (Task 1):**
- `EntityMap.file: str` becomes `files: list[str]` (the JSON key `file` may be a string or a list of alternates in order of preference), and `EntityMap` gains `sentinels: list[str]` and `probes: list[str]` (regular expressions). `validate_map` reports an invalid regular expression and a non-list value.
- Add tests: `test_file_may_be_a_string_or_a_list_of_alternates`; `test_sentinels_and_probes_must_be_valid_regular_expressions`.

---

### Task 2: Entity store schema, ids and shrink guard

**Files:**
- Create: `csa_docx/entity_store.py`
- Test: `csa_docx/tests/test_entity_store.py`

**Interfaces:**
- Produces:
  - `ensure_schema(con: sqlite3.Connection) -> None` creating `entity`, `entity_source`, `host_property`, `dependency` (columns exactly as spec section 5) plus indexes `(kind, host)` and `(kind, key)`.
  - `entity_id(project: str, kind: str, host: str, key: str, capture_utc: str, source_line: int) -> str` returning `"EN-"` plus the first 10 hex of the sha1 of those fields joined by `\x1f`.
  - `kind_counts(con) -> dict[str, int]`
  - `class EntityShrinkError(RuntimeError)`
  - `replace_derived(con, project: str, entities: list[dict], ledger: list[dict], allow_shrink: frozenset[str] = frozenset()) -> None`: drops and refills `entity` and `entity_source` for the project; raises `EntityShrinkError` (and rolls back) when any kind has fewer rows than before and is not in `allow_shrink`.

- [ ] **Step 1: Write the failing tests**: `test_entity_id_is_stable_and_distinct` (same inputs equal; different `source_line` differ; different `capture_utc` differ); `test_replace_derived_is_idempotent` (two calls, identical `select * from entity order by entity_id`); `test_shrink_is_refused` (second call with fewer `account` rows raises `EntityShrinkError` and leaves the first rows in place); `test_shrink_allowed_when_named`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_store.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `entity_store.py`** against an in-memory sqlite connection; `attrs` stored as JSON text.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** the two files, message `entity layer: store schema, stable ids, shrink guard`.

**Part C additions (Task 2):**
- `ensure_schema` also creates `capture` (`project, host, capture_utc, folder, collector_version, intake_batch, run_status, failed_steps, files_present`), `data_release` (`release_id, built_at, captures_hash, maps_hash, rules_hash, counts, previous_release`), `data_suspect` (`project, host, property, source_file, probe, hits, note`) and `entity_history` (a reviewed table a build never drops: `entity_id, project, host, kind, key, capture_utc, attrs, release_first, release_last`). `entity` gains `release_first, release_last, supersedes`; `host_property` gains `reason, release_first, release_last`.
- `entity_source.status` accepts exactly `mapped, empty, unmapped, failed, unparsed, not_collected, missing, collector_error`; any other value raises `ValueError`.
- `replace_derived(con, project, entities, ledger, release_id: str, allow_shrink=frozenset())` stamps every row with `release_id`.
- Add tests: `test_schema_has_capture_release_suspect_and_history_tables`; `test_an_unknown_ledger_status_is_refused`; `test_entity_history_is_never_dropped_by_replace_derived`.

---

### Task 3: Loader, table mode

**Files:**
- Create: `csa_docx/entity_loader.py`
- Test: `csa_docx/tests/test_entity_loader.py`

**Interfaces:**
- Consumes: `EntityMap`, `coerce`, `parse_date` (Task 1); `entity_id` (Task 2).
- Produces: `load_table_map(index: sqlite3.Connection, m: EntityMap, project: str) -> tuple[list[dict], list[dict]]` returning `(entities, ledger)`. An entity dict has the `entity` columns; `attrs` holds the typed attributes plus, for each `datetime` attribute, `<name>_raw`, `<name>_iso`, `<name>_ambiguous`. A ledger dict has the `entity_source` columns.
- The index fixture follows `tests/test_hostmodel.py::_index` (tables `captures`, `files`, `rows`).

- [ ] **Step 1: Write the failing tests** with a fixture index of three current captures (hosts `H1`, `H2`, `H3`) and one superseded capture of `H1`, mapped file `44_local_users.txt`, table `local_users`:
  - `test_every_current_host_gets_entities`: H1 has the original file; H2's file is `status='duplicate'`, `dup_of` the H1 file. Both hosts yield accounts; H2's have `origin == "copied"` and `source_file` equal to H2's own `rel_path`.
  - `test_empty_file_is_recorded_not_skipped`: H3's file has no rows; ledger has `status == "empty"`, `entities_out == 0`, and no entity rows for H3.
  - `test_missing_column_fails_loudly`: rows lacking `Enabled` give ledger `status == "failed"` with a note naming `Enabled`.
  - `test_superseded_capture_is_ignored`: no entity carries the superseded capture's `capture_utc`.
  - `test_duplicate_whose_original_host_is_not_current`: the original file belongs to an archived capture; the duplicate host still yields entities (Review Focus 1).
  - `test_same_key_twice_gets_distinct_ids`: two rows named `SrvAdmin` in one file give two ids (Review Focus 5).
  - `test_key_is_case_insensitive_label_keeps_spelling`: rows `SrvAdmin` (host H1) and `srvadmin` (host H2): both have `key == "srvadmin"`, and `label` is the original spelling of each (Review Focus 3).
  - `test_dates_flagged`: `LastLogon "12/09/2016 9:36:18 PM"` gives `last_logon_iso is None` and `last_logon_ambiguous is True`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_loader.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `load_table_map`.** For each current capture, find the capture's file whose `rel_path` ends with `m.file`; resolve rows through `dup_of` when `status == "duplicate"`; stream rows with a cursor.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: table-mode loader with duplicate and empty-file handling`.

**Part C additions (Task 3):**
- A source file with `files.size` of 2 or less and no rows is ledger `empty`; a file with more content than that and no rows, or whose rows all fail the map, is `unparsed` with a note. `m.files` is tried in order and the first file present in the capture is read.
- Add tests: `test_a_file_with_content_but_no_rows_is_unparsed_not_empty` (size 2 gives `empty`, size 500 gives `unparsed`); `test_the_first_alternate_file_present_is_read`.

---

### Task 4: Loader, text mode

**Files:**
- Modify: `csa_docx/entity_loader.py`
- Test: `csa_docx/tests/test_entity_loader_text.py`
- Create (fixture): `csa_docx/tests/fixtures/55_domain_controller_discovery.txt`, a trimmed copy of `TETRA/06 REVELOC TETRA/01 Current State AS Built/revloc-tetra/02Script_Results/REVELOC_discovery_IPTPRDAPP137_20261029T010439Z/55_domain_controller_discovery.txt`.

**Interfaces:**
- Produces:
  - `TEXT_PARSERS: dict[str, Callable[[str], list[dict]]]` with the key `"csa_docx.hostmodel.domain_controller_list"` wrapping `hostmodel.domain_controller_list(text)` into `[{"host", "fqdn", "site", "pdc", "line"}]` (`line` = offset + 1).
  - `load_text_map(index: sqlite3.Connection, m: EntityMap, project: str, capture_root: Path) -> tuple[list[dict], list[dict]]` reading the raw file at `capture_root / files.rel_path` for every current capture, including duplicates (their own path).

- [ ] **Step 1: Write the failing tests**: `test_domain_controllers_parsed_from_text` (fixture file; asserts the host and site pairs found in the fixture, copied literally from it); `test_text_mode_reads_duplicates_from_their_own_path` (two captures with identical fixture files; both hosts get `domain_controller` entities with their own `source_file`); `test_unreadable_file_is_failed_in_ledger`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_loader_text.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `TEXT_PARSERS` and `load_text_map`; unknown parser name gives a `failed` ledger row.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: text-mode loader for domain controller discovery`.

**Part C additions (Task 4):**
- A text parser that returns no entities for a file with more than 2 bytes of content gives ledger `unparsed`; if the map lists `sentinels` and none appears in the text the note says so.
- Add test: `test_a_text_file_with_content_but_no_parsed_entities_is_unparsed`.

---

### Task 5: Identity maps

**Files:**
- Create: `references/entity-maps/account.json`, `group.json`, `group_member_local_admins.json`, `group_member_rdp.json`, `account_use_services.json`, `account_use_tasks.json`, `domain_controller.json`
- Test: `csa_docx/tests/test_entity_identity_maps.py`

**Interfaces:**
- Consumes: `load_maps`, `validate_map` (Task 1).
- Produces map files with these exact contents:
  - `account.json`: mode `table`, source `local_users`, file `44_local_users.txt`, kind `account`, key `["Name"]`, label `Name`, attrs `enabled` (col `Enabled`, `bool`), `last_logon` (col `LastLogon`, `datetime`), `password_required` (col `PasswordRequired`, `bool`), `principal_source` (col `PrincipalSource`, `text`), view `v_account`.
  - `group.json`: source `local_groups`, file `45_local_groups.txt`, kind `group`, key `["Name"]`, attrs `description` (`Description`), `principal_source`; view `v_group`.
  - `group_member_local_admins.json`: source `local_admins_membership`, file `46_local_admins_membership.txt`, kind `group_member`, key `["Name"]`, const `{"group": "Administrators (local)"}`, attrs `member_type` (`ObjectClass`), `principal_source`; view `v_group_member`.
  - `group_member_rdp.json`: same, source `remote_desktop_users_membership`, file `47_remote_desktop_users_membership.txt`, const `{"group": "Remote Desktop Users"}`.
  - `account_use_services.json`: source `services_inventory`, file `32_services_inventory.txt`, kind `account_use`, key `["Name"]`, attrs `account` (`StartName`), `state` (`State`), `use` const `service`; view `v_account_use`.
  - `account_use_tasks.json`: source `scheduled_tasks`, file `66_scheduled_tasks.txt`, kind `account_use`, key `["TaskPath","TaskName"]`, attrs `account` (`RunAs`), `use` const `scheduled task`.
  - `domain_controller.json`: mode `text`, source `csa_docx.hostmodel.domain_controller_list`, file `55_domain_controller_discovery.txt`, kind `domain_controller`, key `["host"]`, attrs `fqdn`, `site`, `pdc` (`bool`).
- [ ] **Step 1: Write the failing test** `test_every_identity_map_is_valid_and_names_a_real_capture_file`: `load_maps` returns the seven maps, `validate_map` is empty for each, and each `file` exists as a file name in the TETRA capture folder (skipped when the TETRA data is absent).
- [ ] **Step 2: Run it.** Expected: FAIL (no files).
- [ ] **Step 3: Write the seven JSON files** as specified; confirm each `file` and column name against one real capture file before saving.
- [ ] **Step 4: Run the test.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: identity maps`.

---

### Task 6: Host properties

**Files:**
- Create: `csa_docx/entity_properties.py`, `references/entity-properties/identity.json`
- Test: `csa_docx/tests/test_entity_properties.py`

**Interfaces:**
- Consumes: the `entity` and `entity_source` tables (Task 2), loader output (Tasks 3, 4).
- Produces: `compute_properties(con: sqlite3.Connection, project: str, rules_dir: Path) -> list[dict]` returning `host_property` rows `{host, name, value, state, capture_utc, entity_ids}`. `identity.json` defines `identity.local_users` (names of enabled `account` entities, sorted), `admin.local_admins` (`group_member` where `group == "Administrators (local)"`), `admin.rdp_users` (`group_member` where `group == "Remote Desktop Users"`), `identity.domain` and `identity.kdc` kept as later work.
- State rule: capture of the source file exists and yields entities gives `value`; ledger `empty` or file present with no matching entities gives `none evidenced`; no ledger row for the host and file gives `not captured`.

- [ ] **Step 1: Write the failing tests** on a model db built from a fixture: `test_empty_rdp_listing_is_none_evidenced`; `test_missing_file_is_not_captured`; `test_local_users_lists_enabled_only_sorted` (`"SrvAdmin, casuser"` order: sorted case-insensitively, joined by `", "`); `test_property_carries_entity_ids`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_properties.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `compute_properties`** driven only by the rule file (kind, filter, value attribute, sort, join).
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: host properties with the five states`.

**Part C additions (Task 6):**
- `host_property` rows carry `reason`. `none evidenced` is allowed only when the ledger status of the source file is `mapped` or `empty`; `unparsed` gives `suspect` with reason `unparsed`; `not captured` takes its reason from the ledger (`not_collected`, `missing`, `collector_error`).
- Add tests: `test_none_evidenced_needs_a_trusted_source_file`; `test_not_captured_carries_the_ledger_reason`; `test_an_unparsed_file_makes_the_property_suspect`.

---

### Task 7: Dependencies and the application rollup

**Files:**
- Create: `csa_docx/entity_dependencies.py`
- Test: `csa_docx/tests/test_entity_dependencies.py`

**Interfaces:**
- Consumes: `entity` (`domain_controller`, `account`), `host_property`, model tables `host` (columns `host`, `fqdn`), `address` (columns `address`, `name`), `application`, `application_part`, `part_member`.
- Produces:
  - `derive_dependencies(con, project: str) -> list[dict]`: one row per (consumer host, domain controller it lists): `{consumer_host, capability: "directory", provider, provider_ref, fallback, entity_ids, capture_utc}`. `provider_ref` is the host name when the listed name matches `host.host` or `host.fqdn` (case-insensitive), else the address when it matches `address.address`, else the listed name, else `""`. `fallback` is `yes` when the host has at least one enabled local account, `no` when it has local accounts but none enabled, `unknown` when it has no capture.
  - `application_rollup(con, application_id: str) -> list[dict]`: `{capability, provider, hosts: list[str], fallback: str}` grouped by capability and provider, over the application's parts' hosts (tables `application_part`, `part_member`); `fallback` is `yes` only when every listed host has it.

- [ ] **Step 1: Write the failing tests**: `test_provider_resolution` (a host listing one controller known in `host` and one known only in `address` gives `provider_ref` as the host name and as the address; one known in neither gives the listed name); `test_fallback_yes_when_enabled_local_account`; `test_fallback_no_when_local_accounts_all_disabled`; `test_fallback_unknown_without_capture`; `test_unresolved_provider_is_not_guessed` (`provider_ref == ""` when the capture gives no name); `test_rollup_groups_by_capability_and_provider`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_dependencies.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** both functions.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: directory dependencies and application rollup`.

---

### Task 8: `csa entities` command

**Files:**
- Create: `csa_docx/entity_cli.py`
- Modify: `bin/csa` (add `cmd_entities` beside `cmd_model` at line 3769 and its parser beside line 5821), `CSA-COMMANDS.md`
- Test: `csa_docx/tests/test_entity_cli.py`

**Interfaces:**
- Consumes: Tasks 1 to 7.
- Produces: `build(work_dir: Path, project: str, maps_dir: Path, rules_dir: Path, capture_root: Path, db_path: Path | None = None, allow_shrink: frozenset[str] = frozenset()) -> dict[str, int]` (counts per table); `host_view(db_path, host: str) -> dict` (entities by kind with source file and line, properties with entity ids, dependencies, ledger); `coverage(db_path) -> dict` (host by property states, unmapped capture tables, hosts with no capture); `main(argv) -> int` for `build | status | host HOST | show KIND | coverage | deps APPLICATION`, `--json` on each.

- [ ] **Step 1: Write the failing tests** with a temp work dir: `test_build_twice_is_identical`; `test_host_view_shows_source_file_and_line_for_every_entity`; `test_coverage_lists_unmapped_capture_tables` (a table in the index with no map appears under `unmapped`); `test_build_does_not_touch_observation` (row count of `observation` unchanged).
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_cli.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `entity_cli.py`; `cmd_entities` runs it with `subprocess.call([framework_python(), "-m", "csa_docx.entity_cli", ...], cwd=str(FRAMEWORK))` as `cmd_model` does; add the verb to `CSA-COMMANDS.md`.
- [ ] **Step 4: Run** the tests, then `.agents/bin/csa -p tetra-reveloc entities build` on the real project with `--db-path` pointing at a scratch file. Expected: tests PASS; build prints counts, ledger has no `failed` row for the identity maps.
- [ ] **Step 5: Commit** `entity layer: csa entities command`.

**Part C additions (Task 8):**
- `build` runs in this order: capture rows and collector detection (Task 17), profile ledger (Task 18), entity load, properties, dependencies, probe reconciliation (Task 19), release and history (Task 20). `coverage` reports the five states with reasons and lists `data_suspect` rows.
- Add test: `test_coverage_reports_reasons_and_suspects`.

---

### Task 9: Known values on real data, and cross-project

**Files:**
- Test: `csa_docx/tests/test_entity_tetra_known_values.py`

**Interfaces:**
- Consumes: `entity_cli.build(...)` (Task 8) writing to a temp `db_path`; the TETRA project at `TETRA/06 REVELOC TETRA/csa-work` (test skipped when absent) and UTC DTC at `UTC DTC/07 UTC DTC with KVM/csa-work`.

- [ ] **Step 1: Write the tests** (all skipped when the project folder is absent):
  - `test_tetra_accounts_cover_all_19_hosts`: `account` entities exist for 19 distinct hosts.
  - `test_srvadmin_is_enabled_and_local_admin_on_all_19`.
  - `test_srvadmin_on_mkyprdops110_needs_no_password`: `password_required is False`; on every other host it is `True`.
  - `test_rdp_listing`: `admin.rdp_users` state is `value` for 7 hosts and `none evidenced` for 12; includes `IPTPRDAPP137`, `MOTPRDCLU101`, `ROTPRDREV102` among the 12.
  - `test_sdelineadiscovery_in_local_admins_on_14_hosts`: absent on exactly `IPTPRDAPP137`, `MKYPRDOPS110`, `ROKPRDOPS110`, `ROTPRDCLU101`, `ROTPRDCLU104`.
  - `test_every_tetra_host_has_a_directory_dependency_or_none_evidenced`: each of the 19 hosts has at least one `directory` dependency row or an `entity_source` ledger row showing its domain controller file was captured and empty.
  - `test_utc_dtc_builds_with_no_failed_identity_source`: build completes; no `failed` ledger rows for the identity maps.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_tetra_known_values.py -q`. Expected: PASS (these pin the real data; a failure means a loader bug or changed captures).
- [ ] **Step 3: Parity check script step:** compare `identity.local_users`, `admin.local_admins`, `admin.rdp_users` against `observation` rows (`topic.attribute` `identity.local_users`, `admin.local_admins`, `admin.rdp_users`) as sets of names per host; write any difference to `csa-work/entity-parity.md`. Expected: file lists no difference, or each difference is explained in the file.
- [ ] **Step 4: Run the full suite.** Expected: only the baseline failure.
- [ ] **Step 5: Commit** `entity layer: known-value tests on TETRA, UTC DTC build check`.

**Part C additions (Task 9):**
- Add known-value tests (skipped when the TETRA folder is absent): `test_collector_era_of_every_capture` (13 captures are `reveloc-allservers-v3`, the six SQL Server cluster nodes `reveloc-v18-safe`); `test_sql_nodes_are_not_collected_for_the_files_only_the_newer_collector_writes` (for example `13_dns_client_cache.txt`, `42E_smb_share_access.txt`, `85_windows_backup_configuration.txt`); `test_collector_errors_are_read_from_the_run_log` (ROTPRDREV102 has failed steps `88A_host_files_collection_summary.txt` and `88B_host_files_collection_manifest.txt`; report any other October capture that does).

---

### Task 10: Go/no-go evaluation on 4.5 to 4.8

**Files:**
- Create: `.agents/docs/superpowers/plans/2026-11-10-identity-slice-evaluation.md`

**Interfaces:**
- Consumes: `csa entities host`, `show account`, `show group_member`, `coverage`.

- [ ] **Step 1: Build the entity views and draft the register content for 4.5, 4.6, 4.7 and 4.8 from `csa entities` only** (no matrix rows, no card), listing every host and every entity.
- [ ] **Step 2: Score both versions against this checklist, in the evaluation file:** (a) every host present in each register (count missing hosts for the current answers and the new draft); (b) twenty claims spot-checked against the raw capture files, listing any the data contradicts; (c) exceptions surfaced (SrvAdmin without a password on MKYPRDOPS110, accounts with no sign-in since 2019 or earlier, Domain SQL Admins missing on the two Reveloc application / TGOIP servers); (d) every absence worded as `none evidenced` or `not captured`.
- [ ] **Step 3: State the go/no-go.** The slice is a go when (a) shows no missing host, (b) shows no contradicted claim, (c) all three exceptions appear, and (d) holds. Hand the file to the user for the decision before pieces 2 to 5 are planned.
- [ ] **Step 4: Commit** `entity layer: Identity slice evaluation`.

**Part C additions (Task 10):**
- Add checklist items: (f) every suspect is fixed or accepted with a reason; (g) hosts older than the latest intake batch are named, with the files they lack as `not_collected` and not as missing hosts.

---

## Part B: editing and the Host screen

### Task 11: The edit store

**Files:**
- Create: `csa_docx/entity_edits.py`
- Modify: `csa_docx/entity_maps.py` (add `assessor: dict[str, dict] = {}` to `EntityMap`; `validate_map` checks each assessor field has a `type`)
- Test: `csa_docx/tests/test_entity_edits.py`

**Interfaces:**
- Consumes: `EntityMap`, `coerce` (Task 1). Pattern: `csa_docx/connected_devices.py` (`_ok`, `_error`, `_blocked`, `_lock`, `_atomic_write`, `_append_audit`).
- Produces (all return `{"status": "OK", ...}` or `{"status": "ERROR" | "BLOCKED", "message": str}`; `project` is the project root):
  - `add_entity(project, *, host: str, kind: str, key: str, attrs: dict, basis_type: str, source_ref: str, note: str = "", author: str = "") -> dict` returning `edit_id` (`"EE-0001"`, next free) and `revision`.
  - `annotate_entity(project, *, host: str, kind: str, key: str, changes: dict, expected_revision: int | None = None, source_ref: str = "", author: str = "") -> dict`; `changes` may name only fields the kind's map lists under `assessor`.
  - `set_state(project, edit_id: str, *, state: str, source_ref: str = "", expected_revision: int, author: str = "") -> dict` (`asserted`, `confirmed` needs a `source_ref`, `disputed` needs a `note`).
  - `retire_entity(project, edit_id: str, *, expected_revision: int, reason: str, author: str = "") -> dict` and `restore_entity(...)`.
  - `list_edits(project, host: str | None = None, include_retired: bool = False) -> list[dict]` and `read_audit(project, host: str | None = None) -> list[dict]`.
- Files under `<project>/csa-work/hosts/`: `entity_edits.csv` (columns `edit_id, host, kind, key, label, op, attrs, status, basis_type, source_ref, note, author, at, active, revision`), `entity-audit.jsonl` (`at, action, edit_id, before, after, author`), `.entity_edits.lock`. Back up the CSV before each write and keep the newest 10.

- [ ] **Step 1: Write the failing tests:** `test_add_requires_basis_and_source_ref`; `test_add_is_unique_per_host_kind_key_case_insensitively` (`SrvAdmin` then `srvadmin` on the same host is refused naming the first edit); `test_annotate_rejects_a_captured_attribute` (`changes={"enabled": False}` on an account is refused with a message naming `annotate` and `disputed`); `test_annotate_accepts_assessor_fields_only`; `test_stale_revision_is_refused_and_changes_nothing`; `test_retire_and_restore_never_delete` (row stays, `active` toggles, audit has both lines); `test_audit_is_append_only` (earlier lines unchanged after later edits); `test_confirmed_needs_a_source_ref`; `test_a_backup_is_written_before_each_change`; `test_two_writers_do_not_corrupt_the_file` (threads each add 20 distinct keys; 40 rows, all revisions consistent).
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_edits.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the module following `connected_devices.py`; the revision is an integer that rises by one on every change to a row.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: durable edit store for assessor input`.

---

### Task 12: Merge the overlay into the entity view

**Files:**
- Create: `csa_docx/entity_overlay.py`
- Modify: `csa_docx/entity_store.py` (table `entity_effective`), `csa_docx/entity_cli.py` (`build` calls the overlay; `host_view` and `show` read `entity_effective`), `csa_docx/entity_properties.py` (read `entity_effective`), the Identity map files (add `assessor` fields)
- Test: `csa_docx/tests/test_entity_overlay.py`

**Interfaces:**
- Consumes: `list_edits` (Task 11), the `entity` table (Tasks 2 to 4).
- Produces: `apply_overlay(con: sqlite3.Connection, project: str, edits: list[dict]) -> list[dict]` returning the rows written to `entity_effective`: every `entity` column plus `origin` (`capture`, `assessor`, `capture+assessor`), `state` (`captured`, `asserted`, `confirmed`, `disputed`, `retired`), `captured_attrs`, `assessor_attrs`, `edit_ids`, `conflict` (0 or 1), `orphaned` (0 or 1).
- Assessor fields added to the maps: `account`: `purpose`, `owner`, `privileged` (text), `notes`; `group`: `purpose`, `owner`, `notes`; `group_member` and `account_use`: `notes`.
- `host_property` rows gain `asserted_entity_ids` (JSON list); a property still has state `value` when asserted entities contribute.

- [ ] **Step 1: Write the failing tests:** `test_an_annotation_shows_beside_the_captured_value`; `test_an_added_entity_has_origin_assessor`; `test_an_edit_survives_a_rebuild_and_a_recapture` (a second capture of the host gives new entity ids; the annotation still applies); `test_an_edit_on_a_missing_entity_is_orphaned_not_deleted` (Review Focus 6); `test_a_newer_capture_that_disagrees_raises_a_conflict`; `test_a_retired_add_is_hidden_and_a_retired_annotation_is_marked`; `test_properties_include_asserted_entities_and_list_their_ids`; `test_build_never_drops_the_edit_store_and_the_shrink_guard_covers_it`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_overlay.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `apply_overlay`; match on (host, kind, lower-cased key); the annotation applies to the newest capture's entity.
- [ ] **Step 4: Run the tests and the full suite.** Expected: PASS, baseline failure only.
- [ ] **Step 5: Commit** `entity layer: merge assessor edits into entity_effective`.

---

### Task 13: Host API in the Evidence Browser

**Files:**
- Create: `evidence-browser/backend/host_entities.py`
- Modify: `evidence-browser/backend/app.py` (routes, beside the assets routes at line 1086)
- Test: `evidence-browser/tests/test_host_entities.py`

**Interfaces:**
- Consumes: `entity_edits`, `entity_overlay`, the model store, `assets.AssetError`-style errors (`HostEntityError(status: int, message: str, code: str = "invalid")`).
- Produces (module functions, each `(work_dir: Path, agents: Path, ...)`; write functions also take `project_root: Path`):
  - `search_hosts(work_dir, agents, q: str, limit: int = 20) -> list[dict]` rows `{host, fqdn, ips, role, site, application, newest_capture, collector_era, counts, edits}`; matches name, FQDN, address and role words, case-insensitively.
  - `host_page(work_dir, agents, host: str) -> dict` `{header, properties, dependencies, kinds: [{kind, count, asserted}], coverage, suspects}`.
  - `kind_schemas(agents) -> dict[str, dict]` field list with `type`, `editable`, `required` for each kind, read from the maps.
  - `list_entities(work_dir, agents, host: str, kind: str, q: str = "", include_retired: bool = False) -> dict` `{schema, rows}`; each row carries `captured_attrs`, `assessor_attrs`, `origin`, `state`, `source_file`, `source_line`, `revision`.
  - `add_entity`, `annotate_entity`, `set_state`, `retire`, `restore` wrapping Task 11, each returning the new row and `effect` (`{"registers": [...], "blocks": [...], "note": str}`).
  - `import_preview(project_root, work_dir, agents, host: str, kind: str, text: str) -> dict` (tab or comma separated with a header row; per row `ok` or `errors`; writes nothing; returns `preview_id`) and `import_commit(..., preview_id: str) -> dict` (all rows or none).
  - `search_entities(work_dir, agents, kind: str, q: str, limit: int = 50) -> list[dict]` and `history(work_dir, agents, host: str) -> list[dict]`.
- Routes under `/api/systems/{system_key}`, exactly as spec section 17.6. Errors: 404 unknown host, 409 stale revision with `{"stale": true}`, 422 invalid.

- [ ] **Step 1: Write the failing tests** (fixtures as `tests/test_assets.py::_work`): `test_search_finds_a_host_by_name_address_and_role`; `test_host_page_lists_properties_with_state_and_entities_by_kind`; `test_entities_split_captured_and_assessor_values`; `test_add_then_list_shows_the_new_entity_with_origin_assessor`; `test_a_captured_attribute_cannot_be_edited_through_the_api` (422); `test_stale_revision_is_409_and_keeps_the_payload`; `test_import_preview_writes_nothing_and_commit_is_all_or_none` (Review Focus 8); `test_unknown_host_is_404`; `test_every_write_is_in_the_audit`.
- [ ] **Step 2: Run** `python3 -m pytest -q tests/test_host_entities.py` from `.agents/evidence-browser`. Expected: FAIL.
- [ ] **Step 3: Implement** the module and routes; reuse the assets error translation.
- [ ] **Step 4: Run** the new tests and `python3 -m pytest -q tests`. Expected: PASS, no new failure.
- [ ] **Step 5: Commit** `evidence browser: host and entity API`.

---

### Task 14: The Host page, read-only

**Files:**
- Create: `evidence-browser/frontend/src/components/HostPage.tsx`, `host-page.css`
- Modify: `frontend/package.json` (devDependencies `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, pinned to the current stable versions at install time and recorded in the commit message; script `"test": "vitest run"`), create `frontend/vitest.config.ts` (environment `jsdom`), `src/api.ts` (`searchHosts`, `getHostPage`, `listHostEntities`, `getEntityKinds`, `getHostHistory`), `src/types.ts`, `src/components/AssetsPage.tsx` (a **Look up a host** box above the tabs; the Application hosts detail renders `HostPage`)
- Test: `src/__tests__/hostPage.test.tsx`

**Interfaces:**
- Consumes: the Task 13 routes. `HostPage` props: `{ system: string; host: string; onClose: () => void }`.
- Produces: the lookup (type-ahead, 200 ms debounce, name, FQDN, address, role), the header, and the tabs **Overview**, **Entities**, **Coverage**, **History**; the entities table has grey read-only captured columns with `source_file:line`, assessor columns, and an origin badge (`capture`, `assessor`, `disputed`).

- [ ] **Step 1: Write the failing tests:** `typing_a_name_or_address_lists_matching_hosts`; `selecting_a_host_opens_the_host_page`; `overview_shows_properties_with_state_and_justifying_entities`; `entities_tab_shows_captured_columns_read_only_and_assessor_columns`; `coverage_tab_lists_not_collected_and_suspect_files`; `history_tab_lists_edits_for_the_host`.
- [ ] **Step 2: Run** `npm install` then `npm test -- hostPage` from `.agents/evidence-browser/frontend`. Expected: FAIL (no component yet), and the existing `draftRating` test still passes under `npm test`.
- [ ] **Step 3: Add the test tooling, then implement** the component and wiring; keep the Devices, Unidentified and Conflicts tabs as they are. Mock the API module in the tests.
- [ ] **Step 4: Run** the tests and `npm run build`. Expected: PASS, build succeeds.
- [ ] **Step 5: Commit** `evidence browser: Host page`.

---

### Task 15: Editing on the Host page

**Files:**
- Create: `src/components/EntityTable.tsx`, `EntityForm.tsx`, `PasteImport.tsx`
- Modify: `src/components/HostPage.tsx`, `src/api.ts` (`addEntity`, `annotateEntity`, `setEntityState`, `retireEntity`, `restoreEntity`, `previewImport`, `commitImport`), `src/types.ts`
- Test: `src/__tests__/entityEditing.test.tsx`

**Interfaces:**
- Consumes: Task 13 write routes and `kind_schemas`; the stale-revision handling pattern of `AssetsPage.tsx` (the entered text is kept).
- Produces: **Add information** opens `EntityForm` for the selected kind with exactly the schema's editable fields, key and source reference required, host and kind preselected, the last basis remembered, Enter saves; inline editing of assessor cells in `EntityTable` (click, type, Enter saves, Esc cancels); `PasteImport` (paste, preview table with OK or error per row, Commit disabled while any row has an error); an effect banner under the table after every save; Retire (one confirmation), Restore, **Show retired**.

- [ ] **Step 1: Write the failing tests:** `the_add_form_shows_only_the_kinds_fields_and_requires_key_and_source`; `enter_saves_and_the_new_row_appears_with_an_assessor_badge`; `a_duplicate_key_is_stopped_and_names_the_existing_row`; `inline_edit_saves_on_enter_and_cancels_on_escape`; `a_captured_cell_is_not_editable`; `a_stale_revision_keeps_the_typed_text_and_says_the_row_changed`; `paste_preview_marks_each_row_and_commit_is_disabled_while_any_row_is_wrong`; `the_effect_banner_lists_registers_and_blocks_after_saving`; `retire_asks_once_and_restore_brings_the_row_back`.
- [ ] **Step 2: Run** `npm test -- entityEditing`. Expected: FAIL.
- [ ] **Step 3: Implement** the three components and wire them into `HostPage`.
- [ ] **Step 4: Run** the tests and `npm run build`. Expected: PASS.
- [ ] **Step 5: Commit** `evidence browser: add and edit entities`.

---

### Task 16: Walkthrough on the real project (human)

- [ ] **Step 1:** Open the Evidence Browser on TETRA, look up `MKYPRDOPS110` by name, then by its address, then by the word `jump`; each finds it in two interactions or fewer.
- [ ] **Step 2:** On its Entities tab open accounts, see `SrvAdmin` with `password_required` false from the capture, and add a purpose and an owner with a source reference by inline edit. Press Enter to save.
- [ ] **Step 3:** Add an account known only from a document with **Add information**; paste five accounts for another host; retire one and restore it.
- [ ] **Step 4:** Run `csa entities build`; check that both edits show beside the captured values with origin `capture+assessor` and `assessor`, and that the 4.5 register source (`csa entities show account`) lists them as `stated`.
- [ ] **Step 5:** Record what was slow or unclear in `.agents/docs/superpowers/plans/2026-11-10-host-screen-notes.md` and hand it to the user.


---

## Part C: data management foundations

### Task 17: Capture manifest and collector profiles

**Files:**
- Create: `csa_docx/entity_captures.py`, `references/collector-profiles/reveloc-v18-safe.json`, `references/collector-profiles/reveloc-allservers-v3.json`
- Test: `csa_docx/tests/test_entity_captures.py`, fixtures `csa_docx/tests/fixtures/run_summary_utf16.txt` (a real July `90_run_summary.txt`) and `run_summary_utf8.txt` (a real October one), `run_log_failed_steps.txt` (the `RUN_LOG.txt` lines of ROTPRDREV102 around the `88A` and `88B` errors)

**Interfaces:**
- Consumes: Task 2 tables.
- Produces:
  - `read_run_summary(path: Path) -> dict[str, str]`: decodes UTF-16 with or without a BOM, or UTF-8, and returns the `key: value` lines.
  - `load_profiles(profiles_dir: Path) -> list[dict]` each `{name, detect: {"script": [str], "version": [str]}, files: [str]}`.
  - `detect_collector(summary: dict[str, str], files: set[str], profiles: list[dict]) -> str`: the profile whose `detect` matches `Script`, `Version`, `WrapperVersion` or `BaselineVersion`; else the profile whose `files` overlap the capture's set by at least 0.8; else `"unknown"`.
  - `build_capture_rows(index: sqlite3.Connection, capture_root: Path, project: str, profiles: list[dict]) -> list[dict]` one row per current capture (`capture` columns); `failed_steps` is a JSON list of `{step, message}` from `RUN_LOG.txt` lines matching `ERROR: (\S+) failed: (.*)`; `run_status` is `partial` when any step failed, else `complete`; `intake_batch` is the name of the folder holding the capture folder (and the zip name when one named for the capture sits in a sibling `Results <date>` folder).
  - Profile generator: `python -m csa_docx.entity_captures profile --from-capture <folder> --name <name>` prints a profile JSON whose `files` is exactly the files in that folder (sorted); the two shipped profiles are produced from `ROTPRDCLU104_20260709T054259Z` and `ROKPRDOPS110_20261029T035434Z`, with the `detect` values from the General Constraints.

- [ ] **Step 1: Write the failing tests:** `test_read_run_summary_decodes_utf16_without_bom`; `test_read_run_summary_decodes_utf8`; `test_detect_collector_by_script_and_version`; `test_detect_collector_falls_back_to_the_file_set`; `test_an_unrecognised_capture_is_unknown`; `test_failed_steps_are_read_from_the_run_log` (two steps `88A_host_files_collection_summary.txt` and `88B_host_files_collection_manifest.txt`, status `partial`); `test_a_capture_without_failures_is_complete`; `test_profile_from_capture_lists_exactly_the_files_present`; `test_the_shipped_profiles_have_81_and_76_files`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_captures.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the module; generate the two profile files with the profile command and review their `detect` blocks.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: capture manifest and collector profiles`.

---

### Task 18: Ledger from collector profiles

**Files:**
- Modify: `csa_docx/entity_loader.py`
- Test: `csa_docx/tests/test_entity_profile_ledger.py`

**Interfaces:**
- Consumes: Task 17 rows and profiles, Task 3 ledger rows.
- Produces:
  - `profile_ledger(capture: dict, own_profile: dict | None, newest_profile: dict | None, present: set[str]) -> list[dict]`: a ledger row for each file name in `newest_profile["files"]` not in `present`: status `collector_error` when a failed step of the capture has that file's step prefix (`88A_...`), else `not_collected` when the file is not in `own_profile["files"]` and `own_profile` is known, else `missing`. With `own_profile is None` the status is `missing`, never `not_collected`. The note names the collector version that writes the file.
  - `recapture_list(ledger: list[dict], captures: list[dict]) -> list[dict]` `{host, capture_utc, collector_version, files: [str]}` for hosts whose capture lacks files the newest collector writes.

- [ ] **Step 1: Write the failing tests:** `test_a_file_only_the_newer_collector_writes_is_not_collected_for_an_older_capture`; `test_a_file_the_capture_should_have_but_lacks_is_missing`; `test_a_failed_step_gives_collector_error_not_missing`; `test_an_unknown_collector_never_claims_not_collected` (Review Focus 11); `test_recapture_list_groups_files_by_host`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_profile_ledger.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** both functions; the loader appends these rows to the ledger for every capture.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: profile-based ledger and re-capture list`.

---

### Task 19: Sentinels, probes and `suspect`

**Files:**
- Create: `csa_docx/entity_probes.py`
- Modify: `csa_docx/entity_properties.py` (state `suspect`), the property rule files (optional `probes`)
- Test: `csa_docx/tests/test_entity_probes.py`, fixtures `csa_docx/tests/fixtures/gpresult_verbose_july.txt` and `gpresult_xml_october.txt` (small excerpts that contain the two Microsoft Defender for Identity policies as filtered out / denied)

**Interfaces:**
- Consumes: Task 6 `host_property` rows, the capture folders on disk.
- Produces:
  - `reconcile(model: sqlite3.Connection, capture_root: Path, project: str, rules: list[dict]) -> list[dict]`: for each property rule with `probes`, read the raw files of every capture (decode UTF-16 or UTF-8); a probe that hits while the host's property is empty or `none evidenced` makes the property `suspect` (reason names the probe) and returns a `data_suspect` row `{project, host, property, source_file, probe, hits, note}`.
  - `consistency_suspects(rows: list[dict], captures: list[dict]) -> list[dict]`: a property that has values on hosts of one collector version and is empty on every host of another while its probes hit on the second gives `suspect` for each of those hosts.
  - `accept_suspect(project, *, host: str, property: str, probe: str, reason: str, author: str = "") -> dict`: appends to `hosts/suspect_reviews.csv` (`host, property, probe, reason, author, at`); `reconcile` skips an accepted `(host, property, probe)`.

- [ ] **Step 1: Write the failing tests:** `test_a_probe_hit_with_an_empty_property_is_suspect_not_none_evidenced` (July verbose fixture, property returned empty); `test_the_october_xml_fixture_is_probed_the_same_way`; `test_a_probe_with_no_hits_leaves_none_evidenced`; `test_a_probe_in_a_file_the_map_does_not_read_is_still_reported` (Review Focus 12); `test_a_property_empty_on_one_collector_version_with_hits_is_suspect_on_every_such_host`; `test_an_accepted_suspect_does_not_return_after_a_rebuild` (Review Focus 14); `test_a_sentinel_without_entities_is_unparsed`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_probes.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the module; keep decoding in one helper shared with `entity_captures.py`.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: sentinels, probes and suspect state`.

---

### Task 20: Data releases and lineage

**Files:**
- Create: `csa_docx/entity_release.py`
- Test: `csa_docx/tests/test_entity_release.py`

**Interfaces:**
- Consumes: Task 2 tables (`data_release`, `entity_history`).
- Produces:
  - `new_release(con, *, captures: list[dict], maps_hash: str, rules_hash: str, counts: dict, built_at: str | None = None) -> str`: inserts a `data_release` and returns `"R-0001"`-style id (next free); `captures_hash` is the sha1 of the sorted `host=capture_utc` lines; `previous_release` is the last release or null.
  - `record_history(con, project: str, release_id: str) -> None`: for each current entity upsert `entity_history` (`release_first` kept from the earlier row, `release_last` set to `release_id`); entities absent from this build keep their earlier `release_last`; then copy `release_first` and `release_last` onto `entity`.
  - `link_supersedes(con, project: str) -> int`: for each entity whose (host, kind, key) exists in an older capture of the same host, set `supersedes` to that older entity's id; returns the number linked.
  - `diff_releases(con, r1: str, r2: str) -> dict`: `{added: [{host, kind, key}], removed: [...], changed: [{host, kind, key, attr, old, new}]}` compared per (host, kind, key) from `entity_history` as current at each release.

- [ ] **Step 1: Write the failing tests:** `test_new_release_ids_increment_and_hash_the_capture_set`; `test_unchanged_data_gives_the_same_hashes_and_an_empty_diff` (Review Focus 13); `test_release_first_survives_rebuilds`; `test_a_recapture_links_supersedes_and_the_diff_names_each_changed_attribute` (SrvAdmin `password_required` True to False on one host, plus one account added and one removed); `test_removed_entities_stay_in_history`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_entity_release.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the four functions.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `entity layer: data releases, history and supersedes`.

---

### Task 21: `csa data status` and `csa data diff`

**Files:**
- Create: `csa_docx/data_cli.py`
- Modify: `bin/csa` (`cmd_data` beside `cmd_model`, parser with choices `status`, `diff`, `refresh`, `recapture`), `CSA-COMMANDS.md`
- Test: `csa_docx/tests/test_data_cli.py`

**Interfaces:**
- Consumes: Tasks 17 to 20.
- Produces: `status(db_path: Path) -> dict` `{release, captures: [{host, capture_utc, collector_version, intake_batch, run_status, older_than_latest_intake: bool}], ledger_counts: {status: int}, suspects: [...], recapture: [...]}`; `diff(db_path: Path, r1: str, r2: str) -> dict` (Task 20); `main(argv) -> int` for `status [--json]` and `diff R1 R2 [--json]`. `refresh` and `recapture` print `not available in this version (piece 6)` and exit 2.
- `older_than_latest_intake` is true for a capture older than the earliest capture of the newest intake batch (TETRA: the six July captures against the 29 October batch).

- [ ] **Step 1: Write the failing tests:** `test_status_flags_hosts_older_than_the_latest_intake`; `test_status_counts_ledger_statuses_and_lists_suspects`; `test_diff_prints_added_removed_and_changed`; `test_refresh_and_recapture_are_not_available_yet`.
- [ ] **Step 2: Run** `pytest csa_docx/tests/test_data_cli.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `data_cli.py`; add `cmd_data` to `bin/csa` (back up `bin/csa` first) and the verb to `CSA-COMMANDS.md`.
- [ ] **Step 4: Run** the tests, then `.agents/bin/csa -p tetra-reveloc data status` on the real project with `--db-path` at a scratch file. Expected: tests PASS; status lists 19 captures, flags the six July captures, and shows `not_collected` counts for them.
- [ ] **Step 5: Commit** `entity layer: csa data status and diff`.

---

## Self-review

- **Spec coverage:** entity kinds for the slice (Tasks 3 to 5), properties (6), dependencies and rollup (7), schema and shrink guard (2), loading rules for duplicates, dates, current captures (1, 3, 4), commands and host view and coverage (8), tests and acceptance checks (9), parity (9), go/no-go (10). Event kind, other kinds, renderer, cards and answer-sheet changes are outside this plan by design (spec section 2).
- **Part C coverage:** spec 14.1 is Tasks 17 and 18, 14.2 is Task 19 (with `unparsed` in Tasks 3 and 4 and the property states in Task 6), 14.3 is Task 20, the read-only part of 14.8 is Task 21, acceptance 6 is Tasks 17, 18, 21 and 9, acceptance 7 is Task 19 and Task 10 (f), acceptance 8 (block staleness) is piece 6 and not in this plan. Sections 14.4 to 14.7 (claims lifecycle, answer lineage, pipeline, allowance) are pieces 3, 4 and 6.
- **Part B coverage:** spec 17.1 is Task 11, 17.2 and 17.3's overlay half is Task 12, 17.6 is Task 13, 17.4 is Tasks 14 and 15, 17.5 is Task 15, acceptance 9 and 10 are Task 16. The effect banner's block list depends on the lineage manifests of spec 14.5; until they exist it shows the note "Shown after the next refresh".
- **Types:** `EntityMap`, `entity_id`, `replace_derived`, `compute_properties`, `derive_dependencies`, `build` are named once and used with the same signatures in later tasks.
- **Proportion:** the plan is under twice the length of the spec; code bodies are left to the implementer, tests carry the exact values.
