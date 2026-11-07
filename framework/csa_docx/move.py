"""`csa move`: copy the old-format content mapped to one subsection into the CSA template.

Moving is copy-and-reshape, not a change process (``.agents/docs/move-old-template-plan.md``). One
subsection runs four stages: ``brief`` (framework), ``write`` (one writer agent, ``MODE=move``),
``insert`` (check the structure, place the section file as plain text) and ``record`` (moved.csv,
open-items.csv, the parked list). No facts, requirement assignment, evidence or ratings.

The agent stage is passed in as ``run_agent(verb, args) -> return code`` so the CLI can launch the
agent and tests can use a stub. Without ``run_agent`` it comes back PENDING with the command to run.

    python3 -m csa_docx.move --workspace <root> --legacy-docx <path> (--prepare | --order | --section 3.4 [--stage brief])
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from csa_docx import (build, check_section, convert, convert_brief, convert_ledger, legacy_extract, legacy_map,
                      move_record, section_file)

STAGES = ("brief", "write", "insert", "record")
#: Targets that need no writer agent: the existing generators write their section files.
GENERATED = ("7", "5.1")


def _work(workspace: Path) -> Path:
    return Path(workspace) / "csa-work"


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _key(target: str) -> tuple:
    try:
        return tuple(int(p) for p in target.split("."))
    except ValueError:
        return (10**6, target)


def move_prepare(workspace: Path, legacy_docx: Path) -> dict:
    """Extract and map the old document under csa-work/legacy/. No facts, no requirement assignment, no audit."""
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
    parked = convert_ledger.write_parked(work)
    figures = convert_ledger.write_figures(work)
    return {"status": "OK", "extract": extract, "map": mapped, "parked": parked["parked"],
            "figures": figures["figures"]}


def order(workspace: Path) -> list[str]:
    """Mapped targets in run order: 3.1-3.17, 5.2-5.6, 7, 5.1, then 8, then 2.1 last.
    Only targets with convert/context blocks; 8 is included when open-items.csv has rows."""
    work = _work(workspace)
    mapped = {r["target"] for r in _read_csv(work / "legacy" / "map.csv")
              if r.get("target") and r.get("job") in ("convert", "context")}
    if _read_csv(work / "move" / "open-items.csv"):
        mapped.add("8")

    def rank(t: str) -> tuple:
        if t == "2.1":
            return (9, _key(t))
        if t == "8":
            return (8, _key(t))
        if t == "5.1":
            return (7, _key(t))
        if t == "7":
            return (6, _key(t))
        return (3 if t.startswith("3.") else 5, _key(t))

    return sorted(mapped, key=rank)


def _brief(work: Path, section: str) -> dict:
    """Block-mode brief copied to csa-work/move/<section>/. Block mode is forced: a project that ran
    `csa convert --prepare` has facts, which a move must not use."""
    res = convert_brief.build_brief(work, section, block_mode=True)
    if res["status"] == "EMPTY":
        return {"status": "EMPTY"}
    out_dir = work / "move" / section
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("brief*.md"):
        old.unlink()
    files = []
    for f in res["files"]:
        dest = out_dir / Path(f).name
        shutil.copy2(f, dest)
        files.append(str(dest))
    return {"status": "OK", "files": files, "blocks": res["blocks"]}


def _brief_files(work: Path, section: str) -> list[str]:
    out_dir = work / "move" / section
    return [str(p) for p in sorted(out_dir.glob("brief*.md"),
                                   key=lambda p: (0, 0) if p.name == "brief.md"
                                   else (1, int(re.sub(r"\D", "", p.stem) or 0)))]


def _system_name(workspace: Path, system_name: str | None) -> str | None:
    if system_name:
        return system_name
    fv = Path(workspace) / "01 Current State AS Built" / "01 Final Version"
    docs = [d for d in fv.glob("Current State Assessment - *.docx") if not d.name.startswith("~$")]
    return re.match(r"Current State Assessment - (.+)\.docx$", docs[0].name)[1] if len(docs) == 1 else None


def _mark_built(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = re.sub(r"^status:.*$", "status: built", text, count=1, flags=re.M)
    if re.search(r"^placed:.*$", text, re.M):
        text = re.sub(r"^placed:.*$", f"placed: {stamp}", text, count=1, flags=re.M)
    else:
        text = re.sub(r"^status: built$", f"status: built\nplaced: {stamp}", text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")


def _insert(workspace: Path, section: str, system_name: str | None) -> dict:
    """Check the section file (move mode) and place it into the working document as plain text."""
    work = _work(workspace)
    path = move_record._find_section_file(work, section)
    if path is None:
        return {"status": "ERROR", "message": f"no section file for {section} in {work / 'sections'}"}
    chk = check_section.check(path, lint=True)
    errors = [f for f in chk["findings"] if f["level"] == "ERROR"]
    warnings = [f for f in chk["findings"] if f["level"] != "ERROR"]
    if errors:
        return {"status": "FAILED", "file": str(path), "findings": errors, "warnings": warnings,
                "message": f"{path.name} has {len(errors)} structure error(s)"}
    name = _system_name(workspace, system_name)
    if not name:
        return {"status": "ERROR", "message": "no working document to name the system; pass system_name"}
    try:
        blocked = build.plain_blocker(workspace, path, system_name=name)
        if blocked:
            return {"status": "FAILED", "file": str(path), "message": blocked}
        prep = build.place_prepare(workspace, path, system_name=name, source=path.name)
        build.place_apply(workspace, prep["sections"], system_name=name, docx=prep["docx"],
                          change_files=prep["change_files"], plain=True, new_edits=prep["new_edits"],
                          new_files=prep["new_files"])
    except (RuntimeError, ValueError) as e:
        return {"status": "FAILED", "file": str(path), "message": str(e), "warnings": warnings}
    _mark_built(path)
    return {"status": "OK", "file": str(path), "docx": prep["docx"], "warnings": warnings}


def _generate(workspace: Path, section: str, legacy_docx: Path | None) -> dict:
    if section == "7":
        if legacy_docx is None:
            return {"status": "ERROR", "message": "the glossary needs legacy_docx"}
        return convert.glossary_section(workspace, legacy_docx)
    return convert.coverage_file(workspace)


def move(section: str, *, workspace: Path, legacy_docx: Path | None = None, stage: str | None = None,
         run_agent=None, system_name: str | None = None) -> dict:
    workspace = Path(workspace)
    work = _work(workspace)
    section = str(section)
    if stage is not None and stage not in STAGES:
        return {"status": "ERROR", "message": f"unknown stage {stage!r}; use one of {', '.join(STAGES)}"}
    if not (work / "legacy" / "map.csv").is_file():
        return {"status": "ERROR", "message": "run csa move --prepare first"}

    wanted = STAGES if stage is None else (stage,)
    stages: dict[str, dict] = {}
    pending = False

    def result(status: str, **extra) -> dict:
        return {"status": status, "section": section, "stages": stages, **extra}

    for name in wanted:
        if name == "brief":
            if section in GENERATED:
                stages[name] = {"status": "SKIPPED", "message": "generated without a brief"}
                continue
            res = _brief(work, section)
            stages[name] = res
            if res["status"] == "EMPTY":
                return result("EMPTY")
        elif name == "write":
            if section in GENERATED:
                res = _generate(workspace, section, Path(legacy_docx) if legacy_docx else None)
                stages[name] = res
                if res["status"] == "ERROR":
                    return result("ERROR", stage=name, message=res.get("message", ""))
                continue
            files = _brief_files(work, section)
            if not files:
                return result("EMPTY")
            args = [section, "MODE=move", "BRIEF=" + ";".join(files)]
            command = "csa write " + " ".join(args)
            if run_agent is None:
                stages[name] = {"status": "PENDING", "commands": [command]}
                pending = True
                continue
            rc = run_agent("write", args)
            stages[name] = {"status": "FAILED" if rc else "OK", "returncode": rc or 0, "commands": [command]}
            if rc:
                return result("FAILED", stage=name)
        elif name == "insert":
            if pending:
                continue
            res = _insert(workspace, section, system_name)
            stages[name] = res
            if res["status"] != "OK":
                return result("ERROR" if res["status"] == "ERROR" else "FAILED", stage=name,
                              message=res.get("message", ""))
        elif name == "record":
            if pending:
                continue
            res = move_record.record(workspace, section)
            stages[name] = res
            if res["status"] != "OK":
                return result("ERROR", stage=name, message=res.get("message", ""))
    return result("PENDING" if pending else "OK")


def status(workspace: Path) -> list[dict]:
    """One row per mapped target, in run order: blocks, section file status, placed stamp, open items."""
    work = _work(workspace)
    by_target: dict[str, int] = {}
    for r in _read_csv(work / "legacy" / "map.csv"):
        if r.get("target") and r.get("job") in ("convert", "context"):
            by_target[r["target"]] = by_target.get(r["target"], 0) + 1
    open_items = _read_csv(work / "move" / "open-items.csv")
    out = []
    for target in order(workspace):
        path = move_record._find_section_file(work, target)
        meta = section_file.parse_section_file(path)["meta"] if path else {}
        out.append({"target": target,
                    "blocks": len(open_items) if target == "8" else by_target.get(target, 0),
                    "section_file": meta.get("status", ""), "placed": meta.get("placed", ""),
                    "open_items": sum(1 for r in open_items if r["section"] == target)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Move an old-format CSA into the template, one subsection at a time.")
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--legacy-docx", type=Path)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prepare", action="store_true")
    g.add_argument("--order", action="store_true")
    g.add_argument("--status", action="store_true")
    g.add_argument("--section")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--system-name")
    a = ap.parse_args(argv)
    if a.prepare:
        if not a.legacy_docx:
            ap.error("--prepare needs --legacy-docx")
        res = move_prepare(a.workspace, a.legacy_docx)
    elif a.order:
        res = order(a.workspace)
    elif a.status:
        res = status(a.workspace)
    else:
        res = move(a.section, workspace=a.workspace, legacy_docx=a.legacy_docx, stage=a.stage,
                   system_name=a.system_name)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 2 if isinstance(res, dict) and res.get("status") in ("ERROR", "FAILED") else 0


if __name__ == "__main__":
    sys.exit(main())
