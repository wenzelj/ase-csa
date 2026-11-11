# Host entity layer, data management and editing: design (pieces 1, 6 and 7 of 7)

**Superseded implementation direction, 11 November 2026:** The [simple host data plan](../plans/2026-11-11-simple-host-data.md) sets the current scope. This design remains a reference for capture findings and possible later features.

Historical status: approved before the simpler direction replaced it on 11 November 2026. Date: 2026-11-10, extended 2026-11-11 with data management (sections 13 to 16) and editing (section 17). Owner: Wenzel. Written with Claude.

## 1. Why

A CSA assesses whether an OT application can run when it is isolated from IT (the "Drawbridge"). Each requirement asks whether a
capability (time, DNS, identity, patching, backup, monitoring, certificates, ...) is OT-resident and independent of IT, and the
Drawbridge Impact asks which application functions depend on it and what stops during isolation.

Today the answers are built from a card: a capped, lexically ranked sample of evidence-matrix rows (8 per question). This fails for
anything that is one row per entity:

- A register (accounts, groups, group members) needs the complete set. Any cap drops items on a big system.
- The old 4.5 said "no accounts recorded" although 19 hosts list local accounts, because the card's search did not match them.
- The discovery index skips duplicate files, so host counts are understated (Remote Desktop Users showed 4 hosts, 18 had a file).
- Per-host summary strings (`observation`, 74 settings) cannot be re-checked against the rows behind them.

The fix is to hold every structured capture row as an entity that belongs to a host, derive host properties and dependencies from
those entities, and answer from the complete data. Cards (piece 3) then carry summaries and completeness lines, not a sample.

A second class of failure appeared when the 29 October intake was audited (2026-11-11). It is not about retrieval but about how the data
is managed: absence reported when a file was merely not parsed, evidence that is never retired when newer captures arrive, staleness
judged by a proxy, builds with hidden writes, and rules held in two places that disagree. Section 13 lists what happened and why, and
sections 14 to 16 add the mechanisms that stop it. The entity layer alone does not prevent these failures.

## 2. Scope and decomposition

The wider programme has seven pieces. Each gets its own spec, plan and build.

1. **Host entity layer** (this spec): entity store, loaders, host properties, dependencies, application rollup, completeness, host view.
2. Register and table renderer: the framework builds registers and topic tables from the entity set, no model call.
3. Card builder reading entities: summaries and completeness lines instead of a capped matrix sample.
4. Answer-sheet checks: citations resolve to entity ids; a register must cover every entity; the answer step writes prose, exceptions, questions.
5. Migration: section by section, starting with the inventories 4.5 to 4.8.
6. Data pipeline, claims lifecycle and answer lineage (sections 14.4 to 14.6 and 14.8): one ordered refresh with a release identity,
   evidence derived from entities and retired when superseded, and block-level staleness that names what changed.

7. Host screen and editing in the Evidence Browser (section 17): look a host up, see everything on it, and add or edit information
   easily. The edit store and its merge into the entity view (17.1 to 17.3) are part of piece 1; the screen and its API (17.4 to 17.6) are piece 7.

Piece 1 also carries the foundations in sections 14.1 to 14.3 (capture manifest and collector profiles, no silent absence, data releases
and lineage) because they sit in the same store. Pieces 3 and 4 carry sections 14.5 and 14.7 (the allowance object and lineage manifests).
Section 15 lists where each mechanism lands.

Out of scope for piece 1: the renderer, cards, answer-sheet changes, the `event` kind (system, application and DNS/NTP/auth logs, about
7,000 rows; needs a summary design), and document sources (spreadsheets, Confluence, Word tables), which stay in the evidence matrix.

## 3. Principles

- **The host is the anchor.** Pick a host and see everything on it. Everything the CSA needs is mapped from the host.
- **Entities are raw rows, host-scoped.** Software, services, processes, scheduled tasks, listeners, connections, accounts, groups,
  group members, shares, firewall rules, certificates, interfaces, GPOs. Each keeps its capture file and line.
- **Properties are derived, never stored as truth.** "Antivirus", "backup agent", "time source", "enabled local accounts" are computed
  from entities by rules, and always carry the entities that justify them. An agent is software or a service on a host, so it is a
  property, not a kind.
- **Dependencies are derived from properties.** A property that points at a provider (time source, DNS server, domain controller, patch
  source, backup server, certificate issuer, monitoring target) resolves to a provider.
