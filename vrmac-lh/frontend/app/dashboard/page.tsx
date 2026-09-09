"use client";
import dynamic from "next/dynamic";
import { useCallback } from "react";
import AuthGate from "@/components/AuthGate";
import { AdminProvider } from "@/components/admin/AdminContext";
import AdminShell, { type AdminTab } from "@/components/admin/AdminShell";
import KpiTable from "@/components/admin/KpiTable";
import RunReviewPanel from "@/components/admin/RunReviewPanel";
import {
  getHeatmap,
  getKpi,
  getKpiDefinitions,
  getKpiRuns,
  getQuality,
  getTimingLog,
  getVillages,
  optional,
} from "@/components/admin/api";
import { fmtDateTime, fmtEuro, fmtMinutes, fmtNumber, fmtPercent, label, median } from "@/components/admin/format";
import { EmptyState, ErrorAlert, Loading, Section, YesNo } from "@/components/admin/ui";
import { useAsync } from "@/components/admin/useAsync";
import {
  heatDevices,
  type HeatmapCollection,
  type KpiDefinitionsFile,
  type QualityMetrics,
  type TimingRow,
  type Village,
} from "@/components/admin/types";
import { getMeta } from "@/lib/api";
import { useLang, useT } from "@/lib/i18n";
import styles from "@/components/admin/admin.module.css";

/** MapLibre needs a DOM and a WebGL context, so the canvas is client-only. */
const HeatMapCanvas = dynamic(() => import("@/components/admin/HeatMapCanvas"), {
  ssr: false,
  loading: () => <div className="map" aria-hidden="true" />,
});

const EMPTY_HEAT: HeatmapCollection = { type: "FeatureCollection", features: [] };

/** One degree of latitude ≈ 111.32 km — enough to say how wide a grid cell is, in words. */
const METRES_PER_DEGREE = 111_320;

/* ================================================================================================
 * heat map
 * ============================================================================================== */

function HeatSection({ data, kMin }: { data: HeatmapCollection; kMin: number }) {
  const t = useT();
  const { lang } = useLang();

  const cells = data.features;
  const visits = cells.reduce((acc, f) => acc + Number(f.properties?.n_visits ?? 0), 0);
  const maxVisits = cells.reduce((acc, f) => Math.max(acc, Number(f.properties?.n_visits ?? 0)), 0);
  const devices = cells.reduce((acc, f) => acc + (heatDevices(f.properties) ?? 0), 0);
  const sizeDeg = cells.find((f) => typeof f.properties?.cell_size_deg === "number")?.properties?.cell_size_deg ?? null;
  const sizeM = sizeDeg === null ? null : Math.round(sizeDeg * METRES_PER_DEGREE);

  return (
    <div className="stack">
      <p style={{ margin: 0 }}>{t("admin.heat.cellRule", { k: fmtNumber(lang, kMin) })}</p>

      {cells.length === 0 ? (
        <EmptyState title={t("admin.heat.emptyTitle")} body={t("admin.heat.emptyBody", { k: fmtNumber(lang, kMin) })} />
      ) : (
        <>
          <dl className={`${styles.headerGrid} ${styles.kv}`}>
            <div>
              <dt>{t("admin.heat.cells")}</dt>
              <dd>{fmtNumber(lang, cells.length)}</dd>
            </div>
            <div>
              <dt>{t("admin.heat.visits")}</dt>
              <dd>{fmtNumber(lang, visits)}</dd>
            </div>
            <div>
              <dt>{t("admin.heat.busiest")}</dt>
              <dd>{fmtNumber(lang, maxVisits)}</dd>
            </div>
            <div>
              <dt>{t("admin.heat.devices")}</dt>
              <dd>{devices > 0 ? fmtNumber(lang, devices) : "—"}</dd>
            </div>
            <div>
              <dt>{t("admin.heat.cellSize")}</dt>
              <dd>{sizeM === null ? t("admin.heat.cellSizeDefault") : t("admin.heat.cellSizeValue", { m: fmtNumber(lang, sizeM) })}</dd>
            </div>
          </dl>

          <div className={styles.mapWrap}>
            <HeatMapCanvas data={data} ariaLabel={t("admin.heat.ariaLabel", { count: fmtNumber(lang, cells.length) })} />
          </div>
        </>
      )}

      <section aria-labelledby="heat-legend">
        <h3 id="heat-legend" style={{ marginBottom: ".3rem" }}>
          {t("admin.heat.legendTitle")}
        </h3>
        <ul className={styles.legend}>
          <li>
            <span className={styles.swatch} style={{ background: "#e4efe8" }} aria-hidden="true" />
            {t("admin.heat.legendLow")}
          </li>
          <li>
            <span className={styles.swatch} style={{ background: "#2f6b4f" }} aria-hidden="true" />
            {t("admin.heat.legendHigh")}
          </li>
        </ul>
        <ul className="small" style={{ margin: ".5rem 0 0", paddingLeft: "1.1rem" }}>
          <li>{t("admin.heat.legendHidden", { k: fmtNumber(lang, kMin) })}</li>
          <li>{t("admin.heat.legendAggregate")}</li>
          <li>{t("admin.heat.legendNoTracks")}</li>
        </ul>
      </section>
    </div>
  );
}

