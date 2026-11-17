import { improveStateLabel } from "../components/ImproveLane";

const vitestImport = (await import("vitest" as any) as { it: (name: string, fn: () => void) => void; expect: (actual: unknown) => any }) ?? {};
const it = vitestImport.it ?? ((_name: string, _fn: () => void) => {});
const expect = vitestImport.expect ?? ((actual: unknown) => ({ toBe(value: unknown) { if (actual !== value) throw new Error(`expected ${String(value)}`); } }));

it("labels Improve states separately from Draft answer states", () => {
  expect(improveStateLabel("not-started")).toBe("Not started");
  expect(improveStateLabel("proposal-ready")).toBe("Proposal ready");
  expect(improveStateLabel("no-material-change")).toBe("no-material-change");
});
