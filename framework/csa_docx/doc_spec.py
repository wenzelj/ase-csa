"""The document spec: what each part of a CSA document asks, read from the document itself.

A CSA template states its own requirements. Headings give the topic (Heading 1 the section, Heading 2 the
subtopic, Heading 3 a facet), table headers give what to record, `[bracketed]` placeholders give the
instruction, the Rating dropdown gives the allowed ratings, and the template's guidance comments give the
rules. This module reads a .dotx or .docx into a tree of nodes (one per Heading 1 or Heading 2 topic) and
classifies every fillable part by its structure, never by its number:

    requirement   a table whose header holds Req ID, Requirement, Current State and Rating
    observation   the table under a "Discovery Information" heading (or an "Aspect" placeholder table)
    register      a table whose data rows are placeholders: one row per host, account, application, gap ...
    narrative     a [bracketed] placeholder paragraph (the bracket text is the question)
    note          an optional [Optional note: ...] paragraph under a table
    findings      [bracketed] bullets, one per finding (with any standard bullets kept beside them)
    reference     real content with no placeholders (keep as is)
    controlled    a table filled from document properties (first column labels, some placeholder values)

Identity: every topic has a key. A topic with a requirement table is keyed by the family of its requirement
IDs (SEP-TIME-01 -> TIME); any other topic by a slug of its heading text. A hidden bookmark `_csa_<KEY>` in
the heading (a stamp) overrides both, so a renamed or moved heading keeps its key. The visible number is
the heading's position in the live document and is only a label.

    python3 -m csa_docx.doc_spec <file.docx|.dotx> [--json] [--node KEY]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
_q = lambda tag: f"{{{W}}}{tag}"  # noqa: E731

STAMP_PREFIX = "_csa_"
GUIDANCE_AUTHORS = ("CSA Template", "CSA Guidance")
SKIP_STYLES = {"Figure", "Caption", "FigureSource", "TOCHeading", "Title", "Subtitle"}
_HEADING = re.compile(r"^Heading\s?([1-9])$")
_REQ_ID = re.compile(r"^SEP-([A-Z]+)-\d+$")
_BRACKET = re.compile(r"^\[.*\]$", re.S)
REQ_HEADERS = ("req id", "requirement", "current state", "rating")
DEFAULT_RATINGS = ["Met", "Partially Met", "Not Met", "Not Applicable"]


# ---------------------------------------------------------------- low-level reading

def _text(el) -> str:
    """All visible text under an element (runs, including inside content controls), deleted text excluded."""
    out = []
    for node in el.iter():
        if node.tag == _q("t"):
            out.append(node.text or "")
        elif node.tag == _q("tab"):
            out.append(" ")
    return " ".join("".join(out).split())


def _style(p) -> str:
    s = p.find("w:pPr/w:pStyle", NS)
    return s.get(_q("val")) if s is not None else "Normal"


def is_placeholder(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and bool(_BRACKET.match(t))


_SLUG_STOP = {"AND", "OF", "THE", "FOR", "A", "AN", "TO"}


def slug_key(text: str, limit: int = 32) -> str:
    """HEADING_WORDS in capitals, small words dropped, cut at a word boundary (a bookmark name holds 40)."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", (text or "").upper()) if w and w not in _SLUG_STOP]
    out = ""
    for w in words:
        nxt = f"{out}_{w}" if out else w
        if len(nxt) > limit:
            break
        out = nxt
    return out or (words[0][:limit] if words else "UNTITLED")


def _numbered_styles(z: zipfile.ZipFile) -> set[str]:
    """Paragraph styles that carry list numbering (directly or through basedOn)."""
    if "word/styles.xml" not in z.namelist():
        return set()
    styles = ET.fromstring(z.read("word/styles.xml"))
    based, numbered = {}, {}
    for s in styles.findall("w:style", NS):
        sid = s.get(_q("styleId"))
        b = s.find("w:basedOn", NS)
        based[sid] = b.get(_q("val")) if b is not None else None
        n = s.find("w:pPr/w:numPr/w:numId", NS)
        numbered[sid] = None if n is None else n.get(_q("val")) != "0"
    out = set()
    for sid in numbered:
        cur, seen = sid, set()
        while cur and cur not in seen:
            seen.add(cur)
            if numbered.get(cur) is not None:
                if numbered[cur]:
                    out.add(sid)
                break
            cur = based.get(cur)
    return out


_LEAD_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+\S")


