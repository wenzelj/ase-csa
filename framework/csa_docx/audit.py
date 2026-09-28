"""Document audit, scripted stage: what a CSA document is missing, measured without judgement.

Read-only against the working DOCX. Writes WORK_DIR/audit/<audit-id>/audit.json and mechanical.md,
which the audit agent (`csa audit-section`) and the report builder (`csa audit --report`) read.

Checks:
  document     package validation, tracked changes left, open Word comments
  structure    heading numbers that do not match their level or parent, duplicates, headings ending ':'
  requirements every SEP requirement row: present, Current State filled, rating valid
  domains      each requirement domain has Discovery and Drawbridge Impact subsections
  placeholders [..], TBC/TBD, XX, empty table rows
  unknowns     'not confirmed / could not / not established ...' statements by section
  appendix_d   Discovery-required rows and their status; gap-register verdicts when present
  lints        prose_lint, term_lint and section_fit_scan results
  evidence     evidence-matrix totals; captured hosts never named in the document
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "skills"
RATINGS = {"met", "partially met", "not met", "not applicable", "partial", "gap", "n/a"}
REQ_RE = re.compile(r"^(SEP-[A-Z]+-\d+)\b")
NUM_RE = re.compile(r"^((?:\d+|[A-Z])(?:\.\d+)*)\s")
UNKNOWN_RE = re.compile(
    r"\b(not confirmed|unconfirmed|to be confirmed|TBC|TBD|unknown|could not|couldn't|cannot confirm|can't confirm|"
    r"not (?:been )?(?:verified|validated|established|observed|available|documented|recorded)|we haven't seen|"
    r"no evidence|sufficient evidence was not available|not assessed)\b", re.I)
PLACEHOLDER_RE = re.compile(r"\[[^\]]{1,60}\]|\bTBC\b|\bTBD\b|\bXX+\b|<insert[^>]*>|lorem ipsum", re.I)
HOST_RE = re.compile(r"^[A-Z0-9-]{4,}$")


def _t(xml: str) -> str:
    xml = re.sub(r"<w:delText[^>]*>.*?</w:delText>", "", xml, flags=re.S)
    xml = re.sub(r"<w:tab/>", " ", xml)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", xml))).strip()


def read_units(docx: Path) -> list[dict]:
    """Body in order: headings, paragraphs and table rows, each with its heading path."""
    x = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
    body = x[x.find("<w:body"):]
    units, path = [], []
    for tok in re.finditer(r"<w:tbl>.*?</w:tbl>|<w:p\b[^>]*/>|<w:p\b[^>]*>.*?</w:p>", body, re.S):
        s = tok.group(0)
        if s.startswith("<w:tbl"):
            rows = re.findall(r"<w:tr[ >].*?</w:tr>", s, re.S)
            for i, r in enumerate(rows):
                cells = [_t(c) for c in re.findall(r"<w:tc>.*?</w:tc>", r, re.S)]
                units.append({"kind": "row", "cells": cells, "row": i, "path": [h for _, h in path]})
            continue
        m = re.search(r'<w:pStyle w:val="(?:Heading|heading)\s?(\d)"', s)
        text = _t(s)
        if "PAGEREF" in s or re.search(r'w:val="TOC\d', s):
            continue
        if m and text:
            lvl = int(m.group(1))
            path = [(l, h) for l, h in path if l < lvl] + [(lvl, text)]
            units.append({"kind": "heading", "level": lvl, "text": text, "path": [h for _, h in path]})
        elif text:
            units.append({"kind": "para", "text": text, "path": [h for _, h in path]})
    return units


def _section_of(u: dict) -> str:
    return u["path"][-1] if u["path"] else "(front matter)"


def check_structure(units):
    out, seen = [], Counter()
    parents: list[tuple[int, str]] = []
    for u in units:
        if u["kind"] != "heading":
            continue
        t, lvl = u["text"], u["level"]
        parents = [p for p in parents if p[0] < lvl]
        m = NUM_RE.match(t)
        if m:
            num = m.group(1)
            seen[num] += 1
            depth = num.count(".") + 1
            if num[0].isdigit() and depth != lvl:
                out.append({"issue": "NUMBER_LEVEL", "heading": t, "detail": f"number {num} has {depth} part(s) but is Heading {lvl}"})
            par = next((p for p in reversed(parents) if NUM_RE.match(p[1])), None)
            if par and num[0].isdigit() and "." in num:
                pnum = NUM_RE.match(par[1]).group(1)
                if not num.startswith(pnum + "."):
                    out.append({"issue": "NUMBER_PARENT", "heading": t, "detail": f"sits under '{par[1][:50]}'"})
        if t.rstrip().endswith(":"):
            out.append({"issue": "HEADING_COLON", "heading": t, "detail": "heading ends with ':'"})
        parents.append((lvl, t))
    for num, n in seen.items():
        if n > 1:
            out.append({"issue": "DUPLICATE_NUMBER", "heading": num, "detail": f"used by {n} headings"})
    return out


def check_requirements(units, expected: list[str]):
    rows, found = [], {}
    header = None
    for u in units:
        if u["kind"] != "row":
            continue
        cells = u["cells"]
        if u["row"] == 0:
            header = [c.lower() for c in cells]
        m = REQ_RE.match(cells[0]) if cells else None
        if not m:
            continue
        rid = m.group(1)
        cs_i = next((i for i, h in enumerate(header or []) if "current" in h), 2 if len(cells) > 2 else None)
        rt_i = next((i for i, h in enumerate(header or []) if "rating" in h), len(cells) - 1)
        cs = cells[cs_i] if cs_i is not None and cs_i < len(cells) else ""
        rating = cells[rt_i] if rt_i < len(cells) else ""
        issues = []
        if not cs.strip():
            issues.append("Current State empty")
        elif PLACEHOLDER_RE.search(cs):
            issues.append("Current State has a placeholder")
        if not rating.strip():
            issues.append("rating empty")
        elif rating.strip().lower().rstrip(".") not in RATINGS:
            issues.append(f"rating '{rating}' not a standard value")
        found[rid] = found.get(rid, 0) + 1
        rows.append({"req": rid, "section": _section_of(u), "rating": rating, "current_state_words": len(cs.split()), "issues": issues})
    missing = [r for r in expected if r not in found]
    dupes = [r for r, n in found.items() if n > 1]
    return {"rows": rows, "missing": missing, "duplicates": dupes}


def check_domains(units, domains: list[dict]):
    """Per requirement domain: Discovery facts and a Drawbridge Impact present? Headings at the
    wrong level still count when their number belongs to the domain (the structure check reports the level)."""
    out = []
    heads = [u for u in units if u["kind"] == "heading"]
    for d in domains:
        name = d["heading"].lower()
        dh = next((h for h in heads if name[:18] in h["text"].lower()), None)
        if not dh:
            out.append({"domain": f'{d["number"]} {d["heading"]}', "issue": "domain heading not found"})
            continue
        m = NUM_RE.match(dh["text"])
        dnum = m.group(1) if m else None
        # the domain's span: from its heading to the next heading of the same or higher level that is not numbered inside it
        start = units.index(dh)
        span = []
        for u in units[start + 1:]:
            if u["kind"] == "heading" and u["level"] <= dh["level"]:
                um = NUM_RE.match(u["text"])
                if not (dnum and um and um.group(1).startswith(dnum + ".")):
                    break
            span.append(u)
        kids = [u["text"].lower() for u in span if u["kind"] == "heading"]
        paras = [u for u in span if u["kind"] == "para"]
        tables = [u for u in span if u["kind"] == "row" and u["row"] == 0 and not (u["cells"] and u["cells"][0].lower().startswith("req"))]
        before_db = []
        for u in span:
            if u["kind"] == "heading" and "drawbridge" in u["text"].lower():
                break
            if u["kind"] == "para":
                before_db.append(u)
        miss, notes = [], []
        if not any("drawbridge" in k for k in kids):
            miss.append("Drawbridge Impact")
        if any("discovery" in k for k in kids) or tables:
            pass
        elif before_db:
            notes.append("discovery facts are in prose, no Discovery Information table or heading")
        else:
            miss.append("Discovery Information")
        if not paras and not tables:
            notes.append("no content beyond the requirement table")
        words = sum(len((u.get("text") or " ".join(u.get("cells", []))).split()) for u in span)
        out.append({"domain": dh["text"], "missing_subsections": miss, "notes": notes, "words": words})
    return out


def check_placeholders_unknowns(units):
    ph, unk = [], defaultdict(list)
    for u in units:
        text = u.get("text") or " | ".join(u.get("cells", []))
        if not text:
            continue
        if u["kind"] == "row" and u["row"] > 0 and not any(c.strip() for c in u["cells"]):
            ph.append({"section": _section_of(u), "text": "(empty table row)"})
        for m in PLACEHOLDER_RE.finditer(text):
            ph.append({"section": _section_of(u), "text": m.group(0)})
        if UNKNOWN_RE.search(text) and not _section_of(u).lower().startswith("appendix d"):
            unk[_section_of(u)].append(text[:300])
    return ph, dict(unk)


def appendix_d(units, work_dir: Path):
    rows = []
    for u in units:
        if u["kind"] == "row" and u["path"] and u["path"][0].lower().startswith("appendix d") and u["row"] > 0:
            c = u["cells"]
            if c and re.match(r"^(D\s?R|R)-\s?\d+", c[0].replace(" ", "")):
                rows.append({"id": c[0].replace(" ", ""), "requirements": c[1] if len(c) > 1 else "",
                             "status": c[-1] if c else "", "need": (c[2] if len(c) > 2 else "")[:200]})
    verdicts = {}
    reg = work_dir / "gap-register.md"
    if reg.is_file():
        for m in re.finditer(r"^\| ((?:DR|R)-\d+) \| (.+?) \| (.+?) \|$", reg.read_text(encoding="utf-8"), re.M):
            verdicts[m.group(1)] = {"verdict": m.group(2), "priority": m.group(3)}
    for r in rows:
        r.update(verdicts.get(r["id"], {}))
        if not re.match(r"^DR-\d+$", r["id"]):
            r["id_issue"] = "ID does not follow DR-nn"
    return rows


def run_lints(docx: Path):
    out = {}
    py = sys.executable
    pl = SKILLS / "csa-writing-style" / "scripts" / "prose_lint.py"
    r = subprocess.run([py, str(pl), str(docx), "--json"], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
        out["prose"] = [{"section": s["title"], "words": s["prose_words"], "warnings": s["warnings"]} for s in d["sections"] if s["warnings"]]
    except Exception:
        out["prose_error"] = (r.stderr or r.stdout)[-300:]
    tl = SKILLS / "australian-it-ot-terminology" / "scripts" / "term_lint.py"
    r = subprocess.run([py, str(tl), str(docx)], capture_output=True, text=True)
    out["term_flags"] = len(re.findall(r"TERM_REVIEW_REQUIRED|TERM_[A-Z_]+ ", r.stdout))
    out["term_summary"] = [l.strip() for l in r.stdout.splitlines() if "TERM_" in l][:40]
    sf = SKILLS / "csa-quality-review" / "scripts" / "section_fit_scan.py"
    r = subprocess.run([py, str(sf), str(docx), "--json"], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
        cands = d.get("candidates") or d.get("findings") or []
        out["section_fit"] = [{"verdict": c.get("verdict"), "severity": c.get("severity"), "section": c.get("section") or c.get("heading"),
                               "target": c.get("target"), "text": (c.get("text") or c.get("excerpt") or "")[:160]} for c in cands]
    except Exception:
        out["section_fit_error"] = (r.stderr or r.stdout)[-300:]
    return out


def evidence_use(units, work_dir: Path):
    out = {}
    m = work_dir / "evidence-matrix.csv"
    if m.is_file():
        import csv
        rows = list(csv.DictReader(m.open(encoding="utf-8-sig")))
        out["matrix_rows"] = len(rows)
        out["by_status"] = dict(Counter(r.get("status", "") for r in rows))
        out["by_review_state"] = dict(Counter(r.get("review_state", "") for r in rows))
    db = work_dir / "discovery-index.sqlite"
    if db.is_file():
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            hosts = sorted({h for (h,) in con.execute("select distinct host from captures where host is not null")})
        except Exception:
            hosts = []
        doc_text = " ".join((u.get("text") or " ".join(u.get("cells", []))) for u in units).upper()
        out["captured_hosts"] = len(hosts)
        out["captured_hosts_not_in_document"] = [h for h in hosts if HOST_RE.match(h or "") and h.upper() not in doc_text]
    return out


def document_state(docx: Path):
    x = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
    out = {"tracked_insertions": x.count("<w:ins "), "tracked_deletions": x.count("<w:del ")}
    try:
        from csa_docx.list_comments import list_comments
        cs = list_comments(docx)
        change = [c for c in cs if re.search(r"\(Ref S\d+-[EA]\d+", c["text"])]
        review = [c for c in cs if c not in change]
        out["change_comments"] = len(change)
        out["reviewer_comments"] = [{"author": c["author"], "text": c["text"][:300], "section": (c["heading_path"] or ["?"])[-1]} for c in review]
    except Exception as exc:
        out["comments_error"] = str(exc)
    return out


def load_blocks() -> dict:
    p = SKILLS / "csa-document-template" / "references" / "template-blocks.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"domains": []}


def mechanical_markdown(a: dict) -> str:
    L = [f"# Document audit (scripted stage) - {a['audit_id']}", "", f"Document: {a['docx']}", ""]
    d = a["document"]
    L += ["## Document state", "", f"- Tracked changes left: {d['tracked_insertions']} insertions, {d['tracked_deletions']} deletions",
          f"- Open reviewer comments: {len(d.get('reviewer_comments', []))} (framework change comments: {d.get('change_comments', 0)})", ""]
    for c in d.get("reviewer_comments", []):
        L.append(f"- {c['section']}: {c['author']}: {c['text']}")
    L += ["", "## Structure", ""] + [f"- {s['issue']}: {s['heading']} ({s['detail']})" for s in a["structure"]] or ["- No issues."]
    r = a["requirements"]
    L += ["", "## Requirements", "", f"- Requirement rows found: {len(r['rows'])}; missing: {', '.join(r['missing']) or 'none'}; duplicated: {', '.join(r['duplicates']) or 'none'}"]
    L += [f"- {x['req']} ({x['section']}): {'; '.join(x['issues'])}" for x in r["rows"] if x["issues"]]
    L += ["", "## Domain subsections", ""]
    for x in a["domains"]:
        bits = ([f"missing {', '.join(x['missing_subsections'])}"] if x.get("missing_subsections") else []) + x.get("notes", []) + ([x["issue"]] if x.get("issue") else [])
        L.append(f"- {x['domain']}: {'; '.join(bits) or 'complete'} ({x.get('words', 0)} words)")
    L += ["", "## Placeholders", ""] + ([f"- {p['section']}: {p['text']}" for p in a["placeholders"]] or ["- None."])
    L += ["", "## Declared unknowns by section", ""]
    for s, v in a["unknowns"].items():
        L.append(f"- {s}: {len(v)}")
    L += ["", "## Appendix D", ""] + [f"- {x['id']} [{x['status']}] {x.get('verdict', 'not checked')}{' - ' + x['id_issue'] if x.get('id_issue') else ''}" for x in a["appendix_d"]]
    lt = a["lints"]
    L += ["", "## Lints", "", f"- Prose warnings in {len(lt.get('prose', []))} sections; terminology flags {lt.get('term_flags', 0)}; section-fit candidates {len(lt.get('section_fit', []))}"]
    L += [f"- {p['section']}: {'; '.join(p['warnings'])}" for p in lt.get("prose", [])]
    e = a["evidence"]
    L += ["", "## Evidence", "", f"- Matrix rows: {e.get('matrix_rows', 0)} {e.get('by_status', {})}; review state {e.get('by_review_state', {})}",
          f"- Captured hosts: {e.get('captured_hosts', 0)}; not named in the document: {', '.join(e.get('captured_hosts_not_in_document', [])) or 'none'}"]
    return "\n".join(L) + "\n"


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def write_section_texts(units, out_dir: Path) -> list[dict]:
    """One Markdown file per audit unit: each 3.x domain, and every other top-level section.
    The audit agent reads these instead of the DOCX."""
    tdir = out_dir / "text"
    tdir.mkdir(parents=True, exist_ok=True)
    units_out, cur, buf = [], None, []

    def flush():
        if cur and buf:
            f = tdir / f"{slug(cur)}.md"
            f.write_text("\n".join(buf) + "\n", encoding="utf-8")
            units_out.append({"title": cur, "slug": slug(cur), "text_file": str(f), "words": sum(len(b.split()) for b in buf)})

    for u in units:
        top = u["path"][0] if u["path"] else ""
        is_domain_head = u["kind"] == "heading" and u["level"] == 2 and re.match(r"^3\.\d+ ", u["text"])
        is_top = u["kind"] == "heading" and u["level"] == 1
        if is_top and u["text"].lower().startswith("table of contents"):
            flush(); cur, buf = None, []
            continue
        if is_domain_head or (is_top and not re.match(r"^3 ", u["text"])):
            flush(); cur, buf = u["text"], []
        if cur is None:
            continue
        if is_top and re.match(r"^3 ", u["text"]):
            flush(); cur, buf = None, []
            continue
        if u["kind"] == "heading":
            buf.append("#" * min(u["level"] + 1, 6) + " " + u["text"])
        elif u["kind"] == "para":
            buf.append(u["text"])
        else:
            buf.append("| " + " | ".join(c.replace("|", "/") for c in u["cells"]) + " |")
    flush()
    return units_out


def run(docx: Path, work_dir: Path, label: str = "") -> dict:
    audit_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = work_dir / "audit" / audit_id
    (out_dir / "sections").mkdir(parents=True, exist_ok=True)
    units = read_units(docx)
    blocks = load_blocks()
    expected = [r for d in blocks.get("domains", []) for r in d.get("req_ids", [])]
    ph, unk = check_placeholders_unknowns(units)
    a = {
        "audit_id": audit_id, "project": label, "docx": str(docx), "generated_at": datetime.now().isoformat(timespec="seconds"),
        "document": document_state(docx),
        "structure": check_structure(units),
        "requirements": check_requirements(units, expected),
        "domains": check_domains(units, blocks.get("domains", [])),
        "placeholders": ph, "unknowns": unk,
        "appendix_d": appendix_d(units, work_dir),
        "lints": run_lints(docx),
        "evidence": evidence_use(units, work_dir),
        "sections": sorted({u["path"][1] for u in units if len(u["path"]) > 1 and re.match(r"^\d+\.\d+ ", u["path"][1])},
                           key=lambda s: [int(p) for p in NUM_RE.match(s).group(1).split(".")] if NUM_RE.match(s) and NUM_RE.match(s).group(1)[0].isdigit() else [999]),
    }
    a["units"] = write_section_texts(units, out_dir)
    (out_dir / "audit.json").write_text(json.dumps(a, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "mechanical.md").write_text(mechanical_markdown(a), encoding="utf-8")
    a["out_dir"] = str(out_dir)
    return a


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docx"); ap.add_argument("--work-dir", required=True); ap.add_argument("--label", default="")
    a = ap.parse_args(argv)
    res = run(Path(a.docx), Path(a.work_dir), a.label)
    print(json.dumps({"status": "OK", "audit_id": res["audit_id"], "out_dir": res["out_dir"],
                      "audit_units": len(res["units"]), "requirement_rows": len(res["requirements"]["rows"]),
                      "missing_requirements": res["requirements"]["missing"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
