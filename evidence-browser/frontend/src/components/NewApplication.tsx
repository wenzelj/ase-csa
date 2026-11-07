import { useEffect, useRef, useState } from "react";
import {
  cancelNewApplicationUpload, createNewApplicationUpload, fetchNewApplicationDefaults,
  finaliseNewApplicationUpload, putNewApplicationChunk,
  type NewApplicationDefaults, type NewApplicationManifestEntry,
} from "../api";
import "./new-application.css";

export type SelectedFile = { path: string; file: File };
export type FolderSelection = { folderName: string; files: SelectedFile[]; directories: string[]; notice?: string };

type DirectoryReader = { readEntries: (success: (entries: FolderEntry[]) => void, failure?: (error: DOMException) => void) => void };
type FolderEntry = { name: string; isDirectory: boolean; isFile: boolean;
  createReader?: () => DirectoryReader;
  file?: (success: (file: File) => void, failure?: (error: DOMException) => void) => void };

function parents(path: string): string[] {
  const parts = path.split("/"); const result: string[] = [];
  for (let index = 1; index < parts.length; index++) result.push(parts.slice(0, index).join("/"));
  return result;
}

function normaliseSelection(folderName: string, files: SelectedFile[], directories: string[], notice?: string): FolderSelection {
  const all = new Set(directories);
  files.forEach(item => parents(item.path).forEach(path => all.add(path)));
  return { folderName, files: files.sort((a, b) => a.path.localeCompare(b.path)),
    directories: [...all].sort(), notice };
}

export function selectionFromPicker(files: File[]): FolderSelection {
  if (!files.length) throw new Error("Choose an application folder containing Discovery and 00 Knowlege.");
  const paths = files.map(file => file.webkitRelativePath || "");
  if (paths.some(path => !path.includes("/"))) throw new Error("This browser did not provide folder paths. Drag the folder into the drop area.");
  const folderName = paths[0].split("/")[0];
  if (paths.some(path => path.split("/")[0] !== folderName)) throw new Error("Choose one application folder at a time.");
  return normaliseSelection(folderName, files.map((file, index) => ({ path: paths[index].slice(folderName.length + 1), file })), [],
    "The folder picker cannot report empty folders. Drag the folder to include them.");
}

function entriesFrom(reader: DirectoryReader): Promise<FolderEntry[]> {
  return new Promise((resolve, reject) => reader.readEntries(resolve, reject));
}

async function walk(entry: FolderEntry, relative: string, files: SelectedFile[], dirs: string[]): Promise<void> {
  if (entry.isDirectory) {
    if (relative) dirs.push(relative);
    if (!entry.createReader) throw new Error(`Cannot read folder ${entry.name}.`);
    const reader = entry.createReader();
    for (;;) {
      const batch = await entriesFrom(reader);
      if (!batch.length) break;
      for (const child of batch) await walk(child, relative ? `${relative}/${child.name}` : child.name, files, dirs);
    }
  } else if (entry.isFile) {
    if (!entry.file) throw new Error(`Cannot read file ${entry.name}.`);
    const file = await new Promise<File>((resolve, reject) => entry.file!(resolve, reject));
    files.push({ path: relative, file });
  }
}

export async function selectionFromDrop(items: DataTransferItem[]): Promise<FolderSelection> {
  const roots: FolderEntry[] = [];
  for (const item of items) {
    if (item.kind !== "file") continue;
    const entry = item.webkitGetAsEntry?.();
    if (entry) roots.push(entry as FolderEntry);
  }
  if (roots.length !== 1 || !roots[0].isDirectory) throw new Error("Drop one application folder, including its Discovery and 00 Knowlege folders.");
  const files: SelectedFile[] = []; const dirs: string[] = [];
  await walk(roots[0], "", files, dirs);
  return normaliseSelection(roots[0].name, files, dirs);
}

export function selectionManifest(selection: FolderSelection): NewApplicationManifestEntry[] {
  return [
    ...selection.directories.map(path => ({ path, kind: "dir" as const })),
    ...selection.files.map(({ path, file }) => ({ path, kind: "file" as const, size: file.size })),
  ];
}

export function selectionIssue(selection: FolderSelection, defaults?: NewApplicationDefaults): string | null {
  for (const name of [defaults?.discovery_name || "Discovery", defaults?.knowledge_name || "00 Knowlege"]) {
    if (!selection.directories.includes(name)) return `The dropped folder must contain ${name}.`;
  }
  if (selection.files.some(item => !item.path || item.path.startsWith("/") || item.path.split("/").includes(".."))) return "One or more file paths cannot be uploaded safely.";
  const total = selection.files.reduce((size, item) => size + item.file.size, 0);
  if (defaults && total > defaults.max_total_bytes) return "The folder exceeds the upload size limit.";
  if (defaults && selection.files.some(item => item.file.size > defaults.max_file_bytes)) return "A file exceeds the per-file upload size limit.";
  return null;
}