- **Absence is not evidence, and nothing is silent.** Every value is one of: `value`; `none evidenced` (the capture exists, the parser
  is trusted and it shows none); `not captured` (the host has no such file, with a reason: `not collected` by that collector version,
  `missing`, or `collector error`); `suspect` (the raw text hints at data the parser did not return); `unmapped` (a structured source
  that no map covers). NOT_FOUND never becomes a stated absence, and `suspect` is never worded as absence.
- **Captured data is never edited; assessor knowledge is an overlay.** A person adds an entity or fills in what a capture cannot say
  (purpose, owner, notes) in a durable overlay with a basis and a source reference. The overlay survives every rebuild and re-capture, is
  shown next to the captured value, and is worded as `stated`, never `observed`.
- **Everything derived knows its inputs.** A property, dependency, claim or answer block records the entities it was computed from and
  their values, so a change anywhere can be traced to exactly what it affects.
- **Reads have no side effects.** Building a card or a view never writes evidence or settings. Data changes only in the refresh pipeline.
- **One rule, one place.** A fact the card allows (for example a host count) and the check that enforces it come from the same data.
- **Generic, not project facts.** Maps and rules describe capture formats and classification, never one project's facts.

## 4. Findings the design rests on (verified 2026-11-10 on TETRA, UTC DTC, IAMPS)

- The capture collector is shared: UTC DTC uses 38 of the same capture tables as TETRA, IAMPS uses the 7 it has captures for. One set of
  maps serves all projects. TETRA's index has 97 tables, 74 of them capture tables.
- 74 per-host settings are consumed by 19 topic frames (for example `agent.antivirus`, `time.source`, `identity.local_users`). Today they
  are summary strings written by extractors into `model.sqlite` `observation`.
- Volumes differ by orders of magnitude: firewall rules about 14,000, services about 4,700, scheduled tasks about 3,100, certificates
  about 2,400, software about 1,460, accounts 88, groups 356.
- `model.sqlite` already has hosts, addresses, services, flows (128), host links (107), application
  parts and chains (4 chains, 47 steps). 71 of the 107 host links point at a destination that was never captured.
- The index marks identical files `duplicate` and skips their rows. The `files` table keeps `status` and `dup_of`, so the original can be found.

## 4.1 Entity kinds

All host-scoped, loaded from capture tables. Volumes are TETRA, current captures.

| Kind | Source capture tables | Main consumers |
|---|---|---|
| account | local_users | Identity, Vendor Access, Backup, 4.5 |
| account_use | services_inventory (StartName), scheduled_tasks and task actions (RunAs), backup services, startup tasks, DCOM | Identity, Backup, Monitoring, 4.5 |
| group | local_groups | Management, 4.6 |
| group_member | local_admins_membership, remote_desktop_users_membership, gpresult security groups | Management, 4.6, 4.7, 4.8 |
| share, share_access | local_shares, smb_share_access, smb_connections, net use | File Transfer, Storage |
| service | services_inventory, backup_services_products, sql_backup_metadata | Backup, Monitoring, Vulnerability |
| scheduled_task | scheduled_tasks, task actions, trigger results | Monitoring, Backup |
| firewall_rule, firewall_profile | firewall_* (rule joined to its port, address, application, service, security filters by InstanceID) | Perimeter |
| certificate | machine, root, trusted stores, extended, trust chains | PKI |
| software | installed_software, installed_hotfixes, printer_drivers | Asset Inventory, Vulnerability, Patch |
| listener, connection | listening_ports, listeners_by_process, established_connections, process mapping | Network, Perimeter, Drawbridge |
| interface, route, dns_server, dns_cache_entry | ip_interface_config, ip_route, resolver, dns_client_cache | Network, DNS |
| time_source | time_status | Time |
| gpo_applied, gpo_not_applied | gpresult | Group Policy |
| update_setting | windows_update_config, sccm_mecm_check | Patch |
| domain_controller, kerberos | domain controller discovery (file 55), Kerberos ticket detail (file 56), auth_configs | Identity, Isolation |

First slice (section 9) implements account, account_use, group, group_member, domain_controller and kerberos only. The rest follow as
new map files without schema change.

## 4.2 Host properties

