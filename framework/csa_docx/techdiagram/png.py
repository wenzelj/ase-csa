"""SVG to PNG for the Word figure. Uses whatever renderer the machine has, in this order:
Python Playwright, a headless Chrome/Chromium, rsvg-convert, cairosvg. Returns (path or None, how)."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CHROMES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Chromium.app/Contents/MacOS/Chromium", "google-chrome", "chromium", "chromium-browser"]


def _size(svg: str) -> tuple[int, int]:
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    return (int(float(m.group(1))), int(float(m.group(2)))) if m else (1600, 1200)


def to_png(svg_path: Path, png_path: Path, scale: int = 2) -> tuple[Path | None, str]:
    svg = svg_path.read_text(encoding="utf-8")
    w, h = _size(svg)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page(device_scale_factor=scale, viewport={"width": w, "height": h})
            pg.goto(svg_path.resolve().as_uri()); pg.query_selector("svg").screenshot(path=str(png_path)); b.close()
        return png_path, "playwright"
    except Exception:
        pass
    for c in CHROMES:
        exe = c if Path(c).exists() else shutil.which(c)
        if not exe:
            continue
        with tempfile.TemporaryDirectory() as td:
            page = Path(td) / "fig.html"
            page.write_text(f'<!doctype html><html><body style="margin:0">{svg}</body></html>', encoding="utf-8")
            r = subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--force-device-scale-factor={scale}",
                                f"--window-size={w},{h}", f"--screenshot={png_path}", page.as_uri()], capture_output=True, timeout=120)
        if r.returncode == 0 and png_path.is_file():
            return png_path, "chrome"
    if shutil.which("rsvg-convert"):
        r = subprocess.run(["rsvg-convert", "-z", str(scale), "-o", str(png_path), str(svg_path)], capture_output=True)
        if r.returncode == 0:
            return png_path, "rsvg-convert"
    try:
        import cairosvg
        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), scale=scale)
        return png_path, "cairosvg"
    except Exception:
        pass
    return None, "no SVG renderer found (install Playwright, Chrome, rsvg-convert or cairosvg)"
