# Evidence Browser: host and connected-device register plan

## Objective

Give an assessor one screen to identify the IP addresses and named devices seen communicating with application hosts, record what they do, and retain those decisions across discovery rebuilds. Keep application hosts and connected devices visibly and structurally separate. This is a plan; no data or application code has been changed.

## Current state (9 November 2026)

- `discovery-index.sqlite` is the searchable, rebuildable source index. `csa_docx.hostmodel.build()` reads current captures, inventory, selected indexed rows, graph nodes, and `hosts/roles.csv`, then rewrites `hosts/hosts.csv`, `host_links.csv`, `host_services.csv`, `addresses.csv`, and related projections. `roles.csv` is an editable input; it mainly classifies hosts that already enter the register. It is not a suitable record for every unknown IP.
- `hosts/hosts.csv` currently contains both application hosts and peers, distinguished by `in_scope`. For TETRA, it has 170 rows: 24 `Yes`, 2 `No`, and 144 `peer`. `hosts/addresses.csv` has 58 unnamed addresses. `host_links.csv` has 107 captured host-to-host links; 71 have an uncaptured destination with an unverified listening port. `host_services.csv` records 57 configured DNS/time service references. These counts describe the current files, not a validated dependency inventory.
- `hosts/endpoints.csv` is a merged label/zone projection. Reviewed rows survive its own rebuild, but the file mixes hosts and peers and its labels do not feed `hostmodel` address-to-host resolution. TETRA currently has 171 rows. Editing it alone would not solve the assessor's workflow.
- `evidence-matrix.csv` holds source-checked claims; `graph/nodes.csv` and `graph/edges.csv` are append-only derived diagram records that require evidence IDs. TETRA currently has 80 graph nodes and 221 edges. Neither graph CSV is the right CRUD store for user-maintained identity.
- The Evidence Browser already has a read-only **Host network** page (`NetworkMap.tsx`, `/api/systems/{key}/network`) and a read-only System explorer. The network API builds its nodes/edges from live matrix links and `hosts.csv`; its unnamed IP nodes have no persistent identity fields. The browser also has an intake count for unnamed addresses. Both FastAPI and `local_server.py` routes must remain in parity.

## Proposed data contract

Add a project-local, durable **connected-device register** as an input to the host build, not as another generated CSV:

- `hosts/connected_devices.csv`: stable `device_id`, display name, device type, operational role, owning system/team, site/zone, relationship to the application, classification (`supporting IT`, `shared`, `platform`, `OT`, `external`, or unknown), identification state (`unidentified`, `proposed`, `confirmed`, `disputed`), basis/source reference, recorded/reviewed by and dates, `active`, and revision.
- `hosts/device_addresses.csv`: `device_id`, canonical IP/FQDN/alias, address type, first/last seen (if known), source reference, and active state. A device can have multiple addresses; an address may be reused over time. Do not assume that one IP always identifies one machine.
- `hosts/device-audit.jsonl`: append-only create/update/retire/restore records with before/after revisions and source. Write the two CSVs atomically under a project lock and keep a backup. A delete in the UI retires the user identification and aliases; it never deletes capture observations, matrix rows, or graph history. Physical purge is out of scope.

Keep **application host membership** determined by an explicit application scope rule based on the project's capture/inventory/scope data, with a manual scope decision only through a guarded host-classification action. Do not promote a device into an application host merely because it has a name, an address, or a connection. When a connected device is later proven to be an application host, offer a deliberate conversion that checks for an existing host, preserves the audit trail, and runs a preview before rebuilding.

Store user identification separately from source evidence. `confirmed` means an assessor has confirmed identity against a cited source or named owner statement; it does not automatically create a `VERIFIED` matrix row. An unsupported input remains `proposed` or `unidentified`. A source citation can be a matrix E-ID, an exact indexed file/line, or a dated owner-confirmation record. Show conflicting identities without silently choosing one.

## Projection and reconciliation