def _is_numbered(p, style: str, text: str, numbered_styles: set[str]) -> bool:
    """Does Word show a number for this heading? Paragraph numbering wins over the style's; a TOC heading,
    or numbering switched off (numId 0), is unnumbered. Appendix headings count as numbered sections."""
    n = p.find("w:pPr/w:numPr/w:numId", NS)
    if n is not None:
        return n.get(_q("val")) != "0"
    if _LEAD_NUM.match(text) or text.lower().startswith("appendix"):
        return True
    if "toc" in style.lower() or text.strip().lower() in ("table of contents", "contents"):
        return False
    return style in numbered_styles


def _read_parts(path: Path) -> tuple[ET.Element, dict[str, dict]]:
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read("word/document.xml"))
        comments: dict[str, dict] = {}
        if "word/comments.xml" in z.namelist():
            for c in ET.fromstring(z.read("word/comments.xml")).findall("w:comment", NS):
                comments[c.get(_q("id"))] = {"author": c.get(_q("author")) or "", "text": _text(c)}
    return doc.find("w:body", NS), comments


def _blocks(body):
    """Top-level paragraphs and tables in document order; block-level content controls are opened."""
    for el in body:
        if el.tag in (_q("p"), _q("tbl")):
            yield el
        elif el.tag == _q("sdt"):
            content = el.find("w:sdtContent", NS)
            if content is not None:
                yield from _blocks(content)


def _rows(tbl) -> list[list[str]]:
    rows = []
    for tr in tbl.findall("w:tr", NS):
        rows.append([_text(tc) for tc in tr.findall("w:tc", NS)])
    return rows


def _ratings_in(tbl) -> list[str]:
    items = [li.get(_q("displayText")) or li.get(_q("value")) for li in tbl.iter(_q("listItem"))]
    return list(dict.fromkeys(i for i in items if i))


# ---------------------------------------------------------------- classification

def _table_part(rows: list[list[str]], facet: str | None, label: str | None, ratings: list[str]) -> dict:
    header = rows[0] if rows else []
    data = rows[1:]
    low = [h.strip().lower() for h in header]
    part = {"columns": header, "rows": len(data), "facet": facet, "label": label,
            "row_texts": [" | ".join(r) for r in data]}
    if all(h in low for h in REQ_HEADERS):
        i = {h: low.index(h) for h in REQ_HEADERS}
        reqs = []
        for k, r in enumerate(data, start=2):
            get = lambda h: r[i[h]] if i[h] < len(r) else ""  # noqa: E731
            if _REQ_ID.match(get("req id").strip()):
                cs, rt = get("current state"), get("rating")
                reqs.append({"id": get("req id").strip(), "text": get("requirement"), "row": k,
                             "current_state": "" if is_placeholder(cs) else cs,
                             "rating": "" if is_placeholder(rt) else rt})
        part.update(kind="requirement", requirements=reqs, ratings=ratings or DEFAULT_RATINGS)
        return part
    cells = [c for r in data for c in r]
    holders = [c for c in cells if is_placeholder(c)]
    first_col_holder = bool(data) and all(is_placeholder(r[0]) for r in data if r)
    if label and (first_col_holder or not data):
        part["kind"] = "register"                          # a labelled table: one row per host, account, ...
    elif (facet or "").lower() == "discovery information" or (low[:1] == ["aspect"] and first_col_holder):
        part["kind"] = "observation"
    elif first_col_holder:
        part["kind"] = "register"
    elif holders:
        part["kind"] = "controlled"
    else:
        part["kind"] = "reference"
    part["placeholders"] = len(holders)
    part["filled"] = sum(1 for r in data if r and r[0].strip() and not is_placeholder(r[0]))
    return part


def _attach(node: dict, notes: list[dict], facet: str | None) -> None:
    for c in notes:
        key = "guidance" if c["author"] in GUIDANCE_AUTHORS else "comments"
        if not any(x["text"] == c["text"] for x in node[key]):
            node[key].append({"author": c["author"], "text": c["text"], "facet": facet})


