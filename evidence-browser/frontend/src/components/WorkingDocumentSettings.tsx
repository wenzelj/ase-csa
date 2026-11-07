import { useEffect, useState } from "react";
import { fetchWorkingDocumentOptions, selectWorkingDocument, uploadWorkingDocument, type WorkingDocumentOptions } from "../api";

function resultError(result: { errors?: { field: string; message: string }[] }) {
  return result.errors?.map(item => `${item.field}: ${item.message}`).join(" ") || "The working document could not be set.";
}

export function WorkingDocumentSettings({ system, onSaved }: { system: string; onSaved: () => void }) {
  const [options, setOptions] = useState<WorkingDocumentOptions | null>(null);
  const [selected, setSelected] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function reload() {
    const current = await fetchWorkingDocumentOptions(system);
    setOptions(current);
    setSelected(previous => current.candidates.some(item => item.relative_path === previous) ? previous : "");
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

  return <section className="new-app-document-settings"><h3>Working document</h3>
    {options?.configured_path ? <p>Selected: <strong>{options.configured_path}</strong></p> : <p>No working DOCX is selected for this application.</p>}
    <p>Choose an existing CSA DOCX from the application folder, or upload one. Selecting a document does not edit it.</p>
    {options ? <><div className="new-app-document-choice"><label>Existing DOCX<select value={selected} onChange={event => setSelected(event.target.value)}>
      <option value="">Choose a file</option>{options.candidates.map(item => <option key={item.relative_path} value={item.relative_path}>{item.relative_path}</option>)}
    </select></label><button type="button" disabled={!selected || busy} onClick={() => void choose()}>Use this document</button></div>
      {!options.candidates.length && <p>No CSA DOCX was found outside the Discovery and knowledge folders.</p>}
      <div className="new-app-document-choice"><label>Upload a working DOCX<input type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        onChange={event => setFile(event.target.files?.[0] || null)} /></label>
        <button type="button" disabled={!file || busy} onClick={() => void upload()}>Upload and use document</button></div></> : !error && <p>Finding DOCX files…</p>}
    {error && <p className="new-app-error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
