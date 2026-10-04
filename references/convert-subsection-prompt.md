# Prompt: move an old-format CSA into the template, one subsection at a time

Use: replace `{SECTION}` (for example `3.4`) and `{PROJECT}` (for example `tetra-reveloc`), then give the whole prompt to one fresh agent session (Codex, Claude Code or Hermes) started in the CurrentStateAssessments folder. One subsection per session.

---

You are converting subsection **{SECTION}** of the CSA for project **{PROJECT}** from the previous assessment (old format) into the CSA template. Work through the CSA framework in `.agents/` and its rules; do not edit the Word document yourself.

## The test

For every requirement in {SECTION}, does the selected evidence let the reader answer it **accurately, concisely and with the correct uncertainty**? You are not preserving the old document. You are answering the requirements, using the old document as one evidence source and the discovery captures as the stronger one.

## Read first (and nothing else until a step says so)

1. `.agents/csa-core-rules.md`, `.agents/skills/csa-writing-style/SKILL.md`, `.agents/skills/australian-it-ot-terminology/SKILL.md`.
2. `csa -p {PROJECT} scope {SECTION}`: the requirements, what the subsection must explain, what it owns, and what is not here.
3. `.agents/skills/csa-document-template/references/requirement-map.csv`, the rows for this domain: what answers each requirement, what does **not** answer it, the Discovery Information aspects, the capture tables to check.
4. `.agents/references/section-file-format.md` (the section-file shape) and `.agents/docs/convert-old-template-plan.md` section 13 (the transformation rules).
5. The worked reference: `TETRA/06 REVELOC TETRA/csa-work/convert/3.5/answer-plan.csv`, `csa-work/sections/3.05-dns.md` and its review notes below.

## Steps

1. **Brief and old facts.** `csa -p {PROJECT} convert {SECTION} --stage brief` and `--stage prepass`. Read `csa-work/convert/{SECTION}/brief.md`. Also search `csa-work/legacy/facts.csv` (when present) or `csa-work/legacy/blocks.jsonl` for this domain's requirement terms **outside** the old section with the same name. Relevant facts often sit in the Discovery Summary, the dependency-impact table, "Finding comments, recommendations" subsections (mine them: keep the factual sentences) and the SQL cluster narrative.
2. **Captures first.** For each requirement, check the capture tables named in `requirement-map.csv` (`csa index tables`, `csa index rows <table>`, `csa index search`, `csa hosts show <HOST>`). Count hosts from the captures, not from the old text. The host register is `csa-work/hosts/hosts.csv`: say which of the captured hosts each fact covers.
3. **Evidence rows.** Every fact you will use needs a VERIFIED row that quotes the capture line (`csa ev append`, with `source_title` naming the capture folder and file so the automatic source check approves it). Old-document facts already have pre-pass rows (`gap_or_action: legacy L-nnnn`). Where a capture disagrees with the old document, add a CONFLICTING row and use the capture. For every question nothing answers, add a NOT_FOUND row whose `source_title` is the scope you searched.
4. **Answer plan.** Write `csa-work/convert/{SECTION}/answer-plan.csv` with the columns `legacy_ids, req_id, statement_type, fact, evidence_scope, destination, confidence, transformation, gap_generated` (one row per fact; see the 3.5 reference). Destinations: `REQ <id> / Current State`, `REQ <id> / Rating`, `{SECTION}.1 Discovery Information / <Aspect>`, `{SECTION}.2 Drawbridge Impact`, `8 Discovery Required`, `MOVED <subsection>`, `roadmap (convert/parked.md)`, `none`. Every requirement needs a Current State row and a Rating row; every gap needs `DR-<AREA>-nn <what to confirm>`.
5. **Section file.** Write `csa-work/sections/<order>-<slug>.md` (block `domain`) from the answer plan only: the requirement rows (Current State in a short paragraph; Rating Met, Partially Met, Not Met or Not Applicable), Discovery Information rows (Aspect / Configuration Observed / Coverage / Source), an optional one-paragraph note, one Drawbridge Impact paragraph, and the Evidence table keying every statement to its E-ids. Run `csa check-section <file>` and fix every ERROR; run the prose lint.
6. **Place and account.** `csa -p {PROJECT} place <file>` (tracked changes; you do not approve anything, Wenzel accepts or rejects in Word). Write `csa-work/convert/{SECTION}/outcomes.csv` (`id,outcome,target,reason`) for every legacy L-id in the brief the plan does not use: MOVED, DUPLICATE or NOT_USED with a reason. Then `csa convert {SECTION} --stage ledger`.
7. **Report** in five lines: requirements answered and their ratings, Discovery Required items raised, facts moved elsewhere, conflicts with the old document, anything you could not settle.

