---
name: csa-writing-style
description: Mandatory prose style rules for any text that will land in a Current State Assessment document. Load this whenever drafting, revising, or reviewing wording that goes into a CSA - section content, executive summary, technical explanations, a change-authoring edit's replacement text, or the Word comment note on a change. Covers voice (human, not AI-sounding) and concision and flow (answer first, each fact once, sentences not bullet fragments, detail in tables). Owned by the CSA Writer Agent; every other agent that must produce document prose follows this skill rather than inventing its own voice.
---

# CSA Writing Style

The CSA Writer Agent is the single owner of how Current State Assessment prose reads. Any agent that drafts text destined for the working DOCX -- section content, an executive summary, a technical explanation note, or the replacement/insertion text of a change-authoring edit -- follows this skill instead of applying its own judgement about "voice." This keeps one consistent, human voice across the document regardless of which agent or pipeline produced a given sentence.

## Goal

Write the way a competent, slightly busy human assessor writes when they know the material and are not trying to impress anyone: plain, specific, a little uneven in rhythm, and free of the tics that make text read as machine-generated. A reader who has worked with the assessor before should not be able to tell this paragraph apart from one the assessor typed themselves.

## Match the document's existing voice first

Before applying anything below, read a paragraph or two of the section's surrounding, already-approved text. If this document has an established register (more formal, more clipped, more table-heavy), match it. These rules describe how to avoid AI-sounding prose within that register, not a house style to impose over it.

Match the register (formality, level of detail), not the structural habits. Spelling and technical terms always follow `australian-it-ot-terminology` (`.agents/skills/australian-it-ot-terminology/SKILL.md`): Australian English and the terminology table, even where the surrounding text uses US spelling or looser terms. If the surrounding text breaks the "Say it once, say it first" rules below (bullet fragments, restated facts, announcing lead-ins), do not copy those habits into new text.

## Tell the story

A reader should be able to read a paragraph aloud to a colleague and have it make sense. Write each paragraph as a short explanation of how this part of the system works, not as a list of what the evidence contains. Follow this order, and leave out any step that has nothing to say:

1. **What it is.** Name the part of the system and its job in a few words ("Three outside systems feed the control system").
2. **How the pieces connect.** Who talks to whom, and who starts the conversation, in plain words. Name components by their role ("the two application servers", "the primary-site pair"), not by host name.
3. **What is notable.** What differs from the design, the requirement, or between sites.
4. **What it means.** The consequence for operations, including if the OT environment is isolated.
5. **What is still unknown.** Once, at the end, in one sentence, with who can confirm it.

### Answer the question first

The reader asked a question of a system: where does its time come from, which resolvers does it use, what fails when they go. Answer it in terms of the systems and applications (the Reveloc application servers, the SQL clusters, the TETRA log server, the jump hosts), not host counts or capture coverage, and name the server or address the answer points to, so the reader knows what to look at. The limits below are guides that `prose_lint.py` reports as warnings. Never leave the question half answered, or drop a fact that answers it, to meet a limit; a longer sentence or one more host name is the smaller fault.

### Identifier budget

- **Name first, address when there is no name.** Refer to a host by its name or role. When the evidence gives only an IP address (no host name in the discovery data, DNS records or host register), use the address in prose: describing the system matters more than hiding the address. Do not give both name and address in prose, and put long lists of addresses in a table.
- **Ports where they matter.** Give a port where it explains how components connect; put full port lists in a table.
- **Name hosts by role**, and give a host name only where the reader needs it to act or to find the host in a table. When a sentence would list many hosts, group them by role and put the list in a table.
- **Readable sentences.** Aim for an average around 25 words and split sentences over about 45 words where that reads better. Never drop a fact to shorten a sentence.
- **One hedge per point.** Put the unknown once, at the end ("Whether the second site is used only on failover is still to be confirmed with the operations team."), not in every sentence.

`prose_lint.py` reports these as advisory notes. They guide the writing; they are not pass/fail rules.

### Example

Before (accurate, but a data dump):

