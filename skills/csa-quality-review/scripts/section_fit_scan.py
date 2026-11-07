#!/usr/bin/env python3
"""section_fit_scan.py -- find CSA text that may sit in the wrong section or subsection.

Starting point for csa-quality-review check 9 (Section fit). It reads a CSA .docx (or a
Markdown draft), walks every paragraph and table row with its stable ID (@H...), and
reports candidates for the reviewer to confirm:

  WRONG_SECTION      the unit's signal terms point clearly at a domain this section does
                     not host (domains, hosts and terms come from references/section-scope.md)
  WRONG_SUBSECTION   the unit does a job its subsection does not accept: an interpretation
                     in Observed / Discovery Information, a recommendation in Findings, an
                     observation heading under "Design and functionality expected", ...
  SPLIT              one unit mixes finding, isolation consequence and recommendation
  OUT_OF_SCOPE       a recommendation in a template CSA (no Recommendations home), or
                     general technology explanation in a domain section
  MISPLACED_HEADING  a heading that names another domain, under this domain's Heading 1

It is a keyword and pattern scan, not a judgement: every candidate needs a reader to
confirm it, and it cannot see duplicates or facts stated only in the wrong place. The
reviewer applies the rules in references/section-scope.md. The script never modifies input.

Usage:
  python3 section_fit_scan.py <file.docx|file.md> [--section N | --heading T] [--domain 3.5]
                              [--min-hits 2] [--margin 2] [--json] [--strict]

--section N   the Nth Heading 1 (1-based, same as prose_lint.py; its stable ID is @H<N+1>)
--heading T   the Heading 1 whose title starts with T (safer when there are empty Heading 1s)
--domain D    template CSAs: only the domain block D (e.g. 3.5) inside Requirement Domain Assessments
--min-hits    signal-term hits the other domain needs before a WRONG_SECTION candidate (default 2)
--margin      hits by which the other domain must beat this section's own domains (default 2)
--strict      exit 1 when any candidate has a MAJOR severity hint
With --section/--heading/--domain, the report also lists INBOUND candidates: units elsewhere
whose signal terms point at the selected section's domains.
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
SCOPE_MAP = HERE.parent / "references" / "section-scope.md"
FRAMEWORK = HERE.parents[2] / "framework"  # .agents/framework
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# ---------------------------------------------------------------- scope map
@dataclass
class Domain:
    num: str
    name: str
    legacy: list[str]
    terms: list[str]
    term_re: re.Pattern | None = None


def norm(t: str) -> str:
    t = t.replace("&amp;", "&").lower()
    t = re.sub(r"^\s*(?:\d+(?:\.\d+)*\.?|[a-z]\.)\s+", "", t)  # leading numbering
    t = re.sub(r"[\"“”'‘’()]", "", t)
    t = t.replace("&", "and")
    return re.sub(r"\s+", " ", t).strip()


def load_scope(path: Path) -> list[Domain]:
    if str(FRAMEWORK) not in sys.path:
        sys.path.insert(0, str(FRAMEWORK))
    from csa_docx import scope_map
    try:
        entries = scope_map.load(path)
    except ValueError:
        sys.exit(f"no domains parsed from {path}")
    return [Domain(num=k, name=e["title"], legacy=e["legacy_headings"],
                   terms=e["signal_terms"], term_re=e["term_re"]) for k, e in entries.items()]


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def match_domain_by_title(title: str, domains: list[Domain], cutoff: float = 0.78) -> Domain | None:
    best = max(domains, key=lambda d: similar(title, d.name))
    return best if similar(title, best.name) >= cutoff else None


def legacy_hosts(title: str, domains: list[Domain]) -> list[Domain]:
    t = norm(title)
    out = []
    for d in domains:
        for lh in d.legacy:
            n = norm(lh)
            if t == n or t.startswith(n) or (len(t) > 6 and n.startswith(t)):
                out.append(d)
                break
    return out


# ---------------------------------------------------------------- units
@dataclass
class Unit:
    id: str | None
    kind: str  # heading | paragraph | table_row
    level: int
    text: str
    path: list[str] = field(default_factory=list)  # heading titles H1..Hn above (or of) the unit


def _stable_ids_module():
    spec = importlib.util.spec_from_file_location("csa_stable_ids", FRAMEWORK / "csa_docx" / "stable_ids.py")
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["csa_stable_ids"] = mod
    spec.loader.exec_module(mod)
    return mod


def _paragraphs_docxengine(path: Path):
    sys.path.insert(0, str(FRAMEWORK))
    sys.path.insert(0, str(FRAMEWORK / "vendor"))
    from csa_docx.engines.docxengine_adapter import DocxEngineEditor  # noqa: E402

    return DocxEngineEditor(path, section_heading=None).paragraphs_with_table_rows()


def _paragraphs_fallback(path: Path):
    """Same unit order as DocxEngineEditor.paragraphs_with_table_rows(): body-level w:p and
    w:tbl only (content controls are not flattened), each table expanded into its rows."""
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    body = root.find(f"{W}body")
    out = []
    t_ord = 0
    for child in list(body):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            ps = child.find(f"{W}pPr/{W}pStyle")
            style = ps.get(f"{W}val") if ps is not None else ""
            text = "".join(t.text or "" for t in child.iter(f"{W}t"))
            out.append(SimpleNamespace(style=style, text=text, table_anchor=None, anchor=None))
        elif tag == "tbl":
            t_ord += 1
            for r_ix, tr in enumerate(child.findall(f"{W}tr"), start=1):
                cells = ["".join(t.text or "" for t in tc.iter(f"{W}t")).strip() for tc in tr.findall(f"{W}tc")]
                out.append(SimpleNamespace(style="", text=" | ".join(c for c in cells if c),
                                           table_anchor=f"T{t_ord}", anchor=f"T{t_ord}-R{r_ix}"))
    return out


def read_docx_units(path: Path) -> tuple[list[Unit], str]:
    engine = "docxengine"
    try:
        paras = _paragraphs_docxengine(path)
    except Exception:  # vendored DocxEngine needs Python 3.11+; fall back to a plain XML read
        paras = _paragraphs_fallback(path)
        engine = "fallback-xml"
    sid = _stable_ids_module()
    entries = sid.generate_manifest(paras) if sid else [{"id": None}] * len(paras)
    units: list[Unit] = []
    for p, e in zip(paras, entries):
        style = getattr(p, "style", "") or ""
        m = re.match(r"Heading([1-9])", style)
        text = (getattr(p, "text", "") or "").strip()
        if m:
            units.append(Unit(e.get("id"), "heading", int(m.group(1)), text))
        elif getattr(p, "table_anchor", None):
            units.append(Unit(e.get("id"), "table_row", 0, text))
        elif text:
            units.append(Unit(e.get("id"), "paragraph", 0, text))
    return units, engine


def read_md_units(path: Path) -> tuple[list[Unit], str]:
    units = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or re.match(r"^\|?\s*:?-{3,}", line):
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            units.append(Unit(None, "heading", len(m.group(1)), m.group(2).strip()))
        elif line.startswith("|"):
            units.append(Unit(None, "table_row", 0, " | ".join(c.strip() for c in line.strip("|").split("|") if c.strip())))
        else:
            units.append(Unit(None, "paragraph", 0, re.sub(r"^(?:[-*+]|\d+\.)\s+", "", line).lstrip("> ")))
    return units, "markdown"


def check_ids_against_manifest(docx: Path, units: list[Unit]) -> str:
    """Compare our IDs with prepareDocument()'s stable-ID manifest, if one is next to the DOCX."""
    rs = docx.parent / "run-state"
    for mf in sorted(rs.glob("stable-ids-*.json")) if rs.is_dir() else []:
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        if Path(str(data.get("docx", ""))).name != docx.name:
            continue
        ids = {e["id"]: (e.get("text") or "")[:60] for e in data.get("entries", [])}
        ours = [u for u in units if u.id]
        def key(t: str) -> str:
            return re.sub(r"\s+", " ", t or "").strip()[:40].strip()
        same = sum(1 for u in ours if u.id in ids and key(ids[u.id]) == key(u.text))
        return f"{same}/{len(ours)} IDs match {mf.name} (built {data.get('generated_at', '?')})"
    return "no prepareDocument manifest next to the DOCX; confirm IDs with csa lookup"


