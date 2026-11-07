import { useEffect, useRef } from "react";
import type { RailSteps, StepKey } from "./sectionSteps";

const MARK: Record<string, string> = { done: "✓", current: "●", blocked: "!", waiting: "○", running: "◌", failed: "✗" };

export function StepRail({ rail, onStep, onPrimary }: { rail: RailSteps; onStep: (key: StepKey) => void; onPrimary: () => void }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const node = ref.current; const panel = node?.closest<HTMLElement>(".section-inspector");
    if (!node || !panel || typeof ResizeObserver === "undefined") return;
    const sync = () => panel.style.setProperty("--inspector-rail-height", `${node.offsetHeight}px`);
    sync(); const observer = new ResizeObserver(sync); observer.observe(node);
    return () => { observer.disconnect(); panel.style.removeProperty("--inspector-rail-height"); };
  }, []);
  const { primary } = rail; const blocked = rail.steps.find(step => step.status === "blocked" || step.status === "failed");
  const disabled = primary.action === "none" || Boolean(primary.disabledReason);
  return <section ref={ref} className="step-rail" aria-label="Section steps">
    <ol>{rail.steps.map((step, index) => <li key={step.key} className={`step-${step.status}${rail.current === step.key ? " is-current" : ""}`} aria-current={rail.current === step.key ? "step" : undefined}>
      <button type="button" onClick={() => onStep(step.key)} title={`Go to ${step.label}`}><b aria-hidden="true">{MARK[step.status]}</b><span><strong>{index + 1}. {step.label}</strong><small>{step.detail}</small></span></button>
    </li>)}</ol>
    <div className="step-primary">
      {blocked && blocked.status === "blocked" && <small role="status">{blocked.detail}</small>}
      {primary.disabledReason && primary.action !== "none" && !blocked && <small role="status">{primary.disabledReason}</small>}
      <button type="button" className="step-primary-button" disabled={disabled} title={primary.disabledReason} onClick={onPrimary}>{primary.label} ▸</button>
    </div>
  </section>;
}
