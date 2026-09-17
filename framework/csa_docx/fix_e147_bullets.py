#!/usr/bin/env python3
"""Fix E-147 bullet rendering: strip the literal '- ' prefix from the 3 newly
inserted Section 9.1 time-sync bullets. The framework's own bullet paths strip
the markdown prefix before writing run text, but my manual loop passed the
prefixed text. This removes only the leading '- ' from the 3 affected
paragraphs, preserving each bullet's ListParagraph pPr + list numbering.
"""
from __future__ import annotations
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from csa_docx.ooxml import DocumentEditor, paragraph_text
from csa_docx.docx_package import create_backup, extract_docx
from csa_docx.validator import validate_docx

ROOT = Path("/Users/wenzel/Work/ASE/IAMPS/06 IAMPS")
DOCX = ROOT / "01 Current State AS Built/7 IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx"

BULLETS = [
    "centralised time synchronisation is part of the documented IAMPS infrastructure model",
    "future-state design intends to transition relevant time services to OT-controlled infrastructure",
    "consistent time is considered relevant to the systems and integrations identified in the design",
]


def norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def main() -> int:
    backup = create_backup(DOCX, "9")
    print(f"backup: {backup}")

    fixed = 0
    pkg = extract_docx(DOCX)
    try:
        ed = DocumentEditor(pkg.path("word/document.xml"), section_heading=None)
        for i, p in enumerate(ed.paragraphs()):
            txt = " ".join(paragraph_text(p).split())
            if not txt.startswith("- "):
                continue
            remainder = txt[2:].strip().lower()
            if any(remainder == norm(b) for b in BULLETS):
                ed._set_paragraph_text(p, txt[2:].strip(), preserve_list=True)
                fixed += 1
                print(f"fixed paragraph@{i}: '{txt[:60]}...'")
        ed.save()
        pkg.save(DOCX)
    finally:
        pkg.cleanup()

    print(f"total fixed: {fixed} (expected 3)")
    if fixed != 3:
        print("WARNING: fix count != 3; manual review advised")
        return 1

    validation = validate_docx(DOCX)
    print("validation:", validation)
    if any(v != "Pass" for v in validation.values()):
        print("FAILED validation")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