# ---------------------------------------------------------------- roles and kinds
ROLE_RES = [
    ("discovery_information", re.compile(r"discovery information", re.I)),
    ("expected", re.compile(r"design and functionality expected|^expected\b|design intent", re.I)),
    ("observed", re.compile(r"^observed\b|observed configuration", re.I)),
    ("container", re.compile(r"^finding comments", re.I)),
    ("findings", re.compile(r"^findings?\b", re.I)),
    ("drawbridge", re.compile(r"drawbridge impact", re.I)),
    ("operational", re.compile(r"operational behaviou?r", re.I)),
    ("assessment", re.compile(r"^assessment$|^assessment position|^assessment summary", re.I)),
    ("recommendations", re.compile(r"recommendation|short[- ]term|medium[- ]term|long[- ]term|target state", re.I)),
    ("drawing", re.compile(r"^drawing", re.I)),
    ("evidence_appendix", re.compile(r"evidence appendix|appendix table", re.I)),
]
DOC_ROLE_RES = [
    ("document_control", re.compile(r"document control", re.I)),
    ("executive", re.compile(r"executive (?:overview|summary)", re.I)),
    ("scope", re.compile(r"^(?:objectives|scope|assumptions|in scope|out of scope)\b", re.I)),
    ("methodology", re.compile(r"^methodology", re.I)),
    ("discovery_activity", re.compile(r"^discovery activity", re.I)),
    ("architecture", re.compile(r"^architectural review", re.I)),
    ("system_overview", re.compile(r"system assessment overview|system function|business functional", re.I)),
    ("migration", re.compile(r"^migration discovery", re.I)),
    ("glossary", re.compile(r"glossary", re.I)),
    ("appendix", re.compile(r"^append", re.I)),
]
OBSERVATION_HEADING_RE = re.compile(r"observ|interpretation|host[- ]level|script evidence|finding", re.I)

