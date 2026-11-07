# Reveloc / RevelocPlus Reference Notes

This file supports `SKILL.md`. It contains product background that helps an agent interpret
evidence. Treat it as reference knowledge, not proof of the assessed deployment.

## Product identity

- Reveloc originally stood for **Remote Vehicle Locator**.
- The current Epiroc/Radlink product branding is **RevelocPlus**.
- Epiroc states that RevelocPlus tracks assets via GPS-enabled radios and supports historic
  log replay and alerts including speeding, exclusion-zone entry and confinement-zone exit.
- Epiroc completed its acquisition of Radlink in April 2025.

## Current RevelocPlus Core description

Radlink describes RevelocPlus Core as the primary interface between multiple manufacturers'
communications platforms and end-user scenarios.

The platform can log:
- GPS information;
- RSSI;
- telemetry from remote field equipment;

into an SQL database and compare the information against configured trigger conditions.

Current vendor material states that data can be viewed through:
- a Windows desktop application;
- a standard web browser.

## Product capability catalogue

Capabilities documented by Radlink include:

- live tracking of GPS-enabled digital radios;
- historical replay;
- excessive-speed alerts;
- exclusion-zone entry alerts;
- confinement-zone exit alerts;
- radio alerts using text, tones or audio;
- text-to-speech generated audio;
- blast-zone warnings;
- emergency-zone management;
- location-driven channel changes;
- keep-alive monitoring;
- asset validation;
- radio network/RSSI analysis;
- Air Interface Viewer;
- RSSI heat mapping;
- node coverage analysis;
- Log KPI Extractor;
- RevBroadcast;
- RevWeatherWatch;
- RevPrestart.

These features may be separately licensed or site-configured. Their presence in vendor
material does not establish that they are deployed.

## Diagnostic concepts

### Air Interface Viewer
Vendor material describes visualisation of survey data from a GPS-enabled radio, including:
- signal strength;
- node handover points;
- PTT press/release events;
- neighbouring-node information.

### Heat mapping
Can plot live/historic radio positions according to RSSI.

### Node Coverage Analysis
Can generate a KML-exportable grid based on average RSSI and filter analysis by node or
asset class.

### Log KPI Extractor
Can be configured to report call activity by dimensions such as:
- node;
- shift;
- radio group;
- individual call;
- group call.

## Integration concepts

### RevBroadcast
Vendor material describes export/streaming of position data, scheduled custom database
queries and automated report generation.

### RevWeatherWatch
Can use professional weather advisory inputs and translate alerts into radio-network audio
messages. Vendor material also describes optional control of warning signage/beacons.

### Blast Zone Warning
Can create boundaries manually or by importing CAD-based data and alert GPS-enabled radios
that enter an active blast zone.

## Legacy Reveloc architecture — historical context only

Older Simoco Reveloc AVL documentation described a Microsoft Windows-based system with:
- a Reveloc server / RevServer;
- database;
- RF gateways;
- LAN/WAN connectivity;
- client PCs running RevViewer, Google Earth Pro or corporate GIS;
- MPT1327 and DMR radio network support;
- geofencing;
- short-data messaging;
- KML export;
- SOS alerting;
- telemetry/ignition monitoring.

Do not assume these legacy product names or components exist in a current RevelocPlus
deployment. They are useful search terms when reviewing older infrastructure.

## TETRA and Aurizon — historical public reference

A 2017 public industry report about Aurizon's Central Queensland network described:
- TETRA digital radio;
- 79 sites and approximately 2,670 km of rail network at the time of rollout;
- DAMM TetraFlex base stations;
- Sepura radio terminals;
- an Aurizon Central Queensland MPLS network transport dependency;
- Radlink Reveloc digital radio application software;
- geofenced automatic channel change;
- weather alerts;
- radio-location heat maps;
- speed alerts;
- signal-strength visibility;
- a mobile-phone radio client.

This should be treated as **historical architecture context**, not as a statement of the
current environment. A CSA must confirm the present implementation from current evidence.

## Terminology quick reference

| Term | Meaning in this context |
|---|---|
| Reveloc | Original/legacy product name; historically "Remote Vehicle Locator" |
| RevelocPlus | Current Radlink/Epiroc application suite/platform |
| RevelocPlus Core | Core application/integration layer described by Radlink |
| GPS | Global Positioning System; position source in GPS-enabled radios |
| RSSI | Received Signal Strength Indicator; radio signal-strength measurement |
| Geofence | Virtual geographic boundary used as a trigger condition |
| TETRA | Terrestrial Trunked Radio digital trunked radio standard |
| DMR | Digital Mobile Radio |
| PTT | Push-to-Talk |
| Talkgroup | Logical group communication construct in trunked radio systems |
| Handover | Transfer of radio service between coverage nodes/sites as a radio moves |
| KML | Keyhole Markup Language geographic data format |
| CAD | Computer-Aided Design; may be a source of blast-zone boundaries |
| Telemetry | Operational/status data received from remote field equipment |
| Node | Radio-platform term; interpret according to local product design |
| RevBroadcast | Optional RevelocPlus integration/reporting extension |
| RevWeatherWatch | Optional weather-to-radio alerting function |
| RevPrestart | Optional paperless vehicle pre-start function |
