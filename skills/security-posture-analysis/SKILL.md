---
name: security-posture-analysis
description: Describe evidenced current security controls, exposures, exceptions, and uncertainty for an Operational Technology application without turning the Current State Assessment into a future-state security design.
---

# Security Posture Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Summarise current controls and observations across relevant areas:

- segmentation and boundary protection;
- identity, privileged access, and remote access;
- system hardening, patching, malware protection, and vulnerability management;
- logging, monitoring, detection, and incident response;
- encryption, certificate use, data protection, and removable media where relevant;
- backup protection, recovery assurance, supplier access, and lifecycle risk;
- exceptions, compensating controls, and accepted risks.

Use neutral, precise language. `No evidence found` does not mean `control absent`; record the evidence limitation. Describe exposure and consequence only to the level supported by architecture and operational evidence. Do not assign compliance, maturity, severity, or risk ratings unless the governing method and inputs are supplied.

Return a control/evidence table, current-state observations, uncertainties, and items needing specialist validation. Keep recommendations in a separate requested output.
