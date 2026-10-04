"""Check a ChangesCSA_*.md change file before approval.

    python -m csa_docx.check_change <change file> [--workspace <project root>] [--json]
                                    [--no-anchors] [--no-lint] [--evidence CSV] [--sites ROK=Rockhampton,...]

Fact gates (csa_docx.fact_checks): every fact cites evidence, states its basis
(observed / documented / stated, never inferred), carries only terms the evidence
holds, and the Text keeps the evidence's scope.

Run from .agents/framework. Exit code 1 when there is at least one ERROR;
warnings never fail the check. `csa check-change <N>` wraps this.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from csa_docx.change_parser import parse_change_records

FILENAME_RE = re.compile(r"^ChangesCSA_.+?_Section(?P<section>\d+)(?:_[^.]+)?\.md$")
ANY_ID_HEADING_RE = re.compile(r"^###\s+(?!REJECTED\b)(?P<id>[A-Za-z]*\d*-[A-Za-z]*\d+)\s+-\s+\S", re.M)
STATUS_RE = re.compile(r"^\*\*Status:\*\*", re.M)
STABLE_ID_RE = re.compile(r"@H[0-9][\w.\-]*")
ACTIONS = ("replace", "insert before", "insert after", "delete")


def finding(level: str, code: str, message: str, edit_id: str | None = None) -> dict:
    return {"level": level, "code": code, "edit_id": edit_id, "message": message}


def structure_findings(path: Path, text: str, records) -> list[dict]:
    out = []
    m = FILENAME_RE.match(path.name)
    section = m["section"] if m else None
    if not m:
        out.append(finding("ERROR", "FILENAME", f"{path.name} is not ChangesCSA_<App>_Section<N>.md or ..._Section<N>_<label>.md"))
    if not STATUS_RE.search(text):
        out.append(finding("ERROR", "NO_STATUS", "no **Status:** line"))
    valid = re.compile(rf"^S{section}-[EA]\d+$") if section else re.compile(r"^S\d+-[EA]\d+$")
    seen = set()
    for h in ANY_ID_HEADING_RE.finditer(text):
        eid = h["id"]
        if not valid.match(eid):
            out.append(finding("ERROR", "BAD_ID", f"{eid} is not S{section or '<N>'}-E<n> or S{section or '<N>'}-A<n>", eid))
        if eid in seen:
            out.append(finding("ERROR", "DUPLICATE_ID", f"{eid} is used more than once", eid))
        seen.add(eid)
    for r in records:
        if "@H" not in (r.where or ""):
            out.append(finding("ERROR", "WHERE_NOT_STABLE_ID", "Where: must be a stable ID (@H...) from lookupStableId", r.edit_id))
        action = (r.action or "").strip().lower()
        if not action.startswith(ACTIONS):
            out.append(finding("ERROR", "BAD_ACTION", f"Do: must start with Replace, Insert before, Insert after or Delete (got {r.action[:60]!r})", r.edit_id))
        elif not action.startswith("delete") and not (r.text or "").strip():
            out.append(finding("ERROR", "MISSING_TEXT", "no Text: for a Replace or Insert", r.edit_id))
    return out


def anchor_findings(records, workspace: str) -> list[dict]:
    from csa_docx import tools

    out, cache = [], {}
    for r in records:
        ids = sorted({i.rstrip(".-") for i in STABLE_ID_RE.findall(f"{r.where}\n{r.action}")})
        for sid in ids:
            if sid not in cache:
                cache[sid] = tools.lookupStableId(sid, workspace=workspace)
            res = cache[sid]
            if res.get("status") == "ERROR":
                return [finding("WARN", "ANCHOR_CHECK_UNAVAILABLE", f"anchors not checked: {str(res.get('message', ''))[:300]}")]
            if not res.get("unique_id"):
                out.append(finding("ERROR", "ANCHOR_UNRESOLVED",
                                   f"{sid} does not resolve to exactly one place (match_count {res.get('match_count')})", r.edit_id))
    return out


EID_RE = re.compile(r"\bE-\d{2,}\b")
MARKDOWN_RE = re.compile(r"\*\*|`|^\s*>|^\s*#", re.M)
# Addresses and subnets are table or appendix detail, never document prose (csa-writing-style, identifier budget).
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")


def _is_table_text(t: str) -> bool:
    """A table row or cell edit (pipe-separated, or Observed:/Assessment: row text) may carry addresses."""
    first = t.strip().splitlines()[0] if t.strip() else ""
    return " | " in first or first.startswith(("Observed:", "Assessment:"))


BRIEF_RE = re.compile(r"^##\s+Section brief\s*$(.*?)(?=^#{2,}\s|^---\s*$|\Z)", re.M | re.S | re.I)
BRIEF_ITEM_RE = re.compile(r"^\s*[-*]?\s*([BC]\d+)\b", re.M)
FACT_TAG_RE = re.compile(r"^\s*[-*]\s*\[([BC]\d+(?:\s*,\s*[BC]\d+)*)\]")


def brief_findings(text: str, records) -> list[dict]:
    """Section brief: present, every fact tagged with the brief item it answers, every item answered somewhere."""
    prose = [r for r in records if (r.text or "").strip() and not _is_table_text(r.text) and r.action.lower().startswith(("replace", "insert"))]
    if not prose:
        return []
    m = BRIEF_RE.search(text)
    if not m:
        return [finding("WARN", "NO_BRIEF", "no '## Section brief' (purpose, requirements, B/C questions); write it before the evidence search")]
    items = list(dict.fromkeys(BRIEF_ITEM_RE.findall(m.group(1))))
    out = []
    if not items:
        out.append(finding("WARN", "BRIEF_NO_QUESTIONS", "the section brief lists no B1/C1 questions"))
    for r in prose:
        for line in (r.facts or "").splitlines():
            ln = line.strip()
            if not ln.startswith(("-", "*")) or re.match(r"^[-*]\s*(Table detail|Unknown)\s*:", ln, re.I):
                continue
            if not FACT_TAG_RE.match(ln):
                out.append(finding("WARN", "UNTAGGED_FACT", f"fact does not name the brief item it answers: {ln[:80]}", r.edit_id))
    rest = text[:m.start()] + text[m.end():]
    for it in items:
        if not re.search(rf"\b{it}\b", rest):
            out.append(finding("WARN", "BRIEF_ITEM_UNANSWERED", f"{it} is not answered by any fact, open question or unchanged note"))
    return out


BRIEF_CODES = ("NO_BRIEF", "BRIEF_NO_QUESTIONS", "UNTAGGED_FACT", "BRIEF_ITEM_UNANSWERED")


def strict_brief(findings: list[dict]) -> list[dict]:
    """The brief rules as errors: a change is applied only when its brief is there, every fact names the question it
    answers, and every question is answered somewhere (a fact, an open question or an unchanged note)."""
    for f in findings:
        if f["code"] in BRIEF_CODES and f["level"] == "WARN":
            f["level"] = "ERROR"
    return findings


def notes_findings(records, notes: Path | None) -> list[dict]:
    """The author's search note (`WORK_DIR/author/<N>/search-notes.md`) is what the Writer trusts instead of repeating searches."""
    prose = [r for r in records if (r.text or "").strip() and not _is_table_text(r.text) and r.action.lower().startswith(("replace", "insert"))]
    if notes is None or not prose or Path(notes).is_file():
        return []
    return [finding("WARN", "NO_SEARCH_NOTES", f"no {Path(notes).name} at {notes}: the Writer cannot tell which searches were done")]


