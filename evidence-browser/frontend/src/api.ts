import type { WordReview, ReviewSubmit, ReviewJob, ReviewJobResponse, ReviewLatest, AuthorSetup, AuthorSubmit, AuthorJobResponse, CleanupSubmit, CleanupJobResponse, CleanupLatest, CleanupPreflight, BuildSetup, BuildOutcome, AuditSnapshot } from "./types";

export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || `Request failed (${response.status})`);
  }
  return data as T;
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

export async function submitAuthor(system: string, section: string, cards: boolean): Promise<AuthorSubmit> {
  return api<AuthorSubmit>(`/api/systems/${system}/sections/${encodeURIComponent(section)}/author`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cards }),
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
