---
name: reveloc-csa-skill
description: >
  Application-specific knowledge for analysing and writing Current State Assessments
  for Epiroc/Radlink Reveloc or RevelocPlus deployments, including TETRA-connected
  environments. Use this alongside the existing CSA skills when evidence refers to
  Reveloc, RevelocPlus, RevServer, RevViewer, radio location, GPS radio tracking,
  geofencing, RSSI heat maps, TETRA radio applications, Sepura terminals, DAMM
  infrastructure, or Reveloc extensions. This skill supplements the CSA process; it
  does not replace the existing CSA workflow or writing standards.
---

# Reveloc / RevelocPlus — CSA Application Knowledge Skill

## Purpose

Use this skill only to add **Reveloc-specific system knowledge** to the existing Current
State Assessment workflow.

The existing CSA agent remains responsible for:
- evidence collection and traceability;
- document structure;
- current-state writing;
- gap handling;
- review and validation;
- Australian IT/OT terminology and style.

This skill gives that agent the terminology and functional model needed to interpret
Reveloc evidence correctly.

## Core rule

**Describe the deployed system evidenced at the site, not the full vendor product catalogue.**

Vendor capabilities are background knowledge only. A capability must not be written as
implemented, enabled, licensed, configured, operational or safety-critical unless project
evidence demonstrates that it is.

Use wording such as:
- "RevelocPlus supports..." for vendor capability.
- "The assessed Reveloc environment is configured to..." only when supported by evidence.
- "No evidence was identified confirming that [feature] is enabled" when it matters but is
  not established.

## What Reveloc is

Reveloc originally meant **Remote Vehicle Locator**. The current product is marketed as
**RevelocPlus** by Epiroc/Radlink.

Treat RevelocPlus primarily as an **application platform that consumes information from
digital radio/communications infrastructure and applies location, monitoring, alerting,
reporting and automation functions**.

Do **not** describe Reveloc itself as:
- the TETRA network;
- the radio base station system;
- the GPS constellation/service;
- the MPLS/WAN;
- the radio terminal fleet;
- the dispatch network, unless local architecture explicitly combines these under that name.

A Reveloc deployment can depend on those services, but they are separate architectural
components.

## Functional model

A useful evidence-led logical model is:

```text
GPS-enabled digital radio / field device
            |
            | radio registration, GPS/location, RSSI,
            | telemetry and radio events
            v
Digital radio / communications platform
(TETRA, DMR or other supported integration)
            |
            v
RevelocPlus Core / integration layer
            |
            +--> SQL database / historic records
            |
            +--> Windows client and/or browser interface
            |
            +--> geofence / trigger evaluation
            |
            +--> alerts and actions back to radios
            |    (text, tones, audio where supported)
            |
            +--> optional integrations / exports
                 (e.g. position streams, KML, email,
                 weather services, signage, reporting)
```

This is a **logical reference model**, not proof of the site's physical deployment.
Confirm actual server names, products, database technology/version, network paths,
interfaces and redundancy from evidence.

## Key functions and terminology

### Asset and radio location

RevelocPlus can display and retain location information for GPS-enabled radios.

Preferred terms:
- GPS-enabled radio
- radio identity / radio ID
- asset tracking
- live position
- historic location / historic replay
- tracking map

Avoid saying "GPS tracking installed in Reveloc" unless the architecture evidence supports
that phrasing. More accurate wording is generally that Reveloc **receives/processes
location information from GPS-enabled radios**.

### RSSI

**RSSI — Received Signal Strength Indicator** is radio signal-strength information that can
be logged and visualised.

RevelocPlus can use RSSI for:
- live or historic heat mapping;
- coverage analysis;
- comparison of radios at similar locations;
- network diagnostics.

Do not equate RSSI with end-to-end service quality by itself. It is one radio coverage
indicator and should be interpreted with radio-network evidence.

### Geofencing

A **geofence** is a defined geographic boundary used by Reveloc logic.

Known vendor use cases include:
- exclusion/no-go zone entry;
- confinement zone exit;
- speed controls by area;
- blast zone warning;
- emergency zone management;
- location-driven channel/talkgroup changes.

