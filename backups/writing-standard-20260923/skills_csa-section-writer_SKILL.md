---
name: csa-section-writer
description: Write or revise a Current State Assessment section from an approved evidence matrix while preserving document structure, traceability, and factual boundaries.
---

# CSA Section Writer

Write for technical and operational readers using the existing document's structure and style unless the user requests a redesign.

Before drafting, load `csa-writing-style` (`/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-writing-style/SKILL.md`) and write to it -- it governs how the sentences read; the rules below govern what they're allowed to claim.

## Rules

- Use approved evidence as the factual basis.
- Do not put evidence IDs (`E-nnn`) or any other citation marker inside the drafted section text itself -- that text is what a reader sees in the assessment document, and it should read as plain prose, not a citation trail. Evidence traceability lives in the accompanying change record (and from there, in the Word comment attached to the edit when it's applied), never inline in the body.
- State `INFERRED`, `UNCONFIRMED`, `CONFLICTING`, and `NOT_FOUND` matters transparently -- as plain wording in the sentence itself (e.g. "has not been directly observed" rather than a bracketed tag), not as a citation-style marker.
- Expand an abbreviation on first use, for example Operational Technology (OT).
- Keep current state, interpretation, gap, risk observation, and recommendation distinct.
- Do not copy stale facts from a prior assessment merely to complete a section.
- Preserve named owners, reviewers, approvers, dates, and controlled-document fields unless instructed to change them.
- Use tables for inventories and exact mappings; use prose for meaning and operational context.

Before returning the draft, map every material factual sentence to its evidence ID(s) -- but keep that mapping in the change record, not the section text. If the source cannot support the wording, narrow it or label the uncertainty in the prose itself.

Return the revised section (clean prose, no evidence IDs in it) and a brief change record stating what changed, why, and which E-id(s) support each material change -- the change record is where citations belong. Do not silently broaden scope.
