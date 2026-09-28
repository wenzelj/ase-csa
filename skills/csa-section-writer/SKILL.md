---
name: csa-section-writer
description: Write or revise a Current State Assessment section from an approved evidence matrix while preserving document structure, traceability, and factual boundaries.
---

# CSA Section Writer

Write for technical and operational readers using the existing document's structure and style unless the user requests a redesign.

Before drafting, load `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`) for the words (technical terms, IT/OT classification, headings, Australian English), and both shared references -- they govern what the section is about and how it reads: `csa-writing-style` (`.agents/skills/csa-writing-style/SKILL.md`) for how the sentences read, and `references/current-state-reasoning.md` (relative to this skill) for what the section is about: the subject rule (system, not evidence), the three statement classes (fact / evidence / gap), "not observed" vs "does not exist", evidence correlation, scope of a statement, and IT/OT terminology. Write to both; the rules below govern what the sentences are allowed to claim.

## What a section must expose

The CSA is the baseline the later phases (scope, design change, segmentation) act on. A reader of any domain section should be able to answer four questions within a minute:

1. What is in place today?
2. Does it meet the design or reference requirement (the rating)?
3. What happens to operations if the OT environment is isolated from IT: what fails, how fast, and what keeps working?
4. What is not known, and does that matter?

Anything that does not help answer one of these belongs in a table, the appendix, or nowhere.

Before drafting, read the section's entry in the section scope map (`.agents/skills/csa-quality-review/references/section-scope.md`, part 4, plus the tie-breaks in part 5). Write only what this domain owns. When evidence concerns another domain, give it one sentence here if it explains this section's condition, and put the detail in the owning section's draft, or list it as a `Relocation` note in the change record.

## Section shape

Template domain blocks (CSA template v1.x):

- **Requirement table, Current State cell:** one or two sentences stating the condition against the requirement. No lists. Aim for 50 words or fewer. **Rating:** `Met`, `Partially Met`, `Not Met` or `Not Applicable`, as the evidence supports.
- **Discovery Information:** the observed facts only, as a short table or up to five parallel bullets. No interpretation.
- **Drawbridge Impact** (isolation consequence): one paragraph covering what fails, whether it fails immediately or degrades, and what keeps working. Do not restate the discovery facts.

Legacy structures (Design and functionality expected / Observed / Findings / Drawbridge Impact / Operational Behaviour / Assessment / Recommendations): keep the headings, because change records cannot restructure, but give each subsection only its own job:

| Subsection | Carries only |
| --- | --- |
| Expected | the design or reference requirement, in one to three sentences |
| Observed | the facts, preferably one summary table |
| Findings | one paragraph per finding: condition, criteria, consequence |
| Drawbridge Impact / Operational Behaviour | the isolation consequence, once, across both |
| Assessment | a one-sentence position and the rating |
| Recommendations | actions, each tied to a finding, by horizon |

When a subsection would only restate another, reduce it to one sentence that points to the owning subsection, and raise the merge as a structural suggestion under Open questions.

**Length:** aim for 600 words of prose or fewer per domain section, excluding tables; one finding paragraph is 120 words or fewer. These are targets, not reasons to drop evidenced facts.

## Rules

- Use approved evidence as the factual basis.
- Do not put evidence IDs (`E-nnn`) or any other citation marker inside the drafted section text itself -- that text is what a reader sees in the assessment document, and it should read as plain prose, not a citation trail. Evidence traceability lives in the accompanying change record (and from there, in the Word comment attached to the edit when it's applied), never inline in the body.
- State `INFERRED`, `UNCONFIRMED`, `CONFLICTING`, and `NOT_FOUND` matters transparently -- as plain wording in the sentence itself (e.g. "has not been directly observed" rather than a bracketed tag), not as a citation-style marker.
- Expand an abbreviation on first use, for example Operational Technology (OT).
- Keep current state, interpretation, gap, risk observation, and recommendation distinct.
- Do not copy stale facts from a prior assessment merely to complete a section.
- Preserve named owners, reviewers, approvers, dates, and controlled-document fields unless instructed to change them.
- Use tables for inventories and exact mappings; use prose for meaning and operational context.

Before returning the draft, run `prose_lint.py` on it (see `csa-writing-style`, Check before returning) and fix its warnings. Then map every material factual sentence to its evidence ID(s) -- but keep that mapping in the change record, not the section text. If the source cannot support the wording, narrow it or label the uncertainty in the prose itself.

Return the revised section (clean prose, no evidence IDs in it) and a brief change record stating what changed, why, and which E-id(s) support each material change -- the change record is where citations belong. Do not silently broaden scope.
