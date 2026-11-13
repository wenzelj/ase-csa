"""S587: `csa v2 export | host | report` — on-demand exports from csa-work-v2/csa.sqlite.

    python3 -m csa_docx.v2_export_cli [--v2-dir DIR] export --table hosts --out exports/hosts.csv
    python3 -m csa_docx.v2_export_cli export --table evidence --status VERIFIED --out e.csv
    python3 -m csa_docx.v2_export_cli host ROTPRDREV101 --out exports/hosts/ROTPRDREV101.md
    python3 -m csa_docx.v2_export_cli report --out exports/REPORT.md

The v2 dir comes from `--v2-dir`, otherwise from the active project's work dir (the
`CSA_WORK_DIR` the `csa` command sets) when that ends in `csa-work-v2`. Exports are snapshots:
they never change the database.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .v2repo import DB_NAME, Repo


def _resolve_v2_dir(explicit):
    if explicit:
        return Path(explicit)
    wd = os.environ.get("CSA_WORK_DIR", "")
    if wd and Path(wd).name == "csa-work-v2":
        return Path(wd)
    return None


def _fail(msg):
    print(f"v2 export: {msg}", file=sys.stderr)
    return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m csa_docx.v2_export_cli",
                                 description="On-demand exports from csa-work-v2.")
    ap.add_argument("--v2-dir", help="the csa-work-v2 folder (default: the active project's work dir "
                                     "when it ends in csa-work-v2)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write a table (or filtered subset) as CSV")
    e.add_argument("--table", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--status")
    e.add_argument("--area")
    e.add_argument("--review-state", dest="review_state")
    e.add_argument("--state")
    h = sub.add_parser("host", help="write a per-host Markdown card")
    h.add_argument("host")
    h.add_argument("--out", required=True)
    r = sub.add_parser("report", help="write the one-page summary")
    r.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    v2 = _resolve_v2_dir(a.v2_dir)
    if v2 is None:
        return _fail("no csa-work-v2 folder: pass --v2-dir, or run from a project whose work dir "
                     "ends in csa-work-v2.")
    if not (v2 / DB_NAME).is_file():
        return _fail(f"{v2 / DB_NAME} does not exist. Run the S586 migration first "
                     "(python3 -m csa_docx.v2migrate --project-root <root> --v2-dir <dir>).")

    repo = Repo(v2)
    try:
        if a.cmd == "export":
            filters = {k: getattr(a, k) for k in ("status", "area", "review_state", "state")
                       if getattr(a, k) is not None}
            res = repo.export.csv(a.table, a.out, **filters)
            print(f"wrote {res['rows']} row(s) of {a.table} to {res['out']}")
        elif a.cmd == "host":
            res = repo.export.md(a.host, a.out)
            print(f"wrote {res['out']}")
        else:
            res = repo.export.report(a.out)
            print(f"wrote {res['out']}")
    except KeyError:
        return _fail(f"no host named {a.host!r} in {v2 / DB_NAME}.")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
