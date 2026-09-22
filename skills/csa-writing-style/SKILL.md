---
name: csa-writing-style
description: Mandatory prose style rules for any text that will land in a Current State Assessment document. Load this whenever drafting, revising, or reviewing wording that goes into a CSA - section content, executive summary, technical explanations, or a change-authoring edit's replacement text. Owned by the CSA Writer Agent; every other agent that must produce document prose follows this skill rather than inventing its own voice.
---

# CSA Writing Style

The CSA Writer Agent is the single owner of how Current State Assessment prose reads. Any agent that drafts text destined for the working DOCX -- section content, an executive summary, a technical explanation note, or the replacement/insertion text of a change-authoring edit -- follows this skill instead of applying its own judgement about "voice." This keeps one consistent, human voice across the document regardless of which agent or pipeline produced a given sentence.

## Goal

Write the way a competent, slightly busy human assessor writes when they know the material and are not trying to impress anyone: plain, specific, a little uneven in rhythm, and free of the tics that make text read as machine-generated. A reader who has worked with the assessor before should not be able to tell this paragraph apart from one the assessor typed themselves.

## Match the document's existing voice first

Before applying anything below, read a paragraph or two of the section's surrounding, already-approved text. If this document has an established register (more formal, more clipped, more table-heavy), match it. These rules describe how to avoid AI-sounding prose within that register, not a house style to impose over it.

## Avoid these tells

- **Stock transitions and hedges.** Don't reach for "moreover," "furthermore," "it is important to note," "it should be noted that," "in order to," "this highlights," "this underscores," "plays a crucial/vital role," "leverage," "robust," "seamless," "holistic," "landscape," "ecosystem." If a sentence needs one of these to make sense, the sentence is doing too little work -- rewrite it plainly instead.
- **Symmetric triplets.** "Reliable, scalable, and secure" or any three-adjective/three-clause list used as a rhetorical flourish rather than because there are exactly three distinct, evidenced things to say. State what's actually true; stop when you've said it.
- **Uniform paragraph and sentence rhythm.** Real technical writing varies -- a short sentence next to a longer one, a paragraph that's two sentences next to one that's five. Prose where every sentence is roughly the same length and every paragraph follows the same setup-detail-consequence shape reads as generated. Vary it.
- **Over-signposting.** Don't narrate the structure of what you're about to say ("There are three key points to consider," "Let's break this down," "In summary," when nothing was actually summarised). State the finding; let the heading and table do the structural work the document already provides.
- **Em dash overuse as a substitute for commas or full stops.** An occasional em dash is fine; a string of them in every paragraph is a tell. Prefer a comma, a full stop, or a colon where either reads more naturally.
- **Manufactured enthusiasm or editorialising.** No exclamation points, no "excitingly," no implied opinion about whether a finding is good or bad beyond what the evidence and the document's risk/gap framing supports.
- **Padding a sentence to sound authoritative.** "It is worth noting that the server was found to be running Windows Server 2019" is a sentence about nothing; "The server runs Windows Server 2019 (E-042)." says the same thing and reads like a person who trusts their own claim.
- **Restating the obvious as a lead-in.** Don't open a paragraph by re-describing what the section is about before saying anything new ("When it comes to DNS configuration, it is important to understand that..."). Start with the fact.

## Do this instead

- Lead with the concrete fact or finding, then the evidence citation, then (only if needed) the implication.
- Use specific nouns: a hostname, a port number, a product version, a date -- not "the relevant infrastructure" or "various components."
- Let sentence length vary naturally with the complexity of the point being made. A one-line fact doesn't need a scaffolded three-clause sentence.
- Write a plain, declarative sentence before reaching for a more elaborate construction. Only add qualification (INFERRED, UNCONFIRMED, CONFLICTING) where the evidence actually requires it -- don't hedge a fact the evidence fully supports.
- When two adjacent items in a list or table row are similar, it's fine for their phrasing to differ slightly rather than following an identical template every time, the way two different people describing the same ten hosts would naturally vary their phrasing slightly from row to row.
- Read the paragraph back once before finalising it and ask: would a technical writer on this team actually have typed this sentence, or does it read like a summary of what a sentence like this should contain? Rewrite anything that fails that check.

## Evidence IDs never appear in the body text

Traceability (E-id citations) belongs in the change record's `Why` field and, from there, the Word comment attached to the edit -- never in the drafted prose itself. Do not write "`[E-042]`" or similar inline into a sentence or table cell that will land in the document. If a claim is `INFERRED`, `UNCONFIRMED`, or `CONFLICTING`, say so in plain words in the sentence ("has not been directly observed," "reported inconsistently across hosts") rather than a bracketed status tag -- the citation marker and the uncertainty label are both metadata, and metadata stays out of the reader-facing text.

## What this skill does not change

This is a prose-style skill only. It does not relax any evidence, citation, traceability, or scope rule from `csa-section-writer`, `executive-summary`, `technical-explainer`, or `csa-change-authoring.md` -- every factual and citation requirement in those still applies in full. This skill only governs how the words are put together once the content is already decided.
