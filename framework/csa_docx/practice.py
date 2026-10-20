"""Practice catalogue: optional per-requirement declaration of the document, process and owner
evidence that captures cannot supply.

A topic frame may carry a top-level ``practice`` object mapping requirement IDs to practice
declarations. Each declaration states what evidence is needed (``needs``), the minimum evidence
strengths required for the requirement to be rated Met (``minimum_for_met``), and the highest
rating permitted while a required strength is absent (``cap_without``).

Requirements without practice metadata behave exactly as they do today.

    from csa_docx import practice
    result = practice.validate_catalogue(frame_dict)
    # {"status": "OK"} or {"status": "ERROR", "errors": [...]}

    needs = practice.needs_for(frame_dict, "SEP-BAK-02")
    # {"document": [...], "process": [...], "owner": [...]} or {}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Allowed evidence strengths (the document's rating floor vocabulary for practice)
STRENGTHS = ("stated", "documented", "operational")

# The document's existing rating vocabulary (used by cap_without)
RATINGS = ("Met", "Partially Met", "Not Met", "Not Applicable")

# Allowed need kinds
NEED_KINDS = ("document", "process", "owner")

# Allowed status values for questions (S394+)
QUESTION_STATUSES = ("open", "assigned", "answered", "not_applicable", "superseded")

# Allowed observation kinds (S395+)
OBSERVATION_KINDS = ("stated", "documented")


def validate_entry(entry: dict, req_id: str) -> list[str]:
    """Validate one practice catalogue entry. Returns a list of error strings (empty = valid)."""
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f"{req_id}: practice entry must be an object, got {type(entry).__name__}"]

    # needs
    needs = entry.get("needs")
    if needs is not None:
        if not isinstance(needs, list):
            errors.append(f"{req_id}: 'needs' must be a list")
        else:
            for i, need in enumerate(needs):
                if not isinstance(need, dict):
                    errors.append(f"{req_id}: needs[{i}] must be an object")
                    continue
                kind = need.get("kind")
                if kind not in NEED_KINDS:
                    errors.append(f"{req_id}: needs[{i}].kind '{kind}' not in {NEED_KINDS}")
                if kind == "document" and "examples" not in need:
                    errors.append(f"{req_id}: needs[{i}] kind 'document' requires 'examples'")
                if kind == "process" and "examples" not in need:
                    errors.append(f"{req_id}: needs[{i}] kind 'process' requires 'examples'")
                if kind == "owner" and "roles" not in need:
                    errors.append(f"{req_id}: needs[{i}] kind 'owner' requires 'roles'")
                if "examples" in need and not isinstance(need["examples"], list):
                    errors.append(f"{req_id}: needs[{i}].examples must be a list")
                if "roles" in need and not isinstance(need["roles"], list):
                    errors.append(f"{req_id}: needs[{i}].roles must be a list")

    # minimum_for_met
    mfm = entry.get("minimum_for_met")
    if mfm is not None:
        if not isinstance(mfm, list):
            errors.append(f"{req_id}: 'minimum_for_met' must be a list")
        else:
            for s in mfm:
                if s not in STRENGTHS:
                    errors.append(f"{req_id}: minimum_for_met strength '{s}' not in {STRENGTHS}")

    # cap_without
    cap = entry.get("cap_without")
    if cap is not None:
        if not isinstance(cap, str):
            errors.append(f"{req_id}: 'cap_without' must be a string")
        elif cap not in RATINGS:
            errors.append(f"{req_id}: cap_without '{cap}' not in {RATINGS}")

    return errors


def validate_catalogue(frame: dict) -> dict:
    """Validate the practice catalogue of a topic frame dict.

    Returns ``{"status": "OK"}`` when valid (or absent), or
    ``{"status": "ERROR", "errors": [...]}`` with human-readable messages.
    """
    practice_obj = frame.get("practice")
    if practice_obj is None:
        return {"status": "OK"}
    if not isinstance(practice_obj, dict):
        return {"status": "ERROR", "errors": [f"practice must be an object, got {type(practice_obj).__name__}"]}
    errors: list[str] = []
    for req_id, entry in practice_obj.items():
        if not re.match(r"^SEP-[A-Z]+-\d+$", req_id):
            errors.append(f"practice key '{req_id}' does not look like a requirement ID (SEP-XXX-NN)")
        errors.extend(validate_entry(entry, req_id))
    if errors:
        return {"status": "ERROR", "errors": errors}
    return {"status": "OK"}


def needs_for(frame: dict, req_id: str) -> dict:
    """Extract the practice needs for a requirement from a topic frame.

    Returns a dict with keys ``document``, ``process``, ``owner`` (each a list of example/role
    strings), or an empty dict when the requirement has no practice metadata.
    """
    practice_obj = frame.get("practice") or {}
    entry = practice_obj.get(req_id)
    if not entry:
        return {}
    out: dict[str, list[str]] = {}
    for need in entry.get("needs", []):
        kind = need.get("kind", "")
        if kind == "document":
            out.setdefault("document", []).extend(need.get("examples", []))
        elif kind == "process":
            out.setdefault("process", []).extend(need.get("examples", []))
        elif kind == "owner":
            out.setdefault("owner", []).extend(need.get("roles", []))
    return out


def minimum_for_met(frame: dict, req_id: str) -> list[str]:
    """The minimum evidence strengths required for the requirement to be rated Met."""
    entry = (frame.get("practice") or {}).get(req_id) or {}
    mfm = entry.get("minimum_for_met", [])
    return [s for s in mfm if s in STRENGTHS]


def cap_without(frame: dict, req_id: str) -> str:
    """The highest rating permitted while a required strength is absent."""
    entry = (frame.get("practice") or {}).get(req_id) or {}
    cap = entry.get("cap_without", "")
    return cap if cap in RATINGS else ""


def catalogue_summary(frame: dict) -> list[dict]:
    """A summary of the practice catalogue for a frame: one row per requirement that has
    practice metadata. Returns [] when the frame has no practice object."""
    practice_obj = frame.get("practice")
    if not practice_obj:
        return []
    out = []
    for req_id, entry in sorted(practice_obj.items()):
        out.append({
            "requirement": req_id,
            "needs": entry.get("needs", []),
            "minimum_for_met": entry.get("minimum_for_met", []),
            "cap_without": entry.get("cap_without", ""),
        })
    return out


def load_frame(key: str) -> dict | None:
    """Load a topic frame by key (e.g. 'BAK', 'SUPPLY') from the references directory."""
    from csa_docx.topic_frames import FRAMES, frame_for
    # frame_for matches by heading, so we glob and check the key field
    for f in sorted(FRAMES.glob("*.json")):
        try:
            fr = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if fr.get("key", "").upper() == key.upper():
            return fr
    return None


def validate_frames(keys: list[str]) -> dict:
    """Validate the practice catalogue of the named topic frames.

    Returns ``{"status": "OK", "validated": [...]}`` or
    ``{"status": "ERROR", "errors": [...]}``.
    """
    errors: list[str] = []
    validated: list[str] = []
    for key in keys:
        fr = load_frame(key)
        if fr is None:
            errors.append(f"topic frame '{key}' not found")
            continue
        result = validate_catalogue(fr)
        if result["status"] != "OK":
            errors.extend(result.get("errors", []))
        else:
            validated.append(key)
    if errors:
        return {"status": "ERROR", "errors": errors}
    return {"status": "OK", "validated": validated}


def has_practice(frame: dict, req_id: str) -> bool:
    """True when the frame carries practice metadata for the requirement."""
    return req_id in (frame.get("practice") or {})


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p_val = sub.add_parser("validate", help="validate the practice catalogue of named frames")
    p_val.add_argument("keys", nargs="+", help="frame keys, e.g. BAK SUPPLY")

    p_show = sub.add_parser("show", help="show the practice catalogue of a frame")
    p_show.add_argument("key", help="frame key, e.g. BAK")

    a = ap.parse_args(argv)
    if a.cmd == "validate":
        result = validate_frames(a.keys)
        print(json.dumps(result, indent=1))
        return 0 if result["status"] == "OK" else 1
    elif a.cmd == "show":
        fr = load_frame(a.key)
        if fr is None:
            print(f"frame '{a.key}' not found", file=sys.stderr)
            return 1
        result = validate_catalogue(fr)
        if result["status"] != "OK":
            print(json.dumps(result, indent=1), file=sys.stderr)
            return 1
        summary = catalogue_summary(fr)
        if not summary:
            print(f"{a.key}: no practice metadata")
        else:
            print(json.dumps(summary, indent=1))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
