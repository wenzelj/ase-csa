from __future__ import annotations


def find_soffice() -> str | None:
    """LibreOffice's converter: CSA_SOFFICE, then framework/vendor/LibreOffice.app, then PATH, then the standard macOS and Linux install locations
    (the macOS app is not on PATH by default)."""
    import os, shutil
    from pathlib import Path
    vendor = Path(__file__).resolve().parents[2] / "framework" / "vendor" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"
    for candidate in (os.environ.get("CSA_SOFFICE"), str(vendor), shutil.which("soffice"), shutil.which("libreoffice"),
                      "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                      str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice"),
                      "/opt/homebrew/bin/soffice", "/usr/local/bin/soffice", "/usr/bin/soffice",
                      "/usr/lib/libreoffice/program/soffice"):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None
