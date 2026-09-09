"use client";
/** Small presentational pieces shared by the visitor tabs. */
import type { Translate } from "@/lib/i18n";
import { directionsUrl } from "@/lib/api";
import { SYMBOL } from "@/components/map/types";
import type { MapItemType, TrailCondition } from "./types";
import styles from "./visitor.module.css";

const CONDITION_ICON: Record<string, string> = { good: "✓", caution: "!", blocked: "✕", unknown: "?" };
const CONDITION_CLASS: Record<string, string> = {
  good: styles.conditionGood,
  caution: styles.conditionCaution,
  blocked: styles.conditionBlocked,
  unknown: "",
};

/** Condition of a trail: an icon **and** words — never colour alone. */
export function ConditionBadge({
  condition,
  t,
  date,
}: {
  condition: TrailCondition | string | null | undefined;
  t: Translate;
  date?: string;
}) {
  const key = condition === "good" || condition === "caution" || condition === "blocked" ? condition : "unknown";
  return (
    <span className={`${styles.condition} ${CONDITION_CLASS[key]}`}>
      <span aria-hidden="true">{CONDITION_ICON[key]}</span>
      {t(`visitor.condition.${key}`)}
      {date ? <span className="muted">· {date}</span> : null}
    </span>
  );
}

export function TypeChip({ itemType }: { itemType: MapItemType }) {
  return (
    <span className={styles.symbol} aria-hidden="true">
      {SYMBOL[itemType]}
    </span>
  );
}

/**
 * "How to get there": two Google Maps navigation deep links (real Google routing, no key needed).
 * They open in a new tab, and the text says so.
 */
export function DirectionsButtons({
  lat,
  lng,
  walking,
  driving,
  t,
  title,
}: {
  lat: number | null | undefined;
  lng: number | null | undefined;
  walking?: string | null;
  driving?: string | null;
  t: Translate;
  title?: string;
}) {
  const walkHref = walking ?? (lat != null && lng != null ? directionsUrl(lat, lng, "walking") : null);
  const driveHref = driving ?? (lat != null && lng != null ? directionsUrl(lat, lng, "driving") : null);
  if (!walkHref && !driveHref) return <p className="small muted">{t("visitor.directions.noCoords")}</p>;
  const suffix = title ? ` — ${title}` : "";
  return (
    <div>
      <div className={styles.inline}>
        {walkHref ? (
          <a
            className="btn btn-secondary btn-small"
            href={walkHref}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`${t("visitor.directions.walking")}${suffix} (${t("visitor.directions.newTabShort")})`}
          >
            {t("visitor.directions.walking")}
          </a>
        ) : null}
        {driveHref ? (
          <a
            className="btn btn-secondary btn-small"
            href={driveHref}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`${t("visitor.directions.driving")}${suffix} (${t("visitor.directions.newTabShort")})`}
          >
            {t("visitor.directions.driving")}
          </a>
        ) : null}
      </div>
      <p className={styles.note}>{t("visitor.directions.newTab")}</p>
    </div>
  );
}

export function ApproximateBadge({ t }: { t: Translate }) {
  return (
    <span className="badge" title={t("visitor.badge.approximateHelp")}>
      {t("visitor.badge.approximate")}
    </span>
  );
}

export function SampleBadge({ t }: { t: Translate }) {
  return (
    <span className="badge badge-draft" title={t("visitor.badge.sampleHelp")}>
      {t("visitor.badge.sample")}
    </span>
  );
}

export function UnverifiedBadge({ t }: { t: Translate }) {
  return (
    <span className="badge badge-reviewed" title={t("visitor.village.unverifiedHelp")}>
      {t("visitor.village.unverified")}
    </span>
  );
}

export function ErrorNote({ message, t }: { message: string | null; t: Translate }) {
  if (!message) return null;
  return (
    <p className="alert alert-danger" role="alert">
      {t("common.error", { message })}
    </p>
  );
}

export function Loading({ t }: { t: Translate }) {
  return (
    <p className="muted" role="status">
      {t("common.loading")}
    </p>
  );
}