> The historian is the single collection point for all three plant networks. The collector service runs on HIST01 (10.20.4.11) and HIST02 (10.20.4.12) and listens on tcp/5450 and tcp/5451, and PLC gateways GW01-GW06 (10.20.8.0/24) connect to it on tcp/5450 while the reporting server RPT01 (10.40.2.20) connects on tcp/5451 from the IT network, which is the inbound direction the requirement seeks to avoid, and no Kerberos or NTLM was observed on either flow, so the flows are effectively unauthenticated.

After (the same facts, told as a story):

> All three plant networks send their data to one place: the historian pair. The PLC gateways push readings to it from the OT side. The reporting server works the other way round: it reaches in from the IT network to pull data out, which is the inbound direction the requirement aims to avoid. Neither connection uses the Windows domain to prove who is calling; whether the historian checks the caller some other way is still to be confirmed with the vendor.

The addresses, ports and gateway names move to the discovery table. Nothing is lost, and the paragraph now explains the system instead of listing it.

## Say it once, say it first

A Current State Assessment (CSA) gives decision-makers an evidenced baseline: what exists, how it differs from what the design or reference standard expects, and what that means for operations. Its readers are technical and operational people who already know the technologies. They need the facts and their consequence, not a tour of the evidence. These rules apply to every paragraph, bullet and table cell, and they outrank "match the existing voice".

