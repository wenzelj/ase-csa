# Topic-table profiles

One JSON file per section topic. `csa_docx.topic_tables` reads them to build the role-grouped table
under a section's Discovery Information heading, above the Aspect table. Design:
`.agents/docs/topic-tables-spec.md`.

A profile is matched by heading text (`headings`), never by section number, so a section added
mid-document still finds its profile.

```json
{
 "topic": "Time Synchronisation",          // the topic name used in sentences
 "key": "TIME",                            // Discovery Required ids: DR-<KEY>-Tnn
 "headings": ["Time Synchronisation"],     // heading texts this profile serves
 "requirements": ["SEP-TIME-01"],          // requirement ids a gap affects
 "columns": [
  {"label": "Time source",                 // column header
   "attribute": "time.source",             // host_settings.csv attribute
   "explains": "where each host takes its time from",   // the scope map's Must explain point it answers
   "common": "take time from {value}"}     // phrase used when every host has the same value
 ]
}
```

Column options (all optional):

- `"noun"`: the thing named when every host has "None found" ("have no backup agent found").
- `"common_none"`: the whole phrase for that case instead.
- `"list": true`: the value is a list ("A, B, C"). Members every captured host shares go to the sentence under
  the table (`"common_shared": "have {value} in local Administrators"`, `{s}` gives a plural), and each cell
  keeps only what differs, or `"rest_none"` ("No others").
- `"keep": true`: the column stays in the table even when every host has the same value.
- `"flows": {...}`: the column is filled per host from the flow inventory with the flow filter below (what the
  host opened, by mechanism; "Attempted only: ..." when only connection requests were seen); `"none"` is the
  value when nothing matches ("None seen").

Profile options:

- `"common_values": {"value": "phrase"}`: a fixed phrase for a common value.
- `"flows": {...}`: adds a data-flow table under the role table. Filter keys (all must hold): `status`
  (observed, both, declared, attempted), `mechanisms`, `exclude_mechanisms`, `data`, `cross_zone`
  (yes, no, unknown), `dst_zones` (a zone name contains one of these), `direction` (inbound or outbound,
  against the host register), and `any_of` (a list of filters, at least one must hold). The same filter
  is used by the analysis frames (`references/topic-frames/`), through `flows.select`.

What the framework decides from the data, not the profile:

- A column whose value is the same for every captured host moves into one sentence under the table
  ("All hosts in this table run the Windows Time Service, operate at stratum 5 and ...").
- A column with no captured value is dropped.
- At most four columns may vary (A4 portrait); more gives a warning. Column widths follow the content and are never
  narrower than the longest word in the header or a cell.
- Rows are role groups from `hosts/hosts.csv`, split only where captured hosts differ.
- Hosts with no capture take their role's values and are marked with a dagger, with a Discovery Required item.
- No counts or totals.

To add a topic: add its attributes to `framework/csa_docx/host_settings.py` (with capture file and
line for every value), then add a profile here. `python3 -m csa_docx.topic_tables profiles` lists them.

Site order for sub-rows and host lists: `csa-work/hosts/sites.txt`, one site per line (optional).

Attributes come from `host_settings.py` (time, DNS, storage, transfer, agents, identity, admin, platform,
patch, network, firewall, certificates) and from `isolation.py` (`iso.*`, the isolation dependency
matrix, in `hosts/isolation.csv`). `python3 -m csa_docx.host_settings show --work-dir <csa-work> [HOST]`
prints them.