For a CSA, identify:
- who owns and maintains the geofence definitions;
- source format (manual drawing, CAD/file import, system integration, etc.);
- activation/deactivation process;
- trigger/action logic;
- operator notification path;
- any downstream operational or safety dependency.

### Speed alert

RevelocPlus can compare tracked movement with configured speed thresholds. Vendor
material describes tiered alerting where an initial threshold may warn the radio operator
and a higher threshold may also notify a supervisor.

Do not state that speed is used for enforcement, safety interlocking or automatic vehicle
control unless project evidence explicitly establishes that behaviour.

### Blast Zone Warning

Vendor capability can:
- use manually drawn or imported boundaries;
- identify GPS-enabled radios entering an active blast exclusion area;
- send text or recorded voice alerts;
- notify blast personnel;
- activate/deactivate zones via supported clients.

Treat this as potentially safety-relevant, but do not call it a **safety system**, protection
layer, interlock or firing permissive without evidence and appropriate safety classification.

### Emergency Zone Management

Vendor capability supports location-based emergency messaging to selected geographic
zones rather than necessarily standing down an entire site.

It can also support a dynamic emergency zone around a radio emergency activation.

For a CSA, distinguish:
- radio emergency button behaviour;
- radio network emergency functionality;
- Reveloc location/zone processing;
- dispatcher actions;
- resulting radio messages.

Do not merge these into one component.

### Channel Assist / geofenced channel change

RevelocPlus can use radio movement across geofences to trigger the channel/talkgroup
selection appropriate to an area on compatible/configured radios.

Use **talkgroup** when the evidence is specifically TETRA group communications.
Use **channel** when quoting the product feature or when the local configuration uses that
term.

Confirm:
- whether the feature is enabled;
- affected radio models;
- talkgroup/channel mappings;
- whether operator opt-out is configured;
- dependency on location updates and radio application support.

### Keep Alive Monitoring

Vendor functionality can notify when specified radio equipment loses coverage or
unexpectedly deregisters from the network.

Do not confuse this with:
- IP heartbeat/cluster monitoring;
- Windows service monitoring;
- TETRA base-station health monitoring.

Determine exactly what object is being monitored.

### Network analysis

RevelocPlus network diagnostic functions may include:
- Air Interface Viewer;
- RSSI heat mapping;
- node coverage analysis;
- node handover visualisation;
- PTT press/release display;
- neighbouring-node information;
- KML export.

Terminology:
- **PTT** — Push-to-Talk.
- **node** — use only as defined by the site's radio platform; do not automatically translate
  this to "server", "base station" or "repeater".
- **handover** — movement of radio service between radio coverage nodes/sites.
- **KML** — Keyhole Markup Language, commonly used for geographic visualisation/export.

### Log KPI Extractor

An optional/configured extension can analyse radio-network usage information such as:
- individual calls;
- group calls;
- node;
- shift;
- radio group/talkgroup.

Treat this as reporting/analysis functionality. Verify local licensing and data source.

### RevBroadcast

Vendor material describes RevBroadcast as an extension that can:
- export or stream position data to other systems;
- run scheduled database queries;
- automate coverage reports;
- identify radios reporting comparatively low signal strength.

When found in a CSA, treat it as an **integration/reporting component** and capture:
- source and destination;
- protocol/interface;
- schedule or trigger;
- data fields;
- service account;
- failure handling;
- downstream dependency.

### RevWeatherWatch

Vendor functionality can ingest weather advisory information and trigger radio audio
messages and, where configured, external safety signage/beacons.

This creates a potential **IT-to-OT / external-service dependency**. If deployed, identify:
- external weather provider;
- email/API/web-service path;
- Reveloc server/service receiving it;
- radio network action;
- signage/beacon interface;
- failure and fallback process.

Do not assume it is enabled.

### RevPrestart

Vendor material describes RevPrestart as a paperless vehicle pre-start capability using
compatible Sepura radio application functionality to collect maintenance/odometer
information and route it to relevant personnel.

Only discuss it when project evidence indicates it is licensed or used.

## TETRA context

**TETRA — Terrestrial Trunked Radio** is a digital trunked radio standard. Reveloc can be
integrated with TETRA, but Reveloc and TETRA are not synonyms.

In a TETRA-connected environment, keep these layers distinct:

