"""Draw the figure a CSA section needs, from its figure profile and the project's evidence.

    draw(row, work_dir, project_key, net, spec) -> {"model", "svg", "hash"}

row is one result of need.assess(). Only built figure kinds draw; anything else raises NotBuilt.
Outputs (written by save()): <work_dir>/figures/<KEY>/model.json, figure.svg, figure.png, and the
manifest <work_dir>/figures/manifest.json (status, model hash, files) that the Figures page reads.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from csa_docx.figures import brief as B
from csa_docx.figures import need as N
from csa_docx.figures import relations as R
from csa_docx.techdiagram import model as M
from csa_docx.techdiagram import views as V
from csa_docx.techdiagram.print_layout import render_print_svg
from csa_docx.techdiagram.render import render_svg


DRAWING_VERSION = "bands-3"                     # bump when the drawn output changes for the same model


class NotBuilt(Exception):
    pass


def _hash(model: dict) -> str:
    stable = {k: model[k] for k in ("nodes", "edges", "groups") if k in model}
    stable["drawing"] = DRAWING_VERSION            # a new way of drawing makes saved figures out of date
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()[:16]


def draw(row: dict, work_dir: Path, project_key: str, net: dict, spec: dict | None, ev: dict | None = None,
         brief: dict | None = None) -> dict:
    """brief: items you left out of the brief are not drawn."""
    profiles = {p["id"]: p for p in N.load_profiles()}
    p = profiles.get(row.get("profile") or "")
    if not p or not p.get("built"):
        raise NotBuilt(f"{row['number']} {row['title']}: this kind of figure is not built yet")
    layout = N.load_layout(project_key)
    app = (spec or {}).get("application") or project_key
    ids = ", ".join(r["id"] for r in row.get("requirements", []))
    if p["archetype"] == "A":
        m = M.overview(net, spec or {}, M.resolve_profile(net, layout), app)
        m["id"] = f"figure-{row['key'].lower()}"
    elif p["archetype"] == "B":
        ev = ev or R.load(work_dir)
        rows = N.scope_relations(p["service"], ev, layout)
        out = B.excluded(brief)
        rows = [r for r in rows if (r["provider"], r["state"]) not in out]
        m = V.service_view(net, spec or {}, layout, rows, key=row["key"], title=p["caption"],
                           subtitle=f"{p['question']}" + (f" ({ids})" if ids else "") + ". From the discovery captures.",
                           service=p["service"], ot_gap=p.get("ot_gap"), application=app)
    elif p["archetype"] in ("C", "D"):
        prof = M.resolve_profile(net, layout)
        over = M.overview(net, spec or {}, prof, app)
        sub = f"{p['question']}" + (f" ({ids})" if ids else "") + ". From the captured connections."
        if p["archetype"] == "C":
            m = V.conduit_view(over, prof, key=row["key"], title=p["caption"], subtitle=sub, scope=p.get("scope", "all"))
        else:
            m = V.access_view(over, prof, key=row["key"], title=p["caption"], subtitle=sub)
    elif p["archetype"] == "F":
        from csa_docx.figures import flowview as FV
        prof = M.resolve_profile(net, layout)
        over = M.overview(net, spec or {}, prof, app)
        sub = f"{p['question']}" + (f" ({ids})" if ids else "") + ". From the flow inventory and host settings."
        m = FV.view(work_dir, over, prof, p, key=row["key"], title=p["caption"], subtitle=sub)
    else:
        raise NotBuilt(f"archetype {p['archetype']} is not built yet")
    # which band (IT, boundary, OT) a shared service sits in: the project's residency rule, never guessed
    shared = [n for n in m["nodes"] if n["zone"] == "shared" and n["kind"] != "gap"]
    if shared:
        ev = ev or R.load(work_dir)
        for n in shared:
            side, _why = R.residency(n["id"], ev, layout)
            if side in ("it", "internet"):
                n["band"] = "it"
            elif side == "ot":
                n["band"] = "ot"
    m["print"] = {"conduits": p["archetype"] in ("A", "C"), "per_target": p["archetype"] == "B"}
    # the page view (screen layout) and the figure as printed in the CSA (band layout, readable at 17 cm)
    psvg, pinfo = render_print_svg(m, aggregate=p["archetype"] in ("A", "C"))
    return {"model": m, "svg": render_svg(m), "print_svg": psvg, "print": pinfo, "hash": _hash(m)}


def save(row: dict, out: dict, work_dir: Path, png: bool = True) -> dict:
    d = work_dir / "figures" / row["key"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.json").write_text(json.dumps(out["model"], indent=1), encoding="utf-8")
    (d / "figure.svg").write_text(out["svg"], encoding="utf-8")
    rel = lambda q: str(Path(q).relative_to(work_dir))      # relative: the work folder moves between machines
    files = {"model": rel(d / "model.json"), "svg": rel(d / "figure.svg")}
    if out.get("print_svg"):
        (d / "figure-print.svg").write_text(out["print_svg"], encoding="utf-8")
        files["print_svg"] = rel(d / "figure-print.svg")
    if png:
        from csa_docx.techdiagram.png import to_png
        # figure.png is what goes into the document: the print layout, about 360 dpi at the 17 cm text width
        src = d / "figure.svg"
        if out.get("print_svg"):
            src = d / ".figure-print-px.svg"
            src.write_text(re.sub(r'width="[\d.]+mm" height="[\d.]+mm"', lambda _m: "", out["print_svg"], count=1), encoding="utf-8")
        p, how = to_png(src, d / "figure.png", scale=2 if not out.get("print_svg") else 3)
        if src.name.startswith("."):
            src.unlink(missing_ok=True)
        files["png"] = rel(p) if p else None
        # figure-screen.png is the on-screen explorer layout, for the author who wants the screen view in the document
        sp, _ = to_png(d / "figure.svg", d / "figure-screen.png", scale=2)
        files["png_screen"] = rel(sp) if sp else None
        files["png_renderer"] = how
    man_path = work_dir / "figures" / "manifest.json"
    try:
        man = json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        man = {"figures": {}}
    entry = man["figures"].setdefault(row["key"], {})
    entry.update({"title": row["title"], "number": row["number"], "profile": row.get("profile"), "hash": out["hash"],
                  "drawn": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": files, "print": out.get("print")})
    man_path.write_text(json.dumps(man, indent=1), encoding="utf-8")
    return entry
