"use client";
import { useT } from "@/lib/i18n";
import { errorMessage } from "./api";
import type { Status } from "./types";
import styles from "./admin.module.css";

/** Validation status as a coloured badge (colour is never the only carrier — the word is there too). */
export function StatusBadge({ status }: { status: Status | string }) {
  const t = useT();
  const known = ["draft", "reviewed", "approved", "rejected"].includes(status);
  return <span className={`badge ${known ? `badge-${status}` : ""}`}>{known ? t(`admin.status.${status}`) : status}</span>;
}

/** The "unverified facts" flag of the queue and the item view. */
export function UnverifiedFlag({ verified }: { verified: boolean }) {
  const t = useT();
  if (verified) return <span className="muted small">{t("admin.flag.verified")}</span>;
  return (
    <strong className="badge badge-rejected" title={t("admin.flag.unverifiedHelp")}>
      {t("admin.flag.unverified")}
    </strong>
  );
}

export function Loading({ what }: { what?: string }) {
  const t = useT();
  return (
    <p className="muted" role="status" aria-live="polite">
      {what ? t("admin.common.loadingWhat", { what }) : t("admin.common.loading")}
    </p>
  );
}

/** An API failure. 401/403/409 keep their status code so the reason stays honest. */
export function ErrorAlert({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const t = useT();
  if (!error) return null;
  return (
    <div className="alert alert-danger" role="alert">
      <p style={{ margin: 0 }}>{t("admin.common.errorPrefix", { message: errorMessage(error) })}</p>
      {onRetry && (
        <p style={{ margin: ".5rem 0 0" }}>
          <button type="button" className="btn btn-small btn-secondary" onClick={onRetry}>
            {t("admin.common.retry")}
          </button>
        </p>
      )}
    </div>
  );
}

export function EmptyState({ title, body }: { title: string; body?: string }) {
  return (
    <div className="card" role="note">
      <p style={{ margin: 0, fontWeight: 600 }}>{title}</p>
      {body && <p className="muted small" style={{ margin: ".35rem 0 0" }}>{body}</p>}
    </div>
  );
}

/** A short-lived confirmation, announced to assistive technology. */
export function LiveMessage({ message }: { message: string | null }) {
  return (
    <p className={message ? "alert alert-ok" : "visually-hidden"} role="status" aria-live="polite">
      {message ?? ""}
    </p>
  );
}

export function YesNo({ value }: { value: boolean | null | undefined }) {
  const t = useT();
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return <span className={value ? styles.ok : styles.bad}>{value ? t("admin.common.yes") : t("admin.common.no")}</span>;
}

/** A section of a long screen: heading + optional lead paragraph, addressable by id. */
export function Section({
  id,
  title,
  lead,
  children,
}: {
  id?: string;
  title: string;
  lead?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="card stack" aria-labelledby={id ? `${id}-h` : undefined}>
      <div>
        <h2 id={id ? `${id}-h` : undefined} style={{ marginTop: 0, marginBottom: lead ? ".25rem" : 0 }}>
          {title}
        </h2>
        {lead && <p className="muted small" style={{ margin: 0 }}>{lead}</p>}
      </div>
      {children}
    </section>
  );
}
