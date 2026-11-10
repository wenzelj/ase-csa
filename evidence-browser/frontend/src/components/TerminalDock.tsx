import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import "./terminal.css";
import { cancelJob, fetchJobs, fetchTerminal, resizeTerminal, sendTerminalInput } from "../api";
import type { ReviewJob } from "../types";

const ACTIVE = new Set(["queued", "running"]);

function InteractiveTerminal({ system, jobId }: { system: string; jobId: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!host.current) return;
    const element = host.current;
    const terminal = new Terminal({ cursorBlink: true, scrollback: 3000, fontSize: 13,
      fontFamily: '"IBM Plex Mono", monospace', theme: { background: "#14242d", foreground: "#e9edf0" } });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(element);
    fit.fit();
    terminal.focus();
    let capability = "";
    let offset = 0;
    let stopped = false;
    let ended = false;
    let pendingInput = Promise.resolve();
    const controller = new AbortController();
    const sendSize = () => {
      fit.fit();
      if (capability && !ended) void resizeTerminal(system, jobId, terminal.rows, terminal.cols, capability).catch(e => setError((e as Error).message));
    };
    const observer = new ResizeObserver(sendSize);
    observer.observe(element);
    const input = terminal.onData(value => {
      if (!capability || ended) return;
      const bytes = new TextEncoder().encode(value);
      for (let i = 0; i < bytes.length; i += 4096) {
        const encoded = btoa(String.fromCharCode(...bytes.subarray(i, i + 4096)));
        pendingInput = pendingInput.then(() => sendTerminalInput(system, jobId, encoded, capability))
          .catch(e => setError((e as Error).message));
      }
    });
    void (async () => {
      try {
        while (!stopped) {
          const page = await fetchTerminal(system, jobId, offset, controller.signal);
          if (page.truncated) { terminal.reset(); terminal.writeln("[Earlier terminal output is no longer available]"); }
          if (!capability) { capability = page.capability; if (!page.ended) sendSize(); }
          if (page.data) {
            const raw = atob(page.data);
            terminal.write(Uint8Array.from(raw, char => char.charCodeAt(0)));
          }
          offset = page.offset;
          if (page.ended) { ended = true; break; }
        }
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    })();
    return () => { stopped = true; controller.abort(); observer.disconnect(); input.dispose(); terminal.dispose(); };
  }, [system, jobId]);
  return <><div ref={host} className="agent-terminal-screen" aria-label="Interactive agent terminal" />{error && <p className="agent-terminal-error" role="alert">{error}</p>}</>;
}

export function TerminalDock({ system }: { system: string }) {
  const [jobs, setJobs] = useState<ReviewJob[]>([]);
  const [selected, setSelected] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const lastActive = useRef("");
  useEffect(() => {
    let mounted = true;
    async function refresh() {
      try {
        const all = await fetchJobs(system);
        const found = all.filter(job => job.terminal && ACTIVE.has(job.state)).concat(
          all.filter(job => job.terminal && !ACTIVE.has(job.state)).slice(0, 10));
        if (!mounted) return;
        setJobs(found);
        const active = found.find(job => ACTIVE.has(job.state));
        if (active && active.id !== lastActive.current) {
          lastActive.current = active.id; setSelected(active.id); setOpen(true);
        } else if (!active) {
          setSelected(current => current || found[0]?.id || "");
        }
      } catch (e) { if (mounted) setError((e as Error).message); }
    }
    setJobs([]); setSelected(""); setOpen(false); lastActive.current = "";
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [system]);
  const job = jobs.find(row => row.id === selected) || jobs[0];
  if (!job) return null;
  return <aside className={`agent-terminal-dock${open ? " open" : ""}`} aria-label="Agent terminal">
    <header><button className="agent-terminal-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
      <strong>{job.operation.replaceAll("_", " ")}</strong> · {job.state} {open ? "▾" : "▴"}
    </button><select value={job.id} aria-label="Agent job" onChange={e => { setSelected(e.target.value); setOpen(true); }}>
      {jobs.map(row => <option key={row.id} value={row.id}>{row.operation.replaceAll("_", " ")} · {row.state}</option>)}
    </select>{ACTIVE.has(job.state) && <button onClick={() => void cancelJob(system, job.id).catch(e => setError((e as Error).message))}>Stop</button>}</header>
    {open && <InteractiveTerminal key={job.id} system={system} jobId={job.id} />}
    {error && <p className="agent-terminal-error" role="alert">{error}</p>}
  </aside>;
}
