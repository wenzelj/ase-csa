## B1 SEP-TIME-01
Facts:
- The application servers take their time from three enterprise time servers. (E-0063) {observed; application servers}
- The Windows Time client on each application server lists no time source inside the OT environment. (E-0112) {observed; application servers}
- Two application servers also list a public internet time server as a second peer that is not in use. (E-0061) {observed; application servers}
QUESTION: Which time source, if any, keeps the application servers synchronised when the enterprise time servers cannot be reached?
Summary: The application servers depend on the enterprise time servers and no OT-resident time source was identified. The requirement is Not Met because it asks for an OT-resident source.
Story: The application servers take their time from three enterprise time servers through the Windows Time client. Two of them also list a public internet time server, which is not in use.
Story: Nothing inside OT supplies time. If the enterprise time servers cannot be reached, the servers have no listed source to use instead.
Story: It is not established whether any server keeps a usable clock during isolation.
Rating: Not Met
Rating reason: the requirement asks for an OT-resident time source, and every application server depends on the enterprise servers.

## B2 SEP-GEN-01
Facts:
- No dedicated OT asset inventory or configuration management tool was identified. (E-0201) {stated; in-scope systems}
- A point-in-time asset list was compiled before the assessment began. (E-0202) {documented; in-scope systems}
- The building management system is excluded from this assessment and will be assessed separately. (E-0203) {documented; building management system}
Summary: No maintained OT asset inventory or configuration management database was identified, and a one-off list is the only substitute. The requirement is Not Met because it asks for a maintained, classified inventory.
Story: The organisation holds a point-in-time asset list that was compiled before the assessment began. No tool that keeps the list current was identified.
Story: The building management system is excluded from this assessment and will be assessed separately.
Rating: Not Met
Rating reason: the requirement asks for a maintained, classified inventory, and only a one-off list exists.
