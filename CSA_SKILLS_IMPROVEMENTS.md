# CSA Skills Improvement Report

**Date:** 2026-09-25
**Scope:** All shared CSA agents and skills under `.agents/`
**Learning material:** Section 3.5 (DNS / name resolution, legacy Section 5) and Section 6 (Migration Discovery) of the UTC/DTC with KVM assessment (Brendan folder)

---

## Fundamental principle encoded in this change

A Current State Assessment describes **the application, the system it operates in, and the IT/OT environment it currently runs in**. It is not a report about the evidence. The reasoning process is:

```
Evidence → Correlation → Understanding → Current-State View → CSA Narrative
```

The common failure is stopping one step early and writing the description of the evidence instead of the system. Evidence exists to establish and substantiate the current-state view; the reader should never have to reconstruct the system from the evidence.

This principle is now the first rule in every writer, reviewer, and section skill, and is the basis for all changes below.

---

## What was learned from Section 3.5 (DNS / name resolution)

### What the section went through

The DNS section evolved from a one-line description of resolvers into a structured 5.1/5.2/5.3 layout covering:

- the configured resolvers (server, FQDN, IP, site, interface);
- the resolution behaviour of the AD domain and key service names (A-record set, which sites, which address ranges);
- the Active Directory domain context (membership, OU location);
- the dependent services (authentication, time, patching, email, PKI, file services);
- the drawbridge/isolation consequence (what fails, immediately or gradually);
- name-resolution gaps (zone backup, DNSSEC, conditional forwarders, forest root location).

### Key lessons encoded

1. **Correlation, not enumeration.** The resolver config file, the AD membership record, and the resolution test together establish one system fact: DNS is AD-integrated and the forest root is co-located. Writing each source as a separate sentence ("the resolver file shows…; the AD record shows…; the test shows…") is evidence-centric and was corrected to a single system statement.

2. **Resolver configuration vs resolution behaviour.** These are two different facts and were initially conflated. The skill now requires them to be stated in separate subsections: what is set on the NIC, and what the domain actually resolves to.

3. **The finding is the dependent-services list, not the two resolver IPs.** The operational meaning of a DNS dependency is which services stop working when it does. The resolver table is support; the dependent-services table is the finding.

4. **Isolation consequence is one paragraph, stated once.** Immediate vs gradual behaviour must be distinguished. The AD-integrated DNS / authentication / time-synchronisation failure is a single coupled consequence, not three separate findings.

5. **Forest root location.** When records span both IT and OT address ranges, the forest root location is an assessment gap, not a fact to assert. The skill encodes: "never pick one source over another without naming which is more authoritative and why; if it stays unsettled, it is a gap."

6. **Section fit.** Domain controllers as identity/auth components belong in 3.2, not in the DNS section. Firewall rules permitting port 53 belong in the network/perimeter domain. The DNS section owns name resolution only.

---

## What was learned from Section 6 (Migration Discovery)

### What the section went through

Section 6 required three separate correction passes:

1. **Initial text** said "11 sampled hosts" in five places. The actual capture set was 24 unique hosts across three campaigns (March 2026 tg_discovery: 14 hosts; May 2026 UTC: 7; May 2026 SIGMAP: 5; plus 1 BNE simulation host). The declared fleet is 47 hosts across seven classes (per Section 3.1).

2. **Fleet alignment pass** (S6-G1 to S6-G4) corrected the intro to name the full declared fleet and the three capture campaigns, and scoped each finding to the campaign its evidence covers.

3. **Sampled-count fix pass** (S6-F1 to S6-F5) replaced the remaining "11 sampled hosts" references with campaign-scoped language.

### Key lessons encoded

1. **The three-populations rule.** Declared estate (asset list), discovery population (captured hosts), and each capture campaign are three different populations. A finding drawn from one must never be presented as a fact about another. This was the single most important lesson from Section 6 and is the first structural rule in the `migration-discovery-analysis` skill.

2. **"11 sampled hosts" is a failure pattern, not a data point.** A stale or unexplained count in prose is a MINOR finding at minimum. The reviewer must ask: "count of what, as of when, from which source?" If the reader cannot answer without opening the appendix, the count is wrong or missing its scope.

