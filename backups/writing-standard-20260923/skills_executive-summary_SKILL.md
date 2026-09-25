---
name: executive-summary
description: Produce a concise, evidence-aligned stakeholder summary from a completed Operational Technology Current State Assessment. Use after technical sections are stable, not as a substitute for evidence gathering.
---

# Executive Summary

Create a short summary for readers who will not read the full assessment. Load `csa-writing-style` (`/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-writing-style/SKILL.md`) before drafting -- an executive summary is exactly the kind of text that tends to read as AI-generated boilerplate if that skill isn't applied.

Cover:

- what the application or service does and why it matters;
- current architecture and hosting in plain language;
- operational ownership and key dependencies;
- the most material evidenced constraints, exposures, and resilience limitations;
- important declared evidence gaps;
- implications for the named program or decision, without inventing a future state.

Keep factual statements aligned with the approved CSA and use the same as-of date. Avoid unexplained abbreviations, low-level inventories, and new findings. Do not exaggerate uncertainty into risk or dilute material limitations.

Default to one or two pages unless directed otherwise. Include a small `What decision-makers should know` section and a pointer to the detailed CSA for evidence and technical detail.
