/** Intl helpers shared by the admin screens. cnr → "sr-Latn" (Montenegrin, Latin script). */
import type { Lang, Translate } from "@/lib/i18n";

/** Translate `key`, but fall back to `fallback` (a raw backend value) when there is no entry. */
export function label(t: Translate, key: string, fallback: string): string {
  const v = t(key);
  return v === key ? fallback : v;
}

export function localeFor(lang: Lang): string {
  return lang === "cnr" ? "sr-Latn" : "en-GB";
}

const ISO_RE = /^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/;

export function isIsoDate(s: unknown): s is string {
  return typeof s === "string" && ISO_RE.test(s);
}

export function fmtDateTime(lang: Lang, iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return (
    new Intl.DateTimeFormat(localeFor(lang), { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(d) +
    " UTC"
  );
}

export function fmtDate(lang: Lang, iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(localeFor(lang), { dateStyle: "medium", timeZone: "UTC" }).format(d);
}

export function fmtNumber(lang: Lang, n: number | null | undefined, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat(localeFor(lang), opts).format(n);
}

/** A share given as 0…1 rendered as a percentage. */
export function fmtPercent(lang: Lang, share: number | null | undefined, digits = 1): string {
  if (share === null || share === undefined || Number.isNaN(share)) return "—";
  return new Intl.NumberFormat(localeFor(lang), { style: "percent", maximumFractionDigits: digits }).format(share);
}

export function fmtEuro(lang: Lang, n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat(localeFor(lang), { style: "currency", currency: "EUR" }).format(n);
}

/** mm:ss from seconds (rounded). */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Seconds → minutes with one decimal, for the onboarding timing table. */
export function fmtMinutes(lang: Lang, seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  return fmtNumber(lang, seconds / 60, { maximumFractionDigits: 1 });
}

/** Format a KPI value by its unit: count → integer, minutes → "x min", share → percent (0…1). */
export function fmtByUnit(lang: Lang, value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  switch (unit) {
    case "count":
    case "persons":
    case "sessions":
    case "devices":
      return fmtNumber(lang, value, { maximumFractionDigits: Number.isInteger(value) ? 0 : 1 });
    case "minutes":
    case "min":
      return `${fmtNumber(lang, value, { maximumFractionDigits: 1 })} min`;
    case "seconds":
    case "s":
      return fmtDuration(value);
    case "share":
    case "percent":
    case "%":
    case "ratio":
    case "rate":
      return fmtPercent(lang, value);
    default:
      return `${fmtNumber(lang, value, { maximumFractionDigits: 2 })}${unit ? ` ${unit}` : ""}`;
  }
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

export function fmtCoord(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toFixed(5);
}

/** Short, readable rendering of an arbitrary JSON value in a definition list or a table cell. */
export function fmtValue(lang: Lang, v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "✓" : "✗";
  if (typeof v === "number") return fmtNumber(lang, v, { maximumFractionDigits: 5 });
  if (typeof v === "string") return isIsoDate(v) ? fmtDateTime(lang, v) : v;
  if (Array.isArray(v)) return v.length === 0 ? "—" : v.map((x) => fmtValue(lang, x)).join(", ");
  return JSON.stringify(v);
}

/** Month number (1–12) → month name in the active language. */
export function monthName(lang: Lang, month: number | null | undefined): string {
  if (month === null || month === undefined || month < 1 || month > 12) return "—";
  const d = new Date(Date.UTC(2024, month - 1, 1));
  return new Intl.DateTimeFormat(localeFor(lang), { month: "long", timeZone: "UTC" }).format(d);
}
