---
name: resilience-analysis
description: Review current availability, redundancy, failover, backup, restore, disaster recovery, capacity, and single points of failure for an Operational Technology application.
---

# Availability and Resilience Analysis

Assess each important service path, not merely whether a backup product or cluster is mentioned.

Record:

- redundancy and failure domain;
- failover method, trigger, dependency, and test evidence;
- backup scope, schedule, retention, location, immutability where evidenced, and ownership;
- restore procedure and latest evidenced restore test;
- Disaster Recovery (DR) arrangements and dependencies;
- Recovery Time Objective (RTO) and Recovery Point Objective (RPO), distinguishing targets from demonstrated capability;
- capacity or resource constraints;
- single points of failure and operational workarounds.

Do not treat replication as backup, configuration as successful testing, or product capability as implemented control. Mark untested or undocumented recovery claims clearly.

Return a service-level resilience table, confirmed protections, limitations, failure scenarios, and material evidence requests. Keep improvement recommendations separate unless requested.
