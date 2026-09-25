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

Structure it answer first:

1. **Position:** one or two sentences stating the overall current state and its consequence, readable on its own (for example, "The platform is hosted in OT but cannot operate without enterprise IT services; under isolation it loses authentication and messaging immediately.").
2. **Key findings:** at most five, ordered by operational consequence, each one sentence with its rating.
3. **Isolation outcome:** what fails immediately, what degrades, and what keeps working.
4. **Declared gaps** that could change the position.

Write paragraphs, not nested bullet trees. Leave out host names, IP addresses, ports, evidence file names and capture dates; point to the detailed section instead. Follow the "Say it once, say it first" rules in `csa-writing-style`.

The document has one executive summary. If it already carries several overlapping summary sections (for example an Executive Overview, a Discovery Summary and an Assessment Summary), do not add another: write the one summary, and raise consolidating the others as a structural suggestion under Open questions.

Default to one page (two at most) unless directed otherwise. Include a small `What decision-makers should know` section and a pointer to the detailed CSA for evidence and technical detail.