A property is a named, derived value per host. The 74 existing setting names are kept (`agent.antivirus`, `time.source`,
`identity.local_users`, `admin.local_admins`, ...), so the 19 topic frames keep working. Each property has a rule file naming the entity
kinds and filters that produce it and how its value is formatted. A property row carries: host, name, value, state (value, none
evidenced, not captured, unmapped), capture date, and the entity ids that justify it. Classification rules (for example which service or
software names count as antivirus, EDR, backup agent) are generic config and may be extended per project in `csa-context`.

## 4.3 Dependencies

A dependency is a derived row: consumer host, capability, provider, fallback present, entity ids, capture date.

- Capability comes from the property (time, dns, directory, patch, backup, monitoring, certificate).
- The provider is resolved in order: a host in the host register (by name or address), a service known only by name or address,
  or `not recorded`.
- Fallback is a property of the capability: second time peer, secondary DNS server, second domain controller, enabled local accounts
  for sign-in when the directory is unreachable.
- If the provider was captured, its own entities are available, so "independent of the IT domain hierarchy" can follow the provider's
  own time source or domain controller.

## 4.4 Application rollup

`application` and `part_member` already exist in `model.sqlite` (reviewed in `parts.json`). The rollup view lists, per application, its
dependencies grouped by capability and provider, with the fallback state and the hosts affected. It is an input to the
requirement conditions (`requirement-conditions`) and to the Drawbridge Impact.

## 5. Schema (derived tables in `model.sqlite`, rebuilt by `build`)

`entity`: entity_id (hash of project, kind, host, key, capture and source line, so two rows with the same key in one file stay distinct), project, kind, host, key, label, attrs (JSON), capture_utc,
capture_folder, source_file, source_table, source_line, origin (`own` or `copied` for a duplicate file), superseded (0 or 1),
release_first, release_last (the data releases it was current in), supersedes (the entity_id of the same host, kind and key in the
previous capture, or null).
Indexes on (kind, host), (kind, key).

`entity_source` (completeness ledger): project, host, capture_utc, source_file, source_table, status (`mapped`, `empty`, `unmapped`,
`failed`, `unparsed`, `not_collected`, `missing`, `collector_error`), rows_in, entities_out, note. An empty file is `empty`, never skipped: "this host's Remote Desktop Users listing is empty"
is a stored fact.

`host_property`: project, host, name, value, state, reason, capture_utc, entity_ids (JSON list), release_first, release_last.

`dependency`: project, consumer_host, capability, provider, provider_ref (host, address, name or none),
fallback (yes, no, unknown), entity_ids (JSON list), capture_utc.

`entity_edit` (the overlay, a reviewed table that a build never drops; section 17.1): edit_id, project, host, kind, key, label, op (`add`,
`annotate`), attrs (JSON), status (`asserted`, `confirmed`, `disputed`), basis_type, source_ref, note, author, at, active, revision. Its file
form is `hosts/entity_edits.csv` with an append-only `hosts/entity-audit.jsonl`, the same pattern as the connected-device register.

`entity_effective` (derived, section 17.2): every capture entity merged with its overlay, with `origin` (`capture`, `assessor`,
`capture+assessor`), `state`, `captured_attrs`, `assessor_attrs`, `edit_ids`, `conflict` and `orphaned`.

`capture` (one row per capture): project, host, capture_utc, folder, collector_version, intake_batch (zip or folder and its date),
run_status (`complete`, `partial`), failed_steps (JSON list from `90_run_summary` and the `RUN_LOG` ERROR lines), files_present.

`data_release`: release_id, built_at, captures_hash (the host to capture_utc map), maps_hash, rules_hash, counts (JSON per kind and per
property state), previous_release.

`data_suspect`: project, host, property, source_file, probe, hits, note. One row per place where the raw text hints at data the parser
did not return (section 14.2).

Typed SQL views (`v_account`, `v_group`, `v_group_member`, `v_account_use`) expose clean columns and are declared in the map files.
Cross-host facts ("SrvAdmin is enabled on 19 hosts") are queries over the views, not stored rows.

## 6. Loading

- Source: the discovery index `rows` and `files` tables. Use current captures only (not archived, not superseded); keep capture date.
- **Read every current capture file for each host**, including files the index marked `duplicate`: copy the rows of the original
  (`dup_of`) and credit them to this host's own capture and file with `origin = copied`. This removes the understated host counts.
