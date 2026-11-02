# Story rules

One definition. Code: `framework/csa_docx/story_shape.py` (answer sheets, and V1 `<SEP-ID> discovery story` records in
`csa check-change`); the rating checks are in `answer_sheet.py`. Agents and digests point here
and do not copy it.

A Story tells how the capability works now and ends with what the evidence leaves unknown. The Summary carries the rating.

- Write the Story as 2 to 4 short paragraphs, one `Story:` line each, never one block (STORY_NOT_PARAGRAPHED: a paragraph over 4 sentences). Paragraph 1: how it works now. Paragraph 2: how it crosses IT and OT, or who uses it. Paragraph 3: what the evidence leaves unknown. Each paragraph is written to the document as its own paragraph.
- One fact per sentence, none over 40 words (STORY_SENTENCE_LONG).
- No sentence names more than 3 parts (STORY_LIST).
- A long part or role-group name is written in full once, then a short form or "it" (STORY_PHRASE_REPEAT: the same 5 words twice).
- Every sentence says something the Summary does not (style guidance, not a framework check).
- No rating and no inference in the Story: state what was seen (STORY_RESTATES_RATING, STORY_INFERS, STORY_STATES_RATING).
- Say "captured" or "the captures" at most once. Keep config detail (start modes, service names) out of the opening sentence unless it decides the rating.

Hard to read: "The report service runs as an Automatic service on the database cluster node role group with the cluster
service and the backup writer running, and the replica groups replicate between the two sites."
Easier: "The report service runs on the database cluster nodes. The replica groups copy its data between the two sites."
