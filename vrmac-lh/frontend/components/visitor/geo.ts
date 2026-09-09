/** Geometry helpers shared by the visitor screens (WGS84 everywhere). */
import type { Feature, FeatureCollection, Geometry, Position } from "geojson";
import type { LatLng, MapFeature } from "./types";

/** The point that represents a feature: the point itself, or the start of a line. */
export function anchorOf(feature: { geometry: Geometry | null }): LatLng | null {
  const g = feature.geometry;
  if (!g) return null;
  if (g.type === "Point") return { lat: g.coordinates[1], lng: g.coordinates[0] };
  if (g.type === "LineString" && g.coordinates.length > 0) {
    return { lat: g.coordinates[0][1], lng: g.coordinates[0][0] };
  }
  if (g.type === "MultiLineString" && (g.coordinates[0]?.length ?? 0) > 0) {
    return { lat: g.coordinates[0][0][1], lng: g.coordinates[0][0][0] };
  }
  return null;
}

export function featureAnchor(feature: MapFeature): LatLng | null {
  return anchorOf(feature);
}

/** Wrap a list of WGS84 positions in a one-feature collection the map can draw. */
export function lineCollection(coordinates: Position[]): FeatureCollection<Geometry> | null {
  if (coordinates.length < 2) return null;
  const feature: Feature<Geometry> = {
    type: "Feature",
    properties: {},
    geometry: { type: "LineString", coordinates },
  };
  return { type: "FeatureCollection", features: [feature] };
}