- A map file (`references/entity-maps/*.json`) names the source table, kind, key columns, label, attributes with types, constants, and
  the view. Types: `bool`, `int`, `text`, `list`, `datetime`. A column may list alternate names for collector versions.
- Two source modes. `table`: the capture file is parsed into index `rows` (most capture files, for example local_users). `text`: the
  capture file is free text with no index rows (verified: the domain controller discovery file 55 and the Kerberos ticket file 56 have
  none). A text map names an existing parser function (for example `csa_docx.hostmodel.domain_controller_list`) and the loader reads
  the raw file from the capture folder, still for every current capture including duplicates.
- **Dates are never guessed.** TETRA mixes `12/09/2016`, `6/13/2024` and `09-Nov-17`. Keep the raw string; store an ISO date only when
  unambiguous (a day over 12, or a month name); otherwise flag `ambiguous`.
- A mapped column missing from the table fails that source (`failed` in `entity_source`) loudly.
- A map may state expectations ("every host with a capture should have this file") so a missing file shows as a gap.

## 7. Commands and safety

`csa entities build | status | host <HOST> | show <kind> | coverage | deps <APPLICATION>`.

- `csa data status | refresh | diff <R1> <R2> | recapture` are the data-management commands (sections 14.6 and 14.8).
- `csa entities add | annotate | retire | restore` are the command-line forms of the edits in section 17.1; the Host screen is the main way.
- `host <HOST>`: every entity by kind with source file and line, the host's properties with their
  justifying entities, its dependencies, and its ledger rows.
- `coverage`: host by property matrix with the four states, plus unmapped capture tables and hosts with no capture.
- `build` is idempotent, deterministic and rebuilds derived tables only. It refuses to run if a kind would lose rows, as the model
  store does for reviewed tables. Entity ids are stable hashes, so citations survive a rebuild.
- The old extractors keep writing `observation` until each property matches the new one host for host on TETRA. Every difference is
  listed and reviewed before the old extractor is retired for that property.

## 8. Testing

- Unit tests: map parsing, types, ambiguous dates, key normalisation, alternate column names, missing-column failure.
- Fixture index with duplicate files: a duplicate file yields entities credited to its own host with `origin = copied`; an empty file
  yields `empty`.
- Known-value tests on the TETRA data: 19 hosts have local accounts; SrvAdmin is enabled and in the local Administrators group on all
  19; SrvAdmin on MKYPRDOPS110 does not require a password; 12 hosts have an empty Remote Desktop Users listing; INTERNAL\_sDelineadiscovery
  is in the local Administrators group on 14 hosts and not on IPTPRDAPP137, MKYPRDOPS110, ROKPRDOPS110, ROTPRDCLU101, ROTPRDCLU104.
- Cross-project: the same maps build UTC DTC without project-specific code.
- Parity: `identity.local_users`, `admin.local_admins` and `admin.rdp_users` computed from entities equal the old extractor values for
  TETRA, or the differences are listed.
- Shrink guard and idempotence: two builds give identical rows; removing a source file is refused or reported.

## 9. First slice: Identity, end to end

Entities: account, account_use, group, group_member, domain_controller, kerberos. Properties: `identity.local_users`,
`identity.service_accounts`, `identity.domain`, `identity.kdc`, `admin.local_admins`, `admin.rdp_users`. Dependencies: directory and
sign-in (domain controller and KDC, with local-account fallback). Rollup: the identity dependencies of the TETRA/Reveloc application by
provider.

Acceptance:
1. `csa entities build` loads accounts, groups and memberships for all 19 current hosts, including hosts whose files the index marked duplicate.
2. `csa entities host MKYPRDOPS110` shows its accounts (SrvAdmin without password requirement), local administrators, Remote Desktop
   Users, and the directory dependency, each with source file and line.
3. `csa entities coverage` reports Remote Desktop Users as `value` for 7 hosts and `none evidenced` for 12 (6 current captures from
   29 October and 6 SQL Server cluster nodes captured 9 July), with no unmapped identity source.
4. The identity rollup lists each provider and the local-account fallback state for the application.
5. All tests in section 8 pass; the suite shows no new failure.
6. `csa data status` lists the 19 current captures with their collector era (13 from 29 October, 6 SQL Server cluster nodes from 9 July),
   flags the six as older than the latest intake batch, and lists the settings whose files the July collector never wrote as
   `not collected`, not as missing hosts.
