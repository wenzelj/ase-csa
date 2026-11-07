import { useEffect, useMemo, useRef, useState } from "react";
import { EditorState } from "@codemirror/state";
import { EditorView, highlightActiveLine, keymap, lineNumbers } from "@codemirror/view";
import { defaultHighlightStyle, foldGutter, syntaxHighlighting } from "@codemirror/language";
import { searchKeymap } from "@codemirror/search";
import { xml } from "@codemirror/lang-xml";

type SourceLine = { number: number; text: string };

function formatMarkup(source: string): { text: string; warning?: string } {
  if (source.length > 1_500_000) return { text: source, warning: "Formatting was skipped because this source window is too large." };
  try {
    const tokens = source.replace(/>\s*</g, "><").split(/(?=<)|(?<=>)/).filter(Boolean);
    let depth = 0;
    const output: string[] = [];
    for (const token of tokens) {
      const value = token.trim();
      if (!value) continue;
      if (/^<\//.test(value)) depth = Math.max(0, depth - 1);
      output.push(`${"  ".repeat(depth)}${value}`);
      if (/^<[^!?/][^>]*>$/.test(value) && !/\/>$/.test(value) && !/<\/[^>]+>$/.test(value)) depth += 1;
    }
    return { text: output.join("\n") || source };
  } catch {
    return { text: source, warning: "This markup could not be formatted safely. Showing escaped original source." };
  }
}

export function MarkupViewer({ name, format, lines, highlight, truncated, totalLines }: { name: string; format: string; lines: SourceLine[]; highlight?: [number, number]; truncated?: boolean; totalLines?: number }) {
  const [mode, setMode] = useState<"formatted" | "original">("formatted");
  const host = useRef<HTMLDivElement>(null);
  const original = useMemo(() => lines.map(line => line.text).join("\n"), [lines]);
  const formatted = useMemo(() => formatMarkup(original), [original]);
  const cited = highlight ? lines.filter(line => line.number >= highlight[0] && line.number <= highlight[1]) : [];

  useEffect(() => {
    if (mode !== "formatted" || !host.current) return;
    const state = EditorState.create({ doc: formatted.text, extensions: [
      lineNumbers(), foldGutter(), highlightActiveLine(), xml(), syntaxHighlighting(defaultHighlightStyle),
      keymap.of(searchKeymap), EditorState.readOnly.of(true), EditorView.editable.of(false),
      EditorView.theme({ "&": { height: "100%" }, ".cm-scroller": { overflow: "auto", fontFamily: "IBM Plex Mono, monospace" } }),
    ] });
    const view = new EditorView({ state, parent: host.current });
    return () => view.destroy();
  }, [mode, formatted.text]);

  return <section className="markup-viewer" aria-label={`${format.toUpperCase()} source viewer for ${name}`}>
    <header><div><strong>{format.toUpperCase()} structure</strong><small>Formatted for reading; citations continue to use original line numbers.</small></div><div className="markup-modes"><button className={mode === "formatted" ? "active" : ""} onClick={() => setMode("formatted")}>Formatted</button><button className={mode === "original" ? "active" : ""} onClick={() => setMode("original")}>Original source</button></div></header>
    {formatted.warning && <p className="markup-warning" role="status">{formatted.warning}</p>}
    {cited.length > 0 && <section className="citation-strip" aria-label="Cited original lines"><strong>Original citation {highlight?.[0]}–{highlight?.[1]}</strong>{cited.map(line => <div key={line.number}><span>{line.number}</span><code>{line.text || " "}</code></div>)}</section>}
    {mode === "formatted" ? <div className="markup-editor" ref={host} /> : <div className="source-lines markup-original">{lines.map(line => <div key={line.number} className={highlight && line.number >= highlight[0] && line.number <= highlight[1] ? "highlight" : ""}><span>{line.number}</span><code>{line.text || " "}</code></div>)}</div>}
    {truncated && <footer>Showing a bounded source window from {totalLines?.toLocaleString() || "many"} original lines.</footer>}
  </section>;
}
