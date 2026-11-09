import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Empty } from "./ui";
import type { AssetDetail, AssetGroup, AssetItem, AssetKind, AssetList } from "../types";
import "./assets.css";

const VIEWS: { id: AssetKind; title: string; what: string }[] = [
  { id: "application_hosts", title: "Application hosts", what: "Hosts in the host register that run the application under assessment." },
  { id: "devices", title: "Connected devices", what: "Devices recorded in the connected-device register. They are not application hosts." },
  { id: "unidentified", title: "Unidentified addresses", what: "Addresses seen in captures that no register host or device owns. They are not confirmed devices." },
  { id: "conflicts", title: "Conflicts", what: "Addresses claimed twice, or claimed by a device while a register host owns them. Nothing is resolved by guess." },
];
const PER_PAGE = 25;
const OBSERVATION_LABEL: Record<string, string> = {
  captured_connection: "Observed connection", configured_service: "Configured service", documented_dependency: "Documented dependency",
};

function title(item: AssetItem) { return item.name || item.address || item.id; }
function list(values?: string[]) { return values && values.length ? values.join(", ") : "none recorded"; }

export default function AssetsPage({ system, openEvidenceId, openNetwork }: { system: string; openEvidenceId: (id: string) => void; openNetwork: () => void }) {
  const [view, setView] = useState<AssetKind>("application_hosts");
  const [query, setQuery] = useState(""); const [type, setType] = useState(""); const [state, setState] = useState(""); const [page, setPage] = useState(1);
  const [data, setData] = useState<AssetList | null>(null); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const [detail, setDetail] = useState<AssetDetail | null>(null); const [detailError, setDetailError] = useState(""); const [detailLoading, setDetailLoading] = useState(false);
  const panel = useRef<HTMLElement>(null); const opener = useRef<HTMLElement | null>(null);

  useEffect(() => { setPage(1); }, [view, query, type, state, system]);
  useEffect(() => { setType(""); setState(""); }, [view]);
  useEffect(() => {
    let live = true; setLoading(true); setError("");
    const params = new URLSearchParams({ kind: view, page: String(page), per_page: String(PER_PAGE) });
    if (query.trim()) params.set("q", query.trim());
    if (type) params.set("type", type);
    if (state) params.set("state", state);
    api<AssetList>(`/api/systems/${encodeURIComponent(system)}/assets?${params}`)
      .then(result => { if (live) setData(result); }).catch(e => { if (live) setError((e as Error).message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [system, view, query, type, state, page]);
  useEffect(() => { setDetail(null); setDetailError(""); }, [system, view]);

  // Filter choices come from the unfiltered rows of this view, so a chosen filter never hides its own alternatives.
  const [choices, setChoices] = useState<{ types: string[]; states: string[] }>({ types: [], states: [] });
  useEffect(() => {
    let live = true;
    api<AssetList>(`/api/systems/${encodeURIComponent(system)}/assets?kind=${view}&per_page=500`).then(result => {
      if (!live) return; const rows = result.groups[view]?.items || [];
      setChoices({ types: [...new Set(rows.map(r => r.type || "").filter(Boolean))].sort(), states: [...new Set(rows.map(r => r.state || "").filter(Boolean))].sort() });
    }).catch(() => { if (live) setChoices({ types: [], states: [] }); });
    return () => { live = false; };
  }, [system, view]);

  function open(item: AssetItem, element: HTMLElement) {
    opener.current = element; setDetail(null); setDetailError(""); setDetailLoading(true);
    api<AssetDetail>(`/api/systems/${encodeURIComponent(system)}/assets/${encodeURIComponent(item.id)}?kind=${view}`)
      .then(result => { setDetail(result); setTimeout(() => panel.current?.focus(), 0); })
      .catch(e => setDetailError((e as Error).message)).finally(() => setDetailLoading(false));
  }
  function close() { setDetail(null); setDetailError(""); opener.current?.focus(); }

  const group: AssetGroup | undefined = data?.groups[view];
  const total = group?.total || 0; const pages = Math.max(1, Math.ceil(total / PER_PAGE));
  const current = VIEWS.find(v => v.id === view)!;
  const filtered = Boolean(query.trim() || type || state);

  return <section className="page assets-page">
    <div className="page-heading"><div><span>Inventory</span><h1>Hosts &amp; connected devices</h1>
      <p>What the project's evidence names. Application hosts, connected devices, unidentified addresses and conflicts are kept apart.</p></div>
      <button type="button" className="quiet" onClick={openNetwork}>Open Host network</button></div>
    <p className="assets-note" role="note"><b>Observation is not dependency.</b> A captured connection is what was seen, a configured service is what a host is set to use, and a documented dependency is a verified statement. None of them is a migration dependency on its own.</p>
    <div className="assets-tabs" role="tablist" aria-label="Inventory views">{VIEWS.map(v => <button key={v.id} role="tab" aria-selected={view === v.id} className={view === v.id ? "active" : ""} onClick={() => setView(v.id)}>{v.title}<span>{data ? data.counts[v.id] : "–"}</span></button>)}</div>
    <p className="assets-what">{current.what}</p>
    <div className="assets-filters">
      <label>Search<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Name, address, role or site" /></label>
      {choices.types.length > 0 && <label>Type<select value={type} onChange={e => setType(e.target.value)}><option value="">All types</option>{choices.types.map(t => <option key={t}>{t}</option>)}</select></label>}
      {choices.states.length > 0 && <label>State<select value={state} onChange={e => setState(e.target.value)}><option value="">All states</option>{choices.states.map(s => <option key={s}>{s}</option>)}</select></label>}
      {filtered && <button type="button" className="quiet" onClick={() => { setQuery(""); setType(""); setState(""); }}>Clear filters</button>}
    </div>
    {error && <div className="error" role="alert"><div><b>Inventory unavailable</b><span>{error}</span></div></div>}
    <div className="assets-layout">
      <div className="assets-list" aria-busy={loading}>
        {loading && !group ? <div className="loading"><span /><strong>Reading the inventory…</strong></div> :
          group && group.items.length ? <>
            <ul>{group.items.map(item => <li key={`${item.kind}-${item.id}`}><button type="button" className={detail?.id === item.id && detail.kind === view ? "active" : ""} onClick={e => open(item, e.currentTarget)}>
              <strong>{title(item)}</strong>
              <span>{[item.type, item.role, item.site, item.address && item.name ? item.address : ""].filter(Boolean).join(" · ") || item.kind.replaceAll("_", " ")}</span>
              {view === "devices" && <em>{item.state || "state not recorded"}</em>}
              {view === "unidentified" && <em>unidentified{item.claimed_by_device ? `, listed by ${item.claimed_by_device}` : ""}</em>}
              {view === "conflicts" && <em>{item.kind.replaceAll("_", " ")}</em>}
              {view === "application_hosts" && <em>{item.state}</em>}
            </button></li>)}</ul>
            <div className="assets-pager"><button type="button" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button><span>Page {page} of {pages} · {total} {total === 1 ? "row" : "rows"}</span><button type="button" disabled={page >= pages} onClick={() => setPage(p => p + 1)}>Next</button></div>
          </> : !error && <Empty title={filtered ? "Nothing matches these filters" : `No ${current.title.toLowerCase()} recorded`} text={filtered ? "Clear a filter or search for something else." : "The project's host register, address list and device register hold no rows for this view."} />}
      </div>
      <aside className="assets-detail" ref={panel} tabIndex={-1} aria-label="Asset detail" aria-live="polite">
        {detailLoading ? <p>Loading detail…</p> : detailError ? <div className="error" role="alert"><div><b>Detail unavailable</b><span>{detailError}</span></div></div> : detail ? <Detail detail={detail} openEvidenceId={openEvidenceId} close={close} /> :
          <p className="assets-hint">Select a row to see its aliases, connections, services and the evidence behind it.</p>}
      </aside>
    </div>
    {data && <p className="assets-sources">Sources read: {data.sources.length ? data.sources.join(", ") : "none"}.</p>}
  </section>;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) { return <div><dt>{label}</dt><dd>{children}</dd></div>; }

function Detail({ detail, openEvidenceId, close }: { detail: AssetDetail; openEvidenceId: (id: string) => void; close: () => void }) {
  const a = detail.asset; const kind = VIEWS.find(v => v.id === detail.kind)?.title || detail.kind;
  const direction = list(a.direction?.length ? a.direction : a.directions);
  return <div className="assets-detail-body">
    <header><div><span>{kind}</span><h2>{title(a)}</h2></div><button type="button" className="quiet" onClick={close} aria-label="Close detail">Close</button></header>
    {detail.other_kinds.length > 0 && <p className="assets-hint">The same identifier also appears under {detail.other_kinds.map(k => VIEWS.find(v => v.id === k)?.title || k).join(", ")}.</p>}
    <dl>
      {a.type && <Row label="Type">{a.type}</Row>}{a.role && <Row label="Role">{a.role}</Row>}{a.site && <Row label="Site or zone">{a.site}</Row>}
      {a.owner && <Row label="Owner">{a.owner}</Row>}{a.state && <Row label="State">{a.state}</Row>}
      {a.classification && <Row label="Classification">{a.classification}</Row>}{a.relationship && <Row label="Relationship">{a.relationship}</Row>}
      {a.address && <Row label="Address">{a.address}</Row>}
      {a.aliases && <Row label="Aliases">{list(a.aliases)}</Row>}
      {a.connected_application_hosts && <Row label="Connected application hosts">{list(a.connected_application_hosts)}</Row>}
      {a.claimed_by && <Row label="Claimed by">{list(a.claimed_by)}</Row>}{a.host && <Row label="Owned by register host">{a.host}</Row>}
      {a.seen_from && <Row label="Seen from">{list(a.seen_from)}</Row>}
      {(a.direction || a.directions) && <Row label="Direction">{direction}</Row>}
      {a.ports && <Row label="Ports">{list(a.ports)}</Row>}{a.processes && <Row label="Processes">{list(a.processes)}</Row>}
      {a.sessions && <Row label="Sessions">{a.sessions}</Row>}
      {a.observation_type && <Row label="Basis">{a.observation_type.length ? a.observation_type.map(t => OBSERVATION_LABEL[t] || t).join(", ") : "No observation recorded"}</Row>}
    </dl>
    {a.services && <><h3>Configured services</h3>{a.services.length ? <ul className="assets-plain">{a.services.map((s, i) => <li key={i}>{s.service} → {s.server_host || s.server_ip}{s.server_host && s.server_ip ? ` (${s.server_ip})` : ""} <small>configured, not observed{s.source ? ` · ${s.source}` : ""}</small></li>)}</ul> : <p className="assets-hint">None recorded.</p>}</>}
    {a.observed_connections && <><h3>Observed connections</h3>{a.observed_connections.length ? <ul className="assets-plain">{a.observed_connections.map((c, i) => <li key={i}>{c.src} → {c.dst}{c.dst_port ? `:${c.dst_port}` : ""} <small>observed · {c.connections || "?"} connection(s){c.basis ? ` · ${c.basis}` : ""}</small></li>)}</ul> : <p className="assets-hint">None recorded.</p>}</>}
    {a.documented_dependencies && <><h3>Documented dependencies</h3>{a.documented_dependencies.length ? <ul className="assets-plain">{a.documented_dependencies.map(d => <li key={d}>{d} <small>documented dependency</small></li>)}</ul> : <p className="assets-hint">None documented.</p>}</>}
    <h3>Sources</h3>
    {detail.source_links.files.length ? <ul className="assets-plain">{detail.source_links.files.map(f => <li key={f}><code>{f}</code></li>)}</ul> : <p className="assets-hint">No source file recorded.</p>}
    <h3>Evidence</h3>
    {detail.source_links.evidence.length ? <ul className="assets-plain">{detail.source_links.evidence.map(e => <li key={e.evidence_id}><button type="button" className="link" onClick={() => openEvidenceId(e.evidence_id)}>{e.evidence_id}</button> {e.claim}</li>)}</ul> : <p className="assets-hint">No verified evidence row names this asset.</p>}
  </div>;
}