3. **Application modules vs platform tooling.** UTC/DTC application modules were identified from running processes, not from the installed-programs list. Management agents (CrowdStrike, SCCM, Nessus, LAPS) are platform tooling, not application modules. The skill requires these two groups to be kept separate in the installed-applications table.

4. **Redundancy is a system property, not a per-host fact.** "No Windows Failover Clustering service was found on any captured host" is a finding about the estate's redundancy model (the application handles it), not an absence to assert per host. The skill encodes the correct scoping language.

5. **Patch currency is scoped to the capture set.** "All hosts with May 2026 discovery captures run the Configuration Manager client" is correct scope. "All 11 sampled hosts" implies a fixed subset. "Every host in the estate" is a claim the sample does not support.

6. **Application-centric migration framing.** The section exists so a migration engineer can plan from it without opening the raw discovery packages. The reader-value test is: after reading the section, can you state how the estate fails over, what is patched and when, and which GPOs govern it?

---

## New skills created

### `dns-name-resolution-analysis`

**Location:** `.agents/skills/dns-name-resolution-analysis/SKILL.md`

Covers the DNS/name-resolution domain (legacy Section 5, template domain 3.5). Defines:

- purpose and the six questions the section must answer;
- expected source evidence (resolver config, resolution tests, AD membership, module config, prior assessment records);
- correlation method (resolver config + resolution behaviour + AD membership → one system statement);
- conflict handling (records spanning IT and OT ranges → forest-root gap, not a choice);
- gap handling (zone backup, DNSSEC, forwarders, forest root — scoped, not asserted as absences);
- expected IT/OT terminology;
- section structure (design/expected → observed config and behaviour → dependent services → isolation impact → optional technical note → evidence appendix);
- tables that help (resolver table, resolution-behaviour table, dependent-services table, optional name-resolution path diagram);
- what belongs and what does not (domain controllers → 3.2; host inventory → 3.1; firewall rules → 3.13; NTP mechanics → 3.4);
- validation/review checks (8 points);
- common failure patterns (5 listed);
- completion criteria.

Routing: added to `csa-technical-analyst-agent.md` analysis table and `csa-orchestrator-agent.md` routing table under "DNS / name resolution (legacy Section 5, template 3.5)".

### `migration-discovery-analysis`

**Location:** `.agents/skills/migration-discovery-analysis/SKILL.md`

Covers the Migration Discovery domain (legacy Section 6, template section 4). Defines:

- the **three-populations rule** (declared estate / discovery population / capture campaign) as the first structural rule;
- purpose and the six questions the section must answer;
- expected source evidence (asset list, per-host captures, module config, patch records, GPO results, network flows, prior assessment records);
- correlation method (installed software + running processes + module config + network connections → one system statement per host role);
- conflict handling (host name/role/class discrepancies → assessment gap, never silently resolved);
- gap handling (patch state of uncaptured hosts, MECM collections, App-V coverage, licensing, continuous-capture retention — all scoped to the population);
- expected IT/OT terminology (declared estate, discovery capture set, capture campaign, application module, platform tooling, hot-standby, Left/Right pair, Software Update Point, applied Group Policy, host class);
- section structure (intro → discovery coverage → installed applications → failover/replication → patch tooling → GPO → file transfer → open questions);
- tables that help (discovery-coverage table, installed-applications table, patch/update table, GPO table, optional pairing diagram);
- what belongs and what does not (requirement ratings → owning domain; per-domain isolation consequence → each domain; migration design → design deliverable);
- validation/review checks (10 points);
- common failure patterns (6 listed, including the "stale sample count" failure);
- completion criteria.

Routing: added to both agent routing tables under "Migration discovery (legacy Section 6, template 4)".

---

## Existing skills modified

### `csa-section-writer/references/current-state-reasoning.md` (new file)

**Location:** `.agents/skills/csa-section-writer/references/current-state-reasoning.md`

This is the single source of truth for current-state reasoning across all CSA work. It contains eight sections:

