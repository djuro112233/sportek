"use client";
import { useEffect, useRef } from "react";
import {
  AttributionControl,
  GeoJSONSource,
  Map as MapLibreMap,
  NavigationControl,
  type AddLayerObject,
  type DataDrivenPropertyValueSpecification,
  type MapOptions,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { HeatmapCollection } from "./types";

/** OpenStreetMap raster tiles — no API key, attribution shown on the map (required by the licence). */
const OSM_STYLE: MapOptions["style"] = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

const VRMAC_CENTRE: [number, number] = [18.72, 42.4];
const EMPTY: HeatmapCollection = { type: "FeatureCollection", features: [] };

/** Colour ramp of the cells. MapLibre validates the expression at runtime; TS cannot type it. */
/** Layer specs are typed locally: maplibre's AddLayerObject is a union that includes custom layers
 *  without a `paint` field, so reading `paint` back off it does not type-check. */
type PaintedLayer = {
  id: string;
  type: string;
  source: string;
  filter?: unknown[];
  paint: Record<string, DataDrivenPropertyValueSpecification<string> | number | string>;
};

/** Choropleth ramp shared by the layer definition and later repaints. */
function visitColour(max: number): DataDrivenPropertyValueSpecification<string> {
  return ["interpolate", ["linear"], ["get", "n_visits"], 1, "#e4efe8", Math.max(2, max), "#2f6b4f"];
}

function fillLayer(max: number): PaintedLayer {
  return {
    id: "cells-fill",
    type: "fill",
    source: "cells",
    filter: ["==", ["geometry-type"], "Polygon"],
    paint: {
      "fill-color": visitColour(max),
      "fill-opacity": 0.75,
    },
  };
}

function outlineLayer(): PaintedLayer {
  return {
    id: "cells-outline",
    type: "line",
    source: "cells",
    filter: ["==", ["geometry-type"], "Polygon"],
    paint: { "line-color": "#1d1d1b", "line-width": 0.5, "line-opacity": 0.4 },
  };
}

function pointLayer(max: number): PaintedLayer {
  return {
    id: "cells-point",
    type: "circle",
    source: "cells",
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-radius": 7,
      "circle-color": visitColour(max),
      "circle-stroke-width": 1,
      "circle-stroke-color": "#1d1d1b",
    },
  };
}

function bounds(data: HeatmapCollection): [[number, number], [number, number]] | null {
  let w = 180;
  let s = 90;
  let e = -180;
  let n = -90;
  let seen = false;
  const visit = (c: unknown) => {
    if (Array.isArray(c) && typeof c[0] === "number" && typeof c[1] === "number") {
      seen = true;
      w = Math.min(w, c[0]);
      e = Math.max(e, c[0]);
      s = Math.min(s, c[1]);
      n = Math.max(n, c[1]);
    } else if (Array.isArray(c)) c.forEach(visit);
  };
  for (const f of data.features) visit(f.geometry?.coordinates);
  return seen ? [[w, s], [e, n]] : null;
}

/**
 * The heat map of aggregated visit cells. Client-side only (`ssr: false` at the import site):
 * MapLibre needs a DOM and a WebGL context.
 */
export default function HeatMapCanvas({ data, ariaLabel }: { data: HeatmapCollection; ariaLabel: string }) {
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const dataRef = useRef<HeatmapCollection>(data);
  dataRef.current = data ?? EMPTY;

  useEffect(() => {
    const node = container.current;
    if (!node || mapRef.current) return;

    const map = new MapLibreMap({
      container: node,
      style: OSM_STYLE,
      center: VRMAC_CENTRE,
      zoom: 11,
      attributionControl: false,
    });
    map.addControl(new NavigationControl(), "top-right");
    map.addControl(new AttributionControl({ compact: false }));
    map.on("load", () => apply(map));
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map && map.isStyleLoaded()) apply(map);
  }, [data]);

  function apply(map: MapLibreMap) {
    const collection = dataRef.current ?? EMPTY;
    const max = collection.features.reduce((acc, f) => Math.max(acc, Number(f.properties?.n_visits ?? 0)), 0);
    const existing = map.getSource("cells");
    if (existing) {
      (existing as GeoJSONSource).setData(collection);
      if (map.getLayer("cells-fill")) {
        map.setPaintProperty("cells-fill", "fill-color", visitColour(max));
      }
    } else {
      map.addSource("cells", { type: "geojson", data: collection });
      map.addLayer(fillLayer(max) as unknown as AddLayerObject);
      map.addLayer(outlineLayer() as unknown as AddLayerObject);
      map.addLayer(pointLayer(max) as unknown as AddLayerObject);
    }
    const box = bounds(collection);
    if (box) map.fitBounds(box, { padding: 40, maxZoom: 14, animate: false });
  }

  return <div ref={container} className="map" role="img" aria-label={ariaLabel} />;
}
