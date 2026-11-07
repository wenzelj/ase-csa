"""csa system-diagram: write a project's technical diagrams from its live evidence.

  csa system-diagram [--out DIR] [--no-png]

Reads the host register and connection captures (the same build the Evidence Workspace uses),
csa-work/explorer/journeys.json and the project's layout in csa-context/system-diagrams.json.
Writes to <work_dir>/diagrams/system/:
  system-overview.svg / .png / .model.json      the system figure
  flow-<journey>.svg / .png / .model.json       one numbered data-flow figure per journey
  system-diagrams.html                          all of them, clickable (same SVGs)
Prints one JSON result.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[3]
if str(AGENTS / "framework") not in sys.path:
    sys.path.insert(0, str(AGENTS / "framework"))

from csa_docx.techdiagram import diagrams  # noqa: E402
from csa_docx.techdiagram.png import to_png  # noqa: E402
from csa_docx.techdiagram.viewer import make_html  # noqa: E402


def _project(key: str) -> dict:
    from csa_docx.tools import _load_project_registry
    for p in _load_project_registry():
        if p.get("key") == key:
            return p
    raise SystemExit(json.dumps({"status": "ERROR", "message": f"project {key!r} is not in csa-context/PROJECTS.yaml"}))


def _local(path: str) -> Path:
    """Registry paths are absolute Mac paths; on another machine or a VM mount, map them onto this checkout."""
    p = Path(path).expanduser()
    if p.exists():
        return p
    root = AGENTS.parent
    parts = p.parts
    if root.name in parts:
        return root.joinpath(*parts[parts.index(root.name) + 1:])
    return p


def _network(work_dir: Path) -> dict:
    spec = importlib.util.spec_from_file_location("eb_network", AGENTS / "evidence-browser" / "backend" / "network.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod.build(work_dir, AGENTS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project key from csa-context/PROJECTS.yaml")
    ap.add_argument("--out", help="output folder (default <work_dir>/diagrams/system)")
    ap.add_argument("--no-png", action="store_true", help="skip the PNG figures")
    a = ap.parse_args(argv)

    p = _project(a.project)
    work = _local(p["work_dir"])
    out = Path(a.out).expanduser() if a.out else work / "diagrams" / "system"
    out.mkdir(parents=True, exist_ok=True)
    net = _network(work)
    jf = work / "explorer" / "journeys.json"
    spec = json.loads(jf.read_text(encoding="utf-8")) if jf.is_file() else {}
    app = spec.get("application") or p.get("label", a.project)
    ds = diagrams(net, spec, a.project, app)
    written, png_note = [], ""
    for d in ds:
        svg = out / f"{d['id']}.svg"
        svg.write_text(d["svg"], encoding="utf-8")
        (out / f"{d['id']}.model.json").write_text(json.dumps(d["model"], indent=1), encoding="utf-8")
        item = {"id": d["id"], "title": d["title"], "svg": str(svg), "nodes": len(d["model"]["nodes"]), "lines": len(d["model"]["edges"])}
        if not a.no_png:
            png, how = to_png(svg, out / f"{d['id']}.png")
            item["png"] = str(png) if png else None
            png_note = how
        written.append(item)
    page = out / "system-diagrams.html"
    page.write_text(make_html(app, ds), encoding="utf-8")
    print(json.dumps({"status": "OK", "project": a.project, "out": str(out), "html": str(page),
                      "png_renderer": png_note or "skipped", "diagrams": written}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
