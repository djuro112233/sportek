"use client";
/** Read-only view of a listing: both languages side by side, plus the host-confirmed facts. */
import { useLang, useT } from "@/lib/i18n";
import styles from "./host.module.css";
import type { Listing, Village } from "./types";
import { formatDate, formatPrice, seasonLabel } from "./utils";

export function StatusBadge({ status }: { status: string }) {
  const t = useT();
  const known = ["draft", "reviewed", "approved", "rejected"].includes(status);
  return (
    <span className={`badge ${known ? `badge-${status}` : ""}`}>{known ? t(`common.status.${status}`) : status}</span>
  );
}

export default function ListingPreview({ listing, villages = [] }: { listing: Listing; villages?: Village[] }) {
  const t = useT();
  const { lang } = useLang();
  const village = villages.find((v) => v.id === listing.village_id) ?? null;
  const price = formatPrice(lang, listing.price_min, listing.price_max, listing.currency);
  const notGiven = t("host.value.notGiven");

  return (
    <div>
      <div className={styles.langBlock}>
        <h4>{t("host.lang.cnr")}</h4>
        <p>
          <strong>{listing.title_local || notGiven}</strong>
        </p>
        <p>{listing.description_local || notGiven}</p>
      </div>
      <div className={styles.langBlock}>
        <h4>{t("host.lang.en")}</h4>
        <p>
          <strong>{listing.title_en || notGiven}</strong>
        </p>
        <p>{listing.description_en || notGiven}</p>
      </div>
      <dl className={styles.facts}>
        <dt>{t("host.field.category")}</dt>
        <dd>{listing.category ? t(`host.category.${listing.category}`) : notGiven}</dd>
        <dt>{t("host.group.price")}</dt>
        <dd>
          {price ?? notGiven}
          {listing.price_note_local || listing.price_note_en
            ? ` — ${lang === "cnr" ? listing.price_note_local || listing.price_note_en : listing.price_note_en || listing.price_note_local}`
            : ""}
        </dd>
        <dt>{t("host.group.season")}</dt>
        <dd>{seasonLabel(lang, listing, t)}</dd>
        <dt>{t("host.field.capacity")}</dt>
        <dd>{listing.capacity ?? notGiven}</dd>
        <dt>{t("host.field.step_free")}</dt>
        <dd>
          {listing.accessibility_step_free === null || listing.accessibility_step_free === undefined
            ? notGiven
            : listing.accessibility_step_free
              ? t("common.yes")
              : t("common.no")}
          {listing.accessibility_note_local || listing.accessibility_note_en
            ? ` — ${lang === "cnr" ? listing.accessibility_note_local || listing.accessibility_note_en : listing.accessibility_note_en || listing.accessibility_note_local}`
            : ""}
        </dd>
        <dt>{t("host.field.village")}</dt>
        <dd>
          {village ? `${lang === "cnr" ? village.name_local : village.name_en} — ${village.municipality}` : notGiven}
          {village && !village.facts_verified ? ` (${t("host.village.unverified")})` : ""}
        </dd>
        <dt>{t("host.group.location")}</dt>
        <dd>
          {listing.lat !== null && listing.lng !== null
            ? `${listing.lat.toFixed(5)}, ${listing.lng.toFixed(5)}${listing.coords_approximate ? ` (${t("common.approximate")})` : ""}`
            : notGiven}
        </dd>
        <dt>{t("host.field.version")}</dt>
        <dd>{listing.version}</dd>
        <dt>{t("host.field.published_at")}</dt>
        <dd>{listing.published_at ? formatDate(lang, listing.published_at, true) : t("host.value.notPublished")}</dd>
      </dl>
      {listing.missing_fields && listing.missing_fields.length > 0 ? (
        <p className="alert alert-warn small" role="note">
          {t("host.listing.missing", {
            fields: listing.missing_fields.map((f) => t(`host.missing.${f}`)).join(", "),
          })}
        </p>
      ) : null}
      {listing.translation_pending ? (
        <p className="alert alert-warn small" role="note">
          {t("host.draft.translationPending")}
        </p>
      ) : null}
    </div>
  );
}
