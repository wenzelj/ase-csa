## B4 Discovery Information note
Facts:
- Two SQL Server cluster nodes in the same group take their time from different servers, with HOSTCLU03 on TIMESRV224 and HOSTCLU01 on TIMESRV122. (E-0210, E-0214) {observed; HOSTCLU01, HOSTCLU03}
Text:
The SQL Server cluster nodes do not share one time source, as HOSTCLU03 follows TIMESRV224 while the other nodes follow TIMESRV122.

When nothing falls outside the table, the whole block is one line and the framework removes the placeholder:

## B4 Discovery Information note
None: every captured host fits a row of the table.