/* ================================================================================================
 * internal quality metrics
 * ============================================================================================== */

/** Fields the backend sends that the shared read model does not name (`synthetic_samples`, `available`). */
interface WerExtras {
  available?: boolean;
  synthetic_samples?: boolean | null;
  worst_wer?: number | null;
  n_reference_words?: number;
  note?: string;
}

function QualitySection({ quality }: { quality: QualityMetrics | null }) {
  const t = useT();
  const { lang } = useLang();

  const wer = quality?.stt_wer ?? null;
  const extras = (wer ?? {}) as WerExtras;
  const measured = wer !== null && extras.available !== false && (wer.n_samples ?? 0) > 0;
  /** Only an explicit `false` from the backend means consented recordings replaced the stand-ins. */
  const synthetic = wer?.is_synthetic !== false && extras.synthetic_samples !== false;
  const cache = quality?.cache ?? null;
  const budget = quality?.budget ?? null;

  return (
    <div className="stack">
      <p className="muted small" style={{ margin: 0 }}>
        {t("admin.quality.notKpi")}
      </p>

      <section aria-labelledby="quality-stt" className="stack" style={{ gap: ".5rem" }}>
        <h3 id="quality-stt" style={{ margin: 0 }}>
          {t("admin.quality.sttTitle")}
        </h3>
        {synthetic && (
          <div className="alert alert-warn" role="note">
            {t("admin.quality.sttSynthetic")}
          </div>
        )}
        {!measured ? (
          <p className="muted" style={{ margin: 0 }}>
            {t("admin.quality.sttNone")}
          </p>
        ) : (
          <dl className={styles.dl}>
            <dt>{t("admin.quality.meanWer")}</dt>
            <dd>{fmtPercent(lang, wer?.mean_wer ?? null)}</dd>
            <dt>{t("admin.quality.medianWer")}</dt>
            <dd>{fmtPercent(lang, wer?.median_wer ?? null)}</dd>
            <dt>{t("admin.quality.worstWer")}</dt>
            <dd>{fmtPercent(lang, extras.worst_wer ?? null)}</dd>
            <dt>{t("admin.quality.samples")}</dt>
            <dd>
              {t("admin.quality.samplesValue", {
                n: fmtNumber(lang, wer?.n_samples ?? null),
                kind: synthetic ? t("admin.quality.samplesSynthetic") : t("admin.quality.samplesConsented"),
              })}
            </dd>
            <dt>{t("admin.quality.recogniser")}</dt>
            <dd className={styles.mono}>
              {wer?.provider || "—"}
              {wer?.model ? ` · ${wer.model}` : ""}
            </dd>
            <dt>{t("admin.quality.evaluatedAt")}</dt>
            <dd>{fmtDateTime(lang, wer?.evaluated_at ?? null)}</dd>
          </dl>
        )}
        <p className="muted small" style={{ margin: 0 }}>
          {t("admin.quality.sttHow")}
        </p>
      </section>

      <section aria-labelledby="quality-cache" className="stack" style={{ gap: ".5rem" }}>
        <h3 id="quality-cache" style={{ margin: 0 }}>
          {t("admin.quality.cacheTitle")}
        </h3>
        {cache === null ? (
          <p className="muted" style={{ margin: 0 }}>
            {t("admin.quality.unavailable")}
          </p>
        ) : (
          <dl className={styles.dl}>
            <dt>{t("admin.quality.cacheEntries")}</dt>
            <dd>{fmtNumber(lang, cache.entries ?? null)}</dd>
            <dt>{t("admin.quality.cacheHits")}</dt>
            <dd>{fmtNumber(lang, cache.hits ?? null)}</dd>
            <dt>{t("admin.quality.cacheHitRate")}</dt>
            <dd>{fmtPercent(lang, cache.hit_rate ?? null)}</dd>
            <dt>{t("admin.quality.cacheInvalidated")}</dt>
            <dd>{fmtNumber(lang, cache.invalidated ?? null)}</dd>
          </dl>
        )}
      </section>

      <section aria-labelledby="quality-budget" className="stack" style={{ gap: ".5rem" }}>
        <h3 id="quality-budget" style={{ margin: 0 }}>
          {t("admin.quality.budgetTitle")}
        </h3>
        {budget === null ? (
          <p className="muted" style={{ margin: 0 }}>
            {t("admin.quality.unavailable")}
          </p>
        ) : (
          <dl className={styles.dl}>
            <dt>{t("admin.quality.budgetMonth")}</dt>
            <dd className={styles.mono}>{budget.month || "—"}</dd>
            <dt>{t("admin.quality.budgetCap")}</dt>
            <dd>{fmtEuro(lang, budget.cap_eur ?? null)}</dd>
            <dt>{t("admin.quality.budgetSpent")}</dt>
            <dd>{fmtEuro(lang, budget.spent_eur ?? null)}</dd>
            <dt>{t("admin.quality.budgetRemaining")}</dt>
            <dd>{fmtEuro(lang, budget.remaining_eur ?? null)}</dd>
            <dt>{t("admin.quality.budgetCapReached")}</dt>
            <dd>
              <YesNo value={budget.cap_reached ?? null} />
            </dd>
            <dt>{t("admin.quality.budgetProvider")}</dt>
            <dd>
              <span className={styles.mono}>{budget.provider_name || budget.provider || "—"}</span>
              {budget.billable === false && <span className="muted small"> — {t("admin.quality.budgetNotBillable")}</span>}
            </dd>
          </dl>
        )}
      </section>
    </div>
  );
}

