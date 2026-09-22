---
name: ot-architecture-analysis
description: Explain and assess the evidenced current architecture of an Operational Technology application across components, sites, trust boundaries, and OT zones. Use for current-state architecture, not future-state design.
---

# OT Architecture Analysis

Create a current-state architecture view from verified components and relationships.

Identify:

- application tiers and deployment boundaries;
- sites and hosting locations;
- Operational Technology (OT), Information Technology (IT), demilitarized zone, and other evidenced network boundaries;
- operator, engineering, vendor, and administrative access paths;
- data acquisition, processing, storage, reporting, and control relationships;
- shared infrastructure and cross-boundary dependencies;
- architectural constraints, unclear boundaries, and evidenced single points of dependency.

Label every inferred relationship. Do not place a component in an OT zone because its function sounds industrial. Do not claim segmentation, trust, or isolation without network or security evidence.

Prefer a small component/dependency table plus a diagram when topology is materially clearer visually. Attach evidence IDs to nodes or relationships. Keep observations separate from recommendations.
