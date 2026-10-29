"""Block-level work on an answer sheet, so a failed check costs only the blocks that failed.

An answer sheet is a run of blocks (`## B1 ...`, `## C1 ...`, `## F1 Analysis frame`). The framework's checks name
the block each error belongs to, so a sheet that fails is not thrown away:

* ``failing``  the blocks an error names (``*`` when an error belongs to no block: the whole sheet must be redone)
* ``focus``    a smaller card for a fix round: the evidence pack keeps only the blocks being rewritten
* ``merge``    the agent writes only the requested blocks to a patch sheet; the framework copies them into the
               sheet, so a block that already passed can never change in a fix round
* ``wip``      a sheet that has not passed yet is kept as work in progress (``cards/<KEY>.wip.json``: what it was
               built from and which blocks failed), so the next run resumes it instead of starting again

    python3 -m csa_docx.answer_blocks merge <sheet> --patch <patch.md> --only B1,B3 [--json]
    python3 -m csa_docx.answer_blocks focus <card.md> --only B1,B3 --out <focus.md>
    python3 -m csa_docx.answer_blocks wip-check <sheet> --card <card.json> --matrix <csv> [--hosts <csv>]
    python3 -m csa_docx.answer_blocks wip-write <sheet> --card <card.json> --matrix <csv> [--hosts <csv>] --failed B1,B3 --codes X,Y
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_HEAD = re.compile(r"^##\s+([BCF]\d+)\b[^\n]*$", re.M)
_SINGLE_HEAD = re.compile(r"^#(?!#)\s+([BCF]\d+)\b([^\n]*)$", re.M | re.I)
WHOLE = "*"


# ---------------------------------------------------------------- split / merge

def split(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(text before the first block, [(block id, block text including its heading)]), in sheet order."""
    marks = list(_HEAD.finditer(text))
    if not marks:
        return text, []
    head = text[: marks[0].start()]
    blocks = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        blocks.append((m.group(1).upper(), text[m.start(): end].rstrip() + "\n"))
    return head, blocks


def normalize_patch_headings(text: str, only: set[str]) -> tuple[str, list[str]]:
    """Repair a focused model patch that used ``# Bn`` instead of the required ``## Bn``.

    Only requested block IDs are changed. Other Markdown headings and unrequested blocks are left untouched, so this
    tolerance cannot make an unsolicited block eligible for merging.
    """
    only = {x.upper() for x in only}
    normalized = []

    def replace(match: re.Match[str]) -> str:
        bid = match.group(1).upper()
        if bid not in only:
            return match.group(0)
        normalized.append(bid)
        return f"## {bid}{match.group(2)}"

    return _SINGLE_HEAD.sub(replace, text), normalized


def merge_text(base: str, patch: str, only: set[str]) -> dict:
    """Blocks in ``only`` come from the patch, every other block stays as in the base. A requested block the patch
    does not have keeps its base text (reported as missing); a patch block that was not requested is ignored."""
    only = {x.upper() for x in only}
    head, base_blocks = split(base)
    patch, normalized = normalize_patch_headings(patch, only)
    _, patch_blocks = split(patch)
    new = {}
    for bid, body in patch_blocks:
        if bid in only and bid not in new:
            new[bid] = body
    out, merged, seen = [], [], set()
    for bid, body in base_blocks:
        if bid in seen:
            continue
        seen.add(bid)
        if bid in new:
            out.append(new[bid])
            merged.append(bid)
        else:
            out.append(body)
    added = [bid for bid in sorted(new, key=_order) if bid not in seen]      # a block the base lacked
    frame = [b for b in added if b.startswith("F")]
    for bid in [b for b in added if not b.startswith("F")]:
        # before the analysis frame when the base has one: F1 stays last
        fpos = next((i for i, b in enumerate(out) if _HEAD.match(b) and _HEAD.match(b).group(1).upper().startswith("F")), None)
        if fpos is None:
            out.append(new[bid])
        else:
            out.insert(fpos, new[bid])
    for bid in frame:
        out.append(new[bid])
    text = (head.rstrip() + "\n\n" if head.strip() else "") + "\n".join(b.rstrip() + "\n" for b in out)
    return {"text": text, "merged": merged, "added": added,
            "missing": sorted(only - set(new), key=_order),
            "ignored": sorted({b for b, _ in patch_blocks} - only, key=_order),
            "normalized": sorted(set(normalized), key=_order)}


