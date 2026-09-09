import { ApiError } from "@/lib/api";
import type { Lang, Translate } from "@/lib/i18n";
import type {
  Confirmations,
  DraftResponse,
  Listing,
  ListingFields,
  ListingFormValues,
  SttInfo,
  StructuredField,
} from "./types";
import { STRUCTURED_FIELDS } from "./types";

/** 0 → "00:00", 754 → "12:34"; hours are shown as "1:05:03". */
export function mmss(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(r).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Intl locale for the UI language: "cnr" (Montenegrin, Latin script) → "sr-Latn". */
export function intlLocale(lang: Lang): string {
  return lang === "cnr" ? "sr-Latn" : "en";
}

export function formatNumber(lang: Lang, n: number): string {
  try {
    return new Intl.NumberFormat(intlLocale(lang)).format(n);
  } catch {
    return String(n);
  }
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

export function formatDate(lang: Lang, iso: string | null | undefined, withTime = false): string {
  if (!iso) return "";
  let d: Date;
  let time = withTime;
  if (DATE_ONLY.test(iso)) {
    const [y, m, day] = iso.split("-").map(Number);
    d = new Date(y, m - 1, day); // local calendar date, no timezone shift
    time = false;
  } else {
    d = new Date(iso);
  }
  if (Number.isNaN(d.getTime())) return iso;
  const opts: Intl.DateTimeFormatOptions = time
    ? { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { year: "numeric", month: "short", day: "numeric" };
  try {
    return new Intl.DateTimeFormat(intlLocale(lang), opts).format(d);
  } catch {
    return d.toISOString();
  }
}

/** Month 1-12 → localised month name. */
export function monthName(lang: Lang, month: number): string {
  const d = new Date(Date.UTC(2024, Math.max(0, Math.min(11, month - 1)), 1));
  try {
    return new Intl.DateTimeFormat(intlLocale(lang), { month: "long", timeZone: "UTC" }).format(d);
  } catch {
    return String(month);
  }
}

export const MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

export function formatPrice(lang: Lang, min: number | null, max: number | null, currency: string): string | null {
  if (min === null && max === null) return null;
  let fmt: (n: number) => string;
  try {
    const nf = new Intl.NumberFormat(intlLocale(lang), {
      style: "currency",
      currency: currency || "EUR",
      maximumFractionDigits: 0,
    });
    fmt = (n) => nf.format(n);
  } catch {
    fmt = (n) => `${n} ${currency || "EUR"}`;
  }
  if (min !== null && max !== null) return min === max ? fmt(min) : `${fmt(min)} – ${fmt(max)}`;
  return fmt((min ?? max) as number);
}

export function formatBytes(lang: Lang, bytes: number): string {
  const kb = bytes / 1024;
  if (kb < 1024) return `${formatNumber(lang, Math.max(1, Math.round(kb)))} kB`;
  return `${formatNumber(lang, Math.round((kb / 1024) * 10) / 10)} MB`;
}

/** Human-readable message for any thrown value (an ApiError detail may be a string or a FastAPI list). */
export function describeError(e: unknown, t: Translate): string {
  if (e instanceof ApiError) {
    const d = e.detail;
    let message: string;
    if (typeof d === "string") message = d;
    else if (Array.isArray(d)) {
      message = d
        .map((x) => {
          if (x && typeof x === "object" && "msg" in x) {
            const loc =
              "loc" in x && Array.isArray((x as { loc: unknown }).loc) ? (x as { loc: unknown[] }).loc.join(".") : "";
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
  category: "",
  price_min: "",
  price_max: "",
  currency: "EUR",
  price_note_local: "",
  price_note_en: "",
  season_all_year: false,
  season_from: "",
  season_to: "",
  capacity: "",
  accessibility_step_free: "",
  accessibility_note_local: "",
  accessibility_note_en: "",
  lat: "",
  lng: "",
  coords_approximate: true,
  village_id: "",
};

export const NO_CONFIRMATIONS: Confirmations = {
  category: false,
  price_range: false,
  season: false,
  capacity: false,
  accessibility: false,
  coordinates: false,
};

function str(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  return String(v);
}

/**
 * Title and description only — the four fields the assistant is allowed to draft.
 * Everything else in the form is left untouched: it is host-entered.
 */
export function narrativeFromDraft(r: DraftResponse): Pick<
  ListingFormValues,
  "title_local" | "title_en" | "description_local" | "description_en"
> {
  const raw = r.draft ?? {};
  const fields = raw.fields && typeof raw.fields === "object" ? raw.fields : raw;
  return {
    title_local: str(fields.title_local),
    title_en: str(fields.title_en),
    description_local: str(fields.description_local),
    description_en: str(fields.description_en),
  };
}

export function formFromListing(l: Listing, villageId = ""): ListingFormValues {
  return {
    title_local: l.title_local ?? "",
    title_en: l.title_en ?? "",
    description_local: l.description_local ?? "",
    description_en: l.description_en ?? "",
    category: l.category || "",
    price_min: str(l.price_min),
    price_max: str(l.price_max),
    currency: l.currency || "EUR",
    price_note_local: l.price_note_local ?? "",
    price_note_en: l.price_note_en ?? "",
    season_all_year: Boolean(l.season_all_year),
    season_from: str(l.season_from),
    season_to: str(l.season_to),
    capacity: str(l.capacity),
    accessibility_step_free: l.accessibility_step_free === null || l.accessibility_step_free === undefined ? "" : l.accessibility_step_free ? "yes" : "no",
    accessibility_note_local: l.accessibility_note_local ?? "",
    accessibility_note_en: l.accessibility_note_en ?? "",
    lat: str(l.lat),
    lng: str(l.lng),
    coords_approximate: l.coords_approximate ?? true,
    village_id: l.village_id ?? villageId,
  };
}

/** Which structured groups a saved listing already carries a host confirmation for. */
export function confirmationsFromListing(l: Listing): Confirmations {
  const given = new Set((l.confirmed_fields ?? []).map(String));
  const out = { ...NO_CONFIRMATIONS };
  for (const f of STRUCTURED_FIELDS) out[f] = given.has(f);
  return out;
}

export function num(s: string): number | null {
  const v = s.trim().replace(",", ".");
  if (v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function int(s: string): number | null {
  const n = num(s);
  return n === null ? null : Math.round(n);
}

export function formToFields(v: ListingFormValues, confirmed: Confirmations): ListingFields {
  return {
    title_local: v.title_local.trim(),
    title_en: v.title_en.trim(),
    description_local: v.description_local.trim(),
    description_en: v.description_en.trim(),
    category: v.category || "other",
    price_min: num(v.price_min),
    price_max: num(v.price_max),
    currency: (v.currency || "EUR").toUpperCase(),
    price_note_local: v.price_note_local.trim(),
    price_note_en: v.price_note_en.trim(),
    season_from: v.season_all_year ? null : int(v.season_from),
    season_to: v.season_all_year ? null : int(v.season_to),
    season_all_year: v.season_all_year,
    capacity: int(v.capacity),
    accessibility_step_free: v.accessibility_step_free === "" ? null : v.accessibility_step_free === "yes",
    accessibility_note_local: v.accessibility_note_local.trim(),
    accessibility_note_en: v.accessibility_note_en.trim(),
    lat: num(v.lat),
    lng: num(v.lng),
    coords_approximate: v.coords_approximate,
    confirmed_fields: STRUCTURED_FIELDS.filter((f) => confirmed[f]),
  };
}

/** The structured groups the host has not confirmed yet (submitting is blocked while this is non-empty). */
export function unconfirmed(confirmed: Confirmations): StructuredField[] {
  return STRUCTURED_FIELDS.filter((f) => !confirmed[f]);
}

/** Returns a translated error message, or null when the form may be submitted. */
export function validateForm(v: ListingFormValues, t: Translate): string | null {
  if (!v.title_local.trim() && !v.title_en.trim()) return t("host.field.titleRequired");
  if (!v.description_local.trim() && !v.description_en.trim()) return t("host.field.descriptionRequired");
  if (!v.category) return t("host.field.categoryRequired");
  for (const k of ["price_min", "price_max", "capacity", "lat", "lng"] as const) {
    if (v[k].trim() !== "" && num(v[k]) === null) return t("host.field.notANumber", { field: t(`host.field.${k}`) });
  }
  const min = num(v.price_min);
  const max = num(v.price_max);
  if (min !== null && min < 0) return t("host.field.notANumber", { field: t("host.field.price_min") });
  if (min !== null && max !== null && min > max) return t("host.field.priceOrder");
  if (!v.season_all_year && (v.season_from === "") !== (v.season_to === "")) return t("host.field.seasonPair");
  const cap = int(v.capacity);
  if (cap !== null && cap < 0) return t("host.field.notANumber", { field: t("host.field.capacity") });
  const lat = num(v.lat);
  const lng = num(v.lng);
  if ((lat === null) !== (lng === null)) return t("host.field.coordsPair");
  if (lat !== null && (lat < -90 || lat > 90)) return t("host.field.notANumber", { field: t("host.field.lat") });
  if (lng !== null && (lng < -180 || lng > 180)) return t("host.field.notANumber", { field: t("host.field.lng") });
  if (!v.village_id) return t("host.field.villageRequired");
  return null;
}

/** Client-side view of `missing_fields`: which required groups are still empty. */
export function missingGroups(v: ListingFormValues): StructuredField[] {
  const out: StructuredField[] = [];
  if (!v.category) out.push("category");
  if (num(v.price_min) === null && num(v.price_max) === null && !v.price_note_local.trim() && !v.price_note_en.trim())
    out.push("price_range");
  if (!v.season_all_year && (v.season_from === "" || v.season_to === "")) out.push("season");
  if (int(v.capacity) === null) out.push("capacity");
  if (v.accessibility_step_free === "") out.push("accessibility");
  if (num(v.lat) === null || num(v.lng) === null) out.push("coordinates");
  return out;
}

export function seasonLabel(lang: Lang, l: Pick<ListingFields, "season_all_year" | "season_from" | "season_to">, t: Translate): string {
  if (l.season_all_year) return t("host.season.allYear");
  if (l.season_from && l.season_to) return `${monthName(lang, l.season_from)} – ${monthName(lang, l.season_to)}`;
  return t("host.value.notGiven");
}

/** A stable client id (recording ids, form keys). */
export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `r-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