def read(path: Path | str) -> dict:
    """Read a .dotx or .docx into the document spec: {'source', 'nodes': [...], 'ratings'}."""
    path = Path(path)
    body, comments = _read_parts(path)
    with zipfile.ZipFile(path) as z:
        numbered_styles = _numbered_styles(z)
    shown: dict[int, int] = {}   # the number Word shows per heading level (H1 counts across lists; appendices follow)
    shown_path: dict[int, str | None] = {}
    nodes: list[dict] = []
    ordinals: dict[int, int] = {}
    h1 = None          # current Heading 1 node
    topic = None       # node that collects parts (H2, or H1 when it has no H2)
    facet = None       # current Heading 3 text
    label = None       # last Label paragraph before a table
    table_ord = 0      # table ordinal under the current heading (matches the stable-ID manifest)
    p_ord = 0          # paragraph ordinal under the current heading (every body paragraph, empty ones too)
    seen_heads: dict[str, int] = {}
    head_text, head_occ = "", 0
    hpath = "0"
    all_ratings: list[str] = []
    pending_bullets: list[dict] = []

    def flush_bullets():
        nonlocal pending_bullets
        if pending_bullets and topic is not None:
            holders = [b["text"] for b in pending_bullets if is_placeholder(b["text"])]
            topic["parts"].append({"kind": "findings" if holders else "bullets", "facet": facet, "label": None,
                                   "bullets": [b["text"] for b in pending_bullets], "placeholders": len(holders),
                                   "pids": [b["pid"] for b in pending_bullets],
                                   "answered": False})
        pending_bullets = []

    for el in _blocks(body):
        if el.tag == _q("tbl"):
            flush_bullets()
            table_ord += 1
            if topic is None:
                continue                                   # cover block
            ratings = _ratings_in(el)
            all_ratings += [r for r in ratings if r not in all_ratings]
            part = _table_part(_rows(el), facet, label, ratings)
            part["table"] = f"@H{hpath}-T{table_ord}"
            part["under"] = {"heading": head_text, "occurrence": head_occ, "table": table_ord}
            topic["parts"].append(part)
            label = None
            continue
        style = _style(el)
        text = _text(el)
        notes = [comments[cs.get(_q('id'))] for cs in el.iter(_q('commentRangeStart')) if cs.get(_q('id')) in comments]
        m = _HEADING.match(style)
        if m:
            flush_bullets()
            level = int(m.group(1))
            ordinals[level] = ordinals.get(level, 0) + 1
            for deeper in [k for k in ordinals if k > level]:
                del ordinals[deeper]
            hpath = ".".join(str(ordinals.get(lv, 0)) for lv in range(1, level + 1))
            table_ord = 0
            p_ord = 0
            label = None
            seen_heads[text] = seen_heads.get(text, 0) + 1
            head_text, head_occ = text, seen_heads[text]
            stamps = [b.get(_q("name")) for b in el.iter(_q("bookmarkStart"))
                      if (b.get(_q("name")) or "").startswith(STAMP_PREFIX)]
            # the visible number: what Word shows, not the heading's position
            lead = _LEAD_NUM.match(text)
            if level == 1:
                for k in [k for k in shown if k > 1]:
                    del shown[k]
                if lead and "." not in lead.group(1):
                    shown[1] = int(lead.group(1))
                    shown_path[1] = lead.group(1)
                elif _is_numbered(el, style, text, numbered_styles):
                    shown[1] = shown.get(1, 0) + 1
                    shown_path[1] = str(shown[1])
                else:
                    shown_path[1] = None
            else:
                parent_shown = shown_path.get(level - 1)
                shown[level] = shown.get(level, 0) + 1
                for k in [k for k in shown if k > level]:
                    del shown[k]
                shown_path[level] = (lead.group(1) if lead and "." in lead.group(1) else
                                     f"{parent_shown}.{shown[level]}" if parent_shown else None)
            visible = shown_path.get(level) or ""
            if level <= 2:
                node = {"title": text, "level": level, "number": visible, "path": hpath, "hid": f"@H{hpath}",
                        "stamp": stamps[0] if stamps else None, "stamps": stamps,
                        "parent": h1["path"] if (level == 2 and h1) else None,
                        "parts": [], "guidance": [], "comments": [], "children": []}
                nodes.append(node)
                if level == 1:
                    h1 = node
                elif h1 is not None:
                    h1["children"].append(hpath)
                topic = node
                facet = None
                _attach(node, notes, None)
            else:
                facet = text
                if topic is not None:
                    _attach(topic, notes, facet)
            continue
        p_ord += 1
        pid = f"@H{hpath}-P{p_ord}"
        if topic is not None:
            _attach(topic, notes, (text.rstrip(':').strip() if style == 'Label' else facet))
        if topic is None or style in SKIP_STYLES or not text:
            continue
        if style == "Label":
            flush_bullets()
            label = text.rstrip(":").strip()
            continue
        if style in ("ListBullet", "ListParagraph"):
            pending_bullets.append({"text": text, "pid": pid})
            continue
        flush_bullets()
        if is_placeholder(text):
            kind = "note" if text.lower().startswith("[optional note") else "narrative"
            topic["parts"].append({"kind": kind, "facet": facet, "label": None, "question": text.strip("[] "),
                                   "answered": False, "pid": pid, "current": text})
        else:
            topic["parts"].append({"kind": "text", "facet": facet, "label": None, "text": text[:300], "pid": pid,
                                   "current": text})
    flush_bullets()

    _assign_keys(nodes)
    for n in nodes:
        n["kind"] = topic_kind(n)
        n["status"] = status_of(n)
    return {"source": str(path), "ratings": all_ratings or DEFAULT_RATINGS, "nodes": nodes}


