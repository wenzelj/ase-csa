# CSA figures: how they work and how to design a new one

Reference for the CSA Figure Design Agent (`csa figure-design`) and for anyone changing the figure code. It holds
two things: how the figure function works end to end, and the design rules for an IT/OT network topology figure,
with the research they come from.

## 1. What a CSA figure is for

A figure answers the one question a CSA section asks ("where does each vital OT host get its time?", "which
flows cross a zone boundary?"), drawn only from the project's evidence, readable on an A4 page, and placed in the
working document as a tracked change. It is never decoration and never a general architecture picture.

## 2. The pipeline

| Step | What happens | Code |
| --- | --- | --- |
| Need | Every section of the working CSA is matched to a figure profile by its requirement family (`SEP-<FAMILY>-nn`) or its key, never by section number. Status: needed, helpful, not-useful, not-built, placed, none. | `framework/csa_docx/figures/need.py`, `csa-context/figure-profiles.json` |
| Relations | Service figures (archetype B) read who takes a service from whom out of the evidence matrix and host register. One small extractor per service. | `figures/relations.py` (`EXTRACTORS`) |
| Residency | Which side of the IT/OT line a provider sits on, from the project's stated rule (`csa-context/system-diagrams.json` `residency`) and the register. Never guessed: no rule, `unknown`. | `relations.residency` |
| Model | The figure's JSON model: zones, groups, nodes (hosts with their recorded role and kind), edges (flows with status and evidence). | `techdiagram/model.py` (`overview`), `techdiagram/views.py` (`service_view`, `conduit_view`, `access_view`), schema `techdiagram/model.schema.json` |
| Brief | What the figure must show, item by item, each tied to requirement IDs, the section's sentence and evidence; status shown, absent (the finding) or gap (not captured, sent to Discovery Required). Purpose, caption, source. | `figures/brief.py` |
| Draw | The print figure (band layout), the screen figure, the PNG (about 360 dpi), the hash. `DRAWING_VERSION` is part of the hash: bump it when the drawing changes so saved figures show as out of date. | `figures/draw.py`, `techdiagram/band_layout.py`, `techdiagram/render.py`, `techdiagram/png.py` |
| Fit | Does the figure say what the section says: coverage, hosts named in the text, counts, providers the text omits, a Met rating against an outside-OT dependency, print size (8 pt, one page). Reports only. | `figures/fit.py` |
| Save | `csa-work/figures/<KEY>/`: `model.json`, `brief.json`, `figure.svg` (screen), `figure-print.svg`, `figure.png`, `figure.docx` (editable Word drawing), `fit.json`; the manifest; gaps into `figures/gaps.json`. | `figures/work.py` |
| Place | Into the working DOCX as a tracked change: the template's empty slot, a new Figure block after the Discovery Information table, or a replacement of a figure this step placed (bookmark `_CSAFig_<KEY>`). As a picture or as editable Word shapes (picture kept as fallback). Caption numbered by Word (`SEQ Figure`). | `figures/place.py`, `techdiagram/word_drawing.py`, `techdiagram/word_docx.py` |

Commands: `csa figures` (every section, whether it needs a figure and why), `csa figures --refresh` (from the
latest evidence: create every figure never saved, redraw the ones whose evidence or brief changed, report placed
figures that are now out of date; result in `figures/refresh.json`), `csa figure KEY` (one figure), `--save`,
`--place [--drawing word]`, `--agent` (the wording agent rewords purpose and caption; the framework checks it),
`--design --mode design|build|review [--cli claude]` (this agent, headless in its own window; writes
`figures/<KEY>/design.md`, `build-report.md` or `review.md`). The Evidence Workspace's CSA figures page does the
same with buttons: "Refresh figures from the latest evidence" with its summary, brief editor, fit checks,
"As printed" and screen views, Picture or Word drawing, downloads, and a "Figure design agent" box (Design this
figure, Build from this design after a confirm, Review with agent) that shows what the agent wrote.

## 3. Figure kinds (archetypes) and profiles

| Archetype | Kind | Built | Draws |
| --- | --- | --- | --- |
| A | System overview | yes | `model.overview`: every host by site and role, the links between sites and to IT and the Internet |
| B | Service dependency | time, DNS | `views.service_view`: the vital hosts that take one service, their providers, IT or OT side, and the OT gap when no OT provider is evidenced |
| C | Zones and conduits | yes | `views.conduit_view`: captured flows that cross a zone boundary; `scope` all, internet or transfer |
| D | Access path | yes | `views.access_view`: admin protocols into the assessed hosts, through a jump host or not |
| E | Numbered flow | no | steps in order (failover, replication, file transfer) |
| none | A table says it better | n/a | no figure |

A profile in `csa-context/figure-profiles.json`:

```json
{"id": "logging", "families": ["MON"], "archetype": "B", "service": "logging", "built": false,
 "question": "Where the vital hosts send their logs and monitoring data",
 "must_show": ["Log and monitoring collectors per host", "Whether each collector is OT-resident or IT"],
 "ot_gap": "OT-resident log collector", "caption": "Log and monitoring destinations"}
```

`families` or `keys` match sections; `question` is the section's question in plain words; `must_show` becomes the
brief; `ot_gap` names the absence that is itself the finding; `built` stays false until the kind draws. Profiles
are generic for every project: no host names, no project facts.

## 4. Design rules for the printed figure (band design)

### Research basis

- Purdue model and ISA/IEC 62443 reference architectures stack enterprise IT above an industrial DMZ above OT. The
  boundary sits between them and holds jump hosts, firewalls, proxies and data diodes. Direct IT-to-OT paths are the
  thing to show. (Palo Alto Networks, "What is the Purdue model for ICS security"; Opsio, "OT network segmentation,
  zones and conduits".)
- IEC 62443 zones group assets by function and trust; a conduit is the controlled path between zones. Start with a
  simple map of the important paths; over-detailed models go stale and are not used. (Security Boulevard, "Zone and
  conduit modelling under IEC 62443", June 2026; automation.com, "How to define zones and conduits".)
- Network diagram practice: one direction of flow, group by function or location, one recognisable icon style,
  short labels next to their shape, colour used sparingly and consistently, no crossing lines or crowding, a
  high-level view for clarity and separate detailed views. (Creately, "How to draw a network diagram".)
- C4 review checklist: every diagram has a key; every element a name, a type and a purpose; every colour, line
  style, arrowhead and border style is explained. (c4model.com, notation and review checklist.)
- The user's own design example (`Example_IT_OT_Network_Diagram_Icons.docx`): IT, the IT/OT security boundary and OT
  clearly apart, device icons, few words, machine roles, little clutter, single lines that systems join.

### Rules

1. **Bands, top to bottom:** IT and Internet; IT / OT boundary; operational technology. Full width, tinted (IT pale
   blue, boundary pale orange, OT pale green), title in capitals. Portrait A4 at the 17 cm text width.
2. **The boundary band** holds systems whose recorded role is a boundary function (jump host, firewall, bastion,
   remote access, data diode, proxy), wherever they are hosted. When lines cross a zone with no control evidenced
   and no firewall is in the evidence, it holds a dashed "Boundary control: None evidenced" marker.
3. **Sites are panels in the OT band** (each data centre, other sites, site not recorded, OT-resident services).
   "Location not captured" is a dashed panel in the IT band. Shared services go to the band the residency rule
   gives (`draw.py` stamps `node["band"]`).
4. **One tile per machine role per site:** the icon, the role in bold (no site, domain or instance detail), the
   host names underneath on one line (a range such as `ROTPRDCLU101–104`, or the first name and `+n`), a ×n badge
   for several hosts. Connections inside one tile are not drawn. Unknown roles are a dashed grey "?" icon; a missing
   OT service is a muted orange "None evidenced" tile. Icons: `techdiagram/icons.py`, one style (navy outline,
   light blue screens and tops, teal accents, orange firewall shield).
5. **One line per function** (a bus): one horizontal run in each channel it uses, one vertical trunk in a gutter,
   and every system in that traffic joins with a short tap and a dot. The arrowhead marks the system that
   receives. Service figures (B) keep one line per provider so who takes the service from whom stays visible.
   Zones-and-conduits figures (A, C) join sites rather than roles.
6. **Colour is the function**, from the port name or process in the capture and the roles at the ends
   (`band_layout.classify`): purple directory, name and time services (DNS, Time, NTP, Kerberos, LDAP, RPC or SMB to
   a domain controller); amber management and monitoring (RPC, SMB, RDP, SSH, WinRM, VNC, SNMP, Syslog,
   HealthService, agentService); blue web and Internet (HTTP, HTTPS); teal application and database (other named
   processes); grey other ports (no service name, or counted but not listed by the capture). No alarm red on lines.
7. **Line style is the evidence status:** solid observed (or crossing with no control, or an admin path with or
   without a jump host); dashed configured setting or inferred; long dash path not captured; dotted configured but
   not in use, or documented only.
8. **Routing:** vertical runs only in the gutters between tile columns, horizontal runs only in the channel above a
   tile row, taps at the top of an icon or the top edge of a site. A line never runs down the inside of a site it
   does not belong to.
9. **No words on the lines.** The legend has one row per function and status: colour and style, the function, the
   services on it and, when statuses differ, the status in words. One note: all lines cross a zone with no control
   evidenced (when true); arrow = the system that receives; ×n = hosts in the role.
10. **Size:** every text 17 drawing units (8.2 pt) or more at 17 cm; the whole figure 229 mm or less tall (one page
    under a heading with the caption). Too much for one page: split the figure, never shrink the text.
11. **Nothing invented:** every node comes from the register or a capture, every line cites evidence, an unknown
    role or location is drawn as unknown, an absence is drawn only when the brief's item says "absent".

### What a reader must be able to do

- See in two seconds which systems sit in IT, at the boundary and in OT.
- Follow any line to every system on it without crossing a tile.
- Name each line's purpose from its colour and the legend.
- Tell observed from configured from not-in-use without colour (print in grey scale).

## 5. Adding a new figure kind

Start from the section: its requirement IDs, its question, the evidence the project holds. Then:

- **New profile on a built archetype** (a family that a C or D figure answers): add the profile to
  `figure-profiles.json` with `built: true` and the right `scope`. No code. Check `csa figures` lists it as needed.
- **New service figure (B)**, e.g. logging, patching, backup, identity, PKI:
  1. Write the extractor in `figures/relations.py` and add it to `EXTRACTORS`. Each row:
     `{"service", "consumer", "provider", "order", "state": "active" | "inactive", "evidence": [E-...], "text"}`.
     Read only the evidence (`relations.load`: evidence matrix, host register, host facts); cite the matrix row,
     or the capture file and line; a provider the evidence cannot name is not created.
  2. Add the service's words to `SERVICE_WORD` (`need.py`, `brief.py`, `views.py`), `SERVICE_LABEL` and
     `PROVIDER_ROLE` (`views.py`).
  3. If the service has a function colour other than directory, add its names to `band_layout` (`DIRECTORY_SVCS`,
     `MANAGEMENT_SVCS`, `WEB_SVCS`) so `classify` puts it in the right function.
  4. Set `built: true` on the profile.
- **New conduit scope (C)**: add the scope and its port set in `views.conduit_view`.
- **Numbered flow (E)**: not built. It needs its own view (ordered steps between roles) and a renderer that numbers
  the steps on the lines; keep the bands and tiles of the band layout so it reads like the other figures.
- **A new icon or kind**: draw it in `icons.py` on the 24 × 24 grid in the same style, add it to `KINDS` and to the
  `kind` enum in `model.schema.json`, and add the recorded-role rule in `model.py`.
- Every change to what is drawn: bump `DRAWING_VERSION` in `figures/draw.py`.

## 6. Checking a figure

1. `csa figure KEY` and read the fit checks: no flag, every brief item drawn or a stated gap.
2. Look at `figure.png` (or the "As printed" view): bands clear, no line through a tile or a site it does not
   belong to, no text cut, legend complete, 8.2 pt and one page (the Print line on the page).
3. Open `figure.docx` (or place with `--drawing word` into a copy): the drawing is one group, text is editable,
   nothing shifted.
4. Tests: `framework/csa_docx/tests/test_figures.py`, `test_word_drawing.py` (and add one for the new kind).

## 7. Limits to tell the reader

- A line shows that systems share a function, not that every pair on it connects. The System explorer in the
  Evidence Workspace keeps every host-to-host connection.
- Word does not keep a line attached to a tile when someone moves the tile in Word.
- The screen view on the Figures page is the wide interactive layout, not the band layout.
