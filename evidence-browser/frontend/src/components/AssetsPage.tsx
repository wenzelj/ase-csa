import { useEffect, useRef, useState } from "react";
import { addDeviceAlias, api, createDevice, DeviceEditError, patchDevice, previewDeviceAliases, removeDeviceAlias, restoreDevice, retireDevice } from "../api";
import { Empty } from "./ui";
import type { AliasPreview, AssetDetail, AssetGroup, AssetItem, AssetKind, AssetList, DeviceEditResult, DevicePayload } from "../types";
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

const CLASSIFICATIONS = ["unknown", "supporting IT", "shared", "platform", "OT", "external", "unclassified"];
const STATES = ["unidentified", "proposed", "confirmed", "disputed"];
type Mode = { kind: "detail" } | { kind: "create"; addresses: string[] } | { kind: "edit"; device: AssetItem; state?: string } | { kind: "attach"; address: string; device?: AssetItem };

export default function AssetsPage({ system, openEvidenceId, openNetwork }: { system: string; openEvidenceId: (id: string) => void; openNetwork: () => void }) {
  const [view, setView] = useState<AssetKind>("application_hosts");
  const [query, setQuery] = useState(""); const [type, setType] = useState(""); const [state, setState] = useState(""); const [page, setPage] = useState(1);
  const [data, setData] = useState<AssetList | null>(null); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const [detail, setDetail] = useState<AssetDetail | null>(null); const [detailError, setDetailError] = useState(""); const [detailLoading, setDetailLoading] = useState(false);
  const panel = useRef<HTMLElement>(null); const opener = useRef<HTMLElement | null>(null);
  const [mode, setMode] = useState<Mode>({ kind: "detail" }); const [tick, setTick] = useState(0); const [showRetired, setShowRetired] = useState(false); const [saved, setSaved] = useState("");

  useEffect(() => { setPage(1); }, [view, query, type, state, system]);
  useEffect(() => { setType(""); setState(""); setMode({ kind: "detail" }); setSaved(""); }, [view]);
  useEffect(() => {
    let live = true; setLoading(true); setError("");
    const params = new URLSearchParams({ kind: view, page: String(page), per_page: String(PER_PAGE) });
    if (query.trim()) params.set("q", query.trim());
    if (type) params.set("type", type);
    if (state) params.set("state", state);
    if (view === "devices" && showRetired) params.set("include_retired", "true");
    api<AssetList>(`/api/systems/${encodeURIComponent(system)}/assets?${params}`)
      .then(result => { if (live) setData(result); }).catch(e => { if (live) setError((e as Error).message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [system, view, query, type, state, page, showRetired, tick]);
  useEffect(() => { setDetail(null); setDetailError(""); }, [system, view]);

  // Filter choices come from the unfiltered rows of this view, so a chosen filter never hides its own alternatives.
  const [choices, setChoices] = useState<{ types: string[]; states: string[] }>({ types: [], states: [] });
  useEffect(() => {
    let live = true;
    api<AssetList>(`/api/systems/${encodeURIComponent(system)}/assets?kind=${view}&per_page=500${view === "devices" && showRetired ? "&include_retired=true" : ""}`).then(result => {
      if (!live) return; const rows = result.groups[view]?.items || [];
      setChoices({ types: [...new Set(rows.map(r => r.type || "").filter(Boolean))].sort(), states: [...new Set(rows.map(r => r.state || "").filter(Boolean))].sort() });
    }).catch(() => { if (live) setChoices({ types: [], states: [] }); });
    return () => { live = false; };
  }, [system, view, showRetired, tick]);

  function loadDetail(id: string, kind: AssetKind) {
    setDetailError(""); setDetailLoading(true);
    return api<AssetDetail>(`/api/systems/${encodeURIComponent(system)}/assets/${encodeURIComponent(id)}?kind=${kind}`)
      .then(result => { setDetail(result); return result; })
      .catch(e => { setDetail(null); setDetailError((e as Error).message); return null; }).finally(() => setDetailLoading(false));
  }
  function open(item: AssetItem, element: HTMLElement) {
    opener.current = element; setDetail(null); setMode({ kind: "detail" }); setSaved("");
    void loadDetail(item.id, view).then(() => setTimeout(() => panel.current?.focus(), 0));
  }
  // After a save: re-read the list, then show the saved device (switching to Connected devices if needed).
  async function saved_(result: DeviceEditResult, message: string) {
    setMode({ kind: "detail" }); setSaved(message); setTick(t => t + 1);
    if (view !== "devices") setView("devices");
    await loadDetail(result.device.device_id, "devices");
    setSaved(message);                                   // the view change above clears it, so set it once more
    setTimeout(() => panel.current?.focus(), 0);
  }
  function close() { setDetail(null); setDetailError(""); setMode({ kind: "detail" }); setSaved(""); opener.current?.focus(); }

  const group: AssetGroup | undefined = data?.groups[view];
  const total = group?.total || 0; const pages = Math.max(1, Math.ceil(total / PER_PAGE));
  const current = VIEWS.find(v => v.id === view)!;
  const filtered = Boolean(query.trim() || type || state);

  return <section className="page assets-page">
    <div className="page-heading"><div><span>Inventory</span><h1>Hosts &amp; connected devices</h1>
      <p>What the project's evidence names. Application hosts, connected devices, unidentified addresses and conflicts are kept apart.</p></div>
      <div className="assets-heading-actions">{view === "devices" && <button type="button" onClick={() => { setDetail(null); setSaved(""); setMode({ kind: "create", addresses: [] }); setTimeout(() => panel.current?.focus(), 0); }}>New device</button>}<button type="button" className="quiet" onClick={openNetwork}>Open Host network</button></div></div>
    <p className="assets-note" role="note"><b>Observation is not dependency.</b> A captured connection is what was seen, a configured service is what a host is set to use, and a documented dependency is a verified statement. None of them is a migration dependency on its own.</p>
    <div className="assets-tabs" role="tablist" aria-label="Inventory views">{VIEWS.map(v => <button key={v.id} role="tab" aria-selected={view === v.id} className={view === v.id ? "active" : ""} onClick={() => setView(v.id)}>{v.title}<span>{data ? data.counts[v.id] : "–"}</span></button>)}</div>
    <p className="assets-what">{current.what}</p>
    <div className="assets-filters">
      <label>Search<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Name, address, role or site" /></label>
      {choices.types.length > 0 && <label>Type<select value={type} onChange={e => setType(e.target.value)}><option value="">All types</option>{choices.types.map(t => <option key={t}>{t}</option>)}</select></label>}
      {choices.states.length > 0 && <label>State<select value={state} onChange={e => setState(e.target.value)}><option value="">All states</option>{choices.states.map(s => <option key={s}>{s}</option>)}</select></label>}
      {view === "devices" && <label className="assets-check"><input type="checkbox" checked={showRetired} onChange={e => setShowRetired(e.target.checked)} />Show retired devices</label>}
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
              {view === "devices" && <em>{item.active === false ? "retired · " : ""}{item.state || "state not recorded"}</em>}
              {view === "unidentified" && <em>unidentified{item.claimed_by_device ? `, listed by ${item.claimed_by_device}` : ""}</em>}
              {view === "conflicts" && <em>{item.kind.replaceAll("_", " ")}</em>}
              {view === "application_hosts" && <em>{item.state}</em>}
            </button></li>)}</ul>
            <div className="assets-pager"><button type="button" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button><span>Page {page} of {pages} · {total} {total === 1 ? "row" : "rows"}</span><button type="button" disabled={page >= pages} onClick={() => setPage(p => p + 1)}>Next</button></div>
          </> : !error && <Empty title={filtered ? "Nothing matches these filters" : `No ${current.title.toLowerCase()} recorded`} text={filtered ? "Clear a filter or search for something else." : "The project's host register, address list and device register hold no rows for this view."} />}
      </div>
      <aside className="assets-detail" ref={panel} tabIndex={-1} aria-label="Asset detail" aria-live="polite">
        {saved && <p className="assets-saved" role="status">{saved}</p>}
        {mode.kind === "create" ? <DeviceForm key={`create-${mode.addresses.join()}`} system={system} initialAddresses={mode.addresses} onSaved={r => saved_(r, "Device saved to the connected-device register.")} onCancel={() => setMode({ kind: "detail" })} /> :
          mode.kind === "edit" ? <DeviceForm key={`edit-${mode.device.id}-${mode.state || ""}`} system={system} device={mode.device} initialState={mode.state} onSaved={r => saved_(r, "Changes saved to the connected-device register.")} onCancel={() => setMode({ kind: "detail" })} /> :
          mode.kind === "attach" ? <AttachPanel key={`attach-${mode.address}`} system={system} address={mode.address} device={mode.device} onSaved={r => saved_(r, "Address attached to the device.")} onCancel={() => setMode({ kind: "detail" })} /> :
          detailLoading ? <p>Loading detail…</p> : detailError ? <div className="error" role="alert"><div><b>Detail unavailable</b><span>{detailError}</span></div></div> : detail ? <Detail system={system} detail={detail} openEvidenceId={openEvidenceId} close={close} setMode={setMode} onSaved={saved_} reload={() => { setTick(t => t + 1); void loadDetail(detail.id, detail.kind); }} /> :
          <p className="assets-hint">Select a row to see its aliases, connections, services and the evidence behind it.</p>}
      </aside>
    </div>
    {data && <p className="assets-sources">Sources read: {data.sources.length ? data.sources.join(", ") : "none"}.</p>}
  </section>;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) { return <div><dt>{label}</dt><dd>{children}</dd></div>; }

function Detail({ system, detail, openEvidenceId, close, setMode, onSaved, reload }: { system: string; detail: AssetDetail; openEvidenceId: (id: string) => void; close: () => void; setMode: (m: Mode) => void; onSaved: (r: DeviceEditResult, message: string) => Promise<void>; reload: () => void }) {
  const a = detail.asset; const kind = VIEWS.find(v => v.id === detail.kind)?.title || detail.kind;
  const direction = list(a.direction?.length ? a.direction : a.directions);
  return <div className="assets-detail-body">
    <header><div><span>{kind}</span><h2>{title(a)}</h2></div><button type="button" className="quiet" onClick={close} aria-label="Close detail">Close</button></header>
    <Actions system={system} detail={detail} setMode={setMode} onSaved={onSaved} reload={reload} />
    {detail.other_kinds.length > 0 && <p className="assets-hint">The same identifier also appears under {detail.other_kinds.map(k => VIEWS.find(v => v.id === k)?.title || k).join(", ")}.</p>}
    <dl>
      {a.type && <Row label="Type">{a.type}</Row>}{a.role && <Row label="Role">{a.role}</Row>}{a.site && <Row label="Site or zone">{a.site}</Row>}
      {a.owner && <Row label="Owner">{a.owner}</Row>}{a.state && <Row label="State">{a.state}</Row>}
      {a.classification && <Row label="Classification">{a.classification}</Row>}{a.relationship && <Row label="Relationship">{a.relationship}</Row>}
      {a.address && <Row label="Address">{a.address}</Row>}
      {a.aliases && <Row label="Aliases">{detail.kind === "devices" && a.active !== false && a.aliases.length ? <ul className="assets-plain">{a.aliases.map(x => <li key={x}>{x} <RemoveAlias system={system} device={a} address={x} onSaved={onSaved} reload={reload} /></li>)}</ul> : list(a.aliases)}</Row>}
      {a.kind === "connected_device" && <><Row label="Revision">{a.revision || "not recorded"}</Row>{a.provenance && <Row label="Provenance">{a.provenance}</Row>}{a.reviewer && <Row label="Reviewer">{a.reviewer}</Row>}{a.recorded && <Row label="Recorded">{a.recorded}</Row>}</>}
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

type Reload = () => void;

function resolution(state: { resolves_to: string; id: string; name: string } | null) {
  if (!state) return "not checked";
  const named = state.name ? `${state.id} (${state.name})` : state.id;
  switch (state.resolves_to) {
    case "application_host": return `application host ${named}`;
    case "connected_device": return `connected device ${named}`;
    case "unidentified_address": return "unidentified address";
    case "ambiguous": return `ambiguous: claimed by ${state.id}`;
    default: return "nothing recorded";
  }
}

function EditError({ error, reload }: { error: Error | null; reload?: () => void }) {
  if (!error) return null;
  const e = error as DeviceEditError;
  const title = e.stale ? "This device has changed" : e.code === "host_owned" || e.code === "alias_claimed" ? "Address conflict" : e.code === "confirmation_required" || e.code === "invalid_date" ? "Confirmation needs a basis" : "Not saved";
  return <div className="error" role="alert"><div><b>{title}</b><span>{e.message}{e.stale ? " Your entries are kept; use the latest revision, check the device's current values, then save again." : ""}</span></div>{e.stale && reload && <button type="button" onClick={reload}>Use latest revision</button>}</div>;
}

function PreviewTable({ preview }: { preview: AliasPreview }) {
  return <div className="assets-preview"><h3>Before and after</h3>
    <table><thead><tr><th>Change</th><th>Address</th><th>Resolves to now</th><th>Resolves to after saving</th></tr></thead><tbody>
      {preview.changes.map((c, i) => <tr key={i} className={c.status === "blocked" ? "blocked" : ""}><td>{c.action === "add" ? "Attach" : "Remove"}</td><td>{c.normalized || c.address}</td><td>{resolution(c.before)}</td><td>{c.status === "blocked" ? <><b>Blocked.</b> {c.reasons.join("; ")}</> : resolution(c.after)}</td></tr>)}
    </tbody></table><p className="assets-hint">{preview.note} Observed connections are not changed.</p></div>;
}

function Note() { return <p className="assets-hint">Saving changes only the connected-device register and its audit log. Generated host, evidence and graph files are never edited here.</p>; }

async function latestRevision(system: string, id: string): Promise<string> {
  const result = await api<AssetDetail>(`/api/systems/${encodeURIComponent(system)}/assets/${encodeURIComponent(id)}?kind=devices`);
  return result.asset.revision || "";
}

function Actions({ system, detail, setMode, onSaved, reload }: { system: string; detail: AssetDetail; setMode: (m: Mode) => void; onSaved: (r: DeviceEditResult, message: string) => Promise<void>; reload: Reload }) {
  const a = detail.asset; const [retiring, setRetiring] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState<Error | null>(null);
  async function run(call: () => Promise<DeviceEditResult>, message: string) {
    setBusy(true); setError(null);
    try { const result = await call(); setRetiring(false); await onSaved(result, message); } catch (e) { setError(e as Error); } finally { setBusy(false); }
  }
  if (detail.kind === "unidentified") {
    return <div className="assets-actions"><button type="button" onClick={() => setMode({ kind: "create", addresses: [a.address || a.id] })}>Identify as a new device</button><button type="button" className="quiet" onClick={() => setMode({ kind: "attach", address: a.address || a.id })}>Attach to an existing device</button></div>;
  }
  if (detail.kind !== "devices") return null;
  const revision = a.revision || "";
  if (a.active === false) {
    return <div className="assets-actions"><p className="assets-hint">Retired: this device no longer identifies any address. Its row and history stay in the register.</p><button type="button" disabled={busy} onClick={() => void run(() => restoreDevice(system, a.id, revision), "Device restored.")}>Restore device</button><EditError error={error} reload={reload} /></div>;
  }
  return <div className="assets-actions">
    <div><button type="button" onClick={() => setMode({ kind: "edit", device: a })}>Edit</button>
      <button type="button" className="quiet" onClick={() => setMode({ kind: "edit", device: a, state: "confirmed" })}>Confirm identity</button>
      <button type="button" className="quiet" onClick={() => setMode({ kind: "edit", device: a, state: "disputed" })}>Dispute</button>
      <button type="button" className="quiet" onClick={() => setMode({ kind: "attach", address: "", device: a })}>Attach address</button>
      <button type="button" className="danger" onClick={() => setRetiring(true)}>Retire</button></div>
    {retiring && <div className="assets-confirm" role="alertdialog" aria-label="Confirm retirement"><p><b>Retire {a.name}?</b> Retirement removes this identification and its address aliases from the register. It does not remove the observed connections, captures or evidence: those addresses go back to being unidentified. The device can be restored later.</p>
      <button type="button" className="danger" disabled={busy} onClick={() => void run(() => retireDevice(system, a.id, revision), "Device retired.")}>Yes, retire this device</button><button type="button" className="quiet" onClick={() => setRetiring(false)}>Keep device</button></div>}
    <EditError error={error} reload={reload} />
  </div>;
}

function RemoveAlias({ system, device, address, onSaved, reload }: { system: string; device: AssetItem; address: string; onSaved: (r: DeviceEditResult, message: string) => Promise<void>; reload: Reload }) {
  const [preview, setPreview] = useState<AliasPreview | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<Error | null>(null);
  async function start() { setBusy(true); setError(null); try { setPreview(await previewDeviceAliases(system, device.id, [], [address])); } catch (e) { setError(e as Error); } finally { setBusy(false); } }
  async function confirm() { setBusy(true); setError(null); try { const r = await removeDeviceAlias(system, device.id, device.revision || "", address); setPreview(null); await onSaved(r, "Alias removed."); } catch (e) { setError(e as Error); } finally { setBusy(false); } }
  return <span className="assets-inline">
    {!preview && <button type="button" className="link" disabled={busy} onClick={() => void start()} aria-label={`Remove alias ${address}`}>Remove</button>}
    {preview && <div className="assets-confirm"><PreviewTable preview={preview} /><button type="button" className="danger" disabled={busy || preview.blocked} onClick={() => void confirm()}>Confirm removal</button><button type="button" className="quiet" onClick={() => setPreview(null)}>Cancel</button></div>}
    <EditError error={error} reload={reload} />
  </span>;
}

function AttachPanel({ system, address: initial, device: given, onSaved, onCancel }: { system: string; address: string; device?: AssetItem; onSaved: (r: DeviceEditResult, message: string) => Promise<void>; onCancel: () => void }) {
  const [devices, setDevices] = useState<AssetItem[]>(given ? [given] : []); const [chosen, setChosen] = useState(given?.id || "");
  const [address, setAddress] = useState(initial); const [source, setSource] = useState("");
  const [preview, setPreview] = useState<AliasPreview | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    if (given) return; let live = true;
    api<AssetList>(`/api/systems/${encodeURIComponent(system)}/assets?kind=devices&per_page=500`).then(r => { if (live) setDevices(r.groups.devices?.items || []); }).catch(e => { if (live) setError(e as Error); });
    return () => { live = false; };
  }, [system, given]);
  const device = devices.find(d => d.id === chosen);
  async function review() { setBusy(true); setError(null); try { setPreview(await previewDeviceAliases(system, chosen, [address.trim()], [])); } catch (e) { setError(e as Error); } finally { setBusy(false); } }
  async function save() { if (!device) return; setBusy(true); setError(null); try { await onSaved(await addDeviceAlias(system, device.id, device.revision || "", address.trim(), source.trim()), "Address attached to the device."); } catch (e) { setError(e as Error); } finally { setBusy(false); } }
  async function refresh() { if (!device) return; try { const revision = await latestRevision(system, device.id); setDevices(list => list.map(d => d.id === device.id ? { ...d, revision } : d)); setError(null); } catch (e) { setError(e as Error); } }
  return <form className="assets-form" onSubmit={e => { e.preventDefault(); void review(); }} aria-label="Attach an address to a device">
    <header><h2>Attach an address</h2></header>
    {!given && <label>Device<select value={chosen} onChange={e => { setChosen(e.target.value); setPreview(null); }} required><option value="">Choose a connected device</option>{devices.map(d => <option key={d.id} value={d.id}>{d.name} ({d.id})</option>)}</select></label>}
    {given && <p>Device: <b>{given.name}</b> ({given.id}), revision {device?.revision || given.revision}</p>}
    <label>Address (IP or FQDN)<input value={address} onChange={e => { setAddress(e.target.value); setPreview(null); }} required /></label>
    <label>Source<input value={source} onChange={e => setSource(e.target.value)} placeholder="Where this alias comes from" /></label>
    {preview && <PreviewTable preview={preview} />}
    <EditError error={error} reload={() => void refresh()} />
    <div className="assets-form-actions">
      {!preview ? <button type="submit" disabled={busy || !chosen || !address.trim()}>Preview change</button> : <button type="button" disabled={busy || preview.blocked} onClick={() => void save()}>Confirm and attach</button>}
      <button type="button" className="quiet" onClick={onCancel}>Cancel</button></div>
    <Note />
  </form>;
}

