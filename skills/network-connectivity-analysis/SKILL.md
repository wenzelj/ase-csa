---
name: network-connectivity-analysis
description: Analyse evidenced network zones, endpoints, flows, ports, protocols, routing, firewall paths, name resolution, and remote connectivity for an Operational Technology Current State Assessment.
---

# Network and Connectivity Analysis

Build a flow matrix with source, destination, direction, purpose, protocol, port, zone, security device or rule reference, environment, owner, status, and evidence ID.

Check for:

- site-to-site and cross-zone communication;
- client-to-application, application-to-database, interface, management, backup, monitoring, and time/name-resolution flows;
- vendor and remote access paths;
- load balancers, proxies, gateways, firewalls, Virtual Local Area Networks (VLANs), routing, and Network Address Translation (NAT);
- unidirectional requirements or control boundaries where evidenced.

Never infer an open port from a product default, or an allowed firewall path from an intended architecture. Distinguish required, documented, observed, and unconfirmed connectivity. Treat Internet Protocol (IP) addresses and hostnames as sensitive project facts and reproduce them only when needed for the authorised deliverable.

Return the connectivity matrix, a plain-language flow description, conflicts, and targeted questions for missing material flows.
