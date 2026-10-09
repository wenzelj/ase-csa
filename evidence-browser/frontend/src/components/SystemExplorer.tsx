import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import "./explorer.css";

/* System explorer: a clean picture of the assessed system. Sites across, roles down; the services the system
 * relies on underneath. Select a host to read everything about it in one panel. "Show how data flows" plays the
 * recorded journey on the same picture. Data comes from /api/systems/<key>/explorer (host register, captured
 * links, host cards, facts, the working CSA and csa-work/explorer/journeys.json); nothing here is invented. */

type Fact = { attribute: string; value: string };
type Mention = { section: string; kind: string; text: string };
type Host = { id: string; kind: string; role: string; site: string; ips: string; listed?: boolean; system: string; in_scope: string;
  fqdn: string; capture: string; conflicts: string; facts: Fact[]; csa: Mention[]; card: string };
type Edge = { s: string; t: string; port: string; procs: string[]; est: boolean };
type Status = "verified" | "inferred" | "documented" | "unknown";
type Component = { id: string; name: string; host: string | null; status: Status; role: string };
type Dependency = { id: string; from: string; to: string[]; label: string; note?: string };
type Transition = { id: string; from: string; to: string; payload: string; protocol?: string; port?: string; status: Status; edge: unknown };
type Step = { id: string; component?: string; transition?: string | string[]; action: string; status: Status; narrative: string;
  inference?: string; gaps?: string[]; dependencies?: string[] };
type Journey = { id: string; title: string; purpose: string; trigger: { text: string; status: Status }; steps: Step[]; transitions: Transition[] };
type Data = { application: string; hosts: Host[]; edges: Edge[]; components: Component[]; dependencies: Dependency[]; journeys: Journey[]; document: { name: string } };
type Rect = { x: number; y: number; w: number; h: number };
type Model = { byId: Record<string, Host>; sys: Host[]; loose: Host[]; sites: string[]; tiers: typeof TIERS; cell: (s: string, t: string) => Host[]; services: Host[]; externals: Component[] };

const TIERS: { key: string; label: string; test: (h: Host) => boolean }[] = [
  { key: "access", label: "Access", test: h => /jump/i.test(h.role) },
  { key: "app", label: "Application", test: h => /reveloc|tgoip/i.test(h.role) && !/sql/i.test(h.role) },
  { key: "bcast", label: "Broadcast", test: h => /revbroadcast/i.test(h.role) },
  { key: "radio", label: "Radio management", test: h => /radio|sepura/i.test(h.role) },
  { key: "db", label: "Database", test: h => /sql|database/i.test(h.role) },
  { key: "log", label: "Logging", test: h => /\blog\b/i.test(h.role) },
  { key: "other", label: "Role not recorded", test: () => true },
];
const SITE_ORDER = ["Rockhampton", "Mackay", "IPT"];
const SAYS: Record<Status, string> = { verified: "Confirmed", inferred: "Not confirmed (inferred)", documented: "Documented only, not seen", unknown: "Not known" };
const STEP_MS = 4200;
const PORT_NAME: Record<string, string> = { "56420": "SQL", "56522": "SQL cluster", "1433": "SQL", "445": "file sharing", "135": "RPC", "3389": "Remote Desktop",
  "53": "DNS", "88": "Kerberos", "389": "LDAP", "443": "HTTPS", "8080": "HTTP proxy", "5723": "monitoring agent", "9997": "Splunk", "8089": "Splunk management", "7000": "backup agent", "25": "SMTP" };

