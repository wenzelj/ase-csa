#!/usr/bin/env python3
"""Check that a Current State Assessment .docx still conforms to the CSA Word template.

Standard library only (Python 3.8+). Read-only: it never modifies the document.

It compares the document with the highest-version CSA_Template_v*.dotx (or --template) and reports:
  ERROR   styles the template does not define; typed heading numbers; missing template headings;
          unset/default CSA_* properties; DOCPROPERTY fields whose cached text disagrees with the
          property; tables without a CSA table style; invalid Rating values; edited or missing
          Req ID / Requirement text.
  WARN    unfilled placeholders; template guidance comments left in; pending tracked changes;
          direct run/paragraph formatting; empty paragraphs and manual page breaks; header rows
          that do not repeat; typed cross-references; Track Changes switched on.
With --final every WARN about placeholders, guidance comments and tracked changes becomes an ERROR
(use it for the pre-issue gate).

Output: one JSON object. Exit code 0 = PASS or WARN, 1 = FAIL (errors), 2 = could not run.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
q = lambda t: f"{{{W}}}{t}"
GUIDANCE_AUTHOR = "CSA Template"
RATINGS = {"Met", "Partially Met", "Not Met", "Not Applicable"}
ALLOWED_TABLE_STYLES = {"CSATable", "CSACover"}
DIRECT_RUN_PROPS = {"rFonts", "sz", "szCs", "color", "b", "bCs", "i", "iCs", "u", "highlight", "shd", "caps", "smallCaps"}
DIRECT_PARA_PROPS = {"spacing", "ind", "jc", "pBdr", "shd", "tabs", "keepNext", "keepLines", "pageBreakBefore"}


def local(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def find_template(explicit: str | None, workspace: Path) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        p = p if p.is_absolute() else workspace / p
        return p if p.is_file() else None
    found = sorted(glob.glob(str(workspace / "CSA Template" / "CSA_Template_v*.dotx")),
                   key=lambda s: tuple(int(x) for x in (re.search(r"_v([\d.]+)\.dotx$", s) or [None, "0"])[1].split(".")))
    return Path(found[-1]) if found else None


class Doc:
    """Just enough of a docx to check it."""

    def __init__(self, path: Path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.names = set(z.namelist())
            self.root = ET.fromstring(z.read("word/document.xml"))
            self.styles = ET.fromstring(z.read("word/styles.xml"))
            self.settings = ET.fromstring(z.read("word/settings.xml")) if "word/settings.xml" in self.names else None
            self.comments = ET.fromstring(z.read("word/comments.xml")) if "word/comments.xml" in self.names else None
            self.custom = z.read("docProps/custom.xml").decode("utf-8") if "docProps/custom.xml" in self.names else ""
            self.hf = {n: ET.fromstring(z.read(n)) for n in self.names if re.fullmatch(r"word/(header|footer)\d*\.xml", n)}
        self.body = self.root.find("w:body", NS)
        self.parent = {c: p for p in self.root.iter() for c in p}

    def style_ids(self) -> set[str]:
        return {s.get(q("styleId")) for s in self.styles.findall("w:style", NS)}

    def properties(self) -> dict[str, str]:
        out = {}
        for m in re.finditer(r'<property [^>]*name="([^"]+)"[^>]*><vt:lpwstr>(.*?)</vt:lpwstr>', self.custom, re.S):
            out[m.group(1)] = m.group(2).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        return out

    def in_deleted(self, el) -> bool:
        p = self.parent.get(el)
        while p is not None:
            if p.tag == q("del"):
                return True
            p = self.parent.get(p)
        return False

    def ptext(self, p) -> str:
        return "".join((t.text or "") for t in p.iter(q("t")) if not self.in_deleted(t)).strip()

    def walk(self, container):
        for ch in container:
            tag = local(ch)
            if tag in ("p", "tbl"):
                yield tag, ch
            elif tag == "sdt":
                content = ch.find("w:sdtContent", NS)
                if content is not None:
                    yield from self.walk(content)

    def pstyle(self, p) -> str:
        ps = p.find("w:pPr/w:pStyle", NS)
        return ps.get(q("val")) if ps is not None else "Normal"

    def headings(self):
        """[(level, text, label)] in order; label mirrors Word's automatic numbering."""
        out, c, appendix = [], [0, 0, 0], 0
        for kind, el in self.walk(self.body):
            if kind != "p":
                continue
            m = re.fullmatch(r"Heading([1-3])", self.pstyle(el))
            if not m:
                continue
            lvl = int(m.group(1))
            numid = el.find("w:pPr/w:numPr/w:numId", NS)
            if lvl == 1 and numid is not None and numid.get(q("val")) == "3":
                appendix += 1
                label = f"Appendix {chr(64 + appendix)}"
            else:
                c[lvl - 1] += 1
                for i in range(lvl, 3):
                    c[i] = 0
                label = ".".join(str(x) for x in c[:lvl])
            out.append((lvl, self.ptext(el), label, el))
        return out

    def field_caches(self, root) -> list[tuple[str, str]]:
        """[(DOCPROPERTY name, cached text)] from complex fields."""
        found = []
        for p in root.iter(q("p")):
            state, instr, cached, depth = None, "", "", 0
            for r in p.iter(q("r")):
                for ch in r:
                    t = local(ch)
                    if t == "fldChar":
                        kind = ch.get(q("fldCharType"))
                        if kind == "begin":
                            state, instr, cached = "instr", "", ""
                        elif kind == "separate" and state == "instr":
                            state = "result"
                        elif kind == "end" and state:
                            m = re.search(r'DOCPROPERTY\s+"?([A-Za-z_]+)"?', instr)
                            if m:
                                found.append((m.group(1), cached))
                            state = None
                    elif t == "instrText" and state == "instr":
                        instr += ch.text or ""
                    elif t == "t" and state == "result":
                        cached += ch.text or ""
        return found


