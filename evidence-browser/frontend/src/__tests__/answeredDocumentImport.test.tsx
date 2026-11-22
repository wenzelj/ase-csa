import { buildApplicationConfig, initialApplicationForm } from "../components/NewApplication";
import { improveStateLabel } from "../components/ImproveLane";
import type { NewApplicationDefaults } from "../api";
import { expect, it } from "vitest";

const defaults: NewApplicationDefaults = { workspace_root: "/assessment", discovery_name: "Discovery", knowledge_name: "00 Knowlege",
  max_file_bytes: 100, max_total_bytes: 200, chunk_bytes: 4, defaults: { lane: "revise", stage: "draft", spec_mode: "off" }, templates: [] };

it("opts into answered-document reconstruction only when a working DOCX is configured", () => {
  const form = { ...initialApplicationForm("Answered App", defaults), working_docx: "assessment.docx", import_existing_answers: true };
  const config = buildApplicationConfig("Answered App", form, defaults.workspace_root);
  expect(config.working_docx).toBe("/assessment/Answered App/assessment.docx");
  expect(config.import_existing_answers).toBe(true);
});

it("keeps imported sections on the Improve lifecycle labels", () => {
  expect(improveStateLabel("context-ready")).toBe("Context ready");
  expect(improveStateLabel("ready-for-improve")).toBe("Ready for Improve");
});