KIND_RES = {
    "RECOMMENDATION": re.compile(
        r"\b(?:recommend(?:ed|s)?\b|it is recommended|should (?:be )?(?:implement|deploy|establish|migrat|introduc|replac|"
        r"configur|review|consider|document|validat|confirm|develop|mov|remov|enabl|disabl|isolat|test|plan)\w*|"
        r"consider (?:implementing|deploying|introducing|moving|replacing)|it is advised|we propose|next steps?)\b", re.I),
    "FINDING": re.compile(
        r"\b(?:does not meet|do not meet|partially met|not met|single point of failure|non-?compliant|"
        r"(?<!design )(?<!artefacts )(?<!documents )(?<!further )(?<!input )indicates? that|suggests? that|this (?:indicates|confirms|establishes|shows|means)|implies|"
        r"is a concern|weakness|gap|risks?)\b", re.I),
    "CONSEQUENCE": re.compile(
        r"\b(?:during (?:an? )?isolation|on isolation|upon isolation|when (?:ot|it) is isolated|if (?:it|ot|the it|the enterprise)"
        r"[^.]{0,40}(?:isolat|unavailable|disconnect|lost)|would (?:fail|stop|lose|be unable|cease|degrade)|"
        r"will (?:fail|stop|lose|be unable|cease|degrade)|cannot (?:authenticate|resolve|synchroni[sz]e|reach))\b", re.I),
    "POSITION": re.compile(r"(?:\b(?:rating|assessment|overall(?: position)?)\s*(?:is|:|-)\s*(?:met|partially met|not met)\b)|^(?:met|partially met|not met)\.?$", re.I),
    "REQUIREMENT": re.compile(r"\b(?:design (?:artefacts? |documents? |documentation )?(?:further )?indicates?|is designed to|was designed to|the design (?:defines|specifies|requires)|by design|is expected to|are expected to|shall)\b", re.I),
    "RAW": re.compile(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}|\b[A-Z]:\\\\|\bPID\s*\d+|^\s*[\w.-]+\s*[:=]\s*\S+\s+[\w.-]+\s*[:=]", re.I),
    "EXPLANATION": re.compile(r"\b(?:is an? (?:(?:critical|foundational|core|key) )?(?:protocol|service|standard|mechanism|technology|feature|dependency) (?:that|which|used)|in general,|generally,|typically,|industry best practice)\b", re.I),
}

