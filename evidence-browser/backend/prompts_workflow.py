"""Draft answers page: the prompts an answer call is built from (framework/csa_docx/prompts.py).

Shared defaults live in .agents/prompts/answer. A change made on the page is saved for the project only
(csa-work/prompts/answer), and can be reset to the shared default.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import HTTPException


def _prompts(agents_dir: Path):
    framework = str(agents_dir / "framework")
    if framework not in sys.path:
        sys.path.insert(0, framework)
    from csa_docx import prompts
    return prompts


def _work(project: dict[str, str]) -> Path:
    return Path(project["work_dir"]).expanduser()


def _name(prompts, name: str) -> str:
    if name not in prompts.REGISTRY:               # never a path from the client
        raise HTTPException(404, "Unknown prompt")
    return name


def listing(agents_dir: Path, project: dict[str, str]) -> dict[str, Any]:
    prompts = _prompts(agents_dir)
    work = _work(project)
    return {"prompts": prompts.listing(work), "max_bytes": prompts.MAX_BYTES, "sections": _sections(work)}


def _sections(work: Path) -> list[dict[str, Any]]:
    """Each answerable card with its blocks, so the page can preview the prompt of one call."""
    out = []
    for f in sorted((work / "cards").glob("*.json")):
        if f.name.count(".") != 1:                  # STOR.json, not STOR.manifest.json
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or not d.get("questions"):
            continue
        out.append({"key": d.get("key") or f.stem, "number": str(d.get("number") or ""), "title": d.get("title") or f.stem,
                    "blocks": [{"id": q.get("id"), "kind": q.get("kind"), "label": str(q.get("text", ""))[:60]}
                               for q in d["questions"] if q.get("id")]})
    return sorted(out, key=lambda s: [int(x) if x.isdigit() else 0 for x in s["number"].split(".")])


def save(agents_dir: Path, project: dict[str, str], name: str, payload: dict[str, Any]) -> dict[str, Any]:
    prompts = _prompts(agents_dir)
    text = payload.get("text")
    if not isinstance(text, str):
        raise HTTPException(422, "text is required")
    result = prompts.save(_name(prompts, name), _work(project), text, str(payload.get("etag") or ""))
    if result.get("conflict"):
        raise HTTPException(409, result["problems"][0])
    if not result["saved"]:
        raise HTTPException(422, "; ".join(result["problems"]))
    return result


def reset(agents_dir: Path, project: dict[str, str], name: str) -> dict[str, Any]:
    prompts = _prompts(agents_dir)
    return prompts.reset(_name(prompts, name), _work(project))


def history(agents_dir: Path, project: dict[str, str], name: str) -> dict[str, Any]:
    prompts = _prompts(agents_dir)
    return {"versions": prompts.history(_name(prompts, name), _work(project))}


def preview(agents_dir: Path, project: dict[str, str], key: str, block: str) -> dict[str, Any]:
    """The rules part of one call's prompt: base plus the prompt of the kind of that block (or of every block)."""
    prompts = _prompts(agents_dir)
    work = _work(project)
    section = next((s for s in _sections(work) if s["key"] == key), None)
    if not section:
        raise HTTPException(404, "No card for that subsection: build it first")
    block = (block or "").upper()
    if block and block not in {b["id"].upper() for b in section["blocks"]}:
        raise HTTPException(404, "Unknown block")
    kinds = prompts.kinds_for_call(work, key, block)
    text, sources = prompts.assemble(kinds, work, frame=(not block or block == "F1"))
    return {"text": text, "words": len(text.split()), "sources": [{"name": n, "source": s} for n, s in sources],
            "kinds": sorted(k for k in kinds if k)}
