# Section files

The build lane's single definition of a section file. Spec: .agents/docs/build-lane-spec.md.

## Location and names

`WORK_DIR/sections/<order>-<slug>.md`, one file per template block, for example:
- `csa-work/sections/2.1-executive-summary.md`
- `csa-work/sections/3.04-time-synchronisation.md`
- `csa-work/sections/4.3-patch-and-update-tooling.md`
- `csa-work/sections/B-discovery-coverage.md`

The order prefix only sorts the files; the `heading:` front-matter key decides where the content goes.

## Format

Flat front matter (no nesting, parsed without PyYAML, like `PROJECTS.yaml`), then fixed `##` headings. Everything is plain prose or Markdown pipe tables. No evidence IDs, stable IDs or Markdown emphasis appear in rendered text; the same hygiene rules as `csa check-change` apply.

```markdown
---
block: domain
heading: Time Synchronisation
status: draft
---

## Requirements

| Req ID | Current State | Rating |
| --- | --- | --- |
| SEP-TIME-01 | All captured hosts take time from two enterprise time servers; nothing inside OT provides time. | Not Met |

## Discovery Information

- Every captured host runs the Windows Time service as a client of the enterprise time servers.
- No captured host serves time to other OT hosts.

## Drawbridge Impact

If OT is isolated, the hosts keep running on their last synchronised time and drift apart. Authentication fails once the skew passes the Kerberos tolerance; before that, log timestamps lose accuracy.

## Evidence

| Statement | Evidence |
| --- | --- |
| SEP-TIME-01 | E-012, E-044 |
| Discovery Information 1 | E-013 |
| Discovery Information 2 | E-045 |
| Drawbridge Impact | E-012, E-046 |
```

The `## Evidence` table is never rendered. It is the traceability record, and every rendered statement must appear in it. That satisfies "E-ids live in the change record, never in the prose" without a separate sidecar file.

## Block kinds

| `block:` | Template target | Headings in the file | How it fills |
| --- | --- | --- | --- |
| `domain` | a 3.x domain (Heading 2 = `heading:`) | `## Requirements` (every Req ID of that domain, once), `## Discovery Information` (bullets), `## Drawbridge Impact` (one paragraph); 3.1 adds `## Hosts and roles found` (table Host(s) / Environment / Role); 3.2 adds `## Accounts, groups and service accounts found` (table Account / Group / Type / Host(s) / Purpose / Role) | Rows replaced as `Observed:` / `Assessment:`; bullets scaffolded to the count, then replaced; paragraph replaced; tables scaffolded, then rows replaced as pipe rows |
| `executive-summary` | 2.1 Executive Summary | `## Summary` (one to three paragraphs) | The three placeholder paragraphs are replaced in order; unused ones are deleted. The figure placeholder is left for a person (diagrams are out of scope, see section 8). |
| `migration` | a 4.x subsection (Heading 2 = `heading:`) | `## Findings` (bullets) | Bullets scaffolded, then replaced |
| `glossary` | Appendix A | `## Terms` (table Term / Definition) | Standard rows kept; project terms appended by scaffolding the row count up, then replacing the new rows |
| `coverage` | Appendix B | `## Hosts` (table Host / Role / Discovery Script Run / Notes) | Rows scaffolded to the count, then replaced. S61 generates this file from the discovery index. |

Document Control (1.1) and the cover come from the document properties, which `new_csa.py` sets. The build adds one revision-history row (1.2) from its own arguments.

## Rules that `csa check-section` enforces (S55)

- `block:` is one of the kinds above, and `heading:` exists in the template (the list comes from `template-blocks.json`, S55).
- Domain: every Req ID of the domain appears exactly once, and no others; Rating is one of `Met`, `Partially Met`, `Not Met`, `Not Applicable`; Current State is at most 50 words (a warning).
- Every rendered statement has a row in `## Evidence` with at least one existing E-id (checked against the evidence matrix).
- Rendered text is free of E-ids, `@H` IDs, Markdown emphasis and backticks (errors), and `prose_lint.py` / `term_lint.py` run over it (warnings).
