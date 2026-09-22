---
name: dependency-analysis
description: Map upstream, downstream, shared-service, data, vendor, and operational dependencies for an Operational Technology application Current State Assessment.
---

# Dependency Analysis

Build a dependency register containing the assessed component, dependency, direction, purpose, data exchanged, interface or mechanism, site/environment, availability effect, owner, evidence ID, and confidence.

Consider:

- source and destination applications;
- databases, file transfers, message brokers, Application Programming Interfaces (APIs), and manual exchanges;
- identity, Domain Name System (DNS), time, Public Key Infrastructure (PKI), virtualisation, storage, backup, monitoring, and endpoint management;
- field, telemetry, historian, reporting, and enterprise-system relationships;
- vendor services, licensing, remote support, and people/process dependencies.

Distinguish a technical connection from an operational dependency. State whether the consequence of failure is evidenced or inferred. Do not assume interface direction from a diagram arrow without checking its legend or supporting text.

Return the dependency register, critical dependency chains, contradictions, and gaps.
