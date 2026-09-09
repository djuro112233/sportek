/**
 * The state the visitor screens share: the territory, the map data, the selection, the anonymous
 * ids and the geolocation. Passed down as one `ctx` prop so every tab talks to the same map.
 */
import type { FeatureCollection, Geometry } from "geojson";
import type { Lang, Translate } from "@/lib/i18n";
import type { Meta } from "@/lib/api";
import type { ExtraPoint } from "@/components/map/types";
import type { LatLng, MapFeature, MapFeatureCollection, Village } from "./types";

export type GeoState = "idle" | "asking" | "granted" | "denied" | "unsupported" | "error";

export interface VisitorCtx {
  lang: Lang;
  t: Translate;
  meta: Meta | null;
  /** Anonymous, browser-local ids (see `device.ts`). */
  sessionId: string;
  deviceId: string;

  villages: Village[];
  villageBySlug: Map<string, Village>;
  villageById: Map<string, Village>;
  /** Resolve the village of an item from whichever of `village_slug` / `village_id` the API sent. */
  villageOf: (props: { village_slug?: string | null; village_id?: string | null }) => Village | null;

  features: MapFeatureCollection | null;
  featureByKey: Map<string, MapFeature>;
  selectedKey: string | null;
  select: (key: string | null) => void;

  /** Overlays owned by the tabs but drawn by the shared map. */
  setGpx: (fc: FeatureCollection<Geometry> | null) => void;
  setRoute: (fc: FeatureCollection<Geometry> | null) => void;
  setExtraPoints: (points: ExtraPoint[]) => void;
  refit: (reason: string) => void;

  /** Point picking for a trail-condition report. */
  pickMode: boolean;
  setPickMode: (on: boolean) => void;
  pickedPoint: LatLng | null;
  setPickedPoint: (p: LatLng | null) => void;

  userPos: LatLng | null;
  geoState: GeoState;
  requestLocation: () => void;

  /** Polite live-region announcement (selection, picked coordinates, results). */
  announce: (message: string) => void;
  reloadFeatures: () => void;
}
