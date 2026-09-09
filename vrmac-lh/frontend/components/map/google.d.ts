/**
 * Minimal ambient declarations for the optional Google Maps JavaScript API base layer.
 *
 * The prototype installs no npm packages, so `@types/google.maps` is not available; this file
 * declares only the handful of members `GoogleMapView.tsx` actually uses. It is deliberately narrow:
 * anything not declared here is not used. The Google layer is only ever loaded when
 * `GET /api/meta` reports `maps_provider === "google"` **and** a key is configured; the default and
 * the fallback is MapLibre GL over OpenStreetMap, which needs no key at all.
 *
 * This is a global script file (no top-level import/export) so the declarations are ambient.
 */

declare namespace google.maps {
  interface LatLngLiteral {
    lat: number;
    lng: number;
  }

  class LatLng {
    constructor(lat: number, lng: number);
    lat(): number;
    lng(): number;
  }

  class LatLngBounds {
    constructor();
    extend(point: LatLngLiteral | LatLng): LatLngBounds;
    isEmpty(): boolean;
  }

  interface Padding {
    top: number;
    right: number;
    bottom: number;
    left: number;
  }

  interface MapMouseEvent {
    latLng: LatLng | null;
  }

  interface MapsEventListener {
    remove(): void;
  }

  interface MapOptions {
    center?: LatLngLiteral;
    zoom?: number;
    mapTypeId?: string;
    mapTypeControl?: boolean;
    streetViewControl?: boolean;
    fullscreenControl?: boolean;
    scaleControl?: boolean;
    clickableIcons?: boolean;
    draggableCursor?: string;
    gestureHandling?: string;
    maxZoom?: number;
    [key: string]: unknown;
  }

  class Map {
    constructor(element: HTMLElement, options?: MapOptions);
    setOptions(options: MapOptions): void;
    setCenter(latLng: LatLngLiteral | LatLng): void;
    setZoom(zoom: number): void;
    getZoom(): number | undefined;
    fitBounds(bounds: LatLngBounds, padding?: number | Padding): void;
    addListener(eventName: string, handler: (event: MapMouseEvent) => void): MapsEventListener;
  }

  interface MarkerLabel {
    text: string;
    color?: string;
    fontSize?: string;
    fontWeight?: string;
  }

  interface MarkerOptions {
    position: LatLngLiteral;
    map?: Map | null;
    title?: string;
    label?: string | MarkerLabel;
    zIndex?: number;
    optimized?: boolean;
    [key: string]: unknown;
  }

  class Marker {
    constructor(options?: MarkerOptions);
    setMap(map: Map | null): void;
    setOptions(options: Partial<MarkerOptions>): void;
    addListener(eventName: string, handler: () => void): MapsEventListener;
  }

  interface PolylineOptions {
    path: LatLngLiteral[];
    map?: Map | null;
    strokeColor?: string;
    strokeOpacity?: number;
    strokeWeight?: number;
    zIndex?: number;
    icons?: unknown[];
    clickable?: boolean;
    [key: string]: unknown;
  }

  class Polyline {
    constructor(options?: PolylineOptions);
    setMap(map: Map | null): void;
    addListener(eventName: string, handler: () => void): MapsEventListener;
  }
}

interface Window {
  google?: typeof google;
}
