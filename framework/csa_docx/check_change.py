"""Check a ChangesCSA_*.md change file before approval.

    python -m csa_docx.check_change <change file> [--workspace <project root>] [--json]
                                    [--no-anchors] [--no-lint]

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
        if IP_RE.search(t) and not _is_table_text(t):
            out.append(finding("ERROR", "IP_IN_TEXT", "IP address or subnet in prose Text; put it in the discovery table or appendix and name the component by role", r.edit_id))
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


def lint_findings(records) -> list[dict]:
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
            r = subprocess.run([sys.executable, str(script), str(md), "--strict"], capture_output=True, text=True)
            if r.returncode != 0:
                detail = "\n".join(line for line in r.stdout.splitlines() if line.strip())
                out.append(finding("WARN", code, detail[-1500:]))
    finally:
        md.unlink(missing_ok=True)
    return out


def check(path: Path, workspace: str | None = None, anchors: bool = True, lint: bool = True) -> dict:
    text = path.read_text(encoding="utf-8")
    records = parse_change_records(text)
    findings = structure_findings(path, text, records)
    if anchors:
        if workspace:
            findings += anchor_findings(records, workspace)
        else:
            findings.append(finding("INFO", "ANCHOR_CHECK_SKIPPED", "no --workspace given"))
    findings += hygiene_findings(records)
    findings += brief_findings(text, records)
    findings += section_fit_findings(text, records)
    if lint:
        findings += lint_findings(records)
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
    a = ap.parse_args(argv)
    res = check(Path(a.path), a.workspace, anchors=not a.no_anchors, lint=not a.no_lint)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"check-change: {Path(a.path).name}  records: {res['records']}  errors: {res['errors']}  warnings: {res['warnings']}")
        for f in res["findings"]:
            print(f"  {f['level']:<5} {f['code']:<22} {f['edit_id'] or '-':<8} {f['message']}")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
