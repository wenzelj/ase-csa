## Answer the requirement

The subsection has four parts. Each has its own job; the requirement and its conditions set the topic.

- **Current State cell (the Summary) and Rating.** The system's current state against the requirement, as the system named on the card: what it has in place for the topic, then `The requirement is <Rating> because ...` naming the condition that decides it.
- **Discovery Information story (the Story).** The account of how the system got that rating. Go through the conditions on the card in order and say what the discovery shows for each, as plain observation: no verdict and no rating in the Story, because the Summary carries those. End with what is not known and who could answer it. Hosts and settings appear only as evidence for a condition. Isolation belongs in the Drawbridge Impact.
- **Discovery Information table (a table block).** Discovery data about the topic that the role table does not already show: one row per point. See the table rules.
- **Drawbridge Impact (a narrative block).** How losing the topic during isolation affects the application, function by function. See the narrative rules.

For the Summary, the Story and the Facts:

- Write from the point of view of the system on the card. The first sentence of the Summary and of the Story is about the system, in the terms of the requirement, never about a host or a role group.
- Name machines in the Summary, Story and Text by role and site ("the Rockhampton DNS server"), not by host name or address, which belong in tables and Fact braces unless the question asks for them.
- Write about the system's practice, not about each host. Say what most hosts do and name the exceptions by role. Do not list hosts one by one, and do not describe a host's settings unless that setting decides a condition.
- Every Story paragraph is about the topic the requirement names, and each answers a condition or states what is unknown. A paragraph that only describes hosts, roles or settings belongs in the role table.
- Use the findings that settle a condition; leave out the rest.

## Requirement blocks

- Requirement blocks judge the organisation's practice: whether the tool or process exists (name it, or say none was identified), and rate on that.

## Summary and Story

- Write both `Summary:` and `Story:`. Do not put the SEP label or a title in either: the framework adds a bold title.
- **Summary** is the Current State table cell: say what is in place, then `The requirement is <Rating> because ...` naming the deciding condition. Keep it short and plain: no discovery questions, host inventories or evidence trail.
- **Story** is read under the requirement title in Discovery Information by someone who has not seen the evidence. Tell it as an account a person can follow from start to finish, one `Story:` line per paragraph, in this order:
  1. What is true now, in plain words: the answer to the requirement's question, without the rating.
  2. How it works, from the evidence: for each condition of the requirement, what the discovery shows and whether it settles that condition.
  3. What is not known, and who could answer it (the network owner, the application owner), in words the Summary has not used.
  Use fewer paragraphs when there is less to say, and merge related points instead of adding paragraphs. Each paragraph covers one point and its sentences follow on from one another; never give each sentence its own line.
  - The card may list the findings under "Story paragraph 1", "Story paragraph 2" and so on. Use them to order the paragraphs, but let the requirement decide what each paragraph says: drop a paragraph whose findings settle no condition.
  - The last paragraph also says what the evidence leaves unknown, including the gap that decided the rating (for example, no documented fallback). Add a paragraph for it only if that keeps the Story at 4 or fewer. A `QUESTION:` line, if you write one, stays a separate line.
  - If the card has no such headings, group by point: where the data is held; how it crosses IT and OT or who else uses it; what protects it; what is unknown.
  - Leave out service settings (start mode, helper services) unless they decide the rating.