## Transformation rules

- **Facts, not narratives.** One statement per fact; consolidate repeats into one current-state statement with all their L-ids.
- **Separate the kinds:** observed configuration, evidence scope, requirement assessment, gap or unknown, consequence, recommendation. Each goes to its own field.
- **Recommendations never enter the CSA.** Their factual basis becomes a finding. The action goes to the roadmap list, or, when it is really an open question, to Discovery Required.
- **Keep the uncertainty.** "Not observed", "not tested" and "not confirmed" stay as they are. An old absolute ("no X exists") becomes "no X was evidenced" plus a Discovery Required row, unless a capture proves the absence.
- **Correct the scope.** State the host set the captures show (for example "11 of 12 hosts; none on ROTPRDLOG102"). Old "all six hosts" statements usually describe one capture wave only; old "all hosts tested" claims must be checked.
- **Coverage / Source is never empty** and names both the hosts and the evidence type ("All 12 captured hosts; resolver configuration", "5 hosts; role-aware resolution tests").
- **Ratings come from evidence**, per requirement. The old readiness score (RAG, "drawbridge ready") is not carried.
- **Stay in the subsection.** Content that answers another requirement is MOVED; a mention of another domain is at most one clause of cause or context.
- **Story, not inventory.** Conclusion first, each fact once, full sentences, host names in prose (an IP address only where no name was found), long host and address lists in the table. Never mention the previous assessment, its headings or its version, in the text or the comments.
- **Never infer.** When a conclusion needs a step the evidence does not show, either find the capture that shows it or write the narrower statement. Where general platform knowledge does the linking (for example "the addresses the AD domain name resolves to are its domain controllers"), cite the capture that shows the addresses and keep the claim to what that shows.

## Lessons from 3.5 DNS (check every section for the same traps)

- **Keep the requirement row and the table consistent.** The Current State said "all twelve hosts use domain controllers" while the table said one host's resolvers were unnamed. The link (the domain name resolves to those addresses) was in another evidence row that was not cited. Cite the row that closes the gap, or narrow the statement.
- **Count what the capture counts.** A query test of 22 names included `localhost`, so it resolved 21 DNS names. Check list contents, not only list lengths.
- **Check which setting source the text implies.** No Group Policy set DNS client settings, so the section must not say the resolvers come from policy. Only claim a setting source you have seen.
- **Hosts-file entries and similar local overrides are facts, not a fallback.** Record them; their only role in the Drawbridge paragraph is what keeps working.
- **Discovery Required "How to obtain" must fit the question.** A network-zone question is answered by the network team or the address register, not by more host captures.
- **Evidence gaps in the capture set are facts.** State them (for example "no dependency summary for ROTPRDLOG102") in Coverage / Source rather than smoothing them over.

## Section guidance