def _order(bid: str) -> tuple[int, int]:
    return ("BCF".index(bid[0]) if bid[:1] in "BCF" else 9, int(re.sub(r"\D", "", bid) or 0))


# ---------------------------------------------------------------- which blocks failed

def failing(findings: list[dict], level: str = "ERROR") -> set[str]:
    """Blocks named by the errors. An error that names no block (other than a missing analysis frame) means the
    sheet as a whole is wrong: ``{"*"}``."""
    out: set[str] = set()
    for f in findings:
        if f.get("level") != level:
            continue
        q = (f.get("question") or "").strip().upper()
        if not q:
            if f.get("code") == "FRAME_UNCOVERED":
                out.add("F1")
            else:
                out.add(WHOLE)
            continue
        out.add(q if re.fullmatch(r"[BCF]\d+", q) else WHOLE)
    return out


# ---------------------------------------------------------------- focused card for a first pass or fix round

_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
_H3 = re.compile(r"^###\s+(.+?)\s*$", re.M)
_BLOCK_ITEM = re.compile(r"^-\s+([BCF]\d+)\b", re.M)


def _sections(text: str, heading: re.Pattern[str]) -> tuple[str, list[tuple[str, str]]]:
    """Split Markdown at one heading level, keeping each heading in its body."""
    marks = list(heading.finditer(text))
    if not marks:
        return text, []
    pre = text[:marks[0].start()]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1).strip(), text[m.start():end].rstrip() + "\n"))
    return pre, out


def _question_items(section: str, only: set[str]) -> str:
    """Keep only the requested top-level ``- Bn`` question items and their indented detail."""
    head, body = section.split("\n", 1) if "\n" in section else (section, "")
    marks = list(_BLOCK_ITEM.finditer(body))
    kept = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        if m.group(1).upper() in only:
            kept.append(body[m.start():end].rstrip())
    return head + "\n\n" + "\n".join(kept).rstrip() + "\n"


def _block_bullets(section: str, only: set[str]) -> str:
    """Filter a section whose top-level bullets start with a block id (Facts to keep/correct)."""
    head, body = section.split("\n", 1) if "\n" in section else (section, "")
    intro_end = next((m.start() for m in _BLOCK_ITEM.finditer(body)), len(body))
    intro = body[:intro_end].rstrip()
    marks = list(_BLOCK_ITEM.finditer(body))
    kept = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        if m.group(1).upper() in only:
            kept.append(body[m.start():end].rstrip())
    return head + "\n" + ((intro + "\n\n") if intro else "\n") + "\n".join(kept).rstrip() + "\n"


def _established(section: str, only: set[str]) -> str:
    """Keep established facts explicitly routed to one of the requested blocks."""
    lines = section.splitlines()
    out = lines[:3]
    for line in lines[3:]:
        routed = {x.upper() for x in re.findall(r"\b[BCF]\d+\b", line.rsplit("; for ", 1)[-1])} \
                 if "; for " in line else set()
        if not routed or routed & only:
            out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _pack_blocks(section: str, wanted: set[str]) -> str:
    """Keep requested evidence packs plus packs they reference as deduplicated dependencies."""
    pre, subs = _sections(section, _H3)
    by_id = {}
    for title, body in subs:
        m = re.match(r"([BCF]\d+)\b", title, re.I)
        if m:
            by_id[m.group(1).upper()] = body
    closure = set(wanted)
    changed = True
    while changed:
        changed = False
        for bid in list(closure):
            for dep in re.findall(r"shown under\s+([BCF]\d+)\s+above", by_id.get(bid, ""), re.I):
                dep = dep.upper()
                if dep in by_id and dep not in closure:
                    closure.add(dep)
                    changed = True
    kept = []
    for bid, body in by_id.items():
        if bid not in closure:
            continue
        # Candidates are discovery-index leads, explicitly unverified and not citable. A compact answer call uses the
        # verified rows and asks for a controlled Search: round when those rows do not answer the question.
        body = "\n".join(line for line in body.splitlines()
                         if not line.startswith("- candidate (unverified, not in the matrix):")) + "\n"
        kept.append(body)
    return pre.rstrip() + "\n\n" + "\n".join(x.rstrip() for x in kept).rstrip() + "\n"