7. The probe mechanism is shown on the Group Policy not-applied case with fixtures from both collector formats (July text, October XML):
   both give the two Microsoft Defender for Identity policies, and a file whose raw text names them while the property is empty is
   `suspect`. On the real project the identity probes run on all 19 hosts and every suspect is fixed or accepted with a reason.
8. Changing one entity in a fixture (SrvAdmin password requirement on one host) makes exactly the answer blocks that cite it stale, with
   the old and new value in the reason, and no others.
9. An assessor can add a purpose and an owner to SrvAdmin on one host, and add an account known only from a document, with a source
   reference each. Both survive a rebuild and a re-capture, show beside the captured values, and appear in the 4.5 register as `stated`.
10. On the Host screen an assessor finds MKYPRDOPS110 by name, address or role in two interactions, sees its properties, entities by kind,
    coverage and history, and edits a purpose inline with Enter to save.

## 10. Handover to pieces 2 to 6

- Piece 2 renders registers from `v_*` views and the entity ids; every register row shows its source file and line.
- Piece 3 builds a card from `host_property`, `dependency` and the coverage matrix, with a completeness line per register.
- Piece 4 resolves a citation to an entity id and checks that a register has a row for every entity of its kind.
- Piece 5 migrates 4.5 to 4.8 first, then Identity, Management and the remaining sections.
- Piece 7 reads `entity_effective` and writes only through the edit store, so the screen can never change captured data.
- Piece 6 consumes `data_release`, `supersedes` and the lineage manifests to run the refresh pipeline, retire superseded evidence and report
  block-level staleness (sections 14.3 to 14.6).

## 11. Risks

- Mapping 74 capture tables takes time. Mitigation: ship the Identity slice first; `coverage` lists unmapped tables so none is ignored.
- Property rules can disagree with the old extractors. Mitigation: parity tests and a reviewed difference list before retirement.
- Dependencies on uncaptured IT providers stay incomplete. This is a data limit, reported as `not recorded`, and becomes a question.
- The data-management mechanisms widen the scope. Mitigation: only the foundations (14.1 to 14.3) are in piece 1; the pipeline, claims
  lifecycle and staleness engine are piece 6 with their own spec, and piece 1 stays useful without them.
- An overlay can drift from the captures. Mitigation: edits attach to host, kind and key, a changed capture raises a `conflict`, an entity
  that disappears raises `orphaned`, and neither deletes the edit.
- Easy editing can weaken evidence discipline. Mitigation: every add needs a basis and source reference, assessor data is always shown as
  `stated`, and captured values cannot be edited at all.
- Probes (14.2) can raise false `suspect` flags. Mitigation: a suspect is a question to a person, never an error or an absence, and a
  reviewed suspect is recorded as accepted so it does not return.

## 12. Decisions taken (with the user, 2026-11-10)

- Scope: all structured capture data, decomposed into pieces (five on 2026-11-10, six with data management on 2026-11-11), starting with this one.
- Schema: one generic entity table with declarative maps and typed views (not a typed table per kind, not EAV).
- The host is the anchor; agents and anything running on a host are properties derived from entities.
- Add dependencies and an application rollup; first slice is Identity end to end.
- Editing (2026-11-11): entities must be easy to edit. Assessor input is a durable overlay (section 17) and the Evidence Browser gets a Host
  screen to look a host up and add or edit information.
- Data management (proposed 2026-11-11, awaiting review): sections 13 to 16 add capture manifests and collector profiles, a `suspect`
  state with raw-probe reconciliation, data releases with lineage, claims derived from entities and retired when superseded, block-level
  staleness, read-only cards, and one allowance object shared by the card and the check.

## 13. Why the framework is brittle: what happened and the cause

Found while auditing the 29 October intake (2026-11-11), all on TETRA.