# role -> (rejected kind, verdict, severity hint)
REJECTS = {
    "discovery_information": [("FINDING", "WRONG_SUBSECTION", "MAJOR"), ("POSITION", "WRONG_SUBSECTION", "MAJOR"),
                              ("REQUIREMENT", "WRONG_SUBSECTION", "MAJOR"), ("CONSEQUENCE", "WRONG_SUBSECTION", "MINOR"),
                              ("RAW", "WRONG_SUBSECTION", "MINOR")],
    "observed": [("FINDING", "WRONG_SUBSECTION", "MAJOR"), ("POSITION", "WRONG_SUBSECTION", "MAJOR"),
                 ("REQUIREMENT", "WRONG_SUBSECTION", "MAJOR"), ("CONSEQUENCE", "WRONG_SUBSECTION", "MINOR"),
                 ("RAW", "WRONG_SUBSECTION", "MINOR")],
    "expected": [("FINDING", "WRONG_SUBSECTION", "MAJOR"), ("POSITION", "WRONG_SUBSECTION", "MAJOR"),
                 ("CONSEQUENCE", "WRONG_SUBSECTION", "MINOR"), ("RAW", "WRONG_SUBSECTION", "MAJOR")],
    "findings": [("RAW", "WRONG_SUBSECTION", "MINOR")],
    "drawbridge": [("RAW", "WRONG_SUBSECTION", "MINOR")],
    "operational": [("RAW", "WRONG_SUBSECTION", "MINOR")],
    "assessment": [("RAW", "WRONG_SUBSECTION", "MINOR"), ("REQUIREMENT", "WRONG_SUBSECTION", "MINOR")],
    "requirement_table": [("EXPLANATION", "WRONG_SUBSECTION", "MINOR")],
    "methodology": [("FINDING", "WRONG_SECTION", "MAJOR"), ("POSITION", "WRONG_SECTION", "MAJOR")],
    "discovery_activity": [("FINDING", "WRONG_SECTION", "MINOR"), ("POSITION", "WRONG_SECTION", "MAJOR")],
    "scope": [("POSITION", "WRONG_SECTION", "MAJOR")],
    "migration": [("POSITION", "WRONG_SECTION", "MAJOR"), ("FINDING", "WRONG_SECTION", "MINOR")],
    "glossary": [("RECOMMENDATION", "WRONG_SECTION", "MAJOR")],
}
# a recommendation is only acceptable in Recommendations (legacy) -- or nowhere (template)
REC_OK_ROLES = {"recommendations", "executive", "container"}
REC_SEVERITY = {"discovery_information": "MAJOR", "observed": "MAJOR", "expected": "MAJOR",
                "requirement_table": "MAJOR", "assessment": "MAJOR"}
ROLE_TARGET = {"FINDING": "Findings (or Drawbridge Impact)", "POSITION": "Assessment / Rating cell",
               "REQUIREMENT": "Design and functionality expected (or the requirement table)",
               "CONSEQUENCE": "Drawbridge Impact", "RAW": "Evidence Appendix", "RECOMMENDATION": "Recommendations",
               "EXPLANATION": "remove (general explanation)"}


def kinds_of(text: str) -> list[str]:
    ks = [k for k, rx in KIND_RES.items() if rx.search(text)]
    if "POSITION" in ks and "FINDING" in ks:
        # a rating ("Not Met") is a position; keep FINDING only if other finding wording remains
        if not KIND_RES["FINDING"].search(re.sub(r"\b(?:partially met|not met|met)\b", "", text, flags=re.I)):
            ks.remove("FINDING")
    return ks


# ---------------------------------------------------------------- scan
@dataclass
class Ctx:
    h1: str = ""
    h1_id: str | None = None
    h1_index: int = 0
    headings: list[tuple[int, str, str | None]] = field(default_factory=list)  # (level, title, id)
    template: bool = False


def role_of(ctx: Ctx, unit: Unit) -> str | None:
    for lvl, title, _ in reversed(ctx.headings):
        if lvl == 1:
            break
        for role, rx in ROLE_RES:
            if rx.search(norm(title)):
                return role
    if ctx.template and norm(ctx.h1).startswith("requirement domain") and unit.kind == "table_row":
        if not any(lvl >= 3 for lvl, _, _ in ctx.headings):
            return "requirement_table"
    for lvl, title, _ in reversed(ctx.headings):
        for role, rx in DOC_ROLE_RES:
            if rx.search(norm(title)):
                return role
    return None


def host_domains(ctx: Ctx, domains: list[Domain]) -> list[Domain] | None:
    """Domains this unit's section hosts; None for document-level sections (no topic check)."""
    if ctx.template:
        if not norm(ctx.h1).startswith("requirement domain"):
            return None
        h2 = next((t for lvl, t, _ in ctx.headings if lvl == 2), None)
        d = match_domain_by_title(h2, domains) if h2 else None
        return [d] if d else None
    if any(rx.search(norm(ctx.h1)) for _, rx in DOC_ROLE_RES):
        return None  # document-level section: spans every topic by design
    hosts = legacy_hosts(ctx.h1, domains)
    return hosts or None


