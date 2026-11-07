import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import App, { FirstRunSetup, loadCreatedApplication, setupScreen } from "../App";
import { createWorkingDocumentFromTemplate, fetchWorkingDocumentOptions, selectWorkingDocument, uploadWorkingDocument, type WorkingDocumentOptions } from "../api";
import { preferredTemplate } from "../components/WorkingDocumentSettings";

it("keeps New application in navigation outside a selected system", () => {
  vi.stubGlobal("location", { search: "?view=new-application" });
  try {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("New application");
    expect(html).toContain("Application setup");
    expect(html).toContain("Drop one application folder here");
    expect(html).not.toContain("Reading what came in");
  } finally { vi.unstubAllGlobals(); }
});

it("shows registration and separate next steps before index or DOCX exists", () => {
  const html = renderToStaticMarkup(<FirstRunSetup setup={{ status: "BLOCKED", index_present: false, document_present: false,
    source_roots: ["/assessment/My App/Discovery"], reasons: ["Discovery index is absent"], project_key: "my-app" }}
    openIntake={() => {}} openAssessment={() => {}} refresh={() => {}} />);
  expect(html).toContain("my-app is registered");
  expect(html).toContain("csa -p my-app ingest");
  expect(html).toContain("Open Evidence intake");
  expect(html).toContain("working DOCX has not been selected or created");
  expect(html).toContain("Working document");
  expect(html).not.toContain("Open Assessment");
});

it("routes missing prerequisites to each area's own state", () => {
  const missing = { status: "BLOCKED", index_present: false, document_present: false,
    source_roots: [], reasons: [], project_key: "my-app" };
  expect(setupScreen("portrait", missing)).toBe("setup");
  expect(setupScreen("setup", missing)).toBe("setup");
  expect(setupScreen("intake", missing)).toBe("content");
  expect(setupScreen("assessment", missing)).toBe("document");
  expect(setupScreen("evidence", missing)).toBe("index");
  expect(setupScreen("figures", missing)).toBe("index");
  expect(setupScreen("portrait", { ...missing, index_present: true })).toBe("content");
});

it("loads DOCX choices and sends an explicit selection or upload", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ project_key: "my-app", project_root: "/assessment/My App", configured_path: "", candidates: [{ relative_path: "02 Current State Assessment/final.docx", size: 100 }], max_upload_bytes: 1000 }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ status: "READY", working_docx: "/assessment/My App/02 Current State Assessment/final.docx" }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ status: "READY", working_docx: "/assessment/My App/02 Current State Assessment/new.docx" }) });
  vi.stubGlobal("fetch", fetchMock);
  try {
    const options = await fetchWorkingDocumentOptions("my-app");
    expect(options.candidates[0].relative_path).toContain("final.docx");
    await selectWorkingDocument("my-app", options.candidates[0].relative_path);
    const selected = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(selected.relative_path).toBe("02 Current State Assessment/final.docx");
    const file = new File(["doc"], "new.docx");
    await uploadWorkingDocument("my-app", file);
    expect(fetchMock.mock.calls[2][0]).toContain("filename=new.docx");
    expect(fetchMock.mock.calls[2][1].method).toBe("PUT");
  } finally { vi.unstubAllGlobals(); }
});

it("offers the shared DOTX separately and confirms creation of a new DOCX", async () => {
  const options: WorkingDocumentOptions = { project_key: "rms", project_root: "/assessment/RMS",
    configured_path: "", candidates: [], max_upload_bytes: 1000,
    templates: [
      { id: "project:02 Current State Assessment/Current_State_Assessment_Template.dotx", label: "RMS template", source: "application" },
      { id: "shared:CSA_Template_v1.6.dotx", label: "Shared CSA template", source: "shared" },
    ], suggested_output: "02 Current State Assessment/02 New Template/Current State Assessment - RMS.docx" };
  expect(preferredTemplate(options)).toBe("shared:CSA_Template_v1.6.dotx");
  expect(options.candidates).toEqual([]);
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "READY", working_docx: "/assessment/RMS/new.docx" }) });
  vi.stubGlobal("fetch", fetchMock);
  try {
    await createWorkingDocumentFromTemplate("rms", preferredTemplate(options), options.suggested_output, "RMS");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/systems/rms/working-document/from-template");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({ template_id: "shared:CSA_Template_v1.6.dotx", output_path: options.suggested_output,
      system_name: "RMS", confirmed: true });
  } finally { vi.unstubAllGlobals(); }
});

it("refreshes registered systems and returns the new key after commit", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ systems: [
    { key: "old", label: "Old", project_key: "old", available: true },
    { key: "my-app", label: "My App", project_key: "my-app", available: true },
  ] }) });
  vi.stubGlobal("fetch", fetchMock);
  try {
    const result = await loadCreatedApplication("my-app");
    expect(result.key).toBe("my-app");
    expect(result.systems.at(-1)?.label).toBe("My App");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/systems");
  } finally { vi.unstubAllGlobals(); }
});
