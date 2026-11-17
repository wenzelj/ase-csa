# Rules digest: Improve lane

Improve repairs the answer already present in the working document. It is not `csa answer` again.

- Use the supplied current document text and base hash as the baseline.
- Keep supported existing content unless a named contradiction, duplication or evidence-backed gap requires a change.
- Use only evidence IDs in the bounded context.
- Return a bounded edit proposal, not an answer sheet.
- Return `no_material_change` when no justified edit is available.
- Return `blocked` when the evidence cannot settle the requested correction.
- A rating change needs a requirement basis and positive evidence.
- Do not add future-state recommendations or silently widen scope.
