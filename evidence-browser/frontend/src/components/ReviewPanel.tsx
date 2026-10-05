import { useCallback, useEffect, useRef, useState } from "react";
import type { ReviewJob, ReviewOutcome, ReviewSubmit, ReviewLatest } from "../types";
import { submitReview, fetchReviewJob, fetchLatestReview, cancelJob } from "../api";

const STATE_LABELS: Record<string, string> = {
  created: "Queued",
  running: "Reviewing…",
  succeeded: "Approved",
  failed: "Not approved",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

const STATE_COLORS: Record<string, string> = {
  created: "var(--muted-foreground, #9ca3af)",
  running: "var(--amber-500, #f59e0b)",
  succeeded: "var(--emerald-500, #10b981)",
  failed: "var(--rose-500, #f43f5e)",
  cancelled: "var(--muted-foreground, #9ca3af)",
  interrupted: "var(--sky-500, #0ea5e9)",
};

function formatDate(value?: string): string {
  if (!value) return "unknown";
  const d = new Date(value);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

type ReviewPanelProps = {
  system: string;
  section: string;
};

type Phase = "idle" | "submitting" | "polling" | "done" | "error";

export function ReviewPanel({ system, section }: ReviewPanelProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [confirmation, setConfirmation] = useState(false);
  const [job, setJob] = useState<ReviewJob | null>(null);
  const [outcome, setOutcome] = useState<ReviewOutcome | null>(null);
  const [latest, setLatest] = useState<ReviewLatest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitResult, setSubmitResult] = useState<ReviewSubmit | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sectionRef = useRef(section);
  sectionRef.current = section;

  // Load latest completed review on mount / section change
  useEffect(() => {
    let alive = true;
    setPhase("idle");
    setJob(null);
    setOutcome(null);
    setError(null);
    setSubmitResult(null);
    setConfirmation(false);
    fetchLatestReview(system, section)
      .then((result) => { if (alive) { setLatest(result); setOutcome({ state: result.state, ...parseOutcome(result) }); } })
      .catch(() => { if (alive) setLatest(null); });
    return () => { alive = false; };
  }, [system, section]);

  // Clean up polling on unmount
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const startPolling = useCallback((jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const result = await fetchReviewJob(system, jobId);
        setJob(result.job);
        setOutcome(result.outcome);
        if (result.job.state === "succeeded" || result.job.state === "failed" ||
            result.job.state === "cancelled" || result.job.state === "interrupted") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setPhase("done");
        }
      } catch (err) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setPhase("error");
        setError(err instanceof Error ? err.message : "Lost connection to review job");
      }
    }, 2000);
  }, [system]);

  const handleSubmit = useCallback(async () => {
    setConfirmation(false);
    setPhase("submitting");
    setError(null);
    try {
      const result = await submitReview(system, sectionRef.current);
      setJob(result.job);
      setSubmitResult(result);
      setPhase("polling");
      startPolling(result.job.id);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Failed to start review");
    }
  }, [system, startPolling]);

  const handleCancel = useCallback(async () => {
    if (!job) return;
    try {
      await cancelJob(system, job.id);
      setJob({ ...job, state: "cancelled" });
      setOutcome({ state: "cancelled", failure_reason: "Cancelled by operator" });
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      setPhase("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel");
    }
  }, [job, system]);

  const stateLabel = STATE_LABELS[outcome?.state ?? job?.state ?? "created"] ?? "Unknown";
  const stateColor = STATE_COLORS[outcome?.state ?? job?.state ?? "created"] ?? "var(--muted-foreground, #9ca3af)";
  const isActive = phase === "submitting" || phase === "polling";

  return (
    <section className="review-panel" role="region" aria-label="Review agent">
      <header className="rv-header">
        <div>
          <h2>Review Agent</h2>
          <span className="rv-meta">Section: {section}</span>
        </div>
        {latest && (
          <span className="rv-badge" style={{ color: stateColor, borderColor: stateColor }}>
            Last: {STATE_LABELS[latest.state] ?? latest.state} · {formatDate(latest.finished_at)}
          </span>
        )}
      </header>

      {phase === "idle" || (phase === "done" && outcome?.state === "failed") || (phase === "done" && outcome?.state === "succeeded" && !pollRef.current) ? (
        <div className="rv-action-area">
          <p className="rv-prompt">
            Run the framework review agent to verify applied edits, comments, and document integrity.
          </p>

          {confirmation ? (
            <div className="rv-confirm-box" role="alertdialog" aria-label="Confirm review">
              <p className="rv-confirm-text">
                Ready to run the review agent for section <strong>{section}</strong>?
                {submitResult && <> Document: <strong>{submitResult.document_name}</strong></>}
              </p>
              <div className="rv-confirm-actions">
                <button type="button" className="rv-btn rv-btn-primary" onClick={handleSubmit} disabled={isActive}>
                  {isActive ? "Starting…" : "Confirm — start review"}
                </button>
                <button type="button" className="rv-btn rv-btn-ghost" onClick={() => setConfirmation(false)} disabled={isActive}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button type="button" className="rv-btn rv-btn-primary" onClick={() => setConfirmation(true)}>
              Review this section
            </button>
          )}

          {error && <p className="rv-error" role="alert">{error}</p>}
        </div>
      ) : (
        <div className="rv-progress-area">
          <div className="rv-status-row">
            <span className="rv-dot" style={{ background: stateColor }} aria-hidden="true" />
            <span className="rv-state-label" style={{ color: stateColor }}>{stateLabel}</span>
            {job && <span className="rv-job-id">#{job.id}</span>}
          </div>

          {outcome?.failure_reason && (
            <p className="rv-failure" role="alert">{outcome.failure_reason}</p>
          )}

          {outcome?.section_breakdown && outcome.section_breakdown.length > 0 && (
            <table className="rv-table" aria-label="Section verdicts">
              <thead>
                <tr>
                  <th scope="col">Key</th>
                  <th scope="col">Heading</th>
                  <th scope="col">Verdict</th>
                  <th scope="col">Findings</th>
                </tr>
              </thead>
              <tbody>
                {outcome.section_breakdown.map((sec, i) => (
                  <tr key={i}>
                    <td>{String(sec.key ?? "—")}</td>
                    <td>{String(sec.heading ?? "—")}</td>
                    <td>
                      <span className="rv-badge" style={{
                        color: STATE_COLORS[String(sec.verdict ?? "")] ?? "var(--muted-foreground, #9ca3af)",
                        borderColor: STATE_COLORS[String(sec.verdict ?? "")] ?? "var(--muted-foreground, #9ca3af)",
                      }}>
                        {String(sec.verdict ?? "—")}
                      </span>
                    </td>
                    <td>{Array.isArray(sec.findings) ? sec.findings.length : 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {outcome?.findings && outcome.findings.length > 0 && (
            <div className="rv-blocked" role="alert">
              <strong>Findings:</strong>
              <ul>{outcome.findings.map((f, i) => <li key={i}>{String(f.detail ?? f.reason ?? f.code ?? "—")}</li>)}</ul>
            </div>
          )}

          {outcome?.breaking && outcome.breaking.area !== "none" && (
            <div className="rv-blocked" role="alert">
              <strong>Breaking change in {outcome.breaking.area}:</strong>
              <p>{outcome.breaking.detail}</p>
            </div>
          )}

          {isActive && (
            <button type="button" className="rv-btn rv-btn-ghost" onClick={handleCancel}>
              Stop review
            </button>
          )}
        </div>
      )}

      {phase === "done" && outcome && pollRef.current === null && (
        <div className="rv-footer">
          {outcome.state === "succeeded" ? (
            <p className="rv-success" role="status">
              ✓ Review approved — ready for cleanup.
            </p>
          ) : outcome.state === "failed" ? (
            <p className="rv-warn" role="status">
              ✗ Not approved — review findings in report.
            </p>
          ) : (
            <p className="rv-neutral">Review ended: {stateLabel}.</p>
          )}
        </div>
      )}
    </section>
  );
}

function parseOutcome(latest: ReviewLatest): Partial<ReviewOutcome> {
  return {
    state: latest.state,
    review_signoff: latest.state === "succeeded" ? "approved" : "not-approved",
  };
}
