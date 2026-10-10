"""Technical system diagrams: one evidence-backed drawing for the CSA figure and the Evidence Workspace.

  models = build_models(net, spec, profile, application)   # model.py
  svg = render_svg(model)                                   # render.py (track layout, no Graphviz)
  load_profile(project_key)                                 # csa-context/system-diagrams.json

Run for a project:  csa system-diagram  (or  python -m csa_docx.techdiagram --project KEY)
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import build_models
from .render import render_svg

PROFILES = Path(__file__).resolve().parents[3] / "csa-context" / "system-diagrams.json"


def load_profile(project_key: str) -> dict:
    try:
        data = json.loads(PROFILES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get(project_key) or {}


def diagrams(net: dict, spec: dict | None, project_key: str, application: str) -> list[dict]:
    """Every diagram for a project as {id, title, model, svg}."""
    out = []
    for m in build_models(net, spec or {}, load_profile(project_key), application):
        out.append({"id": m["id"], "title": m["title"], "model": m, "svg": render_svg(m)})
    return out