def families(node: dict) -> list[str]:
    out = []
    for p in node["parts"]:
        for r in p.get("requirements", []):
            f = _REQ_ID.match(r["id"]).group(1)
            if f not in out:
                out.append(f)
    return out


def bare_title(title: str) -> str:
    """The heading text without a typed-in number ("4 Migration Discovery" -> "Migration Discovery")."""
    return _LEAD_NUM.sub(lambda m: m.group(0)[len(m.group(1)):].lstrip(), title or "", count=1).strip() if _LEAD_NUM.match(title or "") else (title or "").strip()


def derived_key(node: dict) -> str:
    fam = families(node)
    return fam[0] if fam else slug_key(bare_title(node["title"]))


def _assign_keys(nodes: list[dict]) -> None:
    seen: dict[str, int] = {}
    for n in nodes:
        if n["stamp"]:
            n["key"] = n["stamp"][len(STAMP_PREFIX):]
            n["key_from"] = "stamp"
        else:
            n["key"] = derived_key(n)
            n["key_from"] = "requirement family" if families(n) else "heading"
    for n in nodes:
        k = n["key"]
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > 1 and n["key_from"] != "stamp":
            n["key"] = f"{k}_{seen[k]}"
            n["key_from"] += " (deduplicated)"


def topic_kind(node: dict) -> str:
    kinds = [p["kind"] for p in node["parts"]]
    for k in ("requirement", "register", "observation", "findings", "narrative"):
        if k in kinds:
            return {"requirement": "requirement-block"}.get(k, k)
    if "bullets" in kinds or "text" in kinds:
        return "reference"
    if "controlled" in kinds:
        return "controlled"
    if kinds:
        return "reference"
    return "container" if node["children"] else "empty"


def status_of(node: dict) -> dict:
    """What is still to answer: placeholder cells, narratives, bullets and unrated requirements."""
    open_items = 0
    total = 0
    for p in node["parts"]:
        if p["kind"] == "requirement":
            for r in p["requirements"]:
                total += 2
                open_items += (not r["current_state"]) + (not r["rating"])
        elif p["kind"] in ("observation", "register"):
            total += 1
            open_items += 0 if p["filled"] else 1
        elif p["kind"] in ("narrative", "findings"):
            total += 1
            open_items += 0 if p.get("answered") else 1
    return {"open": open_items, "total": total,
            "state": "n/a" if total == 0 else "answered" if open_items == 0 else "open" if open_items == total else "partial"}


# Parts built from other parts: they are answered after their inputs. Inputs name node kinds ("requirement-block")
# or keys. A user's document may rename these headings: the stamp keeps the key.
DERIVED = {
    "EXECUTIVE_SUMMARY": {"inputs": ["requirement-block", "DISCOVERY_COVERAGE"], "command": "csa summary"},
    "GOVERNANCE_NOTE_NEXT_STEPS": {"inputs": ["requirement-block"], "command": "csa write {number}"},
    "DISCOVERY_REQUIRED": {"inputs": ["*"], "command": "csa write {number}"},
    "GLOSSARY_ACRONYMS": {"inputs": ["*"], "command": "csa write {number}"},
}


def derive(spec: dict) -> dict:
    """Mark derived nodes with their inputs and whether those inputs are answered (state waiting / ready)."""
    nodes = spec["nodes"]
    for n in nodes:
        d = DERIVED.get(n["key"])
        if not d:
            continue
        inputs = []
        for want in d["inputs"]:
            if want == "*":
                inputs += [m for m in nodes if m is not n and m["key"] not in DERIVED and fillable(m)]
            elif want in ("requirement-block", "register", "narrative", "findings", "observation"):
                inputs += [m for m in nodes if m["kind"] == want]
            else:
                inputs += [m for m in nodes if m["key"] == want]
        open_inputs = [m["key"] for m in inputs if m["status"]["state"] in ("open", "partial")]
        n["derived"] = {"inputs": [m["key"] for m in inputs], "open_inputs": open_inputs,
                        "ready": not open_inputs, "command": d["command"].format(number=n["number"] or n["key"])}
    return spec


