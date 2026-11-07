"""Does a Fact belong to this subsection? The answer is written from the subsection's topic: a fact about another
subsection's topic (isolation-time administrative access in 3.4 Time Synchronisation, AD and DNS architecture in 3.4)
is left out here and belongs in the subsection that owns it.

A Fact is judged by the scope map (section-scope.md: each subsection's signal terms) and by where the framework filed the
evidence it cites (a row's csa_area is the topic it was recorded for):

    own      the Fact (or a row it cites) carries this subsection's terms, or a cited row was filed for this topic
    other    no own sign, and it carries another subsection's terms, or every cited row was filed for another topic
    unknown  neither: kept (a fact nobody can place is not removed)

3.1 General and 3.12 Isolation & Resilience span topics, so nothing in them is "other"; and no subsection is judged
against them.
"""
from __future__ import annotations

from csa_docx import scope_map

#: subsections that legitimately cover several topics
CROSS_CUTTING = {"3.1", "3.12"}


def _areas() -> dict[str, str]:
    """{csa_area: subsection key} for every topic frame (the area the framework files that topic's rows under)."""
    from csa_docx import topic_frames
    out = {}
    for fr in topic_frames.all_frames():
        for h in fr.get("headings", [])[:1]:
            d = next((d for d in scope_map.load().values() if scope_map.norm(d["title"]) == scope_map.norm(h)
                      or any(scope_map.norm(x) == scope_map.norm(h) for x in d["legacy_headings"])), None)
            if d:
                out[fr.get("area", "")] = d["key"]
    return out


def topic_checks(sheet: dict, card: dict, matrix: dict | None, finding) -> list[dict]:
    """FACT_OFF_TOPIC (a content warning): a Fact in a requirement block that reads as another subsection's topic. The
    answer is written from this subsection's point of view; the Fact is better placed in the subsection that owns it."""
    domains = scope_map.load()
    domain = scope_map.for_section(card.get("number", ""), card.get("title", ""), domains)
    if not domain or domain["key"] in CROSS_CUTTING:
        return []
    areas, matrix = _areas(), matrix or {}
    qs = {q["id"]: q for q in card.get("questions", [])}
    out = []
    for qid, b in sheet.items():
        if qs.get(qid, {}).get("kind") != "requirement":
            continue
        for f in b.get("facts", []):
            if f.get("basis") == "background":
                continue
            rows = [matrix.get(i.upper(), {}) for i in f.get("ids", [])]
            text = f["text"] + " " + " ".join(r.get("claim", "") for r in rows)
            kind, other = classify(text, [r.get("csa_area", "") for r in rows], domain, domains, areas)
            if kind == "other":
                o = domains[other]
                out.append(finding("WARN", "FACT_OFF_TOPIC", qid,
                                   f"this Fact reads as {o['key']} {o['title']}, not {domain['key']} {domain['title']}: the answer is "
                                   f"written from this subsection's topic, so leave it out here unless the requirement needs it "
                                   f"(the other subsection states it): {f['text'][:110]}"))
    return out


def classify(text: str, row_areas: list[str], domain: dict, domains: dict | None = None,
             areas: dict[str, str] | None = None, min_other: int = 2) -> tuple[str, str]:
    """("own" | "other" | "unknown", the subsection key it reads as when other). Another subsection's terms must occur
    ``min_other`` times: one passing word ("authentication", "connections") does not place a fact elsewhere."""
    domains = domains if domains is not None else scope_map.load()
    areas = areas if areas is not None else _areas()
    own_key = domain["key"]
    if own_key in CROSS_CUTTING:
        return "own", own_key
    row_keys = [areas.get(a, "") for a in row_areas if a]
    if scope_map.dependency_matches(text, domain) or own_key in row_keys:
        return "own", own_key
    best, best_n = "", 0
    for k, d in domains.items():
        if k == own_key or k in CROSS_CUTTING:
            continue
        n = scope_map.score(text, d)
        if n > best_n:
            best, best_n = k, n
    known = [k for k in row_keys if k]
    if best_n >= min_other and (not known or best in known or all(k != own_key for k in known)):
        return "other", best
    if known and best_n and all(k != own_key and k not in CROSS_CUTTING for k in known) and len(known) == len(row_areas):
        return "other", known[0]
    return "unknown", ""
