import { useEffect, useRef, useState } from "react";
import {
  cancelNewApplicationUpload, createNewApplicationUpload, fetchNewApplicationDefaults,
  finaliseNewApplicationUpload, putNewApplicationChunk, previewNewApplication, commitNewApplication,
  type NewApplicationDefaults, type NewApplicationManifestEntry, type NewApplicationPreview,
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

const preferenceLabels: Record<string, string> = {
  evidence_only_factual_claims: "Use evidence for factual claims",
  expand_abbreviations_on_first_use: "Expand abbreviations on first use",
  explain_ot_concepts_separately: "Explain OT concepts separately",
  preserve_existing_document_structure: "Preserve document structure",
  do_not_design_future_state_unless_requested: "Avoid future-state design unless requested",
};
type FormState = {
  key: string; label: string; application: string; assessment_name: string; assessment_type: string;
  program: string; environment: string; organisation: string; as_of_date: string;
  scope_in: string; scope_out: string; authoritative_sources: string; terminology: string;
  known_constraints: string; stakeholders: string; required_deliverables: string; application_skills: string;
  discovery: string; knowledge: string; knowledge_sources: string; lane: string; stage: string;
  template_docx: string; build_output_docx: string; legacy_docx: string; working_docx: string;
  index_extra_sources: string; estate: string; sites: string; spec_mode: string;
  working_preferences: Record<string, boolean>;
};
const lines = (value: string) => value.split(/\r?\n/).map(item => item.trim()).filter(Boolean);
export function initialApplicationForm(folderName: string, defaults?: NewApplicationDefaults): FormState {
  const key = folderName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "application";
  return { key: /^[a-z]/.test(key) ? key : `app-${key}`, label: folderName, application: folderName,
    assessment_name: `${folderName} Current State Assessment`, assessment_type: "Current State Assessment",
    program: "", environment: "", organisation: "", as_of_date: "", scope_in: "", scope_out: "",
    authoritative_sources: "", terminology: "{}", known_constraints: "", stakeholders: "",
    required_deliverables: "detailed_current_state_assessment\nconsumable_summary", application_skills: "",
    discovery: "Discovery", knowledge: "00 Knowlege", knowledge_sources: "", lane: defaults?.defaults.lane || "revise",
    stage: defaults?.defaults.stage || "draft", template_docx: "", build_output_docx: "", legacy_docx: "",
    working_docx: "", index_extra_sources: "", estate: "", sites: "", spec_mode: defaults?.defaults.spec_mode || "off",
    working_preferences: Object.fromEntries(Object.keys(preferenceLabels).map(key => [key, true])),
  };
}
export function buildApplicationConfig(folderName: string, form: FormState, workspaceRoot: string): Record<string, unknown> {
  const root = `${workspaceRoot}/${folderName}`;
  const optional = (value: string) => value.trim() || undefined;
  const withinApplication = (value: string) => value.trim() ? (value.trim().startsWith("/") ? value.trim() : `${root}/${value.trim()}`) : undefined;
  const terminology = JSON.parse(form.terminology || "{}");
  const knowledgeSources = form.knowledge_sources.trim() ? JSON.parse(form.knowledge_sources) : undefined;
  return { key: form.key.trim(), label: form.label.trim(), application: form.application.trim(), destination: folderName,
    discovery: `${root}/${form.discovery.trim()}`, knowledge: `${root}/${form.knowledge.trim()}`,
    lane: form.lane, stage: form.stage, spec_mode: form.spec_mode, estate: optional(form.estate), sites: optional(form.sites),
    template_docx: optional(form.template_docx), build_output_docx: withinApplication(form.build_output_docx),
    legacy_docx: optional(form.legacy_docx), working_docx: withinApplication(form.working_docx),
    index_extra_sources: optional(form.index_extra_sources), knowledge_sources: knowledgeSources,
    working_preferences: form.working_preferences,
    context: { assessment_name: form.assessment_name.trim(), assessment_type: form.assessment_type.trim(),
      program: form.program.trim(), environment: form.environment.trim(), organisation: form.organisation.trim(),
      as_of_date: form.as_of_date.trim(), scope_in: lines(form.scope_in), scope_out: lines(form.scope_out),
      authoritative_sources: lines(form.authoritative_sources), terminology, known_constraints: lines(form.known_constraints),
      stakeholders: lines(form.stakeholders), required_deliverables: lines(form.required_deliverables),
      application_skills: lines(form.application_skills) },
  };
}

export function NewApplication({ onCreated }: { onCreated?: (key: string) => void }) {
  const [defaults, setDefaults] = useState<NewApplicationDefaults | null>(null);
  const [selection, setSelection] = useState<FolderSelection | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [state, setState] = useState<"idle" | "uploading" | "ready" | "error">("idle");
  const [error, setError] = useState("");
  const [received, setReceived] = useState(0);
  const [form, setForm] = useState<FormState | null>(null);
  const [preview, setPreview] = useState<NewApplicationPreview | null>(null);
  const [reviewedConfig, setReviewedConfig] = useState<Record<string, unknown> | null>(null);
  const [createdKey, setCreatedKey] = useState("");
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => { void fetchNewApplicationDefaults().then(setDefaults).catch(e => setError(e.message)); }, []);
  useEffect(() => { picker.current?.setAttribute("webkitdirectory", ""); }, []);

  function choose(next: FolderSelection) {
    if (sessionId) void cancelNewApplicationUpload(sessionId).catch(() => undefined);
    setSelection(next); setSessionId(""); setState("idle"); setReceived(0); setError(selectionIssue(next, defaults || undefined) || "");
    setForm(initialApplicationForm(next.folderName, defaults || undefined)); setPreview(null); setReviewedConfig(null); setCreatedKey("");
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
  function change(field: keyof FormState, value: string) {
    setForm(previous => previous ? { ...previous, [field]: value } : previous);
    setPreview(null); setReviewedConfig(null);
  }
  function field(name: keyof FormState, label: string, hint?: string) {
    return <label className="new-app-field" key={name}><span>{label}</span>
      <input value={String(form?.[name] || "")} onChange={event => change(name, event.target.value)} />
      {hint && <small>{hint}</small>}</label>;
  }
  function multi(name: keyof FormState, label: string, hint?: string) {
    return <label className="new-app-field" key={name}><span>{label}</span>
      <textarea rows={3} value={String(form?.[name] || "")} onChange={event => change(name, event.target.value)} />
      {hint && <small>{hint}</small>}</label>;
  }
  function option(name: keyof FormState, label: string, options: string[]) {
    return <label className="new-app-field" key={name}><span>{label}</span><select value={String(form?.[name] || options[0])}
      onChange={event => change(name, event.target.value)}>{options.map(value => <option key={value} value={value}>{value}</option>)}</select></label>;
  }
  async function review() {
    if (!form || !selection || !defaults || !sessionId) return;
    setBusy(true); setError(""); setPreview(null); setReviewedConfig(null);
    try {
      const config = buildApplicationConfig(selection.folderName, form, defaults.workspace_root);
      const result = await previewNewApplication(config);
      setPreview(result);
      if (result.status === "READY") setReviewedConfig(config);
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  async function create() {
    if (!reviewedConfig || !sessionId) return;
    setBusy(true); setError("");
    try {
      const result = await commitNewApplication(sessionId, reviewedConfig);
      if (result.status !== "READY" || !result.project_key) {
        setPreview(null); setReviewedConfig(null);
        setError(result.errors?.map(item => `${item.field}: ${item.message}`).join(" ") || "Application registration failed.");
        return;
      }
      setCreatedKey(result.project_key); onCreated?.(result.project_key);
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
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
    {state === "ready" && sessionId && form && selection && defaults && !createdKey && <section className="new-app-next">
      <h2>Application settings</h2>
      <p>Review the uploaded sources and configure the framework before creating the application.</p>
      <div className="new-app-form-section"><h3>Identity and scope</h3><div className="new-app-grid">
        {field("key", "Project key", "Lowercase letters, digits and hyphens.")}{field("label", "Project label")}
        {field("application", "Application name")}{field("assessment_name", "Assessment name")}
        {field("assessment_type", "Assessment type")}{field("program", "Program")}
        {field("environment", "Environment")}{field("organisation", "Organisation")}
        {field("as_of_date", "As-of date")}
        {multi("scope_in", "In scope", "One item per line.")}{multi("scope_out", "Out of scope", "One item per line.")}
        {multi("stakeholders", "Stakeholders", "One item per line.")}{multi("known_constraints", "Known constraints", "One item per line.")}
        {multi("required_deliverables", "Required deliverables", "One item per line.")}
      </div></div>
      <div className="new-app-form-section"><h3>Uploaded source folders</h3><p>Both folders come from the selected application folder, with their existing contents.</p>
        <div className="new-app-grid">{field("discovery", "Discovery folder", "Relative to the application folder.")}
        {field("knowledge", "Knowledge folder", "Relative to the application folder.")}</div>
        <p>Discovery: {selection.files.filter(item => item.path.startsWith(`${form.discovery}/`)).length} files. Knowledge: {selection.files.filter(item => item.path.startsWith(`${form.knowledge}/`)).length} files.</p>
        <div className="new-app-grid">{multi("authoritative_sources", "Authoritative sources", "One source per line.")}
        {field("index_extra_sources", "Additional source path", "Existing path to index, when needed.")}
        {multi("knowledge_sources", "Knowledge sources.json metadata", "Optional JSON object with documents and system_terms. Leave blank to preserve an uploaded sources.json.")}
        {multi("terminology", "Terminology", "JSON object of terms and meanings.")}</div>
      </div>
      <div className="new-app-form-section"><h3>Assessment and document settings</h3><div className="new-app-grid">
        {option("lane", "Assessment lane", ["revise", "build"])}{option("stage", "Stage", ["draft", "v1"])}
        {form.lane === "build" && <>{option("template_docx", "Template DOCX", ["", ...defaults.templates])}{field("build_output_docx", "Build output DOCX", "Path inside the new application folder.")}</>}
        {form.lane === "revise" && <>{field("legacy_docx", "Legacy DOCX", "Existing document path, if applicable.")}{field("working_docx", "Working DOCX", "Path inside the new application folder.")}</>}
        {field("application_skills", "Application skills", "One skill name per line; it must already exist in .agents/skills.")}
        {field("estate", "Estate")}{field("sites", "Sites", "PREFIX=Name, comma separated.")}
        {option("spec_mode", "Spec mode", ["off", "shadow", "on"])}
      </div></div>
      <div className="new-app-form-section"><h3>Working preferences</h3><p>These inherit the project template defaults. Unselected preferences are written as false.</p>
        {Object.entries(preferenceLabels).map(([key, label]) => <label key={key} className="new-app-check"><input type="checkbox"
          checked={form.working_preferences[key]} onChange={event => { setForm({ ...form, working_preferences: { ...form.working_preferences, [key]: event.target.checked } }); setPreview(null); setReviewedConfig(null); }} />{label}</label>)}
      </div>
      <div className="new-app-form-section"><h3>Review registration</h3><p>The global CSA framework and agent settings will be inherited.</p>
        <button type="button" disabled={busy} onClick={() => void review()}>Validate and preview</button>
        {preview?.status === "BLOCKED" && <ul className="new-app-validation" role="alert">{preview.errors.map((item, index) => <li key={index}><strong>{item.field}:</strong> {item.message}</li>)}</ul>}
        {preview?.status === "READY" && <div className="new-app-preview"><p>Ready to create. These paths and files will be registered:</p>
          <dl>{Object.entries(preview.values.paths).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
            <div><dt>Registry</dt><dd>{String(preview.values.registry.project_context)}</dd></div>
            <div><dt>Knowledge metadata</dt><dd>{String(preview.values.paths.knowledge)}/sources.json</dd></div></dl>
          <button type="button" disabled={busy || !reviewedConfig} onClick={() => void create()}>Create application</button></div>}
      </div>
    </section>}
    {createdKey && <section className="new-app-next" role="status"><h2>Application created</h2><p>{createdKey} is registered and ready for discovery indexing and evidence intake. No index or assessment document has been created yet.</p></section>}
  </section>;
}

export default NewApplication;
