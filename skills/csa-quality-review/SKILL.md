---
name: csa-quality-review
description: Review an Operational Technology Current State Assessment for evidence traceability, technical sense, internal consistency, scope, section fit (right content in the right section and subsection), terminology, and stakeholder readability.
---

# CSA Quality Review

Review in this order. Checks 1, 3 and 4 come from `csa-section-writer/references/current-state-reasoning.md` (the reader-value test); read that file before this pass.

1. **Application/system focus** — does the section describe the application and its supporting environment, or does it describe the discovery process? A passage whose subject is "the discovery data", "the table", "the workbook", "the capture", "the evidence" is evidence-centric: it belongs in the change record or the evidence appendix, rewritten around the system it tells us about.
2. **Accuracy and traceability** — every material factual claim has adequate evidence and correct citation (E-id in the change record, Word comment, or evidence matrix).
3. **Evidence discipline** — inference and absence are not presented as verified fact; "not observed in the supplied evidence" is not written as "does not exist"; conflicts remain visible and are not silently resolved.
4. **IT/OT terminology** — the language is what an experienced infrastructure, OT application, systems engineering, operations, or architecture person would use, matched to what is actually being described; no consulting- or data-analysis-flavoured terms (e.g. "estate and discovery coverage" where "discovery capture set" is what is meant).
5. **Internal consistency** — names, dates, versions, sites, counts, roles, environments, and relationships agree across prose, tables, and diagrams; populations (declared estate, discovery population, capture campaign) are not conflated.
6. **Technical coherence** — architecture, flows, dependencies, identity, resilience, and operational statements do not contradict one another and hold together as one system.
7. **Cross-section consistency** — the section agrees with the other sections of the document (same host names, same dependency picture, same populations).
8. **Scope and time boundary** — content describes the named system and as-of date; each statement is scoped to the population its evidence covers; future state and recommendations are separated.
9. **Consumability** — abbreviations expand on first use, tables are readable, explanations are proportional, and repeated text is removed.
10. **Concision and flow** — the prose follows the "Say it once, say it first" rules in `csa-writing-style` (`/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-writing-style/SKILL.md`). Run `csa-writing-style/scripts/prose_lint.py` on the draft or DOCX section and use its output as the starting point, then read the text to confirm. Rate as follows:
   - `MAJOR`: the same fact or consequence restated in three or more subsections; overlapping summary sections; the conclusion missing from the start of a section; a domain section more than about twice its word budget; placeholder or unfinished headings; a passage whose subject is the evidence rather than the system (check 1); an absence stated as a bare fact with no scope searched (check 3).
   - `MINOR`: nested bullets or sentences split across bullets; announcing connectors ("This confirms", "As a result"); general technology explanation inside a finding; host lists, IPs, ports or evidence file names in running prose; evidence-label suffixes on headings; inconsistent terms for the same thing; a stale or unexplained count in prose (check 5).
   These are standard rules with measurable tests, not personal style, so reporting them does not break the "do not rewrite for personal style" rule below. Give the corrective action as the condensed wording or the subsection that should own the fact.
11. **Controlled fields** — document owner, reviewers, approvers, identifiers, and dates change only under explicit instruction.
12. **Section fit** — every paragraph, bullet and table row sits in the section that owns its topic and in the subsection whose job it does. The rules are in `references/section-scope.md` (`/Users/wenzel/Work/ASE/CurrentStateAssessments/.agents/skills/csa-quality-review/references/section-scope.md`): read it before this check. Run `scripts/section_fit_scan.py` on the working DOCX for the section (`--heading "<title>"`, or `--domain 3.x` for one template domain block) and use its candidates, with their stable IDs, as the starting point. The scan is a keyword and pattern pass: confirm each candidate by reading the text and apply the "mention vs own" test, then look for what it cannot see (a fact stated only in the wrong place; text that belongs here but sits elsewhere, listed under `INBOUND`). Report each confirmed item with its verdict (`WRONG_SECTION`, `WRONG_SUBSECTION`, `SPLIT`, `DUPLICATE`, `OUT_OF_SCOPE`, `MISPLACED_HEADING`), severity from part 7 of the scope map, and the target stable ID or heading. You report placement; `csa-change-authoring` carries out the move.

Classify findings as `BLOCKER`, `MAJOR`, `MINOR`, or `EDITORIAL`. For each, give location, issue, evidence or reasoning, and exact corrective action. Do not rewrite acceptable passages for personal style.

Conclude with one verdict: `READY`, `READY WITH DECLARED GAPS`, or `NOT READY`, plus the minimum actions needed to advance.
