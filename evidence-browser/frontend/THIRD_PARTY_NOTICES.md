# Third-party source-view dependencies

The readable XML/HTML source viewer uses pinned CodeMirror 6 packages:

- `@codemirror/view` 6.38.6 — MIT
- `@codemirror/state` 6.5.2 — MIT
- `@codemirror/lang-xml` 6.1.0 — MIT
- `@codemirror/search` 6.5.11 — MIT

Captured markup is supplied only as editor text. It is never mounted as HTML, and captured scripts, styles, frames, redirects, handlers, and remote resources are never executed or requested.
