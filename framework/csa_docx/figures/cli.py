"""csa figures / csa figure: where the CSA needs a figure, and each figure's brief, drawing, fit check and placement.

  csa figures                         every section: needs a figure or not, and why
  csa figures --all --save            draw and save every figure that can be drawn
  csa figures --refresh               from the latest evidence: create figures never saved, redraw changed ones
  csa figure TIME                     brief + fit check for one section (drawn now, nothing saved)
  csa figure TIME --save              save it: csa-work/figures/TIME/ (brief, model, SVG, PNG, fit) + its gaps
  csa figure TIME --place             put the saved figure into the working document (tracked; approve in Word)
  csa figure TIME --place --drawing word   ... drawn as editable Word shapes instead of a picture
  csa figure TIME --brief-prompt      the prompt for the agent that rewords the purpose and caption
  csa figure TIME --wording FILE      apply an agent's wording (JSON {"purpose","caption"}), checked first

Run as: python -m csa_docx.figures.cli --project KEY [--docx DOCX] <verb> ...  (bin/csa passes these)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_FW = Path(__file__).resolve().parents[2]
if str(_FW) not in sys.path:                     # run as a script by bin/csa
    sys.path.insert(0, str(_FW))

from csa_docx.techdiagram.cli import AGENTS, _local, _network, _project  # noqa: E402


def _docx(p: dict, given: str | None) -> Path:
    if given:
        return Path(given).expanduser()
    root = _local(p["project_root"])
    found = [f for f in root.glob("01 Current State AS Built/01 Final Version/*.docx") if not f.name.startswith("~$")]
    if len(found) != 1:
        raise SystemExit(json.dumps({"status": "ERROR", "message": f"expected one working DOCX in {root}/01 Current State AS Built/"
                                                                    f"01 Final Version, found {len(found)}; pass --docx"}))
    return found[0]


def _ctx(a):
    from csa_docx.figures import work as WK
    p = _project(a.project)
    work = _local(p["work_dir"])
    return WK.open_ctx(a.project, work, _docx(p, a.docx), _network(work))


def _print(obj, as_json: bool, text: str) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False, default=str) if as_json else text)


def wording_prompt(brief: dict, out: Path) -> str:
    items = "\n".join(f"- {i['what']}" + (f" (the section says: \"{i['section_says']}\")" if i.get("section_says") else "")
                      for i in brief["items"] if i.get("include", True))
    gaps = "\n".join(f"- {g['what']}" for g in brief["gaps"]) or "- none"
    return f"""You write two short texts for one figure in a Current State Assessment. Australian English, plain words, no hype.

Section: {brief['number']} {brief['title']} ({', '.join(brief['requirements'])})
Question the figure answers: {brief.get('question') or ''}
What the figure shows (each item is backed by evidence):
{items}
Not captured (drawn as gaps):
{gaps}

Current purpose: {brief['purpose']['text']}
Current caption: {brief['caption']['text']}

Write:
- purpose: one sentence, at most 40 words, telling the reader of this section what the figure shows.
- caption: the finding the figure shows, at most 25 words, no full stop, no "Figure N:".