const tierOf = (h: Host) => TIERS.find(t => t.test(h))!.key;
const inSystem = (h: Host) => h.kind === "captured" || !!h.system || (!!h.listed && h.kind !== "unnamed" && h.kind !== "public");
const list = <T,>(v: T | T[] | undefined): T[] => v === undefined ? [] : Array.isArray(v) ? v : [v];
const ipsOf = (h: Host) => (h.ips || "").split(/[;,]\s*/).map(x => x.trim()).filter(x => x && !/\.0$/.test(x) && !x.startsWith("169.254") && x !== h.id);
const captureDate = (c: string) => { const m = c.match(/_(\d{4})(\d{2})(\d{2})T/); return m ? new Date(`${m[1]}-${m[2]}-${m[3]}T00:00:00`).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" }) : ""; };

function cardSection(card: string, title: string): string[] {
  const m = card.split(/\n## /).find(s => s.toLowerCase().startsWith(title.toLowerCase()));
  return m ? m.split("\n").slice(1).filter(l => l.startsWith("- ")).map(l => l.slice(2).trim()) : [];
}

export default function SystemExplorer({ system }: { system: string; openEvidenceId?: (id: string) => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [flow, setFlow] = useState(false);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const tiles = useRef<Record<string, HTMLElement | null>>({});
  const [rects, setRects] = useState<Record<string, Rect>>({});
  const pathRefs = useRef<Record<string, SVGPathElement | null>>({});

  useEffect(() => {
    setData(null); setError(""); setSelected(null); setFlow(false); setT(0); setPlaying(false);
    api<Data>(`/api/systems/${system}/explorer`).then(setData).catch(e => setError(String(e.message || e)));
  }, [system]);

  const model = useMemo<Model | null>(() => {
    if (!data) return null;
    const byId = Object.fromEntries(data.hosts.map(h => [h.id, h]));
    const sys = data.hosts.filter(inSystem);
    const placed = sys.filter(h => h.role || h.site);
    const loose = sys.filter(h => !h.role && !h.site);
    const sites = [...new Set(placed.map(h => h.site || "Site not recorded"))]
      .sort((a, b) => (SITE_ORDER.indexOf(a) + 1 || 99) - (SITE_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b));
    const tiers = TIERS.filter(tr => placed.some(h => tierOf(h) === tr.key));
    const cell = (site: string, tier: string) => placed.filter(h => (h.site || "Site not recorded") === site && tierOf(h) === tier).sort((a, b) => a.id.localeCompare(b.id));
    const depTargets = new Set(data.dependencies.flatMap(d => d.to));
    const services = data.hosts.filter(h => !inSystem(h) && (h.kind === "dc" || depTargets.has(h.id)));
    const externals = data.components.filter(c => !c.host);
    return { byId, sys, loose, sites, tiers, cell, services, externals };
  }, [data]);

  const journey = data?.journeys[0] || null;
  const comps = useMemo(() => Object.fromEntries((data?.components || []).map(c => [c.id, c])), [data]);
  const deps = useMemo(() => Object.fromEntries((data?.dependencies || []).map(d => [d.id, d])), [data]);
  const total = journey?.steps.length || 0;
  const step = Math.max(0, Math.min(total - 1, Math.floor(t)));
  const progress = Math.min(1, t - step);
  const cur = flow ? journey?.steps[step] : undefined;
  const curTrans = cur ? list(cur.transition).map(id => journey!.transitions.find(x => x.id === id)).filter(Boolean) as Transition[] : [];
  const tileOf = (cid: string) => { const c = comps[cid]; return c ? (c.host || "x:" + c.id) : ""; };

  /* measure tile positions for the connection overlay */
  const measure = useCallback(() => {
    const stage = stageRef.current; if (!stage) return;
    const base = stage.getBoundingClientRect(); const next: Record<string, Rect> = {};
    Object.entries(tiles.current).forEach(([id, el]) => { if (el && el.isConnected) { const r = el.getBoundingClientRect(); next[id] = { x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height }; } });
    setRects(prev => JSON.stringify(prev) === JSON.stringify(next) ? prev : next);
  }, []);
  useLayoutEffect(() => { measure(); });
  useEffect(() => {
    const stage = stageRef.current; if (!stage) return;
    const ro = new ResizeObserver(() => measure()); ro.observe(stage); return () => ro.disconnect();
  }, [measure, data]);

  /* playback */
  useEffect(() => {
    if (!playing || !total) return;
    let raf = 0, last = performance.now();
    const tick = (now: number) => { const dt = Math.min(100, now - last); last = now; setT(v => Math.min(total, v + dt / STEP_MS)); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick); return () => cancelAnimationFrame(raf);
  }, [playing, total]);
  useEffect(() => { if (playing && t >= total) setPlaying(false); }, [playing, t, total]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setSelected(null); return; }
      if (!flow) return;
      const tag = (e.target as HTMLElement)?.tagName; if (tag === "INPUT" || tag === "SELECT") return;
      if (e.key === " ") { e.preventDefault(); setPlaying(p => !p); }
      if (e.key === "ArrowRight") { e.preventDefault(); setPlaying(false); setT(Math.min(total - 1, step + 1)); }
      if (e.key === "ArrowLeft") { e.preventDefault(); setPlaying(false); setT(Math.max(0, step - 1)); }
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, [flow, step, total]);

  if (error) return <section className="sx"><div className="sx-msg">The system explorer could not load: {error}</div></section>;
  if (!data || !model) return <section className="sx"><div className="loading"><span /><strong>Drawing the system…</strong></div></section>;

  /* lines: the selected host's connections to other tiles, or the current flow stage */
  const centre = (r: Rect) => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });
  const edgePoint = (r: Rect, toward: { x: number; y: number }) => {
    const c = centre(r), dx = toward.x - c.x, dy = toward.y - c.y;
    const sx = dx ? (r.w / 2) / Math.abs(dx) : Infinity, sy = dy ? (r.h / 2) / Math.abs(dy) : Infinity, k = Math.min(sx, sy);
    return { x: c.x + dx * k, y: c.y + dy * k };
  };
  const pathBetween = (a: string, b: string) => {
    const ra = rects[a], rb = rects[b]; if (!ra || !rb) return "";
    const p1 = edgePoint(ra, centre(rb)), p2 = edgePoint(rb, centre(ra));
    const mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2, bend = Math.min(40, Math.hypot(p2.x - p1.x, p2.y - p1.y) / 6);
    const nx = -(p2.y - p1.y), ny = p2.x - p1.x, n = Math.hypot(nx, ny) || 1;
    return `M${p1.x},${p1.y} Q${mx + (nx / n) * bend},${my + (ny / n) * bend} ${p2.x},${p2.y}`;
  };
  const selLinks = selected && !flow ? (() => {
    const pairs = new Map<string, { a: string; b: string; out: boolean }>();
    data.edges.forEach(e => {
      if (e.s !== selected && e.t !== selected) return;
      const other = e.s === selected ? e.t : e.s; if (!rects[other]) return;
      if (!pairs.has(other)) pairs.set(other, { a: selected, b: other, out: e.s === selected });
    });
    return [...pairs.values()];
  })() : [];
  const selDeps = selected && !flow ? data.dependencies.filter(d => d.from === selected).flatMap(d => d.to.filter(x => rects[x]).map(x => ({ id: d.id + x, a: selected, b: x }))) : [];
  const flowDeps = cur ? list(cur.dependencies).map(id => deps[id]).filter(Boolean).flatMap(d => d.to.filter(x => rects[x]).map(x => ({ id: d.id + x, a: d.from, b: x }))) : [];
  const linked = new Set<string>([...selLinks.map(l => l.b), ...selDeps.map(d => d.b)]);
  const active = new Set<string>();
  if (cur) { if (cur.component) active.add(tileOf(cur.component)); curTrans.forEach(x => { active.add(tileOf(x.from)); active.add(tileOf(x.to)); }); flowDeps.forEach(d => active.add(d.b)); }
  const stateOf = (id: string) => selected === id ? " sel" : (selected && !flow && !linked.has(id)) || (flow && active.size > 0 && !active.has(id)) ? " quiet" : active.has(id) ? " on" : "";

  const tile = (h: Host) => {
    const notCaptured = h.kind !== "captured";
    return <button key={h.id} ref={el => { tiles.current[h.id] = el; }} className={`sx-tile${notCaptured ? " nc" : ""}${stateOf(h.id)}`}
      onClick={() => setSelected(selected === h.id ? null : h.id)} aria-pressed={selected === h.id}>
      <b>{h.id}</b><span>{h.role || "Role not recorded"}</span>{notCaptured && <i>not captured</i>}
    </button>;
  };

  const token = (x: Transition) => {
    const el = pathRefs.current[x.id]; if (!el || !(x.status === "verified" || x.status === "inferred") || !el.getAttribute("d")) return null;
    const p = el.getPointAtLength(Math.min(1, progress * 1.2) * el.getTotalLength());
    return <circle key={"k" + x.id} className={`sx-token ${x.status}`} cx={p.x} cy={p.y} r={7} />;
  };

  const sel = selected && !selected.startsWith("x:") ? (model.byId[selected] || null) : null;
  const selExt = selected?.startsWith("x:") ? comps[selected.slice(2)] : null;

  return <section className={`sx${flow ? " flowing" : ""}`}>
    <header className="sx-head">
      <div><h2>{data.application}</h2>
        <p>{model.sys.length - model.loose.length} hosts across {model.sites.length} sites. Select a host to explore it.</p></div>
      {journey && <button className={`sx-flowbtn${flow ? " on" : ""}`} onClick={() => { const next = !flow; setFlow(next); setT(0); setPlaying(next); setSelected(null); }}>
        {flow ? "Close data flow" : "▶ Show how data flows"}</button>}
    </header>

    <div className={`sx-body${sel || selExt ? " has-panel" : ""}`}>
      <div className="sx-stage" ref={stageRef}>
        <div className="sx-grid" style={{ gridTemplateColumns: `130px repeat(${model.sites.length}, minmax(0, 1fr))` }}>
          <div />{model.sites.map(s => <div key={s} className="sx-site">{s}</div>)}
          {model.tiers.map(tr => [
            <div key={tr.key + "-l"} className="sx-tier">{tr.label}</div>,
            ...model.sites.map(s => <div key={tr.key + s} className="sx-cell">{model.cell(s, tr.key).map(tile)}</div>),
          ])}
        </div>

        <div className="sx-services">
          <div className="sx-tier">Relies on</div>
          <div className="sx-svc-row">
            {model.services.map(h => <button key={h.id} ref={el => { tiles.current[h.id] = el; }} className={`sx-tile svc${stateOf(h.id)}`}
              onClick={() => setSelected(selected === h.id ? null : h.id)}><b>{h.id}</b><span>Domain controller{h.site ? ` · ${h.site}` : ""}</span></button>)}
            {model.externals.map(c => <button key={c.id} ref={el => { tiles.current["x:" + c.id] = el; }} className={`sx-tile svc ext${stateOf("x:" + c.id)}`}
              onClick={() => setSelected(selected === "x:" + c.id ? null : "x:" + c.id)}><b>{c.name}</b><span>{SAYS[c.status]}</span></button>)}
          </div>
        </div>

        {model.loose.length > 0 && <p className="sx-note">Also in the AD inventory, with no role or site recorded: {model.loose.map((h, i) =>
          <span key={h.id}>{i ? ", " : ""}<button className="sx-link" onClick={() => setSelected(h.id)}>{h.id}</button></span>)}.</p>}

        <svg className="sx-lines" aria-hidden="true">
          <defs><marker id="sx-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" /></marker></defs>
          {selLinks.map(l => <path key={l.b} className="sx-line" d={l.out ? pathBetween(l.a, l.b) : pathBetween(l.b, l.a)} markerEnd="url(#sx-arrow)" />)}
          {curTrans.map(x => <path key={x.id} ref={el => { pathRefs.current[x.id] = el; }} className={`sx-line flow ${x.status}`} d={pathBetween(tileOf(x.from), tileOf(x.to))} markerEnd="url(#sx-arrow)" />)}
          {curTrans.map(token)}
        </svg>
      </div>

      {(sel || selExt) && <aside className="sx-panel" aria-live="polite">
        <button className="sx-close" onClick={() => setSelected(null)} aria-label="Close">×</button>
        {sel ? <HostDetail host={sel} data={data} model={model} go={setSelected} /> : selExt && <div className="sx-detail">
          <h3>{selExt.name}</h3><p className="sx-sub">{SAYS[selExt.status]}</p><p>{selExt.role}</p></div>}
      </aside>}
    </div>

    {flow && journey && cur && <div className="sx-flow" role="group" aria-label="Data flow">
      <div className="sx-flow-text">
        <span className="sx-flow-title">{journey.title}</span>
        <h3>{step + 1}. {cur.action} <em className={cur.status}>{SAYS[cur.status]}</em></h3>
        <p>{cur.narrative}</p>
        {cur.inference && <p className="sx-flow-note">{cur.inference}</p>}
        {!!cur.gaps?.length && <p className="sx-flow-note">Not yet known: {cur.gaps.join(" ")}</p>}
        {step === 0 && <p className="sx-flow-note">What starts it: {journey.trigger.text}</p>}
      </div>
      <div className="sx-flow-ctl">
        <button onClick={() => { setPlaying(false); setT(Math.max(0, step - 1)); }} disabled={step === 0} aria-label="Previous step">‹</button>
        <button className="play" onClick={() => { if (t >= total) { setT(0); setPlaying(true); } else setPlaying(p => !p); }}>{playing ? "Pause" : t >= total ? "Replay" : "Play"}</button>
        <button onClick={() => { setPlaying(false); setT(Math.min(total - 1, step + 1)); }} disabled={step >= total - 1} aria-label="Next step">›</button>
        <div className="sx-dots">{journey.steps.map((s, i) => <button key={s.id} className={i === step ? "on" : ""} title={s.action} onClick={() => { setPlaying(false); setT(i); }} aria-label={`Step ${i + 1}: ${s.action}`} />)}</div>
        <span className="sx-pace">Playback speed is for reading, not real timing.</span>
      </div>
    </div>}
  </section>;
}

function HostDetail({ host, data, model, go }: { host: Host; data: Data; model: Model; go: (id: string) => void }) {
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
  const named = all.filter(p => { const h = model.byId[p.id]; return h && h.kind !== "unnamed" && h.kind !== "public"; }).sort((a, b) => a.id.localeCompare(b.id));
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
          <small>{model.byId[p.id]?.role ? `${model.byId[p.id].role} · ` : ""}{usage(p)}</small></div></li>)}</ul>
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
