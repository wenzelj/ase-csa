import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import "./explorer.css";

/* System explorer: the technical diagram of the assessed system, the same drawing as the CSA figure
 * (csa_docx.techdiagram via /api/systems/<key>/diagram). IT across the top, the data centres side by side
 * with tier rows, shared services across the bottom; every line runs in its own track. One tab per
 * documented data flow (numbered steps, no animation). Select a system for everything about it (host
 * register, captured links, facts, what the CSA says, from /api/systems/<key>/explorer) or a line for its
 * ports and evidence. Nothing here is invented. */

type Fact = { attribute: string; value: string };
type Mention = { section: string; kind: string; text: string };
type Host = { id: string; kind: string; role: string; site: string; ips: string; listed?: boolean; system: string; in_scope: string;
  fqdn: string; capture: string; conflicts: string; facts: Fact[]; csa: Mention[]; card: string };
type Edge = { s: string; t: string; port: string; procs: string[]; est: boolean };
type Component = { id: string; name: string; host: string | null; status: string; role: string };
type Dependency = { id: string; from: string; to: string[]; label: string; note?: string };
type Data = { application: string; hosts: Host[]; edges: Edge[]; components: Component[]; dependencies: Dependency[]; document: { name: string } };

type DNode = { id: string; label: string; role: string; kind: string; zone: string; kind_basis: string; ips: string[]; host?: boolean };
type DEdge = { id: string; s: string; t: string; dir: string; label: string; status: string; step?: number; evidence: string[];
  detail: Record<string, unknown> };
type DGroup = { id: string; label: string; members: string[] };
type DZone = { id: string; label: string };
type DModel = { id: string; title: string; zones: DZone[]; groups: DGroup[]; nodes: DNode[]; edges: DEdge[]; notes?: string[] };
type Diagram = { id: string; title: string; svg: string; model: DModel;
  print_svg?: string; print?: { width_mm: number; height_mm: number; fits_page: boolean; min_text_pt: number; tiles?: number; lines?: number } };
type Diagrams = { application: string; diagrams: Diagram[] };
type Sel = { type: "node" | "edge" | "group"; id: string } | null;

const SAYS: Record<string, string> = { observed: "Observed in connection captures", configured: "Configured setting (DNS, Kerberos, time)",
  inferred: "Inferred — validate", documented: "Documented only, not observed", unknown: "Path not captured" };
const KIND: Record<string, string> = { database: "Database server", app_server: "Application server", logging: "Log server", jump_host: "Jump host",
  terminal: "Operator workstation", radio: "Radio management", directory: "Domain controller · DNS", internal: "Internal addresses",
  internet: "Internet", backup: "Backup target", mail: "Mail", firewall: "Firewall", dns: "DNS server", time: "Time source",
  switch: "Network switch", router: "Router", hypervisor: "Virtualisation host", storage: "Storage", plc: "PLC", rtu: "RTU", hmi: "HMI",
  historian: "Historian", server: "Server", unknown: "Role not recorded" };
const PORT_NAME: Record<string, string> = { "56420": "SQL", "56522": "SQL cluster", "1433": "SQL", "445": "file sharing", "135": "RPC", "3389": "Remote Desktop",
  "53": "DNS", "88": "Kerberos", "389": "LDAP", "443": "HTTPS", "8080": "HTTP proxy", "5723": "monitoring agent", "9997": "Splunk", "8089": "Splunk management", "7000": "backup agent", "25": "SMTP" };

