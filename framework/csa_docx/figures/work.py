"""One figure, end to end: brief, draw, fit check, save. Shared by `csa figures` and the Evidence Workspace page.

    ctx = open_ctx(project_key, work_dir, docx, net)
    figure(ctx, key, save=False) -> {"row", "brief", "svg", "model", "hash", "fit", "relations", "saved", "freshness"}
    refresh(ctx, keys=None) -> [{"key", "action": created | redrawn | unchanged | not-built | error, "placement", ...}]

Saving writes <work_dir>/figures/<KEY>/ (brief.json, model.json, figure.svg, figure.png, fit.json), the
manifest, and the figure's gaps into figures/gaps.json (they feed Discovery Required). The document is not
touched here; place.py puts a saved figure into the document as a tracked change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from csa_docx import doc_spec
from csa_docx.figures import brief as B
from csa_docx.figures import draw as D
from csa_docx.figures import fit as F
from csa_docx.figures import need as N
from csa_docx.figures import relations as R


@dataclass
class Ctx:
    project_key: str
    work: Path
    docx: Path
    net: dict
    journeys: dict
    spec: dict = field(default_factory=dict)
    ev: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    layout: dict = field(default_factory=dict)

    def row(self, key: str) -> dict:
        r = next((r for r in self.rows if r["key"] == key), None)
        if r is None:
            raise KeyError(key)
        return r

    def node(self, key: str) -> dict:
        return next(n for n in self.spec["nodes"] if n["key"] == key)


def open_ctx(project_key: str, work: Path, docx: Path, net: dict) -> Ctx:
    work = Path(work)
    jf = work / "explorer" / "journeys.json"
    try:
        journeys = json.loads(jf.read_text(encoding="utf-8")) if jf.is_file() else {}
    except json.JSONDecodeError:
        journeys = {}
    ctx = Ctx(project_key, work, Path(docx), net, journeys)
    ctx.spec = doc_spec.read(str(docx))
    ctx.ev = R.load(work)
    ctx.rows = N.assess(ctx.spec, work, project_key, ev=ctx.ev)
    ctx.layout = N.load_layout(project_key)
    return ctx


def manifest(work: Path) -> dict:
    try:
        return json.loads((Path(work) / "figures" / "manifest.json").read_text(encoding="utf-8")).get("figures", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _service(row: dict) -> str | None:
    return next((p.get("service") for p in N.load_profiles() if p["id"] == row.get("profile")), None)


def figure(ctx: Ctx, key: str, save: bool = False, png: bool = True, edits: dict | None = None) -> dict:
    row = ctx.row(key)
    old = B.load(ctx.work, key)
    try:
        out = D.draw(row, ctx.work, ctx.project_key, ctx.net, ctx.journeys, ev=ctx.ev, brief=old)
    except D.NotBuilt:
        out = None
    service = _service(row)
    rel = N.scope_relations(service, ctx.ev, ctx.layout) if row.get("archetype") == "B" and service and out else []
    brief = B.build(row, ctx.node(key), ctx.ev, ctx.layout, rel, out["model"] if out else None, old=old)
    problems: list[str] = []
    if edits:
        brief, problems = B.edit(brief, edits.get("purpose"), edits.get("caption"), edits.get("source"),
                                 edits.get("include"), by=edits.get("by", "you"))
        if not problems and edits.get("include") is not None and out:          # an item left out: draw again without it
            out = D.draw(row, ctx.work, ctx.project_key, ctx.net, ctx.journeys, ev=ctx.ev, brief=brief)
    names = set(ctx.ev["register"])
    fit = F.check(ctx.node(key), brief, out["model"], rel, names,
                                      {h: r.get("ips") or "" for h, r in ctx.ev["register"].items()}) if out else {"checks": [], "counts": {}}
    if out and row.get("archetype") == "F":            # data flow figures: the figure against the Discovery Information tables
        from csa_docx import flows as FL
        from csa_docx.figures import flowview as FV
        prof_ = next((p for p in N.load_profiles() if p["id"] == row.get("profile")), {})
        flt_ = prof_.get("flows") or FV.topic_flows(prof_.get("from_topic"))
        fit["checks"] += F.check_flow_tables(out["model"], FL.load(ctx.work), FV._settings(ctx.work), flt_, set(names))
        fit["counts"] = {lv: sum(1 for c in fit["checks"] if c["level"] == lv) for lv in ("ok", "note", "flag")}
    if out and out.get("print"):
        F.print_checks(fit, out["print"])
    saved = manifest(ctx.work).get(key)
    result = {"row": row, "brief": brief, "problems": problems, "svg": out["svg"] if out else None,
              "print_svg": out.get("print_svg") if out else None, "print": out.get("print") if out else None,
              "model": out["model"] if out else None, "hash": out["hash"] if out else None, "fit": fit,
              "relations": [r for r in rel if (r["provider"], r["state"]) not in B.excluded(brief)],
              "saved": saved, "freshness": "not-saved"}
    if out and saved:
        result["freshness"] = "current" if saved.get("hash") == out["hash"] else "changed"
    result["placement"] = placement(saved, out["hash"] if out else None)
    if save and out:
        B.save(ctx.work, key, brief)
        entry = D.save(row, out, ctx.work, png=png)
        entry_extra = {"caption": brief["caption"]["text"], "source": brief["source"]["text"], "fit": fit["counts"],
                       "gaps": len(brief["gaps"])}
        _manifest_update(ctx.work, key, entry_extra)
        F.save(ctx.work, key, fit)
        save_gaps(ctx.work, key, row, brief)
        try:                                               # the figure on its own, as an editable Word drawing
            from csa_docx.techdiagram.word_docx import write_docx
            d = ctx.work / "figures" / key
            write_docx(d / "figure.docx", out["model"], f"{row.get('number', '')} {row['title']}".strip(),
                       brief["caption"]["text"], brief["source"]["text"], out["model"].get("notes"),
                       aggregate=row.get("archetype") in ("A", "C"), png=d / "figure.png" if (d / "figure.png").is_file() else None,
                       svg=out.get("print_svg"))
            _manifest_update(ctx.work, key, {"docx": f"figures/{key}/figure.docx"})
        except Exception as e:                             # the figure itself is saved; report, do not fail
            _manifest_update(ctx.work, key, {"docx": None, "docx_error": f"{type(e).__name__}: {e}"})
        result["saved"] = {**entry, **entry_extra}
        result["freshness"] = "current"
    elif save and edits and not problems:
        B.save(ctx.work, key, brief)
    return result


NEEDS = ("needed", "helpful", "placed")


def refresh(ctx: Ctx, keys: list[str] | None = None, png: bool = True) -> list[dict]:
    """Draw every figure the document needs from the latest evidence: save the ones never saved (created) and the
    ones whose evidence or brief changed (redrawn); leave current ones alone. A placed figure whose drawing changed
    is reported out of date in the document; replacing it there stays a tracked change you run per figure.
    The result is kept in figures/refresh.json for the Figures page."""
    import time
    out = []
    for r in ctx.rows:
        if r["status"] not in NEEDS or (keys and r["key"] not in keys):
            continue
        item = {"key": r["key"], "number": r.get("number", ""), "title": r["title"]}
        try:
            cur = figure(ctx, r["key"])
            if cur["svg"] is None:
                out.append({**item, "action": "not-built"}); continue
            before = cur["freshness"]
            res = cur if before == "current" else figure(ctx, r["key"], save=True, png=png)
            out.append({**item, "action": {"not-saved": "created", "changed": "redrawn"}.get(before, "unchanged"),
                        "placement": res.get("placement"), "fit": res["fit"]["counts"], "gaps": len(res["brief"]["gaps"])})
        except Exception as e:                       # one section failing must not stop the rest
            out.append({**item, "action": "error", "message": f"{type(e).__name__}: {e}"})
    rep_path = Path(ctx.work) / "figures" / "refresh.json"
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": out}, indent=1, ensure_ascii=False),
                        encoding="utf-8")
    return out


def last_refresh(work: Path) -> dict | None:
    try:
        return json.loads((Path(work) / "figures" / "refresh.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


AGENT_FILES = {"design": "design.md", "review": "review.md", "build": "build-report.md"}


def agent_notes(work: Path, key: str) -> dict:
    """What the figure design agent wrote for this section: its design, review and build report."""
    import time
    d = Path(work) / "figures" / key
    out = {}
    for mode, name in AGENT_FILES.items():
        f = d / name
        if f.is_file():
            out[mode] = {"text": f.read_text(encoding="utf-8", errors="replace")[:60000],
                         "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(f.stat().st_mtime))}
    return out


def _manifest_update(work: Path, key: str, extra: dict) -> None:
    p = Path(work) / "figures" / "manifest.json"
    try:
        man = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        man = {"figures": {}}
    man["figures"].setdefault(key, {}).update(extra)
    p.write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ gaps -> Discovery Required
def gaps_path(work: Path) -> Path:
    return Path(work) / "figures" / "gaps.json"


def load_gaps(work: Path) -> dict:
    try:
        return json.loads(gaps_path(work).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_gaps(work: Path, key: str, row: dict, brief: dict) -> None:
    """The figure's gaps, one Discovery Required candidate each (DR-<KEY>-Fnn)."""
    allg = load_gaps(work)
    allg[key] = [{"dr_id": f"DR-{key}-F{i:02d}", "text": g["what"], "reqs": g.get("requirements", []),
                  "fact": g.get("why", ""), "section": f"{row.get('number', '')} {row['title']}".strip()}
                 for i, g in enumerate(brief.get("gaps", []), 1)]
    if not allg[key]:
        allg.pop(key)
    gaps_path(work).parent.mkdir(parents=True, exist_ok=True)
    gaps_path(work).write_text(json.dumps(allg, indent=1, ensure_ascii=False), encoding="utf-8")


