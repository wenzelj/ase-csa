# Story rules

One definition. Code: `framework/csa_docx/story_shape.py` (answer sheets, and V1 `<SEP-ID> discovery story` records in
`csa check-change`); the rating checks are in `answer_sheet.py`. Agents and digests point here
and do not copy it.

A Story tells how the capability works now and ends with what the evidence leaves unknown. The Summary carries the rating.

- Write the Story as a short account in paragraphs, one `Story:` line each, never one block of text and never a column of one-sentence lines (STORY_NOT_PARAGRAPHED). Each paragraph covers one point and picks up where the last stopped: how it works now, how it crosses IT and OT or who uses it, then what the evidence leaves unknown. Paragraphs open with what they are about, not all with the same word (STORY_SAME_OPENING).
- Plain sentences that carry one observation each; a run-on is rejected (STORY_SENTENCE_LONG).
- When a sentence starts listing many parts, name the first few and say what the rest have in common (style guidance, not a framework check).
- A long part or role-group name is written in full once, then a short form or "it" (STORY_PHRASE_REPEAT: the same 5 words twice).
- Every sentence says something the Summary does not (style guidance, not a framework check).
- No rating and no inference in the Story: state what was seen (STORY_RESTATES_RATING, STORY_INFERS, STORY_STATES_RATING).
- Say "captured" or "the captures" at most once. Keep config detail (start modes, service names) out of the opening sentence unless it decides the rating.

Hard to read: "The report service runs as an Automatic service on the database cluster node role group with the cluster
service and the backup writer running, and the replica groups replicate between the two sites."
Easier: "The report service runs on the database cluster nodes. The replica groups copy its data between the two sites."
