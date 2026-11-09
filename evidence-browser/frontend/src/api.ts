import type { AliasPreview, DeviceEditResult, DevicePayload, PromptList, PromptPreview, JobLogPage, IntakeSnapshot, IntakeErrors, DraftSnapshot, WordReview, ReviewSubmit, ReviewJob, ReviewJobResponse, ReviewLatest, AuthorSetup, AuthorSubmit, AuthorJobResponse, AuthorOptions, CleanupSubmit, CleanupJobResponse, CleanupLatest, CleanupPreflight, BuildSetup, BuildOutcome, AuditSnapshot } from "./types";

export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || `Request failed (${response.status})`);
  }
  return data as T;
}

export type NewApplicationManifestEntry = { path: string; kind: "file" | "dir"; size?: number };
export type NewApplicationResult = { status: "READY" | "OK" | "BLOCKED" | "ERROR"; session_id?: string; offset?: number; already_received?: boolean; errors?: { field: string; code: string; message: string }[] };
export type NewApplicationDefaults = { workspace_root: string; discovery_name: string; knowledge_name: string; max_file_bytes: number; max_total_bytes: number; chunk_bytes: number; defaults: { lane: string; stage: string; spec_mode: string }; templates: string[] };
export type NewApplicationPreview = { status: "READY" | "BLOCKED"; errors: { field: string; code: string; message: string }[]; values: { paths: Record<string, string>; registry: Record<string, unknown>; project_context: Record<string, unknown>; knowledge: Record<string, unknown> } };
export type NewApplicationCommit = { status: "READY" | "BLOCKED" | "ERROR"; errors?: { field: string; code: string; message: string }[]; project_key?: string; paths?: Record<string, string> };
export type WorkingDocumentOptions = { project_key: string; project_root: string; configured_path: string; legacy_path: string; candidates: { relative_path: string; size: number }[]; max_upload_bytes: number; templates: { id: string; label: string; source: "application" | "shared" }[]; suggested_output: string };
export type WorkingDocumentResult = { status: "READY" | "BLOCKED"; project_key?: string; working_docx?: string; legacy_docx?: string; errors?: { field: string; code: string; message: string }[] };

export function fetchWorkingDocumentOptions(system: string) {
  return api<WorkingDocumentOptions>(`/api/systems/${encodeURIComponent(system)}/working-document`);
}

export function selectWorkingDocument(system: string, relativePath: string) {
  return api<WorkingDocumentResult>(`/api/systems/${encodeURIComponent(system)}/working-document`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ relative_path: relativePath }),
  });
}

export function selectLegacyDocument(system: string, relativePath: string) {
  return api<WorkingDocumentResult>(`/api/systems/${encodeURIComponent(system)}/legacy-document`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ relative_path: relativePath }),
  });
}

export function uploadWorkingDocument(system: string, file: File) {
  return api<WorkingDocumentResult>(`/api/systems/${encodeURIComponent(system)}/working-document/upload?filename=${encodeURIComponent(file.name)}`, {
    method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: file,
  });
}

export function createWorkingDocumentFromTemplate(system: string, templateId: string, outputPath: string, systemName: string) {
  return api<WorkingDocumentResult>(`/api/systems/${encodeURIComponent(system)}/working-document/from-template`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template_id: templateId, output_path: outputPath, system_name: systemName, confirmed: true }),
  });
}

export function previewNewApplication(config: Record<string, unknown>) {
  return api<NewApplicationPreview>("/api/new-application/preview", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config),
  });
}

export function commitNewApplication(sessionId: string, config: Record<string, unknown>) {
  return api<NewApplicationCommit>("/api/new-application/commit", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, config, confirmed: true }),
  });
}

export function fetchNewApplicationDefaults() {
  return api<NewApplicationDefaults>("/api/new-application/defaults");
}

export function createNewApplicationUpload(manifest: NewApplicationManifestEntry[]) {
  return api<NewApplicationResult>("/api/new-application/uploads", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ manifest }),
  });
}

export function getNewApplicationUpload(sessionId: string) {
  return api<NewApplicationResult & { received_bytes: number; total_bytes: number; effective_status: string }>(`/api/new-application/uploads/${encodeURIComponent(sessionId)}`);
}

export async function putNewApplicationChunk(sessionId: string, path: string, index: number, data: ArrayBuffer, signal?: AbortSignal): Promise<NewApplicationResult> {
  const encodedPath = path.split("/").map(encodeURIComponent).join("/");
  return api<NewApplicationResult>(`/api/new-application/uploads/${encodeURIComponent(sessionId)}/files/${encodedPath}?index=${index}`, {
    method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: data, signal,
  });
}

export function finaliseNewApplicationUpload(sessionId: string) {
  return api<NewApplicationResult>(`/api/new-application/uploads/${encodeURIComponent(sessionId)}/finalise`, { method: "POST" });
}

