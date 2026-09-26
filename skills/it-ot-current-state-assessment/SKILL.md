---
name: it-ot-current-state-assessment
description: Use when planning, structuring, or writing up a current state assessment of IT and/or OT systems, applications, network architecture, or security posture — covers methodology, reference frameworks, and deliverable structure.
---

# IT/OT Current State Assessment

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

A current state assessment (CSA) establishes a factual, evidence-based baseline of an organisation's technology environment — what exists, how it's architected, how mature its practices are, and where it stands against a reference framework — before recommending any future-state changes. Use this skill whenever asked to plan, run, or document a CSA covering IT infrastructure, OT/ICS environments, applications, or security posture, including IT/OT converged environments.

Do not skip straight to recommendations. A CSA's value comes from being an honest, verifiable snapshot of *what is*, separated from *what should be*. Findings must be traceable to evidence (an inventory record, an interview, an observed config, a scan result) — never inferred or assumed.

**The CSA describes the application and its system, not the evidence.** It is a system- and application-centric document: what exists, how it is architected, what it depends on, how it operates today. Evidence exists to establish and substantiate that view; it is the traceability record behind the statements, never the subject of them. Reasoning runs `Evidence → Correlation → Understanding → Current-State View → CSA Narrative`, not `Evidence → Description of Evidence`. The full working rules (subject rule, fact/evidence/gap classes, "not observed" vs "does not exist", correlation, scope, IT/OT terminology) live in `csa-section-writer/references/current-state-reasoning.md` and are binding on every section this methodology produces.

## 1. Scope and prepare

Before any data gathering:

