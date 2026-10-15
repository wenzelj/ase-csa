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
    """The project's diagram profile (csa-context/system-diagrams.json), plus ``shared_servers`` from the estate
    register when the project has an estate: those servers are drawn in the shared-services band."""
    try:
        data = json.loads(PROFILES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    profile = dict(data.get(project_key) or {})
    try:
        from csa_docx import estate
        shared = estate.shared_servers(project_key)
        if shared:
            profile["shared_servers"] = shared
    except Exception:                       # the estate view is an addition: never stop a diagram for it
        pass
    return profile


def diagrams(net: dict, spec: dict | None, project_key: str, application: str) -> list[dict]:
    """Every diagram for a project as {id, title, model, svg}."""
    out = []
    for m in build_models(net, spec or {}, load_profile(project_key), application):
        out.append({"id": m["id"], "title": m["title"], "model": m, "svg": render_svg(m)})
    return out
