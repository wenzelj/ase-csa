#!/usr/bin/env python3
"""Public IP egress analysis for a CSA project (Vantage/Nozomi export files).

Part of the network-connectivity-analysis skill (see ../SKILL.md). Scoped by
PROJECT the same way graph_store.py / build_diagram_model.py are, so the
csa-technical-analyst-agent can run it for any registered project -- not
project-local tooling. First promoted from a one-off UTC/DTC investigation
(2026-09-23, E-056); the file-format assumptions below (Vantage/Nozomi
export shape) are specific to whichever monitoring tool a project actually
uses, so a project without matching files simply gets 0 files scanned, not
an error -- see SKILL.md for what to do when a project's export format
differs.

What it does:
  1. Resolves PROJECT via PROJECTS.yaml (required, never inferred).
  2. Scans <default_source_set>/ (top level only) for Vantage/Nozomi export
     files: export_query_*.xlsx, export_query_*.csv, nozomi_logs*.xlsx.
  3. For each file, extracts public-internet destination/source IPs using
     to_zone/from_zone == 'Internet' (new-format files) or is_to_public /
     is_from_public (older-format files).
  4. Diffs the combined set against a running baseline file
     (<work_dir>/analysis/public-egress-baseline.json), so re-running after
     new export files land only reports genuinely new destinations.
  5. Prints a summary. With --write-evidence-row, writes a ready-to-review
     evidence_matrix.py --rows-file JSON to stdout or a file -- it does NOT
     call evidence_matrix.py append itself. Appending is a separate,
     deliberate step (see the command printed at the end) so a human/agent
     reviews the row before it becomes evidence.
  6. With --commit-baseline, updates the baseline file. Without it, this is
     a dry run: nothing on disk changes except what --output writes.

This script does not classify intent (SaaS/telemetry vs inadvertent egress)
-- that judgment call is out of scope on purpose, same as the manual run.
"""
import argparse
import glob
import ipaddress
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

EXPORT_GLOBS = ["export_query_*.xlsx", "export_query_*.csv", "nozomi_logs*.xlsx"]


def fail(msg, **extra):
    print(json.dumps({"status": "ERROR", "message": msg, **extra}, indent=2))
    sys.exit(2)


def load_project_registry():
    registry_path = Path(__file__).resolve()
    for parent in registry_path.parents:
        candidate = parent / ".agents" / "csa-context" / "PROJECTS.yaml"
        if candidate.exists():
            return _parse_projects_yaml(candidate)
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / ".agents" / "csa-context" / "PROJECTS.yaml"
        if candidate.exists():
            return _parse_projects_yaml(candidate)
    return []


