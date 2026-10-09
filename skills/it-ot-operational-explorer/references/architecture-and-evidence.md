# Canonical system data and evidence

Maintain separate JSON assets for topology (`system.json`), scenarios (`scenarios.json`), and references (`evidence.json`). Add JSON Schema / TypeScript types and validation.

## Entity
`{id, name, kind, layer, role, siteId?, environment?, properties?, evidenceRefs:[], status}`
Kinds: application, application_service, interface, database, host, vm, network_device, network_zone, ot_device, identity_service, infrastructure_service, site, external_system.

## Relationship
`{id, source, target, kind, direction, protocol?, port?, payload?, evidenceRefs:[], status, inferenceRationale?}`
Kinds: SENDS_TO, RECEIVES_FROM, RUNS_ON, HOSTED_AT, DEPENDS_ON, AUTHENTICATES_WITH, RESOLVES_VIA, REPLICATES_TO, BACKS_UP_TO, CONNECTED_TO, FAILS_OVER_TO, LOCATED_AT.
Avoid extrapolating bidirectional traffic from a one-way relationship. Draw network and application dependencies in separate semantic categories.

## Evidence
`{id, document, section?, page?, quoteOrSummary?, filePathOrUri?, inspectedAt?}`.
Local file/section references are acceptable; do not fabricate URLs or page numbers.

## Scenario
`{id, title, purpose, trigger, evidenceRefs:[], status, steps:[{id, componentId, action, narrative, incomingEdgeId?, outgoingEdgeId?, payloadLabel?, evidenceRefs:[], status, visualDurationMs?}]}`
A stage is an operation, not necessarily a distinct host. Repeated components are allowed. Transitions should only use graph edges backed by evidence. Treat UI animation duration as illustrative presentation pacing.

## Validation rules
- Unique IDs and valid foreign keys.
- Every material assertion has evidence, is visibly inferred, or visibly unknown.
- Scenario steps occur in an order supported by evidence; if order is unverified, mark it as a conceptual view and do not describe it as a factual sequence.
- Do not assume failover is automatic or that redundancy implies zero downtime.
- Keep physical hosting, application flow and network transport separable.
- Redact secrets and sensitive configuration by default; optionally obfuscate hostnames/IPs in external deliverables.