- Order the Facts the same way as the Story, one observation each, with no conclusion in a Fact ("so ...") and no repeat of another Fact. Every Fact ends `(E-ids) {basis; hosts}`; the braces hold a basis word, never prose.
- The Summary states the answer and the deciding condition once. The Story and the rating reason add detail and do not repeat the Summary's sentences.
- The Summary, the last Story paragraph and the Rating reason are read together, so none of them may repeat another (REASON_REPEATS_SUMMARY, STORY_ENDS_BY_REPEATING). The Rating reason is one short clause that rests on the same ground the Summary names (\"The requirement is ... because ...\") and adds the one fact that settles it, in new words; it is never a different ground from the Summary's (REASON_DIFFERS_FROM_SUMMARY). The last Story paragraph says what is unknown and who could answer it, in new words.
- State an absence as a finding, not as "none was identified": "No host has a proxy configured" (cite the proxy finding the card lists) is a finding; "no proxy was identified" is not. Every "no <thing> was identified" in the Summary, the Story or the Rating reason needs a Fact that names that thing and cites its evidence, or the claim is left out (ABSENCE_WITHOUT_FACT). When the card lists a finding that settles part of the requirement (removable media, whether a host uses a proxy), state it in the Story in plain words with its evidence before the Rating reason relies on it; leaving it out is an error (SETTING_NOT_STATED). When the zone of a connection's far end is not recorded, say which side opens the connection and that the far end's zone is not recorded: do not say the data \"leaves OT\", goes \"outward\" or is \"read out of OT\" (DIRECTION_ASSUMED). Say that the zone is not recorded once in a block, not in every paragraph. In general state each unknown once, in the closing paragraph; mention it earlier only where it changes what a sentence means, and never in the Summary, the Story and the Rating reason alike (REPEATED_UNKNOWN).
- Write plain sentences that carry one observation each. When a sentence starts listing many parts, name the first few and say what the rest have in common.
- Write a long part or role-group name in full once, then a short form or "it". A part's name may be said as often as the Story needs it; any other run of eight words said twice in one Story is rejected.
- No rating and no inference in the Story: state what was seen, with no "so", "which means" or "rather than" joining facts. The Story says things the Summary does not, and says nothing about another requirement's conditions.
- A host that has a name is named by its role, not by its address. A peer shown only by its address is named by that address in the Facts, Summary and Story (peer rule in base). Write "Server Message Block", not "SMB". Do not use the words "captured" or "captures": say what the evidence shows.
- Write it the way a careful colleague would explain it aloud. Open each paragraph with what it is about (a place, a role group, a data flow, a gap), so the paragraphs do not all begin the same way and none begins with "The" just because it is easy. Link the paragraphs: the second picks up where the first stopped. Read the whole Story once as the reader would and rewrite any sentence that sounds like a list or a log entry.
- The card's "Story paragraph N: title" lines tell you what each paragraph is about. They are not text: never write the title, or any label or heading, at the start of a paragraph. Start with a sentence that reads naturally (STORY_LABEL).
- The Story gives the path from the evidence to the answer: how the practice works now, then what the evidence leaves unknown (STORY_NO_EVIDENCE_PATH). Do not open it with the rating or the verdict (STORY_STARTS_WITH_RATING) and do not restate the rating or its reason (STORY_RESTATES_RATING); the Summary carries those.
- The Summary ends with the rating and the deciding condition (SUMMARY_NO_RATING_BASIS), asks no question (QUESTION_IN_SUMMARY), and does not repeat the Story's sentences (SUMMARY_STORY_OVERLAP).
- Do not run a sentence on: when the point changes, start a new sentence (STORY_SENTENCE_LONG). Do not say the same long phrase twice in one Story: the second time use a short form (STORY_PHRASE_REPEAT).
- Paragraphs are separate `Story:` lines about one point each, not one block and not a column of one-sentence lines (STORY_NOT_PARAGRAPHED), and they do not all open with the same word (STORY_SAME_OPENING).
- Never mention a "flow map", a flow ID such as R1 or RB1, or say a connection is "declared" or "absent from" any list. That list is a template in the discovery script, not a design document, and no evidence row supports it. State only what was seen: which host opens a connection to which, on which port, and in which zone.
- Write each paragraph as its own `Story:` line with text: no empty `Story:` line. One point per paragraph. Do not start a sentence with "it" or "they" when the thing they stand for is in an earlier sentence: name it.
- Name a condition by what it says. Never write "condition C1", "C2" or "C3": those labels are the card's, not the reader's.
- Rate on the practice, not on the assessment's own host list (see "Requirement rows"). An unknown condition caps the rating at Partially Met.

## Template rules for a requirement block

- Keep every domain heading. Where a domain does not apply, keep the heading and record "Not Applicable" with its justification.
- Req ID and Requirement are the checklist text: never edit them. Write the evidence-based Current State in the third column, and choose the Rating from Met, Partially Met, Not Met or Not Applicable. Heading numbers are automatic: do not type them.
- Discovery Information: one aspect per row (platform, configuration, dependency), what was observed, and which hosts or classes it covers. Use the note under the table only for a finding that does not fit a row.

## Example (format only)

Invented to show the shape of an answer. Its hosts, facts and evidence IDs (E-0nnn) describe no real system. Never copy a line from it: the answer check rejects one (EXAMPLE_COPIED).

{{example}}
