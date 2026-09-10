"use client";
/**
 * The visible half of the offline capture queue: what is stored on this device, what state each
 * recording is in, and how to retry or delete one. The status line is a live region, so a screen
 * reader hears "saved on this device" as soon as connectivity drops.
 *
 * A recording the queue has stopped trying — the API will never accept it, the attempts ran out, or
 * the listing was confirmed while it waited — is never silently retried in the background: it is
 * listed with the reason in the host's own language, a "try again" for the ones that could still
 * work, and a delete for all of them.
 */
import { useState } from "react";
import { useLang, useT } from "@/lib/i18n";
import styles from "./host.module.css";
import { useOfflineQueue } from "./offlineQueue";
import type { QueuedRecording } from "./types";
import { formatBytes, formatDate, mmss } from "./utils";

export default function OfflineQueuePanel({ sessionId = null }: { sessionId?: string | null }) {
  const t = useT();
  const { lang } = useLang();
  const { ready, supported, items, pending, blocked, online, busy, error, remove, retry, retryAll } =
    useOfflineQueue();
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const statusText = !supported
    ? t("host.queue.unsupported")
    : !ready
      ? t("common.loading")
      : pending.length === 0
        ? online
          ? t("host.queue.emptyOnline")
          : t("host.queue.emptyOffline")
        : online
          ? t("host.queue.pendingOnline", { count: pending.length })
          : t("host.queue.pendingOffline", { count: pending.length });

  return (
    <section className={styles.queue} aria-labelledby="queue-heading">
      <h3 id="queue-heading">{t("host.queue.heading")}</h3>
      <p className={styles.hint}>{t("host.queue.explain")}</p>
      <p role="status" aria-live="polite">
        <strong>{online ? t("host.queue.online") : t("host.queue.offline")}</strong> — {statusText}
        {busy ? ` — ${t("host.queue.uploading")}` : ""}
      </p>
      {error ? (
        <p className="alert alert-warn small" role="note">
          {error}
        </p>
      ) : null}
      {blocked.length > 0 ? (
        <p className="alert alert-warn small" role="note">
          {t("host.queue.blockedSummary", { count: blocked.length })}
        </p>
      ) : null}
      {items.length > 0 && (
        <>
          <ul className={styles.queueList}>
            {items.map((r) => (
              <li key={r.id} className={styles.queueItem}>
                <div>
                  <div>
                    <strong>{formatDate(lang, r.captured_at, true)}</strong>
                    {r.session_id === sessionId ? ` — ${t("host.queue.thisListing")}` : ""}
                  </div>
                  <div className="small muted">
                    {t("host.queue.meta", {
                      duration: r.duration_s > 0 ? mmss(r.duration_s) : "—",
                      size: formatBytes(lang, r.size),
                      lang: t(`host.lang.${r.language}`),
                    })}
                  </div>
                  <div className="small">
                    {stateSymbol(r)} {t(`host.queue.state.${r.state}`)}
                    {r.attempts > 0 ? ` — ${t("host.queue.attempts", { count: r.attempts })}` : ""}
                    {r.captured_offline ? ` — ${t("host.queue.offlineCapture")}` : ""}
                  </div>
                  {r.last_error ? <div className="small muted">{r.last_error}</div> : null}
                </div>
                <div className="row">
                  {r.state === "rejected" && confirmDelete !== r.id ? (
                    <button
                      type="button"
                      className="btn btn-small btn-secondary"
                      onClick={() => void retry(r.id)}
                      disabled={busy || !online}
                    >
                      {t("host.queue.retryOne")}
                    </button>
                  ) : null}
                  {confirmDelete === r.id ? (
                    <>
                      <span className="small">{t("host.queue.deleteConfirm")}</span>
                      <button
                        type="button"
                        className="btn btn-small btn-danger"
                        onClick={() => {
                          setConfirmDelete(null);
                          void remove(r.id);
                        }}
                      >
                        {t("host.queue.deleteYes")}
                      </button>
                      <button type="button" className="btn btn-small btn-secondary" onClick={() => setConfirmDelete(null)}>
                        {t("common.cancel")}
                      </button>
                    </>
                  ) : (
                    <button type="button" className="btn btn-small btn-danger" onClick={() => setConfirmDelete(r.id)}>
                      {t("host.queue.delete")}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <div className="row" style={{ marginTop: "0.75rem" }}>
            <button type="button" className="btn btn-secondary" onClick={() => void retryAll()} disabled={busy || !online || pending.length === 0}>
              {t("host.queue.retry")}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

/** A symbol next to the word, so state is never signalled by colour alone. */
function stateSymbol(r: QueuedRecording): string {
  switch (r.state) {
    case "uploaded":
      return "✓";
    case "uploading":
      return "↑";
    case "failed":
      return "!";
    case "rejected":
      return "✕";
    case "obsolete":
      return "⊘";
    default:
      return "•";
  }
}
