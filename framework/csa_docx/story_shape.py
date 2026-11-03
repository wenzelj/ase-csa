"""Story readability, one definition for every place a Story is checked (answer sheets and V1 "discovery story"
change records). The Story is meant to read as a short account, so these checks only catch what plainly reads badly,
not a count of words, sentences or parts. The rules in words: prompts/answer/requirement.md.

    findings(story, part_names=None) -> [(code, message)]
        STORY_SENTENCE_LONG   a run-on sentence (over SENTENCE_WORDS words)
        STORY_PHRASE_REPEAT   the same run of PHRASE_WORDS words twice in one Story (a part's name does not count)
        STORY_NOT_PARAGRAPHED one wall of text (over WALL_SENTENCES sentences with no paragraph break), or a Story cut
                              into many one-sentence lines
        STORY_SAME_OPENING    most paragraphs open with the same word
        STORY_LABEL           a paragraph opens with a heading-like label ("Where the data sits.") instead of a sentence
"""
from __future__ import annotations

import re

SENTENCE_WORDS = 60
PHRASE_WORDS = 8
WALL_SENTENCES = 6
FRAGMENT_PARAGRAPHS = 5
_LABEL = re.compile(r"^(?:Where|How|What|Who|Why|When)\b[^.!?:]{0,70}\.\s+\S")
_ID = re.compile(r"\b(?:E|L|S\d+-E)-?\d+\b")


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


_DESCRIBES = r"(?:connections?|backups?|replication|traffic|service|database|logs?)"


def _without_descriptors(sent: str, part_names: dict) -> str:
    """A part name used as an adjective ("SQL Server connections", "SQL Server backups") describes the thing, it does not
    bring that part into the sentence: it is not counted."""
    names = sorted({n for ns in part_names.values() for n in ns if n}, key=len, reverse=True)
    for n in names:
        sent = re.sub(r"(?<!\w)" + re.escape(n) + r"\s+" + _DESCRIBES + r"\b", "", sent, flags=re.I)
    return sent


def findings(story: str, part_names: dict | None = None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    story = _ID.sub("", story or "")
    paras = [x for x in re.split(r"\n\s*\n", story) if x.strip()]
    if len(paras) == 1 and len(_sentences(paras[0])) > WALL_SENTENCES:
        out.append(("STORY_NOT_PARAGRAPHED", "the Story is one block of text: break it into paragraphs, one `Story:` line "
                    "each, each about one point, so it reads as an account"))
    elif len(paras) >= FRAGMENT_PARAGRAPHS and sum(len(_sentences(x)) == 1 for x in paras) > len(paras) / 2:
        out.append(("STORY_NOT_PARAGRAPHED", "the Story is a column of one-sentence lines: join the sentences that make "
                    "the same point into a paragraph so it reads as an account"))
    labelled = [x for x in paras if _LABEL.match(x.strip())]
    if labelled:
        out.append(("STORY_LABEL", f"a Story paragraph opens with a label (\"{labelled[0].split('.')[0]}.\"): the card's paragraph "
                    "titles say what each paragraph is about, they are not text; begin with a sentence that reads naturally"))
    firsts = [re.sub(r"\W", "", x.split()[0]).lower() for x in paras if x.split()]
    if len(firsts) >= 3:
        word, n = max(((w, firsts.count(w)) for w in set(firsts)), key=lambda t: t[1])
        if n > len(firsts) / 2:
            out.append(("STORY_SAME_OPENING", f"{n} of {len(firsts)} paragraphs begin with \"{word}\": open each one with "
                        "what it is about (a place, a role group, a data flow, a gap) so the Story does not read as a list"))
    for sent in _sentences(story):
        words = len(sent.split())
        if words > SENTENCE_WORDS:
            out.append(("STORY_SENTENCE_LONG", f"a Story sentence that runs on for {words} words: split it where the "
                        f"point changes: \"{sent[:70]}...\""))
    # a part's name is said as often as the story needs it: it is not a repeated phrase. Each occurrence becomes its own
    # break marker so the words around it cannot join into a false repeat.
    low, n = story.lower(), 0
    for name in sorted({x for ns in (part_names or {}).values() for x in ns if x and len(x) > 3}, key=len, reverse=True):
        def _break(_m):
            nonlocal n
            n += 1
            return f" zzbreak{n} "
        low = re.sub(re.escape(name.lower()), _break, low)
    toks = [t.strip(".,;:") for t in re.findall(r"[a-z0-9()/.-]+", low)]
    grams: dict[tuple, list[int]] = {}
    for i in range(len(toks) - PHRASE_WORDS + 1):
        grams.setdefault(tuple(toks[i:i + PHRASE_WORDS]), []).append(i)
    for g, at in grams.items():
        if len(at) >= 2 and at[-1] - at[0] >= PHRASE_WORDS:
            out.append(("STORY_PHRASE_REPEAT", f"the Story says \"{' '.join(g)}\" {len(at)} times: write the full name "
                        "once, then a short form or a pronoun"))
            break
    return out
