export function human(value = "") { return value.replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase()); }
export function Status({ value }: { value?: string }) { const name = (value || "unknown").toLowerCase().replaceAll("_", " "); return <span className={`status status-${name.replaceAll(" ", "-")}`}>{name}</span>; }
export function Empty({ title, text }: { title: string; text: string }) { return <div className="empty-state"><strong>{title}</strong><p>{text}</p></div>; }
export function Loading() { return <div className="loading"><span /><strong>Building the application portrait from evidence…</strong></div>; }
