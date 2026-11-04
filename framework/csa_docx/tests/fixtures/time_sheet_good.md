## B1 SEP-TIME-01
Facts:
- MOTPRDSRV122 and ROTPRDSRV122 are domain controllers hosted in the OT network, and MOTPRDREV101 and MOTPRDLOG103 take their time from them. (E-003, E-004) {observed; MOTPRDSRV122, ROTPRDSRV122}
- MOTPRDREV101 and MOTPRDLOG103 at Mackay take their time from ROTPRDSRV122 at Rockhampton. (E-005) {observed; MOTPRDREV101, MOTPRDLOG103}
- The time sources sit at stratum 5 in the latest capture. (E-3173) {observed; MOTPRDSRV122}
Summary: The time sources are domain controllers hosted in OT. The Mackay hosts depend on a source at another site. The requirement is Partially Met because the sources are OT-hosted but share one domain hierarchy.
Story: Sources are OT domain controllers. Mackay uses the Rockhampton controller. Stratum counts the steps a clock is from the reference clock. Most hosts show stratum 5.
Rating: Partially Met
Rating reason: Mackay takes its time from the Rockhampton controller (E-005), so the sites are not independent.

## B2 Discovery Information
Rows:
| Aspect | Finding |
| Time poll interval | General Purpose Jump Hosts poll every 16,384 s at Mackay and 32,768 s at Rockhampton |

## B3 Optional note
Facts:
- Every host runs the Windows Time service. (E-004) {observed; all hosts}