Rules: use only the hosts, addresses and numbers listed above. Add nothing the items do not say. Do not rate the requirement.
Write only this JSON to {out} and stop:
{{"purpose": "...", "caption": "..."}}
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--docx")
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("list"); s.add_argument("--all", action="store_true"); s.add_argument("--save", action="store_true")
    s.add_argument("--no-png", action="store_true"); s.add_argument("--refresh", action="store_true")
    f = sub.add_parser("figure"); f.add_argument("key")
    f.add_argument("--save", action="store_true"); f.add_argument("--place", action="store_true")
    f.add_argument("--no-png", action="store_true"); f.add_argument("--author")
    f.add_argument("--drawing", choices=["picture", "word"], default="picture",
                   help="--place: picture (the saved PNG) or word (editable Word shapes, same layout)")
    f.add_argument("--brief-prompt", metavar="OUT", help="print the wording agent's prompt; it writes its JSON to OUT")
    f.add_argument("--wording", metavar="FILE", help="apply the wording agent's JSON (checked first)")
    a = ap.parse_args(argv)
    sys.setrecursionlimit(5000)

    from csa_docx.figures import brief as B
    from csa_docx.figures import work as WK
    ctx = _ctx(a)
    if a.verb == "list":
        rows = [r for r in ctx.rows if r["status"] != "none"]
        saved = WK.manifest(ctx.work)
        if a.refresh:
            done = WK.refresh(ctx, png=not a.no_png)
            word = {"created": "created", "redrawn": "redrawn", "unchanged": "unchanged", "not-built": "not built", "error": "error"}
            text = "\n".join(f"{d['number']:>5} {d['title'][:40]:40} {word.get(d['action'], d['action']):10}"
                             + (" · in the document, out of date: replace it" if d.get("placement") == "out-of-date" else "")
                             + (f" {d['message']}" if d.get("message") else "") for d in done)
            _print({"status": "OK", "results": done}, a.json, text or "No section needs a figure.")
            return 0 if not any(d["action"] == "error" for d in done) else 2
        if a.all and a.save:
            done = []
            for r in rows:
                if r["status"] in ("needed", "helpful", "placed"):
                    try:
                        res = WK.figure(ctx, r["key"], save=True, png=not a.no_png)
                    except Exception as e:                       # one section failing must not stop the rest
                        done.append({"key": r["key"], "status": "ERROR", "message": f"{type(e).__name__}: {e}"}); continue
                    done.append({"key": r["key"], "status": "SAVED" if res["svg"] else "NOT_BUILT", "fit": res["fit"]["counts"],
                                 "gaps": len(res["brief"]["gaps"])})
            _print({"status": "OK", "saved": done}, a.json, "\n".join(f"{d['key']:22} {d['status']:9} {d.get('fit', '')}" for d in done))
            return 0
        text = "\n".join(f"{r['number']:>5} {r['title'][:44]:44} {r['status']:10} "
                         f"{'saved ' + saved[r['key']]['drawn'][:16] if r['key'] in saved else '':22} {r['reason'][:110]}" for r in rows)
        _print({"status": "OK", "document": ctx.docx.name, "rows": rows, "saved": saved}, a.json, text)
        return 0

    key = a.key.upper()
    if a.wording:
        cur = WK.figure(ctx, key)
        w = json.loads(Path(a.wording).read_text(encoding="utf-8"))
        res = WK.figure(ctx, key, save=True, png=not a.no_png,
                        edits={"purpose": w.get("purpose"), "caption": w.get("caption"), "by": "agent"}) if cur["svg"] else cur
        ok = not res.get("problems")
        _print({"status": "OK" if ok else "REJECTED", "problems": res.get("problems", []), "brief": res["brief"]}, a.json,
               "Wording applied." if ok else "Wording rejected, the framework's wording stays:\n- " + "\n- ".join(res["problems"]))
        return 0 if ok else 2
    if a.brief_prompt:
        cur = WK.figure(ctx, key)
        B.save(ctx.work, key, cur["brief"])
        print(wording_prompt(cur["brief"], Path(a.brief_prompt)))
        return 0
    if a.place:
        from csa_docx.figures.place import _author_from_cli
        res = WK.place(ctx, key, a.author or _author_from_cli(AGENTS), drawing=a.drawing)
        _print(res, a.json, f"{res['status']}: {res.get('message', '')}" + (f"\nBackup: {res['backup']}" if res.get("backup") else ""))
        return 0 if res["status"] == "OK" else 2
    res = WK.figure(ctx, key, save=a.save, png=not a.no_png)
    b = res["brief"]
    lines = [f"{res['row']['number']} {res['row']['title']}: {res['row']['status']} — {res['row']['reason']}", "",
             f"Purpose: {b['purpose']['text']}  ({b['purpose']['by']})", f"Caption: {b['caption']['text']}  ({b['caption']['by']})",
             b["source"]["text"], "", "Must show:"]
    lines += [f"  [{i['status']}{'' if i.get('include', True) else ', left out'}] {i['what']}  {', '.join(i.get('evidence', [])[:6])}"
              for i in b["items"]]
    lines += ["Gaps (to Discovery Required):"] + [f"  {g['what']}" for g in b["gaps"]] or ["  none"]
    lines += ["", f"Fit check: {res['fit']['counts']}"] + [f"  {c['level']:4} {c['kind']:8} {c['text']}" for c in res["fit"]["checks"]
                                                            if c["level"] != "ok"]
    lines += ["", "Saved." if a.save and res["svg"] else f"Figure: {res['freshness']}; in the document: {res.get('placement')}"]
    _print({k: v for k, v in res.items() if k not in ("svg", "model")}, a.json, "\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