- **The subject is the system, not the evidence.** The subject of a sentence is the application, a component, a service, or a dependency -- never "the discovery data", "the table", "the workbook", "the capture", "the script output". Evidence supports the statement; it does not become its subject. Full rules and before/after examples: `csa-section-writer/references/current-state-reasoning.md`.
- **Answer first.** The first sentence of a section or subsection states its conclusion. Supporting facts follow; raw detail goes in a table or the appendix. Do not build up to the conclusion through a chain of "This confirms... As a result..." steps.
- **Each fact once.** A fact (a host list, a server name, an IP address, a dependency, a consequence) is stated in the one place that owns it. Everywhere else, refer to it ("the two enterprise time servers", or a finding ID) rather than listing it again. When Findings, Assessment, Operational Behaviour and Impact subsections all restate the same dependency, each keeps only what is new to it.
- **State, don't announce.** Delete lead-ins that announce a conclusion instead of stating it: "This confirms that", "This indicates", "This establishes that", "This results in:", "This represents", "As a result:", "The following findings are derived from...", "The analysis focuses on...". Write the conclusion itself as the sentence.
- **Sentences, not fragments.** Write full sentences in paragraphs. Use a bullet list only for three or more parallel items a reader will scan (hosts, services, requirements). Never split one sentence across a lead-in line and bullets ("Loss of:" followed by "- ongoing time synchronisation"). No nested bullets.
- **No textbook material.** Do not explain what DNS, NTP, Kerberos, a firewall or an endpoint agent is, or why such services matter in general. Say what it does in this system and why that matters here. If a reader needs background, it goes in a labelled `Technical explanation` note (`technical-explainer`), not in the finding.
- **Findings, not log lines.** Never paste raw log or command output into the body. State what it shows and give a short source reference (file name and date); the raw lines stay in the evidence.
- **Detail lives in tables and appendices.** Per-host lists, address lists, port lists, capture dates and evidence file names belong in the observed-state or discovery table, or the evidence appendix. Prose carries what the detail means ("all eight captured hosts", "both production sites").
- **State the evidence basis once.** How evidence was gathered, and what it could not see, is stated once in Scope and Methodology. Do not tag headings or sentences with "(Script Evidence)", "(Evidence-Based)" or "(Script Confirmed)". A limitation that affects one finding is stated once, precisely, in that finding ("not confirmed on six of eight hosts, whose captures did not include service inventories").
- **Findings run condition, criteria, consequence.** Each finding is one short paragraph with a headline sentence that could stand alone: what is (condition), what the design or reference standard expects (criteria), and what it means for operations, including under the isolation scenario (consequence). Add the cause only when the evidence shows it. Recommendations sit separately and refer back to the finding.
- **Rank by consequence.** Order findings by operational consequence, not by the order discovery happened.
- **One term per thing.** Define a term once (for example the isolation scenario's name) and use only that term afterwards.
- **Proportion.** Length follows the system: a domain with one finding reads in well under a page, while a large application with many components, interfaces and dependencies needs as much as it takes to describe them. When a draft is longer than its facts justify, cut restatement before cutting facts.

Flow comes from order (conclusion, support, consequence) and from linking sentences by their content, not from connector words. When two points relate, say how in one clause: "Unlike the DNS dependency, loss of time synchronisation degrades gradually."

### Example

Before:

> Host-level discovery confirms that servers synchronise time from:
> - TIMESRV01.corp.example
> - TIMESRV02.corp.example
>
> This establishes that the system is:
> - Fully dependent on externally provided time synchronisation services
> - Operating without any local or fallback time source
>
> Time synchronisation is a foundational service that supports:
> - Authentication (Kerberos time dependency)
> - Event sequencing across systems
>
> As a result, accurate and consistent time is required for both:
> - System operation
> - Cross-system integrity

After:

> All captured hosts take time from two enterprise servers, TIMESRV01 and TIMESRV02, through the Windows Time client, with no local or fallback source. If the OT environment is isolated, the hosts keep running on their last synchronised time and drift apart. Once the skew passes the Kerberos tolerance, authentication fails; before that, log timestamps and message ordering lose accuracy. Unlike the DNS and directory dependencies, this failure is gradual rather than immediate.

The rewrite keeps every fact, adds the consequence the original only implied, and drops the general explanation of why time matters.

- **Evidence as subject.** "The discovery table shows...", "The capture contains...", "The spreadsheet lists...", "The evidence identifies...", "The raw output confirms...". These describe the collection, not the system. Rewrite around the system the evidence tells us about: "The application is hosted on...", "Patching is managed through...", "Name resolution is served by...". A sentence whose subject is the data is a change-record sentence, not a CSA sentence.

## Avoid these tells

- **Stock transitions and hedges.** Don't reach for "moreover," "furthermore," "it is important to note," "it should be noted that," "in order to," "this highlights," "this underscores," "plays a crucial/vital role," "leverage," "robust," "seamless," "holistic," "landscape," "ecosystem." If a sentence needs one of these to make sense, the sentence is doing too little work -- rewrite it plainly instead.
- **Symmetric triplets.** "Reliable, scalable, and secure" or any three-adjective/three-clause list used as a rhetorical flourish rather than because there are exactly three distinct, evidenced things to say. State what's actually true; stop when you've said it.
- **Uniform paragraph and sentence rhythm.** Real technical writing varies -- a short sentence next to a longer one, a paragraph that's two sentences next to one that's five. Prose where every sentence is roughly the same length and every paragraph follows the same setup-detail-consequence shape reads as generated. Vary it.
- **Over-signposting.** Don't narrate the structure of what you're about to say ("There are three key points to consider," "Let's break this down," "In summary," when nothing was actually summarised). State the finding; let the heading and table do the structural work the document already provides.
- **Em dash overuse as a substitute for commas or full stops.** An occasional em dash is fine; a string of them in every paragraph is a tell. Prefer a comma, a full stop, or a colon where either reads more naturally.
- **Manufactured enthusiasm or editorialising.** No exclamation points, no "excitingly," no implied opinion about whether a finding is good or bad beyond what the evidence and the document's risk/gap framing supports.
- **Padding a sentence to sound authoritative.** "It is worth noting that the server was found to be running Windows Server 2019" is a sentence about nothing; "The server runs Windows Server 2019." says the same thing and reads like a person who trusts their own claim.
- **Restating the obvious as a lead-in.** Don't open a paragraph by re-describing what the section is about before saying anything new ("When it comes to DNS configuration, it is important to understand that..."). Start with the fact.

## Do this instead

- Lead with the concrete fact or finding, then (only if needed) the implication. The evidence citation belongs in the change record, not the sentence (see below).
- Use specific nouns: a hostname, a port number, a product version, a date -- not "the relevant infrastructure" or "various components."
- Let sentence length vary naturally with the complexity of the point being made. A one-line fact doesn't need a scaffolded three-clause sentence.
- Write a plain, declarative sentence before reaching for a more elaborate construction. Only add qualification (INFERRED, UNCONFIRMED, CONFLICTING) where the evidence actually requires it -- don't hedge a fact the evidence fully supports.
- When two adjacent items in a list or table row are similar, it's fine for their phrasing to differ slightly rather than following an identical template every time, the way two different people describing the same ten hosts would naturally vary their phrasing slightly from row to row.
- Read the paragraph back once before finalising it and ask: would a technical writer on this team actually have typed this sentence, or does it read like a summary of what a sentence like this should contain? Rewrite anything that fails that check.

## Never infer

See "Never infer" in .agents/csa-core-rules.md.

## Evidence IDs never appear in the body text

See "Evidence IDs never in document text" in .agents/csa-core-rules.md.

## Comment notes (the Word comment on each change)

Every applied change carries a Word comment. The document owner, reviewers and approvers read it while deciding whether to accept the change, usually without the change file open. It is written from the change record's `**Note:**` field, which the authoring agent writes to these rules:

- **One or two sentences, 40 words at most; aim for about 25.** Say what changed and why, so a reader who knows the system but not the evidence can accept or reject the change.
- **Say what the evidence showed, in plain words**, not where it is: "the hosts run the Windows Time service" rather than "32_services_inventory.txt shows W32Time Running".
- **Lead with the change**, in the past tense: Corrected, Removed, Added, Moved, Replaced, Clarified.
- **Leave out** evidence file names, host lists, IP addresses, paragraph numbers, stable IDs (`@H...`), status tags (`VERIFIED`), change IDs and framework terms (anchor, record, block, range). The framework appends the change ID and evidence IDs in brackets itself.
- Do not write "No open questions", initials or sign-offs. Word already shows the author.

| Instead of | Write |
| --- | --- |
| S9-E3: The Findings sentence "No evidence of local NTP services…" is contradicted by E-082 (VERIFIED): 32_services_inventory.txt shows W32Time State=Running on APPSRV01/02 and 20_listening_ports.txt shows UDP 0.0.0.0:123 on all 8 captures… Initials: WJ | Corrected: the servers do run the Windows Time service, but they still take their time from the IT domain, so there is no independent local time source. |
| Stray duplicated H2 "Security Controls" block contains refuted claims (para 2148: …) | Removed an older copy of the Security Controls section that had been left inside Time Synchronization. It said no security tools were found, which the evidence disproves. |
| Editorial -- each fact once; sentences not fragments. The removed bullets restated… | Wording tightened: five bullets joined into one sentence. No facts changed. |

The resulting comment reads: `Corrected: the servers do run … no independent local time source. (Ref S9-E3; evidence E-082)`. Preview every comment in a change file with `python3 -m csa_docx.comment_text <change file>` (run from `.agents/framework`); it flags a missing Note, a Note over 40 words and a file name.

## Check before returning

Run the terminology lint as well as the prose lint, and resolve every flag by deciding what the passage describes: `python3 .agents/skills/australian-it-ot-terminology/scripts/term_lint.py <draft.md | working.docx> [--heading "<title>"]`.

Run the prose lint on the draft (Markdown) or, for review, on the working DOCX section:

```text
python3 .agents/skills/csa-writing-style/scripts/prose_lint.py <draft.md | working.docx> [--section N]
```

It measures the rules above: bullet share, nested bullets, fragments and lead-ins, announcing connectors, identifiers repeated in prose, repeated sentences, evidence IDs or file names in prose, and heading label noise. New or rewritten text should produce no connector, nested-bullet, evidence-ID or heading-noise warnings, and no identifier stated in more than three prose paragraphs of one section. The lint is a guide, not a substitute for reading the paragraph back.

## What this skill does not change

This is a prose-style skill only. It does not relax any evidence, citation, traceability, or scope rule from `csa-section-writer`, `executive-summary`, `technical-explainer`, or `csa-change-authoring.md` -- every factual and citation requirement in those still applies in full. This skill only governs how the words are put together once the content is already decided.
