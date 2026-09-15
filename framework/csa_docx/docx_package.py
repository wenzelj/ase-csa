from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class DocxPackage:
    source: Path
    tempdir: Path

    def path(self, member: str) -> Path:
        return self.tempdir / member

    def save(self, output: Path | None = None) -> Path:
        target = output or self.source
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(self.tempdir.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(self.tempdir).as_posix())
        return target

    def cleanup(self) -> None:
        shutil.rmtree(self.tempdir, ignore_errors=True)


def create_backup(docx: Path, section: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_section = "".join(ch if ch.isalnum() else "_" for ch in str(section)).strip("_")
    backup = docx.with_name(f"{docx.name}.before_section_{safe_section}_{timestamp}.bak")
    shutil.copy2(docx, backup)
    if not backup.exists() or backup.stat().st_size == 0:
        raise RuntimeError(f"Backup was not created correctly: {backup}")
    return backup


def extract_docx(docx: Path) -> DocxPackage:
    if not docx.exists():
        raise FileNotFoundError(docx)
    tempdir = Path(tempfile.mkdtemp(prefix="csa-docx-"))
    with zipfile.ZipFile(docx) as archive:
        archive.extractall(tempdir)
    return DocxPackage(source=docx, tempdir=tempdir)


def test_zip(docx: Path) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(docx) as archive:
            bad = archive.testzip()
        if bad:
            return False, f"First corrupt member: {bad}"
        return True, "Archive integrity passed"
    except Exception as exc:
        return False, str(exc)