| # | What happened | Size | Cause |
|---|---|---|---|
| 1 | The extractor reported "None found" for the not-applied Group Policy list on the six SQL Server cluster nodes. Their captures list the two Microsoft Defender for Identity policies as denied; the older text format was never parsed for that list. | 6 hosts, 1 setting | An unparsed file reported as absence. |
| 2 | The collector changed between captures. 13 hosts were captured on 29 October, the six SQL nodes on 9 July by an older script that wrote fewer files. | 24 settings exist for only 13 hosts | Collector versions are not tracked, so "not collected" and "missing" look alike. |
| 3 | Evidence is never retired. 435 verified rows cite older captures (mostly 5 or 7 June, three from 9 July) of hosts that have newer ones; 22 claims quote old counts such as "all twelve captured hosts"; 4 document paragraphs repeat them. | 82 citations in 10 saved answers | An append-only matrix with no supersession, and counts typed into claims. |
| 4 | `csa stale` flagged 28 of 29 answers. Every flagged answer I sampled with no named question was flagged because a hash of whole host register rows changed when the register was rebuilt. It names no reason a person can act on. | 28 of 29 | Staleness judged by a proxy; answers do not record what they used. |
| 5 | Building a card wrote evidence rows (E-4050 to E-4054). Refreshing the settings regenerated `hosts.csv`, flows and addresses. Nothing records the order or a release. | n/a | Writes in read paths; no ordered pipeline, no release identity. |
| 6 | 49 evidence rows (E-4000 to E-4049) were appended by hand and duplicate group rows that already existed (E-1086 to E-3033). | 49 rows | The matrix, `observation` and the entity rows all hold copies. |
| 7 | The card said "state the number of hosts"; the check rejected any number. A year in "a 2019 baseline with Log Server" was read as "19 servers". | 2 rules | The same rule written separately in the card text and the check. |
| 8 | A register's evidence was a capped, lexically ranked sample. | 8 rows per question | Covered by the entity layer. |

Five root causes cover them: (C1) absence is not typed, (C2) data is not versioned or identified, (C3) derived things do not know their
inputs, (C4) reads write, (C5) one rule lives in two places.

## 14. Mechanisms

### 14.1 Capture manifest and collector profiles (C1, C2)

- `capture` records each capture's collector version, intake batch, run status and failed steps, read from the capture itself
  (`90_run_summary`, `RUN_LOG`, file inventory) and from the intake batch it arrived in.
- A collector profile (`references/collector-profiles/*.json`, generic) lists the files a collector version writes. The loader compares
  each capture with its profile and gives every expected file a ledger status: `mapped`, `empty`, `not_collected` (the file belongs to
  a newer collector version than the capture's), `missing` (expected but absent), `collector_error` (the `RUN_LOG` shows that step failed;
  for example the `88A` and `88B` steps failed with "A positional parameter cannot be found that accepts argument 'SourcePath'").
- The re-capture list is derived: hosts whose capture lacks files a newer collector would give.

### 14.2 No silent absence: sentinels and raw probes (C1)

- A map or rule may declare **sentinels** (text that must appear for the parser to be trusted, such as the "not applied because they
  were filtered out" heading) and **probes** (cheap raw-text patterns for what a property is about, such as `Defender for Identity`, a
  vendor name, an account name).
- After loading, reconcile: a non-empty file that yields no entities is `unparsed`; a probe that hits in a raw file while the property is
  empty makes the property `suspect`. If a property has values on hosts of one collector version and is empty on every host of another
  while its probes hit, all of those hosts are `suspect`. Each case is a `data_suspect` row.
- A `suspect` appears in `coverage` and in the card, is treated as unknown by the checks, and becomes a Discovery Required question.
  Reviewing one as accepted records the reason so it does not return.

### 14.3 Data releases and lineage (C2, C3)

- Every refresh writes a `data_release` with the capture set, map and rule hashes, and counts. Entities, properties and dependencies keep
  `release_first` and `release_last`.
- A new capture of a host gives new entity ids, linked to the previous ones by `supersedes` (same host, kind and key). Old rows stay as
  history, flagged superseded.
- `csa data diff R1 R2` lists what changed by kind and host: entities added, removed, changed attributes. This is the input to
  staleness (14.5) and to a plain-language change note.

### 14.4 Evidence lifecycle: claims derived from entities (C3, C5)

- Capture-backed claims in the evidence matrix are generated from entities by claim templates, once per release. Each carries `release_id`
  and `entity_ids`. Counts in a claim are computed from the data, never typed.
- When a release changes a claim's inputs, the framework appends the new row and marks the old one `SUPERSEDED` through the existing
  review log (append-only is kept; nothing is edited in place).
- Hand-written rows that cite a capture now superseded are listed as stale candidates. Each is re-derived when an equivalent generated
  claim exists, otherwise reviewed. A claim linter flags literal host counts. Hand rows that duplicate generated ones are retired.

