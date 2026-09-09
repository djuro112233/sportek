"use client";
import { useLang, useT } from "@/lib/i18n";
import { fmtDateTime, label } from "./format";
import { StatusBadge } from "./ui";
import type { ProvenanceOut } from "./types";
import styles from "./admin.module.css";

/** Who did what, when, to which version, on which source — the provenance trail of one item. */
export default function ProvenanceTimeline({ provenance }: { provenance: ProvenanceOut[] }) {
  const t = useT();
  const { lang } = useLang();

  if (provenance.length === 0) return <p className="muted">{t("admin.provenance.empty")}</p>;

  return (
    <ol className={styles.timeline}>
      {provenance.map((p) => (
        <li key={p.id}>
          <p style={{ margin: 0 }}>
            <strong>{label(t, `admin.action.${p.action}`, p.action)}</strong>{" "}
            {p.from_status && (
              <>
                <StatusBadge status={p.from_status} /> <span aria-hidden="true">→</span>{" "}
                <span className="visually-hidden">{t("admin.provenance.to")}</span>
              </>
            )}
            {p.to_status && <StatusBadge status={p.to_status} />}
          </p>
          <p className="muted small" style={{ margin: ".15rem 0 0" }}>
            {t("admin.provenance.by", { role: label(t, `admin.role.${p.actor_role}`, p.actor_role) })}
            {" · "}
            {t("admin.provenance.version", { version: p.version })}
            {" · "}
            <time dateTime={p.created_at}>{fmtDateTime(lang, p.created_at)}</time>
          </p>
          {p.source && (
            <p className="small" style={{ margin: ".15rem 0 0" }}>
              {t("admin.provenance.source")}: {p.source}
            </p>
          )}
          {p.note && (
            <p className="small" style={{ margin: ".15rem 0 0" }}>
              {t("admin.provenance.note")}: {p.note}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
