export const AGENT_CLIS = [
  { id: "evo", label: "Evo (local)" },
  { id: "qwen8b", label: "Qwen3 8B (local)" },
  { id: "codex", label: "Codex" },
  { id: "claude", label: "Claude" },
] as const;

export const DEFAULT_AGENT_CLI = "evo";
const STORAGE_KEY = "csa-agent-cli-v2";

export function rememberedAgentCli(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return AGENT_CLIS.some(cli => cli.id === saved) ? saved! : DEFAULT_AGENT_CLI;
  } catch {
    return DEFAULT_AGENT_CLI;
  }
}

export function rememberAgentCli(value: string): void {
  try { localStorage.setItem(STORAGE_KEY, value); }
  catch { /* per-viewer convenience only */ }
}
