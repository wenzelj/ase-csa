import { renderToStaticMarkup } from "react-dom/server";
import { NewApplication, selectionFromDrop, selectionFromPicker, selectionIssue, selectionManifest } from "../components/NewApplication";
import type { NewApplicationDefaults } from "../api";

const vt = await import("vitest" as any) as { it: (name: string, test: () => void | Promise<void>) => void; expect: (value: unknown) => any };
const { it, expect } = vt;
const defaults: NewApplicationDefaults = { workspace_root: "/assessment", discovery_name: "Discovery", knowledge_name: "00 Knowlege",
  max_file_bytes: 100, max_total_bytes: 200, chunk_bytes: 4, defaults: { lane: "revise", stage: "draft", spec_mode: "off" }, templates: [] };

function fakeFile(path: string, size = 4): File {
  return { webkitRelativePath: path, size, slice: () => new Blob(["host"]) } as unknown as File;
}

it("keeps both uploaded source trees in the folder manifest", () => {
  const selection = selectionFromPicker([
    fakeFile("My App/Discovery/hosts/one.txt"), fakeFile("My App/00 Knowlege/vendor/guide.md"),
  ]);
  expect(selection.folderName).toBe("My App");
  expect(selectionIssue(selection, defaults)).toBe(null);
  expect(selectionManifest(selection).map(item => item.path)).toEqual([
    "00 Knowlege", "00 Knowlege/vendor", "Discovery", "Discovery/hosts",
    "00 Knowlege/vendor/guide.md", "Discovery/hosts/one.txt",
  ]);
});

it("reports a missing knowledge folder and a browser that loses paths", () => {
  const selection = selectionFromPicker([fakeFile("My App/Discovery/host.txt")]);
  expect(selectionIssue(selection, defaults)).toBe("The dropped folder must contain 00 Knowlege.");
  expect(() => selectionFromPicker([fakeFile("")])).toThrow();
});

it("reads a dropped folder including an empty directory", async () => {
  const file = fakeFile("", 4);
  const item = (name: string) => ({ name, isFile: true, isDirectory: false, file: (done: (file: File) => void) => done(file) });
  const directory = (name: string, children: any[]) => ({ name, isFile: false, isDirectory: true,
    createReader: () => { let sent = false; return { readEntries: (done: (entries: any[]) => void) => {
      done(sent ? [] : children); sent = true;
    } }; } });
  const root = directory("My App", [directory("Discovery", [item("host.txt")]), directory("00 Knowlege", [directory("empty", [])])]);
  const selection = await selectionFromDrop([{ kind: "file", webkitGetAsEntry: () => root } as unknown as DataTransferItem]);
  expect(selection.directories).toContain("00 Knowlege/empty");
  expect(selectionManifest(selection).some(entry => entry.path === "Discovery/host.txt")).toBe(true);
});

it("renders the drop area before a folder is selected", () => {
  const html = renderToStaticMarkup(<NewApplication />);
  expect(html).toContain("Drop one application folder here");
  expect(html).toContain("Choose folder");
});
