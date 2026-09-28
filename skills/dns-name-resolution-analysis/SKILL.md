---
name: dns-name-resolution-analysis
description: Establish and assess the current name-resolution state of an Operational Technology application -- configured resolvers, DNS type (AD-integrated vs standalone), zone and record behaviour, the services that depend on name resolution, and the isolation consequence. Use for the DNS / name-resolution domain of a CSA (legacy Section 5, template domain 3.5).
---

> Examples in this skill come from the UTC DTC assessment (role names such as TCSI, SIGMAP and Left/Right pairs). The rules are general: use the assessed system's own role names and evidence, never these examples as facts.

# DNS / Name-Resolution Analysis

Terminology: name every component, service, dependency and interface with `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), classify it as OT, supporting IT, shared, platform or external, and write in Australian English.

Write this domain as a statement about **how the application environment resolves names today**, and what that means when the OT boundary is isolated. Follow the shared rules in `csa-section-writer/references/current-state-reasoning.md` (subject rule, fact/evidence/gap classes, "not observed" vs "does not exist", correlation, scope, terminology) and the prose rules in `csa-writing-style` before drafting.

## Purpose

Describe the current name-resolution state of the application and its supporting environment: which resolvers are configured, whether DNS is Active Directory-integrated or standalone, what the domain actually resolves to, which operational services depend on name resolution, and what breaks -- and how fast -- if the OT environment is isolated from the IT-provided name resolution.

## Questions the section must answer

1. What resolvers are configured on the application hosts, and on which interface?
2. Is DNS Active Directory-integrated or standalone (BIND-style zone files)?
3. What does the application domain / key service names actually resolve to (which address ranges, which sites)?
4. Which operational services depend on this name resolution (authentication, time, patching, email, PKI, file services)?
5. What is the isolation consequence: does the application lose name resolution immediately, degrade, or keep working?
6. What is not established from the available evidence (zone backup, DNSSEC, conditional forwarders, forest root location)?

## Expected source evidence

- Per-host resolver configuration (`Get-DnsClient` / `ipconfig /all` output, NIC-level).
- DNS resolution tests for the AD domain and key service FQDNs (`nslookup`, `Resolve-DnsName`).
- Active Directory domain membership and OU location.
- Architecture / design documentation that names the intended DNS model.
- The application's module configuration files that reference a partner or service by name.
- Prior assessment records that describe the DNS model and its drawbridge/isolation treatment.

## How to analyse and correlate

- **Correlate before writing.** Resolver config + resolution tests + AD membership together establish whether DNS is AD-integrated and where the forest root sits. Do not write "the resolver shows X; the AD record shows Y; the test shows Z" -- write the one system statement those three sources jointly establish.
- **Distinguish the resolver configuration from the resolution behaviour.** Configured resolvers (what is set on the NIC) and what the domain actually resolves to (the A-record set, which sites) are two different facts. State each once, in its own subsection.
- **Map the dependent services, not just the DNS server.** The operational meaning of a DNS dependency is the list of services that stop working when it does (authentication, time, patching, email, PKI). That list is the finding; the two resolver IPs are the support.

## Handling conflicting evidence

- If the configured resolvers point at one set of servers but the domain resolves to records in a different address range, that is a co-hosting / forest-root question, not a conflict to silently resolve. State the observed fact (records span both IT and OT ranges) and record the forest-root location as an assessment gap if it is not confirmed.
- Never pick one source over another without naming which is more authoritative and why. If it stays unsettled, it is a gap, not a choice.

## Handling gaps and unknowns

State as gaps, scoped to what was searched: DNS zone backup, DNSSEC, conditional forwarders / split-horizon, DNS monitoring, forest root location, and the behaviour of AD-integrated DNS under isolation. "Not observed in the supplied evidence" is not "not implemented".

## Expected IT/OT terminology

Follow `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`); its table is in `references/terminology.md`. For name resolution in particular:

- **Terms:** name resolution, DNS server, configured DNS servers (resolvers) on a named network interface, Active Directory-integrated DNS, standalone DNS, forward lookup zone, A record, SRV record (Kerberos and domain controller location), conditional forwarder, split-horizon DNS, domain joined, forest root, site. "OT-resident name resolution" is the program's target-state term: use it for the target, not for what exists today unless it does.
- **Say what the DNS servers are.** When the resolvers are domain controllers of the enterprise domain, say so: "the INTERNAL domain controllers ROTPRDSRV122 and MOTPRDSRV122, which also provide DNS". Do not call them "OT DNS servers" because OT hosts use them or because they sit at an operational site. State location and ownership as separate facts when both are known ("located at the Rockhampton and Mackay sites, on addresses in the OT-side range, but part of the enterprise INTERNAL domain").
- **The subject is the name-resolution dependency**, not the resolver file or the test output: "The application hosts resolve names through ...", "Name resolution is provided by ...". Keep "observed", "the current configuration shows" for the places where the strength of the evidence matters, such as the forest-root question.
- **Dependent services** are named as services, not as records: Windows authentication (Kerberos), time synchronisation, patching through Configuration Manager, email alerts through Exchange, certificate revocation checking.

## Expected section structure

- **Design / expected** (where the template has it): the intended DNS model, in one to three sentences.
- **Observed configuration and behaviour**: resolver table (server, FQDN, IP, site, interface); the resolution behaviour of the AD domain and key services; AD domain context (membership, OU).
- **Dependent services**: a table of the operational services that depend on this name resolution and what each needs from it.
- **Drawbridge / isolation impact**: one paragraph on what fails, whether it is immediate or gradual, and what keeps working.
- **Technical explanation** (labelled note, optional): why AD-integrated DNS behaves the way it does under isolation (zone data in the AD database, replication dependency).
- **Evidence appendix**: source files with E-ids.

## Tables and diagrams that help

- Resolver table: server, FQDN, IP address, site, interface.
- Resolution-behaviour table: name, record type, resolved address ranges, which side (IT/OT) each range is on.
- Dependent-services table: service, what it needs from name resolution, evidence.
- A small diagram of the name-resolution path (host -> resolver -> AD zone -> dependent services) where topology is clearer visually.

## How findings are written

Each finding is one short paragraph: the current condition (how names are resolved today), the design or reference expectation it is measured against, and the isolation consequence. Lead with the system statement, not the data. Example:

> The application hosts resolve names through the two INTERNAL domain controllers, one at each site, which provide Active Directory-integrated DNS. Because the zone data lives in the Active Directory database, the name-resolution, authentication and time-synchronisation dependencies fail together when the OT boundary is isolated; the hosts keep resolving their last cached names for a short period, then lose both.

## What belongs and what does not

- **Belongs:** resolver configuration, DNS type, resolution behaviour, dependent services, isolation consequence, name-resolution gaps.
- **Does not belong:** the domain controllers as identity/auth components (goes to the Identity & Authentication domain); host inventory (goes to the asset-inventory domain); the firewall rules that permit port 53 (goes to the network / perimeter domain); NTP mechanics (goes to the time-synchronisation domain -- keep only the name-resolution dependency on it here).

## Validation / review checks

Run `csa-writing-style/scripts/prose_lint.py` on the section. Then confirm:

1. The subject of each sentence is the application environment or a service, not "the discovery data" / "the table" / "the capture".
2. Every material statement traces to an E-id in the change record / Word comment / evidence matrix.
3. Resolver configuration and resolution behaviour are stated separately and not conflated.
4. The dependent-services list is present and each service is tied to what it needs from name resolution.
5. The isolation consequence is stated once, with immediate vs gradual behaviour distinguished.
6. Gaps (zone backup, DNSSEC, forwarders, forest root) are scoped, not asserted as absences.
7. Terminology follows `australian-it-ot-terminology`: `term_lint.py` has been run and every flag resolved; the DNS servers are named for what they are (enterprise domain controllers, or dedicated DNS servers), not labelled OT because OT hosts use them.
8. The section agrees with the Identity & Authentication and Time Synchronisation sections on the AD dependency.

## Common failure patterns

- Writing the section as a tour of the resolver file and the test output, with the system only implied.
- Treating "the domain resolves to 11 records" as the finding, when the finding is which of those are IT-side and what that means for isolation.
- Conflating configured resolvers with resolution behaviour, or stating one where the other is meant.
- Asserting the forest root location (IT or OT side) when the evidence only shows records spanning both ranges.
- Duplicating the dependent-services list in the Identity and Time sections instead of pointing to them.
- Calling the enterprise domain controllers "OT DNS servers", or describing the INTERNAL domain as part of the OT application, when it is an enterprise IT service the application depends on.
- Letting the evidence become the subject: "The raw Get-DnsClient output confirms ...", "The discovery scripts included DNS resolution tests", "All 39 sampled hosts ...". State the configuration and the dependency; name the hosts examined in plain words.

## Completion criteria

The section describes the current name-resolution state of the application environment and its supporting AD, states the isolation consequence, lists the dependent services, declares the name-resolution gaps, and passes `prose_lint.py` with no evidence-as-subject, evidence-ID, or connector warnings, with every `term_lint.py` flag resolved. A reader who has not seen the evidence can state, from the section alone, how the application resolves names today and what happens to that when isolated.
