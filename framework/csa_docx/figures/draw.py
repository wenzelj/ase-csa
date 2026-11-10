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
from collections import OrderedDict
from pathlib import Path

from csa_docx.figures import brief as B
from csa_docx.figures import need as N
from csa_docx.figures import relations as R
from csa_docx.techdiagram import model as M
from csa_docx.techdiagram import views as V
from csa_docx.techdiagram.print_layout import render_print_svg
from csa_docx.techdiagram.render import render_svg


DRAWING_VERSION = "bands-5"                     # compact landscape Screen canvas and larger host typography


class NotBuilt(Exception):
    pass


def _hash(model: dict) -> str:
    stable = {k: model[k] for k in ("nodes", "edges", "groups") if k in model}
    stable["drawing"] = DRAWING_VERSION            # a new way of drawing makes saved figures out of date
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _screen_document_model(model: dict) -> dict:
    """Collapse same-role hosts per site for the A4 landscape Screen layout.

    The interactive explorer keeps every host.  A page cannot: shrinking 35 individual cards
    made their text about 3 pt.  This page model keeps the evidenced connections but represents
    hosts sharing one site/role as a single card and names the members beneath the role.
    """
    from csa_docx.techdiagram.band_layout import members_label, service_names, short_role

    grouped: OrderedDict[tuple[str, str, str], list[dict]] = OrderedDict()
    key_of: dict[str, tuple[str, str, str]] = {}
    for node in model["nodes"]:
        key = (node["zone"], short_role(node), node["kind"])
        grouped.setdefault(key, []).append(node)
        key_of[node["id"]] = key
    group_member = {g["id"]: g["members"][0] for g in model.get("groups", []) if g.get("members")}
    node_id: dict[tuple[str, str, str], str] = {}
    nodes = []
    for n, (key, members) in enumerate(grouped.items(), 1):
        node_id[key] = f"SR-{n}"
        first = members[0]
        nodes.append({**first, "id": node_id[key], "label": key[1],
                      "role": members_label([x["label"] for x in members]), "group": None})

    def endpoint(value: str) -> str:
        if value.startswith("Z:"):
            return value
        value = group_member.get(value, value)
        return node_id[key_of[value]]

    merged: OrderedDict[tuple[str, str, str, str], dict] = OrderedDict()
    for edge in model["edges"]:
        source, target = endpoint(edge["s"]), endpoint(edge["t"])
        if source == target:
            continue
        key = (source, target, edge["status"], edge.get("dir") or "forward")
        item = merged.setdefault(key, {**edge, "id": f"SRL-{len(merged) + 1}",
                                      "s": source, "t": target, "_labels": [], "evidence": []})
        services, more = service_names(edge)
        item["_labels"].extend(services)
        if more:
            item["_more"] = item.get("_more", 0) + more
        item["evidence"] = sorted(set(item["evidence"]) | set(edge.get("evidence") or []))
    edges = []
    for item in merged.values():
        labels = list(dict.fromkeys(item.pop("_labels")))
        shown = labels[:3]
        extra = len(labels) - len(shown) + item.pop("_more", 0)
        item["label"] = ", ".join(shown) + (f" +{extra}" if extra else "")
        edges.append(item)
    return {**model, "nodes": nodes, "edges": edges, "groups": []}


def draw(row: dict, work_dir: Path, project_key: str, net: dict, spec: dict | None, ev: dict | None = None,
         brief: dict | None = None) -> dict:
    """brief: items you left out of the brief are not drawn."""
    profiles = {p["id"]: p for p in N.load_profiles()}
    p = profiles.get(row.get("profile") or "")
    if p and row.get("part"):
        p = N.profile_of(row)
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
    elif p["archetype"] == "G":
        from csa_docx.figures import storeview as SV
        prof = M.resolve_profile(net, layout)
        over = M.overview(net, spec or {}, prof, app)
        sub = f"{p['question']}" + (f" ({ids})" if ids else "") + ". From the flow inventory and host settings."
        m = SV.view(work_dir, over, prof, p, key=row["key"], title=p["caption"], subtitle=sub)
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
    if p["archetype"] == "G":
        # store-centric: a single purpose-built renderer (store cards + consumer tiles)
        from csa_docx.techdiagram.store_layout import render_store_svg
        svg, sinfo = render_store_svg(m)
        return {"model": m, "svg": svg, "screen_landscape_svg": svg, "screen_landscape": sinfo,
                "print_svg": svg, "print": sinfo, "hash": _hash(m)}
    # The Screen view remains a genuine landscape canvas.  It is intentionally separate from the
    # page-oriented As-printed band layout: the screen renderer has compact host spacing and larger
    # labels, so Word can scale it to the full landscape text width without the portrait squash.
    screen_landscape_svg = render_svg(m)
    mm = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', screen_landscape_svg)
    sw, sh = (float(mm.group(1)), float(mm.group(2))) if mm else (1.0, 1.0)
    screen_landscape = {"width_mm": 257.0, "height_mm": round(257.0 * sh / sw, 1),
                        "fits_page": 257.0 * sh / sw <= 170.0, "min_text_pt": 13.0}
    # the page view (screen layout) and the figure as printed in the CSA (band layout, readable at 17 cm)
    psvg, pinfo = render_print_svg(m, aggregate=p["archetype"] in ("A", "C"))
    return {"model": m, "svg": render_svg(m), "screen_landscape_svg": screen_landscape_svg,
            "screen_landscape": screen_landscape, "print_svg": psvg, "print": pinfo, "hash": _hash(m)}


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
    if out.get("screen_landscape_svg"):
        (d / "figure-screen-landscape.svg").write_text(out["screen_landscape_svg"], encoding="utf-8")
        files["screen_landscape_svg"] = rel(d / "figure-screen-landscape.svg")
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
        sl, _ = to_png(d / "figure-screen-landscape.svg", d / "figure-screen-landscape.png", scale=2)
        files["png_screen_landscape"] = rel(sl) if sl else None
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
