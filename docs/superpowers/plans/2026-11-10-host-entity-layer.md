# Host Entity Layer (piece 1, Identity slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load every structured capture row into host-scoped entities in `model.sqlite`, derive host properties and dependencies from them, and prove the Identity slice (accounts, groups, memberships, domain controllers) is complete and correct for all 19 TETRA hosts.

**Architecture:** Declarative map files (`references/entity-maps/*.json`) turn capture tables into `entity` rows, reading every current capture file including ones the index marked duplicate. Rule files derive `host_property` rows (keeping today's 74 setting names) and `dependency` rows. A `csa entities` command builds and shows them. Derived tables only; the old extractors keep running until parity is shown.

**Tech Stack:** Python 3.14 (`.agents/.venv`), sqlite3, pytest. Code in `.agents/framework/csa_docx/`, CLI verb in `.agents/bin/csa`.

**Spec:** `.agents/docs/superpowers/specs/2026-11-10-host-entity-layer-design.md`

**Stories:** `improvements/stories/S560` to `S570` implement this plan (Task 9 is split into S568 known values and S569 parity; Task 10 is S570, a human decision). Run them with `improvements/tools/run-story.sh` or read `python3 improvements/tools/story.py next`.

## Global Constraints

- Current captures only: `captures.archived = 0 and superseded_by is null`. Keep `capture_utc` on every row.
- Read every current capture file for each host, including `files.status = 'duplicate'`: copy the rows of `files.dup_of`, credit them to this host's own file, `origin = 'copied'`.
- Dates are never guessed: keep the raw string, store ISO only when unambiguous (day over 12, or a month name), otherwise flag `ambiguous`.
- States are exactly: `value`, `none evidenced`, `not captured`, `unmapped`. NOT_FOUND never becomes a stated absence.
- Maps and rules are generic (capture formats and classification), never project facts. Project extensions go in `csa-context`.
- Derived tables are dropped and rebuilt; a build that makes any kind lose rows is refused unless that kind is named in `--allow-shrink`.
- Do not change existing extractors, `observation`, or `host_settings` in this plan. Back up any shared framework file before editing it (`<name>.bak-<date>-<tag>`).
- Run tests from `.agents/framework`: `../.venv/bin/python -m pytest csa_docx/tests -q`. Baseline: 1 failure, `test_doc_spec.py::test_every_part_of_the_template_is_classified_by_structure`, present before this work.
- Commits stage only the files named in the task; the user chooses the branch.

## Review Focus

1. A duplicate file whose original host is not a current capture: copied rows must still load (the original's rows are read by `dup_of`, not by host).
2. A capture whose mapped column is renamed (collector version): the source is `failed` in the ledger, never silently empty.
3. The same account written `SrvAdmin` and `srvadmin` on different hosts: keys compare case-insensitively, the original spelling is kept as label. A domain-qualified name (`INTERNAL\srvadmin`) is a different principal and stays a different key.
4. A host captured twice (older capture superseded): the older capture must not add entities or double counts.
5. Two rows with the same key in one file (for example two services of the same name): both load, with different ids.

---

## File Structure

| File | Responsibility |
|---|---|
| `csa_docx/entity_maps.py` (create) | Map schema, validation, loading, value typing, date parsing |
| `csa_docx/entity_store.py` (create) | `model.sqlite` tables for entity, entity_source, host_property, dependency; ids; shrink guard |
| `csa_docx/entity_loader.py` (create) | Index to entities: table mode, text mode, duplicates, ledger |
| `csa_docx/entity_properties.py` (create) | Rule files to `host_property` rows with the four states |
| `csa_docx/entity_dependencies.py` (create) | Dependencies and the application rollup |
| `csa_docx/entity_cli.py` (create) | `build`, `status`, `host`, `show`, `coverage`, `deps` |
| `references/entity-maps/*.json` (create) | Identity maps (section 5 of the spec) |
| `references/entity-properties/identity.json` (create) | Identity property rules |
| `bin/csa` (modify) | `cmd_entities` verb, same pattern as `cmd_model` (line 3769) |
| `CSA-COMMANDS.md` (modify) | Document `csa entities` |
| `csa_docx/tests/test_entity_*.py` (create) | One file per module, plus known-value tests |

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
- [ ] **Step 5: Commit** `entity layer: host properties with the four states`.

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

---

## Self-review

- **Spec coverage:** entity kinds for the slice (Tasks 3 to 5), properties (6), dependencies and rollup (7), schema and shrink guard (2), loading rules for duplicates, dates, current captures (1, 3, 4), commands and host view and coverage (8), tests and acceptance checks (9), parity (9), go/no-go (10). Event kind, other kinds, renderer, cards and answer-sheet changes are outside this plan by design (spec section 2).
- **Types:** `EntityMap`, `entity_id`, `replace_derived`, `compute_properties`, `derive_dependencies`, `build` are named once and used with the same signatures in later tasks.
- **Proportion:** the plan is under twice the length of the spec; code bodies are left to the implementer, tests carry the exact values.
