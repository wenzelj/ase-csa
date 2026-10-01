# Prompt: move one subsection of the old CSA into the template

Use: replace `{SECTION}` (for example `3.4`) and `{PROJECT}` (for example `tetra-reveloc`). One subsection per session. Or run `csa -p {PROJECT} move {SECTION}`, which does this for you.

---

You are moving the old-format content mapped to subsection **{SECTION}** of project **{PROJECT}** into the CSA template. Speed matters: the document is reworked afterwards, so do not research, verify or rate. Do not edit the Word document yourself.

## Read

1. `csa -p {PROJECT} move {SECTION} --stage brief`, then `csa-work/move/{SECTION}/brief.md`: the requirements, the old content assigned to this subsection, the hosts.
2. `.agents/references/section-file-format.md` (the file shape) and, for the look of a finished section, `csa-work/sections/3.05-dns.md`.

## Write

Write `csa-work/sections/<order>-<slug>.md` with `mode: move` in the front matter:

- One row per requirement of {SECTION}. Current State: one or two sentences from the old content. Rating: **leave empty**.
- Discovery Information rows (Aspect / Configuration Observed / Coverage / Source) from what the old content states. Coverage / Source names the hosts and says `previous assessment`.
- One Drawbridge Impact paragraph, only if the old content supports it.
- Where the old content says nothing for a requirement or aspect: `Not stated in previous assessment`.
- An `open_items` block at the end: one line per question the old content leaves open (what is unknown, which requirement).

## Rules

- Facts, not narrative. Each fact once. Full sentences.
- No recommendations (they are listed separately). Keep qualifiers: "not tested", "not observed".
- Never mention the previous assessment, its headings or its version in the text.
- Do not copy old readiness scores or ratings.
- Content that belongs to another subsection is left out.
- No IP addresses in prose; host detail goes in the table.

## Finish

Run `csa -p {PROJECT} move {SECTION} --stage insert` (structure check, plain-text placement, records). Report in two lines: requirements filled and left "Not stated"; number of open items.
