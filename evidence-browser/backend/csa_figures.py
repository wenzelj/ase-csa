"""CSA figures page: where the working document needs a figure, what that figure must show (the brief), the figure
itself, the fit check against the section's text, and its place in the document.

Everything comes from csa_docx.figures (need, brief, draw, fit, work), the same code `csa figures` uses, so the
page and the CLI can never disagree. Saving writes only <work_dir>/figures/<KEY>/. Putting a figure in the document
and the wording agent run as jobs (`csa figure KEY --place` / `--agent`), like the other lanes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import network

BLOCKED = {"state": "blocked", "reason": "No single working document was found for this project.", "rows": []}


def _ctx(project: dict[str, str], agents: Path, docx: Path):
    network._framework(agents)                                    # puts the framework on sys.path
    from csa_docx.figures import work as WK
    work = Path(project["work_dir"]).expanduser()
    return WK, WK.open_ctx(project.get("key", ""), work, docx, network.build(work, agents))


def listing(project: dict[str, str], agents: Path, docx: Path | None) -> dict[str, Any]:
    if docx is None:
        return BLOCKED
    network._framework(agents)
    from csa_docx import doc_spec
    from csa_docx.figures import need, relations
    from csa_docx.figures import work as WK
    work = Path(project["work_dir"]).expanduser()
    ev = relations.load(work)
    rows = need.assess(doc_spec.read(str(docx)), work, project.get("key", ""), ev=ev)
    saved = WK.manifest(work)
    out, counts = [], {}
    for r in rows:
        if r["status"] == "none":
            continue
        s = saved.get(r["key"])
        r = {k: r.get(k) for k in ("key", "number", "title", "level", "status", "reason", "profile", "archetype", "question",
                                   "must_show", "caption", "requirements", "hosts_in_text", "slot")}
        r["saved"] = {"at": s.get("drawn"), "hash": s.get("hash"), "fit": s.get("fit"), "gaps": s.get("gaps"),
                      "placed": s.get("placed")} if s else None
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        out.append(r)
    gaps = WK.all_gaps(work)
    return {"state": "ready", "document": docx.name, "rows": out, "counts": counts, "gaps": len(gaps),
            "last_refresh": WK.last_refresh(work)}


def _shape(res: dict) -> dict[str, Any]:
    m = res.get("model") or {}
    return {"state": "ready", "row": res["row"], "brief": res["brief"], "problems": res.get("problems", []),
            "fit": res["fit"], "relations": res["relations"], "svg": res["svg"], "hash": res["hash"],
            "print_svg": res.get("print_svg"), "print": res.get("print"),
            "notes": m.get("notes", []), "nodes": len(m.get("nodes", [])), "lines": len(m.get("edges", [])),
            "saved": res.get("saved"), "freshness": res.get("freshness"), "placement": res.get("placement", "not-placed"),
            "agent": res.get("agent", {})}


def detail(project: dict[str, str], agents: Path, docx: Path | None, key: str) -> dict[str, Any]:
    if docx is None:
        return BLOCKED
    WK, ctx = _ctx(project, agents, docx)
    res = WK.figure(ctx, key)
    res["agent"] = WK.agent_notes(ctx.work, key)            # what the figure design agent wrote for this section
    return _shape(res)


def refresh(project: dict[str, str], agents: Path, docx: Path | None) -> dict[str, Any]:
    """Every figure the document needs, from the latest evidence: create the ones never saved, redraw the changed
    ones. The document is not changed: a placed figure that changed shows as out of date, to replace per figure."""
    if docx is None:
        return BLOCKED
    WK, ctx = _ctx(project, agents, docx)
    results = WK.refresh(ctx)
    return {**listing(project, agents, docx), "refreshed": results}


def save(project: dict[str, str], agents: Path, docx: Path | None, key: str) -> dict[str, Any]:
    if docx is None:
        return BLOCKED
    WK, ctx = _ctx(project, agents, docx)
    res = WK.figure(ctx, key, save=True)
    if res["svg"] is None:
        return {"state": "blocked", "reason": f"{res['row']['number']} {res['row']['title']}: this kind of figure is not built yet."}
    return {**_shape(res), "state": "saved"}


def edit_brief(project: dict[str, str], agents: Path, docx: Path | None, key: str, edits: dict[str, Any]) -> dict[str, Any]:
    """Your edits to the brief: wording (checked against the evidence) and items left in or out of the figure."""
    if docx is None:
        return BLOCKED
    WK, ctx = _ctx(project, agents, docx)
    from csa_docx.figures import brief as B
    clean = {k: edits.get(k) for k in ("purpose", "caption", "source") if isinstance(edits.get(k), str)}
    include = edits.get("include") if isinstance(edits.get("include"), dict) else None
    res = WK.figure(ctx, key, edits={**clean, "include": include, "by": "you"})
    if not res.get("problems"):
        B.save(ctx.work, key, res["brief"])
    return {**_shape(res), "state": "rejected" if res.get("problems") else "saved"}