/* ================================================================================================
 * onboarding timing: ACTIVE authoring time and elapsed time, never mixed
 * ============================================================================================== */

function TimingSection({ rows, targetMinutes }: { rows: TimingRow[]; targetMinutes: number }) {
  const t = useT();
  const { lang } = useLang();

  const medianActive = median(rows.map((r) => r.active_seconds).filter((s) => typeof s === "number"));
  const withinKnown = rows.filter((r) => r.within_active_target !== null);
  const withinTarget = withinKnown.filter((r) => r.within_active_target === true).length;

  return (
    <div className="stack">
      <div className="alert alert-warn" role="note">
        <p style={{ margin: 0 }}>{t("admin.timing.targetRule", { minutes: fmtNumber(lang, targetMinutes) })}</p>
        <p style={{ margin: ".4rem 0 0" }}>{t("admin.timing.columnsRule")}</p>
      </div>

      {rows.length === 0 ? (
        <EmptyState title={t("admin.timing.emptyTitle")} body={t("admin.timing.emptyBody")} />
      ) : (
        <>
          <dl className={`${styles.headerGrid} ${styles.kv}`}>
            <div>
              <dt>{t("admin.timing.sessions")}</dt>
              <dd>{fmtNumber(lang, rows.length)}</dd>
            </div>
            <div>
              <dt>{t("admin.timing.medianActive")}</dt>
              <dd>{t("admin.timing.minutesValue", { minutes: fmtMinutes(lang, medianActive) })}</dd>
            </div>
            <div>
              <dt>{t("admin.timing.withinTargetCount")}</dt>
              <dd>
                {withinKnown.length === 0
                  ? "—"
                  : t("admin.timing.withinTargetValue", {
                      n: fmtNumber(lang, withinTarget),
                      total: fmtNumber(lang, withinKnown.length),
                    })}
              </dd>
            </div>
          </dl>

          <div className="table-wrap">
            <table className="table">
              <caption>{t("admin.timing.caption", { minutes: fmtNumber(lang, targetMinutes) })}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("admin.timing.colSession")}</th>
                  <th scope="col">{t("admin.timing.colStarted")}</th>
                  <th scope="col">
                    {t("admin.timing.colActive")}
                    <br />
                    <span className="muted small">{t("admin.timing.colActiveHelp")}</span>
                  </th>
                  <th scope="col">
                    {t("admin.timing.colElapsedConfirm")}
                    <br />
                    <span className="muted small">{t("admin.timing.colElapsedHelp")}</span>
                  </th>
                  <th scope="col">
                    {t("admin.timing.colElapsedPublish")}
                    <br />
                    <span className="muted small">{t("admin.timing.colElapsedHelp")}</span>
                  </th>
                  <th scope="col">{t("admin.timing.colWithinTarget")}</th>
                  <th scope="col">{t("admin.timing.colOffline")}</th>
                  <th scope="col">{t("admin.timing.colProviders")}</th>
                  <th scope="col">{t("admin.timing.colStatus")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.session_id}>
                    <th scope="row" className={`${styles.mono} small`} style={{ fontWeight: 400 }}>
                      {r.session_id.slice(0, 8)}
                    </th>
                    <td className="small">{fmtDateTime(lang, r.started_at)}</td>
                    <td className={styles.num}>
                      <strong>{fmtMinutes(lang, r.active_seconds)}</strong>
                    </td>
                    <td className={styles.num}>{fmtMinutes(lang, r.elapsed_to_confirm_seconds)}</td>
                    <td className={styles.num}>{fmtMinutes(lang, r.elapsed_to_publish_seconds)}</td>
                    <td>
                      {r.within_active_target === null ? (
                        <span className="muted small">{t("admin.timing.withinUnknown")}</span>
                      ) : (
                        <span className={`badge ${r.within_active_target ? "badge-approved" : "badge-rejected"}`}>
                          {r.within_active_target ? t("admin.timing.withinYes") : t("admin.timing.withinNo")}
                        </span>
                      )}
                    </td>
                    <td>
                      <YesNo value={r.offline_captured ?? null} />
                    </td>
                    <td className={`${styles.mono} small`}>
                      {r.stt_provider || "—"}
                      <br />
                      {r.llm_provider || "—"}
                    </td>
                    <td className="small">{label(t, `admin.timing.status.${r.status}`, r.status || "—")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="muted small" style={{ margin: 0 }}>
        {t("admin.timing.footnote")}
      </p>
    </div>
  );
}

/* ================================================================================================
 * the dashboard itself
 * ============================================================================================== */

function Dashboard() {
  const t = useT();
  const { lang } = useLang();

  const metaQ = useAsync(() => optional(getMeta()), []);
  const kpiQ = useAsync(() => getKpi(), []);
  const defsQ = useAsync<KpiDefinitionsFile | null>(() => optional(getKpiDefinitions()), []);
  const runsQ = useAsync(() => getKpiRuns(), []);
  const heatQ = useAsync(() => optional(getHeatmap()), []);
  const qualityQ = useAsync(() => optional(getQuality()), []);
  const timingQ = useAsync(() => optional(getTimingLog()), []);
  const villagesQ = useAsync<Village[]>(() => getVillages(), []);

  const reloadPublished = useCallback(() => {
    kpiQ.reload();
    runsQ.reload();
    heatQ.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kpiQ.reload, runsQ.reload, heatQ.reload]);

  const kpi = kpiQ.data;
  const defs = defsQ.data;
  const runs = runsQ.data ?? [];
  const published = Boolean(kpi?.run_id);
  const kMin = kpi?.k_min ?? metaQ.data?.kpi_k_min ?? 5;
  const targetMinutes = metaQ.data?.onboarding_target_minutes ?? 30;
  const definitionsVersion = kpi?.definitions_version || defs?.version || "—";
  /** Provisional unless the published run *and* the definition file both say otherwise. */
  const provisional = (kpi?.definitions_provisional ?? true) || (defs?.kpis.some((d) => d.provisional) ?? false);

  return (
    <div className="stack">
      <section>
        <h1>{t("admin.dash.title")}</h1>
        <p className="muted">{t("admin.dash.lead")}</p>
      </section>

      {provisional && (
        <div className="alert alert-warn" role="alert">
          <p style={{ margin: 0, fontWeight: 700 }}>{t("admin.dash.provisionalTitle")}</p>
          <p style={{ margin: ".4rem 0 0" }}>{t("admin.dash.provisionalBody")}</p>
          <p style={{ margin: ".4rem 0 0" }}>{t("admin.dash.provisionalVersion", { version: definitionsVersion })}</p>
          {defs?.warning && (
            <details style={{ marginTop: ".4rem" }}>
              <summary className="small">{t("admin.dash.provisionalSource")}</summary>
              <p className="small" style={{ margin: ".35rem 0 0" }} lang="en">
                {defs.warning}
              </p>
            </details>
          )}
        </div>
      )}

      <div className="alert alert-ok" role="note">
        <p style={{ margin: 0, fontWeight: 600 }}>{t("admin.dash.gateTitle")}</p>
        <p style={{ margin: ".4rem 0 0" }}>{t("admin.dash.gateBody")}</p>
      </div>

      <div className="row">
        <button type="button" className="btn btn-small btn-secondary" onClick={reloadPublished}>
          {t("admin.common.refresh")}
        </button>
        <span role="status" aria-live="polite" className="muted small">
          {kpiQ.loading
            ? t("admin.common.loading")
            : published
              ? t("admin.dash.publishedStatus", { when: fmtDateTime(lang, kpi?.computed_at ?? null) })
              : t("admin.dash.noPublishedStatus")}
        </span>
      </div>

      <ErrorAlert error={kpiQ.error} onRetry={kpiQ.reload} />

      {published && (
        <section className="card">
          <h2 style={{ marginTop: 0 }}>{t("admin.dash.runTitle")}</h2>
          <dl className={`${styles.headerGrid} ${styles.kv}`}>
            <div>
              <dt>{t("admin.dash.runId")}</dt>
              <dd className={styles.mono}>{(kpi?.run_id ?? "").slice(0, 8) || "—"}</dd>
            </div>
            <div>
              <dt>{t("admin.dash.computedAt")}</dt>
              <dd>{fmtDateTime(lang, kpi?.computed_at ?? null)}</dd>
            </div>
            <div>
              <dt>{t("admin.dash.period")}</dt>
              <dd>
                {t("admin.dash.periodRange", {
                  from: fmtDateTime(lang, kpi?.period_start ?? null),
                  to: fmtDateTime(lang, kpi?.period_end ?? null),
                })}
              </dd>
            </div>
            <div>
              <dt>{t("admin.dash.definitionsVersion")}</dt>
              <dd className={styles.mono}>{definitionsVersion}</dd>
            </div>
            <div>
              <dt>{t("admin.dash.kMin")}</dt>
              <dd>{t("admin.dash.kMinValue", { k: fmtNumber(lang, kMin) })}</dd>
            </div>
            <div>
              <dt>{t("admin.dash.rows")}</dt>
              <dd>{fmtNumber(lang, kpi?.rows.length ?? 0)}</dd>
            </div>
          </dl>
        </section>
      )}

      <Section id="kpi" title={t("admin.dash.kpiTitle")} lead={t("admin.dash.kpiLead")}>
        {kpiQ.loading && !kpi && <Loading what={t("admin.dash.kpiWhat")} />}
        {!kpiQ.loading && !published && (
          <EmptyState title={t("admin.dash.noPublishedTitle")} body={t("admin.dash.noPublishedBody")} />
        )}
        {published && (
          <>
            {defsQ.error != null && <p className="muted small">{t("admin.dash.definitionsUnavailable")}</p>}
            {villagesQ.error != null && <p className="muted small">{t("admin.queue.villagesUnavailable")}</p>}
            <KpiTable
              rows={kpi?.rows ?? []}
              definitions={defs?.kpis ?? []}
              kMin={kMin}
              villages={villagesQ.data ?? []}
            />
          </>
        )}
      </Section>

      <Section id="review" title={t("admin.dash.reviewTitle")} lead={t("admin.dash.reviewLead")}>
        {runsQ.loading && runs.length === 0 && <Loading what={t("admin.dash.reviewWhat")} />}
        <ErrorAlert error={runsQ.error} onRetry={runsQ.reload} />
        <RunReviewPanel runs={runs} publishedRunId={kpi?.run_id ?? null} onChanged={reloadPublished} />
      </Section>

      <Section id="heat" title={t("admin.dash.heatTitle")} lead={t("admin.dash.heatLead")}>
        {heatQ.loading && <Loading what={t("admin.dash.heatWhat")} />}
        <ErrorAlert error={heatQ.error} onRetry={heatQ.reload} />
        <HeatSection data={heatQ.data ?? EMPTY_HEAT} kMin={kMin} />
      </Section>

      <Section id="quality" title={t("admin.dash.qualityTitle")} lead={t("admin.dash.qualityLead")}>
        {qualityQ.loading && <Loading what={t("admin.dash.qualityWhat")} />}
        <ErrorAlert error={qualityQ.error} onRetry={qualityQ.reload} />
        <QualitySection quality={qualityQ.data} />
      </Section>

      <Section id="timing" title={t("admin.dash.timingTitle")} lead={t("admin.dash.timingLead")}>
        {timingQ.loading && <Loading what={t("admin.dash.timingWhat")} />}
        <ErrorAlert error={timingQ.error} onRetry={timingQ.reload} />
        <TimingSection rows={timingQ.data ?? []} targetMinutes={targetMinutes} />
      </Section>

      <section className="card">
        <h2 style={{ marginTop: 0 }}>{t("admin.dash.scopeTitle")}</h2>
        <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
          <li>{t("admin.dash.scopePrototype")}</li>
          <li>{t("admin.dash.scopeEvents")}</li>
          <li>{t("admin.dash.scopeGender")}</li>
          <li>{t("admin.dash.scopeSuppression", { k: fmtNumber(lang, kMin) })}</li>
          <li>{t("admin.dash.scopeDefinitions")}</li>
          <li>{t("admin.dash.scopeQuality")}</li>
        </ul>
      </section>
    </div>
  );
}

/**
 * The institution dashboard: the published KPI run (K01–K23), the disclosure review that publishes
 * it, the aggregated heat map, the internal quality metrics and the onboarding timing log.
 * Institutions and validators only; nothing here is a claim about a live service.
 */
export default function DashboardPage() {
  const t = useT();
  return (
    <AuthGate roles={["institution", "validator"]}>
      {(user, signOut) => {
        const tabs: AdminTab[] = [
          { href: "/dashboard", label: t("admin.tab.dashboard"), exact: true },
          ...(user.role === "validator" ? [{ href: "/validate", label: t("admin.tab.queue") }] : []),
        ];
        return (
          <AdminProvider user={user} signOut={signOut}>
            <AdminShell tabs={tabs}>
              <Dashboard />
            </AdminShell>
          </AdminProvider>
        );
      }}
    </AuthGate>
  );
}
