"use client";
import { useLang, useT } from "@/lib/i18n";
import { useAdminUser } from "@/components/admin/AdminContext";
import { getAudit } from "@/components/admin/api";
import { fmtDateTime, label } from "@/components/admin/format";
import { EmptyState, ErrorAlert, Loading } from "@/components/admin/ui";
import { useAsync } from "@/components/admin/useAsync";
import styles from "@/components/admin/admin.module.css";

/** The audit log (validators): every write, who did it, on what, with no personal data in `detail`. */
export default function AuditPage() {
  const t = useT();
  const { lang } = useLang();
  const { user } = useAdminUser();
  const isValidator = user.role === "validator";
  const auditQ = useAsync(() => (isValidator ? getAudit() : Promise.resolve([])), [isValidator]);
  const rows = auditQ.data ?? [];

  return (
    <div className="stack">
      <section>
        <h1>{t("admin.audit.title")}</h1>
        <p className="muted">{t("admin.audit.lead")}</p>
      </section>

      {!isValidator && (
        <div className="alert alert-warn" role="note">
          {t("admin.audit.validatorOnly")}
        </div>
      )}

      {isValidator && (
        <>
          <div className="row">
            <button type="button" className="btn btn-small btn-secondary" onClick={auditQ.reload}>
              {t("admin.common.refresh")}
            </button>
            <span role="status" aria-live="polite" className="muted small">
              {auditQ.loading ? t("admin.common.loading") : t("admin.audit.count", { count: rows.length })}
            </span>
          </div>

          <ErrorAlert error={auditQ.error} onRetry={auditQ.reload} />
          {auditQ.loading && rows.length === 0 && <Loading />}

          {!auditQ.loading && !auditQ.error && rows.length === 0 && (
            <EmptyState title={t("admin.audit.emptyTitle")} body={t("admin.audit.emptyBody")} />
          )}

          {rows.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <caption className="visually-hidden">{t("admin.audit.caption")}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t("admin.audit.colWhen")}</th>
                    <th scope="col">{t("admin.audit.colRole")}</th>
                    <th scope="col">{t("admin.audit.colAction")}</th>
                    <th scope="col">{t("admin.audit.colResource")}</th>
                    <th scope="col">{t("admin.audit.colDetail")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id}>
                      <th scope="row" className="small" style={{ fontWeight: 400 }}>
                        {fmtDateTime(lang, r.occurred_at)}
                      </th>
                      <td>{label(t, `admin.role.${r.role}`, r.role)}</td>
                      <td className={styles.mono}>{r.action}</td>
                      <td className="small">
                        {r.resource_type || "—"}
                        <br />
                        <span className={`${styles.mono} muted`}>{r.resource_id || "—"}</span>
                      </td>
                      <td className={`${styles.mono} small`}>
                        {r.detail && Object.keys(r.detail).length > 0 ? JSON.stringify(r.detail) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted small">{t("admin.audit.footnote")}</p>
        </>
      )}
    </div>
  );
}
