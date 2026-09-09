"use client";
/**
 * MapLibre GL over OpenStreetMap raster tiles — the default base map of the visitor app.
 *
 * Claim #5: every approved place, provider and trail segment carries WGS84 coordinates and appears
 * here. The style is inline (no external style server), the tiles are plain OSM, and the attribution
 * "© OpenStreetMap contributors" is always visible.
 *
 * Client-only: load it with `next/dynamic` and `ssr: false` (MapLibre needs a DOM and WebGL).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type FilterSpecification,
  type GeoJSONSource,
  type MapLayerMouseEvent,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  ScaleControl,
  type StyleSpecification,
} from "maplibre-gl";
import type { Feature, FeatureCollection, Geometry, Position } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import { pick } from "@/lib/i18n";
import type { MapFeatureCollection, MapItemType } from "@/components/visitor/types";
import { type BaseMapProps, type ExtraPoint, SYMBOL } from "./types";
import styles from "./map.module.css";

/** Inline raster style — OpenStreetMap tiles, no style server, no API key. */
const OSM_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm", minzoom: 0, maxzoom: 22 }],
};

/** The Vrmac ridge, both sides — used until the features arrive. */
const HOME: [number, number] = [18.6935, 42.4445];

interface LineProps {
  key: string;
  condition: "good" | "caution" | "blocked" | "unknown";
  title: string;
}

const EMPTY_LINES: FeatureCollection<Geometry, LineProps> = { type: "FeatureCollection", features: [] };
const EMPTY: FeatureCollection<Geometry> = { type: "FeatureCollection", features: [] };

function conditionOf(props: { latest_report?: { condition?: string } | null }): LineProps["condition"] {
  const c = props.latest_report?.condition;
  return c === "good" || c === "caution" || c === "blocked" ? c : "unknown";
}

function isLine(g: Geometry | null | undefined): boolean {
  return !!g && (g.type === "LineString" || g.type === "MultiLineString");
}

function eachPosition(geometry: Geometry | null | undefined, cb: (p: Position) => void): void {
  if (!geometry) return;
  switch (geometry.type) {
    case "Point":
      cb(geometry.coordinates);
      break;
    case "MultiPoint":
    case "LineString":
      geometry.coordinates.forEach(cb);
      break;
    case "MultiLineString":
    case "Polygon":
      geometry.coordinates.forEach((ring) => ring.forEach(cb));
      break;
    case "MultiPolygon":
      geometry.coordinates.forEach((poly) => poly.forEach((ring) => ring.forEach(cb)));
      break;
    case "GeometryCollection":
      geometry.geometries.forEach((g) => eachPosition(g, cb));
      break;
    default:
      break;
  }
}

type Box = [number, number, number, number]; // [west, south, east, north]

function growBox(box: Box | null, lng: number, lat: number): Box {
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return box ?? [lng, lat, lng, lat];
  if (!box) return [lng, lat, lng, lat];
  return [Math.min(box[0], lng), Math.min(box[1], lat), Math.max(box[2], lng), Math.max(box[3], lat)];
}

function boxOfFeatures(fc: { features: { geometry: Geometry | null }[] } | null, start: Box | null = null): Box | null {
  let box = start;
  for (const f of fc?.features ?? []) eachPosition(f.geometry, (p) => (box = growBox(box, p[0], p[1])));
  return box;
}