def _parse_projects_yaml(path):
    projects, current = [], {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not line.startswith(" "):
            continue
        if stripped.startswith("- key:"):
            if current:
                projects.append(current)
            current = {}
            stripped = stripped[2:]
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current[key.strip()] = value.strip().strip('"').strip("'")
    if current:
        projects.append(current)
    return projects


def resolve_project(key):
    for p in load_project_registry():
        if p.get("key") == key:
            return p
    fail(f"UNKNOWN_PROJECT: {key!r} not in PROJECTS.yaml",
         known_projects=[p.get("key") for p in load_project_registry()])


def is_public_ip(ip):
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def extract_public_ips(df):
    ips = set()
    if "to_zone" in df.columns and "to" in df.columns:
        ips |= set(df.loc[df["to_zone"] == "Internet", "to"].dropna().unique())
    if "from_zone" in df.columns and "from" in df.columns:
        ips |= set(df.loc[df["from_zone"] == "Internet", "from"].dropna().unique())
    if "is_to_public" in df.columns and "to" in df.columns and "to_zone" not in df.columns:
        ips |= set(df.loc[df["is_to_public"] == True, "to"].dropna().unique())  # noqa: E712
    if "is_from_public" in df.columns and "from" in df.columns and "from_zone" not in df.columns:
        ips |= set(df.loc[df["is_from_public"] == True, "from"].dropna().unique())  # noqa: E712
    return {ip for ip in ips if is_public_ip(str(ip))}


def scan_source_dir(source_dir):
    per_file = {}
    for pattern in EXPORT_GLOBS:
        for path in sorted(glob.glob(os.path.join(source_dir, pattern))):
            fn = os.path.basename(path)
            try:
                df = pd.read_csv(path) if fn.lower().endswith(".csv") else pd.read_excel(path)
            except Exception as e:  # noqa: BLE001
                per_file[fn] = {"error": str(e)}
                continue
            per_file[fn] = {"public_ips": sorted(extract_public_ips(df)), "rows": len(df)}
    return per_file


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="PROJECT key from PROJECTS.yaml, e.g. utcdtc")
    ap.add_argument("--commit-baseline", action="store_true",
                     help="Write newly-found IPs into the baseline file. Without this, dry run only.")
    ap.add_argument("--write-evidence-row", metavar="PATH",
                     help="If new IPs are found, write an evidence_matrix.py --rows-file JSON here "
                          "(pass '-' for stdout). Never calls evidence_matrix.py itself.")
    ap.add_argument("--agent-context", default="", help="Free text describing this run, folded into the row's claim.")
    args = ap.parse_args()

    project = resolve_project(args.project)
    source_dir = project.get("default_source_set")
    work_dir = Path(project.get("work_dir"))
    if not source_dir or not os.path.isdir(source_dir):
        fail("SOURCE_DIR_NOT_FOUND", source_dir=source_dir)

    baseline_path = work_dir / "analysis" / "public-egress-baseline.json"
    baseline = set()
    if baseline_path.exists():
        baseline = set(json.loads(baseline_path.read_text(encoding="utf-8")).get("public_ips", []))

    per_file = scan_source_dir(source_dir)
    all_ips = set()
    for fn, result in per_file.items():
        all_ips |= set(result.get("public_ips", []))

    new_ips = sorted(all_ips - baseline)
    result = {
        "status": "OK",
        "project": args.project,
        "source_dir": source_dir,
        "files_scanned": {fn: (r.get("error") or len(r.get("public_ips", []))) for fn, r in per_file.items()},
        "baseline_count": len(baseline),
        "total_public_ips_now": len(all_ips),
        "new_ips": new_ips,
        "baseline_committed": False,
    }

    if args.commit_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps({"public_ips": sorted(all_ips)}, indent=2), encoding="utf-8")
        result["baseline_committed"] = True
        result["baseline_path"] = str(baseline_path)

    print(json.dumps(result, indent=2))

    if args.write_evidence_row:
        if not new_ips:
            print(json.dumps({"status": "SKIPPED", "reason": "no new public IPs found"}))
            return
        files_named = ", ".join(sorted(per_file.keys()))
        row = [{
            "csa_area": "security_posture",
            "question": "Which public IP egress destinations from OT VLANs are new since the last baseline, "
                         "and are they intentional or inadvertent?",
            "claim": f"Scanning {len(per_file)} Vantage/Nozomi export file(s) in {source_dir} "
                     f"({files_named}) found {len(new_ips)} public IP destination(s) not in the "
                     f"previous baseline of {len(baseline)}: {', '.join(new_ips)}. "
                     f"{args.agent_context}".strip(),
            "status": "VERIFIED",
            "source_title": f"Vantage/Nozomi export files: {files_named}",
            "section": "Security Services / RA - public IP egress (automated baseline diff)",
            "page_or_location": source_dir,
            "evidence_excerpt": f"to_zone/from_zone=='Internet' filter, {len(all_ips)} total public IPs "
                                 f"now known, {len(new_ips)} new vs baseline_count={len(baseline)}.",
            "confidence": "medium",
            "gap_or_action": "Intent classification (intentional vs inadvertent) not performed by this "
                              "script -- needs Network SME review, same as prior egress findings.",
            "review_state": "pending",
        }]
        payload = json.dumps(row, indent=2)
        if args.write_evidence_row == "-":
            print(payload)
        else:
            Path(args.write_evidence_row).write_text(payload, encoding="utf-8")
            print(json.dumps({"status": "WROTE_ROW_FILE", "path": args.write_evidence_row}))


if __name__ == "__main__":
    main()
