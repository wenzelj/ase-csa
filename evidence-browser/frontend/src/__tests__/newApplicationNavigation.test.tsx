import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import App, { FirstRunSetup, loadCreatedApplication } from "../App";

it("keeps New application in navigation outside a selected system", () => {
  vi.stubGlobal("location", { search: "?view=new-application" });
  try {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("New application");
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
  expect(html).not.toContain("Open Assessment");
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