def all_gaps(work: Path) -> list[dict]:
    return [g for gs in load_gaps(work).values() for g in gs]


# ------------------------------------------------------------------ into the document
DRAWINGS = ("picture", "word")
LAYOUTS = ("print", "screen")


def place(ctx: Ctx, key: str, author: str, close_word: bool = True, drawing: str = "picture", layout: str = "print") -> dict:
    """drawing: "picture" puts the saved PNG in; "word" draws the figure as editable Word shapes (same layout)."""
    """Put the saved figure into the working document (tracked). The figure must be saved and still match the
    evidence, so what goes into the document is exactly what was checked."""
    from csa_docx.figures import place as P
    cur = figure(ctx, key)
    if cur["svg"] is None:
        return {"status": "BLOCKED", "message": f"{cur['row']['number']} {cur['row']['title']}: this kind of figure is not built yet"}
    if cur["freshness"] != "current":
        return {"status": "BLOCKED", "message": "Save the figure first: the saved figure does not match the current evidence"
                if cur["freshness"] == "changed" else "Save the figure first"}
    if layout not in LAYOUTS:
        return {"status": "BLOCKED", "message": f"layout must be one of {', '.join(LAYOUTS)}"}
    png = ctx.work / "figures" / key / ("figure-screen.png" if layout == "screen" else "figure.png")
    if not png.is_file():
        name = "screen-view PNG" if layout == "screen" else "PNG"
        return {"status": "BLOCKED", "message": f"the saved figure has no {name} (save the figure first)"
                if layout == "screen" else "the saved figure has no PNG (no renderer was available when it was saved)"}
    if drawing not in DRAWINGS:
        return {"status": "BLOCKED", "message": f"drawing must be one of {', '.join(DRAWINGS)}"}
    node = ctx.node(key)
    word = {"model": cur["model"], "aggregate": cur["row"].get("archetype") in ("A", "C")} if drawing == "word" else None
    res = P.place(ctx.docx, node["title"], node["level"], key, png, cur["brief"]["caption"]["text"],
                  cur["brief"]["source"]["text"], author, close_word=close_word, word=word)
    if res["status"] == "OK":
        import time
        _manifest_update(ctx.work, key, {"placed": {"hash": cur["hash"], "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                    "mode": res["mode"], "document": ctx.docx.name, "drawing": drawing, "layout": layout}})
    return res


def placement(saved: dict | None, current_hash: str | None) -> str:
    """not-placed | placed | out-of-date (placed from a figure the evidence has since changed)."""
    p = (saved or {}).get("placed")
    if not p:
        return "not-placed"
    return "placed" if not current_hash or p.get("hash") == current_hash else "out-of-date"