def _host_register(section: str, corpus: str) -> str:
    """Keep captured role groups; retain only named/address peers actually mentioned by this block."""
    lines = section.splitlines()
    out, mode, pending_head, pending = [], "captured", "", []

    def flush() -> None:
        nonlocal pending_head, pending
        if pending:
            out.extend(["", pending_head, *pending])
        pending_head, pending = "", []

    for line in lines:
        if line.startswith("Named in ") and "not captured" in line:
            flush(); mode, pending_head = "named", line
            continue
        if line.startswith("Peers seen only by address"):
            flush(); mode, pending_head = "address", line
            continue
        if mode == "captured":
            out.append(line)
            continue
        if not line.startswith("-"):
            continue
        subject = line[1:].strip().split(":", 1)[0].split(" ", 1)[0]
        if subject and subject.casefold() in corpus.casefold():
            pending.append(line)
    flush()
    return "\n".join(out).rstrip() + "\n"


def _named_subsections(section: str, corpus: str) -> str:
    """Keep named parts referenced by the block, without repeating their analysis-frame findings.

    The full System parts section repeats every S-slot finding under every part. Those findings are already in the
    selected question and analysis/evidence sections. The focused card needs only the accepted name, identity/scope,
    and any explicit parts list needed to connect the routed evidence to that name.
    """
    pre, subs = _sections(section, _H3)
    low = corpus.casefold()
    kept = []
    for title, body in subs:
        names = [title.split(" (also:", 1)[0].strip()]
        aliases = re.search(r"\(also:\s*(.*?)\)\s*$", title, re.I)
        if aliases:
            names += [x.strip() for x in aliases.group(1).split(",")]
        if not any(len(n) >= 4 and n.casefold() in low for n in names):
            continue
        lines = body.splitlines()
        compact = [lines[0]]
        for line in lines[1:]:
            stripped = line.lstrip()
            if stripped.startswith(("- system part", "- dependency part", "- application,", "- one part:", "- parts:")):
                compact.append(line)
        kept.append("\n".join(compact).rstrip() + "\n")
    return pre.rstrip() + "\n\n" + "\n".join(x.rstrip() for x in kept).rstrip() + "\n"


def _examples(text: str, requirement: bool, narrative: bool) -> str:
    """Keep only the example shape needed by the requested block kind."""
    narrative_m = re.search(r"^## Example answer \(narrative\).*?(?=^## Example answer \(requirement\)|\Z)", text, re.M | re.S)
    requirement_m = re.search(r"^## Example answer \(requirement\).*\Z", text, re.M | re.S)
    out = []
    if narrative and narrative_m:
        out.append(narrative_m.group(0).rstrip())
    if requirement and requirement_m:
        req = requirement_m.group(0)
        blocks = list(re.finditer(r"^##\s+B\d+\b", req, re.M))
        if len(blocks) > 1:
            req = req[:blocks[1].start()]
        out.append(req.rstrip())
    return "\n\n".join(out) + ("\n" if out else "")


