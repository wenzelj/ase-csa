import { useEffect, useState } from "react";
import { createWorkingDocumentFromTemplate, doMigration, fetchJob, fetchMigrationStatus, fetchWorkingDocumentOptions, prepareMigration, selectLegacyDocument, selectWorkingDocument, uploadWorkingDocument, type MigrationStatus, type WorkingDocumentOptions } from "../api";
import type { ReviewJob } from "../types";

function resultError(result: { errors?: { field: string; message: string }[] }) {
  return result.errors?.map(item => `${item.field}: ${item.message}`).join(" ") || "The working document could not be set.";
}

export function preferredTemplate(options: WorkingDocumentOptions): string {
  return options.templates.find(item => item.source === "shared")?.id || options.templates[0]?.id || "";
}

export function WorkingDocumentSettings({ system, onSaved }: { system: string; onSaved: () => void }) {
  const [options, setOptions] = useState<WorkingDocumentOptions | null>(null);
  const [selected, setSelected] = useState("");
  const [legacySelected, setLegacySelected] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [templateId, setTemplateId] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [systemName, setSystemName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [migration, setMigration] = useState<MigrationStatus | null>(null);
  const [migrationJob, setMigrationJob] = useState<ReviewJob | null>(null);
  const [prepareJob, setPrepareJob] = useState<ReviewJob | null>(null);

  async function reload() {
    const [current, migrationState] = await Promise.all([fetchWorkingDocumentOptions(system), fetchMigrationStatus(system)]);
    setOptions(current);
    setMigration(migrationState);
    setSelected(previous => current.candidates.some(item => item.relative_path === previous) ? previous : "");
    setLegacySelected(previous => current.candidates.some(item => item.relative_path === previous) &&
      `${current.project_root}/${previous}` !== current.configured_path ? previous : "");
    setTemplateId(previous => current.templates.some(item => item.id === previous) ? previous : preferredTemplate(current));
    setOutputPath(previous => previous || current.suggested_output);
    setSystemName(previous => previous || current.project_root.split("/").at(-1) || current.project_key);
  }
  useEffect(() => { setOptions(null); setSelected(""); setLegacySelected(""); setError(""); void reload().catch(caught => setError((caught as Error).message)); }, [system]);
  useEffect(() => { if (!prepareJob || !["queued", "running"].includes(prepareJob.state)) return; const timer = window.setInterval(async () => { const current = await fetchJob(system, prepareJob.id); setPrepareJob(current); if (!["queued", "running"].includes(current.state)) { window.clearInterval(timer); await reload(); } }, 1200); return () => window.clearInterval(timer); }, [prepareJob, system]);
  useEffect(() => { if (!migrationJob || !["queued", "running"].includes(migrationJob.state)) return; const timer = window.setInterval(async () => { const current = await fetchJob(system, migrationJob.id); setMigrationJob(current); if (!["queued", "running"].includes(current.state)) window.clearInterval(timer); }, 1500); return () => window.clearInterval(timer); }, [migrationJob, system]);

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
  async function chooseLegacy() {
    if (!legacySelected) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await selectLegacyDocument(system, legacySelected);
      if (result.status !== "READY") { setError(resultError(result)); return; }
      setNotice(`Old assessment source set to ${legacySelected}.`);
      await reload(); onSaved();
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  async function prepareOldAssessment() {
    setBusy(true); setError(""); setNotice(""); setMigrationJob(null);
    try { const result = await prepareMigration(system); setPrepareJob(result.job); setNotice("Preparing the old assessment migration…"); }
    catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  async function migrateOldAssessment() {
    if (!prepareJob || prepareJob.state !== "succeeded" || !migration?.can_migrate) return;
    setBusy(true); setError(""); setNotice("");
    try { const result = await doMigration(system, prepareJob.id); setMigrationJob(result.job); setNotice("Migrating the old assessment into the working DOCX…"); }
    catch (caught) { setError((caught as Error).message); }
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
      </div>
      <div className="new-app-template-create"><h4>Old assessment to migrate from</h4>
        <p>This source DOCX is read only during <code>csa move</code>. Choose it separately from the new working DOCX.</p>
        {options.legacy_path && <p>Selected old source: <strong>{options.legacy_path}</strong></p>}
        <div className="new-app-document-choice"><label>Old DOCX<select value={legacySelected} onChange={event => setLegacySelected(event.target.value)}>
          <option value="">Choose an old document</option>{options.candidates.filter(item =>
            `${options.project_root}/${item.relative_path}` !== options.configured_path).map(item =>
            <option key={item.relative_path} value={item.relative_path}>{item.relative_path}</option>)}
        </select></label><button type="button" disabled={!legacySelected || busy} onClick={() => void chooseLegacy()}>Use as old source</button></div>
        {options.configured_path && options.legacy_path && <p>Ready to prepare the move: <code>csa -p {options.project_key} move --prepare</code></p>}
        <div className="new-app-migration" aria-label="Old assessment migration">
          <h4>Old assessment migration</h4>
          <p>Prepare checks the old DOCX and builds the mapping. Migrate stays disabled until that check succeeds.</p>
          <div className="new-app-migration-actions">
            <button type="button" disabled={!options.legacy_path || !options.configured_path || !migration?.legacy_exists || !migration?.working_exists || busy || Boolean(prepareJob && ["queued", "running"].includes(prepareJob.state))} onClick={() => void prepareOldAssessment()}>
              {prepareJob?.state === "running" || prepareJob?.state === "queued" ? "Preparing…" : "Prepare migrate"}
            </button>
            <button type="button" disabled={!prepareJob || prepareJob.state !== "succeeded" || !migration?.can_migrate || busy || Boolean(migrationJob && ["queued", "running"].includes(migrationJob.state))} onClick={() => void migrateOldAssessment()}>
              {migrationJob?.state === "running" || migrationJob?.state === "queued" ? "Migrating…" : "Do migrate"}
            </button>
          </div>
          {prepareJob?.state === "succeeded" && migration && <p className="new-app-migration-good" role="status">Prepare succeeded: {migration.mapped} mapped blocks, {migration.unmapped} unmapped.</p>}
          {prepareJob && ["failed", "cancelled", "interrupted"].includes(prepareJob.state) && <p className="new-app-error" role="alert">Prepare migration stopped: {prepareJob.message || prepareJob.state}.</p>}
          {migrationJob && ["failed", "cancelled", "interrupted"].includes(migrationJob.state) && <p className="new-app-error" role="alert">Migration stopped: {migrationJob.message || migrationJob.state}.</p>}
          {migrationJob?.state === "succeeded" && <p className="new-app-migration-good" role="status">Migration completed. Review the working DOCX before continuing.</p>}
        </div>
      </div></> : !error && <p>Finding DOCX files…</p>}
    {error && <p className="new-app-error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