- Define explicit boundaries: which sites, business units, systems, network zones, and asset classes are in scope. For OT, explicitly state whether safety instrumented systems (SIS) are in scope — they usually need separate, more careful handling.
- Identify the reference frameworks the assessment will be measured against (see section 4) — agree these with the client/stakeholder up front so findings are structured consistently.
- Collect existing documentation first: network diagrams, asset registers, vendor contracts, security policies, prior audit findings, incident history, org charts. Gaps between this documentation and what discovery later finds are themselves a finding.
- Secure sponsorship from both IT and operations/engineering leadership. In OT environments particularly, operations must approve any active scanning, sensor placement, or physical access — passive/non-intrusive methods are the default.
- Set explicit non-goals: a CSA describes current state and gaps: it is not a remediation plan (that's a separate roadmap deliverable built from the findings).

## 2. Discover and inventory

Goal: build a complete, evidenced asset and application inventory. Expect the real environment to differ materially from documentation — OT discovery routinely finds 30–40% more devices than existing records show; IT discovery routinely finds undocumented SaaS/shadow IT.

**IT infrastructure** — inventory across these domains:
- Hardware & software: servers, endpoints, network gear, applications, SaaS subscriptions, with lifecycle/EOL status
- Network: topology, bandwidth utilization (measure peak, not average), segmentation, firewall posture, redundancy
- Storage & backup: capacity, tiering, and *tested* restore procedures (not assumed recovery capability)
- Identity & security controls: endpoint protection coverage, MFA coverage, IAM model, email security, patch cadence/compliance
- Cloud: vendor agreements, resource sizing/utilization, identity sprawl, data residency
- Support model: internal/outsourced split, vendor relationships, preventive maintenance execution

Useful tooling: endpoint/asset discovery agents (e.g. Lansweeper, Microsoft Endpoint Manager), cloud utilization reports (AWS Compute Optimizer, Azure Advisor), network flow analysis over a representative period (aim for 90-day peak visibility where possible).

**Applications** — inventory each application with: owner, business capability supported, technical fit (architecture quality, maintainability, supportability, vendor viability), functional fit (how well it meets business need), integration dependencies, hosting model, data classification, lifecycle stage. This inventory feeds the TIME/6R rationalization scoring in section 4.

**OT/ICS** — prefer passive, non-intrusive discovery:
- Deploy passive network monitoring/taps on key segments for a minimum of ~2 weeks to capture full production cycles (including infrequent batch/maintenance traffic) rather than actively scanning control networks, which risks disrupting real-time devices
- Analyze industrial protocol traffic (Modbus, DNP3, EtherNet/IP, OPC, etc.) to identify device types, firmware versions, and communication patterns
- Conduct physical walkthroughs of control rooms, panels, and field installations — many OT assets are never visible on the network (isolated PLCs, serial links, air-gapped HMIs)
- Capture: make/model/firmware version, patch status, network location (map to Purdue level), criticality/safety relevance, remote access paths, vendor support status

## 3. Map the architecture

**OT — Purdue Model**: place every discovered asset into its level to expose segmentation reality vs. documented/intended design.

| Level | Description | Examples |
|---|---|---|
| 0 | Physical process | Sensors, actuators, valves, motors |
| 1 | Basic control | PLCs, RTUs executing control logic |
| 2 | Supervisory control | HMIs, SCADA |
| 3 | Site operations | MES, historians, site-level servers |
| 3.5 | Industrial DMZ | Firewalls, data diodes, jump servers — the IT/OT boundary |
| 4 | Enterprise IT | ERP, Active Directory, business systems |
| 5 | External/internet | Internet-facing systems |

Zones and conduits (ISA/IEC 62443): a *zone* groups assets sharing common security requirements (often aligned to Purdue levels or sub-divided further by criticality); a *conduit* is the communication path between zones, which must be secured to the level of the most trusted zone it touches. During assessment: map actual observed traffic against this model to find violations (e.g. Level 4 reaching Level 0–2 directly), verify firewall enforcement between levels, confirm shared services (historians, remote access) terminate in the 3.5 DMZ rather than deeper in OT, and check where remote access actually lands.

**IT — enterprise architecture**: use a layered view (business capability → application → data → technology/infrastructure, as in TOGAF's ADM Phase B–D) to show how applications and infrastructure support business capabilities, and where architecture debt, redundancy, or single points of failure sit.

## 4. Assess against reference frameworks

Pick frameworks that match scope and stakeholder expectations; combining a maturity framework with a domain-specific standard is normal.

| Domain | Framework | What it gives the assessment |
|---|---|---|
| OT/ICS security | IEC 62443 | Security Levels SL-1 to SL-4 per zone (most orgs target SL-2: protection against intentional violation using simple means); zone/conduit model |
| OT/ICS (US govt-aligned) | NIST SP 800-82 | ICS-specific control baseline, complements IEC 62443 |
| Sector-specific OT | NERC CIP (utilities), API 1164 (pipeline SCADA), NIS2 (EU) | Regulatory-specific control requirements |
| General cybersecurity maturity | NIST CSF 2.0 | Six functions — Govern, Identify, Protect, Detect, Respond, Recover — each rated by Implementation Tier: 1 Partial (ad hoc, undocumented) → 2 Risk Informed (emerging, reactive) → 3 Repeatable (documented, proactive) → 4 Adaptive (data/threat-intel driven, embedded in decisions). Build a "current profile" of outcomes per category, then a tier rating |
| Enterprise/IT architecture | TOGAF ADM | Structured current-state ("Baseline Architecture") vs. target-state comparison across business, data, application, technology layers |
| Application portfolio | Gartner TIME model | Score each app on Technical Fit (quality/maintainability) × Functional Fit (business value) → Tolerate (high tech/low func), Invest (high/high), Migrate (low tech/high func), Eliminate (low/low) |
| Application portfolio (alternative) | 6R framework | Classify each app's disposition: Retain, Retire, Replatform, Repurchase, Refactor, Rehost |
| ISMS / general security | ISO/IEC 27001 | Control-by-control gap assessment against Annex A |

CISA/FBI/NCSC joint guidance (2025) recommends aligning OT security programs to both IEC 62443 and ISO/IEC 27001 rather than treating them as alternatives — use them together when the environment has significant IT/OT overlap.

## 5. Gap analysis and prioritisation

- For each framework category/control, rate current state (evidenced) vs. target/expected state, and record the delta as the gap — with the specific evidence behind the rating, not a subjective impression.
- Rank findings by **consequence of failure to the business/operation**, not by raw technical severity alone — a medium-severity vulnerability on a safety-critical Level 1 asset outranks a critical vulnerability on an isolated Level 4 reporting server.
- Bucket remediation by horizon: quick wins (30–90 days), medium-term projects (90 days–12 months), long-term/capital investments (12+ months).
- Where a finding can't be remediated quickly (common in OT, where patching may require a shutdown window), document compensating controls and a monitoring plan instead of leaving it open with no mitigation.

## 6. Deliverable structure

A CSA report/deliverable typically includes:

1. **Executive summary** — business-framed: operational risk, compliance exposure, investment need — not technical jargon
2. **Scope and methodology** — what was covered, how data was gathered, any exclusions/limitations
3. **Inventory snapshot** — asset/application registers with lifecycle and criticality flags
4. **Architecture views** — current-state diagrams (Purdue-mapped network diagram for OT; layered architecture view for IT/apps)
5. **Framework assessment results** — maturity tier/security level per function or zone, with evidence
6. **Gap analysis by domain** — structured findings, each with evidence, risk rating, and consequence
7. **Risk register** — findings with severity/likelihood/consequence ratings
8. **Prioritized roadmap** — phased (e.g. 30/90/12-month) remediation and investment plan, distinct from the assessment itself
9. **Appendices** — detailed inventories, interview list, raw scan/monitoring data references

Keep the assessment (what is) and the roadmap (what to do) as clearly separable sections or documents — stakeholders often want to circulate the baseline findings without the recommendations attached, or vice versa.

## 7. Practical notes

- Timeline benchmarks: single-site OT assessment ≈ 2–4 weeks active + 2 weeks reporting; multi-site ≈ 3–6 months. IT infrastructure assessment for a 50–200 employee org ≈ 2–4 weeks.
- Independence matters: pair an external assessor's objectivity with internal operational/engineering knowledge of what's actually safety- or production-critical.
- Never let assessment activity (scanning, sensor placement, interviews) disrupt production — this is a harder constraint in OT than IT, but applies to both.
- Documentation-vs-reality gaps (undocumented assets, stale diagrams, shadow IT/OT) are findings in their own right — report them, don't just quietly correct the inventory.

## Relationship to this workspace's other agents

This skill is general reference methodology — it is not a wrapper around a project-local agent definition (unlike `csa-document-agent` and `csa-change-review-agent`, which wrap `current-state-assessment-document.md` and `csa-change-review.md`). Use it for framing scope, structuring findings, or checking coverage before or alongside those execution agents, e.g. when drafting or reviewing the actual IAMPS Current State Assessment DOCX content for a given section.
