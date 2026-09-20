# C-S-A-Change-Authoring Agent Learnings

This append-only file captures two kinds of reusable lesson learned while drafting Current State Assessment change proposals against Discovery Data evidence:

1. **Evidence-to-topic mappings** -- which Discovery Data file name patterns actually turned out to be useful for which document topics. Recording this is a required step at the end of every authoring run (see `csa-change-authoring.md`, Evidence Mapping), not optional housekeeping -- there is no fixed mapping table anywhere else, so this file is the only place that knowledge accumulates.
2. **General authoring lessons** -- anchor/wording patterns that commonly fail `lookupStableId`, classes of claim that are routinely ambiguous across hosts, governance-field boundaries that came up, etc.

Each entry should use this format:

```text
## YYYY-MM-DD - <short lesson title>

Context:
<section/document/task context>

Issue or risk observed:
<what made authoring harder, failed, or required special handling -- or, for an
evidence mapping, what topic needed a mapping in the first place>

Evidence used:
<what evidence identified or confirmed the issue, or -- for a mapping entry --
the Discovery Data file name pattern(s) that were actually useful>

Improved authoring approach:
<what the agent should do next time>

Validation:
<how to confirm the improved approach worked>
```

## 2026-09-19 - Initial learning log

Context:
Agent created (`csa-change-authoring.md`) to fill the gap between `prepareDocument()` (step 0) and the previously-existing `csa-document-agent` (apply) / `csa-change-review-agent` (verify) agents, which both assumed a `ChangesCSA_*.md` already existed. Nothing had previously drafted the first proposal for a section from a bare, prepared document.

Issue or risk observed:
Without a dedicated append-only place for evidence-to-topic mappings, every authoring run would have to re-derive from scratch which Discovery Data files matter for which document topics (e.g. DNS, time synchronisation, listening ports) -- the exact kind of repeated rework this file exists to prevent.

Evidence used:
Discovery Data at `01 Current State AS Built/IAMPS Discovery Data/` is organised per-host under `PROD/`, `UAT/`, and standalone `tg_discovery_*` runs, with numbered per-topic files inside each host's folder (for example `00_host_summary.txt`, `14_resolver.txt`, `20_listening_ports.txt`, `41_dns_query_tests.txt`, `52_auth_configs.txt`) -- observed directly by listing the folder, not yet correlated against specific document sections.

Improved authoring approach:
After each completed authoring run, record which numbered file(s) were actually useful for the section's topic(s) as a new entry here, and check this file before searching Discovery Data from scratch on every subsequent run.

Validation:
Confirm this file gains at least one evidence-mapping entry per authoring run that found supporting evidence, and confirm the agent's report to the user states either the lesson added or `No new reusable skill lesson identified`.
