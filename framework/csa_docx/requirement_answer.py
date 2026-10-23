"""One requirement at a time: the model judges the findings and writes a short Text, rating and reason; the framework
writes the Facts of the answer-sheet block from the findings the model marked.

    prompt(view)                 the model's whole input for one requirement (section_card.requirement_view)
    parse_reply(text)            the JSON object in a model reply, or None
    check_reply(view, reply)     [error]: every finding has one verdict, a kept fact is not dropped without a reason,
                                 a Text, a rating from the choices and a reason are present
    block(view, reply)           the answer-sheet block ("## B1 SEP-X-01 ...") for the requirement
    answer(view, ask)            prompt -> reply -> check, with one retry that quotes the errors; {"status", "block",
                                 "errors", "reply"}
    compose_view(card, qid, results)   the input for the Discovery table (observation) or the Drawbridge Impact
                                 (narrative), built from the requirement verdicts; answer() handles it like a requirement
    merge(card, results)         one answer sheet: the blocks in card order, then the F1 block built from the verdicts

    python3 -m csa_docx.requirement_answer prompt|tokens <card.json> [QID]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_QUESTION = re.compile(r"\b(whether|which|what|how|where|who|when|do|does|can|is|are)\b", re.I)
MAX_WORDS = {"requirement": 120, "narrative": 200}      # words of Text per block
_SEE = re.compile(r"see\s+(\S+?)\.?\s*$", re.I)         # a gap that shares another finding's question
VERDICTS = ("supports", "contradicts", "gap", "not relevant")
BASIS = {"declared only": "documented"}          # every other finding basis is a capture: observed

OUTPUT = """## Reply

Reply with one JSON object and nothing else:

{"judgements": [{"finding": "<key>", "verdict": "supports|contradicts|gap|not relevant", "note": ""}],
 "text": "one to three sentences", "rating": "<one of the ratings>", "reason": "one sentence", "unknown": ["one question each"]}

