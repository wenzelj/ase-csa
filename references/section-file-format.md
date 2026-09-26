# Section files

The build lane's single definition of a section file. Spec: .agents/docs/build-lane-spec.md. Matches CSA template v1.2.

## Location and names

`WORK_DIR/sections/<order>-<slug>.md`, one file per template block, for example:
- `csa-work/sections/2.1-executive-summary.md`
- `csa-work/sections/3.04-time-synchronisation.md`
- `csa-work/sections/4-governance.md`
- `csa-work/sections/5.1-discovery-coverage.md`
- `csa-work/sections/5.4-patch-and-update-tooling.md`

The order prefix only sorts the files; the `heading:` front-matter key decides where the content goes.

## Format

Flat front matter (no nesting, parsed without PyYAML, like `PROJECTS.yaml`), then fixed `##` headings. Everything is plain prose, `- ` bullets or Markdown pipe tables with a header row. No evidence IDs, stable IDs or Markdown emphasis appear in rendered text; the same hygiene rules as `csa check-change` apply.

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

| Aspect | Configuration Observed | Coverage / Source |
| --- | --- | --- |
| Time source | Two enterprise time servers, configured by Group Policy | All captured hosts; w32tm output |
| Local time service | Windows Time runs as a client only; no host serves time to others | All captured hosts; listening ports |

## Discovery Notes

- The time servers sit in the enterprise IT domain, outside the OT boundary.

## Drawbridge Impact

If OT is isolated, the hosts keep running on their last synchronised time and drift apart. Authentication fails once the skew passes the Kerberos tolerance; before that, log timestamps lose accuracy.

## Evidence

| Statement | Evidence |
| --- | --- |
| SEP-TIME-01 | E-012, E-044 |
| Discovery Information 1 | E-013 |
| Discovery Information 2 | E-045 |
| Discovery Notes 1 | E-047 |
| Drawbridge Impact | E-012, E-046 |
```

The `## Evidence` table is never rendered. It is the traceability record, and every rendered statement must appear in it: a requirement by its Req ID, a table row or bullet as `<section heading> <n>` (numbered from 1 in file order), a single paragraph by its section heading. That satisfies "E-ids live in the change record, never in the prose" without a separate sidecar file.

## Block kinds

| `block:` | Template target | `##` sections in the file | How it fills |
| --- | --- | --- | --- |
| `domain` | a 3.x domain (Heading 2 = `heading:`) | `## Requirements` (every Req ID of that domain, once); `## Discovery Information` (table Aspect / Configuration Observed / Coverage / Source, at least one row); optional `## Discovery Notes` (bullets for findings that do not fit the table); `## Drawbridge Impact` (one paragraph). 3.1 may add `## Hosts and roles found` (Host(s) / Environment / Role); 3.2 may add `## Accounts, groups and service accounts found` (Account / Group / Type / Host(s) / Purpose / Role) | Requirement rows replaced as `Observed:` / `Assessment:`; table rows scaffolded to the count, then replaced as pipe rows; the optional bullet replaced, or deleted when there are no notes; paragraph replaced |
| `executive-summary` | 2.1 Executive Summary | `## Summary` (one to three paragraphs) | The three placeholder paragraphs are replaced in order; unused ones are deleted. The figure placeholder is left for a person. |
| `governance` | 4 Governance Note and Next Steps | `## Actions` (bullets: system-specific actions with owner and target date) | The three standard actions stay; the placeholder bullet is scaffolded to the count, then replaced |
| `migration` | 5 Migration Discovery (heading `Migration Discovery`: `## Summary` only) or a 5.2–5.6 subsection | optional `## Summary` (one paragraph: the intro); `## Table` where the template subsection has a table (5.2, 5.4, 5.5), with the template's columns; `## Findings` (bullets) where it has a bullet (5.3, 5.4, 5.6) | Intro paragraph replaced; table rows scaffolded, then replaced; bullets scaffolded, then replaced. For 5.5 the `## Table` header row renames the two `[Host group]` columns; a CSA that needs more host-group columns adds them by hand in Word after the build (neither the framework nor `scaffold_csa.py` can add columns) |
| `coverage` | 5.1 Discovery Coverage | optional `## Summary`; `## Hosts` (table Host / Role / Discovery Script Run / Notes) | Rows scaffolded to the count, then replaced. S61 generates this file from the discovery index. |
| `glossary` | Appendix B | `## Terms` (table Term / Definition) | Standard rows kept; project terms appended by scaffolding the row count up, then replacing the new rows |

Document Control (1.1) and the cover come from the document properties, which `new_csa.py` sets. The build adds one revision-history row (1.2) from its own arguments. Appendix A (the OT 3.5 destinations) is pre-filled in the template and is not a block.

## Rules that `csa check-section` enforces

- `block:` is one of the kinds above, and `heading:` exists in the template for that kind (from `template-blocks.json`; straight and curly quotes match).
- Every required `##` section is present, no unknown or repeated `##` section appears, and every table has exactly the template's column count.
- Domain: every Req ID of the domain appears exactly once, and no others; Rating is one of `Met`, `Partially Met`, `Not Met`, `Not Applicable`; Current State is at most 50 words (a warning).
- Every rendered statement has a row in `## Evidence` with at least one E-id that exists in the evidence matrix (coverage files cite captures instead). Unused Evidence rows and a missing matrix are warnings.
- Rendered text is free of E-ids, `@H` IDs, Markdown emphasis and backticks (errors), and `prose_lint.py` / `term_lint.py` run over it (warnings).
