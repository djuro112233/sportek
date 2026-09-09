import { ApiError } from "@/lib/api";
import type { Lang, Translate } from "@/lib/i18n";
import type { DraftFieldValues, DraftResponse, Listing, ListingFields, ListingFormValues, SttInfo } from "./types";
import { LISTING_FIELD_KEYS } from "./types";

/** 0 → "00:00", 754 → "12:34". */
export function mmss(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

/** Intl locale for the UI language: "cnr" (Montenegrin, Latin) → "sr-Latn". */
export function intlLocale(lang: Lang): string {
  return lang === "cnr" ? "sr-Latn" : "en";
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

export function formatDate(lang: Lang, iso: string | null | undefined, withTime = false): string {
  if (!iso) return "";
  let d: Date;
  if (DATE_ONLY.test(iso)) {
    const [y, m, day] = iso.split("-").map(Number);
    d = new Date(y, m - 1, day); // local calendar date, no timezone shift
    withTime = false;
  } else {
    d = new Date(iso);
  }
  if (Number.isNaN(d.getTime())) return iso;
  const opts: Intl.DateTimeFormatOptions = withTime
    ? { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { year: "numeric", month: "short", day: "numeric" };
  try {
    return new Intl.DateTimeFormat(intlLocale(lang), opts).format(d);
  } catch {
    return d.toISOString();
  }
}

export function formatPrice(lang: Lang, min: number | null, max: number | null, currency: string): string | null {
  if (min === null && max === null) return null;
  let fmt: (n: number) => string;
  try {
    const nf = new Intl.NumberFormat(intlLocale(lang), { style: "currency", currency: currency || "EUR", maximumFractionDigits: 0 });
    fmt = (n) => nf.format(n);
  } catch {
    fmt = (n) => `${n} ${currency || "EUR"}`;
  }
  if (min !== null && max !== null) return min === max ? fmt(min) : `${fmt(min)} – ${fmt(max)}`;
  return fmt((min ?? max) as number);
}

/** Human-readable message for any thrown value (ApiError detail may be a string or a FastAPI error list). */
export function describeError(e: unknown, t: Translate): string {
  if (e instanceof ApiError) {
    const d = e.detail;
    let message: string;
    if (typeof d === "string") message = d;
    else if (Array.isArray(d)) {
      message = d
        .map((x) => {
          if (x && typeof x === "object" && "msg" in x) {
            const loc = "loc" in x && Array.isArray((x as { loc: unknown }).loc) ? (x as { loc: unknown[] }).loc.join(".") : "";
            return loc ? `${loc}: ${String((x as { msg: unknown }).msg)}` : String((x as { msg: unknown }).msg);
          }
          return JSON.stringify(x);
        })
        .join("; ");
    } else if (d && typeof d === "object" && "message" in d) message = String((d as { message: unknown }).message);
    else message = d === null || d === undefined ? "" : JSON.stringify(d);
    return t("host.error.api", { status: e.status, message: message || e.message });
  }
  return t("common.error", { message: e instanceof Error ? e.message : String(e) });
}

export function normalizeStt(v: SttInfo | string | null | undefined): SttInfo | null {
  if (!v) return null;
  if (typeof v === "string") return { provider: v };
  return v;
}

export const EMPTY_FORM: ListingFormValues = {
  title_local: "",
  title_en: "",
  description_local: "",
  description_en: "",
  category: "other",
  price_min: "",
  price_max: "",
  currency: "EUR",
  season: "",
  capacity: "",
  accessibility_local: "",
  accessibility_en: "",
  lat: "",
  lng: "",
  coords_approximate: true,
};

function str(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  return String(v);
}

/** Build the form model from a draft response; tolerates `draft.fields` and `draft` shaped payloads. */
export function formFromDraft(r: DraftResponse): { values: ListingFormValues; missing: string[] } {
  const raw = r.draft ?? {};
  const fields: DraftFieldValues = raw.fields && typeof raw.fields === "object" ? raw.fields : raw;
  const values: ListingFormValues = {
    ...EMPTY_FORM,
    title_local: str(fields.title_local),
    title_en: str(fields.title_en),
    description_local: str(fields.description_local),
    description_en: str(fields.description_en),
    category: str(fields.category) || "other",
    price_min: str(fields.price_min),
    price_max: str(fields.price_max),
    currency: str(fields.currency) || "EUR",
    season: str(fields.season),
    capacity: str(fields.capacity),
    accessibility_local: str(fields.accessibility_local),
    accessibility_en: str(fields.accessibility_en),
    lat: str(fields.lat),
    lng: str(fields.lng),
    coords_approximate: typeof fields.coords_approximate === "boolean" ? fields.coords_approximate : true,
  };
  const missingRaw = r.missing_fields ?? raw.missing_fields ?? [];
  const missing = Array.isArray(missingRaw) ? missingRaw.map(String) : [];
  return { values, missing };
}

export function formFromListing(l: Listing): ListingFormValues {
  return {
    title_local: l.title_local ?? "",
    title_en: l.title_en ?? "",
    description_local: l.description_local ?? "",
    description_en: l.description_en ?? "",
    category: l.category || "other",
    price_min: str(l.price_min),
    price_max: str(l.price_max),
    currency: l.currency || "EUR",
    season: l.season ?? "",
    capacity: str(l.capacity),
    accessibility_local: l.accessibility_local ?? "",
    accessibility_en: l.accessibility_en ?? "",
    lat: str(l.lat),
    lng: str(l.lng),
    coords_approximate: l.coords_approximate ?? true,
  };
}

function num(s: string): number | null {
  const v = s.trim().replace(",", ".");
  if (v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function formToFields(v: ListingFormValues): ListingFields {
  const cap = num(v.capacity);
  return {
    title_local: v.title_local.trim(),
    title_en: v.title_en.trim(),
    description_local: v.description_local.trim(),
    description_en: v.description_en.trim(),
    category: v.category || "other",
    price_min: num(v.price_min),
    price_max: num(v.price_max),
    currency: (v.currency || "EUR").toUpperCase(),
    season: v.season.trim() || null,
    capacity: cap === null ? null : Math.round(cap),
    accessibility_local: v.accessibility_local.trim(),
    accessibility_en: v.accessibility_en.trim(),
    lat: num(v.lat),
    lng: num(v.lng),
    coords_approximate: v.coords_approximate,
  };
}

/** Returns a translated error message, or null when the form can be submitted. */
export function validateForm(v: ListingFormValues, t: Translate): string | null {
  if (!v.title_local.trim()) return t("host.field.titleRequired");
  for (const k of ["price_min", "price_max", "capacity", "lat", "lng"] as const) {
    if (v[k].trim() !== "" && num(v[k]) === null) return t("host.field.notANumber", { field: t(`host.field.${k}`) });
  }
  const min = num(v.price_min);
  const max = num(v.price_max);
  if (min !== null && max !== null && min > max) return t("host.field.priceOrder");
  const lat = num(v.lat);
  const lng = num(v.lng);
  if ((lat === null) !== (lng === null)) return t("host.field.coordsPair");
  if (lat !== null && (lat < -90 || lat > 90)) return t("host.field.notANumber", { field: t("host.field.lat") });
  if (lng !== null && (lng < -180 || lng > 180)) return t("host.field.notANumber", { field: t("host.field.lng") });
  return null;
}

/** Fields still empty after the host's edits (client-side view of missing_fields). */
export function stillMissing(v: ListingFormValues, missing: string[]): string[] {
  return missing.filter((k) => {
    if (!(LISTING_FIELD_KEYS as string[]).includes(k)) return true;
    const val = v[k as keyof ListingFormValues];
    return typeof val === "string" ? val.trim() === "" : false;
  });
}
