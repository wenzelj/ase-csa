import type { ReviewJob } from "./types";

export function stripAnsi(value: string): string {
  return value.replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, "").replace(/\u001b[@-Z\\^_]/g, "").replace(/[\u0007\u009b]/g, "");
}
export function terminalReason(job: ReviewJob): string {
  const clean = (value?: string | null) => stripAnsi(value || "").replace(/\s+\n/g, "\n").trim();
  const message = clean(job.message);
  if (message) return message;
  const streams = [job.stderr_tail, job.stdout_tail].map(clean).filter(Boolean);
  for (const stream of streams) {
    const lines = stream.split("\n").map(l => l.trimEnd());
    const meaningfulIdx = lines.map((l, i) => (l && (l.includes("csa:") || l.includes("Error:")) ? i : -1)).filter(i => i >= 0);
    if (meaningfulIdx.length) {
      const lastIdx = meaningfulIdx.at(-1)!;
      // Include the actionable line plus any following guidance lines (until blank or end)
      const parts: string[] = [];
      for (let i = lastIdx; i < lines.length; i++) {
        if (!lines[i]) break;
        parts.push(lines[i]);
      }
      return parts.join("\n");
    }
  }
  for (const stream of streams) {
    const lines = stream.split("\n").map(l => l.trimEnd()).filter(Boolean);
    if (lines.length) return lines.at(-1)!;
  }
  return "";
}