def template_facts(tpl: Doc) -> dict:
    tokens, reqs = set(), {}
    for kind, el in tpl.walk(tpl.body):
        if kind == "p":
            for m in re.finditer(r"\[([^\[\]]{2,})\]", tpl.ptext(el)):
                tokens.add(m.group(1))
        else:
            rows = el.findall("w:tr", NS)
            for tr in rows:
                for tc in tr.findall("w:tc", NS):
                    for m in re.finditer(r"\[([^\[\]]{2,})\]", "".join(tpl.ptext(p) for p in tc.iter(q("p")))):
                        tokens.add(m.group(1))
            hdr = [tpl.ptext(tc) for tc in rows[0].findall("w:tc", NS)] if rows else []
            if hdr[:2] == ["Req ID", "Requirement"]:
                for tr in rows[1:]:
                    cells = [tpl.ptext(tc) for tc in tr.findall("w:tc", NS)]
                    reqs[cells[0]] = cells[1]
    return {
        "tokens": tokens,
        "reqs": reqs,
        "headings": [(lvl, text) for lvl, text, _, _ in tpl.headings()],
        "styles": tpl.style_ids(),
        "props": tpl.properties(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docx")
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--template")
    ap.add_argument("--final", action="store_true", help="pre-issue gate: placeholders, guidance comments and tracked changes are errors")
    ap.add_argument("--max-list", type=int, default=25, help="max locations listed per finding")
    args = ap.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    path = Path(args.docx).expanduser()
    if not path.is_file():
        print(json.dumps({"status": "ERROR", "message": f"not found: {path}"})); sys.exit(2)
    tpl_path = find_template(args.template, workspace)
    if tpl_path is None:
        print(json.dumps({"status": "ERROR", "message": "template not found (use --template or --workspace)"})); sys.exit(2)
    try:
        doc, tpl = Doc(path), Doc(tpl_path)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "ERROR", "message": f"cannot open: {exc}"})); sys.exit(2)
    facts = template_facts(tpl)

    findings: list[dict] = []
    def add(level, code, message, where=None):
        findings.append({"level": level, "code": code, "message": message, **({"where": where} if where else {})})
    soft = "ERROR" if args.final else "WARN"

    # ---- styles
    used = {}
    for kind, el in doc.walk(doc.body):
        ps = [el] if kind == "p" else [p for p in el.iter(q("p"))]
        for p in ps:
            used.setdefault(doc.pstyle(p), 0); used[doc.pstyle(p)] += 1
        if kind == "tbl":
            ts = el.find("w:tblPr/w:tblStyle", NS)
            sid = ts.get(q("val")) if ts is not None else None
            if sid not in ALLOWED_TABLE_STYLES:
                add("ERROR", "table-style", f"table uses style {sid!r}; use CSA Table (or CSA Cover Block on the cover)")
            else:
                hdr = el.find("w:tr", NS)
                if sid == "CSATable" and hdr is not None and hdr.find("w:trPr/w:tblHeader", NS) is None:
                    add("WARN", "header-row", "CSA Table without a repeating header row", doc.ptext(hdr)[:60])
    for r in doc.root.iter(q("rStyle")):
        used.setdefault(r.get(q("val")), 0)
    for sid in sorted(used):
        if sid not in facts["styles"] and sid not in ("Normal",):
            add("ERROR", "unknown-style", f"style {sid!r} is not in the template")

    # ---- headings: typed numbers, skeleton
    heads = doc.headings()
    for lvl, text, label, el in heads:
        if re.match(r"^\d+(\.\d+)*\.?\s", text) or re.match(r"^Appendix\s+[A-Z]\b", text):
            add("ERROR", "typed-heading-number", "heading text starts with a typed number; numbering is automatic", f"{label} {text[:50]}")
        if lvl == 3 and not any(h[0] == 2 for h in heads[: [h[3] for h in heads].index(el)]):
            add("WARN", "heading-level", "Heading 3 with no Heading 2 above it", text[:50])
    have = [(lvl, text) for lvl, text, _, _ in heads]
    pos = 0
    for want in facts["headings"]:
        try:
            pos = have.index(want, pos) + 1
        except ValueError:
            add("ERROR", "missing-heading", f"template heading missing or out of order: H{want[0]} {want[1]!r}")
    extra = [h for h in have if h not in facts["headings"]]
    if extra:
        add("INFO", "extra-headings", f"{len(extra)} heading(s) added beyond the template skeleton", "; ".join(f"H{l} {t[:40]}" for l, t in extra[: args.max_list]))

    # ---- properties and cached fields
    props = doc.properties()
    for name, default in facts["props"].items():
        if name not in props:
            add("ERROR", "property-missing", f"custom property {name} missing")
        elif name in ("CSA_SystemName", "CSA_Date") and props[name] == default:
            add("ERROR", "property-default", f"{name} still has the template default {default!r}")
    if "CSA_Date" in props and re.fullmatch(r"\d{2}/\d{2}/\d{4}", props["CSA_Date"]) is None and props["CSA_Date"] != facts["props"].get("CSA_Date"):
        add("WARN", "property-format", "CSA_Date is not dd/mm/yyyy", props["CSA_Date"])
    for part, root in [("word/document.xml", doc.root)] + sorted(doc.hf.items()):
        for name, cached in doc.field_caches(root):
            if name in props and cached != props[name]:
                add("ERROR", "field-stale", f"{part}: DOCPROPERTY {name} shows {cached!r} but the property is {props[name]!r}; refresh fields")

    # ---- requirement tables
    seen_reqs, unfilled_ratings, bad_ratings = set(), 0, []
    for kind, el in doc.walk(doc.body):
        if kind != "tbl":
            continue
        rows = el.findall("w:tr", NS)
        hdr = [doc.ptext(tc) for tc in rows[0].findall("w:tc", NS)] if rows else []
        if hdr[:2] != ["Req ID", "Requirement"]:
            continue
        for tr in rows[1:]:
            tcs = tr.findall("w:tc", NS)
            cells = [doc.ptext(tc) for tc in tcs]
            seen_reqs.add(cells[0])
            if cells[0] in facts["reqs"] and cells[1] != facts["reqs"][cells[0]]:
                add("WARN", "requirement-edited", "Requirement text differs from the template checklist text", cells[0])
            if len(cells) >= 4:
                rating = cells[3]
                sdt_ph = tcs[3].find(".//w:sdt/w:sdtPr/w:showingPlcHdr", NS) is not None
                if sdt_ph or re.fullmatch(r"\[[^\]]*\]", rating) or not rating:
                    unfilled_ratings += 1
                elif rating not in RATINGS:
                    bad_ratings.append(f"{cells[0]}: {rating!r}")
    for rid in sorted(set(facts["reqs"]) - seen_reqs):
        add("ERROR", "requirement-missing", f"template requirement {rid} is missing from the document")
    for b in bad_ratings[: args.max_list]:
        add("ERROR", "rating-invalid", f"Rating must be one of {sorted(RATINGS)}", b)

    # ---- placeholders
    label_now, places = "cover", []
    tokens = facts["tokens"]
    def is_placeholder(p) -> bool:
        t = doc.ptext(p)
        if any(r.find("w:rPr/w:rStyle", NS) is not None and r.find("w:rPr/w:rStyle", NS).get(q("val")) == "PlaceholderText" and not doc.in_deleted(r) for r in p.iter(q("r"))):
            return True
        if re.fullmatch(r"\[[^\[\]]{2,}\]", t):
            return True
        return any(f"[{tok}]" in t for tok in tokens)
    hi = {id(h[3]): h for h in heads}
    for kind, el in doc.walk(doc.body):
        ps = [el] if kind == "p" else list(el.iter(q("p")))
        if kind == "p" and id(el) in hi:
            label_now = f"{hi[id(el)][2]} {hi[id(el)][1][:40]}"
        for p in ps:
            if is_placeholder(p):
                places.append(f"{label_now}: {doc.ptext(p)[:60]}")
    if places:
        by_section: dict[str, int] = {}
        for item in places:
            key = item.split(":", 1)[0]
            by_section[key] = by_section.get(key, 0) + 1
        listing = [f"{k} ({n})" for k, n in by_section.items()]
        add(soft, "placeholders", f"{len(places)} unfilled placeholder(s) in {len(by_section)} section(s)",
            "; ".join(listing[: args.max_list]) + ("; ..." if len(listing) > args.max_list else ""))
    if unfilled_ratings:
        add(soft, "ratings-unset", f"{unfilled_ratings} requirement(s) have no Rating")

    # ---- comments / tracked changes / settings
    if doc.comments is not None:
        guidance = sum(1 for c in doc.comments.findall("w:comment", NS) if c.get(q("author")) == GUIDANCE_AUTHOR)
        others = len(doc.comments.findall("w:comment", NS)) - guidance
        if guidance:
            add(soft, "guidance-comments", f"{guidance} template guidance comment(s) still in the document")
        if others:
            add("INFO", "comments", f"{others} other comment(s) (for example framework edit comments)")
    ins = len(list(doc.root.iter(q("ins")))); dele = len(list(doc.root.iter(q("del"))))
    if ins or dele:
        add(soft if args.final else "INFO", "tracked-changes", f"{ins} tracked insertion(s), {dele} tracked deletion(s) pending")
    if doc.settings is not None and doc.settings.find("w:trackRevisions", NS) is not None:
        add("WARN", "track-revisions-on", "Track Changes is switched on in the document settings")

    # ---- direct formatting, empty paragraphs, page breaks, typed cross-references
    direct_r = direct_p = empty = breaks = xrefs = 0
    samples = []
    for p in doc.body.iter(q("p")):
        if doc.in_deleted(p):
            continue
        for r in p.iter(q("r")):
            rpr = r.find("w:rPr", NS)
            if rpr is not None and any(local(c) in DIRECT_RUN_PROPS for c in rpr) and not doc.in_deleted(r):
                direct_r += 1
                if len(samples) < 5:
                    samples.append(doc.ptext(p)[:40])
            if r.find("w:br[@w:type='page']", NS) is not None:
                breaks += 1
        ppr = p.find("w:pPr", NS)
        st = doc.pstyle(p)
        if ppr is not None and not st.startswith("TOC") and any(local(c) in DIRECT_PARA_PROPS for c in ppr):
            direct_p += 1
        if not doc.ptext(p) and st not in ("TableGap",) and p.find(".//w:drawing", NS) is None and p.find(".//w:fldChar", NS) is None:
            parent = doc.parent.get(p)
            if parent is not None and local(parent) in ("body", "sdtContent"):
                empty += 1
        if re.search(r"\b(?:Section|Appendix)\s+(?:\d+(?:\.\d+)*|[A-Z])\b", doc.ptext(p)) and p.find(".//w:instrText", NS) is None:
            xrefs += 1
    if direct_r:
        add("WARN", "direct-run-formatting", f"{direct_r} run(s) carry direct formatting; apply styles instead", "; ".join(samples))
    if direct_p:
        add("WARN", "direct-paragraph-formatting", f"{direct_p} paragraph(s) carry direct paragraph formatting")
    if empty:
        add("WARN", "empty-paragraphs", f"{empty} empty body paragraph(s); use paragraph spacing, not blank lines")
    if breaks:
        add("WARN", "manual-page-breaks", f"{breaks} manual page break(s); Heading 1 already starts a new page")
    if xrefs:
        add("INFO", "typed-cross-references", f"{xrefs} paragraph(s) mention 'Section N'/'Appendix X' as typed text; prefer a REF cross-reference field where the target may move")

    errors = sum(1 for f in findings if f["level"] == "ERROR")
    warns = sum(1 for f in findings if f["level"] == "WARN")
    status = "FAIL" if errors else ("WARN" if warns else "PASS")
    print(json.dumps({
        "status": status,
        "docx": str(path),
        "template": str(tpl_path),
        "mode": "final" if args.final else "working",
        "counts": {"errors": errors, "warnings": warns, "info": sum(1 for f in findings if f["level"] == "INFO"),
                   "headings": len(heads), "placeholders": len(places), "requirements": len(seen_reqs)},
        "findings": findings,
    }, indent=2, ensure_ascii=False))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