```text
Radio terminal (for example, a vehicle or handheld terminal)
        |
TETRA air interface / coverage
        |
TETRA base station / node infrastructure
        |
TETRA switching / core / management platform
        |
Integration/interface
        |
RevelocPlus application and data services
        |
User clients / integrations / reports / alerts
```

Relevant TETRA terms an agent may encounter:
- terminal / subscriber radio;
- Individual Short Subscriber Identity (ISSI), if present in evidence;
- talkgroup;
- group call;
- individual call;
- registration / deregistration;
- PTT;
- base station / radio site;
- handover;
- coverage;
- RSSI;
- emergency call/button.

Do not introduce an acronym such as ISSI into the CSA merely because TETRA supports it.
Use it only where it exists in the evidence.

## Aurizon historical public context — use cautiously

Public material from 2017 described an Aurizon Central Queensland TETRA deployment using:
- DAMM TetraFlex radio base stations;
- Sepura radio terminals;
- connectivity over Aurizon's Central Queensland MPLS network;
- Radlink Reveloc application functionality;
- geofenced auto channel change;
- weather alerts;
- heat maps showing radio identity/location;
- speed alerts and signal strength;
- a mobile client.

This is useful domain context **only**. It is historical public information and must not be
presented as the present CSA configuration without current evidence.

When site evidence conflicts with this historical description, the current site evidence wins.

## CSA evidence to look for

When Reveloc appears in scope, inspect available evidence for the following.

### Application
- product name: Reveloc, RevelocPlus, RevelocPlus Core;
- application version/build;
- installed modules/extensions;
- Windows services/processes;
- application install paths;
- configuration files;
- scheduled tasks;
- log locations;
- client type: Windows desktop and/or browser;
- licensing information.

### Hosting
- physical/virtual server name;
- operating system/version;
- CPU/RAM/storage allocation;
- virtualisation platform;
- site/location;
- active/passive, cluster or other redundancy;
- backup/restore arrangement;
- DR arrangement;
- server time source;
- service accounts.

### Database
Vendor information states that RevelocPlus Core logs GPS, RSSI and telemetry information
into an SQL database. Determine the actual site implementation:
- database platform and version;
- instance/database name;
- local vs remote DB;
- authentication;
- backup;
- retention;
- growth;
- HA/DR;
- consumers/direct query integrations.

Do not assume Microsoft SQL Server merely from the word "SQL". Legacy Reveloc literature
listed several Microsoft database options, but the current deployment must be evidenced.

### Radio network integration
- radio technology: TETRA, DMR or other;
- radio network vendor/platform;
- interface from the communications platform to Reveloc;
- gateway/server/device dependencies;
- ports/protocols;
- radio identity mapping;
- GPS update mechanism and interval;
- RSSI source;
- telemetry fields;
- registration/deregistration events;
- alert/message path back to radios.

### Network
- Reveloc server VLAN/subnet/zone;
- firewall paths;
- DNS dependencies;
- NTP/time synchronisation;
- routed/WAN/MPLS dependencies;
- remote site connectivity;
- client access path;
- integrations crossing IT/OT/security boundaries.

### Functional configuration
- configured maps and coordinate system;
- geofences;
- speed thresholds;
- blast zones;
- emergency zones;
- channel/talkgroup rules;
- weather integration;
- coverage analysis;
- reporting;
- external data feeds;
- alert recipients;
- operator roles.

### Operational support
- system owner;
- business owner;
- radio/telecommunications support team;
- vendor support arrangement;
- monitoring;
- incident handling;
- maintenance windows;
- patching;
- access management;
- account lifecycle;
- change control;
- recovery procedures.

## Dependency model

Classify dependencies rather than listing components without explaining their role.

Typical Reveloc dependency categories:

| Dependency | Why it matters |
|---|---|
| GPS-enabled radio terminals | Source of radio identity/location and potentially telemetry |
| Digital radio network | Carries radio service/events/data used by Reveloc and delivers actions back to radios |
| Radio platform integration | Supplies the interface between radio infrastructure and Reveloc |
| IP network/WAN | Connects server, radio-system components, clients and integrations where applicable |
| SQL database | Stores location/RSSI/telemetry and historic operational data |
| Server OS/virtual platform | Hosts Reveloc application services |
| Time synchronisation | Important for event correlation, historic replay and logs |
| DNS | Dependency only where hostnames/FQDNs are actually used |
| Mapping/geospatial data | Supports position visualisation and geofenced functions |
| External systems | May provide weather, CAD/zone data, reporting destinations or other integration data |
| User/client endpoints | Provide operator/administrator access |