def next_nodes(spec: dict) -> list[dict]:
    """Fillable nodes still to answer, in document order; a derived node only once its inputs are answered."""
    derive(spec)
    out = []
    for n in spec["nodes"]:
        if not fillable(n) or n["status"]["state"] not in ("open", "partial"):
            continue
        if n.get("derived") and not n["derived"]["ready"]:
            continue
        out.append(n)
    return out


def fillable(node: dict) -> bool:
    return node["kind"] not in ("reference", "controlled", "container", "empty")


# ---------------------------------------------------------------- lint

def lint(spec: dict) -> list[dict]:
    out = []
    keys: dict[str, list[str]] = {}
    req_seen: dict[str, str] = {}
    for n in spec["nodes"]:
        keys.setdefault(n["key"], []).append(n["number"] or n["hid"])
        if len(n["stamps"]) > 1:
            out.append({"level": "ERROR", "code": "TWO_STAMPS", "node": n["key"], "message": f"{n['number']} {n['title']}: stamps {n['stamps']}"})
        fam = families(n)
        if len(fam) > 1:
            out.append({"level": "WARN", "code": "MIXED_FAMILIES", "node": n["key"], "message": f"{n['number']} {n['title']}: requirement families {fam}"})
        for p in n["parts"]:
            for r in p.get("requirements", []):
                if r["id"] in req_seen:
                    out.append({"level": "ERROR", "code": "REQ_ID_TWICE", "node": n["key"],
                                "message": f"{r['id']} is in {req_seen[r['id']]} and {n['number']}"})
                req_seen[r["id"]] = n["number"] or n["hid"]
            if p["kind"] == "requirement" and not p["requirements"]:
                out.append({"level": "WARN", "code": "EMPTY_REQUIREMENT_TABLE", "node": n["key"], "message": f"{n['number']} {n['title']}: requirement table with no SEP- rows"})
        if n["level"] == 2 and n["kind"] in ("empty",):
            out.append({"level": "WARN", "code": "NO_FILLABLE_CONTENT", "node": n["key"],
                        "message": f"{n['number']} {n['title']}: no table, placeholder or bullet; the framework cannot say what it needs"})
        if n["key_from"] == "heading" and n["level"] == 2 and n["parent"] and any(
                m["kind"] == "requirement-block" for m in spec["nodes"] if m.get("parent") == n["parent"]) and n["kind"] != "requirement-block":
            out.append({"level": "WARN", "code": "NO_REQUIREMENT_TABLE", "node": n["key"],
                        "message": f"{n['number']} {n['title']}: its siblings are requirement blocks but it has no requirement table (Req ID, Requirement, Current State, Rating)"})
    for k, nums in keys.items():
        if len(nums) > 1:
            out.append({"level": "ERROR", "code": "DUPLICATE_KEY", "node": k, "message": f"key {k} used by {', '.join(nums)}"})
    return out


# ---------------------------------------------------------------- join and resolve

def _same_cols(a: list[str], b: list[str]) -> bool:
    norm = lambda xs: [re.sub(r"\s+", " ", x.strip().lower()) for x in xs]  # noqa: E731
    return norm(a) == norm(b)


def _align(node: dict, tparts: list[dict]) -> None:
    """Give a document node the template's part kinds and questions. Placeholders vanish as cells and
    paragraphs are filled, so a filled register looks like a reference table and an answered narrative like
    plain text; the template part in the same place (same columns, or same facet) says what each one is."""
    parts = node["parts"]
    used: set[int] = set()
    for tp in tparts:
        if tp.get("columns"):
            for i, p in enumerate(parts):
                if i not in used and p.get("columns") and _same_cols(p["columns"], tp["columns"]):
                    used.add(i)
                    if p["kind"] != "requirement":
                        p["kind"] = tp["kind"]
                    break
        elif tp["kind"] in ("narrative", "note", "findings"):
            want = ("narrative", "note", "text") if tp["kind"] != "findings" else ("findings", "bullets")
            for i, p in enumerate(parts):
                if i in used or p.get("facet") != tp.get("facet") or p["kind"] not in want:
                    continue
                used.add(i)
                if p["kind"] in ("text", "bullets"):
                    p["kind"] = tp["kind"]
                    p["answered"] = True
                p["question"] = tp.get("question", p.get("question"))
                break
            else:
                if tp["kind"] == "narrative":
                    # the template asks it and the document has nothing in that place: still to answer
                    parts.append(dict(tp, answered=False, missing=True))