def focus(card_md: str, only: set[str], first_pass: bool = False) -> str:
    """Build a compact card for the requested blocks.

    The old focus path removed only other Evidence Pack blocks, leaving every question, host, part, analysis slot and
    example in place. This renderer keeps the shared rules but routes block-addressable material to the requested
    question. Evidence-pack references such as ``shown under B1 above`` are closed transitively so compaction never
    removes the rows a selected block is told it may cite.
    """
    only = {x.upper() for x in only}
    example_at = re.search(r"^## Example answer", card_md, re.M)
    main = card_md[:example_at.start()].rstrip() + "\n" if example_at else card_md
    example_text = card_md[example_at.start():] if example_at else ""
    pre, sections = _sections(main, _H2)
    by_name = {title.casefold(): body for title, body in sections}

    if only == {"F1"}:
        keep = [by_name[k] for k in ("scope", "analysis frame (built by the framework from the captures)") if k in by_name]
        text = pre.rstrip() + "\n\n" + "\n\n".join(x.rstrip() for x in keep) + "\n"
    else:
        questions = _question_items(by_name.get("questions", "## Questions\n"), only)
        req_ids = {x.upper() for x in re.findall(r"\bSEP-[A-Z0-9-]+\b", questions, re.I)}
        requirement = bool(req_ids)
        narrative = any(re.search(rf"(?m)^-\s+{re.escape(b)}\b(?!\s+SEP-)", questions, re.I) for b in only)

        routed: dict[str, str] = {"questions": questions}
        for name in ("facts to correct or drop", "facts to keep"):
            if name in by_name:
                routed[name] = _block_bullets(by_name[name], only)
        if "facts already established" in by_name:
            routed["facts already established"] = _established(by_name["facts already established"], only)
        # Requirement-table rows and analysis findings are already copied into each question's Must address/function
        # digest. F1 receives the complete analysis frame through its dedicated minimal path; repeating it in B cards
        # was one of the largest sources of prompt duplication.
        if "evidence pack" in by_name:
            routed["evidence pack"] = _pack_blocks(by_name["evidence pack"], only)

        corpus = "\n".join(routed.values())
        if "host register (captured hosts, grouped by role)" in by_name:
            routed["host register (captured hosts, grouped by role)"] = _host_register(
                by_name["host register (captured hosts, grouped by role)"], corpus)
        if "system parts (built by the framework from the host register and the flows)" in by_name:
            routed["system parts (built by the framework from the host register and the flows)"] = _named_subsections(
                by_name["system parts (built by the framework from the host register and the flows)"], corpus)
        if "applications (reviewed in csa-work/parts.json)" in by_name:
            routed["applications (reviewed in csa-work/parts.json)"] = _named_subsections(
                by_name["applications (reviewed in csa-work/parts.json)"], corpus)

        always = {"requirement summaries and stories", "system name",
                  "rules from the template", "scope", "current text in the document"}
        if narrative:
            always.add("background knowledge (not evidence)")
        ordered = []
        for title, body in sections:
            key = title.casefold()
            if key in routed:
                ordered.append(routed[key])
            elif key in always:
                ordered.append(body)
        text = pre.rstrip() + "\n\n" + "\n\n".join(x.rstrip() for x in ordered if x.strip()) + "\n"
        text += "\n" + _examples(example_text, requirement, narrative)

    if first_pass:
        note = ("> Answer only " + ", ".join(sorted(only, key=_order)) + ": write just that block to SHEET=. This focused "
                "card contains that block's routed evidence and any evidence-pack dependencies; the framework answers and "
                "merges the other blocks separately.\n\n")
    else:
        note = ("> Fix round: rewrite only " + ", ".join(sorted(only, key=_order)) +
                ". This focused card contains only those blocks and their routed evidence; the other blocks already pass.\n\n")
    first = text.find("\n## ")
    return text[: first + 1] + note + text[first + 1:] if first >= 0 else note + text


def focus_metrics(full: str, focused: str) -> dict[str, int | float]:
    """Small, stable measurements for CLI reporting and regression tests."""
    before, after = len(full.encode()), len(focused.encode())
    return {"bytes": after, "words": len(focused.split()), "lines": len(focused.splitlines()),
            "reduction_pct": round((1 - after / before) * 100, 1) if before else 0.0}


# ---------------------------------------------------------------- work in progress

def wip_path(sheet: Path) -> Path:
    sheet = Path(sheet)
    name = sheet.name[: -len(".answer.md")] if sheet.name.endswith(".answer.md") else sheet.stem
    return sheet.with_name(f"{name}.wip.json")