Do not mark every item as "critical". Determine impact from the deployed function and evidence.

## Failure-impact reasoning

Use causal language.

Examples:

**Radio network loss**
> Loss of the radio network would prevent or degrade the flow of radio location/events to
> Reveloc and may prevent Reveloc-generated alerts or actions from being delivered to
> affected radios. The exact impact depends on the integration and coverage failure mode.

**Reveloc application outage**
> An outage of Reveloc would affect the Reveloc-provided tracking, geofence processing,
> alerting, historic visibility and/or reporting functions that are enabled at the site.
> It does not by itself prove that core TETRA voice communications would fail.

**Database outage**
> Where the application depends on the database for live processing or persistence, a
> database outage may affect application operation and historic data capture. Confirm the
> site's runtime behaviour and recovery design before specifying impact.

**WAN/MPLS loss**
> Determine whether the failure isolates a radio site only from Reveloc, also affects the
> TETRA network/core, or both. Do not infer this from architecture labels alone.

## Writing rules for the CSA

Write about the **application and system current state**, with evidence supporting the
description.

Prefer:
> RevelocPlus receives GPS, RSSI and radio telemetry information from the digital radio
> environment and records the information in its application database. The application is
> used by [evidenced users] for [evidenced functions].

Avoid:
> The data shows lots of GPS information and many radio records.

Prefer:
> The configured geofences provide location-based trigger areas used for [evidenced
> purpose].

Avoid:
> The geofence table contains 42 polygons.

The number of polygons is evidence; the system function is the current-state point.

## Terms that must not be conflated

- Reveloc / RevelocPlus != TETRA
- Reveloc server != TETRA core
- radio terminal != Reveloc client
- GPS position != RSSI
- radio coverage != IP network reachability
- talkgroup != physical radio channel/frequency in all contexts
- geofence alert != physical safety interlock
- application redundancy != radio-network redundancy
- historic replay != backup
- database retention != backup retention
- radio registration != Windows/application login
- emergency radio feature != Reveloc Emergency Zone Management

## Evidence-confidence rules

Use this priority:
1. current project evidence from the assessed environment;
2. current configuration exports/screenshots/logs and operational confirmation;
3. vendor documentation for the deployed version;
4. current vendor product information;
5. historical vendor/product information;
6. third-party articles.

Vendor documentation can explain **what a feature means**, but it cannot prove the site
uses it.

When uncertain, explicitly record:
- `Confirmed`
- `Supported by evidence`
- `Vendor capability — deployment not confirmed`
- `Not established from available evidence`

## High-value questions for SMEs

Ask only where evidence does not already answer them:

1. Which Reveloc/RevelocPlus version and licensed modules are in use?
2. Which servers and database instances make up the production service?
3. How does Reveloc interface with the radio network/core?
4. Which radio technologies and terminal models supply location/telemetry?
5. What is the GPS update interval and how are stale positions handled?
6. Which geofence-triggered functions are enabled?
7. Are speed alerts, channel assist, blast-zone or emergency-zone functions operational?
8. Which functions are considered operationally or safety significant?
9. What happens to TETRA voice communications if Reveloc is unavailable?
10. What happens to Reveloc if the WAN/MPLS path to a radio site is lost?
11. Is Reveloc redundant, and how is application/database failover performed?
12. What historic data is retained and for how long?
13. Which external systems consume Reveloc data?
14. Which external systems feed Reveloc?
15. Who owns application support, radio-network support and database support?
16. How are maps, geofences and radio-to-asset mappings maintained and approved?

## Output expectation

When this skill is active, the CSA agent should produce a technically accurate description
of the **actual Reveloc application in its radio-system context** and should be able to
distinguish:
- application services;
- radio infrastructure;
- location/telemetry data;
- database and hosting;
- integrations;
- configured operational functions;
- dependencies;
- failure impacts;
- evidence gaps.

It must not turn the CSA into a vendor brochure.