1. Build a unified read model from `hosts.csv` (application hosts), `addresses.csv` (unidentified observations), `host_links.csv` (captured links), `host_services.csv` (configured DNS/time destinations), `connected_devices.csv` and `device_addresses.csv` (assessor decisions), plus matrix/graph references where useful. Keep `observed connection`, `configured service`, and `documented dependency` as different relationship types. Show direction, port, process, session count, capture/source, and confidence. A sampled connection alone is not a migration dependency.
2. Match observations to registered devices by exact normalised IP or FQDN, then by explicitly recorded aliases. Detect multiple matches, changed/reused addresses, and conflicts with application-host addresses. Never merge on a fuzzy name or subnet. Unmatched observations stay in an **Unidentified addresses** queue.
3. Feed confirmed device aliases into `hostmodel`'s address resolution before it writes `addresses.csv` and `host_links.csv`; keep the device identity in its own register and expose it as a peer projection rather than adding it as an application host. Ensure `endpoints.build()` and `network.build()` use the same resolved identity and provenance. Preserve compatibility for consumers still reading `hosts.csv` by adding a typed adapter during migration, then remove peer assumptions only after callers are updated.
4. On rebuild, recompute observations and links, join them to stable device IDs, retain assessor decisions, surface stale/no-longer-seen devices, and show conflicts. A new capture must not overwrite reviewed identity. A retired device may reappear as an unidentified observation.

## Evidence Browser screen

Add **Hosts & connected devices** to the navigation; retain the existing network diagram as a related view. The default screen has tabs/filters for **Application hosts**, **Connected devices**, **Unidentified addresses**, and **Conflicts**. A searchable table shows name/address, role, site/zone, identification state, last observation, connected application hosts, relationship direction and ports, and source. The detail panel shows all aliases and observations, exact capture or evidence links, configured services, and migration notes such as owner, dependency significance, cutover/validation question, and whether the relationship is only observed.

Actions: create a connected device, attach an unidentified address to a new or existing device, edit identity/role/ownership, mark confirmed or disputed with a basis, retire/restore a device, and remove an incorrect alias. Allow application-host classification edits only through the guarded scope action. Display a before/after reconciliation preview for alias changes and conversion. Do not let the browser edit generated CSVs, discovery captures, matrix rows, or graph rows directly.

Suggested API: `GET /api/systems/{key}/assets` with search/filter/pagination; `GET /assets/{id}`; `POST /devices`; `PATCH /devices/{id}` with expected revision; `POST /devices/{id}/addresses`; `DELETE /devices/{id}/addresses/{address}`; `DELETE /devices/{id}` (retire); `POST /devices/{id}/restore`; and a reconciliation preview endpoint. Implement the same routes in FastAPI and the dependency-free local server, using the existing project registry to constrain paths and prevent cross-project writes.

## Delivery sequence and acceptance checks

1. **Read model:** add a backend assembler and a read-only table/detail screen using the live TETRA files. Verify that all 24 in-scope application hosts and all 58 unidentified address rows are visible, and that peer rows are labelled separately. Count may change after a new capture, so tests should use fixtures rather than hard-coded production counts.
2. **Durable CRUD:** add the register, validation, locking, backups, audit log, API routes and form. Test create/edit/retire/restore, duplicate or conflicting IPs, stale revision, invalid IP/FQDN, project isolation, and both server implementations. Verify a rebuild leaves decisions intact.
3. **Reconciliation:** update `hostmodel`, endpoint and network projections. Test inbound and outbound links, configured DNS/time targets, multi-address devices, unresolved/reused IPs, rejected evidence, and retired devices. Compare before/after TETRA projections; never rewrite old E-IDs or promote peers into application hosts automatically.
4. **Migration:** import existing reviewed endpoint labels into the new register only where the endpoint is clearly a non-application device and an exact address/name match exists. Produce a dry-run report for ambiguous rows and leave those for assessor review. Keep a rollback backup. Add user documentation explaining where to update a device and what `confirmed` means.

Completion means the assessor can identify an address in the browser, save its name and role with provenance, see it under connected devices and on relevant host connections after a rebuild, retire a wrong identification without erasing observations, and still see application hosts as a separate inventory.
