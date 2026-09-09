/** Grouping helpers for the KPI table: definitions (K01–K23) merged with the published rows. */
import type { GenderDimension, KpiDefinition, KpiRow } from "./types";

/** Map a stored dimension onto a gender column. Accepts `gender=female`, `female`, `sex=F`… */
export function genderBucket(dimension: string): GenderDimension | null {
  const raw = dimension.includes("=") ? dimension.slice(dimension.indexOf("=") + 1) : dimension;
  const v = raw.trim().toLowerCase();
  if (["female", "f", "woman", "women"].includes(v)) return "female";
  if (["male", "m", "man", "men"].includes(v)) return "male";
  if (["other", "x", "nonbinary", "non_binary", "non-binary"].includes(v)) return "other";
  if (["not_reported", "not-reported", "notreported", "undisclosed", "prefer_not_to_say", "unknown", "na", ""].includes(v))
    return "not_reported";
  return null;
}

export function isTotalRow(r: KpiRow): boolean {
  return r.dimension_kind === "total" || r.dimension === "total";
}

export function isGenderRow(r: KpiRow): boolean {
  return r.dimension_kind === "gender" || (!isTotalRow(r) && genderBucket(r.dimension) !== null && r.dimension_kind !== "village");
}

export interface KpiGroup {
  key: string;
  definition: KpiDefinition | null;
  total: KpiRow | null;
  gender: Partial<Record<GenderDimension, KpiRow>>;
  /** Village (and any other) breakdown rows, shown behind the toggle. */
  breakdown: KpiRow[];
  /** Any row of the group, used when neither a definition nor a total row exists. */
  sample: KpiRow | null;
}

/**
 * One group per KPI, in the order of the definition file; KPIs that only exist in the data are
 * appended so nothing published is silently dropped from the screen.
 */
export function groupRows(rows: KpiRow[], definitions: KpiDefinition[]): KpiGroup[] {
  const byKey = new Map<string, KpiRow[]>();
  for (const r of rows) {
    const list = byKey.get(r.kpi_key);
    if (list) list.push(r);
    else byKey.set(r.kpi_key, [r]);
  }
  const keys = [...definitions.map((d) => d.key), ...[...byKey.keys()].filter((k) => !definitions.some((d) => d.key === k))];

  return keys.map((key) => {
    const list = byKey.get(key) ?? [];
    const gender: Partial<Record<GenderDimension, KpiRow>> = {};
    const breakdown: KpiRow[] = [];
    let total: KpiRow | null = null;
    for (const r of list) {
      if (isTotalRow(r)) total = total ?? r;
      else if (isGenderRow(r)) {
        const b = genderBucket(r.dimension);
        if (b && !gender[b]) gender[b] = r;
        else breakdown.push(r);
      } else breakdown.push(r);
    }
    return {
      key,
      definition: definitions.find((d) => d.key === key) ?? null,
      total,
      gender,
      breakdown,
      sample: list[0] ?? null,
    };
  });
}

/** Is this KPI disaggregated by gender? The definition file decides; the data confirms. */
export function isGenderDisaggregated(g: KpiGroup): boolean {
  if (g.definition) return g.definition.gender_disaggregated;
  return Object.keys(g.gender).length > 0;
}

export function isProvisional(g: KpiGroup): boolean {
  if (g.definition) return g.definition.provisional;
  return g.total?.provisional_definition ?? g.sample?.provisional_definition ?? false;
}
