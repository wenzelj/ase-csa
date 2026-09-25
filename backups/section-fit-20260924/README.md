# Section-fit check install (24 Sep 2026)

Added csa-quality-review check 9 (Section fit): does each paragraph, bullet and table row sit in the section and subsection that own it.

New files:
- skills/csa-quality-review/references/section-scope.md  (scope map: subsection jobs, 17 domains with owns / not-here / legacy hosts / signal terms, tie-breaks, verdicts and severity)
- skills/csa-quality-review/scripts/section_fit_scan.py  (candidate scan with stable IDs; read-only)

Edited (originals in this folder):
- skills/csa-quality-review/SKILL.md            check 9 added, description updated
- csa-quality-reviewer-agent.md                  loads the scope map, runs the scan
- skills/csa-section-writer/SKILL.md             reads the scope map before drafting
- csa-change-authoring.md                        loads the scope map; new "Out-Of-Place Content" section; editorial mode may move text
- csa-templates/SECTION_COVERAGE.md and skills/csa-orchestrator/references/SECTION_COVERAGE.md   completion criterion
- registry.yaml (summary for `csa qa`) then `csa sync` regenerated skills/csa-quality-reviewer-agent/SKILL.md and .claude/commands/csa-qa.md
- README.md                                      routing rule

Rollback: copy the files in this folder back over the edited ones, delete the two new files, run `csa sync`.

Tested: IAMPS (13 candidates incl. the Security Controls block under Time Synchronization, 49 units), UTC DTC v0.4 (17 candidates incl. migration headings in Architectural Review), a synthetic template draft (all 6 planted misplacements found), blank template v1.1 (no false positives; all 17 domain headings mapped).

## End-to-end test: `csa qa 9` on IAMPS (24 Sep 2026)

Review written to `IAMPS/06 IAMPS/csa-work/reviews/section-9-time-synchronization-review.md` (verdict NOT READY; 1 BLOCKER, 2 MAJOR, 9 MINOR).
The scan (v1, saved here as `section_fit_scan.py.v1`) raised 1 of 6 placement findings. Patterns added afterwards: "This indicates:/This confirms:" lead-ins without "that"; "X is a critical/foundational service that ..." explanations; requirement wording inside Assessment; bare lead-ins rated MINOR; legacy targets name the heading the document actually has. It now raises 5 of the 6 (facts restated inside Findings/Drawbridge/Recommendations remain reader-only).

Found during the test, outside this change: the 24 Sep accept step (between `before_repair_s4fix_20260924.bak` and `before_accept_fix_20260924.bak`) removed all 95 tracked-deletion marks without removing the text. 43 of 55 approved deletions are live again (Time Synchronization, Security Controls, DNS, Executive Overview). See review F-01.