- Give every finding key above exactly one verdict. "supports" and "contradicts" findings become the Facts of the answer.
- A finding cannot be set aside: mark it supports or contradicts, or gap with the question to ask in note. Only a finding marked [fact to keep] may be not relevant, with the reason in note.
- An observed finding is a fact even when its meaning is open (a tool is installed, a share exists, a connection was seen): mark it supports or contradicts and put the open question in note. Use gap only for a finding that states nothing yet. A finding marked [fact to keep] is never a gap.
- Findings about the same peer, zone or share share one question: write it once, in the note of one finding, and write "see <that key>" in the note of the others.
- A question about a listed finding goes in that finding's gap note only: "unknown" holds questions no finding carries. One question per unknown or gap note, each a single sentence that asks one thing (no "and" joining two questions).
- You write only text, rating, reason and unknown. Do not write fact sentences or evidence IDs; the framework adds them.
"""


def prompt(view: dict) -> str:
    return view["markdown"] + ("\n" + OUTPUT if view.get("kind", "requirement") == "requirement" else "")


def parse_reply(text: str) -> dict | None:
    """The first JSON object in ``text`` (a fenced block or bare), or None."""
    text = text or ""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    for cand in ([m.group(1)] if m else []) + [text[i:] for i in [x.start() for x in re.finditer(r"\{", text)][:6]]:
        try:
            obj, _ = json.JSONDecoder().raw_decode(cand)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _judgement_errors(view: dict, reply: dict) -> list[str]:
    errs = []
    keys = {f["key"]: f for f in view["findings"]}
    seen: dict[str, dict] = {}
    bad = set()
    for j in reply.get("judgements") or []:
        if not isinstance(j, dict) or j.get("finding") not in keys:
            errs.append(f"JUDGEMENT_UNKNOWN: {j.get('finding') if isinstance(j, dict) else j!r} is not a finding key above")
        elif j["finding"] in seen or j["finding"] in bad:
            errs.append(f"JUDGEMENT_TWICE: {j['finding']} has two verdicts")
        elif j.get("verdict") not in VERDICTS:
            bad.add(j["finding"])
            errs.append(f"VERDICT_BAD: {j['finding']} verdict must be one of {', '.join(VERDICTS)}")
        else:
            seen[j["finding"]] = j
    errs += [f"NO_VERDICT: {k} has no verdict" for k in keys if k not in seen and k not in bad]
    for k, j in seen.items():
        note = str(j.get("note") or "").strip()
        if j["verdict"] == "not relevant" and keys[k].get("keep") and not note:
            errs.append(f"DROPPED_NO_REASON: {k} carries a fact to keep; say in note why it no longer applies")
        elif j["verdict"] == "not relevant" and not keys[k].get("keep") and view.get("kind", "requirement") == "requirement":
            errs.append(f"NOT_RELEVANT_OWED: {k} is owed by this requirement: mark it supports or contradicts, or gap with a "
                        "question in note (a finding cannot be set aside)")
        elif j["verdict"] == "gap" and keys[k].get("keep"):
            errs.append(f"GAP_ON_KEPT_FACT: {k} is a fact to keep: mark it supports or contradicts and put the open question in note")
        elif j["verdict"] == "gap" and _SEE.match(note) and _SEE.match(note).group(1) in keys and _SEE.match(note).group(1) != k:
            pass
        elif j["verdict"] == "gap" and not _QUESTION.search(note):
            errs.append(f"GAP_NO_QUESTION: {k} is a gap: put the question to ask in note (it becomes an Unknown line); its note was {note!r}")
    return errs


def check_reply(view: dict, reply: dict | None) -> list[str]:
    if not isinstance(reply, dict):
        return ["the reply is not one JSON object"]
    kind = view.get("kind", "requirement")
    keys_ids = {f["key"]: f["ids"] for f in view["findings"]}
    errs = [] if kind == "observation" else _judgement_errors(view, reply)
    if not isinstance(reply.get("unknown", []), list):
        errs.append("UNKNOWN_BAD: unknown must be a list of strings")
    unknown = [u for u in reply.get("unknown") or [] if str(u).strip()]
    if kind == "observation":
        rows = reply.get("rows")
        if not isinstance(rows, list) or (not rows and not unknown):
            return errs + ["NO_ROWS: rows must be a list of rows, or give an unknown"]
        allowed = {i.upper() for i in view["ids"]}
        for r in rows:
            if not isinstance(r, list) or len(r) != len(view["columns"]):
                errs.append(f"ROW_COLUMNS: each row needs exactly {len(view['columns'])} cells ({' | '.join(view['columns'])})")
                continue
            cited = {i.upper() for i in re.findall(r"E-\d+", " ".join(map(str, r)))}
            if not cited or cited - allowed:
                errs.append(f"ROW_EVIDENCE: row '{str(r[0])[:40]}' must cite evidence IDs from the findings above, and only those")
        return errs
    if not str(reply.get("text") or "").strip():
        errs.append("NO_TEXT: text is empty")
    cap = MAX_WORDS.get(kind, 0)
    if cap and len(str(reply.get("text") or "").split()) > cap:
        errs.append(f"TEXT_TOO_LONG: text is {len(str(reply['text']).split())} words; the limit is {cap}. Write the verdict and one "
                    "sentence per part that differs; the findings and unknowns carry the detail")
    if kind == "narrative":
        if not unknown and not any(j.get("verdict") in ("supports", "contradicts") for j in reply.get("judgements") or []
                                   if isinstance(j, dict)):
            errs.append("NO_CONTENT: mark at least one finding supports or contradicts, or give an unknown")
        return errs
    if not any(j.get("verdict") in ("supports", "contradicts") and keys_ids.get(j.get("finding"))
               for j in reply.get("judgements") or [] if isinstance(j, dict)):
        errs.append("NO_FACT: a requirement needs at least one finding with evidence marked supports or contradicts")
    if reply.get("rating") not in view["ratings"]:
        errs.append(f"RATING_BAD: rating must be one of {', '.join(view['ratings'])}")
    if not str(reply.get("reason") or "").strip():
        errs.append("NO_REASON: reason is empty")
    return errs


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


_HINT = re.compile(r"\s*The zone of the far end is not recorded: say so and raise it as Unknown\.")


def _fact_text(text: str) -> str:
    """A finding's text as a fact sentence: no direction label, no instruction to the writer, no semicolons."""
    t = _HINT.sub("", re.sub(r"^\[[^\]]+\]\s*", "", text))
    return re.sub(r";\s*(\w)", lambda m: ". " + m.group(1).upper(), t)


