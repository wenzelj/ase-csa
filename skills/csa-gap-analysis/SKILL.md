---
name: csa-gap-analysis
description: Identify, prioritise, and convert missing, weak, stale, or contradictory Current State Assessment evidence into targeted questions and actions.
---

# CSA Gap Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Review the evidence matrix and draft for claims that are absent, weakly sourced, inferred, stale, conflicting, or too broad for their evidence.

For each gap record:

- stable gap ID and affected section;
- missing decision-relevant fact;
- why it matters to current-state accuracy;
- evidence already checked;
- best owner or source to consult;
- one specific answerable question;
- priority: `blocking`, `material`, or `minor`;
- status and accepted limitation, if any.

Prioritise gaps that could change architecture, operational impact, security boundary, migration scope, ownership, recovery, cost, or schedule. Combine duplicate questions. Do not ask stakeholders for information already available in reviewed sources.

The output is a gap register and a short interview/request list. A CSA can finish with declared gaps when they are non-blocking or formally accepted; do not keep the work open indefinitely.
