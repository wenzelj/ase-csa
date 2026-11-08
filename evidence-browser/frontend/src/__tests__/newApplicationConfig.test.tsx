import { renderToStaticMarkup } from "react-dom/server";
import { buildApplicationConfig, initialApplicationForm, NewApplication } from "../components/NewApplication";
import { previewNewApplication, commitNewApplication, type NewApplicationDefaults } from "../api";
import { it, expect, vi } from "vitest";

const defaults: NewApplicationDefaults = { workspace_root: "/assessment", discovery_name: "Discovery", knowledge_name: "00 Knowlege",
  max_file_bytes: 100, max_total_bytes: 200, chunk_bytes: 4, defaults: { lane: "revise", stage: "draft", spec_mode: "off" }, templates: ["/template.dotx"] };

it("starts with the two populated source folder paths and template defaults", () => {
  const form = initialApplicationForm("My App", defaults);
  expect(form.discovery).toBe("Discovery");
  expect(form.knowledge).toBe("00 Knowlege");
  expect(form.lane).toBe("revise");
  expect(form.working_preferences.evidence_only_factual_claims).toBe(true);
  const config = buildApplicationConfig("My App", form, defaults.workspace_root);
  expect(config.discovery).toBe("/assessment/My App/Discovery");
  expect(config.knowledge).toBe("/assessment/My App/00 Knowlege");
  expect(config.destination).toBe("My App");
});

it("includes build settings and selected project context", () => {
  const form = { ...initialApplicationForm("My App", defaults), lane: "build", template_docx: "/template.dotx",
    build_output_docx: "/assessment/My App/output.docx", scope_in: "Site A\nSite B", application_skills: "reveloc-csa-skill" };
  const config = buildApplicationConfig("My App", form, defaults.workspace_root);
  expect(config.lane).toBe("build");
  expect(config.template_docx).toBe("/template.dotx");
  expect((config.context as any).scope_in).toEqual(["Site A", "Site B"]);
  expect((config.context as any).application_skills).toEqual(["reveloc-csa-skill"]);
});

it("sends preview validation before an explicitly confirmed commit", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ status: "BLOCKED", errors: [{ field: "key", code: "DUPLICATE_KEY", message: "Already registered" }] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ status: "READY", project_key: "my-app" }) });
  vi.stubGlobal("fetch", fetchMock);
  try {
    const form = initialApplicationForm("My App", defaults);
    const config = buildApplicationConfig("My App", form, defaults.workspace_root);
    expect((await previewNewApplication(config)).errors[0].code).toBe("DUPLICATE_KEY");
    await commitNewApplication("session-1", config);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/new-application/preview");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).confirmed).toBe(true);
  } finally { vi.unstubAllGlobals(); }
});

it("shows the folder drop before configuration", () => {
  const html = renderToStaticMarkup(<NewApplication />);
  expect(html).toContain("Drop one application folder here");
  expect(html).not.toContain("Create application");
});