| Section | Answer with | Keep out / treat as a gap |
| --- | --- | --- |
| 3.1 Asset Inventory | Host register: hosts, roles, sites, function, known dependencies | Architecture narrative (to its domain or Section 5) |
| 3.2 Identity | Enterprise AD dependence, domain service accounts, Kerberos evidence, jump-host authentication, VNC/SSH paths | Remediation prose; PAM coverage unknown → Discovery Required |
| 3.3 PKI | Certificate issuers from the captures | Renewal, CRL/OCSP and isolation behaviour not established → targeted Discovery Required rows; no conclusion beyond the evidence |
| 3.4 Time | Active enterprise sources, host coverage, pending time.windows.com peers, no OT-local source evidenced, consequence once | Repetition |
| 3.5 DNS | Resolvers, host coverage, names that must resolve, local overrides, no fallback evidenced, consequence once | Repetition; successful resolution is not independence |
| 3.6 Network | Zones, conduits, cross-zone flows, network dependencies | Internet/SMTP (3.17), firewall-control evidence (3.13); zone/SL-T assignment unknown → Discovery Required |
| 3.7 Storage & Data Transfer | Local storage, IT file shares, SMB paths, transfer mechanisms, scanning, push versus pull | General SQL, Azure, DNS or infrastructure dependencies; USB-over-IP licensing is not file transfer |
| 3.8 Management Access | Jump hosts, RDP, VNC, SSH, enterprise-domain authentication, admin groups (captures) | Session monitoring / PAM gaps → Discovery Required |
| 3.9 Monitoring | SCOM, Splunk, EDR presence and host coverage | Retention, tamper protection, OT-resident capability stated as unknown |
| 3.10 Patch | Tooling, MECM/WSUS dependency, observed versions and patch dates, maintenance windows | Cadence and escalation process not documented → Discovery Required; tooling detail to 5.4 |
| 3.11 Backup | PPDM evidence on the SQL nodes versus unconfirmed backup of the application hosts | Offline rebuild, restore testing, backup accounts, independence → gaps; Availability Group replication is not a backup |
| 3.12 Isolation | Whether a tested three-month plan, thresholds and manual fallback processes exist | A dependency-impact table is an input, not a plan; if not evidenced, say so precisely and raise Discovery Required |
| 3.13 Perimeter | Firewall-profile evidence, boundary-device inventory, rule-review status, external exposure, management-plane ownership | Host firewall rules are not boundary devices; unknown rules or ownership → gaps |
| 3.14 Vulnerability | Endpoint protection coverage (VULN-02) | CrowdStrike does not prove a vulnerability register, cadence or OT-independent process (VULN-01) |
| 3.15 Infrastructure | Virtualisation hosting, hypervisor management, privileged accounts, loss-of-IT-management impact | Physical server and general dependency detail is context only |
| 3.16 Supply Chain | Only evidence about vendor support and remote-access paths | Product names are not access paths; vendor identities, methods, approvals, monitoring not captured → Discovery Required |
| 3.17 Internet & SMTP | Direct or proxy route, public HTTPS, Azure private endpoints (kept distinct), telemetry, Windows Update, corporate SMTP relay | Private routed services are not internet |
| 5.2 Installed Applications | Compact component inventory by host and function | Full installed-software dumps |
| 5.3 Failover & Replication | Listeners, nodes, Availability Groups, observed connectivity, designed failover, what was or was not tested | The 80-block narrative |
| 5.4 Patch Tooling | MECM/WSUS, vendor packages, lifecycle, deployment, settings, maintenance windows | |
| 5.6 File Transfer | Observed shares, SMB connections, local paths, transfer tools, removable-media controls, direction | Otherwise focused Discovery Required |
| 8 Discovery Required | One structured row per gap: requirement IDs, evidence needed, reason, rating impact, owner/source, how to obtain, status | Narrative gaps |
| 2.1 Executive Summary (last) | System, assessed scope, critical dependencies, isolation posture, major gaps, evidence limits | Recreating the legacy Discovery Summary |

## Done when

- Every requirement of {SECTION} has a Current State, a Rating and Discovery Information rows with a real Coverage / Source, or a Discovery Required row.
- Every statement in the section file has E-ids in its Evidence table, and every E-id is approved by the source check or decided by a person.
- `csa check-section` passes; no recommendation, no IP address in prose where a host name is known, no mention of the old document.
- The ledger shows every legacy fact in the brief as used, moved, duplicate or not used with a reason.
