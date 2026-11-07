import type { IntakeRun } from "./types";

export function runSummaryText(run: IntakeRun): string {
  const lines = [
    `Operation: ${run.operation}`,
    `Run id: ${run.id}`,
    `State: ${run.state}`,
    `Exit code: ${run.exit_code ?? "unknown"}`,
    `Started: ${run.started_at || "unknown"}`,
    `Finished: ${run.finished_at || "unknown"}`,
    `Reason: ${run.reason || "none"}`,
    "Problems:",
  ];
  if (run.problems.length === 0) lines.push("  none");
  for (const p of run.problems) lines.push(`  ×${p.count} ${p.kind}: ${p.signature} (first line ${p.first_line})`);
  lines.push(`Log: csa-work/ui-jobs/${run.id}/stderr.log`);
  return lines.join("\n");
}
