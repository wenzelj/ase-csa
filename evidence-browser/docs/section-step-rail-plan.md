# Section workspace step rail — plan (Author → Validate → Apply → Review)

Date: 2026-10-07 · Scope: `.agents/evidence-browser` Assessment view, `SectionWorkspace` (`.section-inspector`) in `frontend/src/App.tsx`.

## User story
As an assessor, when I select a section in the Assessment map, I want one obvious control in the section inspector to run each step of Author → Validate → Apply → Review, so I always know which step I'm on, what's next, and why a step is blocked.

## Decisions (2026-10-07, Wenzel)
- **Review auto-starts** after a successful apply (no extra click).
- **Cleanup stays under Review** — not its own rail step.
- **Validate is its own step** on the rail.

## Current state (as found)
- **Author**: `AuthorPanel` inside the inspector (only when section has `change_file`/`section_file`). "Run authoring" button sits at the bottom of a long panel.
- **Validate / Save / Apply**: buttons in the inspector footer (`proposal-instrument`). Apply needs: saved, validated, hash match, Word not locked, no running job. Then a confirm scrim → apply job polled each second.
- **Review**: `ReviewPanel` (and `CleanupPanel`, `WordReviewPanel`) render at **page level in App.tsx**, outside the inspector — the user has to leave the inspector to find them.
- Stage logic already exists in `pipelineState()` and `exactNext()`.

Main friction: the steps live in three places, with disabled buttons that don't say why.

## Proposed design
A **step rail** pinned under the inspector header (above the area nav), visible at all times:

```
 ① Author ── ② Validate ── ③ Apply ── ④ Review   [ Primary action ▸ ]
   ✓ done      ✓ passed      ● ready    ○ waiting   "Apply 4 edits to working doc"
```

- Each step shows state: done / current / blocked / waiting / running (spinner + elapsed) / failed.
- **One primary button** = the next action for this section (derived from `pipelineState` + live job state).
- Clicking a step chip expands + scrolls to that step's area (reuse `showArea`).
- Blocked steps show the reason inline ("Word has the document open", "Unsaved changes — save first", "Validation found 2 errors").
- **Apply → Review chaining**: when the apply job ends `succeeded` with state `complete`, the rail immediately submits review and shows ④ as running. Not chained on `partial`, `failed`, `blocked`, or when the section moves to `awaiting-word-decision` (Word decision must come first, then review auto-starts once that clears, or user clicks). Apply itself stays a deliberate, confirmed action.
- **Cleanup** appears inside the Review step's area once review passes (`ready-to-clean`); the rail's ④ shows "Review passed · cleanup pending" and the primary button becomes "Clean up".

### Step → action mapping
| Section state | Rail step | Primary action | Guard |
|---|---|---|---|
| not-started / no proposal | ① Author | Run authoring | author lock not held |
| proposal exists, dirty | ② Validate | Save draft | — |
| saved, not validated / validation-failed | ② Validate | Validate (re-validate) | not dirty |
| validated (valid, hash matches) / ready-to-apply | ③ Apply | Apply proposal → confirm scrim | existing apply guards |
| partially-applied | ③ Apply | Resume remaining edits | Word not locked |
| apply succeeded | ④ Review | (auto) Reviewing… · Stop | — |
| awaiting-word-decision | ④ Review | Open Word decisions (WordReviewPanel) | — |
| review-failed | ④ Review | Retry review | no running job |
| ready-to-clean | ④ Review | Clean up | — |
| complete | — | none; show "Complete" | — |

## Implementation steps
1. **Extract `SectionWorkspace`** from App.tsx into `components/SectionWorkspace.tsx`. No behaviour change; tests stay green.
2. **Add `deriveSteps`** (`components/sectionSteps.ts`): pure function `(section, proposal, dirty, validationResult, applyJob, applyOutcome, authorJob, reviewJob, wordLocked)` → `{ steps[4], current, primary: {label, action, disabledReason} }`. Table-driven unit tests against the mapping above.
3. **Lift job state**: AuthorPanel and ReviewPanel own their job/polling today. Expose `start()` / `cancel()` via `useImperativeHandle` plus an `onJobChange` callback so the rail can trigger and observe runs. Panels remain the detail views.
4. **Move Review + Cleanup into the inspector** as area `review` ("Review & cleanup", Cleanup nested below Review), and remove the page-level `ReviewPanel`/`CleanupPanel` render for the selected section in App.tsx. Keep `WordReviewPanel` page-level; link to it from the rail.
5. **Auto-review chain**: in the apply-job polling effect, on `succeeded` + outcome `complete` → `await refresh()` then call review `start()`. Guard against double submit (ref flag keyed by apply job id) and skip if a review job is already running.
6. **Build `StepRail` component**: four chips + primary button + blocked reason; sticky under header (reuse `--inspector-header-height`). Styles in `inspector-scroll.css` with `ase-palette.css` tokens.
7. **Refresh on completion**: any job finishing → `refresh()` + re-fetch inspection so the rail advances.
8. **Footer tidy**: keep Save/Validate/Apply in footer, but disabled buttons gain `title` with the reason from `deriveSteps`.
9. **Tests**: `deriveSteps` unit tests (incl. validate as a separate step, cleanup under review); render tests: ready-to-apply shows "Apply proposal"; Word-locked shows blocked reason; successful apply triggers exactly one review submit (mock API).
10. **Verify** via `start-dev.sh` against IAMPS: walk one section author → validate → apply → auto review → cleanup.

## Backend
No new endpoints expected. Confirm the inspection/pipeline payload returns latest author/review job ids so the rail can resume a running job after page reload; add if missing. Confirm review submit is safe to call straight after apply (document handle released).
