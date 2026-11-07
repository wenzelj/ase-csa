"""The prompts an answer call is built from: one base prompt plus one short prompt per kind of block.

Shared defaults live in `.agents/prompts/answer/<name>.md`. A project may override any of them in
`<work_dir>/prompts/answer/<name>.md` (the Evidence Browser's Draft answers page writes these). A project file wins
over the shared default. Nothing else in the framework reads these files directly.

    assemble(kinds, work_dir, fix=False, frame=False) -> (text, [(name, "default" | "project")])
    kinds_for_call(work_dir, card_name, only) -> set of block kinds the call writes
    listing(work_dir) -> [{name, title, ..., text, source, etag, words}]
    save(name, work_dir, text, etag) / reset(name, work_dir) / history(name, work_dir)
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

DEFAULTS = Path(__file__).resolve().parents[2] / "prompts" / "answer"
MAX_BYTES = 12288
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

#: name -> title, what it is used for, block kinds (as in the card json), placeholders the file must keep
REGISTRY: dict[str, dict] = {
    "base": {"title": "Every call", "kinds": [], "required": ["plain_language", "forbidden_terms"],
             "use": "Role, sheet format, Facts, never infer, names and addresses, plain language. Part of every call."},
    "requirement": {"title": "Requirement blocks", "kinds": ["requirement"], "required": [],
                    "use": "Summary and Story, the rating, and the practice the requirement asks about."},
    "narrative": {"title": "Drawbridge Impact and narrative blocks", "kinds": ["narrative"], "required": [],
                  "use": "What stops and what keeps working when the system is isolated."},
    "table": {"title": "Table blocks", "kinds": ["observation", "register"], "required": [],
              "use": "Rows, one row per role group, counts."},
    "note": {"title": "Note under a table", "kinds": ["note"], "required": [],
             "use": "No note, or one or two evidenced sentences."},
    "findings": {"title": "Findings blocks", "kinds": ["findings"], "required": [],
                 "use": "Bullets, one finding each."},
    "frame": {"title": "Analysis frame (F1)", "kinds": [], "required": [],
              "use": "The F1 block that lists which blocks answer each slot."},
    "fix": {"title": "Fix round", "kinds": [], "required": [],
            "use": "How to read the errors and rewrite only the listed blocks."},
    "rating": {"title": "Answer rating", "kinds": [], "required": [],
               "use": "The call after the answer that scores each block's quality 1 to 10 (shown on the Draft answers page). It never edits."},
    "review": {"title": "Reader review", "kinds": [], "required": [],
               "use": "The call after the answer that reads the whole sheet as the customer and reports problems. It never edits."},
}
#: kinds in the card json -> prompt file
KIND_FILE = {k: n for n, r in REGISTRY.items() for k in r["kinds"]}


def _project_dir(work_dir) -> Path:
    return Path(work_dir) / "prompts" / "answer"


def _plain_language() -> str:
    from csa_docx import rules_digest
    return rules_digest.plain_language()


def etag(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def resolve(name: str, work_dir) -> tuple[str, str]:
    """(text, source) of one prompt: the project's own file when it has one, else the shared default."""
    if name not in REGISTRY:
        raise KeyError(f"unknown prompt {name!r}")
    if work_dir:
        mine = _project_dir(work_dir) / f"{name}.md"
        if mine.is_file():
            return mine.read_text(encoding="utf-8"), "project"
    return (DEFAULTS / f"{name}.md").read_text(encoding="utf-8"), "default"


def _body(text: str) -> str:
    return _COMMENT.sub("", text).strip()


def _forbidden_terms() -> str:
    from csa_docx.section_card import forbidden_terms_lines
    return "\n".join(ln for ln in forbidden_terms_lines() if ln.startswith("- "))


def _example() -> str:
    from csa_docx.section_card import _example as example
    return example("requirement").strip()


def _fill(text: str) -> str:
    values = {"plain_language": _plain_language, "forbidden_terms": _forbidden_terms, "example": _example}
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)]() if m.group(1) in values else m.group(0), text)


def assemble(kinds, work_dir, fix: bool = False, frame: bool = False) -> tuple[str, list[tuple[str, str]]]:
    """The prompt text for a call that writes blocks of ``kinds``: base, then one file per kind (in registry order),
    then the frame and fix files when the call needs them. A file that holds only a comment adds nothing."""
    wanted = {KIND_FILE[k] for k in kinds if k in KIND_FILE}
    order = ["base"] + [n for n in REGISTRY if n in wanted] + (["frame"] if frame else []) + (["fix"] if fix else [])
    parts, sources = [], []
    for name in order:
        text, source = resolve(name, work_dir)
        sources.append((name, source))
        if _body(text):
            parts.append(_fill(_body(text)))
    return "\n\n".join(parts) + "\n", sources


