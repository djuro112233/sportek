/** Intl + geometry helpers for the visitor app. cnr → "sr-Latn" (Montenegrin, Latin script). */
import type { Lang } from "@/lib/i18n";
import type { LatLng } from "./types";

export function localeFor(lang: Lang): string {
  return lang === "cnr" ? "sr-Latn" : "en-GB";
}

export function fmtNumber(lang: Lang, n: number | null | undefined, opts: Intl.NumberFormatOptions = {}): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat(localeFor(lang), opts).format(n);
}

export function fmtDate(lang: Lang, iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(localeFor(lang), { dateStyle: "medium", timeZone: "UTC" }).format(d);
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

export function fmtMonth(lang: Lang, month: number | null | undefined): string {
  if (month === null || month === undefined || month < 1 || month > 12) return "—";
  const d = new Date(Date.UTC(2000, month - 1, 1));
  return new Intl.DateTimeFormat(localeFor(lang), { month: "long", timeZone: "UTC" }).format(d);
}

export function fmtMoney(lang: Lang, n: number | null | undefined, currency = "EUR"): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  try {
    return new Intl.NumberFormat(localeFor(lang), { style: "currency", currency, maximumFractionDigits: 0 }).format(n);
  } catch {
    return `${fmtNumber(lang, n)} ${currency}`;
  }
}

/** Distance for humans: metres below a kilometre, then one decimal. */
export function fmtDistance(lang: Lang, metres: number | null | undefined): string {
  if (metres === null || metres === undefined || Number.isNaN(metres)) return "—";
  if (metres < 1000) return `${fmtNumber(lang, Math.round(metres))} m`;
  return `${fmtNumber(lang, metres / 1000, { maximumFractionDigits: 1 })} km`;
}

export function fmtMinutes(lang: Lang, minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return "—";
  return `${fmtNumber(lang, Math.round(minutes))} min`;
}

/** WGS84 coordinates, five decimals (~1 m) — the form we announce to screen readers. */
export function fmtCoord(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(5);
}

export function fmtLatLng(p: LatLng | null | undefined): string {
  if (!p) return "—";
  return `${fmtCoord(p.lat)}, ${fmtCoord(p.lng)}`;
}

/** Great-circle distance in metres (WGS84 sphere approximation). */
export function haversineM(a: LatLng, b: LatLng): number {
  const R = 6371008.8;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const s =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}
