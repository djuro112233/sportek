/** Look-ups over the village reference data (`GET /api/villages`). */
import { pick, type Lang } from "@/lib/i18n";
import type { Village } from "./types";

export function villageByKey(villages: Village[], key: string | null | undefined): Village | null {
  if (!key) return null;
  return villages.find((v) => v.slug === key || v.id === key) ?? null;
}

/** Localised village name, falling back to whatever key the API sent. */
export function villageName(lang: Lang, villages: Village[], key: string | null | undefined): string {
  const v = villageByKey(villages, key);
  if (v) return pick(lang, v.name_local, v.name_en);
  return key || "—";
}

/** "Gornja Lastva (Tivat)" — the village and the municipality it belongs to. */
export function villageWithMunicipality(
  lang: Lang,
  villages: Village[],
  key: string | null | undefined,
  municipality?: string | null,
): string {
  const v = villageByKey(villages, key);
  const name = v ? pick(lang, v.name_local, v.name_en) : key || "—";
  const mun = municipality || v?.municipality || "";
  return mun ? `${name} (${mun})` : name;
}

/** Villages sorted by municipality then localised name — the order of the pickers. */
export function sortedVillages(lang: Lang, villages: Village[]): Village[] {
  return [...villages].sort(
    (a, b) =>
      a.municipality.localeCompare(b.municipality) ||
      pick(lang, a.name_local, a.name_en).localeCompare(pick(lang, b.name_local, b.name_en)),
  );
}
