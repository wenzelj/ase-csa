# CSA coverage guide

Use only the areas relevant to the assessed system:

- purpose, users, criticality, lifecycle, and operational impact;
- logical components and deployment model;
- physical and virtual infrastructure, storage, database, and platform services;
- Operational Technology (OT) zones, network paths, protocols, ports, and remote access;
- identity sources, authentication, authorization, service accounts, and privileged access;
- upstream, downstream, vendor, data, time, name-resolution, and certificate dependencies;
- redundancy, failover, backup, restore, Disaster Recovery (DR), and single points of failure;
- ownership, support, monitoring, patching, maintenance, licensing, and vendor arrangements;
- current security controls, exposures, exceptions, and evidence limitations.

A section is complete when every paragraph sits in the section and subsection that own it (see `.agents/skills/csa-quality-review/references/section-scope.md`), material claims are traceable, uncertainties are labelled, contradictions are visible, remaining gaps are either resolved or accepted as limitations, and the text passes the concision and flow check: conclusion first, each fact stated once, full sentences rather than bullet fragments, and host-level detail in tables (see `csa-writing-style`; measure with `prose_lint.py`).