### 14.5 Answer lineage and block-level staleness (C3)

- An answer block's manifest records what it used: the ids of the entities, properties, dependencies and claims it cites, and a content
  hash of each; for a register, also the ids of every entity of the kind it must cover.
- A block is stale when a used item changed, was superseded or removed, or when the register's covered set gained a member. The reason
  says which, with old and new value ("SrvAdmin on MKYPRDOPS110: password required True to False, R6 to R7").
- This replaces the whole-row host hash. A release that changes nothing a block used leaves it current, and `csa refresh` re-answers
  only the impacted blocks.

### 14.6 One pipeline, explicit order, no hidden writes (C4)

- `csa data refresh [--dry-run]` runs: intake, index, entity load, properties, dependencies, derived claims, registers and tables,
  lineage check, stale report. Each stage is idempotent, takes a lock, logs its time and writes the release record.
- Cards, views and renderers are read-only. Evidence is written only in the claims stage.
- Every data-management command prints the release id it ran against.

### 14.7 One allowance object (C5)

- The card carries an `allowance` computed from the entity model: host counts it may state (for example `covered: 19`), host lists, and
  names. The card's instruction text is generated from it, and the answer check reads the same object. A number or name outside it is
  rejected, and one inside it never is. This removes the card and check disagreeing.

### 14.8 Visibility and intake feedback (C1, C2)

- `csa data status` (and a Data health page in the Evidence Browser) shows: the release, capture age per host with the newest intake
  batch marked, a host by expected-file matrix with the ledger statuses, open suspects, stale evidence (rows citing superseded
  captures), and stale answer blocks with reasons.
- `csa data recapture` writes the list of hosts and files to ask the data owner for, derived from 14.1.

## 15. Where each mechanism lands

| Mechanism | Piece | Notes |
|---|---|---|
| 14.1 capture manifest, collector profiles | 1 | `capture` table, new ledger statuses, loader reads profiles |
| 14.2 sentinels and probes, `suspect` | 1 | declared in maps and rules; reconcile step in `build` |
| 14.3 releases, lineage, `supersedes` | 1 | `data_release`, entity columns, `csa data diff` |
| 14.7 allowance object | 3 (card) and 4 (check) | the entity model supplies the numbers |
| 14.5 answer lineage, block staleness | 4 (manifest) and 6 (engine) | replaces the host-row hash |
| 14.4 claims lifecycle | 6 | generated claims, supersession, linter |
| 14.8 `csa data status` (read-only) | 1 | captures, collector era, ledger statuses, suspects |
| 14.6 pipeline, 14.8 `refresh` and `recapture` | 6 | one `csa data refresh` |

## 16. Testing and acceptance for data management

- **Collector versions:** fixtures from both formats of the same file (the July text and October XML Group Policy files) return the same
  not-applied names; a capture missing files its profile lists is `missing`, one from an older collector is `not_collected`, one with a
  failed `RUN_LOG` step is `collector_error`.
- **Probes:** a file whose raw text names a probed policy while the property is empty gives `suspect`, never `none evidenced`; a
  property with values on one collector version and none on another, with probe hits, gives `suspect` on the second.
- **Releases:** two refreshes of unchanged data give the same release hashes and an empty diff; a re-capture gives `supersedes` links and a
  diff naming each changed attribute.
- **Claims:** a claim is regenerated when an input changes and the old row is marked `SUPERSEDED`; the linter rejects a typed host count.
- **Staleness:** changing one entity makes exactly the blocks citing it stale, with old and new value; a register becomes stale when a new
  host adds an entity; a release that changes nothing used leaves all blocks current.
- **Pipeline:** building a card writes nothing (file hashes and matrix length unchanged); `refresh --dry-run` changes nothing.
- **Allowance:** the card's stated count is accepted by the check and any other count is rejected from the same object.
- **Known TETRA values:** the six SQL nodes are `not_collected` for the files the July collector never wrote; the `RUN_LOG` failures of steps `88A` and `88B`
  (seen on ROTPRDREV102; to be confirmed per capture) show as `collector_error`; the Defender policies appear for all 19 hosts.

## 17. Editing entities and the Host screen

Why: much of what a CSA register needs is not in any capture (the purpose of an account, who owns a group, an account known only from a
document or an interview). Today that is written into answers by hand or left as "Not recorded". It should be entered once, in the data,
and flow into every register and card.

