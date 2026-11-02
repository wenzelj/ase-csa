"""Story readability, one definition for every place a Story is checked (answer sheets and V1 "discovery story"
change records). The rules in words: references/story-rules.md.

    findings(story, part_names=None) -> [(code, message)]
        STORY_SENTENCE_LONG   a sentence over SENTENCE_WORDS words
        STORY_LIST            a sentence naming more than 3 parts (only when part_names is given)
        STORY_PHRASE_REPEAT   the same run of PHRASE_WORDS words twice in one Story
        STORY_NOT_PARAGRAPHED a paragraph of more than MAX_PARAGRAPH_SENTENCES sentences (one `Story:` line per paragraph)
"""
from __future__ import annotations

import re

SENTENCE_WORDS = 40
PHRASE_WORDS = 5
MAX_PARTS = 3
MAX_PARAGRAPH_SENTENCES = 4
_ID = re.compile(r"\b(?:E|L|S\d+-E)-?\d+\b")


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def findings(story: str, part_names: dict | None = None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    story = _ID.sub("", story or "")
    for para in [x for x in re.split(r"\n\s*\n", story) if x.strip()]:
        n = len(_sentences(para))
        if n > MAX_PARAGRAPH_SENTENCES:
            out.append(("STORY_NOT_PARAGRAPHED", f"a Story paragraph of {n} sentences (over {MAX_PARAGRAPH_SENTENCES}): "
                        "split the Story into 2 to 4 short paragraphs, one `Story:` line each (how it works, "
                        f"how it crosses IT and OT or who uses it, what is unknown): \"{para[:60]}...\""))
    for sent in _sentences(story):
        words = len(sent.split())
        if words > SENTENCE_WORDS:
            out.append(("STORY_SENTENCE_LONG", f"a Story sentence of {words} words (over {SENTENCE_WORDS}): one fact per "
                        f"sentence, split it: \"{sent[:70]}...\""))
        if part_names:
            from csa_docx import parts as _parts
            n = len(_parts.parts_in(sent, part_names))
            if n > MAX_PARTS:
                out.append(("STORY_LIST", f"a Story sentence names {n} parts (more than {MAX_PARTS}): split it so each "
                            f"sentence names at most {MAX_PARTS}: \"{sent[:70]}...\""))
    toks = [t.strip(".,;:") for t in re.findall(r"[a-z0-9()/.-]+", story.lower())]
    grams: dict[tuple, list[int]] = {}
    for i in range(len(toks) - PHRASE_WORDS + 1):
        grams.setdefault(tuple(toks[i:i + PHRASE_WORDS]), []).append(i)
    for g, at in grams.items():
        if len(at) >= 2 and at[-1] - at[0] >= PHRASE_WORDS:
            out.append(("STORY_PHRASE_REPEAT", f"the Story says \"{' '.join(g)}\" {len(at)} times: write the full name "
                        "once, then a short form or a pronoun"))
            break
    return out
