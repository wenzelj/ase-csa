import { useEffect, useState } from "react";
import type { WordReview, WordSectionReview } from "../types";
import { fetchWordReview } from "../api";

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
          onClick={() => setReloadKey((k) => k + 1)}
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
          <dl className="wr-summary" aria-label="Summary">
            <dt>Sections</dt><dd>{data.section_count}</dd>
            <dt>Pending</dt><dd>{data.pending_count}</dd>
            <dt>Open comments</dt><dd>{data.comment_count}</dd>
          </dl>

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