### 17.1 The edit store (piece 1)

- A sibling of `csa_docx/connected_devices.py`: `csa_docx/entity_edits.py`, files `hosts/entity_edits.csv` and `hosts/entity-audit.jsonl`
  under the project's `csa-work`, a lock file, atomic writes, a backup before each write, and an expected-revision check on every change.
- Two operations. **Add**: an entity that no capture lists (key, attributes typed by its map, basis type and source reference required).
  **Annotate**: assessor fields on an entity that exists in a capture (purpose, owner, notes, an assessed privilege flag). A map declares
  its `assessor` fields beside its captured attributes; a captured attribute cannot be edited.
- Status: `asserted` (entered with a basis), `confirmed` (checked against a cited source or a named owner) or `disputed` (with a reason).
  Retire and restore never delete. `basis_type` is `document`, `interview`, `site_visit` or `other`; `source_ref` names the source.
- An edit targets host, kind and key (the key compared case-insensitively), not an entity id, so it applies to every capture of that host.

### 17.2 Merging the overlay (piece 1)

- The build writes `entity_effective`: each capture entity with its overlay beside it. Both the captured and the assessor values stay
  visible; `origin` says which.
- A `conflict` is raised when a newer capture gives a different value for an attribute the assessor set. An `orphaned` edit targets an
  entity the newest capture no longer lists. Neither deletes the edit; both are shown for a person to resolve.
- Host properties and dependencies are computed from `entity_effective`, list the asserted entity ids that contribute, and keep the state
  `value`. Registers and cards show assessor data as `stated by <source_ref>`; an answer fact about it uses basis `stated`.
- The edit store is never dropped by a build, and the shrink guard applies to it.

### 17.3 Effect of an edit

- Every edit is a lineage input (14.5). Saving shows its effect: the registers that will change and the answer blocks that become stale,
  or "shown after the next refresh" when lineage is not available yet.

### 17.4 The Host screen (piece 7)

A **host page** in the Evidence Browser, reached from a **Look up a host** box that is always visible on the Hosts and devices screen.
It replaces the read-only application-host detail there; the Devices, Unidentified and Conflicts tabs stay.

- **Lookup:** type a name, FQDN, address or role; matches appear as you type, with role, site, newest capture and counts. Recent hosts
  are kept. A second box finds an entity across hosts ("where is account SrvAdmin, group OT_Tele_LAdmins").
- **Header:** name, role, site, application, newest capture and its collector era, coverage badges (files not collected, suspects), and an
  **Add information** button.
- **Overview:** the host's properties with their state and the entities that justify them, and its dependencies.
- **Entities:** a kind selector with counts, then a table per kind. Captured columns are read-only and grey, with the source file and line;
  assessor columns are editable in place (click, type, Enter saves, Esc cancels). A badge shows `capture`, `assessor` or `disputed`.
  Toolbar: **Add <kind>** (a form generated from the map), **Paste rows**, **Show retired**.
- **Coverage:** this host's ledger by file (mapped, empty, not collected, missing, collector error, suspect) and what to ask the data owner for.
- **History:** this host's edits and data releases.

### 17.5 Easy to edit: what that means

- The add form shows only the fields of the kind and asks for a key and a source reference; host and kind are preselected, the last basis
  is remembered, and Enter saves.
- Inline editing for assessor fields; a stale revision keeps what the person typed and says who changed the row.
- **Paste rows** accepts a tab or comma separated table with a header row, shows each row as OK or with its error, and commits all rows or
  none.
- A duplicate key is stopped with a message that names the existing row. Retire asks once; restore is one click.
- A new application host with no capture is added through the existing connected-device conversion path, not a second mechanism.

### 17.6 API (piece 7)

Under `/api/systems/{key}`: `GET hosts?q=`, `GET hosts/{host}`, `GET hosts/{host}/entities?kind=&q=&include_retired=`, `POST
hosts/{host}/entities`, `POST hosts/{host}/entities/{kind}/{key}/annotate`, `POST entity-edits/{id}/state|retire|restore`, `POST
hosts/{host}/entities/import/preview` and `.../import`, `GET entities/search?kind=&q=`, `GET hosts/{host}/history`, `GET entity-kinds`. Errors
follow the Assets API: 404 unknown host, 409 stale revision (the person's text is kept), 422 invalid.