def card_rules(kinds, work_dir=None) -> str:
    """Only the rules that used to sit on the card (Using the card, Unknowns, forbidden words, and the kind prompts), for
    the V1 answer lane, whose digest has its own sheet-shape text."""
    base, _ = resolve("base", work_dir)
    start, end = base.find("## Using the card"), base.find("{{plain_language}}")
    own = base[start:end] if 0 <= start < end else ""
    wanted = {KIND_FILE[k] for k in kinds if k in KIND_FILE}
    parts = [_fill(_body(own))] + [_fill(_body(resolve(n, work_dir)[0])) for n in REGISTRY if n in wanted]
    return "\n\n".join(x for x in parts if x) + "\n"


def kinds_for_call(work_dir, card_name: str, only: str = "") -> set[str]:
    """The block kinds a call writes. The card json is cards/<KEY>.json, KEY being the card file's first name part;
    ``only`` is the call's ONLY= (B1,B3). With no ONLY every block of the card counts."""
    key = Path(card_name or "").name.split(".")[0]
    path = Path(work_dir) / "cards" / f"{key}.json"
    try:
        qs = json.loads(path.read_text(encoding="utf-8")).get("questions", [])
    except (OSError, ValueError):
        return set(KIND_FILE)                      # no card json: every kind, so no rule is missing
    ids = {x.strip().upper() for x in str(only or "").split(",") if x.strip()}
    return {q.get("kind") for q in qs if q.get("kind") and (not ids or str(q.get("id", "")).upper() in ids)}


def listing(work_dir) -> list[dict]:
    out = []
    for name, r in REGISTRY.items():
        text, source = resolve(name, work_dir)
        out.append({"name": name, "title": r["title"], "use": r["use"], "kinds": r["kinds"], "required": r["required"],
                    "text": text, "source": source, "etag": etag(text), "words": len(_body(text).split())})
    return out


def check(name: str, text: str) -> list[str]:
    problems = []
    if len(text.encode("utf-8")) > MAX_BYTES:
        problems.append(f"over {MAX_BYTES} bytes")
    for ph in REGISTRY[name]["required"]:
        if "{{" + ph + "}}" not in text:
            problems.append("must keep the placeholder {{" + ph + "}}")
    unknown = sorted({m for m in _PLACEHOLDER.findall(text) if m not in {"plain_language", "forbidden_terms", "example"}})
    if unknown:
        problems.append("unknown placeholder " + ", ".join("{{" + u + "}}" for u in unknown))
    return problems


def _backups(work_dir) -> Path:
    return Path(work_dir) / "backups" / "prompts"


def save(name: str, work_dir, text: str, expected_etag: str) -> dict:
    """Write the project's own copy of a prompt. Refuses a stale etag or a text that breaks the checks; saves a
    timestamped copy of what it replaces."""
    if name not in REGISTRY:
        raise KeyError(f"unknown prompt {name!r}")
    current, source = resolve(name, work_dir)
    if expected_etag and expected_etag != etag(current):
        return {"saved": False, "conflict": True, "problems": ["the prompt changed since you opened it: reload"]}
    problems = check(name, text)
    if problems:
        return {"saved": False, "conflict": False, "problems": problems}
    target = _project_dir(work_dir) / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if source == "project":
        _backups(work_dir).mkdir(parents=True, exist_ok=True)
        backup = _backups(work_dir) / f"{name}.{datetime.now():%Y%m%d-%H%M%S}.md"
        shutil.copy2(target, backup)
    target.write_text(text, encoding="utf-8")
    return {"saved": True, "etag": etag(text), "backup": str(backup) if backup else None, "problems": []}


def reset(name: str, work_dir) -> dict:
    mine = _project_dir(work_dir) / f"{name}.md"
    if name not in REGISTRY:
        raise KeyError(f"unknown prompt {name!r}")
    if mine.is_file():
        _backups(work_dir).mkdir(parents=True, exist_ok=True)
        shutil.move(str(mine), str(_backups(work_dir) / f"{name}.{datetime.now():%Y%m%d-%H%M%S}.reset.md"))
    return {"reset": True}


def history(name: str, work_dir) -> list[dict]:
    if name not in REGISTRY:
        raise KeyError(f"unknown prompt {name!r}")
    folder = _backups(work_dir)
    files = sorted(folder.glob(f"{name}.*.md"), reverse=True) if folder.is_dir() else []
    return [{"file": f.name, "text": f.read_text(encoding="utf-8")} for f in files[:20]]
