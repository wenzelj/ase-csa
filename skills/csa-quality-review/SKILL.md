---
name: csa-quality-review
description: Review an Operational Technology Current State Assessment for evidence traceability, technical sense, internal consistency, scope, terminology, and stakeholder readability.
---

# CSA Quality Review

Review in this order:

1. **Accuracy and traceability** — every material factual claim has adequate evidence and correct citation.
2. **Internal consistency** — names, dates, versions, sites, counts, roles, environments, and relationships agree across prose, tables, and diagrams.
3. **Evidence discipline** — inference and absence are not presented as verified fact; conflicts remain visible.
4. **Technical sense** — architecture, flows, dependencies, identity, resilience, and operational statements do not contradict one another.
5. **Scope and time boundary** — content describes the named system and as-of date; future state and recommendations are separated.
6. **Consumability** — abbreviations expand on first use, tables are readable, explanations are proportional, and repeated text is removed.
7. **Controlled fields** — document owner, reviewers, approvers, identifiers, and dates change only under explicit instruction.

Classify findings as `BLOCKER`, `MAJOR`, `MINOR`, or `EDITORIAL`. For each, give location, issue, evidence or reasoning, and exact corrective action. Do not rewrite acceptable passages for personal style.

Conclude with one verdict: `READY`, `READY WITH DECLARED GAPS`, or `NOT READY`, plus the minimum actions needed to advance.