def wip_write(sheet: Path, fp: dict, failed: list[str], codes: list[str]) -> Path:
    from csa_docx import answer_cache
    path = wip_path(sheet)
    data = {"fingerprint": fp, "sheet_sha256": answer_cache._file_sha(Path(sheet)),
            "failed": sorted(set(failed), key=_order), "codes": sorted(set(codes)),
            "written": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def wip_check(sheet: Path, fp: dict) -> dict:
    """RESUME (with "changed": blocks whose evidence changed since the sheet was kept, and "failed"), STALE (the card's
    questions or the host register changed: answer from scratch) or NONE (nothing to resume)."""
    sheet, path = Path(sheet), wip_path(sheet)
    if not sheet.is_file() or not path.is_file():
        return {"status": "NONE", "changed": [], "failed": []}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        old = saved["fingerprint"]
    except (OSError, ValueError, KeyError):
        return {"status": "NONE", "changed": [], "failed": []}
    # A sheet that cites evidence outside the verified matrix is contaminated
    # input, not useful work in progress. A focused repair receives ANSWER= and
    # can preserve or reintroduce those citations; regenerate from the verified
    # card instead.
    if "UNKNOWN_EVIDENCE" in set(saved.get("codes", [])):
        return {"status": "STALE", "changed": [], "failed": [],
                "reason": "the kept sheet cites evidence that is not verified"}
    old_q, new_q = old.get("questions", {}), fp.get("questions", {})
    if set(old_q) != set(new_q):
        return {"status": "STALE", "changed": [], "failed": [], "reason": "the card's questions changed"}
    if old.get("hosts", "") != fp.get("hosts", ""):
        return {"status": "STALE", "changed": [], "failed": [], "reason": "hosts.csv changed"}
    changed = [q for q in new_q if old_q[q] != new_q[q]]
    return {"status": "RESUME", "changed": changed, "failed": saved.get("failed", []), "codes": saved.get("codes", []),
            "written": saved.get("written", "")}


def wip_clear(sheet: Path) -> None:
    wip_path(sheet).unlink(missing_ok=True)


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("sheet", type=Path)
    m.add_argument("--patch", type=Path, required=True)
    m.add_argument("--only", required=True)
    m.add_argument("--json", action="store_true")
    f = sub.add_parser("focus")
    f.add_argument("card", type=Path)
    f.add_argument("--only", required=True)
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--first-pass", action="store_true", help="the first answer of one block, not a fix round")
    for name in ("wip-check", "wip-write", "wip-clear"):
        s = sub.add_parser(name)
        s.add_argument("sheet", type=Path)
        s.add_argument("--card", type=Path)
        s.add_argument("--matrix", type=Path)
        s.add_argument("--hosts", type=Path)
        s.add_argument("--failed", default="")
        s.add_argument("--codes", default="")
    a = ap.parse_args(argv)
    only = {x.strip().upper() for x in getattr(a, "only", "").split(",") if x.strip()}
    if a.cmd == "merge":
        base = a.sheet.read_text(encoding="utf-8") if a.sheet.is_file() else ""
        if not a.patch.is_file():
            print(json.dumps({"status": "NO_PATCH", "merged": [], "missing": sorted(only, key=_order)}))
            return 1
        res = merge_text(base, a.patch.read_text(encoding="utf-8"), only)
        a.sheet.write_text(res.pop("text"), encoding="utf-8")
        print(json.dumps({"status": "OK", **res}))
        return 0
    if a.cmd == "focus":
        full = a.card.read_text(encoding="utf-8")
        focused = focus(full, only, a.first_pass)
        a.out.write_text(focused, encoding="utf-8")
        print(json.dumps({"status": "OK", "out": str(a.out), **focus_metrics(full, focused)}))
        return 0
    if a.cmd == "wip-clear":
        wip_clear(a.sheet)
        print(json.dumps({"status": "OK"}))
        return 0
    from csa_docx import answer_cache
    fp = answer_cache.fingerprint(a.card, a.matrix, a.hosts)
    if a.cmd == "wip-write":
        p = wip_write(a.sheet, fp, [x for x in a.failed.split(",") if x], [x for x in a.codes.split(",") if x])
        print(json.dumps({"status": "OK", "wip": str(p)}))
        return 0
    print(json.dumps(wip_check(a.sheet, fp)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
