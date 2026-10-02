## B1 SEP-TIME-01
Facts:
- Every captured host synchronises from one of three enterprise time servers. (E-063) {observed; all 12 captured hosts}
- No time source inside the OT environment was found in the captures. (E-112) {observed; all 12 captured hosts}
- Two hosts also list a public internet time server as a second peer that is not in use. (E-061) {observed; HOSTLOG02, HOSTAPP37}
Unknown: whether any host keeps a usable clock when the enterprise time servers cannot be reached.
Rating: Not Met
Rating reason: the requirement asks for an OT-resident time source; every host depends on the enterprise servers.
