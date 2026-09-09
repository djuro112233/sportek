"use client";
/**
 * Visitor requests for the host's own listings.
 *
 * A request is a **message**, never a booking: the host answers it (confirm or refuse, always with
 * a written reply) and later records how it ended (completed or cancelled). No payment is taken
 * anywhere in this prototype, so nothing here talks about money.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import HostShell from "@/components/host/HostShell";
import styles from "@/components/host/host.module.css";
import { closeRequest, getHostRequests, respondToRequest } from "@/components/host/hostApi";
import type { ClosePayload, HostRequest, RespondPayload } from "@/components/host/types";
import { OPEN_REQUEST_STATUSES } from "@/components/host/types";
import { describeError, formatDate } from "@/components/host/utils";
import { type Lang, useLang, useT } from "@/lib/i18n";

const KNOWN_STATUSES = ["sent", "confirmed", "completed", "cancelled", "refused", "expired"];

function isOpen(r: HostRequest): boolean {
  return (OPEN_REQUEST_STATUSES as string[]).includes(r.status);
}

function listingTitle(lang: Lang, r: HostRequest, fallback: string): string {
  const local = r.listing_title_local || r.listing?.title_local || "";
  const en = r.listing_title_en || r.listing?.title_en || "";
  return (lang === "cnr" ? local || en : en || local) || fallback;
}

function RequestStatusBadge({ status }: { status: string }) {
  const t = useT();
  const known = KNOWN_STATUSES.includes(status);
  return <span className="badge">{known ? t(`host.request.status.${status}`) : status}</span>;
}

function HostRequests() {
  const t = useT();
  const { lang } = useLang();
  const [rows, setRows] = useState<HostRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [replies, setReplies] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await getHostRequests());
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
    // The list is fetched once; a language switch re-renders the labels, not the data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function replace(updated: HostRequest) {
    setRows((current) => current.map((row) => (row.id === updated.id ? updated : row)));
  }

  async function respond(r: HostRequest, decision: RespondPayload["status"]) {
    const reply = (replies[r.id] ?? "").trim();
    if (!reply) {
      setError(t("host.request.replyRequired"));
      return;
    }
    setBusyId(r.id);
    setError(null);
    try {
      replace(await respondToRequest(r.id, { status: decision, reply }));
      setReplies((current) => ({ ...current, [r.id]: "" }));
      setStatus(decision === "confirmed" ? t("host.request.confirmed") : t("host.request.refused"));
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusyId(null);
    }
  }

  async function close(r: HostRequest, outcome: ClosePayload["status"]) {
    setBusyId(r.id);
    setError(null);
    try {
      replace(await closeRequest(r.id, { status: outcome, note: (notes[r.id] ?? "").trim() }));
      setNotes((current) => ({ ...current, [r.id]: "" }));
      setStatus(outcome === "completed" ? t("host.request.completed") : t("host.request.cancelled"));
    } catch (e) {
      setError(describeError(e, t));
    } finally {
      setBusyId(null);
    }
  }

  const open = useMemo(() => rows.filter(isOpen), [rows]);
  const closed = useMemo(() => rows.filter((r) => !isOpen(r)), [rows]);

  const card = (r: HostRequest) => {
    const busy = busyId === r.id;
    return (
      <article key={r.id} className="card">
        <div className={styles.cardHead}>
          <h3>{listingTitle(lang, r, t("host.request.untitledListing"))}</h3>
          <RequestStatusBadge status={r.status} />
        </div>
        <dl className={styles.facts}>
          <dt>{t("host.request.received")}</dt>
          <dd>{formatDate(lang, r.created_at, true)}</dd>
          <dt>{t("host.request.date")}</dt>
          <dd>{r.requested_date ? formatDate(lang, r.requested_date) : t("host.value.notGiven")}</dd>
          <dt>{t("host.request.party")}</dt>
          <dd>{r.party_size ?? t("host.value.notGiven")}</dd>
          {r.responded_at ? (
            <>
              <dt>{t("host.request.respondedAt")}</dt>
              <dd>{formatDate(lang, r.responded_at, true)}</dd>
            </>
          ) : null}
          {r.closed_at ? (
            <>
              <dt>{t("host.request.closedAt")}</dt>
              <dd>{formatDate(lang, r.closed_at, true)}</dd>
            </>
          ) : null}
          {r.expires_at && isOpen(r) ? (
            <>
              <dt>{t("host.request.expires")}</dt>
              <dd>{formatDate(lang, r.expires_at, true)}</dd>
            </>
          ) : null}
        </dl>

        <div className={styles.langBlock}>
          <h4>{t("host.request.message")}</h4>
          <p>{r.message || t("host.value.notGiven")}</p>
        </div>

        {r.host_reply ? (
          <div className={styles.langBlock}>
            <h4>{t("host.request.yourReply")}</h4>
            <p>{r.host_reply}</p>
          </div>
        ) : null}

        {r.status === "sent" ? (
          <form
            className={styles.replyRow}
            onSubmit={(e) => {
              e.preventDefault();
              void respond(r, "confirmed");
            }}
          >
            <label className="field" htmlFor={`reply-${r.id}`}>
              <span>{t("host.request.replyLabel")}</span>
              <textarea
                id={`reply-${r.id}`}
                rows={3}
                value={replies[r.id] ?? ""}
                onChange={(e) => setReplies((current) => ({ ...current, [r.id]: e.target.value }))}
                aria-describedby={`reply-hint-${r.id}`}
              />
            </label>
            <p className={styles.hint} id={`reply-hint-${r.id}`}>
              {t("host.request.replyHint")}
            </p>
            <div className={styles.actions}>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? t("host.request.sending") : t("host.request.confirm")}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy}
                onClick={() => void respond(r, "refused")}
              >
                {t("host.request.refuse")}
              </button>
            </div>
          </form>
        ) : null}

        {r.status === "confirmed" ? (
          <form
            className={styles.replyRow}
            onSubmit={(e) => {
              e.preventDefault();
              void close(r, "completed");
            }}
          >
            <label className="field" htmlFor={`note-${r.id}`}>
              <span>{t("host.request.noteLabel")}</span>
              <textarea
                id={`note-${r.id}`}
                rows={2}
                value={notes[r.id] ?? ""}
                onChange={(e) => setNotes((current) => ({ ...current, [r.id]: e.target.value }))}
                aria-describedby={`note-hint-${r.id}`}
              />
            </label>
            <p className={styles.hint} id={`note-hint-${r.id}`}>
              {t("host.request.noteHint")}
            </p>
            <div className={styles.actions}>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? t("host.request.sending") : t("host.request.complete")}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy}
                onClick={() => void close(r, "cancelled")}
              >
                {t("host.request.cancel")}
              </button>
            </div>
          </form>
        ) : null}
      </article>
    );
  };

  return (
    <section aria-labelledby="requests-heading">
      <h2 id="requests-heading">{t("host.requests.heading")}</h2>
      <p>{t("host.requests.intro")}</p>
      <p className="alert alert-warn" role="note">
        {t("host.requests.noBookings")}
      </p>

      <div className="row">
        <button type="button" className="btn btn-secondary" onClick={() => void load()} disabled={loading}>
          {t("host.requests.refresh")}
        </button>
        <span role="status" aria-live="polite" className="small">
          {loading ? t("common.loading") : status}
        </span>
      </div>

      {error ? (
        <p className="alert alert-danger" role="alert">
          {error}
        </p>
      ) : null}

      {!loading && rows.length === 0 ? <p className="card">{t("host.requests.empty")}</p> : null}

      {open.length > 0 ? (
        <>
          <h3>{t("host.requests.open", { count: open.length })}</h3>
          <div className={styles.cards}>{open.map(card)}</div>
        </>
      ) : null}

      {closed.length > 0 ? (
        <>
          <h3>{t("host.requests.closed", { count: closed.length })}</h3>
          <div className={styles.cards}>{closed.map(card)}</div>
        </>
      ) : null}
    </section>
  );
}

export default function HostRequestsPage() {
  return <HostShell>{() => <HostRequests />}</HostShell>;
}
