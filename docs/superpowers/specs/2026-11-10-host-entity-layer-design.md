# Host entity layer: design (piece 1 of 5)

Status: draft for review. Date: 2026-11-10. Owner: Wenzel. Written with Claude.

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

## 2. Scope and decomposition

The wider programme has five pieces. Each gets its own spec, plan and build.

1. **Host entity layer** (this spec): entity store, loaders, host properties, dependencies, application rollup, completeness, host view.
2. Register and table renderer: the framework builds registers and topic tables from the entity set, no model call.
3. Card builder reading entities: summaries and completeness lines instead of a capped matrix sample.
4. Answer-sheet checks: citations resolve to entity ids; a register must cover every entity; the answer step writes prose, exceptions, questions.
5. Migration: section by section, starting with the inventories 4.5 to 4.8.

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
- **Absence is not evidence.** Every value is one of: a value, `none evidenced` (capture exists and shows none), `not captured` (no
  capture file for the host), `unmapped` (a structured source exists that no map covers). NOT_FOUND never becomes a stated absence.
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
capture_folder, source_file, source_table, source_line, origin (`own` or `copied` for a duplicate file), superseded (0 or 1).
Indexes on (kind, host), (kind, key).

`entity_source` (completeness ledger): project, host, capture_utc, source_file, source_table, status (`mapped`, `empty`, `unmapped`,
`failed`), rows_in, entities_out, note. An empty file is `empty`, never skipped: "this host's Remote Desktop Users listing is empty"
is a stored fact.

`host_property`: project, host, name, value, state, capture_utc, entity_ids (JSON list).

`dependency`: project, consumer_host, capability, provider, provider_ref (host, address, name or none),
fallback (yes, no, unknown), entity_ids (JSON list), capture_utc.

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

## 10. Handover to pieces 2 to 5

- Piece 2 renders registers from `v_*` views and the entity ids; every register row shows its source file and line.
- Piece 3 builds a card from `host_property`, `dependency` and the coverage matrix, with a completeness line per register.
- Piece 4 resolves a citation to an entity id and checks that a register has a row for every entity of its kind.
- Piece 5 migrates 4.5 to 4.8 first, then Identity, Management and the remaining sections.

## 11. Risks

- Mapping 74 capture tables takes time. Mitigation: ship the Identity slice first; `coverage` lists unmapped tables so none is ignored.
- Property rules can disagree with the old extractors. Mitigation: parity tests and a reviewed difference list before retirement.
- Dependencies on uncaptured IT providers stay incomplete. This is a data limit, reported as `not recorded`, and becomes a question.

## 12. Decisions taken (with the user, 2026-11-10)

- Scope: all structured capture data, decomposed into five pieces, starting with this one.
- Schema: one generic entity table with declarative maps and typed views (not a typed table per kind, not EAV).
- The host is the anchor; agents and anything running on a host are properties derived from entities.
- Add dependencies and an application rollup; first slice is Identity end to end.
