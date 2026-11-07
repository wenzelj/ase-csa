import { useCallback, useEffect, useRef, useState } from "react";
import type { CleanupPreflight, CleanupSubmit, CleanupOutcome, CleanupLatest } from "../types";
import { fetchCleanupPreflight, submitCleanup, fetchCleanupJob, fetchLatestCleanup, cancelJob } from "../api";

type Phase = "checking" | "ready" | "confirming" | "polling" | "done" | "blocked" | "error";

const GATE_LABELS: Record<string, string> = {
  review_signoff: "Review signed off",
  hash_current: "Current document hash",
  word_locked: "No Word lock",
  framework_locked: "No framework lock",
  unresolved_revisions: "No unresolved tracked changes",
};

type CleanupPanelProps = { system: string; section: string };

export function CleanupPanel({ system, section }: CleanupPanelProps) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [preflight, setPreflight] = useState<CleanupPreflight | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [submit, setSubmit] = useState<CleanupSubmit | null>(null);
  const [outcome, setOutcome] = useState<CleanupOutcome | null>(null);
  const [latest, setLatest] = useState<CleanupLatest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sectionRef = useRef(section);
  sectionRef.current = section;

  useEffect(() => {
    let alive = true;
    setPhase("checking"); setPreflight(null); setConfirmText(""); setSubmit(null);
    setOutcome(null); setError(null); setLatest(null);
    fetchLatestCleanup(system, section)
      .then((result) => { if (alive) setLatest(result); })
      .catch(() => { if (alive) setLatest(null); });
    fetchCleanupPreflight(system, section)
      .then((result) => { if (alive) { setPreflight(result); setPhase("ready"); } })
      .catch((err) => { if (alive) { setPhase("blocked"); setError(err instanceof Error ? err.message : "Cleanup preflight failed."); } });
    return () => { alive = false; };
  }, [system, section]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const startPolling = useCallback((id: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const result = await fetchCleanupJob(system, id);
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
        setError(err instanceof Error ? err.message : "Lost connection to cleanup job");
      }
    }, 2000);
  }, [system]);

  const jobActive = submit ? phase === "confirming" || phase === "polling" : false;
  const jobId = submit?.job.id;

  const handleConfirm = useCallback(async () => {
    if (phase !== "ready" && phase !== "blocked") return;
    if (confirmText.trim().toLowerCase() !== "finalize this section") return;
    setPhase("confirming");
    setError(null);
    try {
      const result = await submitCleanup(system, sectionRef.current);
      setSubmit(result);
      setPhase("polling");
      startPolling(result.job.id);
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "Failed to start cleanup");
    }
  }, [phase, confirmText, system, startPolling]);

  const handleCancel = useCallback(async () => {
    if (!jobId) return;
    try {
      await cancelJob(system, jobId);
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      setPhase("done");
      setOutcome({ state: "cancelled", result: "STOPPED", section_state: "unknown",
        validation: {}, recovery_instructions: ["Cleanup was stopped before it completed."], failure_reason: "Cancelled by operator." });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel");
    }
  }, [jobId, system]);

  const canSubmit = phase === "ready" && confirmText.trim().toLowerCase() === "finalize this section";
  const isActive = phase === "confirming" || phase === "polling";
  const gateRows = preflight?.gates ?? [];
  const gatesPass = gateRows.every((g) => !g.required || g.satisfied);

  return (
    <section className="review-panel cleanup-panel" role="region" aria-label="Cleanup agent">
      <header className="rv-header">
        <div>
          <h2>Cleanup Agent</h2>
          <span className="rv-meta">Section: {section} · irreversible finalisation</span>
        </div>
        {latest && (
          <span className="rv-badge">
            Last: {latest.state} · {latest.finished_at ? new Date(latest.finished_at).toLocaleString() : "—"}
          </span>
        )}
      </header>

      {phase === "checking" && (
        <div className="rv-action-area">
          <p className="rv-prompt">Checking cleanup gates…</p>
        </div>
      )}

      {phase === "blocked" && (
        <div className="rv-action-area">
          <p className="rv-prompt">Cleanup is blocked for this section.</p>
          {error && <p className="rv-error" role="alert">{error}</p>}
        </div>
      )}

      {phase === "ready" && (
        <div className="rv-action-area">
          <p className="rv-prompt">
            Cleanup accepts the review's signed-off changes and removes framework scaffolding,
            leaving your content and Word fields untouched. This step is irreversible.
          </p>
          <ul className="cleanup-gates" aria-label="Cleanup gates">
            {gateRows.map((g) => (
              <li key={g.key} className={g.satisfied ? "gate-pass" : "gate-fail"}>
                <span className={`gate-marker ${g.satisfied ? "ok" : "bad"}`}></span>
                <strong>{GATE_LABELS[g.key] ?? g.key}</strong>
                {g.detail && <small> · {g.detail}</small>}
              </li>
            ))}
          </ul>
          <label className="cleanup-confirm-label" htmlFor="cleanup-confirm-input">
            To confirm, type <strong>finalize this section</strong>:
          </label>
          <input
            id="cleanup-confirm-input"
            className="cleanup-confirm-input"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="finalize this section"
            autoComplete="off"
            spellCheck={false}
          />
          <div className="rv-confirm-actions">
            <button type="button" className="rv-btn rv-btn-primary" disabled={!canSubmit} onClick={handleConfirm}>
              {isActive ? "Starting…" : "Cleanup this section"}
            </button>
            <button type="button" className="rv-btn rv-btn-ghost" disabled={isActive} onClick={() => setConfirmText("")}>
              Reset
            </button>
          </div>
          {error && <p className="rv-error" role="alert">{error}</p>}
          <p className="rv-prompt">
            A backup will be created at <code>{preflight?.backup_destination ?? "—"}</code>.
          </p>
        </div>
      )}

      {(phase === "confirming" || phase === "polling" || (phase === "done" && outcome)) && (
        <div className="rv-progress-area">
          <div className="rv-status-row">
            <span className={`rv-dot cleanup-dot-${outcome?.result?.toLowerCase() ?? "running"}`} aria-hidden="true" />
            <span className="rv-state-label">
              {outcome ? outcome.result : "Starting cleanup…"}
            </span>
            {jobId && <span className="rv-job-id">#{jobId.slice(0, 8)}</span>}
          </div>

          {outcome?.failure_reason && (
            <div className="rv-blocked" role="alert">
              <strong>Stopped</strong>
              <p>{outcome.failure_reason}</p>
            </div>
          )}

          {outcome?.validation && Object.keys(outcome.validation).length > 0 && (
            <table className="rv-table" aria-label="Validation results">
              <thead><tr><th scope="col">Check</th><th scope="col">Result</th></tr></thead>
              <tbody>
                {Object.entries(outcome.validation).map(([k, v]) => (
                  <tr key={k}>
                    <td>{String(k)}</td>
                    <td><span className="cleanup-pill">{String(v)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {outcome && (outcome.removed_artifacts?.length || outcome.retained_artifacts?.length) ? (
            <div className="cleanup-artifacts">
              <dl>
                {outcome.removed_artifacts && outcome.removed_artifacts.length > 0 && (
                  <>
                    <dt>Removed</dt>
                    <dd>
                      <ul>{outcome.removed_artifacts.map((a, i) => <li key={i}>{a}</li>)}</ul>
                    </dd>
                  </>
                )}
                {outcome.retained_artifacts && outcome.retained_artifacts.length > 0 && (
                  <>
                    <dt>Retained</dt>
                    <dd>
                      <ul>{outcome.retained_artifacts.map((a, i) => <li key={i}>{a}</li>)}</ul>
                    </dd>
                  </>
                )}
              </dl>
            </div>
          ) : null}

          {outcome?.backup && (
            <p className="cleanup-backup">Backup: <code>{outcome.backup}</code></p>
          )}

          {(phase === "confirming" || phase === "polling") && (
            <button type="button" className="rv-btn rv-btn-ghost" onClick={handleCancel}>
              Stop cleanup
            </button>
          )}

          {phase === "done" && outcome && (
            <div className="rv-footer">
              {outcome.result === "FINALISED" ? (
                <p className="rv-success" role="status">
                  ✓ Section finalized — tracked changes accepted, scaffolding removed.
                </p>
              ) : (
                <p className="rv-warn" role="status">
                  ✗ Cleanup stopped.
                </p>
              )}
              {outcome.recovery_instructions?.length > 0 && (
                <ul className="cleanup-recovery">
                  {outcome.recovery_instructions.map((step, i) => <li key={i}>{step}</li>)}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {phase === "error" && (
        <div className="rv-action-area">
          <p className="rv-error" role="alert">{error ?? "Cleanup failed."}</p>
          <button type="button" className="rv-btn rv-btn-ghost" onClick={() => { setPhase("ready"); setError(null); setPreflight(null); void fetchCleanupPreflight(system, section).then(p => { setPreflight(p); setPhase("ready"); }); }}>
            Retry preflight
          </button>
        </div>
      )}
    </section>
  );
}