def join(doc: dict, template: dict | None) -> dict:
    """Give each document node the template's guidance, part kinds and questions, joined by key."""
    if not template:
        return doc
    tnodes = {n["key"]: n for n in template["nodes"]}
    for n in doc["nodes"]:
        t = tnodes.get(n["key"])
        n["template"] = bool(t)
        if not t:
            continue
        if not n["guidance"]:
            n["guidance"] = t["guidance"]
        _align(n, t["parts"])
        n["kind"] = topic_kind(n)
        n["status"] = status_of(n)
    doc["removed"] = [{"key": k, "title": t["title"]} for k, t in tnodes.items()
                      if k not in {n["key"] for n in doc["nodes"]}]
    doc["added"] = [{"key": n["key"], "number": n["number"], "title": n["title"]} for n in doc["nodes"]
                    if n["key"] not in tnodes]
    return doc


class ResolveError(LookupError):
    pass


def resolve(spec: dict, target: str) -> dict:
    """A node by stamp/key, requirement family, visible number or heading text. Never by a guess."""
    t = (target or "").strip()
    nodes = spec["nodes"]
    low = t.lower().removeprefix(STAMP_PREFIX)
    hits = [n for n in nodes if n["key"].lower() == low]
    if not hits:
        hits = [n for n in nodes if low.upper() in families(n)]
    if not hits and t.startswith("@H"):
        hits = [n for n in nodes if n["hid"] == t.split("-")[0]]
    if not hits and re.fullmatch(r"\d+(\.\d+)*", t):
        num = t if "." in t or not any(n["number"] == t for n in nodes if n["level"] == 2) else t
        hits = [n for n in nodes if n["number"] == num]
        if not hits and t.count(".") >= 2:                    # 3.4.1 -> the topic 3.4
            hits = [n for n in nodes if n["number"] == ".".join(t.split(".")[:2])]
    if not hits:
        norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower().replace("&", " and ")).strip()  # noqa: E731
        hits = [n for n in nodes if norm(bare_title(n["title"])) == norm(t)]
        if not hits:
            hits = [n for n in nodes if norm(t) and norm(t) in norm(bare_title(n["title"]))]
    if len(hits) == 1:
        return hits[0]
    listing = "; ".join(f"{n['number']} {n['title']} ({n['key']})" for n in (hits or nodes) if n["level"] <= 2)
    if not hits:
        raise ResolveError(f"no section matches '{target}'. The document has: {listing}")
    raise ResolveError(f"'{target}' matches more than one section: {listing}")


# ---------------------------------------------------------------- CLI

def _show(n: dict) -> str:
    lines = [f"{n['number']} {n['title']}  [{n['key']}, from {n['key_from']}]  kind: {n['kind']}  "
             f"open {n['status']['open']}/{n['status']['total']}"]
    for p in n["parts"]:
        where = " > ".join(x for x in (p.get("facet"), p.get("label")) if x)
        desc = p["kind"] + (f" ({where})" if where else "")
        if p["kind"] == "requirement":
            desc += ": " + ", ".join(r["id"] for r in p["requirements"])
        elif p.get("columns"):
            desc += ": " + " | ".join(p["columns"])
        elif p.get("question"):
            desc += ": " + p["question"][:90]
        elif p.get("bullets"):
            desc += f": {len(p['bullets'])} bullet(s)"
        lines.append("    " + desc)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--node")
    ap.add_argument("--lint", action="store_true")
    ap.add_argument("--template", type=Path, help="the template the document was made from (joined by key)")
    a = ap.parse_args(argv)
    spec = read(a.path)
    if a.template:
        spec = join(spec, read(a.template))
    if a.lint:
        f = lint(spec)
        print(json.dumps(f, indent=2) if a.json else "\n".join(f"{x['level']:<5} {x['code']:<24} {x['message']}" for x in f) or "no findings")
        return 1 if any(x["level"] == "ERROR" for x in f) else 0
    if a.node:
        n = resolve(spec, a.node)
        print(json.dumps(n, indent=2) if a.json else _show(n))
        return 0
    if a.json:
        print(json.dumps(spec, indent=2))
    else:
        for n in spec["nodes"]:
            print(_show(n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
