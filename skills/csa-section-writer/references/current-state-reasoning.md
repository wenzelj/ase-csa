# Current-State Reasoning

The single source of truth for **how a Current State Assessment thinks about its subject**. Every section skill, the writer, the quality reviewer, and the analysis skills point to this file instead of restating the rules. If a rule here and a rule in a section skill disagree, this file wins for *what the document is about* and the section skill wins for *how that particular section is organised*.

## 1. What a CSA is (and is not)

A Current State Assessment describes **the application, the system it operates in, and the IT/OT environment it currently runs in**: components, architecture, hosting, interfaces, dependencies, identity, network, time, storage, backup, monitoring, security controls, availability, resilience, operational support, and the configuration each of those has today.

It is **not** a report about the evidence. It is not a tour of the discovery data, a catalogue of what a script captured, or a walkthrough of the spreadsheet. Evidence exists to establish and substantiate the current-state view. The reader should never have to reconstruct the system from the evidence; the system should stand on its own and the evidence should hang behind it.

Reasoning runs one way:

```text
Evidence  ->  Correlation  ->  Understanding  ->  Current-State View  ->  CSA Narrative
```

The common failure is stopping one step early and writing the description of the evidence instead of the system:

```text
Evidence  ->  Description of Evidence    (wrong destination)
```

## 2. The subject rule

The subject of a CSA sentence is the **application, the system, a component, a service, or a dependency** -- never the evidence.

- The application *is hosted on*, *runs on*, *depends on*, *resolves names through*, *takes time from*, *backs up to*, *connects to*.
- The evidence *supports*, *shows*, *indicates*, *establishes*, *confirms* -- but only in the change record, the Word comment, or the evidence matrix, where traceability belongs.

| Evidence-centric (avoid in the CSA body) | System-centric (write this) |
| --- | --- |
| The discovery table contains six Windows servers across two locations. | The application is hosted on six Windows servers distributed across the two operational sites. |
| The spreadsheet lists an SCCM client on every host. | Patching is managed through the IT-hosted Configuration Manager service; every host in the capture set runs its client. |
| The network capture shows DNS queries to 10.40.228.97. | Name resolution for the application environment is served by two Active Directory-integrated DNS servers, one at each site. |
| The gpresult output indicates 30 applied GPOs. | Every host receives the corporate computer GPO baseline (29 to 30 policies) from the INTERNAL domain. |
| The raw resolver file confirms two server addresses on Ethernet 3. | The OT-facing NIC on each host carries the only DNS configuration; no interface uses a local or external resolver. |
| The evidence identifies a backup script. | The only identified backup mechanism is a scheduled task that copies the previous day's application logs to an IT-domain file share. |

If a sentence needs "the data", "the capture", "the workbook", "the script output", "the spreadsheet" or "the discovery" as its subject, it is describing the evidence and must be rewritten around the system it tells us about -- or moved to the evidence appendix / change record.

## 3. Three classes of statement -- keep them distinct

Every statement in a CSA is one of three classes. Conflate them and the section becomes either over-assertive or evasive.

1. **Current-state fact.** A statement about the application or system, stated in the strength the evidence supports.
   - *The application servers are domain joined and depend on Active Directory for Windows authentication.*
   - *The TCS modules run as Left/Right host pairs; redundancy is handled by the application, not by Windows Failover Clustering.*
2. **Supporting evidence.** What proves or shows the fact: a configuration record, AD record, DNS record, network flow, firewall rule, diagram, SCCM record, script, scheduled task, interview, document. This lives in the evidence matrix (with its E-id and exact excerpt), the change record's `Why`, and the Word comment -- **not** as the subject of the body prose.
3. **Assessment gap.** Something that cannot yet be established from the available evidence, stated as a gap, not as an absence in the world.
   - *The retention period for the application backup has not been confirmed from the available configuration or operational documentation.*
   - *The patch state of the other hosts in the asset list has not been established.*

The final CSA is primarily **current-state facts and clearly identified gaps**. Evidence is traceable behind them.

### "Not observed" is not "does not exist"

The most important boundary: a negative statement must say what was searched, or that it is unestablished, and must never be written as a bare absence.

| Do not write | Write instead |
| --- | --- |
| No Windows Failover Clustering exists. | No Windows Failover Clustering service was found in the reviewed systems outputs; redundancy is handled by the application. |
| There is no backup. | The only identified backup mechanism is ...; no OT-resident backup target was identified in the sampled evidence. |
| No mapped drives exist. | No mapped drives were recorded where the discovery package included share outputs; the script set was not uniform across all captured hosts, so this is not a full-population absence. |
| Nothing was found on those hosts. | The capture set does not include a services or software inventory for those hosts, so their agent presence is not established. |

**"Not observed in the supplied evidence" does not mean "not implemented."** The scope searched belongs with the gap.

