## B1 SEP-TIME-01
Facts:
- Every captured host synchronises from one of three enterprise time servers. (E-0063) {observed; all 12 captured hosts}
- No time source inside the OT environment was found in the captures. (E-0112) {observed; all 12 captured hosts}
- Two hosts also list a public internet time server as a second peer that is not in use. (E-0061) {observed; HOSTLOG02, HOSTAPP37}
Unknown: whether any host keeps a usable clock when the enterprise time servers cannot be reached.
Rating: Not Met
Rating reason: the requirement asks for an OT-resident time source; every host depends on the enterprise servers.

## B2 SEP-GEN-01
Facts:
- No dedicated OT asset inventory or CMDB tool was identified. (E-0201) {stated; all in-scope systems}
- A point-in-time asset list was compiled prior to discovery for this assessment. (E-0202) {documented; all in-scope systems}
- The building management system is excluded from this CSA and will be assessed separately. (E-0203) {documented; building management system}
Rating: Not Met
Rating reason: the requirement asks for a maintained, classified inventory; only a one-off list compiled for the assessment exists.
(Not here: the hosts and roles discovery found. They go in the Hosts and roles table.)
