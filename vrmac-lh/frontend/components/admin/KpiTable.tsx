"use client";
import { Fragment, useId, useState } from "react";
import { pick, useLang, useT, type Translate } from "@/lib/i18n";
import { fmtByUnit, fmtNumber, label } from "./format";
import { groupRows, isGenderDisaggregated, isProvisional, type KpiGroup } from "./kpi";
import { GENDER_DIMENSIONS, type KpiDefinition, type KpiRow, type Village } from "./types";
import { villageName } from "./villages";
import styles from "./admin.module.css";

function suppressionText(t: Translate, row: KpiRow, kMin: number): { short: string; full: string } {
  const reason = row.suppression_reason || row.note || "";
  const short = t("admin.kpi.suppressed", { k: kMin });
  const reasonText =
    reason === "secondary"
      ? t("admin.kpi.reasonSecondary")
      : reason.startsWith("k<")
        ? t("admin.kpi.reasonPrimary", { k: kMin })
        : reason
          ? label(t, `admin.kpi.reason.${reason}`, reason)
          : t("admin.kpi.reasonPrimary", { k: kMin });
  return { short, full: `${short} — ${reasonText}` };
}

/** One published cell. A suppressed cell never shows a number, only why it is hidden. */
function Cell({ row, kMin, header = false }: { row: KpiRow | null | undefined; kMin: number; header?: boolean }) {
  const t = useT();
  const { lang } = useLang();
  if (!row) {
    return (
      <td className="muted" aria-label={t("admin.kpi.notDisaggregated")}>
        —
      </td>
    );
  }
  if (row.suppressed) {
    const { short, full } = suppressionText(t, row, kMin);
    return (
      <td className={styles.suppressed} aria-label={full} title={full}>
        {short}
      </td>
    );
  }
  const value = fmtByUnit(lang, row.value, row.unit);
  return (
    <td className={styles.num}>
      <strong style={{ fontWeight: header ? 700 : 500 }}>{value}</strong>
      <br />
      <span className="muted small">
        {row.n_persons !== null && row.n_persons !== undefined
          ? t("admin.kpi.nPersonsEvents", { persons: fmtNumber(lang, row.n_persons), events: fmtNumber(lang, row.n_events) })
          : t("admin.kpi.nEvents", { events: fmtNumber(lang, row.n_events) })}
      </span>
    </td>
  );
}

function KpiName({ group }: { group: KpiGroup }) {
  const t = useT();
  const { lang } = useLang();
  const def = group.definition;
  const name = def
    ? pick(lang, def.label_local, def.label_en)
    : (group.total?.kpi_label ?? group.sample?.kpi_label ?? group.key);
  return (
    <>
      <span className={styles.mono}>{group.key}</span> {name}
      {isProvisional(group) && (
        <>
          {" "}
          <span className="badge badge-reviewed">{t("admin.kpi.provisionalBadge")}</span>
        </>
      )}
      {def?.definition && (
        <details>
          <summary className="small muted">{t("admin.kpi.showDefinition")}</summary>
          <p className="small" style={{ margin: ".25rem 0 0" }}>
            {def.definition}
          </p>
          <p className="small muted" style={{ margin: ".25rem 0 0" }}>
            {t("admin.kpi.unit")}: {def.unit}
            {def.person_level ? ` · ${t("admin.kpi.personLevel")}` : ""}
          </p>
        </details>
      )}
    </>
  );
}

/**
 * K01–K23: the definition file merged with the rows of the published run.
 * Gender columns are filled **only** from a voluntary self-report; small cells are suppressed.
 */
export default function KpiTable({
  rows,
  definitions,
  kMin,
  villages,
}: {
  rows: KpiRow[];
  definitions: KpiDefinition[];
  kMin: number;
  villages: Village[];
}) {
  const t = useT();
  const { lang } = useLang();
  const toggleId = useId();
  const [showBreakdown, setShowBreakdown] = useState(false);
  const groups = groupRows(rows, definitions);
  const anyBreakdown = groups.some((g) => g.breakdown.length > 0);

  return (
    <div className="stack">
      <div className="row">
        <input
          id={toggleId}
          type="checkbox"
          checked={showBreakdown}
          onChange={(e) => setShowBreakdown(e.target.checked)}
          disabled={!anyBreakdown}
          style={{ width: "auto", minHeight: "auto" }}
        />
        <label htmlFor={toggleId}>
          {t("admin.kpi.showVillages")}
          {!anyBreakdown && <span className="muted small"> — {t("admin.kpi.noBreakdown")}</span>}
        </label>
      </div>

      <div className="table-wrap">
        <table className="table">
          <caption>{t("admin.kpi.caption", { k: kMin })}</caption>
          <thead>
            <tr>
              <th scope="col">{t("admin.kpi.colKpi")}</th>
              <th scope="col">{t("admin.kpi.colTotal")}</th>
              {GENDER_DIMENSIONS.map((g) => (
                <th key={g} scope="col">
                  {t(`admin.gender.${g}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const disaggregated = isGenderDisaggregated(g);
              return (
                <Fragment key={g.key}>
                  <tr>
                    <th scope="row" style={{ fontWeight: 400 }}>
                      <KpiName group={g} />
                    </th>
                    <Cell row={g.total} kMin={kMin} header />
                    {GENDER_DIMENSIONS.map((dim) => (
                      <Cell key={dim} row={disaggregated ? (g.gender[dim] ?? null) : null} kMin={kMin} />
                    ))}
                  </tr>
                  {showBreakdown &&
                    g.breakdown.map((b, i) => (
                      <tr key={`${g.key}-b-${i}`} className={styles.detailsRow}>
                        <th scope="row" style={{ fontWeight: 400, paddingLeft: "2rem" }}>
                          {b.dimension_kind === "village"
                            ? villageName(lang, villages, b.dimension.replace(/^village=/, ""))
                            : b.dimension}
                          <span className="muted small"> ({label(t, `admin.kpi.dim.${b.dimension_kind}`, b.dimension_kind)})</span>
                        </th>
                        <Cell row={b} kMin={kMin} />
                        <td className="muted" colSpan={GENDER_DIMENSIONS.length}>
                          —
                        </td>
                      </tr>
                    ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <section aria-labelledby="kpi-legend">
        <h3 id="kpi-legend" style={{ marginBottom: ".3rem" }}>
          {t("admin.kpi.legendTitle")}
        </h3>
        <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
          <li>{t("admin.kpi.legendPrimary", { k: kMin })}</li>
          <li>{t("admin.kpi.legendSecondary")}</li>
          <li>{t("admin.kpi.legendSmallCells", { k: kMin })}</li>
          <li>{t("admin.kpi.legendGender")}</li>
          <li>{t("admin.kpi.legendCounts")}</li>
        </ul>
      </section>
    </div>
  );
}