## 4. Evidence correlation

Multiple independent sources that together establish one system view are stronger than any single source, and they should be written as one system statement, not as a list of "source A says X; source B says Y".

Correlation examples:

```text
Server inventory  +  application configuration  +  network flows
+  DNS  +  Active Directory  +  scheduled tasks  +  backup scripts
+  architecture documentation
        =  the current application and system architecture
```

Practical method:

1. **Extract** what each source individually establishes (one atomic claim each, into the matrix).
2. **Correlate**: which claims describe the same component, relationship, dependency, or interface? Group them.
3. **Write** the grouped system statement once, in the section that owns it, in the strength the strongest supporting source allows.
4. **Cite** all contributing E-ids in the change record / Word comment, not in the body.

### When two sources disagree

1. Identify the conflict precisely (which field, which value, which source, which date).
2. Determine whether one source is more authoritative or more current (capture date, source of record, who owns the data).
3. Look for corroborating evidence that settles it.
4. **Never silently choose one.** If it settles, write the settled value and record the conflict in the matrix (`CONFLICTING` row citing both). If it does not settle, write the unestablished point as an assessment gap with the conflict visible, and add it to the gap register / open questions.

## 5. Scope of a statement

A finding is only as wide as the population its evidence covers. Name the population in the sentence.

- "every host captured in May 2026 runs the Configuration Manager client" (correct scope)
- NOT "all 11 sampled hosts" (a stale, unexplained number) and NOT "every host in the environment" (a claim the sample does not support).

Hosts in the asset list, hosts with discovery captures, and the hosts captured in each discovery run (March / April / May, per site) are different groups. A statement drawn from one must not be presented as the other. If a count appears in prose, the reader should be able to answer "count of what, as of when, from which source" without opening the appendix.

## 6. Terminology: IT/OT system language

Terminology has its own shared skill: `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`), with the controlled table in its `references/terminology.md`. It sets how to choose the term from what is being described (not a word list), IT versus OT classification, the most specific term the evidence supports, heading choice, when evidence wording is warranted, and Australian English. This file keeps only the rules about populations and counts, below.

Populations, in plain words: "hosts in the asset list" (the full recorded population), "hosts with discovery captures" (the hosts examined), and each discovery run by date. Do not use "estate".

Expand an abbreviation on first use in a section. One term per thing: pick the name for a component, service, or population and use only that name afterwards.

### Counts name the thing they count -- never conflate an entry with a host

An asset list is recorded as **entries**, and a single entry may name several hosts (e.g. one row listing every host of a host class). The number of entries is therefore not the number of hosts, and a host count is not a list size. State each count with the thing it counts ("108 asset-list entries", "42 unique captured hosts") and never present one as the other.

Lead with the count that **bounds the section's findings** -- usually the hosts with discovery captures (the hosts the findings are drawn from) -- not the size of the asset list. The asset-list count is context that belongs in the asset-inventory section, not in a finding's opening sentence; it does not change what the findings say, so it does not belong in the finding's scope.

## 7. Separating analysis from writing

The pipeline is `Discover -> Extract -> Correlate -> Validate -> Build System View -> Write -> Review`.

- **Discover / Extract:** gather and record the evidence (matrix rows).
- **Correlate:** work out the relationships between components, infrastructure, dependencies, interfaces and operational services.
- **Validate:** check that each intended conclusion is supported at the strength you will state it.
- **Build System View:** form one coherent picture of how the application and its supporting environment currently operate.
- **Write:** only then, turn the system view into prose, in the section that owns each part.

A writer that reaches for a sentence as soon as it has found a fact is writing the evidence, not the system. If a paragraph is a string of "X shows, Y lists, Z contains", it has skipped Correlate and Build System View.

## 8. The reader-value test (completion check)

Before a section is complete, the reviewer asks, in order:

1. **Application/system focus** -- does the section describe the application and its supporting environment, or does it describe the discovery process? If it mainly describes the information collected, rewrite it.
2. **IT/OT language** -- would the terminology sound natural to an experienced IT/OT engineer, application specialist, infrastructure engineer, architect, or operations person?
3. **Evidence support** -- can every material statement be traced to evidence (matrix E-id / change record / Word comment)?
4. **Unsupported assumptions** -- has anything been stated more strongly than the evidence permits, or has an absence been written as a fact?
5. **Technical coherence** -- do the servers, components, interfaces, dependencies, network services, sites and infrastructure relationships hold together as one system?
6. **Cross-section consistency** -- does the section agree with the other sections (same host names, same populations, same dependency picture)?
7. **Unknowns** -- are genuine gaps clearly identified rather than filled with assumptions?
8. **Reader value** -- after reading the section, does a reader unfamiliar with the evidence understand materially better how the application and its supporting system currently operate?

A section that fails any of 1, 4, 6 or 8 is not complete.
