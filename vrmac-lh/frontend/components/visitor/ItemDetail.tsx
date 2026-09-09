"use client";
/**
 * The detail of one approved item: what it is, where it is, who confirmed the facts, how to get
 * there, and — for a provider — how to send a request. Nothing here is a booking or a payment.
 *
 * The map feature carries enough to draw the list; the authoritative record is fetched from the
 * item's own endpoint (`/api/heritage/{slug}`, `/api/listings/{slug}`, `/api/trails/{slug}`), so the
 * host-confirmed structured fields and the source citation come from the validated row itself.
 */
import { useEffect, useState } from "react";
import { pick } from "@/lib/i18n";
import type { VisitorCtx } from "./context";
import { errorMessage, getHeritageEntry, getListing, getTrail, postVisit } from "./api";
import { fmtDate, fmtMonth, fmtMoney, fmtNumber } from "./format";
import RequestPanel from "./RequestPanel";
import { ApproximateBadge, ConditionBadge, DirectionsButtons, SampleBadge, TypeChip } from "./ui";
import type { HeritageEntry, LatLng, Listing, MapFeature, Trail } from "./types";
import styles from "./visitor.module.css";

/** First coordinate of whatever geometry the feature has. */
function anchorOf(feature: MapFeature): LatLng | null {
  const g = feature.geometry;
  if (!g) return null;
  if (g.type === "Point") return { lat: g.coordinates[1], lng: g.coordinates[0] };
  if (g.type === "LineString" && g.coordinates.length > 0) {
    return { lat: g.coordinates[0][1], lng: g.coordinates[0][0] };
  }
  if (g.type === "MultiLineString" && g.coordinates[0]?.length > 0) {
    return { lat: g.coordinates[0][0][1], lng: g.coordinates[0][0][0] };
  }
  return null;
}

