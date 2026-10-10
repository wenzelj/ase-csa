"""One self-contained HTML page holding a project's diagrams (the same SVGs as the CSA figures).
Select a system or a line to see its evidence; Escape clears."""
from __future__ import annotations

import html
import json


def make_html(title: str, diagrams: list[dict]) -> str:
    data = {d["id"]: d["model"] for d in diagrams}
    tabs = "".join(f'<button class="tab" data-stem="{html.escape(d["id"])}">{html.escape(d["title"])}</button>' for d in diagrams)
    svgs = "".join(f'<div class="diagram" data-stem="{html.escape(d["id"])}">{d["svg"]}</div>' for d in diagrams)
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f8fa;--panel:#fff;--ink:#1f2328;--muted:#57606a;--line:#d0d7de;--accent:#0969da}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 "Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
header{display:flex;gap:8px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel);flex-wrap:wrap}
header h1{font-size:15px;margin:0 12px 0 0}
.tab{border:1px solid var(--line);background:#fff;border-radius:6px;padding:5px 10px;cursor:pointer;font:inherit}
.tab[aria-selected=true]{background:var(--ink);color:#fff;border-color:var(--ink)}
main{display:grid;grid-template-columns:1fr 340px;height:calc(100vh - 52px)}
.stage{overflow:auto;background:#fff}.stage svg{display:block;width:100%;height:auto;min-width:1100px}.diagram[data-stem$=overview] svg{min-width:1700px}
aside{border-left:1px solid var(--line);background:var(--panel);padding:16px;overflow:auto}
aside h2{font-size:16px;margin:0 0 2px}aside .k{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
aside dl{margin:12px 0;display:grid;grid-template-columns:96px 1fr;gap:4px 8px}aside dt{color:var(--muted)}aside dd{margin:0;word-break:break-word}
aside ul{padding-left:18px;margin:6px 0}aside li{margin:3px 0}.ev{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--muted)}
.hint{color:var(--muted)}
svg .node,svg .edge{cursor:pointer;transition:opacity .15s}
svg.dim .node:not(.on),svg.dim .edge:not(.on),svg.dim .group:not(.on){opacity:.15}
svg .node.sel rect:first-child{stroke:var(--accent);stroke-width:2.4}
svg .node:focus{outline:none}svg .node:focus-visible rect:first-child{stroke:var(--accent);stroke-width:2.4}
@media (max-width:800px){main{grid-template-columns:1fr;height:auto}aside{border-left:0;border-top:1px solid var(--line)}}
@media (prefers-reduced-motion:reduce){svg .node,svg .edge{transition:none}}
</style></head><body>
<header><h1>__TITLE__</h1>__TABS__</header>
<main><div class="stage" id="stage">__SVGS__</div>
<aside id="panel"><p class="hint">Select a system or a line to see what the evidence says about it. Select empty space to clear.</p></aside></main>
<script>
const DATA = __DATA__;
const KIND = {database:"Database server",app_server:"Application server",logging:"Log server",jump_host:"Jump host",terminal:"Operator workstation",radio:"Radio management",directory:"Domain controller · DNS",internal:"Internal addresses",internet:"Internet",backup:"Backup target",mail:"Mail",unknown:"Role not recorded"};
const STATUS = {observed:"Observed in connection captures",configured:"Configured setting",inferred:"Inferred — validate",documented:"Documented only, not observed",unknown:"Path not captured"};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let cur = null;
function show(stem){
  cur = stem;
  document.querySelectorAll(".tab").forEach(t => t.setAttribute("aria-selected", t.dataset.stem === stem));
  document.querySelectorAll(".diagram").forEach(d => d.hidden = d.dataset.stem !== stem);
  clear();
}
function m(){ return DATA[cur]; }
function members(end){
  const M = m();
  if (end.startsWith("Z:")) return M.nodes.filter(n => n.zone === end.slice(2)).map(n => n.id);
  if (end.startsWith("SG:")) return (M.groups.find(g => g.id === end) || {members:[]}).members;
  return [end];
}
function endName(end){
  const M = m();
  if (end.startsWith("Z:")) return (M.zones.find(z => z.id === end.slice(2)) || {}).label + " (site)";
  if (end.startsWith("SG:")) return (M.groups.find(g => g.id === end) || {}).label;
  const n = M.nodes.find(n => n.id === end); return n ? n.label : end;
}
function svg(){ return document.querySelector(`.diagram[data-stem="${cur}"] svg`); }
function clear(){
  const s = svg(); if (!s) return;
  s.classList.remove("dim"); s.querySelectorAll(".on,.sel").forEach(e => e.classList.remove("on","sel"));
  document.getElementById("panel").innerHTML = '<p class="hint">Select a system or a line to see what the evidence says about it. Select empty space to clear.</p>';
}
function light(ids, edgeIds){
  const s = svg(); s.classList.add("dim");
  s.querySelectorAll(".node,.edge,.group").forEach(e => e.classList.remove("on","sel"));
  ids.forEach(id => s.querySelector(`.node[data-id="${CSS.escape(id)}"]`)?.classList.add("on"));
  edgeIds.forEach(id => s.querySelectorAll(`.edge[data-id="${CSS.escape(id)}"]`).forEach(x => x.classList.add("on")));
  s.querySelectorAll(".group").forEach(g => { if (members(g.dataset.id).some(x => ids.includes(x))) g.classList.add("on"); });
}
function pickNode(id){
  const M = m(), n = M.nodes.find(x => x.id === id);
  const es = M.edges.filter(e => members(e.s).includes(id) || members(e.t).includes(id));
  const ids = new Set([id]); es.forEach(e => [...members(e.s), ...members(e.t)].forEach(x => ids.add(x)));
  light([...ids], es.map(e => e.id));
  svg().querySelector(`.node[data-id="${CSS.escape(id)}"]`).classList.add("sel");
  const zone = (M.zones.find(z => z.id === n.zone) || {}).label;
  document.getElementById("panel").innerHTML = `<div class="k">${esc(KIND[n.kind])}</div><h2>${esc(n.label)}</h2><div>${esc(n.role)}</div>
   <dl><dt>Site</dt><dd>${esc(zone)}</dd><dt>Why this type</dt><dd>${esc(n.kind_basis)}</dd>${n.ips && n.ips.length ? `<dt>Addresses</dt><dd class="ev">${esc(n.ips.slice(0,12).join(", "))}${n.ips.length>12?" …":""}</dd>`:""}</dl>
   <div class="k">Connections (${es.length})</div><ul>${es.map(e => `<li><a href="#" data-edge="${esc(e.id)}">${esc(endName(e.s))} → ${esc(endName(e.t))}</a><br><span class="hint">${esc(e.label.replace(/\\n/g," · "))} — ${esc(STATUS[e.status])}</span></li>`).join("")}</ul>`;
}
function pickEdge(id){
  const M = m(), e = M.edges.find(x => x.id === id);
  light([...members(e.s), ...members(e.t)], [id]);
  const det = e.detail || {};
  const extra = Object.entries(det).map(([k,v]) => `<dt>${esc(k)}</dt><dd>${esc(Array.isArray(v) ? v.join(", ") : (typeof v === "object" ? Object.entries(v).map(([a,b]) => a+" ×"+b).join(", ") : v))}</dd>`).join("");
  document.getElementById("panel").innerHTML = `<div class="k">${e.step ? "Step " + e.step + " · " : ""}${esc(STATUS[e.status])}</div>
   <h2>${esc(endName(e.s))} ${e.dir === "both" ? "↔" : "→"} ${esc(endName(e.t))}</h2><div>${esc(e.label.replace(/\\n/g," · "))}</div>
   <dl>${extra}<dt>Evidence</dt><dd class="ev">${esc((e.evidence||[]).join(", "))}</dd></dl>`;
}
document.addEventListener("click", ev => {
  const a = ev.target.closest("[data-edge]"); if (a){ ev.preventDefault(); pickEdge(a.dataset.edge); return; }
  const t = ev.target.closest(".tab"); if (t){ show(t.dataset.stem); return; }
  const n = ev.target.closest("svg .node"); if (n){ pickNode(n.dataset.id); return; }
  const e = ev.target.closest("svg .edge"); if (e){ pickEdge(e.dataset.id); return; }
  if (ev.target.closest(".stage")) clear();
});
document.addEventListener("keydown", ev => {
  const n = ev.target.closest && ev.target.closest("svg .node");
  if (n && (ev.key === "Enter" || ev.key === " ")){ ev.preventDefault(); pickNode(n.dataset.id); }
  if (ev.key === "Escape") clear();
});
show(Object.keys(DATA)[0]);
</script></body></html>"""
    return (page.replace("__TABS__", tabs).replace("__SVGS__", svgs)
                .replace("__DATA__", json.dumps(data).replace("</", "<\\/")).replace("__TITLE__", html.escape(title)))
