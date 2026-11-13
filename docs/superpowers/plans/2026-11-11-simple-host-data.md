# Simple host data in the CSA database

**Status:** Revised direction from Wenzel, 11 November 2026. This replaces the implementation direction in the 10 November host entity plan. No implementation has started.

## Goal

Put the useful facts from discovery runs into `csa-work/model.sqlite` as queryable host entities. A later run updates those entities. An assessor can correct or add information, with a source and reason. The CSA can then use the database to build complete host and account registers.

Start with the TETRA Identity data: local accounts, groups, group memberships, account use and domain controllers. Extend to other capture types after this slice works.

## Data model

Use three small tables in the existing SQLite database:

1. **`data_run`** records the project, host, capture time, source folder, collector, result and when it was imported.
2. **`entity`** holds one current row per discovered item: a database-generated integer ID, project, host, kind, a stable key within that kind, attributes, source file and line, run ID, and status (`current`, `not seen in latest run`, or `manually added`). Use ordinary SQLite uniqueness rules for the natural identity; do not derive IDs from hashes. Keep two genuine source rows with the same name distinct when they represent different items.
3. **`entity_change`** records each import or manual change: entity ID, old value, new value, source or reason, who/what changed it, and time. This is the audit trail and a simple way to see what a run changed.

The original capture files remain the record of what the collector returned. The database holds the current usable data and its source reference.

## Refresh rule

`csa entities refresh` processes one completed host capture at a time in a transaction:

1. Read the capture and record its run. Include files the discovery index marked as duplicates, crediting the data to the host being imported.
2. Match each parsed item to a current entity by project, host, kind and a kind-specific natural key. Insert new items; update changed attributes and source references; leave unchanged items alone.
3. Only after the host's required files parse successfully, mark items that this run did not see as `not seen in latest run`. Do not delete them. If a file is missing or fails to parse, show the gap and leave its earlier entities in place, clearly marked with the earlier run date.
4. Record the changes in `entity_change` and report counts of added, changed, unchanged, not seen and failed sources.

Running the same capture twice must leave the current data unchanged. A newer capture may change values or reduce the number of current entities; that is normal and must be reported, not blocked by a general shrink guard.

## Manual changes

Allow an assessor to add or correct an entity through the database-backed host view. Require a source reference and a short reason. Record the original value and correction in `entity_change`; show that the value was manually corrected or stated.

When a later capture disagrees with a manual correction, keep the correction visible and flag the disagreement for review. Do not silently overwrite either value. Ordinary discovery updates to entities without a manual correction apply automatically.

## Evidence quality

- Show each entity's host, capture date, source file and line, and whether its current value came from a capture or an assessor correction.
- Distinguish `present`, `captured file shows none`, `file missing`, and `file could not be parsed`. An empty result from a failed or unknown parser is never evidence of absence.
- Keep the existing `observation` and `host_settings` outputs while checking the new Identity data against them. Do not change the Word pipeline in this slice.
- Do not turn database rows into verified evidence-matrix claims automatically. Source checking and the existing evidence classes still apply when a CSA answer is written.

## Small delivery sequence

1. Add the tables and a refresh command for the Identity capture files. Test duplicate files, a repeated run, a changed value, a removed item, and a failed file.
2. Add `csa entities host HOST` and `csa entities changes HOST` so an assessor can inspect the current data and its history. Check all 19 TETRA hosts and one other project against their raw captures.
3. Add simple manual add/correct actions in the Evidence Browser host view. Test that the next data run retains and flags a conflicting correction.
4. Compare complete account and group registers with the current 4.5–4.8 answers. Report missing rows and source gaps before using the new data in answers.

## Done when

Every current TETRA host's Identity capture is represented or has a visible import gap; a second import makes no changes; a newer run updates the current rows and shows exactly what changed; an assessor can correct a value with a source; and register comparisons show no unexplained omissions. Existing CSA authoring and review remain in control of document changes.

The older plan, design and stories S560–S581 are reference material for capture formats and test cases. They need to be rewritten to this scope before dispatch; their hashes, release machinery, shrink guard and immutable captured-value rule are not requirements of this plan.
