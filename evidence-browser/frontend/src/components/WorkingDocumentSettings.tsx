import { useEffect, useState } from "react";
import { createWorkingDocumentFromTemplate, fetchWorkingDocumentOptions, selectWorkingDocument, uploadWorkingDocument, type WorkingDocumentOptions } from "../api";

function resultError(result: { errors?: { field: string; message: string }[] }) {
  return result.errors?.map(item => `${item.field}: ${item.message}`).join(" ") || "The working document could not be set.";
}

export function preferredTemplate(options: WorkingDocumentOptions): string {
  return options.templates.find(item => item.source === "shared")?.id || options.templates[0]?.id || "";
}

export function WorkingDocumentSettings({ system, onSaved }: { system: string; onSaved: () => void }) {
  const [options, setOptions] = useState<WorkingDocumentOptions | null>(null);
  const [selected, setSelected] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [templateId, setTemplateId] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [systemName, setSystemName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function reload() {
    const current = await fetchWorkingDocumentOptions(system);
    setOptions(current);
    setSelected(previous => current.candidates.some(item => item.relative_path === previous) ? previous : "");
    setTemplateId(previous => current.templates.some(item => item.id === previous) ? previous : preferredTemplate(current));
    setOutputPath(previous => previous || current.suggested_output);
    setSystemName(previous => previous || current.project_root.split("/").at(-1) || current.project_key);
  }
  useEffect(() => { setOptions(null); setSelected(""); setError(""); void reload().catch(caught => setError((caught as Error).message)); }, [system]);

  async function choose() {
    if (!selected) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await selectWorkingDocument(system, selected);
      if (result.status !== "READY") { setError(resultError(result)); return; }
      setNotice(`Working document set to ${selected}.`);
      await reload(); onSaved();
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  async function upload() {
    if (!file || !options) return;
    if (file.size > options.max_upload_bytes) { setError("The DOCX exceeds the 50 MiB upload limit."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await uploadWorkingDocument(system, file);
      if (result.status !== "READY") { setError(resultError(result)); return; }
      setNotice(`Working document uploaded and set to ${file.name}.`);
      setFile(null); await reload(); onSaved();
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  async function createFromTemplate() {
    if (!templateId || !outputPath.trim() || !systemName.trim()) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await createWorkingDocumentFromTemplate(system, templateId, outputPath.trim(), systemName.trim());
      if (result.status !== "READY") { setError(resultError(result)); return; }
      setNotice(`Created and selected ${outputPath.trim()} from the DOTX template. The template was not changed.`);
      await reload(); onSaved();
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }

  return <section className="new-app-document-settings"><h3>Working document</h3>
    {options?.configured_path ? <p>Selected: <strong>{options.configured_path}</strong></p> : <p>No working DOCX is selected for this application.</p>}
    <p>Choose an existing CSA DOCX from the application folder, or upload one. Selecting a document does not edit it.</p>
    {options ? <><div className="new-app-document-choice"><label>Existing DOCX<select value={selected} onChange={event => setSelected(event.target.value)}>
      <option value="">Choose a file</option>{options.candidates.map(item => <option key={item.relative_path} value={item.relative_path}>{item.relative_path}</option>)}
    </select></label><button type="button" disabled={!selected || busy} onClick={() => void choose()}>Use this document</button></div>
      {!options.candidates.length && <p>No CSA DOCX was found outside the Discovery and knowledge folders.</p>}
      <div className="new-app-document-choice"><label>Upload a working DOCX<input type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        onChange={event => setFile(event.target.files?.[0] || null)} /></label>
        <button type="button" disabled={!file || busy} onClick={() => void upload()}>Upload and use document</button></div>
      <div className="new-app-template-create"><h4>Create a DOCX from a DOTX template</h4>
        <p>A template is a starting point. The new DOCX becomes the working document; the DOTX stays unchanged.</p>
        <label>Template (.dotx)<select value={templateId} onChange={event => setTemplateId(event.target.value)}>
          <option value="">Choose a template</option>{options.templates.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select></label>
        <label>System name on the cover<input value={systemName} onChange={event => setSystemName(event.target.value)} /></label>
        <label>New working DOCX path inside the application<input value={outputPath} onChange={event => setOutputPath(event.target.value)} /></label>
        <button type="button" disabled={!templateId || !systemName.trim() || !outputPath.trim() || busy}
          onClick={() => void createFromTemplate()}>Create and use DOCX</button>
        {!options.templates.length && <p>No DOTX template was found in the application or shared CSA Template folder.</p>}
      </div></> : !error && <p>Finding DOCX files…</p>}
    {error && <p className="new-app-error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
