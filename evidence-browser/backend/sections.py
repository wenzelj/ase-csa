from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from . import documents, pipeline


Runner = Callable[[str], Any]
RevisionReader = Callable[[dict[str, str]], dict[str, Any]]
EVIDENCE_ID = re.compile(r"\bE-\d{3,}\b", re.I)


def _resolver(agents_dir: Path):
    path = agents_dir / "framework" / "csa_docx" / "doc_spec.py"
    spec = importlib.util.spec_from_file_location("csa_evidence_browser_doc_spec", path)
    if spec is None or spec.loader is None:
        raise HTTPException(503, "The framework section resolver is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normal(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())


def _read_text(path: str | None) -> str | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    try:
        return candidate.read_text(encoding="utf-8") if candidate.is_file() else None
    except OSError:
        return None


def _matched_record(node: dict[str, Any], rows: list[dict[str, Any]], *, build: bool = False) -> dict[str, Any] | None:
    number, title = str(node.get("number") or ""), _normal(node.get("title"))
    if build:
        hits = [row for row in rows if _normal(row.get("heading")) == title]
    else:
        hits = [row for row in rows if str(row.get("subsection") or row.get("section") or "") == number]
        if len(hits) != 1:
            hits = [row for row in rows if _normal(row.get("title")) == title]
    return hits[0] if len(hits) == 1 else None


def _evidence_for(node: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blob = " ".join([str(node.get("title") or ""), str(node.get("key") or ""),
                     *[str(part) for part in node.get("parts", [])]])
    cited = {value.upper() for value in EVIDENCE_ID.findall(blob)}
    tokens = {token for token in _normal(node.get("title")).split() if len(token) > 3}
    result = []
    for row in evidence:
        eid = str(row.get("evidence_id") or "").upper()
        haystack = _normal(" ".join(str(row.get(key) or "") for key in ("csa_area", "question", "claim", "section")))
        if eid in cited or (tokens and len(tokens.intersection(haystack.split())) >= min(2, len(tokens))):
            result.append(row)
    return result


def _revision_slice(node: dict[str, Any], view: dict[str, Any]) -> list[dict[str, Any]]:
    paragraphs = view.get("paragraphs", []) if isinstance(view, dict) else []
    wanted = {_normal(node.get("title")), _normal(f"{node.get('number', '')} {node.get('title', '')}")}
    start = next((i for i, row in enumerate(paragraphs)
                  if str(row.get("style", "")).lower().startswith("heading") and
                  _normal("".join(str(token.get("text", "")) for token in row.get("tokens", []))) in wanted), None)
    if start is None:
        return []
    level = int(re.search(r"(\d+)", str(paragraphs[start].get("style", "Heading 9"))).group(1))
    end = len(paragraphs)
    for i in range(start + 1, len(paragraphs)):
        match = re.search(r"heading\s*(\d+)", str(paragraphs[i].get("style", "")), re.I)
        if match and int(match.group(1)) <= level:
            end = i
            break
    return paragraphs[start:end]


def inspect(agents_dir: Path, project: dict[str, str], section: str,
            evidence: list[dict[str, Any]], *, runner: Runner | None = None,
            revision_reader: RevisionReader | None = None) -> dict[str, Any]:
    run = runner or (lambda operation: pipeline._run(agents_dir, project, operation))
    spec = run("spec_status")
    if not isinstance(spec, dict) or not isinstance(spec.get("nodes"), list):
        raise HTTPException(502, "The document specification returned an unexpected structure")
    resolver = _resolver(agents_dir)
    try:
        node = resolver.resolve(spec, section)
    except resolver.ResolveError as error:
        message = str(error)
        raise HTTPException(409 if "more than one" in message else 404, message) from error

    status_rows = run("status")
    build_rows = run("sections")
    if not isinstance(status_rows, list):
        status_rows = []
    if not isinstance(build_rows, list):
        build_rows = []
    revise = _matched_record(node, status_rows)
    build = _matched_record(node, build_rows, build=True)
    change_file = revise.get("change_file") if revise else None
    section_file = build.get("file") if build else None
    if section_file and not Path(str(section_file)).is_absolute():
        section_file = str(Path(project["work_dir"]).expanduser() / "sections" / str(section_file))
    proposal = _read_text(change_file) or _read_text(section_file)
    parts = node.get("parts", [])
    questions = []
    requirements = []
    for part in parts:
        if part.get("question"):
            questions.append({"id": part.get("pid"), "question": part["question"], "answered": part.get("answered", False)})
        for requirement in part.get("requirements", []):
            requirements.append({**requirement, "table_id": part.get("table"), "ratings": part.get("ratings", [])})
    relevant = _evidence_for(node, evidence)
    open_questions = [q for q in questions if not q["answered"]]
    if not relevant:
        open_questions.append({"id": None, "question": "Which reviewed evidence supports this section?", "answered": False})
    try:
        revisions = _revision_slice(node, (revision_reader or documents.revision_view)(project))
    except (HTTPException, OSError):
        revisions = []
    deleted = [{"paragraph_id": row.get("index"), "text": token.get("text", "")}
               for row in revisions for token in row.get("tokens", []) if token.get("kind") == "delete"]

    return {
        "identity": {"requested": section, "visible_number": node.get("number", ""),
                     "stable_key": node.get("key", ""), "stable_path": node.get("path"),
                     "stable_id": node.get("hid"), "heading": node.get("title", ""),
                     "kind": node.get("kind", "")},
        "current": {"status": node.get("status", {}), "parts": parts},
        "requirements": requirements,
        "comments": node.get("comments", []),
        "guidance": node.get("guidance", []),
        "removed": deleted,
        "removed_sections": spec.get("removed", []),
        "revisions": revisions,
        "evidence": relevant,
        "questions": questions,
        "open_questions": open_questions,
        "work": {"lane": "revise" if revise else "build" if build else "unknown",
                 "change_file": change_file, "section_file": section_file,
                 "proposal": proposal, "author_report": (revise or build or {})},
        "validation": {"state": (revise or build or {}).get("review") or
                                  (revise or build or {}).get("validation") or "unknown",
                       "findings": [value for value in ((revise or build or {}).get("problem"),) if value]},
    }
