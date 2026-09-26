---
name: evidence-investigator
description: Find, extract, classify, and reconcile source evidence for an Operational Technology Current State Assessment. Use for document review and fact verification; do not draft unsupported narrative.
---

# Evidence Investigator

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Build a defensible evidence set before analysis or writing.

## Method

1. Define the precise question and relevant source set.
2. Search headings, tables, diagrams, appendices, metadata, and surrounding text.
3. Record atomic claims in the evidence matrix. Split compound statements when their support differs.
4. Capture source title, document identifier or version, section, page or location, exact supporting excerpt where permitted, and retrieval date when relevant.
5. Classify each claim:
   - `VERIFIED`: directly supported by an authoritative source.
   - `INFERRED`: reasoned from verified facts; record the reasoning.
   - `UNCONFIRMED`: asserted but not adequately supported.
   - `CONFLICTING`: credible sources disagree.
   - `NOT_FOUND`: absent after a proportionate search of the stated source set.
6. Compare duplicate claims across sources and preserve disagreements.

Never upgrade an inference because it is technically plausible. Do not use prior knowledge to complete hostnames, addresses, versions, ownership, topology, control status, or dates. A diagram may establish relationships but not undocumented implementation details.

## Search stopping rule

Stop when the named sources have been searched in the locations likely to contain the answer and further passes would repeat the same search. Record `NOT_FOUND` with the searched scope. Escalate only material gaps.

## Output

Use [EVIDENCE_MATRIX_TEMPLATE.csv](references/EVIDENCE_MATRIX_TEMPLATE.csv). Give every row a stable evidence ID so writers can cite it and reviewers can trace it.