def _facts(view: dict, reply: dict) -> tuple[list[str], list[str]]:
    verdict = {j["finding"]: j for j in reply.get("judgements") or []}
    facts, drops, gaps = [], [], []
    for f in view["findings"]:
        j = verdict.get(f["key"], {})
        note = _one_line(j.get("note") or "")
        if j.get("verdict") in ("supports", "contradicts") and f["ids"]:
            facts.append(f"- {_one_line(_fact_text(f['text']))} ({', '.join(f['ids'])}) {{{BASIS.get(f['basis'], 'observed')}}}")
            if note.endswith("?"):
                gaps.append(f"Unknown: {note}")
        elif j.get("verdict") == "gap" and not _SEE.match(note):
            gaps.append(f"Unknown: {note}")
        elif j.get("verdict") == "not relevant" and f.get("keep") and f["ids"]:
            drops.append(f"Dropped: {', '.join(f['ids'])} {_one_line(j.get('note'))}")
    return facts, drops + gaps


def block(view: dict, reply: dict) -> str:
    """The sheet block. Facts come from the findings marked supports or contradicts, with the finding's own text, ids and
    basis; a finding with no evidence ID cannot be a fact. A kept fact judged not relevant becomes a Dropped: line."""
    kind = view.get("kind", "requirement")
    unknown = [f"Unknown: {_one_line(u)}" for u in reply.get("unknown") or [] if str(u).strip()]
    if kind == "observation":
        cols = view["columns"]
        rows = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
        rows += ["| " + " | ".join(_one_line(c).replace("|", "/") for c in r) + " |" for r in reply.get("rows") or []]
        return "\n".join([f"## {view['qid']} {view['label']}", "Rows:", *rows, *unknown]) + "\n"
    facts, drops = _facts(view, reply)
    head = f"## {view['qid']} {view['req_id'] if kind == 'requirement' else view['label']}"
    lines = [head] + (["Facts:", *facts] if facts else [])
    lines.append(f"Text: {_one_line(reply['text'])}")
    seen: set[str] = set()
    for u in drops + unknown:                      # a gap's question and the same question in "unknown" are one line
        q = re.split(r"(?<=[.?!])\s+", u.strip())[-1].lower()     # a context sentence before the question is not a new one
        if q not in seen:
            seen.add(q)
            lines.append(u)
    if kind == "requirement":
        lines += [f"Rating: {reply['rating']}", f"Rating reason: {_one_line(reply['reason'])}"]
    return "\n".join(lines) + "\n"


def text_errors(card: dict, qid: str, blk: str) -> list[str]:
    """The sheet checks about one block's wording (the Text names the parts it owes, another application's name, a part given a
    machine's role, semicolons), run on the block alone, so the call that wrote it can be asked to fix them."""
    from csa_docx import answer_sheet as A
    sheet = A.parse(blk)
    found = A.subject_checks(sheet, card) + A.part_checks(sheet, card)
    out = [f"{f['code']}: {f['message']}" for f in found if f["level"] == "ERROR" and f.get("question") == qid]
    text = (sheet.get(qid) or {}).get("text") or ""
    if ";" in text:
        out.append("SEMICOLON: the Text has a semicolon: write two sentences, or join the parts with a comma and 'and' or 'but'")
    return out


def answer(view: dict, ask, retries: int = 1, extra=None) -> dict:
    """``ask(prompt) -> reply text``. One retry quotes the errors; after that the block is marked failed. ``extra(block)``
    returns more errors about the written block (see ``text_errors``)."""
    text, errs, reply = prompt(view), [], None
    for attempt in range(retries + 1):
        reply = parse_reply(ask(text))
        errs = check_reply(view, reply)
        if not errs and extra:
            errs = extra(block(view, reply))
        if not errs:
            return {"status": "OK", "block": block(view, reply), "errors": [], "reply": reply, "attempts": attempt + 1}
        text = prompt(view) + "\n## Your last reply was refused\n\n" + "\n".join(f"- {e}" for e in errs) + "\n\nReply again.\n"
    return {"status": "FAILED", "block": "", "errors": errs, "reply": reply, "attempts": retries + 1}


