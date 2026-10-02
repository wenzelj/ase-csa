"""The section brief skeleton for an author run (`csa brief N`), read from the document.

The questions come from the subsection itself (its requirement rows, tables, placeholders and reviewer
comments) through the document spec (`csa_docx.doc_spec`); the scope map's Must explain and Not here are
added when the section's requirement family or heading matches a scope-map domain. `N` may be a visible
number, a heading, a requirement family or a stamp key. The author agent copies the brief into the change
file under `## Section brief` and refines it; it does not invent it.

    python3 -m csa_docx.author_brief 3.1 [--docx working.docx] [--template T] [--out brief.md]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from csa_docx import doc_spec

_REQ = re.compile(r"(SEP-[A-Z]+-\d+)\s*(.*)")


def domain_key(section: str) -> str:
    """`3.1` and `3.1.2` both belong to the topic 3.1."""
    parts = str(section).strip().split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else str(section)


def requirement_items(requirements: str) -> list[tuple[str, str]]:
    """(ID, wording) for each requirement in a scope-map `Requirements` field (separated by `;`)."""
    out = []
    for chunk in requirements.split(";"):
        m = _REQ.match(chunk.strip())
        if m:
            out.append((m.group(1), m.group(2).strip().rstrip(".")))
    return out


def build(section: str, docx: Path | None = None, template: Path | None = None, spec: dict | None = None) -> dict:
    """{'status': 'OK', 'text', 'questions', 'comments', 'key', 'number'} or {'status': 'UNKNOWN_SECTION', 'message'}."""
    from csa_docx import section_card, spec_cli
    try:
        spec = spec or spec_cli.load(docx, template)
        node = doc_spec.resolve(spec, section)
    except (FileNotFoundError, doc_spec.ResolveError) as e:
        return {"status": "UNKNOWN_SECTION", "message": f"{e}; write the brief by hand"}
    qs = section_card.questions(node, spec)
    return {"status": "OK", "text": section_card.brief_markdown(node, spec), "key": node["key"], "number": node["number"],
            "questions": sum(1 for q in qs if q["id"].startswith("B")),
            "comments": sum(1 for q in qs if q["id"].startswith("C"))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section")
    ap.add_argument("--docx", type=Path)
    ap.add_argument("--template", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    res = build(a.section, a.docx, a.template)
    if res["status"] != "OK":
        print(res["message"], file=sys.stderr)
        return 1
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(res["text"], encoding="utf-8")
    print(res["text"], end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
