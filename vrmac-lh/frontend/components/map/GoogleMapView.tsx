"use client";
/**
 * Optional Google Maps base layer — used only when `GET /api/meta` reports
 * `maps_provider === "google"` **and** a key is configured. Everything else in the app is unchanged:
 * it implements the same `BaseMapProps` contract as `MapView` (MapLibre + OpenStreetMap), which
 * stays the default and the fallback.
 *
 * The script is injected once per page load; the ambient types live in `./google.d.ts` (no npm
 * package is installed for this prototype).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { Geometry, Position } from "geojson";
import { pick } from "@/lib/i18n";
import type { MapItemType } from "@/components/visitor/types";
import { type BaseMapProps, type ExtraPoint, SYMBOL } from "./types";
import styles from "./map.module.css";

const CALLBACK = "__vrmacGoogleMapsReady";
let scriptPromise: Promise<void> | null = null;

/** Load the Google Maps JS API exactly once, whatever how many maps are mounted. */
function loadGoogleMaps(apiKey: string): Promise<void> {
  if (typeof window === "undefined") return Promise.reject(new Error("no browser"));
  if (window.google?.maps) return Promise.resolve();
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise<void>((resolve, reject) => {
    const holder = window as unknown as Record<string, unknown>;
    holder[CALLBACK] = () => resolve();
    const script = document.createElement("script");
    script.src =
      `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}` +
      `&callback=${CALLBACK}&loading=async`;
    script.async = true;
    script.defer = true;
    script.onerror = () => reject(new Error("Google Maps JavaScript API could not be loaded"));
    document.head.appendChild(script);
  });
  return scriptPromise;
}

function positionsOf(geometry: Geometry | null | undefined): Position[] {
  if (!geometry) return [];
  switch (geometry.type) {
    case "LineString":
      return geometry.coordinates;
    case "MultiLineString":
      return geometry.coordinates.flat();
    case "Point":
      return [geometry.coordinates];
    default:
      return [];
  }
}

const LINE_COLOR: Record<string, string> = {
  good: "#1b5e35",
  caution: "#8a5a00",
  blocked: "#8c1d1d",
  unknown: "#4a4f57",
};

