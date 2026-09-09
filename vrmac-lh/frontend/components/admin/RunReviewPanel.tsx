"use client";
import { useState } from "react";
import { useLang, useT } from "@/lib/i18n";
import { computeKpi, errorMessage, reviewKpiRun } from "./api";
import { fmtDateTime, fmtNumber } from "./format";
import { runIdOf, type KpiRunSummary } from "./types";
import { EmptyState } from "./ui";
import styles from "./admin.module.css";

const BADGE: Record<string, string> = {
  computed: "badge-draft",
  reviewed: "badge-reviewed",
  published: "badge-approved",
  rejected: "badge-rejected",
};

function RunStatusBadge({ status }: { status: string }) {
  const t = useT();
  return <span className={`badge ${BADGE[status] ?? ""}`}>{t(`admin.run.status.${status}`)}</span>;
}

/**
 * The disclosure review: a computed run is a candidate, not a publication. Only a run that a
 * reviewer publishes ever reaches `GET /api/kpi` — and therefore this dashboard.
 */
export default function RunReviewPanel({
  runs,
  publishedRunId,
  onChanged,
}: {
  runs: KpiRunSummary[];
  publishedRunId: string | null;
  onChanged: () => void;
}) {
  const t = useT();
  const { lang } = useLang();
  const [periodDays, setPeriodDays] = useState("365");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function recompute() {
    setError(null);
    setMessage(null);
    setBusy("compute");
    try {
      const run = await computeKpi(Number(periodDays) || undefined);
      setMessage(t("admin.run.computed", { id: runIdOf(run).slice(0, 8) || "—" }));
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function review(runId: string, decision: "publish" | "reject") {
    setError(null);
    setMessage(null);
    const note = (notes[runId] ?? "").trim();
    if (decision === "reject" && note === "") {
      setError(t("admin.run.noteRequired"));
      return;
    }
    setBusy(runId);
    try {
      await reviewKpiRun(runId, decision, note);
      setMessage(decision === "publish" ? t("admin.run.published") : t("admin.run.rejected"));
      setNotes((prev) => ({ ...prev, [runId]: "" }));
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <div className="alert alert-warn" role="note">
        {t("admin.run.gateExplainer")}
      </div>

      <div className={styles.toolbar}>
        <label className="field">
          <span>{t("admin.run.periodDays")}</span>
          <input value={periodDays} onChange={(e) => setPeriodDays(e.target.value)} inputMode="numeric" />
        </label>
        <button type="button" className="btn btn-primary" onClick={recompute} disabled={busy !== null}>
          {busy === "compute" ? t("admin.run.computing") : t("admin.run.recompute")}
        </button>
      </div>

      <p role="status" aria-live="polite" className={message ? "alert alert-ok" : "visually-hidden"}>
        {message ?? ""}
      </p>
      {error && (
        <p className="alert alert-danger" role="alert">
          {error}
        </p>
      )}

      {runs.length === 0 ? (
        <EmptyState title={t("admin.run.emptyTitle")} body={t("admin.run.emptyBody")} />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">{t("admin.run.caption")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("admin.run.colComputed")}</th>
                <th scope="col">{t("admin.run.colPeriod")}</th>
                <th scope="col">{t("admin.run.colStatus")}</th>
                <th scope="col">{t("admin.run.colRows")}</th>
                <th scope="col">{t("admin.run.colDefinitions")}</th>
                <th scope="col">{t("admin.run.colReview")}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const id = runIdOf(run);
                const decided = run.status === "published" || run.status === "rejected";
                return (
                  <tr key={id || run.computed_at || Math.random()}>
                    <th scope="row" className="small" style={{ fontWeight: 400 }}>
                      {fmtDateTime(lang, run.computed_at)}
                      <br />
                      <span className={`${styles.mono} muted`}>{id.slice(0, 8)}</span>
                      {id && id === publishedRunId && (
                        <>
                          {" "}
                          <span className="badge badge-approved">{t("admin.run.live")}</span>
                        </>
                      )}
                    </th>
                    <td className="small">
                      {fmtDateTime(lang, run.period_start)}
                      <br />
                      {fmtDateTime(lang, run.period_end)}
                    </td>
                    <td>
                      <RunStatusBadge status={String(run.status)} />
                    </td>
                    <td className="small">
                      {t("admin.run.rowsCount", {
                        rows: fmtNumber(lang, run.n_rows ?? null),
                        suppressed: fmtNumber(lang, run.n_suppressed ?? null),
                      })}
                      <br />
                      <span className="muted">{t("admin.run.kMin", { k: fmtNumber(lang, run.k_min ?? null) })}</span>
                    </td>
                    <td className="small">
                      <span className={styles.mono}>{run.definitions_version || "—"}</span>
                      <br />
                      {run.definitions_provisional !== false && (
                        <span className="badge badge-reviewed">{t("admin.kpi.provisionalBadge")}</span>
                      )}
                    </td>
                    <td>
                      {decided ? (
                        <span className="small muted">
                          {t("admin.run.reviewedAt", { when: fmtDateTime(lang, run.reviewed_at ?? null) })}
                          {run.review_note ? ` — ${run.review_note}` : ""}
                        </span>
                      ) : (
                        <div className="stack" style={{ gap: ".4rem", minWidth: "16rem" }}>
                          <label className="field" style={{ margin: 0 }}>
                            <span className="small">{t("admin.run.note")}</span>
                            <input
                              value={notes[id] ?? ""}
                              onChange={(e) => setNotes((p) => ({ ...p, [id]: e.target.value }))}
                              maxLength={2000}
                            />
                          </label>
                          <div className={styles.actions}>
                            <button
                              type="button"
                              className="btn btn-small btn-primary"
                              onClick={() => review(id, "publish")}
                              disabled={busy !== null || !id}
                            >
                              {t("admin.run.publish")}
                            </button>
                            <button
                              type="button"
                              className="btn btn-small btn-danger"
                              onClick={() => review(id, "reject")}
                              disabled={busy !== null || !id}
                            >
                              {t("admin.run.reject")}
                            </button>
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">{t("admin.run.checklist")}</p>
    </div>
  );
}