# ---------------------------------------------------------------- the composed blocks and the merge

CROSSING = ("ot_push", "pull_into_ot", "into_ot", "unknown_zone")
MAX_UNUSED = 40


def _marked(results: dict) -> set[tuple]:
    """{(slot, text)} of the findings some requirement block marked supports or contradicts."""
    out = set()
    for r in results.values():
        if r["view"].get("kind", "requirement") != "requirement":
            continue
        v = {j["finding"]: j["verdict"] for j in r["reply"].get("judgements") or []}
        out |= {(f["slot"], f["text"]) for f in r["view"]["findings"] if v.get(f["key"]) in ("supports", "contradicts")}
    return out


def _all_findings(card: dict) -> list[dict]:
    seen, out = set(), []
    for pid, fs in ((card.get("parts") or {}).get("findings") or {}).items():
        for f in fs:
            if (f["slot"], f["text"]) not in seen:
                seen.add((f["slot"], f["text"]))
                out.append(dict(f, part=card["parts"]["parts"].get(pid, pid)))
    return out


def _label(q: dict) -> str:
    return q["text"].split(":")[0].strip()[:60] or q["id"]


def compose_view(card: dict, qid: str, results: dict) -> dict | None:
    """The input for a table or narrative question after the requirement blocks are answered, or None for any other
    question. ``results`` is {requirement qid: {"view", "reply"}}.
    Observation: the findings no requirement block marked, plus the table rows kept from an earlier answer.
    Narrative: the isolation line per part, the declared applications, the three requirement verdicts, and the findings
    that cross the OT boundary (each judged, so the Facts are written from them by the framework)."""
    q = next((x for x in card.get("questions", []) if x["id"] == qid), None)
    if not q or q.get("kind") not in ("observation", "narrative"):
        return None
    pv = card.get("parts") or {}
    marked = _marked(results)
    lines = [f"# {q['kind'].capitalize()} {qid}", "", q["text"], ""]
    if q["kind"] == "observation":
        unused = [f for f in _all_findings(card) if (f["slot"], f["text"]) not in marked][:MAX_UNUSED]
        keep = [k for k in card.get("keep") or [] if str(k.get("question", "")).startswith(qid)]
        ids = [i for f in unused for i in f["ids"]] + [i for k in keep for i in k["evidence_ids"]]
        lines += [f"Columns: {' | '.join(q['columns'])}", "", "## Findings no requirement used", ""]
        lines += [f"- {f['part']} [{f['slot']}, {f['basis']}]: {f['text'][:200]}" + (f" ({', '.join(f['ids'])})" if f["ids"] else "")
                  for f in unused] or ["- none"]
        if keep:
            lines += ["", "## Rows to keep (restate them, or leave them out only if they no longer apply)", ""]
            lines += [f"- {k['fact']} ({', '.join(k['evidence_ids'])})" for k in keep]
        lines += ["", "## Reply", "",
                  'Reply with one JSON object and nothing else: {"rows": [[' + ", ".join(f'"{c}"' for c in q["columns"]) + ']], '
                  '"unknown": []}. One row per aspect, a part per row where the topic touches it; the last cell cites the '
                  "evidence IDs above, and only those. No semicolons, no totals.", ""]
        md = "\n".join(lines)
        return {"qid": qid, "kind": "observation", "label": _label(q), "columns": list(q["columns"]), "findings": [],
                "ids": ids, "markdown": md, "tokens": len(md) // 4}
    cross = []
    for f in _all_findings(card):
        if f.get("direction") in CROSSING and f["ids"] and f["text"] not in {c["text"] for c in cross}:
            cross.append(f)
    findings = [dict(f, key=f"X{n}", keep=[]) for n, f in enumerate(cross[:MAX_UNUSED], 1)]
    from csa_docx.section_card import kept_rows
    findings += kept_rows(card.get("keep") or [], qid, {i.upper() for f in findings for i in f["ids"]})
    lines += ["## When OT is isolated, by part", ""]
    lines += [f"- {pv['parts'][pid]}: {iso['effect'][:300]}" for pid, iso in (pv.get("isolation") or {}).items() if pid in pv.get("parts", {})]
    apps = [a for a in pv.get("applications") or []]
    if apps:
        lines += ["", "## Declared applications", ""] + [f"- {a.get('name', a.get('id'))}: {a.get('purpose', '')[:160]}" for a in apps]
    lines += ["", "## How the requirements were rated (context only: these are not findings and take no verdict)", ""]
    for r in results.values():
        if r["view"].get("kind", "requirement") == "requirement":
            lines.append(f"{r['view']['req_id']} was rated {r['reply'].get('rating')}: {_one_line(r['reply'].get('reason', ''))}")
    lines += ["", "## Findings that cross the OT boundary (give each a verdict)", ""]
    lines += [f"- {f['key']} | {f['part']} [{f['slot']}, {f['basis']}]: {f['text'][:240]} ({', '.join(f['ids'])})" for f in findings] or ["- none"]
    lines += ["", "## Reply", "", 'Reply with one JSON object and nothing else: {"judgements": [{"finding": "<key>", "verdict": '
             '"supports|contradicts|gap|not relevant", "note": ""}], "text": "what each part keeps or loses when OT is isolated, '
             'part by part", "unknown": ["one question each"]}. A part outside OT loses only its paths into OT. Marked findings '
             "become the Facts; a kept fact you set aside needs a reason in note. You write only the text and the unknowns. One question per "
             "unknown, each a single sentence. Name another application (IAMPS) only where it meets a part of this system, and use "
             "no addresses. Judgement keys are only the finding keys listed above. The text is under 200 words, has no semicolons, and calls a part by "
             "the name it is listed under (never a shortened or invented name).", ""]
    md = "\n".join(lines)
    return {"qid": qid, "kind": "narrative", "label": _label(q), "findings": findings, "markdown": md, "tokens": len(md) // 4}


def frame_block(card: dict, results: dict) -> str:
    """The F1 block: for each frame slot, the blocks holding a finding of that slot a requirement marked, else Unknown."""
    slots = (card.get("frame") or {}).get("slots") or []
    if not slots:
        return ""
    by_slot: dict[str, list[str]] = {}
    for qid, r in results.items():
        if r["view"].get("kind", "requirement") != "requirement":
            continue
        v = {j["finding"]: j["verdict"] for j in r["reply"].get("judgements") or []}
        for f in r["view"]["findings"]:
            if v.get(f["key"]) in ("supports", "contradicts") and qid not in by_slot.setdefault(f["slot"], []):
                by_slot[f["slot"]].append(qid)
    out = ["## F1 Analysis frame"]
    for s in slots:
        out.append(f"- {s}: " + (", ".join(by_slot[s]) if by_slot.get(s) else "Unknown: no requirement block marked a finding of this slot"))
    return "\n".join(out) + "\n"


def merge(card: dict, results: dict) -> dict:
    """{"sheet", "missing", "failed"}: the blocks of ``results`` ({qid: {"view", "reply", "block"}}; a failed one has no block)
    in card order, then F1. ``missing`` lists questions of a kind this lane does not answer (note, register, findings, ...):
    the whole-section lane must write those."""
    parts, missing, failed = [], [], []
    for q in card.get("questions", []):
        r = results.get(q["id"])
        if r and r.get("block"):
            parts.append(r["block"])
        elif r:
            failed.append(q["id"])
        elif q.get("kind") != "comment":
            missing.append(q["id"])
    f1 = frame_block(card, {k: v for k, v in results.items() if v.get("block")})
    return {"sheet": "\n".join(parts + ([f1] if f1 else [])), "missing": missing, "failed": failed}


def main(argv: list[str] | None = None) -> int:
    from csa_docx import section_card
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("prompt", "tokens"))
    ap.add_argument("card")
    ap.add_argument("qid", nargs="?")
    a = ap.parse_args(argv)
    card = json.loads(Path(a.card).read_text(encoding="utf-8"))
    if a.cmd == "tokens":
        print(json.dumps(section_card.requirement_tokens(card)))
        return 0
    v = section_card.requirement_view(card, a.qid or "")
    if not v:
        print(f"{a.qid} is not a requirement question of this card", file=sys.stderr)
        return 2
    print(prompt(v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