1. **What a CSA is (and is not)** — the subject rule, the reasoning pipeline, the "evidence → description of evidence" anti-pattern.
2. **The subject rule** — with a table of evidence-centric vs system-centric rewrite examples (6 real examples from Section 5 and 6 work).
3. **Three classes of statement** — current-state fact / supporting evidence / assessment gap, with the "not observed" vs "does not exist" table (4 real examples).
4. **Evidence correlation** — the extract → correlate → write → cite method, and the four-step conflict-resolution protocol.
5. **Scope of a statement** — the three-populations rule, with the "11 sampled hosts" anti-pattern.
6. **Terminology** — the IT/OT term list, the "estate" vs "capture set" distinction, the one-term-per-thing rule.
7. **Separating analysis from writing** — the seven-step pipeline (Discover → Extract → Correlate → Validate → Build System View → Write → Review).
8. **The reader-value test** — the eight completion checks in order.

This file is referenced by: `csa-section-writer/SKILL.md`, `csa-quality-review/SKILL.md`, `csa-orchestrator/SKILL.md`, `it-ot-current-state-assessment/SKILL.md`, and both new section skills.

### `csa-section-writer/SKILL.md`

Added a mandatory pre-drafting step: load both `csa-writing-style` and `current-state-reasoning.md` before writing. The writer is now required to check both the subject rule and the prose rules before returning a draft.

### `csa-writing-style/SKILL.md`

Added:
- **"Subject is the system, not the evidence"** as a new rule in the style section, with the tell: "If a sentence needs 'the data', 'the capture', 'the workbook', 'the script output', 'the spreadsheet' or 'the discovery' as its subject, it is describing the evidence."
- A pointer to `current-state-reasoning.md` for the full reasoning rules.

### `prose_lint.py`

