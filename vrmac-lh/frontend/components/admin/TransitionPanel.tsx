"use client";
import { useId, useRef, useState } from "react";
import { useT } from "@/lib/i18n";
import { errorMessage, postTransition } from "./api";
import { allowedTransitions, type ItemType, type Role, type Status } from "./types";
import { StatusBadge } from "./ui";
import styles from "./admin.module.css";

/**
 * The validation gate as buttons: exactly the transitions `role` may perform from `status`
 * (mirrors `services/validation.TRANSITIONS`). Rejecting requires a note. 403 and 409 answers
 * from the API are shown verbatim — the UI never pretends a refused transition succeeded.
 */
export default function TransitionPanel({
  itemType,
  itemId,
  status,
  role,
  factsVerified,
  onDone,
}: {
  itemType: ItemType | string;
  itemId: string;
  status: Status;
  role: Role;
  factsVerified: boolean | null;
  onDone: (toStatus: Status) => void;
}) {
  const t = useT();
  const noteId = useId();
  const warnId = useId();
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  const targets = allowedTransitions(status, role);
  const blockedApproval = factsVerified === false;

  async function go(to: Status) {
    setError(null);
    if (to === "rejected" && note.trim() === "") {
      setError(t("admin.transition.noteRequired"));
      noteRef.current?.focus();
      return;
    }
    setBusy(to);
    try {
      await postTransition(itemType, itemId, to, note.trim());
      setNote("");
      onDone(to);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <p style={{ margin: 0 }}>
        {t("admin.transition.current")} <StatusBadge status={status} />
      </p>

      <div className="alert alert-warn" id={warnId}>
        <p style={{ margin: 0 }}>{t("admin.transition.gateCallout")}</p>
        <p style={{ margin: ".4rem 0 0" }}>{t("admin.transition.unverifiedCallout")}</p>
      </div>

      {blockedApproval && (
        <p className="alert alert-danger" role="alert">
          {t("admin.transition.blockedByFacts")}
        </p>
      )}

      <label className="field" htmlFor={noteId}>
        <span>{t("admin.transition.note")}</span>
        <textarea
          id={noteId}
          ref={noteRef}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={2000}
          aria-describedby={`${noteId}-help`}
        />
      </label>
      <p id={`${noteId}-help`} className="muted small" style={{ marginTop: "-.5rem" }}>
        {t("admin.transition.noteHelp")}
      </p>

      {targets.length === 0 ? (
        <p className="muted" role="note">
          {t("admin.transition.none", { role: t(`admin.role.${role}`), status: t(`admin.status.${status}`) })}
        </p>
      ) : (
        <div className={styles.actions}>
          {targets.map((to) => (
            <button
              key={to}
              type="button"
              className={`btn ${to === "approved" ? "btn-primary" : to === "rejected" ? "btn-danger" : "btn-secondary"}`}
              onClick={() => go(to)}
              disabled={busy !== null}
              aria-describedby={to === "approved" ? warnId : undefined}
            >
              {busy === to ? t("admin.transition.working") : t(`admin.transition.to.${to}`)}
            </button>
          ))}
        </div>
      )}

      {error && (
        <p className="alert alert-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
