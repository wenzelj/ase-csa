"""Measure what each registry agent loads before it starts (`csa budget`).

An agent's start-up load is its own definition file, the shared core rules and
every file listed under its ``## Required reading`` heading. Tokens are
estimated as ceil(characters / 4). Standard library only.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

CORE_RULES = ".agents/csa-core-rules.md"
_ENTRY_RE = re.compile(r"^\s*-\s+(\w+):\s*(.*?)\s*$")
_FIELD_RE = re.compile(r"^\s+(\w+):\s*(.*?)\s*$")
_PATH_RE = re.compile(r"`([^`]+)`")


def _tokens(chars: int) -> int:
    return math.ceil(chars / 4)


def load_agents(agents_dir) -> list[dict]:
    """Read registry.yaml (flat format, no PyYAML): verb, file and tier per agent."""
    agents_dir = Path(agents_dir)
    out: list[dict] = []
    cur: dict | None = None
    in_agents = False
    for line in (agents_dir / "registry.yaml").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and not line.startswith("-"):
            in_agents = line.strip().rstrip(":") == "agents"
            continue
        if not in_agents:
            continue
        m = _ENTRY_RE.match(line)
        if m:
            cur = {m.group(1): m.group(2)}
            out.append(cur)
            continue
        m = _FIELD_RE.match(line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2)
    return [{"verb": a.get("verb", ""), "file": a.get("file", ""), "tier": a.get("tier", "")} for a in out]


def required_reading(agent_path) -> list[str] | None:
    """Backticked paths in the bullet list under '## Required reading', or None when the heading is missing."""
    lines = Path(agent_path).read_text(encoding="utf-8").splitlines()
    fence = False
    found = False
    paths: list[str] = []
    for line in lines:
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if line.startswith("## "):
            if found:
                break
            if line[3:].strip().lower() == "required reading":
                found = True
            continue
        if found and line.lstrip().startswith(("-", "*")):
            paths.extend(_PATH_RE.findall(line))
    return paths if found else None


def _entry(root: Path, rel: str) -> dict:
    p = root / rel
    exists = p.is_file()
    chars = len(p.read_text(encoding="utf-8")) if exists else 0
    return {"path": rel, "tokens": _tokens(chars), "exists": exists}


def measure(agents_dir, verb: str | None = None) -> list[dict]:
    agents_dir = Path(agents_dir).resolve()
    root = agents_dir.parent
    rows = []
    for a in load_agents(agents_dir):
        if verb and a["verb"] != verb:
            continue
        own_path = agents_dir / a["file"]
        own = _tokens(len(own_path.read_text(encoding="utf-8"))) if own_path.is_file() else 0
        listed = required_reading(own_path) if own_path.is_file() else None
        reading = [_entry(root, CORE_RULES)]
        seen = {CORE_RULES, f".agents/{a['file']}"}
        for rel in listed or []:
            if rel in seen:
                continue
            seen.add(rel)
            reading.append(_entry(root, rel))
        rows.append({**a, "declared": listed is not None, "own_tokens": own, "reading": reading,
                     "total_tokens": own + sum(x["tokens"] for x in reading)})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="csa budget", description="tokens each agent loads before it starts")
    ap.add_argument("verb", nargs="?")
    ap.add_argument("--max", type=int, default=None, dest="max_tokens")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--agents-dir", default=str(Path(__file__).resolve().parents[2]))
    a = ap.parse_args(argv)
    rows = measure(a.agents_dir, a.verb)
    if a.verb and not rows:
        print(f"unknown verb: {a.verb}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"{'verb':<14}{'tier':<10}{'declared':<10}{'own':>8}{'total':>8}")
        for r in rows:
            flag = "yes" if r["declared"] else "no"
            print(f"{r['verb']:<14}{r['tier']:<10}{flag:<10}{r['own_tokens']:>8}{r['total_tokens']:>8}")
            for x in r["reading"]:
                print(f"{'':<34}{x['tokens']:>8}  {x['path']}" + ("" if x["exists"] else "  (missing)"))
    if a.max_tokens is not None and any(r["total_tokens"] > a.max_tokens or not r["declared"] for r in rows):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
