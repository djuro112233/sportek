"use client";
/**
 * Send a request to a provider and follow it through its whole lifecycle.
 *
 * This is **not** a booking system and **not** a payment system: the visitor sends a message, the
 * host answers, and either side can close it. Nothing is reserved, nothing is charged, no contact
 * details are required — the request is tied to the anonymous `session_id` of this browser only.
 */
import { useCallback, useEffect, useState } from "react";
import type { VisitorCtx } from "./context";
import { cancelRequest, errorMessage, getMyRequests, postRequest } from "./api";
import { fmtDate, fmtDateTime, labelOr } from "./format";
import type { VisitorRequest } from "./types";
import styles from "./visitor.module.css";

const OPEN_STATUSES = new Set(["sent", "confirmed"]);

export default function RequestPanel({ ctx, listingId, title }: { ctx: VisitorCtx; listingId: string; title: string }) {
  const { t, lang } = ctx;
  const [message, setMessage] = useState("");
  const [requestedDate, setRequestedDate] = useState("");
  const [partySize, setPartySize] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mine, setMine] = useState<VisitorRequest[] | null>(null);
  const [mineError, setMineError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setMine(await getMyRequests(ctx.sessionId));
      setMineError(null);
    } catch (e) {
      setMineError(errorMessage(e));
    }
  }, [ctx.sessionId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!message.trim()) return;
    setSending(true);
    setError(null);
    try {
      await postRequest({
        listing_id: listingId,
        message: message.trim(),
        requested_date: requestedDate || null,
        party_size: partySize ? Number(partySize) : null,
        session_id: ctx.sessionId,
        device_id: ctx.deviceId,
      });
      setSent(true);
      setMessage("");
      setRequestedDate("");
      setPartySize("");
      ctx.announce(t("visitor.request.sentAnnounce"));
      await reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSending(false);
    }
  };

  const cancel = async (id: string) => {
    try {
      await cancelRequest(id, ctx.sessionId);
      await reload();
      ctx.announce(t("visitor.request.cancelled"));
    } catch (e) {
      setMineError(errorMessage(e));
    }
  };

  return (
    <section aria-labelledby="visitor-request-title">
      <h4 id="visitor-request-title">{t("visitor.request.title", { title })}</h4>
      <p className="alert alert-warn small">{t("visitor.request.noBooking")}</p>

      <form onSubmit={submit}>
        <label className="field">
          <span>{t("visitor.request.message")}</span>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            required
            maxLength={2000}
            placeholder={t("visitor.request.messagePlaceholder")}
          />
        </label>
        <div className={styles.filterRow}>
          <label className="field" style={{ flex: "1 1 10rem" }}>
            <span>{t("visitor.request.date")}</span>
            <input type="date" value={requestedDate} onChange={(e) => setRequestedDate(e.target.value)} />
          </label>
          <label className="field" style={{ flex: "1 1 8rem" }}>
            <span>{t("visitor.request.party")}</span>
            <input
              type="number"
              min={1}
              max={99}
              value={partySize}
              onChange={(e) => setPartySize(e.target.value)}
              inputMode="numeric"
            />
          </label>
        </div>
        <p className={styles.note}>{t("visitor.request.privacy")}</p>
        <button type="submit" className="btn btn-primary" disabled={sending || !message.trim()}>
          {sending ? t("visitor.request.sending") : t("visitor.request.send")}
        </button>
      </form>

      {sent ? (
        <p className="alert alert-ok small" role="status">
          {t("visitor.request.sentHelp")}
        </p>
      ) : null}
      {error ? (
        <p className="alert alert-danger small" role="alert">
          {t("common.error", { message: error })}
        </p>
      ) : null}

      <h4>{t("visitor.request.mine")}</h4>
      <p className={styles.note}>{t("visitor.request.mineHelp")}</p>
      {mineError ? (
        <p className="alert alert-warn small" role="status">
          {t("common.error", { message: mineError })}
        </p>
      ) : null}
      {mine === null ? (
        <p className="muted" role="status">
          {t("common.loading")}
        </p>
      ) : mine.length === 0 ? (
        <p className="muted">{t("visitor.request.mineEmpty")}</p>
      ) : (
        <ul className={`${styles.stops} ${styles.scroll}`}>
          {mine.map((r) => (
            <li key={r.id} className={styles.requestCard}>
              <p style={{ margin: 0 }}>
                <strong>{r.listing_title_local || r.listing_title_en || r.listing_id}</strong>{" "}
                <span className={`badge badge-${r.status === "confirmed" || r.status === "completed" ? "approved" : r.status === "refused" || r.status === "expired" ? "rejected" : "draft"}`}>
                  {labelOr(t, `visitor.request.status.${r.status}`, r.status)}
                </span>
              </p>
              <p className="small muted" style={{ margin: 0 }}>
                {t("visitor.request.sentOn")}: {fmtDateTime(lang, r.created_at)}
                {r.requested_date ? ` · ${t("visitor.request.date")}: ${fmtDate(lang, r.requested_date)}` : ""}
                {r.party_size ? ` · ${t("visitor.request.party")}: ${r.party_size}` : ""}
                {r.expires_at ? ` · ${t("visitor.request.expires")}: ${fmtDateTime(lang, r.expires_at)}` : ""}
              </p>
              <p className="small" style={{ margin: ".25rem 0 0" }}>
                {r.message}
              </p>
              {r.host_reply ? (
                <p className="cite small" style={{ margin: ".25rem 0 0" }}>
                  {t("visitor.request.hostReply")}: {r.host_reply}
                </p>
              ) : null}
              <p className="small muted" style={{ margin: ".25rem 0 0" }}>
                {labelOr(t, `visitor.request.statusHelp.${r.status}`, "")}
              </p>
              {OPEN_STATUSES.has(String(r.status)) ? (
                <button type="button" className="btn btn-danger btn-small" onClick={() => void cancel(r.id)}>
                  {t("visitor.request.cancel")}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
