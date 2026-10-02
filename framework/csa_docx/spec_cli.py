"""`csa spec`: the document spec of a project's working document, joined with its template.

    python3 -m csa_docx.spec_cli --docx D [--template T] [--work-dir W] status
    python3 -m csa_docx.spec_cli ... show <target>          one section: parts, questions, guidance
    python3 -m csa_docx.spec_cli ... resolve <target>       number, key and title as JSON (for the CLI)
    python3 -m csa_docx.spec_cli ... lint
    python3 -m csa_docx.spec_cli ... stamp [--confirm] [--dry-run]

<target> is a visible number (3.4), a heading ("Time Synchronisation"), a requirement family (TIME) or a
stamp key. The template part is cached in WORK_DIR/spec/ per template file; the document is read every run.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

from csa_docx import doc_spec, doc_stamp


DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "CSA Template"


def find_template(start: Path | None) -> Path | None:
    """The highest CSA_Template_v*.dotx in the nearest `CSA Template` folder above `start`, else the shared
    `CurrentStateAssessments/CSA Template`."""
    dirs = ([Path(start)] + list(Path(start).parents)) if start else []
    for d in dirs + [DEFAULT_TEMPLATE_DIR.parent]:
        folder = d / "CSA Template"
        found = sorted(folder.glob("CSA_Template_v*.dotx"), key=_version) if folder.is_dir() else []
        if found:
            return found[-1]
    return None


def _version(p: Path) -> tuple:
    m = re.search(r"v(\d+(?:\.\d+)*)", p.stem)
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def template_spec(template: Path | None, work_dir: Path | None) -> dict | None:
    if not template or not Path(template).is_file():
        return None
    template = Path(template)
    if work_dir:
        cache = Path(work_dir) / "spec" / f"template-{template.stem}.json"
        st = template.stat()
        stamp = f"{st.st_size}:{int(st.st_mtime)}"
        if cache.is_file():
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if data.get("_file_stamp") == stamp:
                    return data
            except ValueError:
                pass
        data = doc_spec.read(template)
        data["_file_stamp"] = stamp
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return data
    return doc_spec.read(template)


def load(docx: Path | None, template: Path | None = None, work_dir: Path | None = None) -> dict:
    """The joined spec. With no working document the template itself is the document."""
    template = template or find_template(Path(docx).parent if docx else None)
    tspec = template_spec(template, work_dir)
    if docx and Path(docx).is_file():
        spec = doc_spec.join(doc_spec.read(docx), tspec)
    elif tspec:
        spec = json.loads(json.dumps(tspec))
        for n in spec["nodes"]:
            n["template"] = True
            n["template_parts"] = n["parts"]
    else:
        raise FileNotFoundError("no working document and no CSA template found")
    spec["template_file"] = str(template) if template else None
    return spec


def word_has_open(docx: Path) -> bool:
    """Word keeps an owner file `~$` + the name (first two characters dropped for long names) beside an open file."""
    d = Path(docx)
    return any(p.name.startswith("~$") and (p.name[2:] in d.name or d.name.endswith(p.name[2:]))
               for p in d.parent.glob("~$*"))


def stamp(docx: Path, spec: dict, template_spec_: dict | None, work_dir: Path | None, *,
          confirm: bool = False, dry_run: bool = False) -> dict:
    pl = doc_stamp.plan(doc_spec.read(docx), template_spec_, confirm)
    pl["docx"] = str(docx)
    if dry_run or not pl["stamp"]:
        pl["status"] = "DRY_RUN" if dry_run else "NOTHING_TO_STAMP"
        return pl
    if word_has_open(docx):
        pl["status"] = "LOCKED"
        pl["message"] = f"{Path(docx).name} is open in Word; close it and run again"
        return pl
    backup_dir = (Path(work_dir) if work_dir else Path(docx).parent) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{Path(docx).stem}.before-stamp-{time.strftime('%Y%m%d-%H%M%S')}{Path(docx).suffix}"
    shutil.copy2(docx, backup)
    pl["backup"] = str(backup)
    pl["done"] = doc_stamp.stamp_file(Path(docx), Path(docx), pl["stamp"])
    pl["status"] = "STAMPED"
    return pl


def status_table(spec: dict) -> str:
    doc_spec.derive(spec)
    lines = [f"{'Number':<7} {'Key':<30} {'Kind':<18} {'Open':>9}  Title"]
    for n in spec["nodes"]:
        st = n["status"]
        open_ = f"{st['open']}/{st['total']}" if st["total"] else "-"
        if n.get("derived") and st["state"] in ("open", "partial") and not n["derived"]["ready"]:
            open_ = "waiting"
        mark = "" if n.get("stamp") else " (unstamped)" if n["level"] <= 2 and doc_spec.fillable(n) else ""
        lines.append(f"{n['number']:<7} {n['key']:<30} {n['kind']:<18} {open_:>9}  {'  ' * (n['level'] - 1)}{n['title']}{mark}")
    for r in spec.get("removed", []):
        lines.append(f"{'-':<7} {r['key']:<30} {'removed':<18} {'':>9}  {r['title']} (in the template, not in the document)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docx", type=Path)
    ap.add_argument("--template", type=Path)
    ap.add_argument("--work-dir", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("action", choices=["status", "show", "resolve", "lint", "stamp", "next"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        spec = load(a.docx, a.template, a.work_dir)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    if a.action == "status":
        print(json.dumps(spec, indent=1) if a.json else status_table(spec))
        return 0
    if a.action in ("show", "resolve"):
        try:
            n = doc_spec.resolve(spec, a.target or "")
        except doc_spec.ResolveError as e:
            print(json.dumps({"status": "ERROR", "message": str(e)}) if a.json or a.action == "resolve" else str(e),
                  file=sys.stdout if a.action == "resolve" else sys.stderr)
            return 1
        if a.action == "resolve":
            print(json.dumps({"status": "OK", "number": n["number"], "key": n["key"], "title": n["title"],
                              "kind": n["kind"], "stamp": n.get("stamp"), "level": n["level"], "hid": n["hid"],
                              "path": n["path"]}))
            return 0
        if a.json:
            print(json.dumps(dict(n, ratings=spec.get("ratings")), indent=1))
        else:
            from csa_docx import section_card
            print(doc_spec._show(n))
            print()
            print(section_card.brief_markdown(n, spec))
        return 0
    if a.action == "next":
        todo = doc_spec.next_nodes(spec)
        rows = [{"number": n["number"], "key": n["key"], "title": n["title"], "kind": n["kind"],
                 "open": n["status"]["open"], "command": (n.get("derived") or {}).get("command")
                 or (f"csa author {n['key']} --cards" if n["kind"] == "requirement-block" else f"csa write {n['number'] or n['key']}")}
                for n in todo]
        print(json.dumps(rows, indent=1) if a.json else "\n".join(f"{r['number']:<6} {r['key']:<28} {r['command']}" for r in rows)
              or "every section is answered")
        return 0
    if a.action == "lint":
        f = doc_spec.lint(spec)
        if a.json:
            print(json.dumps(f, indent=1))
        else:
            print("\n".join(f"{x['level']:<5} {x['code']:<24} {x['message']}" for x in f) or "no findings")
        return 1 if any(x["level"] == "ERROR" for x in f) else 0
    if a.action == "stamp":
        if not a.docx:
            print("stamp needs --docx", file=sys.stderr)
            return 2
        tspec = template_spec(a.template or find_template(a.docx.parent), a.work_dir)
        res = stamp(a.docx, spec, tspec, a.work_dir, confirm=a.confirm, dry_run=a.dry_run)
        if a.json:
            print(json.dumps(res, indent=1))
        else:
            print(f"{res['status']}: {len(res['stamp'])} to stamp, {len(res['keep'])} already stamped, {len(res['ask'])} need --confirm")
            for k in res.get("done", []):
                print(f"  stamped {k['number']:<6} {k['stamp']}")
            for k in res["ask"]:
                print(f"  ask     {k['number']:<6} {k['title']} -> {k['key']}  ({k['reason']})")
            if res.get("backup"):
                print(f"  backup: {res['backup']}")
            if res.get("message"):
                print("  " + res["message"])
        return 1 if res["status"] == "LOCKED" else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
