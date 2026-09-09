"use client";
/**
 * "About my data" — the **voluntary** gender self-report (POST /api/auth/me/gender).
 *
 * It is optional, it is used only for aggregate statistics, and leaving it unanswered is a normal
 * outcome that the panel states plainly. Nothing else in the host app depends on the answer.
 */
import { FormEvent, useState } from "react";
import { useT } from "@/lib/i18n";
import styles from "./host.module.css";
import { reportGender } from "./hostApi";
import type { GenderChoice, HostUser } from "./types";
import { GENDER_CHOICES } from "./types";
import { describeError } from "./utils";

export default function GenderPanel({ user }: { user: HostUser }) {
  const t = useT();
  const [current, setCurrent] = useState<GenderChoice | "undisclosed">(user.gender ?? "undisclosed");
  const [reported, setReported] = useState<boolean>(Boolean(user.gender_self_reported));
  const [choice, setChoice] = useState<GenderChoice | "">("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!choice) return;
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      const updated = await reportGender(choice);
      setCurrent(updated.gender ?? choice);
      setReported(Boolean(updated.gender_self_reported ?? true));
      setMessage(t("host.gender.saved"));
    } catch (err) {
      setError(describeError(err, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-labelledby="gender-heading">
      <h2 id="gender-heading">{t("host.gender.heading")}</h2>
      <p>{t("host.gender.why")}</p>
      <ul>
        <li>{t("host.gender.point1")}</li>
        <li>{t("host.gender.point2")}</li>
        <li>{t("host.gender.point3")}</li>
      </ul>
      <p>
        <strong>
          {reported ? t("host.gender.current", { value: t(`host.gender.value.${current}`) }) : t("host.gender.notAnswered")}
        </strong>
      </p>
      <form onSubmit={submit}>
        <fieldset className={styles.group}>
          <legend>{t("host.gender.legend")}</legend>
          {GENDER_CHOICES.map((g) => (
            <label key={g} className={styles.check} htmlFor={`gender-${g}`}>
              <input
                id={`gender-${g}`}
                type="radio"
                name="gender"
                value={g}
                checked={choice === g}
                onChange={() => setChoice(g)}
              />
              <span>{t(`host.gender.value.${g}`)}</span>
            </label>
          ))}
          <p className={styles.hint}>{t("host.gender.optional")}</p>
        </fieldset>
        <button type="submit" className="btn btn-primary" disabled={busy || !choice}>
          {busy ? t("host.gender.saving") : t("host.gender.save")}
        </button>
      </form>
      <p role="status" aria-live="polite" className="small">
        {message}
      </p>
      {error ? (
        <p className="alert alert-danger" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
