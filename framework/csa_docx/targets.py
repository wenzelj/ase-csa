"""Section targets by identity, not position (S254).

Convert, move, the requirement map and the legacy map name their target subsection. A target may be a
number (3.5), a heading ("DNS"), a requirement family (DNS) or a stamp key; it is resolved against the CSA
template's document spec, so two spellings of the same subsection compare equal and a number is checked
against what the template actually has there. Folders and records keep the template number as a readable
label (`convert/3.5/`); the key is the identity.

spec_mode (CSA_SPEC_MODE): off = plain string comparison; shadow = string comparison, and every place the
key comparison would answer differently is logged to WORK_DIR/spec/shadow.log; on = key comparison.
"""

from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from pathlib import Path

from csa_docx import doc_spec

_REQ = re.compile(r"^SEP-([A-Z]+)-\d+$")


def spec_mode() -> str:
    m = (os.environ.get("CSA_SPEC_MODE") or "shadow").strip().lower()
    return m if m in ("off", "shadow", "on") else "shadow"


def shadow_log(what: str, old, new, **ctx) -> None:
    root = os.environ.get("CSA_WORK_DIR")
    if not root:
        return
    try:
        log = Path(root) / "spec" / "shadow.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "what": what, "old": old, "new": new, **ctx},
                                default=str) + "\n")
    except OSError:
        pass


@lru_cache(maxsize=4)
def template_spec(path: str | None = None) -> dict | None:
    from csa_docx import spec_cli
    t = Path(path) if path else spec_cli.find_template(None)
    return doc_spec.read(t) if t and Path(t).is_file() else None


def _node(target: str):
    spec = template_spec()
    if not spec or not str(target or "").strip():
        return None
    try:
        return doc_spec.resolve(spec, str(target))
    except doc_spec.ResolveError:
        return None


@lru_cache(maxsize=512)
def target_key(target: str) -> str | None:
    n = _node(target)
    return n["key"] if n else None


@lru_cache(maxsize=512)
def canonical(target: str) -> str:
    """The template number of a target given as number, heading, family or key (unchanged when unknown)."""
    t = str(target or "").strip()
    n = _node(t)
    return n["number"] if n and n.get("number") else t


def family(req_id: str) -> str | None:
    m = _REQ.match(str(req_id or "").strip())
    return m.group(1) if m else None


def requirement_key(row: dict) -> str | None:
    """The key of the subsection a requirement-map row belongs to: the template node holding its requirement ID."""
    spec = template_spec()
    rid = row.get("req_id", "")
    if spec:
        for n in spec["nodes"]:
            if any(r["id"] == rid for p in n["parts"] for r in p.get("requirements", [])):
                return n["key"]
    return family(rid)


def same_target(a: str, b: str, *, what: str = "target") -> bool:
    plain = str(a or "").strip() == str(b or "").strip()
    mode = spec_mode()
    if mode == "off":
        return plain
    ka, kb = target_key(str(a or "")), target_key(str(b or ""))
    by_key = bool(ka) and ka == kb
    if mode == "on":
        return by_key if (ka and kb) else plain
    if ka and kb and by_key != plain:
        shadow_log(what, plain, by_key, a=a, b=b)
    return plain


def requirement_in(row: dict, target: str) -> bool:
    """Is this requirement-map row part of target? on: by the node that holds its ID; else by the domain column."""
    plain = str(row.get("domain", "")).strip() == str(target or "").strip()
    mode = spec_mode()
    if mode == "off":
        return plain
    tk = target_key(str(target or ""))
    rk = requirement_key(row)
    by_key = bool(tk) and tk == rk
    if mode == "on":
        return by_key if tk else plain
    if tk and by_key != plain:
        shadow_log("requirement_map", plain, by_key, req_id=row.get("req_id"), target=target)
    return plain
