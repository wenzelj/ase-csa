import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import "./network.css";
import networkCss from "./network.css?raw";

type NetNode = { id: string; kind: "captured" | "dc" | "named" | "unnamed" | "public"; role: string; site: string; ips: string; listed?: boolean };
type NetEdge = { s: string; t: string; port: string; procs: string[]; ids: string[]; est: boolean };
type NetData = { nodes: NetNode[]; edges: NetEdge[]; matrix_rows: number };
type Agg = { s: string; t: string; ports: string[]; procs: string[]; ids: string[]; est: boolean; intra: boolean };

const PUB = "Public internet";
const SITE_ORDER = ["Rockhampton", "Mackay", "IPT"];
const KIND_LABEL: Record<string, string> = {
  captured: "Captured system host", dc: "Domain controller", named: "Named host, not captured",
  unnamed: "Internal address, name not captured", public: "Public internet",
};
const W = 1180, BW = 170, BH = 34, GAP = 10;

export default function NetworkMap({ system, openEvidenceId }: { system: string; openEvidenceId: (id: string) => void }) {
  const [data, setData] = useState<NetData | null>(null);
  const [error, setError] = useState("");
  const [showPublic, setShowPublic] = useState(false);
  const [attempted, setAttempted] = useState(true);
  const [intra, setIntra] = useState(true);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [hiCaptured, setHiCaptured] = useState(false);

  useEffect(() => {
    setData(null); setSelected(null); setError("");
    api<NetData>(`/api/systems/${system}/network`).then(setData).catch(e => setError(String(e.message || e)));
  }, [system]);

  const graph = useMemo(() => {
    if (!data) return null;
    const byId = Object.fromEntries(data.nodes.map(n => [n.id, n]));
    let nodes: NetNode[] = data.nodes.filter(n => showPublic || n.kind !== "public");
    const publicCount = data.nodes.filter(n => n.kind === "public").length;
    if (!showPublic && publicCount) nodes = [...nodes, { id: PUB, kind: "public", role: `${publicCount} addresses`, site: "", ips: "" }];
    const map = (n: string) => (!showPublic && byId[n]?.kind === "public" ? PUB : n);
    const agg: Record<string, Agg> = {};
    for (const e of data.edges) {
      if (!attempted && !e.est) continue;
      const isIntra = byId[e.s]?.kind === "captured" && byId[e.t]?.kind === "captured";
      if (isIntra && !intra) continue;
      const s = map(e.s), t = map(e.t), k = `${s}|${t}`;
      const a = agg[k] || (agg[k] = { s, t, ports: [], procs: [], ids: [], est: false, intra: isIntra });
      if (!a.ports.includes(e.port)) a.ports.push(e.port);
      e.procs.forEach(p => { if (!a.procs.includes(p)) a.procs.push(p); });
      a.ids.push(...e.ids); a.est = a.est || e.est;
    }
    const edges = Object.values(agg);
    const used = new Set(edges.flatMap(e => [e.s, e.t]));
    nodes = nodes.filter(n => used.has(n.id) || n.kind === "captured" || n.listed);
    // lanes: outside the system | captured hosts by site | other named hosts
    const deg: Record<string, number> = {};
    edges.forEach(e => { deg[e.s] = (deg[e.s] || 0) + 1; deg[e.t] = (deg[e.t] || 0) + 1; });
    const left = nodes.filter(n => n.kind === "unnamed" || n.kind === "public")
      .sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "unnamed" ? -1 : 1) || (deg[b.id] || 0) - (deg[a.id] || 0));
    const rightAll = nodes.filter(n => n.kind === "dc" || n.kind === "named")
      .sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "dc" ? -1 : 1) || a.id.localeCompare(b.id));
    const inv = rightAll.filter(n => n.listed), other = rightAll.filter(n => !n.listed);
    const mid = nodes.filter(n => n.kind === "captured");
    const X = { left: 40, mid: W / 2 - BW / 2, right: W - 40 - BW };
    const pos: Record<string, { x: number; y: number }> = {};
    const rank = (s: string) => { const i = SITE_ORDER.indexOf(s); return i < 0 ? 99 : i; };
    const sites = [...new Set(mid.map(n => n.site || "Site not recorded"))].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
    const siteLabels: { s: string; y: number }[] = [];
    let y = 70;
    for (const s of sites) {
      siteLabels.push({ s, y }); y += 18;
      mid.filter(n => (n.site || "Site not recorded") === s).sort((a, b) => a.role.localeCompare(b.role) || a.id.localeCompare(b.id))
        .forEach(n => { pos[n.id] = { x: X.mid, y }; y += BH + GAP; });
      y += 14;
    }
    let yl = 70; left.forEach(n => { pos[n.id] = { x: X.left, y: yl }; yl += BH + GAP; });
    let yr = 70;
    const rightLabels: { s: string; y: number }[] = [];
    if (inv.length) {
      rightLabels.push({ s: "In the OU inventory, not captured", y: yr }); yr += 18;
      inv.forEach(n => { pos[n.id] = { x: X.right, y: yr }; yr += BH + GAP; });
      yr += 14;
      if (other.length) { rightLabels.push({ s: "Other named hosts", y: yr }); yr += 18; }
    }
    other.forEach(n => { pos[n.id] = { x: X.right, y: yr }; yr += BH + GAP; });
    return { nodes, edges, pos, X, siteLabels, rightLabels, H: Math.max(y, yl, yr) + 20 };
  }, [data, showPublic, attempted, intra]);

  if (error) return <section className="net"><div className="error" role="alert"><div><b>Network unavailable</b><span>{error}</span></div></div></section>;
  if (!data || !graph) return <section className="net"><p className="net-note">Loading the host network…</p></section>;

  const count = (k: string) => data.nodes.filter(n => n.kind === k).length;
  const neighbours = new Set<string>();
  if (selected) graph.edges.forEach(e => { if (e.s === selected || e.t === selected) { neighbours.add(e.s); neighbours.add(e.t); } });
  const q = query.trim().toLowerCase();
  const sel = selected ? graph.nodes.find(n => n.id === selected) : undefined;
  const selEdges = selected ? graph.edges.filter(e => e.s === selected || e.t === selected) : [];

  const path = (e: Agg) => {
    const a = graph.pos[e.s], b = graph.pos[e.t];
    if (!a || !b) return "";
    if (a.x === b.x) {
      const x = a.x + BW, y1 = a.y + BH / 2, y2 = b.y + BH / 2, o = 40 + Math.abs(y2 - y1) * 0.25;
      return `M${x},${y1} C${x + o},${y1} ${x + o},${y2} ${x},${y2}`;
    }
    const ltr = a.x < b.x, x1 = ltr ? a.x + BW : a.x, x2 = ltr ? b.x : b.x + BW, y1 = a.y + BH / 2, y2 = b.y + BH / 2, m = (x1 + x2) / 2;
    return `M${x1},${y1} C${m},${y1} ${m},${y2} ${x2},${y2}`;
  };

  const exportHtml = () => {
    const svg = document.getElementById("net-svg");
    if (!svg) return;
    const root = getComputedStyle(document.documentElement);
    const vars = ["--ink", "--paper", "--muted", "--line", "--teal", "--amber", "--red", "--ase-signal-soft"]
      .map(v => `${v}:${root.getPropertyValue(v).trim()}`).join(";");
    const esc = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;");
    const model = {
      nodes: Object.fromEntries(graph.nodes.map(n => [n.id, { kind: KIND_LABEL[n.kind], role: n.role, site: n.site, ips: n.ips }])),
      edges: graph.edges.map(e => ({ s: e.s, t: e.t, ports: e.ports, procs: e.procs, ids: e.ids, est: e.est })),
    };
    const stats = [["Captured hosts", count("captured")], ["Named peers", count("dc") + count("named")], ["Unnamed internal", count("unnamed")], ["Public addresses", count("public")], ["Links", graph.edges.length]]
      .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
    const clone = svg.cloneNode(true) as SVGElement;
    clone.removeAttribute("id");
    clone.querySelectorAll(".dim,.hi,.sel").forEach(el => el.classList.remove("dim", "hi", "sel"));
    const script = `const M=${JSON.stringify(model).replace(/</g, "\\u003c")};
const svg=document.querySelector("svg"),panel=document.getElementById("panel");let sel=null;
const nodes=[...svg.querySelectorAll(".node")],edges=[...svg.querySelectorAll(".edge")];
const h=(t)=>t.replace(/&/g,"&amp;").replace(/</g,"&lt;");
function draw(){const nb=new Set();if(sel)M.edges.forEach(e=>{if(e.s===sel||e.t===sel){nb.add(e.s);nb.add(e.t)}});
nodes.forEach(n=>{const id=n.dataset.id;n.classList.toggle("sel",id===sel);n.classList.toggle("dim",!!sel&&!nb.has(id))});
edges.forEach(p=>{const on=!!sel&&(p.dataset.s===sel||p.dataset.t===sel);p.classList.toggle("hi",on);p.classList.toggle("dim",!!sel&&!on)});
if(!sel){panel.innerHTML='<div class="kind">Select a host</div><h3>No host selected</h3><p class="net-note">Lines run from the host that opened the connection to the one that accepted it. Dashed lines were attempted but not established when sampled.</p>';return}
const n=M.nodes[sel]||{};let o='<div class="kind">'+h(n.kind||"")+'</div><h3>'+h(sel)+'</h3>';
if(n.role)o+='<div>'+h(n.role)+(n.site?" · "+h(n.site):"")+'</div>';
if(n.ips&&n.ips!==sel)o+='<div class="mono muted">'+h(n.ips.split(";").filter(x=>x&&!x.endsWith(".0")).join(", "))+'</div>';
o+='<div class="conn">';M.edges.filter(e=>e.s===sel||e.t===sel).forEach(e=>{const out=e.s===sel,peer=out?e.t:e.s;
o+='<div><span class="dir">'+(out?"connects to":"accepts from")+'</span><button class="peer" data-peer="'+h(peer).replace(/"/g,"&quot;")+'">'+h(peer)+'</button><br>port '+h(e.ports.join(", "))+' · '+h(e.procs.join(", "))+(e.est?"":" · attempted only")+'<div class="ids">'+e.ids.map(i=>'<span>'+h(i)+'</span>').join("")+'</div></div>'});
panel.innerHTML=o+'</div>'}
nodes.forEach(n=>{const pick=()=>{sel=sel===n.dataset.id?null:n.dataset.id;draw()};n.addEventListener("click",pick);n.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();pick()}})});
panel.addEventListener("click",e=>{const b=e.target.closest(".peer");if(b){sel=b.dataset.peer;draw()}});draw();`;
    const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Host network - ${esc(system)}</title><style>
:root{${vars}}body{margin:0;font:14px/1.45 system-ui,sans-serif;color:var(--ink);background:var(--paper)}
${networkCss}
.net{max-width:none}.net-panel .ids span{font-family:ui-monospace,Menlo,monospace;font-size:.72rem;border:1px solid var(--line);border-radius:4px;padding:0 4px}
</style></head><body><section class="net"><header class="net-head"><div><h2>Host network: ${esc(system)}</h2><p>Snapshot exported ${new Date().toISOString().slice(0, 10)}. Select a host to trace who it talks to.</p></div><dl class="net-stats">${stats}</dl></header>
<div class="net-main"><div class="net-canvas">${clone.outerHTML}</div><aside class="net-panel" id="panel"></aside></div>
<p class="net-note">Connections were sampled for about 30 seconds per host, so occasional peers can be missing. Addresses without a captured name are shown as addresses; nothing about them is inferred. Built from ${data.matrix_rows} evidence matrix rows and the host register.</p></section>
<script>${script}</script></body></html>`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    a.download = `host-network-${system}.html`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return <section className="net">
    <header className="net-head">
      <div>
        <h2>Host network</h2>
        <p>Every connection the captures recorded, from the evidence matrix. Select a host to trace who it talks to; the panel lists ports, processes and the evidence behind each link.</p>
      </div>
      <dl className="net-stats">
        <div><dt>Captured hosts</dt><dd>{count("captured")}</dd></div>
        <div><dt>Named peers</dt><dd>{count("dc") + count("named")}</dd></div>
        <div><dt>Unnamed internal</dt><dd>{count("unnamed")}</dd></div>
        <div><dt>Public addresses</dt><dd>{count("public")}</dd></div>
        <div><dt>Links</dt><dd>{data.edges.length}</dd></div>
      </dl>
    </header>
    <div className="net-controls">
      <input id="net-q" type="search" placeholder="Find a host or address" aria-label="Find a host or address" value={query} onChange={e => setQuery(e.target.value)} />
      <label><input id="net-pub" type="checkbox" checked={showPublic} onChange={e => { setShowPublic(e.target.checked); setSelected(null); }} /> Show each public address</label>
      <label><input id="net-att" type="checkbox" checked={attempted} onChange={e => { setAttempted(e.target.checked); setSelected(null); }} /> Include attempted-only connections</label>
      <label><input id="net-intra" type="checkbox" checked={intra} onChange={e => { setIntra(e.target.checked); setSelected(null); }} /> Links inside the system</label>
      <button id="net-export" type="button" onClick={exportHtml}>Export as HTML</button>
      <label><input id="net-hicap" type="checkbox" checked={hiCaptured} onChange={e => setHiCaptured(e.target.checked)} /> Highlight captured hosts</label>
    </div>
    <div className="net-legend">
      <span><i className="sw k-captured" />Captured system host</span>
      <span><i className="sw k-listed" />In the OU inventory, not captured</span>
      <span><i className="sw k-dc" />Other named host, not captured</span>
      <span><i className="sw k-unnamed" />Internal address, name not captured</span>
      <span><i className="sw k-public" />Public internet address</span>
      <span>— established · ┄ attempted only</span>
    </div>
    <div className="net-main">
      <div className="net-canvas">
        <svg id="net-svg" viewBox={`0 0 ${W} ${graph.H}`} role="img" aria-label="Network diagram of the captured hosts and their connections">
          <text x={graph.X.left} y={40} className="lane-t">Outside the system</text>
          <text x={graph.X.mid} y={40} className="lane-t">Captured hosts</text>
          <text x={graph.X.right} y={40} className="lane-t">Other named hosts</text>
          {graph.siteLabels.map(s => <text key={s.s} x={graph.X.mid} y={s.y + 11} className="site-t">{s.s.toUpperCase()}</text>)}
          {graph.rightLabels.map(s => <text key={s.s} x={graph.X.right} y={s.y + 11} className="site-t">{s.s.toUpperCase()}</text>)}
          <g>{graph.edges.map(e => {
            const on = !!selected && (e.s === selected || e.t === selected);
            return <path key={`${e.s}|${e.t}`} data-s={e.s} data-t={e.t} d={path(e)} className={`edge${e.est ? "" : " att"}${on ? " hi" : ""}${selected && !on ? " dim" : ""}`} />;
          })}</g>
          <g>{graph.nodes.map(n => {
            const p = graph.pos[n.id]; if (!p) return null;
            const dim = (selected && !neighbours.has(n.id)) || (q && !(n.id.toLowerCase().includes(q) || n.role.toLowerCase().includes(q)));
            const role = n.kind === "unnamed" ? "name not captured" : n.role;
            const pick = () => setSelected(selected === n.id ? null : n.id);
            return <g key={n.id} data-id={n.id} className={`node k-${n.kind}${n.listed && n.kind !== "captured" ? " listed" : ""}${selected === n.id ? " sel" : ""}${dim ? " dim" : ""}${hiCaptured ? (n.kind === "captured" ? " cap-hi" : selected && neighbours.has(n.id) ? "" : " cap-lo") : ""}`} transform={`translate(${p.x},${p.y})`}
              tabIndex={0} role="button" aria-label={n.id} onClick={pick} onKeyDown={ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(); } }}>
              <rect width={BW} height={BH} rx={4} />
              {hiCaptured && n.kind === "captured" && <circle cx={BW - 10} cy={10} r={4} className="cap-dot" />}
              <text x={8} y={14}>{n.id}</text>
              <text x={8} y={27} className="role">{role.length > 30 ? role.slice(0, 29) + "…" : role}</text>
            </g>;
          })}</g>
        </svg>
      </div>
      <aside className="net-panel" aria-live="polite">
        {!sel ? <>
          <div className="kind">Select a host</div><h3>No host selected</h3>
          <p className="net-note">Lines run from the host that opened the connection to the one that accepted it. Dashed lines were attempted but not established when sampled.</p>
        </> : <>
          <div className="kind">{KIND_LABEL[sel.kind]}</div><h3>{sel.id}</h3>
          {sel.role && <div>{sel.role}{sel.site ? ` · ${sel.site}` : ""}</div>}
          {sel.ips && sel.ips !== sel.id && <div className="mono muted">{sel.ips.split(";").filter(x => x && !x.endsWith(".0")).join(", ")}</div>}
          <div className="conn">{selEdges.length ? selEdges.map(e => {
            const out = e.s === sel.id, peer = out ? e.t : e.s;
            return <div key={`${e.s}|${e.t}`}>
              <span className="dir">{out ? "connects to" : "accepts from"}</span>
              <button className="peer" onClick={() => setSelected(peer)}>{peer}</button><br />
              port {e.ports.join(", ")} · {e.procs.join(", ")}{e.est ? "" : " · attempted only"}
              <div className="ids">{e.ids.map(id => <button key={id} onClick={() => openEvidenceId(id)}>{id}</button>)}</div>
            </div>;
          }) : <div>No connections in the current view.</div>}</div>
        </>}
      </aside>
    </div>
    <p className="net-note">Connections were sampled for about 30 seconds per host, so occasional peers can be missing. Addresses without a captured name are shown as addresses; nothing about them is inferred. Built from {data.matrix_rows} evidence matrix rows and the host register.</p>
  </section>;
}
