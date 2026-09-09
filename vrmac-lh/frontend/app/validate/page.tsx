"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { pick, useLang, useT } from "@/lib/i18n";
import { getQueue, getVillages } from "@/components/admin/api";
import { fmtDateTime } from "@/components/admin/format";
import { ITEM_TYPES } from "@/components/admin/types";
import { EmptyState, ErrorAlert, Loading, StatusBadge, UnverifiedFlag } from "@/components/admin/ui";
import { useAsync } from "@/components/admin/useAsync";
import { sortedVillages, villageName } from "@/components/admin/villages";
import styles from "@/components/admin/admin.module.css";

/** The validation queue: everything waiting for a decision, with its territory and its provenance. */
export default function QueuePage() {
  const t = useT();
  const { lang } = useLang();
  const [itemType, setItemType] = useState("");
  const [village, setVillage] = useState("");

  const villagesQ = useAsync(() => getVillages(), []);
  const queueQ = useAsync(() => getQueue({ item_type: itemType || undefined, village: village || undefined }), [itemType, village]);

  const villages = useMemo(() => villagesQ.data ?? [], [villagesQ.data]);
  const rows = queueQ.data ?? [];

  return (
    <div className="stack">
      <section>
        <h1>{t("admin.queue.title")}</h1>
        <p className="muted">{t("admin.queue.lead")}</p>
      </section>

      <form className={`card ${styles.toolbar}`} aria-label={t("admin.queue.filters")} onSubmit={(e) => e.preventDefault()}>
        <label className="field">
          <span>{t("admin.queue.filterType")}</span>
          <select value={itemType} onChange={(e) => setItemType(e.target.value)}>
            <option value="">{t("admin.queue.allTypes")}</option>
            {ITEM_TYPES.map((it) => (
              <option key={it} value={it}>
                {t(`admin.itemType.${it}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{t("admin.queue.filterVillage")}</span>
          <select value={village} onChange={(e) => setVillage(e.target.value)} disabled={villages.length === 0}>
            <option value="">{t("admin.queue.allVillages")}</option>
            {sortedVillages(lang, villages).map((v) => (
              <option key={v.id} value={v.slug}>
                {pick(lang, v.name_local, v.name_en)} ({v.municipality})
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn btn-secondary" onClick={() => queueQ.reload()}>
          {t("admin.common.refresh")}
        </button>
      </form>

      <p role="status" aria-live="polite" className="muted small">
        {queueQ.loading ? t("admin.common.loading") : t("admin.queue.count", { count: rows.length })}
      </p>

      <ErrorAlert error={queueQ.error} onRetry={queueQ.reload} />
      {villagesQ.error != null && (
        <p className="muted small">{t("admin.queue.villagesUnavailable")}</p>
      )}

      {queueQ.loading && rows.length === 0 && <Loading />}

      {!queueQ.loading && !queueQ.error && rows.length === 0 && (
        <EmptyState title={t("admin.queue.emptyTitle")} body={t("admin.queue.emptyBody")} />
      )}

      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">{t("admin.queue.caption")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("admin.queue.colType")}</th>
                <th scope="col">{t("admin.queue.colTitle")}</th>
                <th scope="col">{t("admin.queue.colVillage")}</th>
                <th scope="col">{t("admin.queue.colStatus")}</th>
                <th scope="col">{t("admin.queue.colVersion")}</th>
                <th scope="col">{t("admin.queue.colCreated")}</th>
                <th scope="col">{t("admin.queue.colSource")}</th>
                <th scope="col">{t("admin.queue.colFacts")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.item_type}:${r.id}`}>
                  <td>{t(`admin.itemType.${r.item_type}`)}</td>
                  <th scope="row" style={{ fontWeight: 600 }}>
                    <Link href={`/validate/${r.item_type}/${r.id}`}>{r.title || t("admin.queue.untitled")}</Link>
                  </th>
                  <td>
                    {villageName(lang, villages, r.village)}
                    <br />
                    <span className="muted small">{r.municipality || "—"}</span>
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td className={styles.num}>{r.version}</td>
                  <td className="small">{fmtDateTime(lang, r.created_at)}</td>
                  <td className="small">{r.source || "—"}</td>
                  <td>
                    <UnverifiedFlag verified={r.facts_verified !== false} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="muted small">{t("admin.queue.footnote")}</p>
    </div>
  );
}
