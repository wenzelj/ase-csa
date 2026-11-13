import { useEffect, useState } from "react";
import { api } from "../api";

type Node = { id: string; label: string; application_key: string; application_label: string; membership: string; role: string; site: string };
type Edge = { s: string; t: string; ids: string[]; source_projects: string[] };
type Portfolio = { nodes: Node[]; edges: Edge[]; applications: { application_key: string; label: string; state: string }[]; partial: boolean };

export default function PortfolioNetwork({ openApplication }: { openApplication: (key: string) => void }) {
  const [data, setData] = useState<Portfolio | null>(null); const [error, setError] = useState("");
  useEffect(() => { api<Portfolio>("/api/global/network").then(setData).catch(e => setError(String(e.message || e))); }, []);
  if (error) return <section className="page"><div className="error" role="alert">{error}</div></section>;
  if (!data) return <section className="page"><p>Loading portfolio graph…</p></section>;
  const groups = [...new Set(data.nodes.map(n => n.application_key))];
  return <section className="page new-application-page">
    <div className="page-heading"><div><span>Portfolio view</span><h1>Applications and their connections</h1>
      <p>Read-only aggregation of application-scoped V2 stores. Evidence and host records remain in their owning application.</p></div></div>
    {data.partial && <div className="error" role="status">Some registered applications have no usable scope metadata; they were not treated as owned.</div>}
    <div className="new-app-selection"><h2>Applications</h2>{data.applications.map(app => <div key={app.application_key}>
      <button type="button" onClick={() => openApplication(app.application_key)}>{app.label || app.application_key}</button>
      <span> · {app.state}</span></div>)}</div>
    <div className="new-app-selection"><h2>Scoped hosts ({data.nodes.length})</h2>{groups.map(key => <div key={key}><h3>{data.nodes.find(n => n.application_key === key)?.application_label || key}</h3>
      <p>{data.nodes.filter(n => n.application_key === key).map(n => n.label).join(", ")}</p></div>)}</div>
    <div className="new-app-selection"><h2>Evidence-backed relationships ({data.edges.length})</h2>{data.edges.map((edge, i) => <p key={`${edge.s}-${edge.t}-${i}`}><code>{edge.s}</code> → <code>{edge.t}</code> <small>({edge.source_projects.join(", ")})</small></p>)}</div>
  </section>;
}