function DeviceForm({ system, device, initialState, initialAddresses = [], onSaved, onCancel }: { system: string; device?: AssetItem; initialState?: string; initialAddresses?: string[]; onSaved: (r: DeviceEditResult, message: string) => Promise<void>; onCancel: () => void }) {
  const [f, setF] = useState({
    name: device?.name || "", device_type: device?.type || "", role: device?.role || "", owner: device?.owner || "", site_zone: device?.site || "",
    relationship: device?.relationship || "", classification: device?.classification || "unknown", identification_state: initialState || device?.state || "unidentified",
    reviewer: "", source: "", owner_confirmed_on: "", addresses: initialAddresses.join("\n"),
  });
  const [revision, setRevision] = useState(device?.revision || ""); const [preview, setPreview] = useState<AliasPreview | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<Error | null>(null);
  const set = (key: keyof typeof f) => (e: { target: { value: string } }) => { setF(v => ({ ...v, [key]: e.target.value })); setPreview(null); };
  const addresses = f.addresses.split(/[\n,;]+/).map(x => x.trim()).filter(Boolean);
  const needsBasis = f.identification_state === "confirmed" && device?.state !== "confirmed";

  async function save() {
    setBusy(true); setError(null);
    try {
      if (!device) {
        const payload: DevicePayload = { name: f.name.trim(), device_type: f.device_type.trim(), role: f.role.trim(), owner: f.owner.trim(), site_zone: f.site_zone.trim(), relationship: f.relationship.trim(), classification: f.classification, identification_state: f.identification_state, reviewer: f.reviewer.trim(), source: f.source.trim(), owner_confirmed_on: f.owner_confirmed_on, addresses };
        await onSaved(await createDevice(system, payload), "Device saved to the connected-device register.");
      } else {
        const current: Record<string, string> = { name: device.name || "", device_type: device.type || "", role: device.role || "", owner: device.owner || "", site_zone: device.site || "", relationship: device.relationship || "", classification: device.classification || "unknown", identification_state: device.state || "unidentified" };
        const next: Record<string, string> = { name: f.name.trim(), device_type: f.device_type.trim(), role: f.role.trim(), owner: f.owner.trim(), site_zone: f.site_zone.trim(), relationship: f.relationship.trim(), classification: f.classification, identification_state: f.identification_state };
        const changes = Object.fromEntries(Object.entries(next).filter(([k, v]) => v !== current[k])) as DevicePayload;
        if (!Object.keys(changes).length) throw new Error("Nothing has changed yet.");
        await onSaved(await patchDevice(system, device.id, revision, changes, { source: f.source.trim() || undefined, owner_confirmed_on: f.owner_confirmed_on || undefined, reviewer: f.reviewer.trim() || undefined }), "Changes saved to the connected-device register.");
      }
    } catch (e) { setError(e as Error); } finally { setBusy(false); }
  }
  async function submit() {
    if (!device && addresses.length && !preview) {          // alias changes are always shown before they are saved
      setBusy(true); setError(null);
      try { const p = await previewDeviceAliases(system, "", addresses, []); setPreview(p); if (p.blocked) setError(new DeviceEditError(p.changes.filter(c => c.status === "blocked").map(c => `${c.normalized || c.address}: ${c.reasons.join("; ")}`).join(" · "), "alias_claimed", 409)); }
      catch (e) { setError(e as Error); } finally { setBusy(false); }
      return;
    }
    await save();
  }
  async function refresh() {
    if (!device) return;
    try { setRevision(await latestRevision(system, device.id)); setError(null); } catch (e) { setError(e as Error); }
  }
  return <form className="assets-form" onSubmit={e => { e.preventDefault(); void submit(); }} aria-label={device ? `Edit ${device.name}` : "New connected device"}>
    <header><h2>{device ? `Edit ${device.name}` : "New connected device"}</h2>{device && <small>Revision {revision}</small>}</header>
    <label>Name<input value={f.name} onChange={set("name")} required /></label>
    <label>Device type<input value={f.device_type} onChange={set("device_type")} placeholder="printer, switch, UPS…" /></label>
    <label>Operational role<input value={f.role} onChange={set("role")} /></label>
    <label>Owner<input value={f.owner} onChange={set("owner")} /></label>
    <label>Site or zone<input value={f.site_zone} onChange={set("site_zone")} /></label>
    <label>Relationship to the application<input value={f.relationship} onChange={set("relationship")} /></label>
    <label>Classification<select value={f.classification} onChange={set("classification")}>{CLASSIFICATIONS.map(c => <option key={c}>{c}</option>)}</select></label>
    <label>Identification<select value={f.identification_state} onChange={set("identification_state")}>{STATES.map(c => <option key={c}>{c}</option>)}</select></label>
    <label>Cited source{needsBasis ? " (or an owner confirmation date)" : ""}<input value={f.source} onChange={set("source")} placeholder="Document, register or capture reference" required={false} aria-required={needsBasis} /></label>
    <label>Review date (owner confirmation)<input type="date" value={f.owner_confirmed_on} onChange={set("owner_confirmed_on")} /></label>
    <label>Reviewer<input value={f.reviewer} onChange={set("reviewer")} /></label>
    {!device && <label>Addresses (one per line)<textarea rows={3} value={f.addresses} onChange={set("addresses")} placeholder="10.0.0.5&#10;printer.site.local" /></label>}
    {needsBasis && <p className="assets-hint">A confirmed device needs a cited source or a dated owner confirmation. Confirming here never adds an evidence row.</p>}
    {preview && <PreviewTable preview={preview} />}
    <EditError error={error} reload={device ? () => void refresh() : undefined} />
    <div className="assets-form-actions"><button type="submit" disabled={busy || !f.name.trim()}>{!device && addresses.length && !preview ? "Review address changes" : preview ? "Confirm and save" : "Save"}</button><button type="button" className="quiet" onClick={onCancel}>Cancel</button></div>
    <Note />
  </form>;
}
