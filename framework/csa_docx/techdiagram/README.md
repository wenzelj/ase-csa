# techdiagram: evidence-based IT/OT figures for CSA documents

One diagram model, several outputs. The model is built only from discovery evidence (host register, connection
captures, configured settings, the evidence matrix); the renderers never add a host, port or flow.

| Part | File | What it does |
| --- | --- | --- |
| Input model | `model.schema.json` | The JSON every renderer takes: zones, groups, nodes (hosts with recorded role), edges (flows with status and evidence), notes. Saved per figure as `csa-work/figures/<KEY>/model.json`. |
| Model builders | `model.py`, `views.py` | `overview` (whole system), `service_view` (time, DNS: who takes it from whom, IT or OT side), `conduit_view` (flows that cross a zone boundary), `access_view` (admin protocols, jump hosts). |
| Icon library | `icons.py` | 31 device icons on a 24 × 24 grid in the CSA design style (navy outlines on white, light blue screens and cylinder tops, teal accents, orange firewall shield), drawn for this project (no third-party licence). Kinds map a recorded role to an icon, a label and an outline colour. |
| Screen layout | `layout_tracks.py`, `render.py` | Wide interactive drawing for the Evidence Workspace. |
| Print layout | `band_layout.py` (via `print_layout.render_print_svg`) | The figure at the CSA's 17 cm text width, in three bands top to bottom: IT and Internet, the IT / OT boundary, OT (one panel per site). One icon per machine role with its hosts underneath, one coloured line per function that every system in that traffic joins. Every text 8.2 pt or more on paper. The earlier two-column card layout is kept as `print_layout.render_card_svg`. |
| SVG / PNG | `print_layout.render_print_svg`, `png.py` | SVG is the source of truth for the picture; PNG at about 360 dpi for Word. |
| Word drawing | `word_drawing.py`, `svgpath.py` | The same print layout as native Word shapes in one group: zones and cards are shapes, icons are vector freeforms, lines are freeforms with arrowheads, every label is a text box. The PNG is kept as the fallback picture for readers without Word 2010 drawing support. |
| Word document | `word_docx.py` | A standalone `.docx` per figure: A4 landscape for a wide figure, portrait for a tall one, the editable drawing, a caption numbered by Word (`SEQ Figure`), the source line and the technical notes. |
| Placement | `../figures/place.py` | Puts a figure into the working CSA as a tracked change, as a picture or as a Word drawing. |

## Figure design

Researched against the Purdue / IEC 62443 reference architectures, IEC 62443 zone and conduit guidance, network
diagram practice and the C4 review checklist (record: project doc `csa-figures-band-design-record.md`).

- **Bands, top to bottom:** IT and Internet; IT / OT boundary; operational technology. The boundary band holds
  systems whose recorded role is a boundary function (jump host, firewall, bastion, remote access, data diode, proxy).
  When lines cross a zone with no control evidenced and no firewall is in the evidence, it shows a dashed
  "Boundary control: None evidenced" marker. Shared services go to the band the project's residency rule gives.
- **Sites** are panels in the OT band (data centres, other sites, site not recorded, OT-resident services);
  "Location not captured" is a dashed panel in the IT band.
- **One tile per machine role per site:** icon, role (site, domain and instance detail removed), host names, and a
  ×n badge for several hosts. Connections inside one tile are not drawn.
- **One line per function**, coloured by what the traffic is for; every system in that traffic joins it with a short
  tap; the arrowhead marks the system that receives. Service figures (time, DNS) keep one line per provider.
  Zones-and-conduits figures join sites rather than roles.

| Colour | Function | Services (from the port name or process in the capture) |
| --- | --- | --- |
| purple | Directory, name and time services | DNS, Time, NTP, Kerberos, LDAP; RPC or SMB to a domain controller |
| amber | Management and monitoring | RPC, SMB, RDP, SSH, WinRM, VNC, SNMP, Syslog, HealthService, agentService |
| blue | Web and Internet | HTTP, HTTPS |
| teal | Application and database | other named processes (sqlservr, RevAdmin, RevGateway) |
| grey | Other ports | ports with no service name, and ports the capture counted but did not list |

| Line style | Evidence status |
| --- | --- |
| solid | observed in captures; crossing a zone with no control evidenced; admin from outside OT with or without a jump host |
| dashed | configured setting (DNS, Kerberos, time); inferred |
| long dash | path not captured |
| dotted | configured, not in use; documented only |

The legend lists each line with its function, the services on it and, where it matters, its status. No line is
drawn in alarm red. A line shows that systems share a function, not that every pair on it connects: the System
explorer keeps every host-to-host connection.

## Making a figure for another application

1. Register the project in `csa-context/PROJECTS.yaml` and give its data centres and residency rule in
   `csa-context/system-diagrams.json` (`data_centres` left to right with the site names recorded against hosts;
   `residency.it_domains`, `ot_domains`, `evidence`, `basis`).
2. Run discovery and ingest, so `csa-work/hosts/hosts.csv`, the connection captures and `evidence-matrix.csv` exist.
3. `csa figures` lists every section of the working CSA, whether it needs a figure and why.
4. `csa figure <KEY> --save` writes `csa-work/figures/<KEY>/`: `model.json`, `figure.svg` (screen), `figure-print.svg`,
   `figure.png`, `figure.docx` (editable Word drawing), `brief.json`, `fit.json`.
5. `csa figure <KEY> --place [--drawing word]` puts it into the working CSA as a tracked change. The Evidence
   Workspace's CSA figures page does the same with buttons, including the Picture / Word drawing choice.

From Python, with any model that matches the schema:

```python
from csa_docx.techdiagram.print_layout import render_print_svg
from csa_docx.techdiagram.word_docx import write_docx
svg, info = render_print_svg(model)                       # print SVG, info["min_text_pt"] >= 8
write_docx("figure.docx", model, "3.4 Time Synchronisation", "Caption", "Source: ...", notes=model.get("notes"))
```

## Limits

- Word does not keep a freeform line attached to a card: moving a card in Word leaves its lines in place. Move the
  line with it, or move the whole group.
- The print layout is built for the portrait text width. A wide figure is not re-flowed for landscape; the standalone
  document picks landscape only when the drawing is wider than it is tall.
- Line styles show evidence status, not traffic type (application data, management, replication): the captures
  give ports and processes, and naming the traffic type from a port would be an inference.
