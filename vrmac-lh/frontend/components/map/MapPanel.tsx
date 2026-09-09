"use client";
/**
 * The map area of the visitor app: base-map choice, legend and the caption that says, in words,
 * which base map is currently drawing the tiles.
 *
 * Default: MapLibre GL over OpenStreetMap raster tiles (no key, no account).
 * Optional: the Google base layer, only when `GET /api/meta` reports `maps_provider === "google"`
 * and a key is configured. Directions are unaffected — they always open Google Maps navigation,
 * which needs no key.
 */
import dynamic from "next/dynamic";
import type { BaseMapProps } from "./types";
import { SYMBOL } from "./types";
import styles from "./map.module.css";

const Placeholder = () => <div className={styles.canvas} aria-hidden="true" />;

const MapView = dynamic(() => import("./MapView"), { ssr: false, loading: Placeholder });
const GoogleMapView = dynamic(() => import("./GoogleMapView"), { ssr: false, loading: Placeholder });

export interface MapPanelProps extends BaseMapProps {
  provider: "osm" | "google";
  apiKey: string;
}

export default function MapPanel(props: MapPanelProps) {
  const { provider, apiKey, t, ...map } = props;
  const google = provider === "google" && apiKey.length > 0;

  return (
    <div>
      {google ? <GoogleMapView {...map} t={t} apiKey={apiKey} /> : <MapView {...map} t={t} />}
      <p className={styles.caption}>
        {google ? t("visitor.map.baseGoogle") : t("visitor.map.baseOsm")}
        {provider === "google" && !google ? ` ${t("visitor.map.googleNoKey")}` : ""}
      </p>
      <ul className={styles.legend} aria-label={t("visitor.map.legend")}>
        <li>
          <span className={styles.legendSymbol} aria-hidden="true">
            {SYMBOL.heritage_entry}
          </span>
          {t("visitor.type.heritage_entry")}
        </li>
        <li>
          <span className={styles.legendSymbol} aria-hidden="true">
            {SYMBOL.listing}
          </span>
          {t("visitor.type.listing")}
        </li>
        <li>
          <span className={styles.legendSymbol} aria-hidden="true">
            {SYMBOL.trail_segment}
          </span>
          {t("visitor.type.trail_segment")}
        </li>
        <li>
          <span className={styles.legendSymbol} aria-hidden="true">
            {SYMBOL.user}
          </span>
          {t("visitor.map.you")}
        </li>
        <li>
          <span className={styles.legendSymbol} aria-hidden="true">
            {SYMBOL.report}
          </span>
          {t("visitor.map.reportPoint")}
        </li>
        <li>
          <span className={`${styles.legendLine} ${styles.lineGood}`} aria-hidden="true" />
          {t("visitor.condition.good")}
        </li>
        <li>
          <span className={`${styles.legendLine} ${styles.lineCaution}`} aria-hidden="true" />
          {t("visitor.condition.caution")}
        </li>
        <li>
          <span className={`${styles.legendLine} ${styles.lineBlocked}`} aria-hidden="true" />
          {t("visitor.condition.blocked")}
        </li>
        <li>
          <span className={`${styles.legendLine} ${styles.lineUnknown}`} aria-hidden="true" />
          {t("visitor.condition.unknown")}
        </li>
        <li>
          <span className={`${styles.legendLine} ${styles.lineGpx}`} aria-hidden="true" />
          {t("visitor.map.gpxTrack")}
        </li>
        <li>
          <span className={`${styles.legendLine} ${styles.lineRoute}`} aria-hidden="true" />
          {t("visitor.map.routeLine")}
        </li>
      </ul>
    </div>
  );
}