def scores(text: str, domains: list[Domain]) -> dict[str, int]:
    return {d.num: len(d.term_re.findall(text)) for d in domains if d.term_re}


def target_for(dnum: str, domains: list[Domain], template: bool, doc_domains: dict[str, str]) -> str:
    d = next(x for x in domains if x.num == dnum)
    if template:
        return doc_domains.get(dnum, f"{d.num} {d.name}")
    host = doc_domains.get(dnum) or " / ".join(d.legacy[:1] or ["(none)"])
    return f"{d.num} {d.name} -> legacy host: {host}"


def scan(units: list[Unit], domains: list[Domain], min_hits: int, margin: int) -> tuple[list[dict], bool]:
    template = any(u.kind == "heading" and u.level == 1 and norm(u.text).startswith("requirement domain") for u in units)
    doc_domains: dict[str, str] = {}
    if template:
        h1 = ""
        for u in units:
            if u.kind == "heading" and u.level == 1:
                h1 = u.text
            elif u.kind == "heading" and u.level == 2 and norm(h1).startswith("requirement domain"):
                d = match_domain_by_title(u.text, domains)
                if d:
                    doc_domains[d.num] = f"{d.num} {u.text} ({u.id})"
    if not template:
        for u in units:
            if u.kind == "heading" and u.level == 1 and u.text:
                for d in legacy_hosts(u.text, domains):
                    doc_domains.setdefault(d.num, f"{u.text} ({u.id})")
    ctx = Ctx(template=template)
    out: list[dict] = []
    h1_count = 0
    seen_role_in_h1 = False
    misplaced: tuple[int, dict] | None = None  # (heading level, its finding)
    for u in units:
        if u.kind == "heading":
            if misplaced and u.level <= misplaced[0]:
                misplaced = None
            if u.level == 1:
                h1_count += 1
                ctx.h1, ctx.h1_id, ctx.h1_index = u.text, u.id, h1_count
                ctx.headings = [(1, u.text, u.id)]
                seen_role_in_h1 = False
            else:
                ctx.headings = [h for h in ctx.headings if h[0] < u.level] + [(u.level, u.text, u.id)]
            u.path = [t for _, t, _ in ctx.headings]
            if u.level == 1 or not u.text:
                continue
            hosts = host_domains(ctx, domains)
            if any(rx.search(norm(u.text)) for _, rx in ROLE_RES):
                seen_role_in_h1 = True
            # a heading naming another domain, inside a domain section
            if hosts:
                other = [d for d in domains if d not in hosts and (
                    similar(u.text, d.name) >= 0.85 or any(norm(u.text) == norm(lh) for lh in d.legacy))]
                if other and not (template and u.level == 2):
                    f = finding(u, ctx, "MISPLACED_HEADING", "MAJOR",
                                f"heading names domain {other[0].num} {other[0].name}, but sits under '{ctx.h1}'",
                                target_for(other[0].num, domains, template, doc_domains))
                    f["units_under"] = 0
                    out.append(f)
                    misplaced = (u.level, f)
                    continue
            if misplaced:
                continue
            # recommendation or migration-planning headings inside a document-level overview section
            h1_role = next((role for role, rx in DOC_ROLE_RES if rx.search(norm(ctx.h1))), None)
            if h1_role in ("architecture", "methodology", "discovery_activity", "scope", "system_overview"):
                if re.search(r"recommendation", u.text, re.I):
                    out.append(finding(u, ctx, "WRONG_SECTION", "MINOR", f"recommendations heading inside '{ctx.h1}'",
                                       "the domain's Recommendations (legacy) or roadmap (template)"))
                elif re.search(r"migrat", u.text, re.I):
                    out.append(finding(u, ctx, "OUT_OF_SCOPE", "MINOR", f"migration-planning heading inside '{ctx.h1}'",
                                       "5 Migration Discovery (template v1.2) or the roadmap"))
            # observation / interpretation heading under "Design and functionality expected"
            parent_roles = [role for lvl, t, _ in ctx.headings[:-1] if lvl > 1 for role, rx in ROLE_RES if rx.search(norm(t))]
            if parent_roles and parent_roles[-1] == "expected" and OBSERVATION_HEADING_RE.search(u.text) \
                    and not ROLE_RES[1][1].search(norm(u.text)):
                out.append(finding(u, ctx, "WRONG_SUBSECTION", "MAJOR",
                                   "observation or interpretation heading under 'Design and functionality expected'",
                                   "Observed Configuration and Functionality / Findings"))
            # legacy: a subheading before the domain's first standard subsection
            if hosts and not template and not seen_role_in_h1 and u.level >= 2:
                out.append(finding(u, ctx, "WRONG_SUBSECTION", "MINOR",
                                   "heading sits before the section's first standard subsection (Expected / Observed / Findings)",
                                   "the standard subsection that carries its content"))
            continue
        u.path = [t for _, t, _ in ctx.headings]
        if ctx.h1_index == 0:
            continue  # cover / before first Heading 1
        if misplaced:
            misplaced[1]["units_under"] += 1
            continue  # the whole block is reported once, on its heading
        role = role_of(ctx, u)
        hosts = host_domains(ctx, domains)
        ks = kinds_of(u.text)
        nwords = len(u.text.split())
        # 1. job checks
        for kind, verdict, sev in REJECTS.get(role or "", []):
            if kind in ks and not (kind == "FINDING" and u.kind == "table_row" and role in ("observed", "discovery_information")
                                   and not re.search(r"not met|partially met|does not meet|single point of failure", u.text, re.I)):
                reason = f"{kind.lower()} wording in '{role}'"
                if kind == "FINDING" and nwords <= 4 and u.text.rstrip().endswith(":"):
                    # a bare lead-in ("This confirms:"); the lines under it may be plain facts
                    sev, reason = "MINOR", "announcing lead-in in '" + str(role) + "': check whether the lines under it interpret or restate facts"
                out.append(finding(u, ctx, verdict, sev, reason, ROLE_TARGET.get(kind, "")))
        if "RECOMMENDATION" in ks and role not in REC_OK_ROLES:
            if template and (hosts or role in ("migration", "requirement_table", "discovery_information", "drawbridge")):
                out.append(finding(u, ctx, "OUT_OF_SCOPE", REC_SEVERITY.get(role or "", "MINOR"),
                                   "recommendation in a template CSA (no Recommendations home)", "roadmap (not this document)"))
            elif not template and hosts and role not in (None,):
                out.append(finding(u, ctx, "WRONG_SUBSECTION", REC_SEVERITY.get(role or "", "MINOR"),
                                   f"recommendation wording in '{role}'", "Recommendations"))
        if role == "container":
            mix = [k for k in ("FINDING", "CONSEQUENCE", "RECOMMENDATION") if k in ks]
            if len(mix) >= 2:
                out.append(finding(u, ctx, "SPLIT", "MINOR", "one unit mixes " + " + ".join(m.lower() for m in mix),
                                   "Findings / Drawbridge Impact / Recommendations"))
        if hosts and "EXPLANATION" in ks and role != "requirement_table":
            out.append(finding(u, ctx, "OUT_OF_SCOPE", "MINOR", "general technology explanation", "remove"))
        # 2. topic check
        port_row = u.kind == "table_row" and re.match(r"^\s*(?:tcp|udp)?\s*\d{2,5}(?:[-/,]\d{2,5})*\s*(?:/\s*(?:tcp|udp))?\s*\|", u.text, re.I)
        if port_row and any(h.num in ("3.6", "3.13") for h in hosts or []):
            pass
        elif hosts and nwords >= 8 and role not in ("evidence_appendix", "drawing"):
            sc = scores(u.text, domains)
            best = max(sc, key=sc.get)
            host_best = max(sc.get(h.num, 0) for h in hosts)
            if best not in [h.num for h in hosts] and sc[best] >= min_hits and sc[best] - host_best >= margin:
                f = finding(u, ctx, "WRONG_SECTION", "MAJOR if only statement, else MINOR",
                            f"signal terms: {best}={sc[best]} vs this section {host_best}",
                            target_for(best, domains, template, doc_domains))
                f["topic_domain"] = best
                out.append(f)
        # remember topic for inbound lookups
        if hosts and nwords >= 8:
            sc = scores(u.text, domains)
            u.__dict__["topic"] = max(sc, key=sc.get) if max(sc.values()) >= min_hits else None
    return out, template