export async function transferSelection(selection: FolderSelection, defaults: NewApplicationDefaults,
  onProgress: (received: number) => void, signal?: AbortSignal): Promise<string> {
  const issue = selectionIssue(selection, defaults);
  if (issue) throw new Error(issue);
  const created = await createNewApplicationUpload(selectionManifest(selection));
  if (created.status !== "READY" || !created.session_id) throw new Error(created.errors?.[0]?.message || "Could not start the upload.");
  const sessionId = created.session_id;
  let received = 0;
  try {
    for (const item of selection.files) {
      if (item.file.size === 0) {
        const empty = await putNewApplicationChunk(sessionId, item.path, 0, new ArrayBuffer(0), signal);
        if (empty.status !== "OK") throw new Error(empty.errors?.[0]?.message || `Could not upload ${item.path}.`);
      }
      for (let offset = 0, index = 0; offset < item.file.size; offset += defaults.chunk_bytes, index++) {
        const chunk = await item.file.slice(offset, offset + defaults.chunk_bytes).arrayBuffer();
        let result;
        try { result = await putNewApplicationChunk(sessionId, item.path, index, chunk, signal); }
        catch (error) {
          if (signal?.aborted) throw error;
          result = await putNewApplicationChunk(sessionId, item.path, index, chunk, signal);
        }
        if (result.status !== "OK") throw new Error(result.errors?.[0]?.message || `Could not upload ${item.path}.`);
        received += chunk.byteLength;
        onProgress(received);
      }
    }
    const finished = await finaliseNewApplicationUpload(sessionId);
    if (finished.status !== "READY") throw new Error(finished.errors?.[0]?.message || "The uploaded folder did not pass validation.");
    return sessionId;
  } catch (error) {
    await cancelNewApplicationUpload(sessionId).catch(() => undefined);
    throw error;
  }
}

function sizeText(value: number) { return value < 1_000_000 ? `${(value / 1_000).toFixed(1)} KB` : `${(value / 1_000_000).toFixed(1)} MB`; }

export function NewApplication() {
  const [defaults, setDefaults] = useState<NewApplicationDefaults | null>(null);
  const [selection, setSelection] = useState<FolderSelection | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [state, setState] = useState<"idle" | "uploading" | "ready" | "error">("idle");
  const [error, setError] = useState("");
  const [received, setReceived] = useState(0);
  const picker = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => { void fetchNewApplicationDefaults().then(setDefaults).catch(e => setError(e.message)); }, []);
  useEffect(() => { picker.current?.setAttribute("webkitdirectory", ""); }, []);

  function choose(next: FolderSelection) {
    if (sessionId) void cancelNewApplicationUpload(sessionId).catch(() => undefined);
    setSelection(next); setSessionId(""); setState("idle"); setReceived(0); setError(selectionIssue(next, defaults || undefined) || "");
  }
  async function upload() {
    if (!selection || !defaults) return;
    setState("uploading"); setError(""); setReceived(0);
    const next = new AbortController(); controller.current = next;
    try { const id = await transferSelection(selection, defaults, setReceived, next.signal); setSessionId(id); setState("ready"); }
    catch (caught) { setState("error"); setError((caught as Error).message); }
    finally { controller.current = null; }
  }
  function cancel() { controller.current?.abort(); setState("idle"); setError("Upload cancelled. The selected folder is still available to retry."); }
  async function drop(event: React.DragEvent) {
    event.preventDefault();
    try { choose(await selectionFromDrop(Array.from(event.dataTransfer.items))); }
    catch (caught) { setError((caught as Error).message); }
  }
  const total = selection?.files.reduce((sum, item) => sum + item.file.size, 0) || 0;
  const paths = selection ? selectionManifest(selection).map(entry => entry.path) : [];
  return <section className="page new-application-page">
    <div className="page-heading"><div><span>Project setup</span><h1>New application</h1><p>Drop the application folder with its Discovery and 00 Knowlege folders inside.</p></div></div>
    <div className="new-app-drop" onDragOver={event => event.preventDefault()} onDrop={event => void drop(event)}>
      <strong>Drop one application folder here</strong><span>All nested files and folders will be kept under the application folder.</span>
      <button type="button" onClick={() => picker.current?.click()}>Choose folder</button>
      <input ref={picker} type="file" multiple className="new-app-picker" onChange={event => {
        try { choose(selectionFromPicker(Array.from(event.target.files || []))); }
        catch (caught) { setError((caught as Error).message); }
      }} />
    </div>
    {selection && <section className="new-app-selection"><h2>{selection.folderName}</h2>
      <p>Destination: {defaults?.workspace_root || "CurrentStateAssessments"}/{selection.folderName}</p>
      <p>{selection.files.length} files · {selection.directories.length} folders · {sizeText(total)}</p>
      {selection.notice && <p className="new-app-note">{selection.notice}</p>}
      <div className="new-app-tree"><strong>Folder contents</strong><ul>{paths.slice(0, 100).map(path => <li key={path}>{path}</li>)}</ul>{paths.length > 100 && <small>And {paths.length - 100} more items.</small>}</div>
      {state === "uploading" && <progress max={total || 1} value={received} aria-label="Upload progress" />}
      <div className="new-app-actions"><button type="button" disabled={!defaults || state === "uploading" || state === "ready" || Boolean(selectionIssue(selection, defaults || undefined))} onClick={() => void upload()}>{state === "error" ? "Retry upload" : "Upload folder"}</button>
        {state === "uploading" && <button type="button" onClick={cancel}>Cancel upload</button>}
        {state === "ready" && <span role="status">Folder uploaded. Review its application settings next.</span>}</div>
    </section>}
    {error && <p className="new-app-error" role="alert">{error}</p>}
    {state === "ready" && sessionId && <section className="new-app-next"><h2>Application settings</h2><p>Upload session {sessionId} is ready for configuration review.</p></section>}
  </section>;
}

export default NewApplication;
