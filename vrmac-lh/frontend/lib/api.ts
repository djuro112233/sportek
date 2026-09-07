/** Thin fetch wrapper for the FastAPI backend (same-origin /api, proxied by Next.js). */

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

const TOKEN_KEY = "vrmac.token";
const SESSION_KEY = "vrmac.session";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

/** Anonymous visitor session id: random, stored only in this browser, never linked to a person. */
export function sessionId(): string {
  try {
    let id = localStorage.getItem(SESSION_KEY);
    if (!id) {
      id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `s-${Math.random().toString(36).slice(2)}`;
      localStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    return "s-ephemeral";
  }
}

export interface User {
  id: string;
  email: string;
  role: "host" | "ambassador" | "validator" | "institution";
  display_name: string;
  sex: "F" | "M" | "X" | null;
  is_sample: boolean;
}

type Init = Omit<RequestInit, "body"> & { body?: unknown; auth?: boolean };

export async function api<T = unknown>(path: string, init: Init = {}): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  let body: BodyInit | undefined;
  if (init.body instanceof FormData) body = init.body;
  else if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.body);
  }
  if (init.auth !== false) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(path, { ...init, headers, body });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail ?? data;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export async function login(email: string, password: string): Promise<{ access_token: string; user: User }> {
  const r = await api<{ access_token: string; user: User }>("/api/auth/login", { method: "POST", body: { email, password }, auth: false });
  setToken(r.access_token);
  return r;
}

export async function me(): Promise<User | null> {
  if (!getToken()) return null;
  try {
    return await api<User>("/api/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) setToken(null);
    return null;
  }
}

export function logout() {
  setToken(null);
}

/** Google Maps navigation deep link — real routing, no API key needed. */
export function directionsUrl(lat: number, lng: number, mode: "walking" | "driving" = "walking"): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=${mode}`;
}

export interface Meta {
  prototype_label: string;
  languages: string[];
  local_language: string;
  maps_provider: "osm" | "google";
  google_maps_api_key: string;
  kpi_k_min: number;
  onboarding_target_minutes: number;
}

export function getMeta(): Promise<Meta> {
  return api<Meta>("/api/meta", { auth: false });
}
