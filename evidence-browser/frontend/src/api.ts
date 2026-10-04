import type { WordReview } from "./types";

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