Added `EVIDENCE_SUBJECT_RE` detector: a regex that flags sentences whose subject is an evidence artefact (discovery data, table, workbook, spreadsheet, capture, script output, raw file). Verified against the Brendan DOCX: flags 2 legitimate evidence-as-subject passages (both correctly about the discovery set's sample nature), no false positives on the rest of the document.

### `csa-quality-review/SKILL.md`

Review checks renumbered and restructured to 12 checks. New/updated checks:

- **Check 1 (Application/system focus)** — was not a separate check before; now the first check. A passage whose subject is "the discovery data", "the table", "the workbook", "the capture", or "the evidence" is evidence-centric and must be rewritten.
- **Check 3 (Evidence discipline)** — "not observed in the supplied evidence" is not written as "does not exist"; conflicts remain visible and are not silently resolved.
- **Check 4 (IT/OT terminology)** — no consulting- or data-analysis-flavoured terms (e.g. "estate and discovery coverage" where "discovery capture set" is meant).
- **Check 5 (Internal consistency)** — populations (declared estate, discovery population, capture campaign) are not conflated; a stale or unexplained count in prose is a MINOR finding.
- **MAJOR/MINOR severity table** — updated to include the new checks.

### `csa-orchestrator/SKILL.md`

Added the reasoning loop pointer: the orchestrator must ensure the pipeline is Discover → Extract → Correlate → Validate → Build System View → Write → Review, not just Write.

### `csa-evidence-matrix/SKILL.md`

Added "Purpose separation: matrix vs analysis vs CSA" section: the evidence matrix is the supporting technical record; the CSA is the current-state description derived from that evidence. These are related but serve different purposes, and the matrix is an input and traceability mechanism, not the structure or subject of the CSA.

### `it-ot-current-state-assessment/SKILL.md`

Added the core framing: "The CSA describes the system, not the evidence" and a pointer to `current-state-reasoning.md`.

### `csa-quality-review/references/section-scope.md`

Added section-skill pointers:
- 3.5 DNS row now references `dns-name-resolution-analysis`.
- 4 Migration Discovery row now references `migration-discovery-analysis`.

### `csa-technical-analyst-agent.md`

Added two rows to the analysis skill table:
- DNS / name resolution → `dns-name-resolution-analysis/SKILL.md`
- Migration discovery → `migration-discovery-analysis/SKILL.md`

### `csa-orchestrator-agent.md`

Added two rows to the routing table:
- DNS / name resolution (legacy Section 5, template 3.5) → `dns-name-resolution-analysis`
- Migration discovery (legacy Section 6, template 4) → `migration-discovery-analysis`

---

## Terminology improvements

| Before (evidence-centric or generic) | After (IT/OT system language) | Context |
|---|---|---|
| Estate and Discovery Coverage | Discovery capture set / Declared estate vs discovery population | Section 6.1 heading and coverage table |
| The discovery table contains six Windows servers | The application is hosted on six Windows servers distributed across the two operational sites | Section 6 intro |
| The spreadsheet lists an SCCM client on every host | Patching is managed through the IT-hosted Configuration Manager service; every host in the capture set runs its client | Section 6.3 |
| The network capture shows DNS queries to 10.40.228.97 | Name resolution for the application environment is served by two Active Directory-integrated DNS servers, one at each site | Section 3.5 |
| The gpresult output indicates 30 applied GPOs | Every host receives the corporate computer GPO baseline from the INTERNAL domain | Section 6.5 |
| 11 sampled hosts | Hosts with May 2026 discovery captures (7 UTC + 5 SIGMAP) | Section 6, all subsections |
| No Windows Failover Clustering exists | No Windows Failover Clustering service was found in the reviewed systems outputs; redundancy is handled by the application | Section 6.3 |
| There is no backup | The only identified backup mechanism is a scheduled task that copies the previous day's application logs to an IT-domain file share; no OT-resident backup target was identified in the sampled evidence | Section 6.6 |

---

## Evidence-centric → system-centric rewrite examples

These are the real examples used in `current-state-reasoning.md` §2:

| Evidence-centric (avoid in CSA body) | System-centric (write this) |
|---|---|
| The discovery table contains six Windows servers across two locations. | The application is hosted on six Windows servers distributed across the two operational sites. |
| The spreadsheet lists an SCCM client on every host. | Patching is managed through the IT-hosted Configuration Manager service; every host in the capture set runs its client. |
| The network capture shows DNS queries to 10.40.228.97. | Name resolution for the application environment is served by two Active Directory-integrated DNS servers, one at each site. |
| The gpresult output indicates 30 applied GPOs. | Every host receives the corporate computer GPO baseline (29 to 30 policies) from the INTERNAL domain. |
| The raw resolver file confirms two server addresses on Ethernet 3. | The OT-facing NIC on each host carries the only DNS configuration; no interface uses a local or external resolver. |
| The evidence identifies a backup script. | The only identified backup mechanism is a scheduled task that copies the previous day's application logs to an IT-domain file share. |

---

## Behaviours that should improve in the next CSA

1. **The writer will load `current-state-reasoning.md` before drafting** and check the subject rule on every sentence, not just at review time.

2. **The reviewer will run `prose_lint.py`** and use the `EVIDENCE_SUBJECT_RE` warnings as the starting point for the application/system focus check (check 1).

3. **The analyst will correlate before writing.** The seven-step pipeline (Discover → Extract → Correlate → Validate → Build System View → Write → Review) means the writer receives a system view, not a list of source claims to string together.

4. **The three-populations rule will be enforced** in any section that deals with a declared estate vs captured hosts. The reviewer will check that no stale or unexplained count remains in prose.

5. **"Not observed" will always carry its scope.** The reviewer will flag any bare absence statement that does not say what was searched.

6. **Section skills will route correctly** for DNS (legacy Section 5 / template 3.5) and Migration Discovery (legacy Section 6 / template 4), so the analyst loads the right skill for the right domain.

7. **Gaps will be gaps, not absences.** The reviewer will distinguish "not confirmed from available evidence" from "does not exist" and require the former to carry the scope searched.

8. **Tables will answer a technical question** (what components, where hosted, what roles, what dependencies) rather than catalogue discovered data.

---

## Remaining weaknesses and recommended future work

1. **No automatic correlation step yet.** The seven-step pipeline is documented but the `Correlate` step is still a reasoning instruction, not a tool. A `csa correlate` command that groups matrix rows by component/relationship and produces a system-view outline would reduce the chance that the writer starts before correlation is done. This is the most valuable next tooling investment.

2. **prose_lint.py `EVIDENCE_SUBJECT_RE` is a regex, not a parser.** It catches the most common evidence-as-subject patterns but will miss novel phrasings ("According to the discovery package…", "Per the workbook…"). A more sophisticated check would require NLP or LLM-based review, which is out of scope for the current framework but worth noting.

3. **No cross-section consistency tool.** Check 7 (cross-section consistency) in `csa-quality-review` is a manual check. A `csa cross-check` command that compares host names, counts, and dependency descriptions across sections and flags mismatches would reduce the risk of the "11 sampled hosts" class of error recurring.

4. **Section 3.5 and Section 6 skills are UTC/DTC-informed, not UTC/DTC-specific.** They use the UTC/DTC examples (TCSI, Left/Right pairs, SIGMAP) as illustrations, but the rules are general. Future CSAs with different application architectures will need the same reasoning discipline applied to different component sets. The skills are designed to be domain-agnostic in their rules and specific in their examples.

5. **The evidence matrix still lacks verbatim excerpts for many rows.** The schema migration (2026-09-23) moved rows to the canonical 14-column shape but left `evidence_excerpt`, `question`, `inference_reason`, and `confidence` blank for most rows. Filling these would make the traceability chain stronger and reduce the reviewer's need to re-verify against raw sources.

6. **No `csa write` prompt currently injects `current-state-reasoning.md` automatically.** The writer skill loads it, but a `csa write --print` prompt that explicitly names the file would make it harder to skip. This is a minor gap; the current routing is correct.

---

## Files changed or created

| File | Action |
|---|---|
| `skills/dns-name-resolution-analysis/SKILL.md` | **Created** |
| `skills/migration-discovery-analysis/SKILL.md` | **Created** |
| `skills/csa-section-writer/references/current-state-reasoning.md` | **Created** |
| `skills/csa-section-writer/SKILL.md` | Modified — added mandatory pre-drafting reference load |
| `skills/csa-writing-style/SKILL.md` | Modified — added subject rule + evidence-as-subject tell |
| `skills/csa-writing-style/scripts/prose_lint.py` | Modified — added `EVIDENCE_SUBJECT_RE` detector |
| `skills/csa-quality-review/SKILL.md` | Modified — restructured review checks 1–12, added new checks |
| `skills/csa-quality-review/references/section-scope.md` | Modified — added section-skill pointers to 3.5 and 4 rows |
| `skills/csa-orchestrator/SKILL.md` | Modified — added reasoning-loop pointer |
| `skills/csa-evidence-matrix/SKILL.md` | Modified — added purpose-separation section |
| `skills/it-ot-current-state-assessment/SKILL.md` | Modified — added core framing + pointer |
| `csa-technical-analyst-agent.md` | Modified — added 2 analysis-skill table rows |
| `csa-orchestrator-agent.md` | Modified — added 2 routing-table rows |
| `CSA_SKILLS_IMPROVEMENTS.md` | **Created** (this file) |

---

## Australian IT/OT Terminology and Writing Standard

**Date:** 2026-09-25

Australian IT/OT terminology is now a shared foundational capability of the framework: the skill `australian-it-ot-terminology` is loaded on every run by each agent that analyses, writes, edits or reviews CSA text, so it no longer has to be asked for section by section. It is a decision method, not a word-substitution list.

Two principles head the skill:

> The CSA writer is describing an application and the IT/OT system in which it currently operates. Evidence is used to establish, verify and qualify that current-state description. The CSA is not a report about the evidence itself.

> Use the terminology that an Australian IT/OT engineer would naturally use to describe the component, service, dependency, interface or operational relationship being assessed.

### Sources researched

Full list, links and what each contributed: `skills/australian-it-ot-terminology/references/sources.md`.

| Source | Used for |
| --- | --- |
| ASD ISM, Cyber security terminology (glossary) | Definitions of system, system owner, operational technology, OT equipment, server, workstation, network device, gateway, security domain, virtualisation, privileged and service accounts, jump server, remote access |
| ASD ISM guideline titles | Management vocabulary: system hardening, system management, system monitoring, networking, gateways, data transfers |
| ASD/ACSC *Principles of operational technology cyber security* (2024) | OT environment, OT systems, physical processes, vital systems; the six principles |
| ASD/ACSC *Creating and maintaining a definitive view of your OT architecture* | Asset inventory, criticality, connectivity, data flows, protocols and ports, dependencies, zones and conduits, third parties, site details: the closest match to what a CSA describes |
| ASD/ACSC *Remote access to OT environments* | Jump host in a DMZ plus a second jump host inside the OT environment, corporate environment, MFA per jump |
| AEMO AESCSF glossary and 2025 overview | Asset, IT, OT, SCADA, critical infrastructure asset; domain names that treat IT and OT together; OT security depends on IT-run processes |
| Australian Government Style Manual | Australian dictionaries allow both spellings but prefer the British form (-ise, -our) |
| SOCI Act material (Home Affairs) | Legal terms, used only in their legal sense |

Some cyber.gov.au pages refused automated fetching on 25 September 2026; where so, the source file says which mirror or search result confirmed the terms.

### Terminology decisions

- **Choose the term from the object.** Six questions before naming anything: what object, what kind, what role, part of the application or a dependency, OT / supporting IT / shared / platform / external, and the most specific term the evidence supports.
- **IT and OT are classified by what a thing is, not by who uses it.** Active Directory, DNS, NTP, Configuration Manager, PKI, backup, virtualisation and Windows infrastructure are normally enterprise IT services or supporting infrastructure that the OT application depends on. Location and ownership are stated separately ("located at the Rockhampton site, part of the enterprise INTERNAL domain").
- **Most specific term supported**: domain controller, not authentication asset; virtual machine, not infrastructure item; network share, not storage resource.
- **Headings name the subject.** A heading is chosen from its content; "Discovery" is kept only where the subject really is the discovery activity (template Appendix B).
- **Evidence wording only where the qualification matters.** Repeated "the evidence shows / the data shows / the table shows" openers are flagged.
- **Australian English** (-ise, -our, -re, licence noun / license verb, "program", "signalling", day/month/year dates, "cyber security" in prose), without changing product, protocol, command, configuration or quoted names.
- **Established technical terms are kept** (server, VLAN, domain controller, SCADA, PLC, historian, failover and so on). No invented local alternatives.
- **Source hierarchy**: organisation/program terms; Australian legislation; ASD/ACSC/ISM; Australian industry framework (AESCSF); IEC/ISO; vendor; established industry usage. Cyber security terms are not forced onto architecture and application sections.
- **Supersedes** the earlier recommendation in this file to write "discovery capture set", "declared estate vs discovery population" and "platform tooling". The document now says "hosts in the asset list", "hosts with discovery captures", "hosts captured in May 2026" and "management and security agents"; "estate" is not used.

### New skill and files

| File | Purpose |
| --- | --- |
| `skills/australian-it-ot-terminology/SKILL.md` | The standard: principles, decision method, IT/OT classification table, specificity, current-state phrasing, evidence language, headings, Australian English, established terms, source hierarchy, terminology review procedure and severity, examples |
| `skills/australian-it-ot-terminology/references/terminology.md` | Controlled terminology table (Preferred term, Meaning/context, Avoid/use carefully, Example) in 11 groups: application and parts, environment and classification, servers and virtualisation, networks and zones, interfaces and dependencies, supporting services, identity and access, backup/availability/resilience, monitoring/patching/system management, OT equipment and industrial control, operational support and ownership. Plus the lint's three source tables: terms that need review, evidence-centric phrases, Australian spelling |
| `skills/australian-it-ot-terminology/references/sources.md` | Sources, what each contributed, source hierarchy, decisions |
| `skills/australian-it-ot-terminology/scripts/term_lint.py` | Terminology lint (below) |
| `skills/australian-it-ot-terminology/validation/` | Sections 5 and 6 validation: `before.md`, `after.md`, `2026-09-25-sections-5-6.md` |

### Agents using the skill (always loaded)

| Agent | How it uses it |
| --- | --- |
| `csa-evidence-investigator-agent.md` | Names components and services in matrix claims with the controlled terms |
| `csa-technical-analyst-agent.md` | Names and classifies (OT / IT / shared / platform / external) every component and dependency in its analysis |
| `csa-writer-agent.md` | Every mode, alongside `csa-writing-style` |
| `csa-change-authoring.md` | Every replacement, insertion and Word comment `Note` |
| `csa-quality-reviewer-agent.md` | Runs `term_lint.py` and applies the terminology review in check 4 |
| `csa-orchestrator-agent.md` | Treats it as foundational (never routed as a task); every section still goes through the reviewer |

### Existing skills and files changed

| File | Change |
| --- | --- |
| `skills/csa-quality-review/SKILL.md` | Check 4 is now "Terminology and Australian English": the seven-part terminology review, `term_lint.py` as the starting point. Check 5 names the three host groups in plain words |
| `skills/csa-writing-style/SKILL.md` | Spelling and terms always follow the terminology skill, even when the surrounding text does not; `term_lint.py` added to "Check before returning" |
| `skills/csa-section-writer/SKILL.md` | Loads the terminology skill before drafting |
| `skills/csa-section-writer/references/current-state-reasoning.md` | Section 6 points to the terminology skill instead of keeping its own list; populations described in plain words; "estate" removed |
| `skills/migration-discovery-analysis/SKILL.md` (Section 6) | Three host groups renamed in plain words; "Discovery coverage" becomes "Application hosts and discovery scope" with guidance to choose the heading from content; "platform tooling" becomes "management and security agents"; new terminology section with IT/OT classification for Configuration Manager, INTERNAL Group Policy and IT file shares; template headings kept; new check 11 and failure pattern for data-collection language |
| `skills/dns-name-resolution-analysis/SKILL.md` (Section 5) | New terminology section: name the DNS servers for what they are (enterprise domain controllers, not "OT DNS"), location versus ownership, "OT-resident" only for the target state, dependent services named as services; example finding and check 7 updated; two new failure patterns |
| 16 other analysis and section skills | One pointer line to the terminology skill (application-discovery, infrastructure, OT architecture, dependency, network, identity-access, resilience, operations-support, security-posture, evidence-investigator, csa-gap-analysis, executive-summary, technical-explainer, csa-orchestrator, it-ot-current-state-assessment, csa-evidence-matrix) |
| `csa-quality-reviewer-agent.md`, `csa-orchestrator-agent.md`, `skills/csa-quality-review/references/section-scope.md`, `README.md` | Stale check numbers corrected after the 12-check restructure (concision is check 10, section fit is check 12) |
| US spellings in framework prose | authorisation (identity-access skill, orchestrator, both SECTION_COVERAGE copies), organisation and prioritisation (it-ot skill). Left as written: vendor skills (docxengine, mistune, rapidfuzz), the function name `analyze_public_egress`, and the scope map's US-spelled signal terms, which exist to match US-spelled documents |

Backups of every changed file: `backups/au-terminology-20260925/`.

### Terminology lint rules (`term_lint.py`)

```text
python3 .agents/skills/australian-it-ot-terminology/scripts/term_lint.py <file.docx | draft.md> [--heading "<Heading 1>"] [--json] [--strict]
```

| Code | Raised when | Required response |
| --- | --- | --- |
| `TERM_REVIEW_REQUIRED` | A phrase from terminology.md part 12 appears (estate and discovery coverage, discovery coverage, discovery footprint, evidence landscape, technology estate/footprint, estate, landscape, ecosystem, dataset, data/evidence coverage, application sample, evidence sample, sampled, discovery/declared population, capture campaign, solution, as-is, to-be) | Decide what technical concept is meant and name it. Not an automatic replacement: an appendix about discovery may keep "discovery coverage" |
| `SPECIFICITY_REVIEW` | A vague term from part 12 marked "Vague" (technology asset, compute asset, infrastructure item, authentication asset, network service asset, storage resource, platform tooling) | Use the most specific term the evidence supports |
| `EVIDENCE_CENTRIC` | A part 13 phrase opens a sentence (the evidence shows, the data shows, the table shows, information provided, documentation shows, the raw ... output, the discovery scripts, the table below records ...), or evidence phrases occur three or more times in a section | Make the system the subject; keep evidence wording only where the qualification matters |
| `IT_OT_REVIEW` | "OT" attached to an enterprise service (OT DNS, OT Active Directory, OT NTP ...) or an enterprise service described as part of the OT application | Target-state wording is fine (the lint says when it sees it nearby); otherwise state the service as a dependency and where it sits |
| `AU_SPELLING` | A US spelling from part 14, outside code spans, quotes, paths, file names, identifiers and an allow-list of product names (System Center, Local Administrator Password Solution, Organizational Unit ...) | Use the Australian form |

The lint reads its phrase lists from `references/terminology.md`, so the table and the lint cannot drift apart. It never edits a file.

### Terminology corrections (examples)

| Before | After |
| --- | --- |
| Estate and Discovery Coverage | Application Hosts and Discovery Scope (for a table of the application's hosts and which were examined); otherwise Server Environment, Hosting Environment, Infrastructure Overview or Application Components, depending on content |
| technology asset / compute asset / infrastructure item | Windows server, application server, virtual machine |
| authentication asset | domain controller |
| storage resource | network share, SAN, local storage (whichever it is) |
| platform tooling | management and security agents (CrowdStrike Falcon, Configuration Manager client, Nessus agent, Splunk universal forwarder, LAPS) |
| OT DNS servers (for the enterprise domain controllers) | the INTERNAL domain controllers, which also provide DNS |
| Active Directory is part of the OT application stack | The application depends on the INTERNAL Active Directory domain for Windows authentication |
| May 2026 application sample | hosts captured in May 2026 |
| not a full-estate absence claim | does not establish that the other hosts have none |
| DNS-Adjacent Service Dependencies | Services That Depend on Name Resolution |
| Time Synchronization, authorization, centralized | Time Synchronisation, authorisation, centralised |

### Before and after writing examples (validation)

Run against Section 6 of the UTC DTC (Brendan) document and the Section 5 DNS draft. Full comparison of 14 items: `skills/australian-it-ot-terminology/validation/2026-09-25-sections-5-6.md`.

| Before | After |
| --- | --- |
| This section consolidates migration-relevant discovery while keeping the declared asset inventory separate from the evidence actually collected. ... The discovery set is a sample of the estate ... | The UTC/DTC application runs on Central Engine, Message Redirector, Telemetry Processor and TCSI server pairs, SIGMAP servers, maintenance consoles, and UTC and DTC operator workstations at the Rockhampton and Mackay sites. Discovery captures exist for 42 of these hosts ... |
| The table below records software and processes found in the May 2026 application sample ... | The 11 hosts captured in May 2026 run the application components, management and security agents, drivers and tools listed below ... |
| The TCS Backup Script scheduled task was confirmed on every host in the May application/update sample. | Every host captured in May 2026 runs the TCS Backup Script scheduled task ... This log copy therefore depends on a file share in the INTERNAL domain namespace and an INTERNAL domain account. |
| The raw `Get-DnsClient` output from CONTROLLER36 confirms that DNS servers are configured only on Ethernet 3 ... | On CONTROLLER36, DNS servers are configured on Ethernet 3 only; no other interface has a DNS server. |
| All 39 sampled UTC/DTC hosts use the identical pair of DNS resolvers ... | All [count to be confirmed] UTC/DTC hosts examined use the same two DNS servers ... Both are INTERNAL domain controllers, one at each site. |

Result: `term_lint.py` 10 flags before, none after; `prose_lint.py` connector, evidence-ID and evidence-as-subject warnings cleared. Every host name, address and count was carried over or deliberately held back; no unsupported claim was added. The validation also found a count mismatch ("39 sampled UTC/DTC hosts" in the DNS draft against 32 UTC/DTC hosts among the 42 captured in Section 6) and a missing evidence matrix row for the domain-controller role of ROTPRDSRV122 and MOTPRDSRV122.

### How future CSA agents use the capability

1. It loads automatically: evidence investigator, technical analyst, writer, change authoring and quality reviewer all list it as always-loaded. Section skills carry a pointer line; do not copy the table into them.
2. Before naming anything, apply the six-question decision method (SKILL.md part 1) and the IT/OT classification (part 2).
3. Before returning a draft or a change file, run `term_lint.py` with `prose_lint.py` and resolve every flag by deciding what the passage describes.
4. Reviewers apply check 4 in `csa-quality-review` and report terminology findings with location, problem and corrected wording. Corrections reach the document through `csa-change-authoring` (an editorial edit with a plain `Note`, or inside an evidence edit already touching the text).
5. To add or change a term, edit `references/terminology.md`. New review phrases, evidence phrases and spellings take effect in the lint immediately. Record the source in `sources.md`.

### Remaining limits

- The lint is pattern-based. It cannot judge whether "discovery coverage" is legitimate in a given place or whether a classification is right; the reviewer decides.
- `prose_lint.py` reads configuration file names (`.ps1`, `.csv`) as evidence file names; accept them where they name what the system runs.
- The terminology table reflects rail (UTC/DTC, IAMPS) and energy sources most strongly. Extend it with the owner's terms for mining, water or other sectors when those CSAs start.
