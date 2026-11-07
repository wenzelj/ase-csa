import { useEffect, useState } from "react";
import type { WordReview, WordSectionReview } from "../types";
import { fetchWordReview, openWordDocument, recordWordOperatorNote, refreshWordReview } from "../api";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending — needs decision",
  decided: "Reviewed — change applied",
  has_comments: "Under review — comments attached",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "var(--amber-500, #f59e0b)",
  decided: "var(--emerald-500, #10b981)",
  has_comments: "var(--sky-500, #0ea5e9)",
};

function formatDate(value?: string): string {
  if (!value) return "unknown";
  const d = new Date(value);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

type WordReviewPanelProps = {
  system: string;
  onReady?: () => void;
};

export function WordReviewPanel({ system, onReady }: WordReviewPanelProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<WordReview | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetchWordReview(system)
      .then((result) => {
        if (!alive) return;
        setData(result);
        onReady?.();
      })
      .catch((err: unknown) => {
        if (!alive) return;
        const msg = err instanceof Error ? err.message : "Failed to load";
        setError(`The pipeline did not complete cleanly: ${msg}.`);
      })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [system, reloadKey]);

  async function openDocument() {
    try { const result = await openWordDocument(system); setMessage(result.state === "opened" ? "Opened the authoritative Word document." : result.reason || result.state); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not open the document"); }
  }

  async function refreshGate() {
    setLoading(true); setError(null);
    try { const result = await refreshWordReview(system); setData(result); setMessage(result.reason); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not refresh the approval gate"); }
    finally { setLoading(false); }
  }

  async function saveNote() {
    if (!note.trim()) return;
    try { await recordWordOperatorNote(system, note.trim()); setNote(""); setMessage("Operator note recorded against this apply job and document hash."); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not record the operator note"); }
  }

  return (
    <section className="word-review-panel" role="region" aria-label="Word approval review">
      <header className="wr-header">
        <div>
          <h2>Word Approval Review</h2>
          {data && (
            <span className="wr-meta">
              {data.document} · {formatDate(data.modified_at)}
            </span>
          )}
        </div>
        <button
          type="button"
          className="wr-refresh"
          onClick={refreshGate}
          disabled={loading}
          aria-label="Refresh review"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      {error && (
        <p className="wr-error" role="alert">{error}</p>
      )}

      {data && (
        <>
          <div className={`wr-gate wr-gate-${data.gate}`} role="status">
            <strong>{data.review_enabled ? "Ready for framework review" : "Word decision required"}</strong>
            <p>{data.reason}</p>
            <ol><li>Open the authoritative document.</li><li>Inspect every tracked change and framework comment.</li><li>Accept or reject in Word, save, close Word, then refresh.</li></ol>
            {data.word_lock && <p><b>Word lock:</b> {data.word_lock.file || data.word_lock.owner}, observed {formatDate(data.word_lock.since)}</p>}
          </div>
          <dl className="wr-summary" aria-label="Summary">
            <dt>Sections</dt><dd>{data.section_count}</dd>
            <dt>Pending</dt><dd>{data.pending_count}</dd>
            <dt>Open comments</dt><dd>{data.comment_count}</dd>
            <dt>Tracked changes</dt><dd>{data.tracked_changes.total}</dd>
          </dl>

          <dl className="wr-handoff">
            <div><dt>Authoritative document</dt><dd>{data.authoritative_path}</dd></div>
            <div><dt>Document hash</dt><dd>{data.sha256}</dd></div>
            <div><dt>Apply job</dt><dd>{data.apply_job_id || "Not recorded"}</dd></div>
            <div><dt>Backup</dt><dd>{data.backup_path || "Reported by the apply outcome"}</dd></div>
            <div><dt>Applied edit IDs</dt><dd>{data.applied_edit_ids.length ? data.applied_edit_ids.join(", ") : "No edit IDs reported"}</dd></div>
          </dl>

          <div className="wr-actions">
            <button type="button" onClick={openDocument}>Open authoritative document</button>
            <button type="button" className="quiet" onClick={refreshGate} disabled={loading}>Refresh after save and close</button>
          </div>
          <label className="wr-note">Optional operator record
            <textarea rows={2} value={note} onChange={event => setNote(event.target.value)} placeholder="Record what you inspected or decided. This is not proof of Word acceptance." />
          </label>
          <button type="button" className="quiet" disabled={!note.trim()} onClick={saveNote}>Record note</button>
          {message && <p className="wr-message" role="status">{message}</p>}

          <table className="wr-table" aria-label="Section-by-section review">
            <thead>
              <tr>
                <th scope="col">§</th>
                <th scope="col">Heading</th>
                <th scope="col">Change</th>
                <th scope="col">Comments</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.sections.map((sec) => (
                <SectionRow key={sec.number} sec={sec} />
              ))}
            </tbody>
          </table>
        </>
      )}

      {loading && !error && <p className="wr-loading">Loading review…</p>}
    </section>
  );
}

function SectionRow({ sec }: { sec: WordSectionReview }) {
  const color = STATUS_COLORS[sec.status] ?? "var(--muted-foreground, #9ca3af)";
  return (
    <tr className={`wr-row wr-row-${sec.status}`}>
      <td className="wr-num">{sec.number}</td>
      <td className="wr-heading">{sec.heading}</td>
      <td className="wr-count">{sec.change_count > 0 ? "Yes" : "—"}</td>
      <td className="wr-count">{sec.comment_count > 0 ? String(sec.comment_count) : "—"}</td>
      <td>
        <span className="wr-badge" style={{ color, borderColor: color }}>
          {STATUS_LABELS[sec.status] ?? sec.status}
        </span>
      </td>
    </tr>
  );
}