const ipsOf = (h: Host) => (h.ips || "").split(/[;,]\s*/).map(x => x.trim()).filter(x => x && !/\.0$/.test(x) && !x.startsWith("169.254") && x !== h.id);
const captureDate = (c: string) => { const m = c.match(/_(\d{4})(\d{2})(\d{2})T/); return m ? new Date(`${m[1]}-${m[2]}-${m[3]}T00:00:00`).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" }) : ""; };
const cssId = (s: string) => (window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/"/g, '\\"'));

function cardSection(card: string, title: string): string[] {
  const m = (card || "").split(/\n## /).find(s => s.toLowerCase().startsWith(title.toLowerCase()));
  return m ? m.split("\n").slice(1).filter(l => l.startsWith("- ")).map(l => l.slice(2).trim()) : [];
}

function download(name: string, blob: Blob) {
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function savePng(name: string, svg: string) {
  const m = svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/); const w = m ? +m[1] : 1600, h = m ? +m[2] : 1200;
  const img = new Image(); const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  img.onload = () => {
    const c = document.createElement("canvas"); c.width = w * 2; c.height = h * 2;
    const g = c.getContext("2d")!; g.scale(2, 2); g.drawImage(img, 0, 0, w, h); URL.revokeObjectURL(url);
    c.toBlob(b => b && download(name, b), "image/png");
  };
  img.src = url;
}

export default function SystemExplorer({ system, openEvidenceId }: { system: string; openEvidenceId?: (id: string) => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [dg, setDg] = useState<Diagrams | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState(0);
  const [sel, setSel] = useState<Sel>(null);
  const [fit, setFit] = useState(true);
  const [layout, setLayout] = useState<"portrait" | "detailed">(() => {
    try { return localStorage.getItem("sx-layout") === "detailed" ? "detailed" : "portrait"; }
    catch { return "portrait"; }
  });
  const setLayoutChoice = (v: "portrait" | "detailed") => {
    setLayout(v); setSel(null);
    try { localStorage.setItem("sx-layout", v); } catch { /* keep the choice for this visit only */ }
  };
  const stage = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setData(null); setDg(null); setError(""); setSel(null); setTab(0); setLayoutChoice("portrait");
    Promise.all([api<Data>(`/api/systems/${system}/explorer`), api<Diagrams>(`/api/systems/${system}/diagram`)])
      .then(([d, g]) => { setData(d); setDg(g); }).catch(e => setError(String(e.message || e)));
  }, [system]);

  const cur = dg?.diagrams[tab] || null;
  const model = cur?.model || null;
  const byId = useMemo(() => Object.fromEntries((data?.hosts || []).map(h => [h.id, h])), [data]);

  const members = (end: string): string[] => {
    if (!model) return [];
    if (end.startsWith("Z:")) return model.nodes.filter(n => n.zone === end.slice(2)).map(n => n.id);
    if (end.startsWith("SG:")) return model.groups.find(g => g.id === end)?.members || [];
    return [end];
  };
  const endName = (end: string): string => {
    if (!model) return end;
    if (end.startsWith("Z:")) return model.zones.find(z => z.id === end.slice(2))?.label || end;
    if (end.startsWith("SG:")) return model.groups.find(g => g.id === end)?.label || end;
    return model.nodes.find(n => n.id === end)?.label || end;
  };

  /* highlight the selection on the drawing */
  useEffect(() => {
    const svg = stage.current?.querySelector("svg"); if (!svg || !model) return;
    svg.querySelectorAll(".on,.sel").forEach(e => e.classList.remove("on", "sel"));
    svg.classList.toggle("dim", !!sel);
    if (!sel) return;
    let nodes: string[] = [], edges: string[] = [];
    if (sel.type === "edge") {
      const e = model.edges.find(x => x.id === sel.id); if (!e) return;
      nodes = [...members(e.s), ...members(e.t)]; edges = [e.id];
    } else {
      const ids = sel.type === "group" ? members(sel.id) : [sel.id];
      const es = model.edges.filter(e => [...members(e.s), ...members(e.t), e.s, e.t].some(x => ids.includes(x) || x === sel.id));
      nodes = [...new Set([...ids, ...es.flatMap(e => [...members(e.s), ...members(e.t)])])]; edges = es.map(e => e.id);
    }
    nodes.forEach(id => svg.querySelector(`.node[data-id="${cssId(id)}"]`)?.classList.add("on"));
    edges.forEach(id => svg.querySelectorAll(`.edge[data-id="${cssId(id)}"]`).forEach(x => x.classList.add("on")));
    svg.querySelectorAll(".group").forEach(g => { if (members((g as HTMLElement).dataset.id || "").some(x => nodes.includes(x))) g.classList.add("on"); });
    if (sel.type !== "edge") {
      const el = svg.querySelector(`.${sel.type}[data-id="${cssId(sel.id)}"]`);
      el?.classList.add("sel", "on");
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      (el as Element | null)?.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: reduce ? "auto" : "smooth" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, tab, model]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setSel(null); };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, []);

  const pick = (target: EventTarget | null) => {
    const el = target as Element | null; if (!el || !el.closest) return;
    const n = el.closest(".node") as HTMLElement | null; if (n?.dataset.id) { setSel({ type: "node", id: n.dataset.id }); return; }
    const e = el.closest(".edge") as HTMLElement | null; if (e?.dataset.id) { setSel({ type: "edge", id: e.dataset.id }); return; }
    const g = el.closest(".group") as HTMLElement | null; if (g?.dataset.id) { setSel({ type: "group", id: g.dataset.id }); return; }
    setSel(null);
  };

  if (error) return <section className="sx"><div className="sx-msg">The system explorer could not load: {error}</div></section>;
  if (!data || !dg || !cur || !model) return <section className="sx"><div className="loading"><span /><strong>Drawing the system…</strong></div></section>;

  const activeSvg = layout === "portrait" ? (cur.print_svg || cur.svg) : cur.svg;
  const hostCount = model.nodes.filter(n => n.host).length;
  const dcs = model.zones.filter(z => (model as unknown as { layout?: { dcs?: string[] } }).layout?.dcs?.includes(z.id)).map(z => z.label);
  const selNode = sel?.type === "node" ? model.nodes.find(n => n.id === sel.id) : undefined;
  const selHost = selNode && byId[selNode.id];
  const selEdge = sel?.type === "edge" ? model.edges.find(e => e.id === sel.id) : undefined;
  const selGroup = sel?.type === "group" ? model.groups.find(g => g.id === sel.id) : undefined;

  return <section className="sx">
    <header className="sx-head">
      <div><h2>{dg.application}</h2>
        <p>{tab === 0 ? `${hostCount} systems${dcs.length ? ` across ${dcs.join(" and ")}` : ""}. ` : ""}
          A4 portrait groups hosts by recorded role; Detailed network shows individual hosts. Select a system or a line to see its evidence. The same drawing is the CSA figure.</p></div>
      <div className="sx-tools" role="group" aria-label="Layout">
        <button className={layout === "portrait" ? "on" : ""} aria-pressed={layout === "portrait"} onClick={() => setLayoutChoice("portrait")}>A4 portrait</button>
        <button className={layout === "detailed" ? "on" : ""} aria-pressed={layout === "detailed"} onClick={() => setLayoutChoice("detailed")}>Detailed network</button>
        <button onClick={() => setFit(f => !f)}>{fit ? "Actual size" : "Fit to width"}</button>
        <button onClick={() => download(`${cur.id}-${layout === "portrait" ? "a4" : "detailed"}.svg`, new Blob([activeSvg], { type: "image/svg+xml" }))}>Download SVG</button>
        <button onClick={() => savePng(`${cur.id}-${layout === "portrait" ? "a4" : "detailed"}.png`, activeSvg)}>Download PNG</button>
      </div>
    </header>

    {dg.diagrams.length > 1 && <nav className="sx-tabs" role="tablist" aria-label="Diagrams">
      {dg.diagrams.map((d, i) => <button key={d.id} role="tab" aria-selected={i === tab} className={i === tab ? "on" : ""}
        onClick={() => { setTab(i); setSel(null); }}>{i === 0 ? "System" : d.title}</button>)}
    </nav>}

    {layout === "portrait" && cur.print && <p className="sx-printline" aria-live="polite">
      {cur.print.width_mm} × {cur.print.height_mm} mm · smallest text {cur.print.min_text_pt} pt ·{" "}
      <b className={cur.print.fits_page ? "ok" : "over"}>{cur.print.fits_page ? "Fits A4" : "Exceeds one A4 page"}</b>
      {typeof cur.print.tiles === "number" && typeof cur.print.lines === "number" ? ` · ${cur.print.tiles} tiles, ${cur.print.lines} lines` : ""}
    </p>}

    <div className={`sx-body${sel ? " has-panel" : ""}`}>
      <div className={`sx-stage sx-drawing${fit ? " fit" : ""}${layout === "portrait" ? " portrait" : ""}`} ref={stage}
        onClick={layout === "detailed" ? (e => pick(e.target)) : undefined}
        onKeyDown={layout === "detailed" ? (e => { if (e.key === "Enter" || e.key === " ") { const n = (e.target as Element).closest?.(".node"); if (n) { e.preventDefault(); pick(n); } } }) : undefined}
        dangerouslySetInnerHTML={{ __html: activeSvg }} />

      {sel && <aside className="sx-panel" aria-live="polite">
        <button className="sx-close" onClick={() => setSel(null)} aria-label="Close">×</button>
        {selHost ? <HostDetail host={selHost} data={data} byId={byId} go={id => setSel({ type: "node", id })} />
          : selNode ? <OtherDetail node={selNode} />
          : selGroup ? <div className="sx-detail"><p className="sx-kind">Group</p><h3 className="plain">{selGroup.label}</h3>
              <section><h4>Members</h4><ul className="sx-plain">{selGroup.members.map(m => <li key={m}>
                <button className="sx-link" onClick={() => setSel({ type: "node", id: m })}>{m}</button></li>)}</ul></section></div>
          : selEdge ? <EdgeDetail edge={selEdge} endName={endName} go={id => setSel({ type: "node", id })} openEvidenceId={openEvidenceId} />
          : null}
      </aside>}
    </div>
  </section>;
}

function OtherDetail({ node }: { node: DNode }) {
  return <div className="sx-detail">
    <p className="sx-kind">{KIND[node.kind] || node.kind}</p>
    <h3 className="plain">{node.label}</h3>
    <p className="sx-sub">{node.role}</p>
    <p className="sx-meta">{node.kind_basis}</p>
    {node.ips.length > 0 && <section><h4>Addresses ({node.ips.length})</h4>
      <p className="sx-ips">{node.ips.join(", ")}</p></section>}
  </div>;
}

function EdgeDetail({ edge, endName, go, openEvidenceId }: { edge: DEdge; endName: (s: string) => string; go: (id: string) => void;
  openEvidenceId?: (id: string) => void }) {
  const d = edge.detail || {};
  const ports = d.ports as Record<string, number> | undefined;
  const hosts = d.hosts as string[] | undefined;
  const settings = d.settings as string[] | undefined;
  const end = (x: string) => x.startsWith("Z:") || x.startsWith("SG:") || x.startsWith("G-") ? <b>{endName(x)}</b>
    : <button className="sx-link" onClick={() => go(x)}>{endName(x)}</button>;
  return <div className="sx-detail">
    <p className="sx-kind">{edge.step ? `Step ${edge.step} · ` : ""}{SAYS[edge.status] || edge.status}</p>
    <h3 className="plain edge-title">{end(edge.s)} <span>{edge.dir === "both" ? "↔" : "→"}</span> {end(edge.t)}</h3>
    <p className="sx-sub">{edge.label.split("\n").join(" · ")}</p>
    {typeof d.connections === "number" && <p className="sx-meta">{d.connections as number} captured connection{(d.connections as number) === 1 ? "" : "s"}</p>}
    {ports && <section><h4>Ports</h4><ul className="sx-plain">{Object.entries(ports).map(([p, n]) =>
      <li key={p}>{PORT_NAME[p] ? `${PORT_NAME[p]} (${p})` : /^\d+$/.test(p) ? `port ${p}` : p}{n > 1 ? ` × ${n}` : ""}</li>)}</ul></section>}
    {hosts && hosts.length > 0 && <section><h4>Hosts on this line</h4><p className="sx-ips">{hosts.map((h, i) =>
      <span key={h}>{i ? ", " : ""}<button className="sx-link" onClick={() => go(h)}>{h}</button></span>)}</p></section>}
    {settings && settings.length > 0 && <section><h4>Settings</h4><ul className="sx-plain">{settings.map((s, i) => <li key={i}>{s}</li>)}</ul></section>}
    {typeof d.inference === "string" && <section><h4>Why inferred</h4><p className="sx-quiet">{d.inference as string}</p></section>}
    {typeof d.unknown === "string" && <section><h4>Not known</h4><p className="sx-quiet">{d.unknown as string}</p></section>}
    <section><h4>Evidence ({edge.evidence.length})</h4>
      {edge.evidence.length ? <div className="sx-ev">{edge.evidence.map(id => <button key={id} onClick={() => openEvidenceId?.(id)}>{id}</button>)}</div>
        : <p className="sx-quiet">No evidence ID recorded.</p>}</section>
  </div>;
}

function HostDetail({ host, data, byId, go }: { host: Host; data: Data; byId: Record<string, Host>; go: (id: string) => void }) {
  const doesLines = cardSection(host.card, "What it does");
  const apps = [...new Set(doesLines.filter(l => l.startsWith("Application:")).map(l => l.replace(/^Application:\s*/, "")))];
  const services = doesLines.filter(l => l.startsWith("Service:")).map(l => l.replace(/^Service:\s*/, "").split(" - ")[0].replace(/\s*\(`[^`]*`\)\s*$/, ""));
  const questions = cardSection(host.card, "Open questions");
  const peers = new Map<string, { id: string; out: boolean; ports: Set<string>; procs: Set<string> }>();
  data.edges.forEach(e => {
    if (e.s !== host.id && e.t !== host.id) return;
    const other = e.s === host.id ? e.t : e.s, out = e.s === host.id, k = `${other}|${out}`;
    const p = peers.get(k) || { id: other, out, ports: new Set<string>(), procs: new Set<string>() };
    p.ports.add(e.port); e.procs.forEach(x => x && p.procs.add(x)); peers.set(k, p);
  });
  const all = [...peers.values()];
  const named = all.filter(p => { const h = byId[p.id]; return h && h.kind !== "unnamed" && h.kind !== "public"; }).sort((a, b) => a.id.localeCompare(b.id));
  const unnamed = all.filter(p => !named.includes(p));
  const deps = data.dependencies.filter(d => d.from === host.id);
  const comps = data.components.filter(c => c.host === host.id);
  const os = host.facts.find(f => /host_summary: Caption|OperatingSystem/i.test(f.attribute))?.value;
  const csa = host.csa.reduce<Record<string, Mention[]>>((acc, m) => { const k = (m.section || "Document").replace(/^Requirement Domain Assessments ›\s*/, ""); (acc[k] ||= []).push(m); return acc; }, {});
  const factGroups = host.facts.reduce<Record<string, Fact[]>>((acc, f) => { const k = (f.attribute.split(":")[0] || "other").replaceAll("_", " "); (acc[k] ||= []).push(f); return acc; }, {});
  const usage = (p: { ports: Set<string>; procs: Set<string> }) => {
    const ports = [...p.ports].map(x => PORT_NAME[x] ? `${PORT_NAME[x]} (${x})` : `port ${x}`).join(", ");
    const procs = [...p.procs].filter(x => !/^(System|svchost)$/i.test(x)).join(", ");
    return procs ? `${ports} · ${procs}` : ports;
  };

  return <div className="sx-detail">
    <h3>{host.id}</h3>
    <p className="sx-sub">{host.role || "Role not recorded"}{host.site ? ` · ${host.site}` : ""}</p>
    <p className="sx-meta">{host.kind === "captured" ? `Discovery captured ${captureDate(host.capture)}` : "No discovery capture for this host"}{os ? ` · ${os}` : ""}{ipsOf(host).length ? ` · ${ipsOf(host).join(", ")}` : ""}</p>
    {host.conflicts && <p className="sx-warn">{host.conflicts}</p>}

    {(apps.length > 0 || comps.length > 0) && <section><h4>What runs on it</h4>
      <ul className="sx-plain">{comps.map(c => <li key={c.id}><b>{c.name}</b> — {c.role}</li>)}{apps.map(a => <li key={a}>{a}</li>)}</ul>
      {services.length > 0 && <details><summary>All services ({services.length})</summary><ul className="sx-plain small">{services.map((s, i) => <li key={i}>{s}</li>)}</ul></details>}
    </section>}

    <section><h4>Who it talks to</h4>
      {named.length ? <ul className="sx-peers">{named.map(p => <li key={p.id + p.out}>
        <span className="dir" title={p.out ? "it connects to" : "connects to it"}>{p.out ? "→" : "←"}</span>
        <div><button className="sx-link" onClick={() => go(p.id)}>{p.id}</button>
          <small>{byId[p.id]?.role ? `${byId[p.id].role} · ` : ""}{usage(p)}</small></div></li>)}</ul>
        : <p className="sx-quiet">No connections to named hosts were captured.</p>}
      {unnamed.length > 0 && <details><summary>{unnamed.length} other address{unnamed.length > 1 ? "es" : ""} (names not captured)</summary>
        <ul className="sx-plain small">{unnamed.map(p => <li key={p.id + p.out}>{p.out ? "→" : "←"} {p.id} · {usage(p)}</li>)}</ul></details>}
    </section>

    {deps.length > 0 && <section><h4>What it depends on</h4><ul className="sx-plain">{deps.map(d => <li key={d.id}>{d.label}{d.note && <small>{d.note}</small>}</li>)}</ul></section>}

    <section><h4>What the CSA says</h4>
      {Object.keys(csa).length ? Object.entries(csa).map(([s, ms]) => <div key={s} className="sx-csa"><b>{s}</b>
        {ms.map((m, i) => { const cells = m.text.split(" | "); return <p key={i}>{m.kind === "table row" && cells.length > 1 ? <><strong>{cells[0]}:</strong> {cells.slice(1).join(" · ")}</> : m.text}</p>; })}</div>)
        : <p className="sx-quiet">The CSA does not name this host directly.</p>}
    </section>

    {questions.length > 0 && <section><h4>Open questions</h4><ul className="sx-plain small">{questions.map(q => <li key={q}>{q}</li>)}</ul></section>}

    {host.facts.length > 0 && <details className="sx-more"><summary>More details ({host.facts.length})</summary>
      {Object.entries(factGroups).map(([k, fs]) => <div key={k} className="sx-facts"><b>{k}</b>
        <dl>{fs.map((f, i) => <div key={i}><dt>{f.attribute.split(":").slice(1).join(":").trim() || f.attribute}</dt><dd>{f.value}</dd></div>)}</dl></div>)}
    </details>}
  </div>;
}
