# Topic tables: Discovery Information that describes the system

Decided 15/10/2026 with Wenzel. Built and piloted on REVELOC TETRA 3.4 Time Synchronisation and 3.5 DNS.

## Why

A CSA section's job is to describe the system for its topic and answer the requirement. The Discovery
Information table was a fixed Aspect / Configuration Observed / Coverage / Source list, so per-host facts
(which time source each host follows) ended up as host lists inside sentences, repeated "Active enterprise
source" rows, ranges that hid outliers and totals ("nine captured hosts"). The card fixed that shape and gave
the agent prose evidence, so the agent could not do better.

## What the reader sees under Discovery Information

1. **Role table**, built by the framework from the captures (no model call). Columns are Role, Hosts and the
   topic's columns.
2. **Common sentence**: one `TableNote` paragraph for values every host shares ("All hosts in this table run
   the Windows Time Service, operate at stratum 5 and follow sources at stratum 4.").
3. **Marker line**: "† Not captured, assumed to match the captured hosts of its role." (and ‡ when used).
4. **Aspect table**, kept for points that are not per host (what exists or is missing across the system, what
   was not tested). The agent writes these rows.
5. The optional note and Drawbridge Impact, as before.

The Word template does not change.

## Rules (decided)

- Rows are **role groups** from `csa-work/hosts/hosts.csv`. A role is split into sub-rows only where its
  captured hosts differ. The role cell is merged over its sub-rows, and the shading bands follow role groups,
  not rows.
- **No counts or totals** anywhere: host names and role groups carry it. This applies to the table and also
  to the agent's text (`NO_TOTALS`).
- **Hosts not captured are assumed to match their role.** A host with no capture for the topic joins its role's row
  marked †, and one Discovery Required item per role asks to confirm it. When the captured hosts of that role
  differ, the host gets its own sub-row marked ‡ with "Not captured". A role with no captured host gets no
  row, only a Discovery Required item.
- Hosts with no role in hosts.csv are left out and named in the run output (fix `roles.csv`).
- **Columns follow the data.** A column with one value for every captured host moves into the common sentence.
  A column with no data is dropped. At most four varying columns (A4 portrait).
- Every cell keeps its capture file and line (`csa-work/topic-tables/<KEY>.json`).

## Parts

| Part | What it does |
| --- | --- |
| `framework/csa_docx/host_settings.py` | Per-host setting values from the captures with file and line: `csa-work/hosts/host_settings.csv`. Time from `03_time_status.txt` (source, fallback peers and state, poll interval, service, stratum, source stratum); DNS primary and secondary from the resolver capture. Runs inside `csa hosts build`. |
| `references/topic-tables/*.json` | One profile per topic, matched by heading text (never section number). README there. |
| `framework/csa_docx/topic_tables.py` | Grouping, common sentence, markers, Discovery Required items (`DR-<KEY>-Tnn`), and placing the table under Discovery Information. The table carries a hidden caption `csa-topic-table`, and a rerun replaces it. |
| `doc_spec.py` | The captioned table is counted (stable-ID ordinals stay right) but is a `topic-table` part, and its note lines are `topic-note` parts. Nobody is asked to answer them, and the template's optional note still matches the agent's note below the Aspect table. |
| `section_card.py` | The card shows the role table and its Discovery Required items. The Aspect question asks only for points that are not per host. The host register has no counts. |
| `section_card.py` (Facts to keep) | Facts from earlier answers that count hosts are marked `[restate without "..."]`: the agent keeps the fact and its capture evidence but rewrites it by role group, so NO_TOTALS and CAPTURE_DROPPED never pull against each other. Added 15/10/2026 after the first 3.4 run copied "Nine captured hosts ...". |
| `answer_sheet.py` | `NO_TOTALS` (host counts in Text, facts, bullets, rows) and `ROLE_TABLE_REPEAT` (an Aspect row naming two or more hosts or servers from the role table) block in both lanes. An old per-host row of the Aspect table is not demanded back (CAPTURE_DROPPED) once the role table states it. |
| `draft_lane.py`, `discovery_required.py` | The role-table gaps join the open questions and Section 8 Discovery Required. |
| `bin/csa` | `csa draft N` places or refreshes the role table after writing the subsection. `csa topic-table N [--place] [--settings] [--json]` builds it on its own, with no model. |
| `csa-work/hosts/sites.txt` | Optional site display order (TETRA: Rockhampton, Mackay, IPT). |

## Pilot (TETRA, 15/10/2026)

On a copy (`csa-work/pilot/`): 3.4 gets nine rows, with the RevBroadcast AG and RevViewer Jump Hosts split by
time source. The Jump Hosts poll every 32,768 s and every other host every 1,024 s. The TETRA Log Servers
(ROTPRDLOG103, MOTPRDLOG103) and ROTPRDREV101 are assumed †. Discovery Required DR-TIME-T01 to T06 covers the
Radio Management, OT Reveloc Server and Licence Server roles, which have no capture. 3.5 DNS shows the Mackay
hosts asking MOTPRDSRV122 first and the Rockhampton hosts ROTPRDSRV122. The document passes the validator, a
rerun replaces the table, and the card for 3.4 is unchanged apart from the role table.

## Next

- Run `csa draft 3.4` and `csa draft 3.5` so the agent rewrites the Aspect rows, Current State and Drawbridge
  text without counts and without repeating the role table.
- Give the four SQLCDN hosts a role in `roles.csv`, or mark them out of scope.
- Add profiles for the other domains one topic at a time (a host_settings extractor plus a profile each),
  as small improvement stories.
- No hosts-file capture exists in the TETRA script results yet, so the DNS profile has no hosts-file column.