export default function MapView({
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
}: BaseMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<{ key: string; marker: Marker; el: HTMLButtonElement }[]>([]);
  const onSelectRef = useRef(onSelect);
  const onMapClickRef = useRef(onMapClick);
  const pickModeRef = useRef(pickMode);
  const [ready, setReady] = useState(false);

  onSelectRef.current = onSelect;
  onMapClickRef.current = onMapClick;
  pickModeRef.current = pickMode;

  const reduceMotion = useCallback(
    () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  /* Lines (trail segments) go into a GeoJSON source; points become real <button> markers. */
  const lines = useMemo<FeatureCollection<Geometry, LineProps>>(() => {
    const out: Feature<Geometry, LineProps>[] = [];
    for (const f of features?.features ?? []) {
      if (!isLine(f.geometry) || !f.properties) continue;
      out.push({
        type: "Feature",
        geometry: f.geometry as Geometry,
        properties: {
          key: `${f.properties.item_type}:${f.properties.id}`,
          condition: conditionOf(f.properties),
          title: pick(lang, f.properties.title_local, f.properties.title_en),
        },
      });
    }
    return { type: "FeatureCollection", features: out };
  }, [features, lang]);

  const points = useMemo(() => {
    const out: { key: string; lat: number; lng: number; itemType: MapItemType; title: string }[] = [];
    for (const f of features?.features ?? []) {
      if (!f.properties) continue;
      const g = f.geometry;
      if (!g || g.type !== "Point") continue;
      const [lng, lat] = g.coordinates;
      out.push({
        key: `${f.properties.item_type}:${f.properties.id}`,
        lat,
        lng,
        itemType: f.properties.item_type,
        title: pick(lang, f.properties.title_local, f.properties.title_en),
      });
    }
    return out;
  }, [features, lang]);

  /* ---------------------------------------------------------------- create the map (once) */
  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return;

    const map = new MapLibreMap({
      container,
      style: OSM_STYLE,
      center: HOME,
      zoom: 12,
      attributionControl: { compact: false },
      maxZoom: 19,
    });
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-left");

    const eq = (value: string): FilterSpecification =>
      ["==", ["get", "condition"], value] as unknown as FilterSpecification;

    map.on("load", () => {
      map.addSource("vrmac-lines", { type: "geojson", data: EMPTY_LINES });
      map.addSource("vrmac-gpx", { type: "geojson", data: EMPTY });
      map.addSource("vrmac-route", { type: "geojson", data: EMPTY });

      // Highlight below the trail itself, so the condition pattern stays readable.
      map.addLayer({
        id: "lines-selected",
        type: "line",
        source: "vrmac-lines",
        filter: ["==", ["get", "key"], ""] as unknown as FilterSpecification,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#1a4fd6", "line-width": 11, "line-opacity": 0.4 },
      });
      map.addLayer({
        id: "lines-unknown",
        type: "line",
        source: "vrmac-lines",
        filter: eq("unknown"),
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: { "line-color": "#4a4f57", "line-width": 4, "line-dasharray": [4, 2] },
      });
      map.addLayer({
        id: "lines-good",
        type: "line",
        source: "vrmac-lines",
        filter: eq("good"),
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#1b5e35", "line-width": 4 },
      });
      map.addLayer({
        id: "lines-caution",
        type: "line",
        source: "vrmac-lines",
        filter: eq("caution"),
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: { "line-color": "#8a5a00", "line-width": 4, "line-dasharray": [3, 2] },
      });
      map.addLayer({
        id: "lines-blocked",
        type: "line",
        source: "vrmac-lines",
        filter: eq("blocked"),
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: { "line-color": "#8c1d1d", "line-width": 5, "line-dasharray": [1, 1.5] },
      });
      map.addLayer({
        id: "gpx-casing",
        type: "line",
        source: "vrmac-gpx",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": 9, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: "gpx-line",
        type: "line",
        source: "vrmac-gpx",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#3d2a7a", "line-width": 5 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "vrmac-route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#0f5a8f", "line-width": 5, "line-dasharray": [2, 1.5] },
      });
      // Invisible, generous hit area so a 4 px line can be tapped on a phone.
      map.addLayer({
        id: "lines-hit",
        type: "line",
        source: "vrmac-lines",
        paint: { "line-color": "#000000", "line-width": 20, "line-opacity": 0.01 },
      });

      const canvas = map.getCanvas();
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", label);

      setReady(true);
    });

    const onLineClick = (e: MapLayerMouseEvent) => {
      if (pickModeRef.current) return; // in pick mode a click means "here", not "select this"
      const key = e.features?.[0]?.properties?.key;
      if (typeof key === "string") onSelectRef.current(key);
    };
    map.on("click", "lines-hit", onLineClick);
    map.on("mouseenter", "lines-hit", () => {
      if (!pickModeRef.current) map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "lines-hit", () => {
      map.getCanvas().style.cursor = pickModeRef.current ? "crosshair" : "";
    });
    map.on("click", (e) => {
      if (pickModeRef.current) onMapClickRef.current?.(e.lngLat.lat, e.lngLat.lng);
    });

    return () => {
      markersRef.current.forEach((m) => m.marker.remove());
      markersRef.current = [];
      setReady(false);
      mapRef.current = null;
      map.remove();
    };
    // The accessible name is set once; it does not change while the map lives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---------------------------------------------------------------- data → sources */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("vrmac-lines") as GeoJSONSource | undefined)?.setData(lines);
  }, [lines, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("vrmac-gpx") as GeoJSONSource | undefined)?.setData(gpx ?? EMPTY);
  }, [gpx, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("vrmac-route") as GeoJSONSource | undefined)?.setData(route ?? EMPTY);
  }, [route, ready]);

  /* ---------------------------------------------------------------- markers */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    markersRef.current.forEach((m) => m.marker.remove());
    markersRef.current = [];

    const add = (
      key: string,
      lat: number,
      lng: number,
      cls: string,
      glyph: string,
      ariaLabel: string,
      selectable: boolean,
    ) => {
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
      const el = document.createElement("button");
      el.type = "button";
      el.className = `${styles.marker} ${cls}`;
      el.textContent = glyph;
      el.title = ariaLabel;
      el.setAttribute("aria-label", ariaLabel);
      if (selectable) {
        el.setAttribute("aria-pressed", "false");
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          onSelectRef.current(key);
        });
      } else {
        el.tabIndex = -1;
        el.setAttribute("aria-hidden", "true");
      }
      const marker = new Marker({ element: el, anchor: "center" }).setLngLat([lng, lat]).addTo(map);
      markersRef.current.push({ key, marker, el });
    };

    const clsFor: Record<MapItemType, string> = {
      heritage_entry: styles.markerHeritage,
      listing: styles.markerListing,
      trail_segment: styles.markerTrail,
    };
    for (const p of points) {
      add(p.key, p.lat, p.lng, clsFor[p.itemType], SYMBOL[p.itemType], `${p.title} — ${t(`visitor.type.${p.itemType}`)}`, true);
    }

    const extraCls: Record<ExtraPoint["kind"], string> = {
      user: styles.markerUser,
      report: styles.markerReport,
      picked: styles.markerPicked,
      stop: styles.markerStop,
    };
    for (const p of extraPoints) {
      add(
        `extra:${p.id}`,
        p.lat,
        p.lng,
        extraCls[p.kind],
        p.kind === "stop" && p.order ? String(p.order) : SYMBOL[p.kind],
        p.label,
        false,
      );
    }
  }, [points, extraPoints, ready, t]);

  /* ---------------------------------------------------------------- selection */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const m of markersRef.current) {
      const on = m.key === selectedKey;
      m.el.classList.toggle(styles.markerSelected, on);
      if (m.el.hasAttribute("aria-pressed")) m.el.setAttribute("aria-pressed", on ? "true" : "false");
    }
    map.setFilter("lines-selected", ["==", ["get", "key"], selectedKey ?? ""] as unknown as FilterSpecification);
    if (!selectedKey) return;

    const point = points.find((p) => p.key === selectedKey);
    if (point) {
      const target = { center: [point.lng, point.lat] as [number, number], zoom: Math.max(map.getZoom(), 15) };
      if (reduceMotion()) map.jumpTo(target);
      else map.easeTo({ ...target, duration: 700 });
      return;
    }
    const line = lines.features.find((f) => f.properties.key === selectedKey);
    if (line) {
      const box = boxOfFeatures({ features: [line] });
      if (box) map.fitBounds([[box[0], box[1]], [box[2], box[3]]], { padding: 60, maxZoom: 16, animate: !reduceMotion() });
    }
  }, [selectedKey, points, lines, ready, reduceMotion]);

  /* ---------------------------------------------------------------- fit bounds */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    let box: Box | null = null;
    if (gpx && gpx.features.length > 0) box = boxOfFeatures(gpx);
    else if (route && route.features.length > 0) box = boxOfFeatures(route);
    else {
      box = boxOfFeatures(lines);
      for (const p of points) box = growBox(box, p.lng, p.lat);
    }
    if (!box) return;
    const [w, s, e, n] = box;
    if (w === e && s === n) {
      map.jumpTo({ center: [w, s], zoom: Math.max(map.getZoom(), 14) });
      return;
    }
    map.fitBounds([[w, s], [e, n]], { padding: 56, maxZoom: 16, animate: !reduceMotion() });
    // Refit only when the parent says the data set changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, ready]);

  /* ---------------------------------------------------------------- pick mode cursor */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.getCanvas().style.cursor = pickMode ? "crosshair" : "";
  }, [pickMode, ready]);

  return (
    <div className={styles.wrap}>
      <div
        ref={containerRef}
        className={`${styles.canvas} ${pickMode ? styles.pick : ""}`}
        role="region"
        aria-label={label}
        aria-describedby={describedById}
        data-testid="maplibre-map"
      />
      {!ready ? (
        <p className={styles.caption} role="status">
          {t("visitor.map.loading")}
        </p>
      ) : null}
    </div>
  );
}
