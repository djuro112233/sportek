/** Intl helpers shared by the admin screens. cnr → "sr-Latn" (Montenegrin, Latin script). */
import type { Lang } from "@/lib/i18n";

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
  return new Intl.DateTimeFormat(localeFor(lang), { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(d) + " UTC";
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

/** mm:ss from seconds (rounded). */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Format a KPI value by its unit: count → integer, minutes → "x min", share → percent (0..1). */
export function fmtByUnit(lang: Lang, value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  switch (unit) {
    case "count":
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
      return fmtNumber(lang, value, { style: "percent", maximumFractionDigits: 1 });
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