export default function GoogleMapView({
  features,
  selectedKey,
  onSelect,
  gpx,
  route,
  extraPoints,
  onMapClick,
  pickMode = false,
  lang,
  t,
  label,
  describedById,
  fitKey,
  apiKey,
}: BaseMapProps & { apiKey: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const overlaysRef = useRef<{ markers: google.maps.Marker[]; lines: google.maps.Polyline[] }>({
    markers: [],
    lines: [],
  });
  const onSelectRef = useRef(onSelect);
  const onMapClickRef = useRef(onMapClick);
  const pickModeRef = useRef(pickMode);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  onSelectRef.current = onSelect;
  onMapClickRef.current = onMapClick;
  pickModeRef.current = pickMode;

  useEffect(() => {
    let cancelled = false;
    loadGoogleMaps(apiKey)
      .then(() => {
        if (cancelled || !containerRef.current || mapRef.current || !window.google?.maps) return;
        const map = new window.google.maps.Map(containerRef.current, {
          center: { lat: 42.4445, lng: 18.6935 },
          zoom: 12,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          scaleControl: true,
          clickableIcons: false,
          maxZoom: 19,
        });
        map.addListener("click", (event: google.maps.MapMouseEvent) => {
          if (!pickModeRef.current || !event.latLng) return;
          onMapClickRef.current?.(event.latLng.lat(), event.latLng.lng());
        });
        mapRef.current = map;
        setReady(true);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [apiKey]);

  const items = useMemo(() => features?.features ?? [], [features]);

  /* Markers + polylines are rebuilt whenever the data or the selection changes (the set is small). */
  useEffect(() => {
    const map = mapRef.current;
    const maps = typeof window !== "undefined" ? window.google?.maps : undefined;
    if (!map || !ready || !maps) return;

    overlaysRef.current.markers.forEach((m) => m.setMap(null));
    overlaysRef.current.lines.forEach((l) => l.setMap(null));
    overlaysRef.current = { markers: [], lines: [] };

    const bounds = new maps.LatLngBounds();
    let hasBounds = false;

    for (const f of items) {
      const props = f.properties;
      if (!props) continue;
      const key = `${props.item_type}:${props.id}`;
      const title = pick(lang, props.title_local, props.title_en);
      const selected = key === selectedKey;
      if (f.geometry?.type === "Point") {
        const [lng, lat] = f.geometry.coordinates;
        const marker = new maps.Marker({
          position: { lat, lng },
          map,
          title: `${title} — ${t(`visitor.type.${props.item_type as MapItemType}`)}`,
          label: { text: SYMBOL[props.item_type], color: "#ffffff", fontSize: selected ? "18px" : "14px" },
          zIndex: selected ? 10 : 1,
          optimized: false,
        });
        marker.addListener("click", () => onSelectRef.current(key));
        overlaysRef.current.markers.push(marker);
        bounds.extend({ lat, lng });
        hasBounds = true;
      } else {
        const path = positionsOf(f.geometry).map(([lng, lat]) => ({ lat, lng }));
        if (path.length < 2) continue;
        const condition = props.latest_report?.condition ?? "unknown";
        const line = new maps.Polyline({
          path,
          map,
          strokeColor: LINE_COLOR[condition] ?? LINE_COLOR.unknown,
          strokeOpacity: 0.95,
          strokeWeight: selected ? 8 : 4,
          zIndex: selected ? 10 : 1,
          clickable: true,
        });
        line.addListener("click", () => {
          if (!pickModeRef.current) onSelectRef.current(key);
        });
        overlaysRef.current.lines.push(line);
        path.forEach((p) => bounds.extend(p));
        hasBounds = true;
      }
    }

    const extraCls: Record<ExtraPoint["kind"], string> = {
      user: "#0f5a8f",
      report: "#8c1d1d",
      picked: "#1d1d1b",
      stop: "#0f5a8f",
    };
    for (const p of extraPoints) {
      const marker = new maps.Marker({
        position: { lat: p.lat, lng: p.lng },
        map,
        title: p.label,
        label: {
          text: p.kind === "stop" && p.order ? String(p.order) : SYMBOL[p.kind],
          color: extraCls[p.kind],
          fontWeight: "700",
        },
        zIndex: 20,
        optimized: false,
      });
      overlaysRef.current.markers.push(marker);
    }

    for (const overlay of [gpx, route]) {
      for (const f of overlay?.features ?? []) {
        const path = positionsOf(f.geometry).map(([lng, lat]) => ({ lat, lng }));
        if (path.length < 2) continue;
        const line = new maps.Polyline({
          path,
          map,
          strokeColor: overlay === gpx ? "#3d2a7a" : "#0f5a8f",
          strokeOpacity: 0.95,
          strokeWeight: 6,
          zIndex: 15,
          clickable: false,
        });
        overlaysRef.current.lines.push(line);
      }
    }
    void hasBounds;
  }, [items, extraPoints, gpx, route, selectedKey, lang, t, ready]);

  /* Fit the viewport when the parent says the data set changed. */
  useEffect(() => {
    const map = mapRef.current;
    const maps = typeof window !== "undefined" ? window.google?.maps : undefined;
    if (!map || !ready || !maps) return;
    const bounds = new maps.LatLngBounds();
    let any = false;
    const source =
      gpx && gpx.features.length > 0 ? gpx.features : route && route.features.length > 0 ? route.features : items;
    for (const f of source) {
      for (const [lng, lat] of positionsOf(f.geometry)) {
        bounds.extend({ lat, lng });
        any = true;
      }
    }
    if (any) map.fitBounds(bounds, 48);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.setOptions({ draggableCursor: pickMode ? "crosshair" : undefined });
  }, [pickMode, ready]);

  return (
    <div className={styles.wrap}>
      <div
        ref={containerRef}
        className={`${styles.googleCanvas} ${pickMode ? styles.pick : ""}`}
        role="region"
        aria-label={label}
        aria-describedby={describedById}
        data-testid="google-map"
      />
      {error ? (
        <p className={styles.caption} role="alert">
          {t("visitor.map.googleFailed")}
        </p>
      ) : null}
      {!ready && !error ? (
        <p className={styles.caption} role="status">
          {t("visitor.map.loading")}
        </p>
      ) : null}
    </div>
  );
}
