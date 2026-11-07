# Shared rules (answer and draft)

## Facts

- Another application's rows (`<project>:E-nnn`, from "Shared enterprise services") are context: only in narrative and note blocks, with that project in the scope (`{observed; utcdtc: 8 hosts}`). Never the only support of a current state or table row (CROSS_PROJECT_ONLY).
- Re-answering: keep every fact listed under the card's "Facts to keep" and every fact that capture evidence supported in the answer you replace, or add `Dropped: E-<n> <why it no longer applies>` to the block (CAPTURE_DROPPED).
Write Facts from this subsection's topic only (Owns / Must explain / Not here on the card); a Fact about another subsection's topic is left out (FACT_OFF_TOPIC).
- Write every fact about the application, host or practice, never about the source: "MOTPRDREV101 hosts the Reveloc application, TGOIP and SMTP", not "The capture's host map lists MOTPRDREV101 as ...". The source shows only in the basis braces. A requirement fact that only restates which hosts the evidence names does not answer the requirement: say whether the practice exists, or write `QUESTION:`.
- Scope names the hosts or sites the cited rows cover. Never widen it beyond them.
- A row answers a question only when it is about the same hosts, the same thing and a capture date that still holds. Rows marked "previous assessment, not checked against the captures" are leads: use them only with a capture row, or as `documented`.
- A connection has one side that opens it. An evidence row says who: "A opened X connections to B" means A opens them and B receives them. Write that direction in the Fact, never the reverse, and never call a connection "into OT" when OT hosts opened it or "outward" when a far end opened it. The Summary, Story, Text and Rating reason only restate what the block's Facts say: name no address, host or kind of connection there that a Fact of the same block does not state (DIRECTION_REVERSED, PROSE_NOT_IN_FACTS).

## Questions

- A `QUESTION:` line is one real question ending in "?", and its answer would supply the missing fact. It names what it asks about ("What data does the peer at 10.129.11.10 read from the TETRA log server?"), never "it" or "those", never "Whether ...". Several open points get several lines so each becomes its own Discovery Required item (UNKNOWN_BUNDLED, QUESTION_BUNDLED).

## Background knowledge

- The card's "Background knowledge (not evidence)" section comes from knowledge documents kept apart from the discovery data. It is NOT evidence and is not in the evidence matrix. Use it to understand what the evidence means. A K- passage may explain an evidenced observation in a narrative block (Drawbridge Impact): give it its own fact citing only its K- ID with basis `background`, next to the E- fact it explains. Never cite a K- ID in a Current State, Rating, table row or bullet. A "Look for" line (system model, second-hand statements) has no ID: state it only from an E- evidence row, otherwise write `QUESTION:`. An "Open question" line is an `QUESTION:`. The framework refuses a sheet that breaks this (BACKGROUND_AS_EVIDENCE, BACKGROUND_MIXED, BACKGROUND_ALONE, BACKGROUND_NOT_ON_CARD).

## Requirements

- Requirement blocks judge the organisation's practice: whether the tool or process exists (name it, or say none was identified), and rate on that.

## Drawbridge Impact

- Drawbridge Impact names the system's functions, what stops, what keeps working and what that means for operations, not only the infrastructure that is lost. Take the functions from the card's "Declared dependencies and flows" rows: a function stops when something it needs is cut, stated only where a row names the need.
- Drawbridge Impact: state each stop plainly and say what it means for operations in the function's own words (from the function map). Where a path's zone is not recorded, say so once in an `QUESTION:` line; do not hedge the Text with "if" or "may" (DRAWBRIDGE_HEDGE, a warning). Leave out a part outside OT whose only paths are its own outward internet paths unless it loses a path into OT.
- A card line "Rows disagree:" means a row says there is none of a kind of traffic while the frame found some: state both, and do not cite that row as showing there are none.

## Names and absence

- When the evidence shows something is absent, say so about the system and name the sources that were checked: "No isolation test record appears in the twelve discovery captures or the supplied documents." Never describe the framework's own search ("the matrix", "the index rows", "rows searched", "for this domain"). The reader has never seen them, and the framework refuses the sheet (PROCESS_AS_SUBJECT).
- When a host has a name, use the name exactly as the sources write it. Never rename or "correct" a host name (for example, RevViewer stays RevViewer).
- Prose names a machine by its role from the Host register (the RevViewer Jump Host, the Radio Management host), not by host name or IP address; names and addresses go in tables, unless the question asks for hosts or addresses, in which case give them. Rules and exceptions: "Host references" in `csa-writing-style`. Use an IP address in prose only for a machine with no name and no known role.
- Tables that capture the system (host, register and connection tables) give both the name and the address, e.g. `MOTPRDREV101 (10.20.1.5)`. Leave the address out when none is known.
- Story rules: `.agents/references/story-rules.md` (read it before writing a Story).
