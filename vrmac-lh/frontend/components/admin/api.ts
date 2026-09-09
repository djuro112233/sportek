/** Typed calls of the admin screens (validator queue + institution dashboard).
 *
 *  Every path comes from `docs/api-contract.md`. The helpers are deliberately tolerant about the
 *  envelope (`[...]` vs `{items: [...]}`) so a partially built backend still renders.
 */
import { ApiError, api } from "@/lib/api";
import type {
  AuditRow,
  HeatmapCollection,
  HeritageEntryIn,
  HeritageEntryOut,
  ItemType,
  KpiDefinitionsFile,
  KpiRunSummary,
  KpiSnapshot,
  QualityMetrics,
  QueueItem,
  Status,
  TimingRow,
  ValidationItem,
  Village,
} from "./types";

function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** Accept a bare array or `{key: [...]}` / `{items: [...]}` / `{results: [...]}`. */
function asArray<T>(data: unknown, ...keys: string[]): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === "object") {
    for (const k of [...keys, "items", "results", "rows", "data"]) {
      const v = (data as Record<string, unknown>)[k];
      if (Array.isArray(v)) return v as T[];
    }
  }
  return [];
}

/** 404 (endpoint not built yet / nothing published) → `null` instead of an error screen. */
export async function optional<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/** Human-readable message of an API failure, with the status code kept visible. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail;
    if (typeof d === "string") return `${e.status} — ${d}`;
    if (Array.isArray(d)) {
      const parts = d.map((x) => {
        const o = x as { loc?: unknown[]; msg?: string };
        const loc = Array.isArray(o.loc) ? o.loc.filter((s) => s !== "body").join(".") : "";
        return loc ? `${loc}: ${o.msg ?? ""}` : (o.msg ?? JSON.stringify(x));
      });
      return `${e.status} — ${parts.join("; ")}`;
    }
    return `${e.status} — ${JSON.stringify(d)}`;
  }
  return e instanceof Error ? e.message : String(e);
}

/* ---------- territory ---------- */

export async function getVillages(municipality?: string): Promise<Village[]> {
  return asArray<Village>(await api(`/api/villages${qs({ municipality })}`, { auth: false }), "villages");
}

/* ---------- validation ---------- */

export async function getQueue(filters: { item_type?: string; village?: string } = {}): Promise<QueueItem[]> {
  return asArray<QueueItem>(await api(`/api/validation/queue${qs(filters)}`), "queue");
}

export function getValidationItem(itemType: ItemType | string, id: string): Promise<ValidationItem> {
  return api<ValidationItem>(`/api/validation/items/${encodeURIComponent(itemType)}/${encodeURIComponent(id)}`);
}

export function postTransition(
  itemType: ItemType | string,
  id: string,
  to_status: Status,
  note: string,
): Promise<unknown> {
  return api(`/api/validation/items/${encodeURIComponent(itemType)}/${encodeURIComponent(id)}/transition`, {
    method: "POST",
    body: { to_status, note },
  });
}

export async function getAudit(): Promise<AuditRow[]> {
  return asArray<AuditRow>(await api("/api/validation/audit"), "audit");
}

export function createHeritageEntry(body: HeritageEntryIn): Promise<HeritageEntryOut> {
  return api<HeritageEntryOut>("/api/heritage", { method: "POST", body });
}

/* ---------- kpi ---------- */

export function getKpi(): Promise<KpiSnapshot> {
  return api<KpiSnapshot>("/api/kpi");
}

export function computeKpi(periodDays?: number): Promise<KpiRunSummary> {
  return api<KpiRunSummary>("/api/kpi/compute", {
    method: "POST",
    body: periodDays ? { period_days: periodDays } : {},
  });
}

export async function getKpiRuns(): Promise<KpiRunSummary[]> {
  return asArray<KpiRunSummary>(await api("/api/kpi/runs"), "runs");
}

export function reviewKpiRun(runId: string, decision: "publish" | "reject", note: string): Promise<unknown> {
  return api(`/api/kpi/runs/${encodeURIComponent(runId)}/review`, { method: "POST", body: { decision, note } });
}

export function getHeatmap(): Promise<HeatmapCollection> {
  return api<HeatmapCollection>("/api/kpi/heatmap");
}

export async function getKpiDefinitions(): Promise<KpiDefinitionsFile> {
  const data = await api<unknown>("/api/kpi/definitions", { auth: false });
  const file = (data ?? {}) as Partial<KpiDefinitionsFile>;
  return { version: file.version ?? "", status: file.status, warning: file.warning, kpis: asArray(data, "kpis") };
}

export function getQuality(): Promise<QualityMetrics> {
  return api<QualityMetrics>("/api/kpi/quality");
}

/* ---------- onboarding ---------- */

export async function getTimingLog(): Promise<TimingRow[]> {
  return asArray<TimingRow>(await api("/api/onboarding/timing-log"), "sessions", "timing");
}