_ASSESS_RE = re.compile(r"^\s*>?\s*Assessment:\s*(.+?)\s*$", re.M)
_OBSERVED_RE = re.compile(r"^\s*>?\s*Observed:\s*(.*)$", re.M)
_SEP_RE = re.compile(r"\bSEP-[A-Z]+-\d+\b")


def node_findings(records, node: dict | None) -> list[dict]:
    """Check records against the section as the document defines it (csa_docx.doc_spec): ratings come from the
    document's own Rating dropdown, Not Applicable needs a justification, requirement IDs belong to this section,
    and every anchor sits under the section's heading."""
    if not node:
        return []
    out = []
    ratings = node.get("ratings") or ["Met", "Partially Met", "Not Met", "Not Applicable"]
    own = {r["id"] for p in node.get("parts", []) for r in p.get("requirements", [])}
    hid = node.get("hid", "")
    for r in records:
        text = r.text or ""
        for m in _ASSESS_RE.finditer(text):
            if m.group(1) not in ratings:
                out.append(finding("ERROR", "RATING_INVALID", f"rating '{m.group(1)}' is not one of {', '.join(ratings)}", r.edit_id))
            if m.group(1) == "Not Applicable":
                obs = _OBSERVED_RE.search(text)
                if not obs or len(obs.group(1).split()) < 5:
                    out.append(finding("ERROR", "NA_NO_JUSTIFICATION", "Not Applicable needs a current state that says why", r.edit_id))
        req_tables = {p_["table"] for p_ in node.get("parts", []) if p_.get("kind") == "requirement" and p_.get("table")}
        wm = re.search(r"(@H[\d.]+-T\d+)-R\d+", r.where or "")
        if wm and wm.group(1) in req_tables and not _ASSESS_RE.search(text):
            cells = [c.strip() for c in text.strip().lstrip(">").split("|")]
            if len(cells) == 2 and cells[1] not in ratings:
                out.append(finding("ERROR", "RATING_INVALID", f"'{cells[1]}' is not one of {', '.join(ratings)} "
                                   "(a requirement row is '<current state> | <rating>' or Observed:/Assessment: lines)", r.edit_id))
            elif len(cells) not in (2, 4):
                out.append(finding("ERROR", "REQ_ROW_SHAPE", "a requirement row is '<current state> | <rating>', the full row, "
                                   "or Observed:/Assessment: lines", r.edit_id))
        foreign = sorted(set(_SEP_RE.findall((r.facts or "") + " " + text)) - own) if own else []
        if foreign:
            out.append(finding("WARN", "REQ_NOT_IN_SECTION", f"{', '.join(foreign)} are not requirements of {node.get('title')}", r.edit_id))
        m = re.search(r"@H[\d.]+(?:-[A-Z]\d+(?:-R\d+)?)?", r.where or "")
        if hid and m and not (m.group(0) == hid or m.group(0).startswith(hid + ".") or m.group(0).startswith(hid + "-")):
            out.append(finding("WARN", "WHERE_OUTSIDE_SECTION", f"{m.group(0)} is not under {hid} ({node.get('title')})", r.edit_id))
    return out


