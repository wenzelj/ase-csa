from pathlib import Path

from backend.app import text_preview


def test_xml_preview_is_structured_but_preserves_original_lines(tmp_path: Path):
    path = tmp_path / "config.xml"; path.write_text('<root xmlns:x="urn:test">\n<x:item>value</x:item>\n</root>')
    result = text_preview(path, "config.xml lines 2-2")
    assert result["kind"] == "markup" and result["format"] == "xml"
    assert result["highlight"] == [2, 2]
    assert result["lines"][1]["text"] == "<x:item>value</x:item>"


def test_html_preview_never_returns_executable_html(tmp_path: Path):
    path = tmp_path / "capture.html"; path.write_text('<script>globalThis.pwned=true</script><iframe src="https://invalid.test"></iframe>')
    result = text_preview(path, None)
    assert result["kind"] == "markup"
    assert "lines" in result and "html" not in result


def test_large_markup_is_bounded(tmp_path: Path):
    path = tmp_path / "large.xml"; path.write_text("\n".join(f"<n>{i}</n>" for i in range(3000)))
    result = text_preview(path, None)
    assert result["truncated"] is True and len(result["lines"]) == 2000