export default function ItemDetail({ ctx, feature }: { ctx: VisitorCtx; feature: MapFeature }) {
  const { t, lang } = ctx;
  const props = feature.properties;
  const [entry, setEntry] = useState<HeritageEntry | null>(null);
  const [listing, setListing] = useState<Listing | null>(null);
  const [trail, setTrail] = useState<Trail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [visitState, setVisitState] = useState<"idle" | "sending" | "sent" | "failed">("idle");
  const [visitError, setVisitError] = useState<string | null>(null);

  const key = `${props.item_type}:${props.id}`;

  useEffect(() => {
    let cancelled = false;
    setEntry(null);
    setListing(null);
    setTrail(null);
    setDetailError(null);
    setVisitState("idle");
    setVisitError(null);
    const ref = props.slug || props.id;
    const done = <T,>(apply: (value: T) => void) => (value: T) => {
      if (!cancelled) apply(value);
    };
    const failed = (e: unknown) => {
      if (!cancelled) setDetailError(errorMessage(e));
    };
    if (props.item_type === "heritage_entry") getHeritageEntry(ref).then(done(setEntry), failed);
    else if (props.item_type === "listing") getListing(ref).then(done(setListing), failed);
    else getTrail(ref).then(done(setTrail), failed);
    return () => {
      cancelled = true;
    };
  }, [key, props.item_type, props.slug, props.id]);

  const village = ctx.villageOf({ village_slug: props.village_slug, village_id: props.village_id });
  const anchor = anchorOf(feature) ?? (listing && listing.lat != null && listing.lng != null ? { lat: listing.lat, lng: listing.lng } : null);
  const title = pick(lang, props.title_local, props.title_en);
  const summary = pick(
    lang,
    entry?.summary_local ?? listing?.description_local ?? trail?.description_local ?? props.summary_local,
    entry?.summary_en ?? listing?.description_en ?? trail?.description_en ?? props.summary_en,
  );
  const body = entry ? pick(lang, entry.body_local, entry.body_en) : "";
  const approximate = props.coords_approximate ?? entry?.coords_approximate ?? listing?.coords_approximate ?? false;
  const isSample = props.is_sample ?? listing?.is_sample ?? false;
  const confirmed = listing?.confirmed_fields ?? props.confirmed_fields ?? [];

  const recordVisit = async () => {
    if (!anchor) return;
    setVisitState("sending");
    setVisitError(null);
    try {
      await postVisit({
        event_type: "visit_recorded",
        session_id: ctx.sessionId,
        device_id: ctx.deviceId,
        lat: anchor.lat,
        lng: anchor.lng,
        item_type: props.item_type,
        item_id: props.id,
      });
      setVisitState("sent");
      ctx.announce(t("visitor.visit.done"));
    } catch (e) {
      setVisitState("failed");
      setVisitError(errorMessage(e));
    }
  };

  const season = () => {
    const l = listing;
    if (!l) return null;
    if (l.season_all_year) return t("visitor.listing.allYear");
    if (l.season_from && l.season_to) return `${fmtMonth(lang, l.season_from)} – ${fmtMonth(lang, l.season_to)}`;
    return null;
  };

  const price = () => {
    const l = listing;
    if (!l || (l.price_min == null && l.price_max == null)) return null;
    const cur = l.currency || "EUR";
    const range =
      l.price_min != null && l.price_max != null && l.price_min !== l.price_max
        ? `${fmtMoney(lang, l.price_min, cur)} – ${fmtMoney(lang, l.price_max, cur)}`
        : fmtMoney(lang, l.price_min ?? l.price_max, cur);
    const note = pick(lang, l.price_note_local, l.price_note_en);
    return note ? `${range} (${note})` : range;
  };

  const stepFree = () => {
    const l = listing;
    if (!l) return null;
    if (l.accessibility_step_free === null || l.accessibility_step_free === undefined) return t("visitor.listing.unknown");
    return l.accessibility_step_free ? t("common.yes") : t("common.no");
  };

  return (
    <section className={styles.detail} aria-labelledby="visitor-detail-title" tabIndex={-1}>
      <h3 id="visitor-detail-title">
        <TypeChip itemType={props.item_type} /> {title}
      </h3>

      <p className={styles.inline}>
        <span className="badge">{t(`visitor.type.${props.item_type}`)}</span>
        {props.kind ? <span className="badge">{t(`visitor.kind.${props.kind}`, { fallback: props.kind })}</span> : null}
        {props.category ? <span className="badge">{t(`visitor.category.${props.category}`)}</span> : null}
        {approximate ? <ApproximateBadge t={t} /> : null}
        {isSample ? <SampleBadge t={t} /> : null}
      </p>

      {village ? (
        <p className="small">
          {t("visitor.village.label")}: <strong>{pick(lang, village.name_local, village.name_en)}</strong> ·{" "}
          {t("visitor.municipality.label")}: {village.municipality}
        </p>
      ) : props.municipality ? (
        <p className="small">
          {t("visitor.municipality.label")}: {props.municipality}
        </p>
      ) : null}

      {listing?.photo_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className={styles.photo} src={listing.photo_url} alt={t("visitor.listing.photoAlt", { title })} />
      ) : null}

      {summary ? <p>{summary}</p> : null}
      {body ? <p style={{ whiteSpace: "pre-wrap" }}>{body}</p> : null}

      {props.item_type === "trail_segment" ? (
        <dl className={styles.facts}>
          <dt>{t("visitor.trail.length")}</dt>
          <dd>{trail?.length_m ?? props.length_m ? `${fmtNumber(lang, (trail?.length_m ?? props.length_m) as number)} m` : "—"}</dd>
          <dt>{t("visitor.trail.ascent")}</dt>
          <dd>{trail?.ascent_m ?? props.ascent_m ? `${fmtNumber(lang, (trail?.ascent_m ?? props.ascent_m) as number)} m` : "—"}</dd>
          <dt>{t("visitor.trail.difficulty")}</dt>
          <dd>{t(`visitor.difficulty.${trail?.difficulty ?? props.difficulty ?? "unknown"}`)}</dd>
          <dt>{t("visitor.trail.latestReport")}</dt>
          <dd>
            <ConditionBadge
              condition={props.latest_report?.condition}
              t={t}
              date={props.latest_report?.reported_at ? fmtDate(lang, props.latest_report.reported_at) : undefined}
            />
          </dd>
        </dl>
      ) : null}

      {props.item_type === "listing" ? (
        <section aria-labelledby="visitor-confirmed-title">
          <h4 id="visitor-confirmed-title">{t("visitor.listing.confirmedTitle")}</h4>
          <p className={styles.note}>{t("visitor.listing.confirmedHelp")}</p>
          <dl className={styles.facts}>
            <dt>{t("visitor.listing.price")}</dt>
            <dd>{price() ?? t("visitor.listing.notGiven")}</dd>
            <dt>{t("visitor.listing.season")}</dt>
            <dd>{season() ?? t("visitor.listing.notGiven")}</dd>
            <dt>{t("visitor.listing.capacity")}</dt>
            <dd>{listing?.capacity != null ? fmtNumber(lang, listing.capacity) : t("visitor.listing.notGiven")}</dd>
            <dt>{t("visitor.listing.stepFree")}</dt>
            <dd>
              {stepFree() ?? t("visitor.listing.notGiven")}
              {pick(lang, listing?.accessibility_note_local, listing?.accessibility_note_en) ? (
                <> — {pick(lang, listing?.accessibility_note_local, listing?.accessibility_note_en)}</>
              ) : null}
            </dd>
          </dl>
          {confirmed.length > 0 ? (
            <p className={styles.note}>{t("visitor.listing.confirmedFields", { fields: confirmed.join(", ") })}</p>
          ) : null}
        </section>
      ) : null}

      {props.item_type === "heritage_entry" ? (
        <section aria-labelledby="visitor-source-title">
          <h4 id="visitor-source-title">{t("common.source")}</h4>
          <p className="cite">{entry?.source || props.source || t("visitor.source.missing")}</p>
          {(entry?.sources ?? []).length > 0 ? (
            <ul className="small">
              {(entry?.sources ?? []).map((s, i) => (
                <li key={`${s.title ?? "source"}-${i}`}>
                  {s.url ? (
                    <a href={s.url} target="_blank" rel="noopener noreferrer">
                      {s.title ?? s.url}
                    </a>
                  ) : (
                    (s.title ?? "—")
                  )}
                </li>
              ))}
            </ul>
          ) : null}
          {entry?.event_date ? (
            <p className="small">
              {t("visitor.calendar.date")}: {fmtDate(lang, entry.event_date)}
              {entry.recurrence_rule ? ` · ${entry.recurrence_rule}` : ""}
            </p>
          ) : null}
        </section>
      ) : null}

      <h4>{t("common.directions")}</h4>
      <DirectionsButtons
        lat={anchor?.lat}
        lng={anchor?.lng}
        walking={props.directions_walking}
        driving={props.directions_driving}
        t={t}
        title={title}
      />

      <h4>{t("visitor.visit.title")}</h4>
      <p className={styles.note}>{t("visitor.visit.explain")}</p>
      <button
        type="button"
        className="btn btn-secondary btn-small"
        onClick={recordVisit}
        disabled={!anchor || visitState === "sending" || visitState === "sent"}
      >
        {visitState === "sent" ? t("visitor.visit.recorded") : t("visitor.visit.button")}
      </button>
      {visitState === "sent" ? (
        <p className="alert alert-ok small" role="status">
          {t("visitor.visit.done")}
        </p>
      ) : null}
      {visitState === "failed" ? (
        <p className="alert alert-danger small" role="alert">
          {t("common.error", { message: visitError ?? "" })}
        </p>
      ) : null}

      {props.item_type === "listing" ? <RequestPanel ctx={ctx} listingId={props.id} title={title} /> : null}

      {detailError ? (
        <p className="alert alert-warn small" role="status">
          {t("visitor.detail.partial", { message: detailError })}
        </p>
      ) : null}
    </section>
  );
}
