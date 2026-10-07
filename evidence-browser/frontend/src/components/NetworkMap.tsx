import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import "./network.css";

type NetNode = { id: string; kind: "captured" | "dc" | "named" | "unnamed" | "public"; role: string; site: string; ips: string };
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
    nodes = nodes.filter(n => used.has(n.id) || n.kind === "captured");
    // lanes: outside the system | captured hosts by site | other named hosts
    const deg: Record<string, number> = {};
    edges.forEach(e => { deg[e.s] = (deg[e.s] || 0) + 1; deg[e.t] = (deg[e.t] || 0) + 1; });
    const left = nodes.filter(n => n.kind === "unnamed" || n.kind === "public")
      .sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "unnamed" ? -1 : 1) || (deg[b.id] || 0) - (deg[a.id] || 0));
    const right = nodes.filter(n => n.kind === "dc" || n.kind === "named")
      .sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "dc" ? -1 : 1) || a.id.localeCompare(b.id));
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
    let yr = 70; right.forEach(n => { pos[n.id] = { x: X.right, y: yr }; yr += BH + GAP; });
    return { nodes, edges, pos, X, siteLabels, H: Math.max(y, yl, yr) + 20 };
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
    </div>
    <div className="net-legend">
      <span><i className="sw k-captured" />Captured system host</span>
      <span><i className="sw k-dc" />Named host, not captured</span>
      <span><i className="sw k-unnamed" />Internal address, name not captured</span>
      <span><i className="sw k-public" />Public internet address</span>
      <span>— established · ┄ attempted only</span>
    </div>
    <div className="net-main">
      <div className="net-canvas">
        <svg viewBox={`0 0 ${W} ${graph.H}`} role="img" aria-label="Network diagram of the captured hosts and their connections">
          <text x={graph.X.left} y={40} className="lane-t">Outside the system</text>
          <text x={graph.X.mid} y={40} className="lane-t">Captured hosts</text>
          <text x={graph.X.right} y={40} className="lane-t">Other named hosts</text>
          {graph.siteLabels.map(s => <text key={s.s} x={graph.X.mid} y={s.y + 11} className="site-t">{s.s.toUpperCase()}</text>)}
          <g>{graph.edges.map(e => {
            const on = !!selected && (e.s === selected || e.t === selected);
            return <path key={`${e.s}|${e.t}`} d={path(e)} className={`edge${e.est ? "" : " att"}${on ? " hi" : ""}${selected && !on ? " dim" : ""}`} />;
          })}</g>
          <g>{graph.nodes.map(n => {
            const p = graph.pos[n.id]; if (!p) return null;
            const dim = (selected && !neighbours.has(n.id)) || (q && !(n.id.toLowerCase().includes(q) || n.role.toLowerCase().includes(q)));
            const role = n.kind === "unnamed" ? "name not captured" : n.role;
            const pick = () => setSelected(selected === n.id ? null : n.id);
            return <g key={n.id} className={`node k-${n.kind}${selected === n.id ? " sel" : ""}${dim ? " dim" : ""}`} transform={`translate(${p.x},${p.y})`}
              tabIndex={0} role="button" aria-label={n.id} onClick={pick} onKeyDown={ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(); } }}>
              <rect width={BW} height={BH} rx={4} />
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