def section_fit_findings(text: str, records) -> list[dict]:
    """Signal terms in each prose record against the domain the brief's requirement IDs name.
    Uses the section scope map and the quality reviewer's scanner, so the rules live in one place."""
    m = BRIEF_RE.search(text)
    req = re.search(r"Requirements:\*?\*?\s*(.*)", m.group(1)) if m else None
    families = set(re.findall(r"SEP-([A-Z]+)-\d+", req.group(1))) if req else set()
    if not families:
        return []
    scan_py = SKILLS / "csa-quality-review" / "scripts" / "section_fit_scan.py"
    scope_md = SKILLS / "csa-quality-review" / "references" / "section-scope.md"
    if not scan_py.is_file() or not scope_md.is_file():
        return []
    import importlib.util
    spec = importlib.util.spec_from_file_location("section_fit_scan", scan_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("section_fit_scan", mod)
    try:
        spec.loader.exec_module(mod)
        domains = mod.load_scope(scope_md)
    except BaseException:
        return []
    owner = set()
    cur = None
    for line in scope_md.read_text(encoding="utf-8").splitlines():
        h = re.match(r"^###\s+(\d+\.\d+)\s", line)
        if h:
            cur = h.group(1)
        elif cur and line.startswith("- **Requirements:**") and families & set(re.findall(r"SEP-([A-Z]+)-\d+", line)):
            owner.add(cur)
    if not owner:
        return []
    out = []
    for r in records:
        t = (r.text or "").strip()
        if not t or _is_table_text(t):
            continue
        sc = mod.scores(t, domains)
        own = max(sc.get(d, 0) for d in owner)
        other, hits = max(((d, n) for d, n in sc.items() if d not in owner), key=lambda kv: kv[1], default=(None, 0))
        if other and hits >= 3 and hits >= own + 2:
            name = next((d.name for d in domains if d.num == other), other)
            out.append(finding("WARN", "SECTION_FIT", f"the text reads as {other} {name} ({hits} signal terms) more than this section's domain ({own}); tell the section's story or relocate the detail", r.edit_id))
    return out


def hygiene_findings(records) -> list[dict]:
    from csa_docx.comment_text import comment_warnings

    out = []
    for r in records:
        t = r.text or ""
        if EID_RE.search(t):
            out.append(finding("ERROR", "EID_IN_TEXT", "evidence ID in Text; it belongs in Why only", r.edit_id))
        if STABLE_ID_RE.search(t):
            out.append(finding("ERROR", "STABLE_ID_IN_TEXT", "stable ID (@H...) in Text", r.edit_id))
        elif MARKDOWN_RE.search(t):
            out.append(finding("ERROR", "MARKDOWN_IN_TEXT", "Markdown (**, backticks, >, #) in Text; it would land in the document", r.edit_id))
        if r.action.lower().startswith(("replace", "delete")) and not re.search(r"currently:\s*[\"\u201c]", r.where or "") and "-T" not in (r.where or ""):
            out.append(finding("WARN", "NO_CURRENTLY", "Where has no 'currently: \"...\"' quote; apply uses it to confirm the stable ID still points at the right paragraph", r.edit_id))
        if IP_RE.search(t) and not _is_table_text(t):
            out.append(finding("WARN", "IP_IN_TEXT", "IP address in prose Text: use the host name if the evidence gives one; an address is fine where no name was found", r.edit_id))
        if t.strip() and r.action.lower().startswith(("replace", "insert")) and not (r.facts or "").strip() and not _is_table_text(t):
            out.append(finding("WARN", "NO_FACTS", "no **Facts:** list; the Writer should write Text from the authoring agent's fact list", r.edit_id))
        for w in comment_warnings(r):
            out.append(finding("WARN", "NOTE", w, r.edit_id))
    return out


SKILLS = Path(__file__).resolve().parents[2] / "skills"
LINTS = (
    ("PROSE_LINT", SKILLS / "csa-writing-style" / "scripts" / "prose_lint.py"),
    ("TERM_LINT", SKILLS / "australian-it-ot-terminology" / "scripts" / "term_lint.py"),
)


SOURCE_KEY_RE = re.compile(r"^\s*(?:[A-Z]{2,6}\d{3,}[A-Z0-9]*|row\s*\d+|line\s*\d+|E-\d+)\s*[:(-]", re.I)


def subject_findings(records) -> list[dict]:
    """A table row is about hosts, a role, an application or the system. A first cell that
    starts with a source identifier (a collection ID such as BRI0083D, a sheet row or line
    number, an evidence ID) makes the source's own key the subject. See 'The subject is the
    system' in csa-core-rules.md."""
    out = []
    for r in records:
        t = (r.text or "").strip()
        if not _is_table_text(t):
            continue
        for line in t.splitlines():
            cells = [c.strip() for c in line.strip().lstrip(">").strip().strip("|").split("|")]
            if cells and SOURCE_KEY_RE.match(cells[0]):
                out.append(finding("WARN", "TABLE_ROW_SOURCE_KEYED",
                                   f"first cell {cells[0][:40]!r} is a source ID; key the row by host(s), role or "
                                   "application and keep the source ID in Why", r.edit_id))
                break
    return out


def lint_findings(records, max_words: int | None = None) -> list[dict]:
    texts = [(r.edit_id, r.text) for r in records if (r.text or "").strip()]
    if not texts:
        return []
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write("\n\n".join(f"# {eid}\n\n{t}" for eid, t in texts) + "\n")
        md = Path(fh.name)
    out = []
    try:
        for code, script in LINTS:
            if not script.is_file():
                out.append(finding("WARN", code, f"lint script missing: {script}"))
                continue
            args = [sys.executable, str(script), str(md), "--strict"]
            if max_words and code == "PROSE_LINT":
                args += ["--max-words", str(max_words)]
            r = subprocess.run(args, capture_output=True, text=True)
            if r.returncode != 0:
                detail = "\n".join(line for line in r.stdout.splitlines() if line.strip())
                out.append(finding("WARN", code, detail[-1500:]))
    finally:
        md.unlink(missing_ok=True)
    return out


def check(path: Path, workspace: str | None = None, anchors: bool = True, lint: bool = True,
          evidence: str | None = None, sites: str | None = None, notes: str | None = None, strict: bool = False,
          node: dict | None = None) -> dict:
    text = path.read_text(encoding="utf-8")
    records = parse_change_records(text)
    findings = structure_findings(path, text, records)
    if anchors:
        if workspace:
            findings += anchor_findings(records, workspace)
        else:
            findings.append(finding("INFO", "ANCHOR_CHECK_SKIPPED", "no --workspace given"))
    findings += hygiene_findings(records)
    brief = brief_findings(text, records)
    findings += strict_brief(brief) if strict else brief
    findings += notes_findings(records, Path(notes) if notes else None)
    findings += node_findings(records, node)
    findings += section_fit_findings(text, records)
    findings += subject_findings(records)
    from csa_docx.fact_checks import fact_findings, load_matrix, parse_sites
    ev = Path(evidence) if evidence else (Path(workspace) / "csa-work" / "evidence-matrix.csv" if workspace else None)
    findings += fact_findings(records, load_matrix(ev), parse_sites(sites), finding)
    if lint:
        from csa_docx.prose_budget import budgets
        b = budgets(path.parent, workspace)
        findings.append(finding("INFO", "PROSE_BUDGET", f"section guide {b['section_words']} words ({b['basis']})"))
        findings += lint_findings(records, b["section_words"])
    return {
        "file": str(path),
        "records": len(records),
        "findings": findings,
        "errors": sum(f["level"] == "ERROR" for f in findings),
        "warnings": sum(f["level"] == "WARN" for f in findings),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--workspace", help="project root, for resolving @H anchors")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-anchors", action="store_true")
    ap.add_argument("--no-lint", action="store_true")
    ap.add_argument("--evidence", help="evidence-matrix.csv (default: <workspace>/csa-work/evidence-matrix.csv)")
    ap.add_argument("--sites", help="site prefixes for scope checks, e.g. ROK=Rockhampton,MKY=Mackay")
    ap.add_argument("--notes", help="the author's search-notes.md; a warning when it is missing")
    ap.add_argument("--strict", action="store_true", help="brief findings are errors (used when the change is applied)")
    ap.add_argument("--node", help="the section as the document defines it (csa spec show N --json)")
    a = ap.parse_args(argv)
    node = json.loads(Path(a.node).read_text(encoding="utf-8")) if a.node and Path(a.node).is_file() else None
    res = check(Path(a.path), a.workspace, anchors=not a.no_anchors, lint=not a.no_lint, evidence=a.evidence, sites=a.sites,
                notes=a.notes, strict=a.strict, node=node)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"check-change: {Path(a.path).name}  records: {res['records']}  errors: {res['errors']}  warnings: {res['warnings']}")
        for f in res["findings"]:
            print(f"  {f['level']:<5} {f['code']:<22} {f['edit_id'] or '-':<8} {f['message']}")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
