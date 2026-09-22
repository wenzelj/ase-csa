---
name: csa-section-writer
description: Write or revise a Current State Assessment section from an approved evidence matrix while preserving document structure, traceability, and factual boundaries.
---

# CSA Section Writer

Write for technical and operational readers using the existing document's structure and style unless the user requests a redesign.

Before drafting, load `csa-writing-style` (`/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-writing-style/SKILL.md`) and write to it -- it governs how the sentences read; the rules below govern what they're allowed to claim.

## Rules

- Use approved evidence as the factual basis.
- Cite evidence IDs or the document's required citation form near material claims.
- State `INFERRED`, `UNCONFIRMED`, `CONFLICTING`, and `NOT_FOUND` matters transparently.
- Expand an abbreviation on first use, for example Operational Technology (OT).
- Keep current state, interpretation, gap, risk observation, and recommendation distinct.
- Do not copy stale facts from a prior assessment merely to complete a section.
- Preserve named owners, reviewers, approvers, dates, and controlled-document fields unless instructed to change them.
- Use tables for inventories and exact mappings; use prose for meaning and operational context.

Before returning the draft, map every material factual sentence to evidence. If the source cannot support the wording, narrow it or label the uncertainty.

Return the revised section and a brief change record stating what changed and why. Do not silently broaden scope.
