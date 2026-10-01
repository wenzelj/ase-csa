"""`convertOldTemplateToNew`: move one subsection of an old-format CSA into the CSA template.

Runs the stages in order: brief, evidence pre-pass, evidence agent, writer agent, ledger. The framework
stages run here; the two agent stages are passed in as `run_agent(verb, args) -> return code` so the
CLI can launch the agents and tests can use stubs. Without `run_agent` they come back PENDING with the
commands to run.

    python3 -m csa_docx.convert --workspace <root> --legacy-docx <path> (--prepare | --status | --section 3.4 [--stage brief])
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from csa_docx import (answer_plan, check_section, convert_brief, convert_evidence, convert_ledger,
                      discovery_required, gap_lookup, legacy_extract, legacy_facts, legacy_map, requirement_assign,
                      requirement_audit, section_file)

STAGES = ("brief", "prepass", "evidence", "plan-check", "write", "ledger")

COVERAGE_SCRIPT = (Path(__file__).resolve().parents[2] / "skills" / "csa-discovery-index"
                   / "scripts" / "coverage_section.py")
_COVERAGE_NOT_USED = "coverage table is generated from the discovery index"


def _work(workspace: Path) -> Path:
    return Path(workspace) / "csa-work"


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def prepare(workspace: Path, legacy_docx: Path) -> dict:
    """Extract and map the old document under csa-work/legacy/. Never writes outside csa-work."""
    legacy_docx = Path(legacy_docx)
    if not legacy_docx.is_file():
        return {"status": "ERROR", "message": f"legacy document not found: {legacy_docx}"}
    work = _work(workspace)
    legacy = work / "legacy"
    try:
        blocks = legacy_extract.extract(legacy_docx)
    except Exception as e:  # bad zip, missing part, bad XML
        return {"status": "ERROR", "message": f"cannot read {legacy_docx.name}: {e}"}
    extract = legacy_extract.write(blocks, legacy)
    rows = legacy_map.map_blocks(
        blocks,
        project_rules=legacy_map.load_rules(legacy / "legacy-map.csv"),
        moved=legacy_map.load_moved(legacy / "moved.csv"),
    )
    mapped = legacy_map.write_map(rows, legacy)
    facts = legacy_facts.split(blocks, rows)
    legacy_facts.write(facts, legacy)
    assigned = requirement_assign.write(
        requirement_assign.cluster(requirement_assign.assign(facts, requirement_assign.load_requirements())), legacy)
    audit = requirement_audit.audit(work)
    parked = convert_ledger.write_parked(work)
    figures = convert_ledger.write_figures(work)
    return {"status": "OK", "extract": extract, "map": mapped, "facts": assigned, "audit": audit,
            "parked": parked["parked"], "figures": figures["figures"]}


def _brief_files(work: Path, section: str) -> list[str]:
    found = sorted((work / "convert" / section).glob("brief*.md"),
                   key=lambda p: (0, 0) if p.name == "brief.md"
                   else (1, int(re.sub(r"\D", "", p.stem) or 0)))
    if found:
        return [str(p) for p in found]
    return convert_brief.build_brief(work, section).get("files", [])


def _agent_stage(verb: str, args: list[str], run_agent) -> dict:
    command = "csa " + verb + " " + " ".join(args)
    if run_agent is None:
        return {"status": "PENDING", "commands": [command]}
    rc = run_agent(verb, args)
    return {"status": "FAILED" if rc else "OK", "returncode": rc or 0, "commands": [command]}


def _read_blocks(work: Path) -> dict[str, dict]:
    return convert_ledger._read_blocks(work)


def glossary_section(workspace: Path, legacy_docx: Path) -> dict:
    """Merge the old glossary terms into a `glossary` section file (no LLM)."""
    workspace = Path(workspace)
    work = _work(workspace)
    convert_evidence.prepass(workspace, "7", legacy_docx=Path(legacy_docx))
    blocks = _read_blocks(work)
    matrix = _read_csv(work / "evidence-matrix.csv")

    def evidence_id(lid: str) -> str:
        for m in matrix:
            if re.search(rf"legacy {re.escape(lid)}(?!\d)", m.get("gap_or_action") or "") \
                    and (m.get("status") or "").upper() == "VERIFIED":
                return m["evidence_id"]
        return ""

    out = work / "sections" / "7-glossary-and-acronyms.md"
    existing: set[str] = set()
    if out.is_file():
        try:
            parsed = section_file.parse_section_file(out)
            existing = {cells[0].strip().lower() for cells in parsed.get("tables", {}).get("Terms", []) if cells}
        except ValueError:
            existing = set()

    seen = set(existing)
    terms: list[tuple[str, str, str]] = []
    for r in _read_csv(work / "legacy" / "map.csv"):
        b = blocks.get(r["id"])
        if r.get("target") != "7" or r.get("job") not in ("convert", "context") or not b or b["kind"] != "table_row":
            continue
        cells = [c.strip() for c in (b.get("cells") or []) if c.strip()]
        if len(cells) < 2 or cells[0].lower() in seen:
            continue
        seen.add(cells[0].lower())
        terms.append((cells[0], cells[1], evidence_id(r["id"])))

    if not terms:
        return {"status": "OK", "file": str(out), "terms": 0, "findings": []}

    old = []
    if out.is_file():
        parsed = section_file.parse_section_file(out)
        ev = parsed.get("evidence", {})
        for n, cells in enumerate(parsed.get("tables", {}).get("Terms", []), start=1):
            old.append((cells[0], cells[1] if len(cells) > 1 else "", (ev.get(f"Terms {n}") or [""])[0]))
    rows = old + terms
    lines = ["---", "block: glossary", "heading: Glossary and Acronyms", "status: draft", "---", "",
             "## Terms", "", "| Term | Definition |", "| --- | --- |"]
    lines += [f"| {t.replace('|', '/')} | {d.replace('|', '/')} |" for t, d, _ in rows]
    lines += ["", "## Evidence", "", "| Statement | Evidence |", "| --- | --- |"]
    lines += [f"| Terms {n} | {e} |" for n, (_, _, e) in enumerate(rows, start=1) if e]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    res = check_section.check(out, workspace=str(workspace), lint=False)
    return {"status": "ERROR" if res.get("errors") else "OK", "file": str(out),
            "terms": len(terms), "findings": res.get("findings", [])}


def coverage_file(workspace: Path) -> dict:
    """Write the 5.1 Discovery Coverage section file from the discovery index (no LLM)."""
    workspace = Path(workspace)
    out = _work(workspace) / "sections" / "5.1-discovery-coverage.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([sys.executable, str(COVERAGE_SCRIPT), "--workspace", str(workspace), "--out", str(out)],
                          capture_output=True, text=True)
    if proc.returncode != 0 or not out.is_file():
        return {"status": "ERROR", "message": (proc.stderr or proc.stdout).strip()[-400:] or "coverage_section failed"}
    return {"status": "OK", "file": str(out)}


def _document_target(section: str, workspace: Path, legacy_docx: Path, stage: str | None) -> dict:
    """Targets 7 (glossary) and 5.1 (coverage) need no agents."""
    work = _work(workspace)
    wanted = STAGES if stage is None else (stage,)
    stages: dict[str, dict] = {}
    placed: dict | None = None

    def result(status: str, **extra) -> dict:
        return {"status": status, "section": section, "stages": stages, **extra}

    for name in wanted:
        if name == "brief":
            res = convert_brief.build_brief(work, section)
            stages[name] = res
            if res["status"] == "EMPTY" and section == "7":
                return result("EMPTY")
        elif name == "write":
            res = glossary_section(workspace, legacy_docx) if section == "7" else coverage_file(workspace)
            stages[name] = res
            if res["status"] == "ERROR":
                return result("ERROR", stage=name, message=res.get("message", ""))
            placed = res
            stages[name] = {**res, "status": "PLACE"}
        elif name == "ledger":
            if section == "5.1":
                mapped = [r for r in _read_csv(work / "legacy" / "map.csv")
                          if r.get("target") == "5.1" and r.get("job") in ("convert", "context")]
                out_dir = work / "convert" / "5.1"
                out_dir.mkdir(parents=True, exist_ok=True)
                with (out_dir / "outcomes.csv").open("w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    w.writerow(["id", "outcome", "target", "reason"])
                    w.writerows([r["id"], "NOT_USED", "", _COVERAGE_NOT_USED] for r in mapped)
            stages[name] = convert_ledger.build_ledger(work, section)
        # prepass and evidence are done by glossary_section or not needed
    if placed is not None:
        return result("PLACE", file=placed["file"])
    return result("OK")


def _requirement_mode(work: Path, section: str) -> bool:
    """True when the section is a 3.x domain and the facts carry requirement IDs (csa convert --prepare)."""
    path = work / "legacy" / "facts.jsonl"
    if not path.is_file() or not requirement_assign.load_requirements():
        return False
    if not any(r["domain"] == section for r in requirement_assign.load_requirements()):
        return False
    with path.open(encoding="utf-8") as fh:
        first = fh.readline()
    return '"req_ids"' in first


def _plan_gaps(work: Path) -> bool:
    return any(answer_plan.gaps(answer_plan.load(p)) for p in (work / "convert").glob("*/answer-plan.csv"))


def _plan_check(workspace: Path, section: str, legacy_docx: Path | None = None) -> dict:
    work = _work(workspace)
    plan = work / "convert" / section / "answer-plan.csv"
    if not plan.is_file():
        return {"status": "MISSING", "message": f"the evidence agent did not write {plan}"}
    rows = answer_plan.load(plan)
    findings = answer_plan.validate(rows, section, answer_plan.requirement_ids(section))
    # A gap is only a gap when the evidence matrix and the discovery index do not answer it.
    exclude = (Path(legacy_docx).name,) if legacy_docx else ()
    checked: set[str] = set()
    for n, g in enumerate(rows, start=1):
        m = re.fullmatch(r"(DR-[A-Z]+-\d{2}) (.+)", g["gap_generated"].strip(), re.S)
        if not m or m.group(1) in checked:
            continue
        checked.add(m.group(1))
        look = gap_lookup.lookup_gap(workspace, m.group(1), m.group(2), exclude=exclude)
        if look["verdict"] != "NOT_FOUND":
            findings.append({"level": "ERROR", "code": "GAP_HAS_EVIDENCE", "row": n, "message": (
                f"{m.group(1)}: the evidence already holds {', '.join(look['evidence_ids'])}. Read them: if one answers it, "
                "restate the row with that evidence; if none does, reject each with `evidence_matrix.py review --state "
                "rejected` and rerun")})
    if not (work / "convert" / section / "search-notes.md").is_file():
        findings.append({"level": "WARNING", "code": "NO_SEARCH_NOTES", "message": (
            "the evidence agent left no convert/%s/search-notes.md; the writer will repeat its searches" % section)})
    errors = [f for f in findings if f["level"] == "ERROR"]
    return {"status": "ERROR" if errors else "OK", "errors": len(errors),
            "warnings": len(findings) - len(errors), "findings": findings}


def convertOldTemplateToNew(section: str, *, workspace: Path, legacy_docx: Path,
                            stage: str | None = None, run_agent=None) -> dict:
    workspace = Path(workspace)
    work = _work(workspace)
    if stage is not None and stage not in STAGES:
        return {"status": "ERROR", "message": f"unknown stage {stage!r}; use one of {', '.join(STAGES)}"}
    if not (work / "legacy" / "map.csv").is_file():
        return {"status": "ERROR", "message": "run csa convert --prepare first"}

    if section in ("7", "5.1"):
        return _document_target(section, workspace, Path(legacy_docx), stage)

    wanted = STAGES if stage is None else (stage,)
    stages: dict[str, dict] = {}
    pending = False
    timing: dict[str, float] = {}

    def timed(key: str, fn):
        """Run an agent stage and record its wall time in convert/<N>/timing.json."""
        start = time.perf_counter()
        out = fn()
        if run_agent is not None:
            timing[key] = round(time.perf_counter() - start, 1)
            path = work / "convert" / section / "timing.json"
            try:
                old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            except ValueError:
                old = {}
            old.update(timing)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
        return out

    def result(status: str, **extra) -> dict:
        return {"status": status, "section": section, "stages": stages, **extra}

    for name in wanted:
        if name == "brief":
            res = convert_brief.build_brief(work, section)
            stages[name] = res
            if res["status"] == "EMPTY":
                return result("EMPTY")
        elif name == "prepass":
            res = convert_evidence.prepass(workspace, section, legacy_docx=Path(legacy_docx))
            stages[name] = res
            if res.get("status") == "ERROR":
                return result("ERROR", stage=name, message=res.get("message", ""))
        elif name == "evidence":
            files = _brief_files(work, section)
            if not files:
                return result("EMPTY")
            runs = timed("evidence_s", lambda: [
                _agent_stage("evidence", [section, "MODE=convert", f"BRIEF={f}"], run_agent) for f in files])
            failed = next((r for r in runs if r["status"] == "FAILED"), None)
            stages[name] = failed or {
                "status": "PENDING" if run_agent is None else "OK",
                "commands": [c for r in runs for c in r["commands"]]}
            if failed:
                return result("FAILED", stage=name)
            pending |= run_agent is None
        elif name == "plan-check":
            if pending:
                continue
            if not _requirement_mode(work, section):
                stages[name] = {"status": "SKIPPED", "message": "no requirement-led brief for this target"}
                continue
            res = _plan_check(workspace, section, legacy_docx)
            stages[name] = res
            if res["status"] != "OK":
                return result("FAILED", stage=name, message=res.get("message", ""),
                              findings=[f for f in res.get("findings", []) if f["level"] == "ERROR"])
        elif name == "write":
            files = _brief_files(work, section)
            if not files:
                return result("EMPTY")
            res = timed("write_s", lambda: _agent_stage("write", [section, "BRIEF=" + ";".join(files)], run_agent))
            stages[name] = res
            if res["status"] == "FAILED":
                return result("FAILED", stage=name)
            pending |= run_agent is None
        elif name == "ledger":
            if pending:
                continue
            res = convert_ledger.build_ledger(work, section)
            stages[name] = res
            if stage in (None, "ledger") and _plan_gaps(work):
                stages["discovery-required"] = discovery_required.build(workspace, Path(legacy_docx))
            return result("OK" if res["status"] == "COMPLETE" else "INCOMPLETE")

    if pending:
        return result("PENDING")
    return result("OK")


def status(workspace: Path) -> list[dict]:
    work = _work(workspace)
    by_target: dict[str, list[str]] = {}
    for r in _read_csv(work / "legacy" / "map.csv"):
        if r.get("target") and r.get("job") in ("convert", "context"):
            by_target.setdefault(r["target"], []).append(r["id"])
    rows = _read_csv(work / "evidence-matrix.csv")

    out = []
    for target in sorted(by_target, key=lambda t: [int(p) for p in t.split(".")]):
        ids = by_target[target]
        evidence = sum(1 for m in rows if any(
            re.search(rf"legacy {re.escape(i)}(?!\d)", m.get("gap_or_action") or "") for i in ids))
        parsed = convert_ledger._find_section_file(work, convert_ledger._target_heading(target))
        ledger_rows = _read_csv(work / "convert" / target / "ledger.csv")
        if not ledger_rows:
            ledger = ""
        else:
            open_outcomes = ("MISSING", "REQ_INCOMPLETE", "FACT_UNACCOUNTED")
            ledger = "INCOMPLETE" if any(r["outcome"] in open_outcomes for r in ledger_rows) else "COMPLETE"
        req_rows = [r for r in ledger_rows if r.get("kind") == "requirement"]
        plan = work / "convert" / target / "answer-plan.csv"
        dr_items = len({g["dr_id"] for g in answer_plan.gaps(answer_plan.load(plan))}) if plan.is_file() else 0
        out.append({"target": target, "blocks": len(ids), "evidence_rows": evidence,
                    "brief": (work / "convert" / target / "brief.md").is_file(),
                    "section_file": parsed.get("status", "") if parsed else "",
                    "ledger": ledger,
                    "requirements": f"{sum(r['outcome'] == 'ANSWERED' for r in req_rows)}/{len(req_rows)}" if req_rows else "",
                    "dr_items": dr_items})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert an old-format CSA into the template, one subsection at a time.")
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--legacy-docx", type=Path)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prepare", action="store_true")
    g.add_argument("--status", action="store_true")
    g.add_argument("--section")
    ap.add_argument("--stage", choices=STAGES)
    a = ap.parse_args(argv)

    if a.status:
        print(json.dumps(status(a.workspace), ensure_ascii=False))
        return 0
    if a.legacy_docx is None:
        print(json.dumps({"status": "ERROR", "message": "--legacy-docx is required"}))
        return 2
    if a.prepare:
        res = prepare(a.workspace, a.legacy_docx)
    else:
        res = convertOldTemplateToNew(a.section, workspace=a.workspace, legacy_docx=a.legacy_docx, stage=a.stage)
    print(json.dumps(res, ensure_ascii=False))
    return 2 if res.get("status") in ("ERROR", "FAILED") else 0


if __name__ == "__main__":
    sys.exit(main())