def finding(u: Unit, ctx: Ctx, verdict: str, sev: str, reason: str, target: str) -> dict:
    return {"id": u.id, "unit": u.kind, "section": ctx.h1_index, "path": " > ".join(u.path[1:] if len(u.path) > 1 else u.path),
            "h1": ctx.h1, "verdict": verdict, "severity_hint": sev, "reason": reason, "target": target,
            "excerpt": (u.text[:110] + ("..." if len(u.text) > 110 else ""))}


# ---------------------------------------------------------------- report
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--section", type=int)
    ap.add_argument("--heading")
    ap.add_argument("--domain", help="template CSAs: domain number (3.5) or name inside Requirement Domain Assessments")
    ap.add_argument("--min-hits", type=int, default=2)
    ap.add_argument("--margin", type=int, default=2)
    ap.add_argument("--scope", default=str(SCOPE_MAP), help="section scope map (default: references/section-scope.md)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    path = Path(a.path)
    if not path.exists():
        sys.exit(f"not found: {path}")
    domains = load_scope(Path(a.scope))
    if path.suffix.lower() in (".docx", ".dotx"):
        units, engine = read_docx_units(path)
        id_check = check_ids_against_manifest(path, units)
    else:
        units, engine = read_md_units(path)
        id_check = "markdown input: no stable IDs"
    found, template = scan(units, domains, a.min_hits, a.margin)

    # section selection
    h1s = [(i + 1, u.text) for i, u in enumerate([u for u in units if u.kind == "heading" and u.level == 1])]
    sel_index = None
    if a.heading:
        sel = [i for i, t in h1s if t.strip().lower().startswith(a.heading.strip().lower())]
        if not sel:
            sys.exit(f"no Heading 1 titled '{a.heading}'")
        sel_index = sel[0]
    elif a.section is not None:
        if not any(i == a.section for i, _ in h1s):
            sys.exit(f"no Heading 1 section {a.section}")
        sel_index = a.section
    dom_sel = None
    if a.domain:
        dom_sel = next((d for d in domains if d.num == a.domain), None) or match_domain_by_title(a.domain, domains, 0.6)
        if dom_sel is None:
            sys.exit(f"unknown domain '{a.domain}'")
    chosen = [f for f in found if (sel_index is None or f["section"] == sel_index)
              and (dom_sel is None or norm(f["path"]).startswith(norm(dom_sel.name)[:12]) or dom_sel.name.lower() in f["path"].lower())]

    inbound: list[dict] = []
    if sel_index is not None or dom_sel is not None:
        sel_title = dict(h1s).get(sel_index, "") if sel_index else ""
        sel_domains = {dom_sel.num} if dom_sel else {d.num for d in legacy_hosts(sel_title, domains)}
        inbound = [f for f in found if f["verdict"] == "WRONG_SECTION" and f.get("topic_domain") in sel_domains
                   and f not in chosen]

    report = {"file": str(path), "reader": engine, "structure": "template" if template else "legacy",
              "stable_ids": id_check, "scope_map": a.scope, "candidates": chosen, "inbound": inbound,
              "counts": {}}
    for f in chosen:
        report["counts"][f["verdict"]] = report["counts"].get(f["verdict"], 0) + 1
    if a.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{path.name}  structure: {report['structure']}  reader: {engine}")
        print(f"stable IDs: {id_check}")
        print("candidates: " + (", ".join(f"{k} {v}" for k, v in sorted(report['counts'].items())) or "none"))
        cur = None
        for f in chosen:
            if f["h1"] != cur:
                cur = f["h1"]
                print(f"\n[Section {f['section']}] {cur}")
            print(f"  {f['id'] or '-':<18} {f['verdict']:<17} {f['severity_hint']:<10} {f['path'][:70]}")
            under = f" ({f['units_under']} paragraphs/rows under it)" if "units_under" in f else ""
            print(f"      {f['reason']}{under}  ->  {f['target']}")
            print(f"      \"{f['excerpt']}\"")
        if inbound:
            print("\nINBOUND (elsewhere, but signal terms point here):")
            for f in inbound:
                print(f"  {f['id'] or '-':<18} [S{f['section']}] {f['path'][:70]}")
                print(f"      {f['reason']}  \"{f['excerpt']}\"")
        print("\nCandidates only: confirm each against references/section-scope.md before reporting it.")
    if a.strict and any(f["severity_hint"].startswith("MAJOR") for f in chosen):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
