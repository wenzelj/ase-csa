---
name: mistune
description: "Use when parsing or rendering Markdown in Python — covers mistune's AST-first design, the block/inline token tree shape (including the `table` plugin), custom renderers, and plugin usage. Reach for this before hand-rolling regex-based Markdown parsing."
---

# mistune

## What it is

mistune is a fast, pure-Python Markdown parser (BSD-3-Clause, `github.com/lepture/mistune`, `pip install mistune`, no compiled dependencies). Current stable line is 3.x, which requires Python ≥ 3.8. It ships a CommonMark-ish core plus an opt-in plugin system (tables, strikethrough, footnotes, task lists, math, and more).

The key design point: mistune is **AST-first**. Rendering to HTML is just the default `renderer="html"` behavior — the same parse produces a structured token tree you can walk yourself, which is what makes it useful for *extracting data* out of Markdown (e.g. table contents, list structure) rather than only converting Markdown to another markup format.

## Core usage

```python
import mistune

# Default: parse and render straight to an HTML string.
html = mistune.html("# Title\n\nSome **text**.")

# AST mode: get the token tree instead of rendered output.
md = mistune.create_markdown(renderer=None, plugins=["table"])
tokens = md("| A | B |\n|---|---|\n| 1 | 2 |\n")
```

`mistune.create_markdown(renderer=None, plugins=[...])` is the pattern to reach for whenever you need to *read* Markdown structurally rather than convert it — `renderer=None` returns the raw AST (a list of block-level token dicts) instead of routing through a renderer.

## AST token shape

With `renderer=None`, `md(text)` returns a list of block tokens. Each token is a dict with a `"type"` key and type-specific children/attrs. The shapes that matter most:

- **Paragraph**: `{"type": "paragraph", "children": [...inline tokens...]}`
- **Table** (`table` plugin): `{"type": "table", "children": [table_head, table_body]}`
  - `table_head`: `{"type": "table_head", "children": [table_cell, ...]}` — one row of header cells
  - `table_body`: `{"type": "table_body", "children": [table_row, ...]}`
  - `table_row`: `{"type": "table_row", "children": [table_cell, ...]}`
  - `table_cell`: `{"type": "table_cell", "children": [...inline tokens...], "attrs": {"align": ..., "head": bool}}`
- **Inline tokens** inside any cell/paragraph: `{"type": "text", "raw": "..."}`, `{"type": "codespan", "raw": "..."}`, `{"type": "linebreak"}`, `{"type": "strong"/"emphasis", "children": [...]}`, `{"type": "link", "children": [...], "attrs": {"url": ...}}`, etc.

There is no single `.text` field on a cell — you have to walk `children` and concatenate the leaf text yourself. A small recursive helper covers the common case:

```python
def inline_text(node) -> str:
    """Flatten an inline AST node (or list of them) to plain text."""
    if isinstance(node, list):
        return "".join(inline_text(n) for n in node)
    t = node.get("type")
    if t in ("text", "codespan"):
        return node.get("raw", "")
    if t == "linebreak":
        return " "
    return inline_text(node.get("children", []))

def cell_text(cell) -> str:
    return inline_text(cell.get("children", [])).strip()
```

Enabling the `table` plugin is required for GFM-style pipe tables to parse into `table`/`table_head`/`table_body`/`table_row`/`table_cell` tokens at all — without it, a `| A | B |` block parses as an ordinary paragraph.

## Practical tips

- Use AST mode (`renderer=None`) for *extraction* tasks (pulling structured data — tables, headings, lists — out of an approved/authored Markdown fragment); use the default HTML renderer only when the goal is to actually render the Markdown for display.
- Enable only the plugins you need (`plugins=["table"]`, or add `"strikethrough"`, `"footnotes"`, `"task_lists"`, etc.) — plugins are opt-in per `create_markdown()` call, not global.
- `create_markdown()` returns a reusable parser object; build it once and call it repeatedly rather than re-constructing it per document.
- Prefer this over regex-based "parse the pipe table by splitting on `|`" code — mistune already handles escaped pipes, inline formatting inside cells, alignment markers (`:---`, `---:`, `:---:`), and header/body separation correctly, which hand-rolled splitting tends to get wrong on edge cases (a `|` inside a code span, an empty cell, a row with a different column count than the header).
- mistune has no compiled/binary dependency, so it vendors trivially (drop the unzipped wheel's `mistune/` package directory onto `sys.path`) into environments where `pip install` isn't available, and it isn't tied to a specific CPython ABI/platform — the same wheel works across Python versions/OSes unlike a compiled package such as rapidfuzz.

## Worked example: turning an approved Markdown table into row data

This is the shape used to take a small, trusted Markdown table (e.g. an approved replacement table in a change record) and turn it into a plain list-of-lists, first row treated as header:

```python
def parse_markdown_table(text: str) -> list[list[str]]:
    md = mistune.create_markdown(renderer=None, plugins=["table"])
    tokens = md(text)
    for block in tokens:
        if block.get("type") != "table":
            continue
        rows = []
        head, body = block["children"]
        rows.append([cell_text(c) for c in head["children"]])
        for row in body["children"]:
            rows.append([cell_text(c) for c in row["children"]])
        return rows
    raise ValueError("no table found in markdown text")
```
