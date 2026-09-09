/**
 * The one contract both base maps implement: MapLibre GL over OpenStreetMap (`MapView`) and the
 * optional Google base layer (`GoogleMapView`). The page never knows which one it is talking to.
 */
import type { FeatureCollection, Geometry } from "geojson";
import type { Lang, Translate } from "@/lib/i18n";
import type { MapFeatureCollection, MapItemType } from "@/components/visitor/types";

/** A point drawn on top of the approved items: the visitor, a condition report, a picked point, a stop. */
export interface ExtraPoint {
  id: string;
  lat: number;
  lng: number;
  kind: "user" | "report" | "picked" | "stop";
  label: string;
  /** Stop number of an itinerary, shown inside the symbol. */
  order?: number;
}

export interface BaseMapProps {
  /** Approved items from `GET /api/map/features` (WGS84). */
  features: MapFeatureCollection | null;
  /** `item_type:id` of the highlighted item, or null. */
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
  /** Track parsed from `GET /api/trails/{slug}/gpx`. */
  gpx: FeatureCollection<Geometry> | null;
  /** Itinerary route. */
  route: FeatureCollection<Geometry> | null;
  extraPoints: ExtraPoint[];
  /** Called with WGS84 coordinates when the visitor clicks the map (picking a report point). */
  onMapClick?: (lat: number, lng: number) => void;
  pickMode?: boolean;
  lang: Lang;
  t: Translate;
  /** Accessible name of the map region. */
  label: string;
  /** Id of the element that is the map's text alternative (the item list). */
  describedById?: string;
  /** Change this string to re-fit the viewport to the current data. */
  fitKey: string;
}

/** Symbols are shapes first — colour is never the only difference (WCAG 1.4.1). */
export const SYMBOL: Record<MapItemType | ExtraPoint["kind"], string> = {
  heritage_entry: "◆",
  listing: "■",
  trail_segment: "▲",
  user: "◉",
  report: "✚",
  picked: "✕",
  stop: "●",
};