export function cancelNewApplicationUpload(sessionId: string) {
  return api<NewApplicationResult>(`/api/new-application/uploads/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}

export async function fetchWordReview(system: string): Promise<WordReview> {
  return api<WordReview>(`/api/systems/${system}/word-review`);
}

export async function openWordDocument(system: string): Promise<{ state: string; authoritative_path: string; reason?: string }> {
  return api(`/api/systems/${system}/word-review/open`, { method: "POST" });
}

export async function refreshWordReview(system: string): Promise<WordReview> {
  return api<WordReview>(`/api/systems/${system}/word-review/refresh`, { method: "POST" });
}

export async function recordWordOperatorNote(system: string, note: string): Promise<{ state: string }> {
  return api(`/api/systems/${system}/word-review/operator-note`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note }),
  });
}

export async function submitReview(system: string, section: string): Promise<ReviewSubmit> {
  return api<ReviewSubmit>(`/api/systems/${system}/sections/${section}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function fetchReviewJob(system: string, jobId: string): Promise<ReviewJobResponse> {
  return api<ReviewJobResponse>(`/api/systems/${system}/review-jobs/${jobId}`);
}

export async function fetchLatestReview(system: string, section: string): Promise<ReviewLatest> {
  return api<ReviewLatest>(`/api/systems/${system}/review/latest/${section}`);
}

export async function fetchAuthorSetup(system: string, section: string): Promise<AuthorSetup> {
  return api<AuthorSetup>(`/api/systems/${system}/sections/${encodeURIComponent(section)}/author-setup`);
}

export async function submitAuthor(system: string, section: string, options: AuthorOptions): Promise<AuthorSubmit> {
  return api<AuthorSubmit>(`/api/systems/${system}/sections/${encodeURIComponent(section)}/author`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(options),
  });
}

export async function fetchAuthorJob(system: string, section: string, jobId: string): Promise<AuthorJobResponse> {
  return api<AuthorJobResponse>(`/api/systems/${system}/sections/${encodeURIComponent(section)}/author-jobs/${jobId}`);
}

export async function fetchLatestAuthor(system: string, section: string): Promise<AuthorJobResponse> {
  return api<AuthorJobResponse>(`/api/systems/${system}/sections/${encodeURIComponent(section)}/author/latest`);
}

export function authorArtifactUrl(system: string, section: string, key: string): string {
  return `/api/systems/${system}/sections/${encodeURIComponent(section)}/author-artifacts/${encodeURIComponent(key)}`;
}

export async function cancelJob(system: string, jobId: string): Promise<unknown> {
  return api(`/api/systems/${system}/jobs/${jobId}`, { method: "DELETE" });
}

export async function fetchCleanupPreflight(system: string, section: string): Promise<CleanupPreflight> {
  return api<CleanupPreflight>(`/api/systems/${system}/sections/${section}/cleanup-preflight`);
}

export async function submitCleanup(system: string, section: string): Promise<CleanupSubmit> {
  return api<CleanupSubmit>(`/api/systems/${system}/sections/${section}/cleanup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function fetchCleanupJob(system: string, jobId: string): Promise<CleanupJobResponse> {
  return api<CleanupJobResponse>(`/api/systems/${system}/cleanup-jobs/${jobId}`);
}

export async function fetchLatestCleanup(system: string, section: string): Promise<CleanupLatest> {
  return api<CleanupLatest>(`/api/systems/${system}/cleanup/latest/${section}`);
}

export async function fetchBuildSetup(system: string): Promise<BuildSetup> { return api(`/api/systems/${system}/build/setup`); }
export async function submitBuild(system: string, preview: boolean): Promise<{ job: ReviewJob; preflight: BuildSetup }> { return api(`/api/systems/${system}/build${preview ? "/preview" : ""}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(preview ? {} : { confirmed: true }) }); }
export async function fetchBuildJob(system: string, id: string): Promise<{ job: ReviewJob; outcome: BuildOutcome }> { return api(`/api/systems/${system}/build-jobs/${id}`); }
export async function fetchAudit(system: string): Promise<AuditSnapshot> { return api(`/api/systems/${system}/audit`); }
export async function submitAudit(system: string): Promise<{ job: ReviewJob }> { return api(`/api/systems/${system}/audit`, { method: "POST" }); }
export async function fetchAuditJob(system: string, id: string): Promise<{ job: ReviewJob; outcome: { state: string; snapshot?: AuditSnapshot; failure_reason?: string } }> { return api(`/api/systems/${system}/audit-jobs/${id}`); }
export async function recordAuditGap(system: string, payload: Record<string, string>): Promise<{ state: string; path: string }> { return api(`/api/systems/${system}/audit/gaps`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }

export async function fetchDraft(system: string): Promise<DraftSnapshot> { return api(`/api/systems/${system}/draft`); }
export async function submitJob(system: string, operation: string, target?: string, options: Record<string, string | boolean> = {}): Promise<ReviewJob> { return api(`/api/systems/${system}/jobs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation, target: target || null, options }) }); }
export async function fetchJobs(system: string): Promise<ReviewJob[]> { const data = await api<{ jobs: ReviewJob[] }>(`/api/systems/${system}/jobs`); return data.jobs; }
export async function fetchJob(system: string, id: string): Promise<ReviewJob> { return api(`/api/systems/${system}/jobs/${id}`); }

export async function fetchIntake(system: string): Promise<IntakeSnapshot> { return api(`/api/systems/${system}/intake`); }
export async function fetchIntakeErrors(system: string): Promise<IntakeErrors> { return api(`/api/systems/${system}/intake/errors`); }
export async function fetchJobLog(system: string, jobId: string, stream: "stdout" | "stderr", start: number, limit: number): Promise<JobLogPage> { return api(`/api/systems/${system}/jobs/${jobId}/log?stream=${stream}&start=${start}&limit=${limit}`); }
export async function reviewEvidence(system: string, id: string, state: "rejected" | "reviewed", note: string): Promise<{ status: string; reviewed: string[]; state: string }> {
  return api(`/api/systems/${system}/evidence/${encodeURIComponent(id)}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state, note }) });
}
export async function reviewLead(system: string, id: string, state: "open" | "not_an_answer" | "resolved" | "retired", note: string, evidenceIds: string[] = []): Promise<{ status: string; reviewed: string[]; reused: string[]; state: string }> {
  return api(`/api/systems/${system}/leads/${encodeURIComponent(id)}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state, note, evidence_ids: evidenceIds }) });
}

const JSON_HEADERS = { "Content-Type": "application/json" };
export async function fetchPrompts(system: string): Promise<PromptList> { return api(`/api/systems/${system}/prompts`); }
export async function savePrompt(system: string, name: string, text: string, etag: string): Promise<{ saved: boolean; etag: string }> { return api(`/api/systems/${system}/prompts/${name}`, { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify({ text, etag }) }); }
export async function resetPrompt(system: string, name: string): Promise<{ reset: boolean }> { return api(`/api/systems/${system}/prompts/${name}`, { method: "DELETE" }); }
export async function fetchPromptHistory(system: string, name: string): Promise<{ versions: { file: string; text: string }[] }> { return api(`/api/systems/${system}/prompts/${name}/history`); }
export async function fetchPromptPreview(system: string, key: string, block: string): Promise<PromptPreview> { return api(`/api/systems/${system}/prompt-preview?key=${encodeURIComponent(key)}&block=${encodeURIComponent(block)}`); }

export class DeviceEditError extends Error {
  code: string; status: number;
  constructor(message: string, code: string, status: number) { super(message); this.code = code; this.status = status; }
  get stale() { return this.code === "conflict" && this.message.startsWith("stale revision"); }
}

async function deviceCall<T>(system: string, method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/systems/${encodeURIComponent(system)}/devices${path}`, {
    method, headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === "string" ? detail : detail?.message || `Request failed (${response.status})`;
    throw new DeviceEditError(message, typeof detail === "object" && detail?.code ? detail.code : "error", response.status);
  }
  return data as T;
}

export const createDevice = (system: string, payload: DevicePayload) => deviceCall<DeviceEditResult>(system, "POST", "", payload);
export const patchDevice = (system: string, id: string, expected_revision: string, changes: DevicePayload, extra: { source?: string; owner_confirmed_on?: string; reviewer?: string }) =>
  deviceCall<DeviceEditResult>(system, "PATCH", `/${encodeURIComponent(id)}`, { expected_revision, changes, ...extra });
export const addDeviceAlias = (system: string, id: string, expected_revision: string, address: string, source: string) =>
  deviceCall<DeviceEditResult>(system, "POST", `/${encodeURIComponent(id)}/aliases`, { expected_revision, address, source });
export const removeDeviceAlias = (system: string, id: string, expected_revision: string, address: string) =>
  deviceCall<DeviceEditResult>(system, "DELETE", `/${encodeURIComponent(id)}/aliases/${encodeURIComponent(address)}?expected_revision=${encodeURIComponent(expected_revision)}`);
export const retireDevice = (system: string, id: string, expected_revision: string) =>
  deviceCall<DeviceEditResult>(system, "POST", `/${encodeURIComponent(id)}/retire`, { expected_revision });
export const restoreDevice = (system: string, id: string, expected_revision: string) =>
  deviceCall<DeviceEditResult>(system, "POST", `/${encodeURIComponent(id)}/restore`, { expected_revision });
export const previewDeviceAliases = (system: string, deviceId: string, add: string[], remove: string[]) =>
  deviceCall<AliasPreview>(system, "POST", "/reconcile-preview", { device_id: deviceId, add, remove });
