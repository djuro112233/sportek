"use client";
/**
 * The visitor app: one shared map and the five sections of the contract — Explore, Trails, Ask,
 * Itinerary and Calendar.
 *
 * Everything on this screen comes from endpoints that return **approved rows only**
 * (`docs/api-contract.md`: map, trails, itinerary, requests, ask, villages, heritage calendar,
 * events, meta). The page owns the state the sections share (`VisitorCtx`): the territory, the map
 * data, the selection, the map overlays, the anonymous ids and the geolocation. The base map is
 * loaded by `MapPanel` through `next/dynamic` with `ssr: false`, so nothing touches WebGL on the
 * server.
 *
 * What this screen never does: it never books, never charges, never asks for a name, and never
 * claims that a coordinate is surveyed, that a sample provider is a real business, or that the
 * prototype is in production.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { gpx as gpxToGeoJson } from "@tmcw/togeojson";
import { pick, useLang } from "@/lib/i18n";
import { getMeta, sessionId, type Meta } from "@/lib/api";
import MapPanel from "@/components/map/MapPanel";
import type { ExtraPoint } from "@/components/map/types";
import ItemDetail from "@/components/visitor/ItemDetail";
import Tabs, { panelId, tabId, type TabDef } from "@/components/visitor/Tabs";
import {
  errorMessage,
  getCalendar,
  getMapFeatures,
  getTrailGpx,
  getTrails,
  getVillages,
  postAsk,
  postItinerary,
  postTrailReport,
} from "@/components/visitor/api";
import type { GeoState, VisitorCtx } from "@/components/visitor/context";
import { deviceId } from "@/components/visitor/device";
import {
  fmtDate,
  fmtDistance,
  fmtLatLng,
  fmtMinutes,
  fmtNumber,
  haversineM,
  labelOr,
  localeFor,
} from "@/components/visitor/format";
import { anchorOf, lineCollection } from "@/components/visitor/geo";
import {
  ApproximateBadge,
  ConditionBadge,
  DirectionsButtons,
  ErrorNote,
  SampleBadge,
  TypeChip,
  UnverifiedBadge,
} from "@/components/visitor/ui";
import {
  featureKey,
  HERITAGE_KINDS,
  LISTING_CATEGORIES,
  MAP_ITEM_TYPES,
  MUNICIPALITIES,
  TRAIL_CONDITIONS,
  type AskResponse,
  type CalendarEntry,
  type ItineraryRequest,
  type ItineraryResponse,
  type ItineraryRoute,
  type LatLng,
  type MapFeature,
  type MapFeatureCollection,
  type MapItemType,
  type Trail,
  type TrailCondition,
  type Village,
} from "@/components/visitor/types";
import styles from "@/components/visitor/visitor.module.css";

const TAB_IDS = ["explore", "trails", "ask", "itinerary", "calendar"] as const;
type TabId = (typeof TAB_IDS)[number];
const isTabId = (value: string): value is TabId => (TAB_IDS as readonly string[]).includes(value);

/** The id of the item list — it is the map's text alternative (`aria-describedby`). */
const LIST_ID = "visitor-item-list";
/** "Near me" radius. Deliberately generous: the coordinates are approximate. */
const NEAR_RADIUS_M = 3000;
/** `MAX_ITINERARY_HOURS` of the itinerary service. */
const MAX_HOURS = 12;

interface ExploreItem {
  key: string;
  feature: MapFeature;
  title: string;
  distanceM: number | null;
}

/** Filters of the Explore section. They govern the list *and* the map, so both always agree. */
interface ExploreState {
  village: string;
  setVillage: (value: string) => void;
  municipality: string;
  setMunicipality: (value: string) => void;
  types: MapItemType[];
  toggleType: (value: MapItemType) => void;
  query: string;
  setQuery: (value: string) => void;
  nearOnly: boolean;
  setNearOnly: (value: boolean) => void;
  items: ExploreItem[];
  total: number;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/** GPX text → a collection the map can draw. Returns null when the body is not parsable GPX. */
function parseGpx(text: string): FeatureCollection<Geometry> | null {
  if (typeof DOMParser === "undefined") return null;
  const doc = new DOMParser().parseFromString(text, "application/xml");
  if (doc.getElementsByTagName("parsererror").length > 0) return null;
  const parsed = gpxToGeoJson(doc);
  const features = (parsed.features ?? []).filter((f): f is Feature<Geometry> => f.geometry != null);
  return { type: "FeatureCollection", features };
}

/** The itinerary `route` may arrive as a geometry, a Feature, a FeatureCollection or bare positions. */
function routeToCollection(route: ItineraryRoute | undefined): FeatureCollection<Geometry> | null {
  if (!route) return null;
  if (Array.isArray(route)) return lineCollection(route);
  if (route.type === "FeatureCollection") {
    const features = route.features.filter((f): f is Feature<Geometry> => f.geometry != null);
    return features.length > 0 ? { type: "FeatureCollection", features } : null;
  }
  if (route.type === "Feature") {
    if (!route.geometry) return null;
    return {
      type: "FeatureCollection",
      features: [{ type: "Feature", properties: route.properties ?? {}, geometry: route.geometry }],
    };
  }
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: route }] };
}

export default function VisitorPage() {
  const { lang, t } = useLang();

  /* ---------------------------------------------------------------- anonymous ids (browser only) */
  const [sid, setSid] = useState("");
  const [did, setDid] = useState("");
  useEffect(() => {
    setSid(sessionId());
    setDid(deviceId());
  }, []);

  /* ---------------------------------------------------------------- reference data */
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    let alive = true;
    getMeta().then(
      (m) => {
        if (alive) setMeta(m);
      },
      () => {
        /* the map falls back to OpenStreetMap, which needs no key */
      },
    );
    return () => {
      alive = false;
    };
  }, []);

  const [villages, setVillages] = useState<Village[]>([]);
  useEffect(() => {
    let alive = true;
    getVillages().then(
      (list) => {
        if (alive) setVillages(list);
      },
      () => {
        /* the filters degrade to municipality only */
      },
    );
    return () => {
      alive = false;
    };
  }, []);

  const [features, setFeatures] = useState<MapFeatureCollection | null>(null);
  const [featuresError, setFeaturesError] = useState<string | null>(null);
  const [featuresLoading, setFeaturesLoading] = useState(true);
  const [featuresNonce, setFeaturesNonce] = useState(0);
  const reloadFeatures = useCallback(() => setFeaturesNonce((n) => n + 1), []);

  const [fitKey, setFitKey] = useState("start");
  const refit = useCallback((reason: string) => setFitKey(`${reason}-${Date.now()}`), []);

  useEffect(() => {
    let alive = true;
    setFeaturesLoading(true);
    getMapFeatures().then(
      (fc) => {
        if (!alive) return;
        setFeatures(fc);
        setFeaturesError(null);
        setFeaturesLoading(false);
        refit("features");
      },
      (e: unknown) => {
        if (!alive) return;
        setFeaturesError(errorMessage(e));
        setFeaturesLoading(false);
      },
    );
    return () => {
      alive = false;
    };
  }, [featuresNonce, refit]);

  const villageBySlug = useMemo(() => new Map(villages.map((v) => [v.slug, v])), [villages]);
  const villageById = useMemo(() => new Map(villages.map((v) => [v.id, v])), [villages]);
  const villageOf = useCallback(
    (props: { village_slug?: string | null; village_id?: string | null }): Village | null => {
      if (props.village_slug) {
        const bySlug = villageBySlug.get(props.village_slug);
        if (bySlug) return bySlug;
      }
      if (props.village_id) {
        const byId = villageById.get(props.village_id);
        if (byId) return byId;
      }
      return null;
    },
    [villageBySlug, villageById],
  );

  const featureByKey = useMemo(() => {
    const map = new Map<string, MapFeature>();
    for (const f of features?.features ?? []) if (f.properties) map.set(featureKey(f.properties), f);
    return map;
  }, [features]);

  /* ---------------------------------------------------------------- selection and announcements */
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const select = useCallback((key: string | null) => setSelectedKey(key), []);
  const [announcement, setAnnouncement] = useState("");
  const announce = useCallback((message: string) => setAnnouncement(message), []);

  const announcedRef = useRef<string | null>(null);
  useEffect(() => {
    if (announcedRef.current === selectedKey) return;
    announcedRef.current = selectedKey;
    if (!selectedKey) return;
    const feature = featureByKey.get(selectedKey);
    if (!feature) return;
    announce(
      t("visitor.explore.selectedAnnounce", {
        title: pick(lang, feature.properties.title_local, feature.properties.title_en),
      }),
    );
  }, [selectedKey, featureByKey, announce, lang, t]);

  /* ---------------------------------------------------------------- map overlays */
  const [gpx, setGpx] = useState<FeatureCollection<Geometry> | null>(null);
  const [route, setRoute] = useState<FeatureCollection<Geometry> | null>(null);
  const [sectionPoints, setSectionPoints] = useState<ExtraPoint[]>([]);
  const [pickMode, setPickMode] = useState(false);
  const [pickedPoint, setPickedPoint] = useState<LatLng | null>(null);

  /* ---------------------------------------------------------------- geolocation */
  const [userPos, setUserPos] = useState<LatLng | null>(null);
  const [geoState, setGeoState] = useState<GeoState>("idle");
  const requestLocation = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setGeoState("unsupported");
      return;
    }
    setGeoState("asking");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const point = { lat: position.coords.latitude, lng: position.coords.longitude };
        setUserPos(point);
        setGeoState("granted");
        announce(t("visitor.geo.found", { coords: fmtLatLng(point) }));
      },
      (error) => {
        setGeoState(error.code === error.PERMISSION_DENIED ? "denied" : "error");
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  }, [announce, t]);

  const onMapClick = useCallback(
    (lat: number, lng: number) => {
      setPickedPoint({ lat, lng });
      setPickMode(false);
      announce(t("visitor.trails.pickedAnnounce", { coords: fmtLatLng({ lat, lng }) }));
    },
    [announce, t],
  );

  const extraPoints = useMemo<ExtraPoint[]>(() => {
    const out = [...sectionPoints];
    if (userPos) out.push({ id: "user", lat: userPos.lat, lng: userPos.lng, kind: "user", label: t("visitor.map.you") });
    if (pickedPoint) {
      out.push({
        id: "picked",
        lat: pickedPoint.lat,
        lng: pickedPoint.lng,
        kind: "picked",
        label: t("visitor.trails.pickedLabel"),
      });
    }
    return out;
  }, [sectionPoints, userPos, pickedPoint, t]);

  /* ---------------------------------------------------------------- Explore filters */
  const [fVillage, setFVillage] = useState("");
  const [fMunicipality, setFMunicipality] = useState("");
  const [fTypes, setFTypes] = useState<MapItemType[]>([...MAP_ITEM_TYPES]);
  const [fQuery, setFQuery] = useState("");
  const [fNearOnly, setFNearOnly] = useState(false);

  const toggleType = useCallback((value: MapItemType) => {
    setFTypes((prev) => (prev.includes(value) ? prev.filter((x) => x !== value) : [...prev, value]));
  }, []);

  const items = useMemo<ExploreItem[]>(() => {
    const query = fQuery.trim().toLocaleLowerCase(localeFor(lang));
    const out: ExploreItem[] = [];
    for (const feature of features?.features ?? []) {
      const props = feature.properties;
      if (!props) continue;
      if (!fTypes.includes(props.item_type)) continue;
      if (fVillage) {
        const slugs = new Set<string>(props.village_slugs ?? []);
        if (props.village_slug) slugs.add(props.village_slug);
        const village = villageOf(props);
        if (village) slugs.add(village.slug);
        if (!slugs.has(fVillage)) continue;
      }
      if (fMunicipality) {
        const municipality = props.municipality ?? villageOf(props)?.municipality ?? "";
        if (municipality !== fMunicipality) continue;
      }
      if (query) {
        const haystack = `${props.title_local} ${props.title_en} ${props.summary_local ?? ""} ${props.summary_en ?? ""}`;
        if (!haystack.toLocaleLowerCase(localeFor(lang)).includes(query)) continue;
      }
      const anchor = anchorOf(feature);
      const distanceM = userPos && anchor ? haversineM(userPos, anchor) : null;
      if (fNearOnly && userPos && (distanceM === null || distanceM > NEAR_RADIUS_M)) continue;
      out.push({
        key: featureKey(props),
        feature,
        title: pick(lang, props.title_local, props.title_en),
        distanceM,
      });
    }
    out.sort((a, b) => {
      if (a.distanceM !== null && b.distanceM !== null) return a.distanceM - b.distanceM;
      return a.title.localeCompare(b.title, localeFor(lang));
    });
    return out;
  }, [features, fTypes, fVillage, fMunicipality, fQuery, fNearOnly, userPos, villageOf, lang]);

  const visibleFeatures = useMemo<MapFeatureCollection>(
    () => ({ type: "FeatureCollection", features: items.map((item) => item.feature) }),
    [items],
  );

  const filterSignature = `${fVillage}|${fMunicipality}|${fTypes.join(",")}|${fQuery}|${fNearOnly}`;
  useEffect(() => {
    refit("filters");
  }, [filterSignature, refit]);

  /* ---------------------------------------------------------------- the shared context */
  const ctx = useMemo<VisitorCtx>(
    () => ({
      lang,
      t,
      meta,
      sessionId: sid,
      deviceId: did,
      villages,
      villageBySlug,
      villageById,
      villageOf,
      features,
      featureByKey,
      selectedKey,
      select,
      setGpx,
      setRoute,
      setExtraPoints: setSectionPoints,
      refit,
      pickMode,
      setPickMode,
      pickedPoint,
      setPickedPoint,
      userPos,
      geoState,
      requestLocation,
      announce,
      reloadFeatures,
    }),
    [
      lang,
      t,
      meta,
      sid,
      did,
      villages,
      villageBySlug,
      villageById,
      villageOf,
      features,
      featureByKey,
      selectedKey,
      select,
      refit,
      pickMode,
      pickedPoint,
      userPos,
      geoState,
      requestLocation,
      announce,
      reloadFeatures,
    ],
  );

  const explore: ExploreState = {
    village: fVillage,
    setVillage: setFVillage,
    municipality: fMunicipality,
    setMunicipality: setFMunicipality,
    types: fTypes,
    toggleType,
    query: fQuery,
    setQuery: setFQuery,
    nearOnly: fNearOnly,
    setNearOnly: setFNearOnly,
    items,
    total: features?.features.length ?? 0,
    loading: featuresLoading,
    error: featuresError,
    reload: reloadFeatures,
  };

  const [tab, setTab] = useState<TabId>("explore");
  const tabs: TabDef[] = TAB_IDS.map((id) => ({ id, label: t(`visitor.tab.${id}`) }));

  return (
    <div className="stack">
      <section>
        <h1>{t("visitor.title")}</h1>
        <p>{t("visitor.lead")}</p>
        <p className={styles.note}>{t("visitor.territory")}</p>
        <p className={styles.note}>{t("visitor.honesty")}</p>
      </section>

      <div className={styles.layout}>
        <div>
          <MapPanel
            provider={meta?.maps_provider === "google" ? "google" : "osm"}
            apiKey={meta?.google_maps_api_key ?? ""}
            features={visibleFeatures}
            selectedKey={selectedKey}
            onSelect={select}
            gpx={gpx}
            route={route}
            extraPoints={extraPoints}
            onMapClick={onMapClick}
            pickMode={pickMode}
            lang={lang}
            t={t}
            label={t("visitor.map.label")}
            describedById={LIST_ID}
            fitKey={fitKey}
          />
          {pickMode ? (
            <p className="alert alert-warn small" role="status">
              {t("visitor.trails.pickHint")}
            </p>
          ) : null}
          <p className={styles.note}>{t("visitor.map.coordsNote")}</p>
        </div>

        <div className={styles.panel}>
          <Tabs
            tabs={tabs}
            active={tab}
            onChange={(id) => {
              if (isTabId(id)) setTab(id);
            }}
            label={t("visitor.tabsLabel")}
          />
          {TAB_IDS.map((id) => (
            <div
              key={id}
              role="tabpanel"
              id={panelId(id)}
              aria-labelledby={tabId(id)}
              className={styles.tabpanel}
              tabIndex={0}
              hidden={id !== tab}
            >
              {id === "explore" ? <ExploreSection ctx={ctx} explore={explore} /> : null}
              {id === "trails" ? <TrailsSection ctx={ctx} /> : null}
              {id === "ask" ? <AskSection ctx={ctx} /> : null}
              {id === "itinerary" ? <ItinerarySection ctx={ctx} /> : null}
              {id === "calendar" ? <CalendarSection ctx={ctx} /> : null}
            </div>
          ))}
        </div>
      </div>

      <p className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
}

/* =========================================================================== shared small pieces */

function sortedVillages(lang: VisitorCtx["lang"], villages: Village[]): Village[] {
  return [...villages].sort((a, b) =>
    pick(lang, a.name_local, a.name_en).localeCompare(pick(lang, b.name_local, b.name_en), localeFor(lang)),
  );
}

/** What the browser said about the position, in words — plus what happens to it. */
function GeoNote({ ctx }: { ctx: VisitorCtx }) {
  const { t } = ctx;
  const message =
    ctx.geoState === "asking"
      ? t("visitor.geo.asking")
      : ctx.geoState === "denied"
        ? t("visitor.geo.denied")
        : ctx.geoState === "unsupported"
          ? t("visitor.geo.unsupported")
          : ctx.geoState === "error"
            ? t("visitor.geo.error")
            : ctx.userPos
              ? t("visitor.geo.granted", { coords: fmtLatLng(ctx.userPos) })
              : "";
  return (
    <>
      {message ? (
        <p className="small" role="status">
          {message}
        </p>
      ) : null}
      <p className={styles.note}>{t("visitor.geo.privacy")}</p>
    </>
  );
}

/* =========================================================================== 1. Explore */

function ExploreSection({ ctx, explore }: { ctx: VisitorCtx; explore: ExploreState }) {
  const { t, lang } = ctx;
  const selected = ctx.selectedKey ? (ctx.featureByKey.get(ctx.selectedKey) ?? null) : null;
  const village = explore.village ? (ctx.villageBySlug.get(explore.village) ?? null) : null;

  return (
    <section aria-labelledby="visitor-explore-title">
      <h2 id="visitor-explore-title">{t("visitor.explore.title")}</h2>
      <p className={styles.note}>{t("visitor.explore.lead")}</p>

      <form className={styles.filters} aria-label={t("visitor.explore.filters")} onSubmit={(e) => e.preventDefault()}>
        <div className={styles.filterRow}>
          <label className="field" style={{ flex: "1 1 12rem" }}>
            <span>{t("visitor.explore.village")}</span>
            <select value={explore.village} onChange={(e) => explore.setVillage(e.target.value)}>
              <option value="">{t("visitor.explore.allVillages")}</option>
              {sortedVillages(lang, ctx.villages).map((v) => (
                <option key={v.id} value={v.slug}>
                  {pick(lang, v.name_local, v.name_en)} ({v.municipality})
                </option>
              ))}
            </select>
          </label>
          <label className="field" style={{ flex: "1 1 9rem" }}>
            <span>{t("visitor.explore.municipality")}</span>
            <select value={explore.municipality} onChange={(e) => explore.setMunicipality(e.target.value)}>
              <option value="">{t("visitor.explore.allMunicipalities")}</option>
              {MUNICIPALITIES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="field" style={{ flex: "1 1 12rem" }}>
            <span>{t("visitor.explore.search")}</span>
            <input
              type="search"
              value={explore.query}
              onChange={(e) => explore.setQuery(e.target.value)}
              placeholder={t("visitor.explore.searchPlaceholder")}
            />
          </label>
        </div>

        <fieldset className={styles.checkGroup}>
          <legend>{t("visitor.explore.types")}</legend>
          <div className={styles.checks}>
            {MAP_ITEM_TYPES.map((it) => (
              <label key={it} className={styles.check}>
                <input type="checkbox" checked={explore.types.includes(it)} onChange={() => explore.toggleType(it)} />
                {t(`visitor.type.${it}`)}
              </label>
            ))}
          </div>
        </fieldset>

        <div className={styles.filterRow}>
          <button type="button" className="btn btn-secondary btn-small" onClick={ctx.requestLocation}>
            {t("visitor.explore.nearMe")}
          </button>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={explore.nearOnly}
              disabled={!ctx.userPos}
              onChange={(e) => explore.setNearOnly(e.target.checked)}
            />
            {t("visitor.explore.nearOnly", { km: NEAR_RADIUS_M / 1000 })}
          </label>
          <button type="button" className="btn btn-secondary btn-small" onClick={explore.reload}>
            {t("visitor.explore.reload")}
          </button>
        </div>
        <GeoNote ctx={ctx} />
      </form>

      {village ? (
        <div className="card small">
          <p style={{ margin: 0 }}>
            <strong>{pick(lang, village.name_local, village.name_en)}</strong> · {t("visitor.municipality.label")}:{" "}
            {village.municipality}
            {village.ridge_side
              ? ` · ${t("visitor.village.ridge")}: ${labelOr(t, `visitor.ridge.${village.ridge_side}`, village.ridge_side)}`
              : ""}
            {village.elevation_m != null ? ` · ${fmtNumber(lang, village.elevation_m)} m` : ""}
          </p>
          <p className={styles.inline} style={{ margin: ".35rem 0 0" }}>
            {village.coords_approximate === false ? null : <ApproximateBadge t={t} />}
            {village.facts_verified === false ? <UnverifiedBadge t={t} /> : null}
            {village.n_approved_items != null ? (
              <span className="badge">{t("visitor.village.items", { count: village.n_approved_items })}</span>
            ) : null}
          </p>
          {village.source ? (
            <p className="cite" style={{ marginBottom: 0 }}>
              {t("common.source")}: {village.source}
            </p>
          ) : null}
          {village.verification_note ? (
            <p className="muted small" style={{ margin: ".35rem 0 0" }}>
              {village.verification_note}
            </p>
          ) : null}
        </div>
      ) : null}

      <p className="muted small" role="status">
        {explore.loading
          ? t("common.loading")
          : t("visitor.explore.count", { count: explore.items.length, total: explore.total })}
      </p>
      <ErrorNote message={explore.error} t={t} />

      {!explore.loading && explore.items.length === 0 ? <p className="muted">{t("visitor.explore.empty")}</p> : null}

      <ul className={styles.list} id={LIST_ID} aria-label={t("visitor.explore.listLabel")}>
        {explore.items.map((item) => {
          const props = item.feature.properties;
          const itemVillage = ctx.villageOf(props);
          const meta = [
            itemVillage ? pick(lang, itemVillage.name_local, itemVillage.name_en) : (props.municipality ?? ""),
            t(`visitor.type.${props.item_type}`),
            item.distanceM !== null ? t("visitor.explore.away", { distance: fmtDistance(lang, item.distanceM) }) : "",
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            <li key={item.key}>
              <button
                type="button"
                className={styles.itemButton}
                aria-current={item.key === ctx.selectedKey}
                onClick={() => ctx.select(item.key)}
              >
                <TypeChip itemType={props.item_type} />
                <span>
                  {item.title} {props.is_sample ? <SampleBadge t={t} /> : null}
                  {props.coords_approximate ? <ApproximateBadge t={t} /> : null}
                  <span className={styles.itemMeta}>{meta}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {selected ? (
        <ItemDetail ctx={ctx} feature={selected} />
      ) : (
        <p className="muted small">{t("visitor.explore.selectHint")}</p>
      )}
    </section>
  );
}

/* =========================================================================== 2. Trails */

function TrailsSection({ ctx }: { ctx: VisitorCtx }) {
  const { t, lang, select, setGpx, setExtraPoints, refit, announce } = ctx;
  const [trails, setTrails] = useState<Trail[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [gpxState, setGpxState] = useState<"idle" | "loading" | "ready" | "empty" | "failed">("idle");
  const [condition, setCondition] = useState<TrailCondition>("caution");
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getTrails().then(
      (list) => {
        if (!alive) return;
        setTrails(list);
        setListError(null);
      },
      (e: unknown) => {
        if (!alive) return;
        setTrails([]);
        setListError(errorMessage(e));
      },
    );
    return () => {
      alive = false;
    };
  }, []);

  const open = useCallback(
    async (trail: Trail) => {
      setOpenId(trail.id);
      setSent(false);
      setReportError(null);
      select(`trail_segment:${trail.id}`);
      const report = trail.latest_report;
      const points: ExtraPoint[] = [];
      if (report && report.lat != null && report.lng != null) {
        points.push({
          id: `report-${trail.id}`,
          lat: report.lat,
          lng: report.lng,
          kind: "report",
          label: t("visitor.trails.reportMarker", { trail: pick(lang, trail.name_local, trail.name_en) }),
        });
      }
      setExtraPoints(points);
      setGpxState("loading");
      try {
        const text = await getTrailGpx(trail.slug || trail.id);
        const collection = parseGpx(text);
        if (!collection || collection.features.length === 0) {
          setGpx(null);
          setGpxState("empty");
          return;
        }
        setGpx(collection);
        setGpxState("ready");
        refit("gpx");
        announce(t("visitor.trails.gpxAnnounce", { trail: pick(lang, trail.name_local, trail.name_en) }));
      } catch {
        setGpx(null);
        setGpxState("failed");
      }
    },
    [select, setGpx, setExtraPoints, refit, announce, t, lang],
  );

  const trail = (trails ?? []).find((x) => x.id === openId) ?? null;
  const point = ctx.pickedPoint ?? ctx.userPos;
  const report = trail?.latest_report ?? null;

  const submitReport = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!trail || !point) return;
    setSending(true);
    setReportError(null);
    try {
      await postTrailReport(trail.id, {
        lat: point.lat,
        lng: point.lng,
        condition,
        note: note.trim(),
        lang,
        session_id: ctx.sessionId,
        device_id: ctx.deviceId,
      });
      setSent(true);
      setNote("");
      ctx.setPickedPoint(null);
      announce(t("visitor.trails.sentAnnounce"));
    } catch (e) {
      setReportError(errorMessage(e));
    } finally {
      setSending(false);
    }
  };

  return (
    <section aria-labelledby="visitor-trails-title">
      <h2 id="visitor-trails-title">{t("visitor.trails.title")}</h2>
      <p className={styles.note}>{t("visitor.trails.lead")}</p>

      <ErrorNote message={listError} t={t} />
      {trails === null ? (
        <p className="muted" role="status">
          {t("common.loading")}
        </p>
      ) : trails.length === 0 ? (
        <p className="muted">{t("visitor.trails.empty")}</p>
      ) : (
        <ul className={styles.list} aria-label={t("visitor.trails.listLabel")}>
          {trails.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={styles.itemButton}
                aria-current={item.id === openId}
                onClick={() => void open(item)}
              >
                <TypeChip itemType="trail_segment" />
                <span>
                  {pick(lang, item.name_local, item.name_en)}
                  <span className={styles.itemMeta}>
                    {[
                      item.from_name && item.to_name ? `${item.from_name} → ${item.to_name}` : "",
                      item.length_m != null ? fmtDistance(lang, item.length_m) : "",
                      labelOr(t, `visitor.difficulty.${item.difficulty ?? "unknown"}`, item.difficulty),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {trail ? (
        <div className={styles.detail}>
          <h3>{pick(lang, trail.name_local, trail.name_en)}</h3>
          {pick(lang, trail.description_local, trail.description_en) ? (
            <p>{pick(lang, trail.description_local, trail.description_en)}</p>
          ) : null}

          <dl className={styles.facts}>
            <dt>{t("visitor.trails.route")}</dt>
            <dd>{trail.from_name && trail.to_name ? `${trail.from_name} → ${trail.to_name}` : "—"}</dd>
            <dt>{t("visitor.trail.length")}</dt>
            <dd>{trail.length_m != null ? fmtDistance(lang, trail.length_m) : "—"}</dd>
            <dt>{t("visitor.trail.ascent")}</dt>
            <dd>{trail.ascent_m != null ? `${fmtNumber(lang, trail.ascent_m)} m` : "—"}</dd>
            <dt>{t("visitor.trail.difficulty")}</dt>
            <dd>{labelOr(t, `visitor.difficulty.${trail.difficulty ?? "unknown"}`, trail.difficulty)}</dd>
          </dl>

          <p className="small" role="status">
            {gpxState === "loading"
              ? t("visitor.trails.gpxLoading")
              : gpxState === "ready"
                ? t("visitor.trails.gpxReady")
                : gpxState === "empty"
                  ? t("visitor.trails.gpxEmpty")
                  : gpxState === "failed"
                    ? t("visitor.trails.gpxFailed")
                    : ""}
          </p>

          <h4>{t("visitor.trail.latestReport")}</h4>
          {report ? (
            <div className="card small">
              <p className={styles.inline} style={{ margin: 0 }}>
                <ConditionBadge
                  condition={report.condition}
                  t={t}
                  date={report.reported_at ? fmtDate(lang, report.reported_at) : undefined}
                />
                {report.reporter_role ? (
                  <span className="muted">
                    {t("visitor.trails.reporter")}: {labelOr(t, `visitor.role.${report.reporter_role}`, report.reporter_role)}
                  </span>
                ) : null}
              </p>
              {pick(lang, report.note_local, report.note_en) ? (
                <p style={{ margin: ".35rem 0 0" }}>{pick(lang, report.note_local, report.note_en)}</p>
              ) : null}
              {report.lat != null && report.lng != null ? (
                <p className="muted small" style={{ margin: ".35rem 0 0" }}>
                  {fmtLatLng({ lat: report.lat, lng: report.lng })}
                </p>
              ) : null}
            </div>
          ) : (
            <p className="muted small">{t("visitor.trails.noReport")}</p>
          )}

          <h4>{t("common.directions")}</h4>
          <DirectionsButtons
            lat={trail.lat}
            lng={trail.lng}
            t={t}
            title={pick(lang, trail.name_local, trail.name_en)}
          />

          <h4>{t("visitor.trails.reportTitle")}</h4>
          <p className={styles.note}>{t("visitor.trails.reportHelp")}</p>
          <form onSubmit={submitReport}>
            <fieldset className={styles.checkGroup}>
              <legend>{t("visitor.trails.condition")}</legend>
              <div className={styles.checks}>
                {TRAIL_CONDITIONS.map((value) => (
                  <label key={value} className={styles.check}>
                    <input
                      type="radio"
                      name="visitor-trail-condition"
                      value={value}
                      checked={condition === value}
                      onChange={() => setCondition(value)}
                    />
                    {t(`visitor.condition.${value}`)}
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="field">
              <span>{t("visitor.trails.note")}</span>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={1000}
                placeholder={t("visitor.trails.notePlaceholder")}
              />
            </label>

            <p className="small" style={{ marginBottom: ".25rem" }}>
              {t("visitor.trails.point")}: <strong>{point ? fmtLatLng(point) : t("visitor.trails.pointNone")}</strong>
            </p>
            <div className={styles.filterRow}>
              <button
                type="button"
                className="btn btn-secondary btn-small"
                onClick={() => ctx.setPickMode(!ctx.pickMode)}
                aria-pressed={ctx.pickMode}
              >
                {ctx.pickMode ? t("visitor.trails.pickCancel") : t("visitor.trails.pickOnMap")}
              </button>
              <button type="button" className="btn btn-secondary btn-small" onClick={ctx.requestLocation}>
                {t("visitor.trails.useMyLocation")}
              </button>
            </div>

            <button type="submit" className="btn btn-primary" disabled={sending || !point}>
              {sending ? t("visitor.trails.sending") : t("visitor.trails.send")}
            </button>
          </form>

          {sent ? (
            <p className="alert alert-ok small" role="status">
              {t("visitor.trails.sentHelp")}
            </p>
          ) : null}
          {reportError ? (
            <p className="alert alert-danger small" role="alert">
              {t("common.error", { message: reportError })}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="muted small">{t("visitor.trails.selectHint")}</p>
      )}
    </section>
  );
}

/* =========================================================================== 3. Ask */

interface AskTurn {
  id: number;
  question: string;
  answer: AskResponse;
}

function AskSection({ ctx }: { ctx: VisitorCtx }) {
  const { t } = ctx;
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const nextId = useRef(1);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const asked = question.trim();
    if (!asked) return;
    setAsking(true);
    setError(null);
    try {
      const answer = await postAsk({
        question: asked,
        lang: ctx.lang,
        session_id: ctx.sessionId,
        device_id: ctx.deviceId,
      });
      setTurns((prev) => [{ id: nextId.current++, question: asked, answer }, ...prev]);
      setQuestion("");
      ctx.announce(answer.answered ? t("visitor.ask.answeredAnnounce") : t("visitor.ask.refusedAnnounce"));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setAsking(false);
    }
  };

  return (
    <section aria-labelledby="visitor-ask-title">
      <h2 id="visitor-ask-title">{t("visitor.ask.title")}</h2>
      <p className={styles.note}>{t("visitor.ask.lead")}</p>
      <p className="alert alert-warn small">{t("visitor.ask.rule")}</p>

      <form onSubmit={submit}>
        <label className="field">
          <span>{t("visitor.ask.question")}</span>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={500}
            required
            placeholder={t("visitor.ask.questionPlaceholder")}
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={asking || !question.trim()}>
          {asking ? t("visitor.ask.sending") : t("visitor.ask.send")}
        </button>
      </form>

      <ErrorNote message={error} t={t} />

      {turns.length === 0 ? (
        <p className="muted small">{t("visitor.ask.empty")}</p>
      ) : (
        <div className={styles.history}>
          {turns.map((turn) => (
            <AskTurnView key={turn.id} ctx={ctx} turn={turn} />
          ))}
        </div>
      )}
    </section>
  );
}

function AskTurnView({ ctx, turn }: { ctx: VisitorCtx; turn: AskTurn }) {
  const { t, lang } = ctx;
  const answer = turn.answer;
  const reason = answer.refusal_reason ?? "";
  const paused = reason === "assistant_paused";

  return (
    <article className="card" style={{ marginBottom: ".75rem" }}>
      <h3 style={{ marginTop: 0 }}>{turn.question}</h3>

      {answer.answered && answer.answer ? (
        <>
          <p className={styles.answer}>{answer.answer}</p>
          <p className={styles.note}>{t("visitor.ask.grounded")}</p>
        </>
      ) : (
        <>
          <p className="alert alert-warn" role="status">
            {answer.refusal_message || t("visitor.ask.refusedFallback")}
          </p>
          <p className={styles.note}>{paused ? t("visitor.ask.pausedExplain") : t("visitor.ask.refusedExplain")}</p>
          {reason ? (
            <p className="small muted">
              {t("visitor.ask.reasonLabel")}: {labelOr(t, `visitor.ask.reason.${reason}`, reason)}
            </p>
          ) : null}
        </>
      )}

      {answer.dropped_sentences ? (
        <p className="alert alert-warn small">{t("visitor.ask.dropped", { count: answer.dropped_sentences })}</p>
      ) : null}

      <h4>{t("visitor.ask.citationsTitle")}</h4>
      {answer.citations.length === 0 ? (
        <p className="muted small">{t("visitor.ask.noCitations")}</p>
      ) : (
        <ul className={styles.sources}>
          {answer.citations.map((citation, index) => {
            const key = `heritage_entry:${citation.entry_id}`;
            const onMap = ctx.featureByKey.has(key);
            const village = citation.village_slug ? ctx.villageBySlug.get(citation.village_slug) : undefined;
            return (
              <li key={`${citation.entry_id}-${citation.chunk_index ?? index}`} className="cite">
                <p style={{ margin: 0 }}>
                  <strong>{citation.title}</strong>
                  {village ? ` · ${pick(lang, village.name_local, village.name_en)}` : ""}
                </p>
                <p className="small" style={{ margin: 0 }}>
                  {citation.excerpt}
                </p>
                <p className="small muted" style={{ margin: 0 }}>
                  {t("common.source")}: {citation.source}
                  {citation.entry_version != null ? ` · ${t("visitor.ask.version", { version: citation.entry_version })}` : ""}
                </p>
                {onMap ? (
                  <button type="button" className="btn btn-secondary btn-small" onClick={() => ctx.select(key)}>
                    {t("visitor.showOnMap")}
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {answer.support && answer.support.length > 0 ? (
        <details>
          <summary>{t("visitor.ask.supportTitle", { count: answer.support.length })}</summary>
          <p className={styles.note}>{t("visitor.ask.supportHelp")}</p>
          <ul className="small">
            {answer.support.map((sentence, index) => (
              <li key={`${index}-${sentence.sentence.slice(0, 24)}`}>
                <span aria-hidden="true">{sentence.supported ? "✓" : "✕"}</span> {sentence.sentence}{" "}
                <span className="muted">
                  {sentence.supported ? t("visitor.ask.supported") : t("visitor.ask.unsupported")}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <p className="small muted" style={{ marginBottom: 0 }}>
        {answer.confidence != null ? `${t("visitor.ask.confidence")}: ${fmtNumber(lang, answer.confidence, { maximumFractionDigits: 2 })} · ` : ""}
        {answer.served_from_cache ? `${t("visitor.ask.cache")} · ` : ""}
        {t("visitor.ask.provider", {
          llm: answer.provider?.llm ?? "—",
          embeddings: answer.provider?.embeddings ?? "—",
          support: answer.provider?.support_check ?? "—",
        })}
      </p>
    </article>
  );
}

/* =========================================================================== 4. Itinerary */

function ItinerarySection({ ctx }: { ctx: VisitorCtx }) {
  const { t, lang, setRoute, setExtraPoints, refit, announce } = ctx;
  const [interests, setInterests] = useState<string[]>([]);
  const [hours, setHours] = useState(3);
  const [chosenVillages, setChosenVillages] = useState<string[]>([]);
  const [municipality, setMunicipality] = useState("");
  const [startHere, setStartHere] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ItineraryResponse | null>(null);

  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((x) => x !== value) : [...list, value];

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPlanning(true);
    setError(null);
    try {
      const body: ItineraryRequest = {
        interests,
        hours,
        villages: chosenVillages.length > 0 ? chosenVillages : undefined,
        municipality: municipality || undefined,
        start: startHere && ctx.userPos ? ctx.userPos : undefined,
        lang,
        session_id: ctx.sessionId,
        device_id: ctx.deviceId,
      };
      const plan = await postItinerary(body);
      setResult(plan);
      setRoute(routeToCollection(plan.route));
      setExtraPoints(
        plan.stops
          .filter((stop) => stop.lat != null && stop.lng != null)
          .map((stop, index) => ({
            id: `stop-${stop.id ?? index}`,
            lat: stop.lat as number,
            lng: stop.lng as number,
            kind: "stop" as const,
            order: stop.order ?? index + 1,
            label: t("visitor.itinerary.stopLabel", {
              order: stop.order ?? index + 1,
              title: stop.title || pick(lang, stop.title_local, stop.title_en),
            }),
          })),
      );
      refit("route");
      announce(t("visitor.itinerary.doneAnnounce", { count: plan.stops.length }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPlanning(false);
    }
  };

  const clear = () => {
    setResult(null);
    setRoute(null);
    setExtraPoints([]);
    refit("clear");
  };

  return (
    <section aria-labelledby="visitor-itinerary-title">
      <h2 id="visitor-itinerary-title">{t("visitor.itinerary.title")}</h2>
      <p className={styles.note}>{t("visitor.itinerary.lead")}</p>

      <form onSubmit={submit}>
        <fieldset className={styles.checkGroup}>
          <legend>{t("visitor.itinerary.interestsHeritage")}</legend>
          <div className={styles.checks}>
            {HERITAGE_KINDS.map((kind) => (
              <label key={kind} className={styles.check}>
                <input
                  type="checkbox"
                  checked={interests.includes(kind)}
                  onChange={() => setInterests((prev) => toggle(prev, kind))}
                />
                {t(`visitor.kind.${kind}`)}
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className={styles.checkGroup}>
          <legend>{t("visitor.itinerary.interestsListing")}</legend>
          <div className={styles.checks}>
            {LISTING_CATEGORIES.map((category) => (
              <label key={category} className={styles.check}>
                <input
                  type="checkbox"
                  checked={interests.includes(category)}
                  onChange={() => setInterests((prev) => toggle(prev, category))}
                />
                {t(`visitor.category.${category}`)}
              </label>
            ))}
          </div>
        </fieldset>
        <p className={styles.note}>{t("visitor.itinerary.interestsHint")}</p>

        <label className="field">
          <span>{t("visitor.itinerary.hours", { hours })}</span>
          <input
            className={styles.slider}
            type="range"
            min={1}
            max={MAX_HOURS}
            step={1}
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          />
        </label>

        <fieldset className={styles.checkGroup}>
          <legend>{t("visitor.itinerary.villages")}</legend>
          <div className={styles.checks}>
            {sortedVillages(lang, ctx.villages).map((village) => (
              <label key={village.id} className={styles.check}>
                <input
                  type="checkbox"
                  checked={chosenVillages.includes(village.slug)}
                  onChange={() => setChosenVillages((prev) => toggle(prev, village.slug))}
                />
                {pick(lang, village.name_local, village.name_en)}
              </label>
            ))}
          </div>
        </fieldset>
        <p className={styles.note}>{t("visitor.itinerary.villagesHint")}</p>

        <label className="field">
          <span>{t("visitor.explore.municipality")}</span>
          <select value={municipality} onChange={(e) => setMunicipality(e.target.value)}>
            <option value="">{t("visitor.explore.allMunicipalities")}</option>
            {MUNICIPALITIES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>

        <div className={styles.filterRow}>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={startHere}
              disabled={!ctx.userPos}
              onChange={(e) => setStartHere(e.target.checked)}
            />
            {t("visitor.itinerary.startHere")}
          </label>
          <button type="button" className="btn btn-secondary btn-small" onClick={ctx.requestLocation}>
            {t("visitor.explore.nearMe")}
          </button>
        </div>
        <p className={styles.note}>{t("visitor.itinerary.startHereHelp")}</p>

        <div className={styles.filterRow}>
          <button type="submit" className="btn btn-primary" disabled={planning}>
            {planning ? t("visitor.itinerary.planning") : t("visitor.itinerary.plan")}
          </button>
          {result ? (
            <button type="button" className="btn btn-secondary btn-small" onClick={clear}>
              {t("visitor.itinerary.clear")}
            </button>
          ) : null}
        </div>
      </form>

      <ErrorNote message={error} t={t} />

      {result ? (
        <div className={styles.detail}>
          <h3>{t("visitor.itinerary.resultTitle")}</h3>
          <p className={styles.inline}>
            {result.multi_village ? (
              <span className="badge badge-approved">{t("visitor.itinerary.multiVillage")}</span>
            ) : (
              <span className="badge">{t("visitor.itinerary.singleVillage")}</span>
            )}
            {(result.municipalities ?? []).length > 1 ? (
              <span className="badge badge-approved">{t("visitor.itinerary.multiMunicipality")}</span>
            ) : null}
          </p>
          <p className="small">
            {t("visitor.itinerary.totals", {
              stops: result.stops.length,
              km: fmtNumber(lang, result.total_km ?? null, { maximumFractionDigits: 1 }),
              hours: fmtNumber(lang, result.est_hours ?? null, { maximumFractionDigits: 1 }),
            })}
          </p>
          {(result.villages ?? []).length > 0 ? (
            <p className="small">
              {t("visitor.itinerary.villagesLine", {
                villages: (result.villages ?? [])
                  .map((slug) => {
                    const village = ctx.villageBySlug.get(slug);
                    return village ? pick(lang, village.name_local, village.name_en) : slug;
                  })
                  .join(", "),
              })}
            </p>
          ) : null}
          {(result.municipalities ?? []).length > 0 ? (
            <p className="small">
              {t("visitor.itinerary.municipalitiesLine", { municipalities: (result.municipalities ?? []).join(", ") })}
            </p>
          ) : null}
          <p className={styles.note}>{t("visitor.itinerary.multiVillageHelp")}</p>

          {result.stops.length === 0 ? (
            <p className="muted">{t("visitor.itinerary.noStops")}</p>
          ) : (
            <ol className={styles.stops} aria-label={t("visitor.itinerary.stopsLabel")}>
              {result.stops.map((stop, index) => {
                const village = ctx.villageOf({ village_slug: stop.village_slug ?? null });
                const title = stop.title || pick(lang, stop.title_local, stop.title_en);
                const key = stop.item_type && stop.id ? `${stop.item_type}:${stop.id}` : null;
                return (
                  <li key={`${stop.id ?? index}-${index}`} className={styles.requestCard}>
                    <p className={styles.inline} style={{ margin: 0 }}>
                      <span className={styles.stopNumber} aria-hidden="true">
                        {stop.order ?? index + 1}
                      </span>
                      <strong>{title}</strong>
                    </p>
                    <p className="small muted" style={{ margin: ".25rem 0 0" }}>
                      {[
                        village ? pick(lang, village.name_local, village.name_en) : (stop.village_slug ?? ""),
                        stop.municipality ?? "",
                        stop.minutes_from_previous != null
                          ? t("visitor.itinerary.walkFromPrevious", {
                              minutes: fmtMinutes(lang, stop.minutes_from_previous),
                            })
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                    {pick(lang, stop.summary_local, stop.summary_en) ? (
                      <p className="small" style={{ margin: ".25rem 0 0" }}>
                        {pick(lang, stop.summary_local, stop.summary_en)}
                      </p>
                    ) : null}
                    <DirectionsButtons
                      lat={stop.lat}
                      lng={stop.lng}
                      walking={stop.directions_url}
                      t={t}
                      title={title}
                    />
                    {key && ctx.featureByKey.has(key) ? (
                      <button type="button" className="btn btn-secondary btn-small" onClick={() => ctx.select(key)}>
                        {t("visitor.showOnMap")}
                      </button>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      ) : null}
    </section>
  );
}

/* =========================================================================== 5. Calendar */

function CalendarSection({ ctx }: { ctx: VisitorCtx }) {
  const { t, lang } = ctx;
  const [entries, setEntries] = useState<CalendarEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getCalendar().then(
      (list) => {
        if (!alive) return;
        setEntries(list);
        setError(null);
      },
      (e: unknown) => {
        if (!alive) return;
        setEntries([]);
        setError(errorMessage(e));
      },
    );
    return () => {
      alive = false;
    };
  }, []);

  return (
    <section aria-labelledby="visitor-calendar-title">
      <h2 id="visitor-calendar-title">{t("visitor.calendar.title")}</h2>
      <p className={styles.note}>{t("visitor.calendar.lead")}</p>
      <ErrorNote message={error} t={t} />

      {entries === null ? (
        <p className="muted" role="status">
          {t("common.loading")}
        </p>
      ) : entries.length === 0 ? (
        <p className="muted">{t("visitor.calendar.empty")}</p>
      ) : (
        <ul className={`${styles.stops} ${styles.scroll}`} aria-label={t("visitor.calendar.listLabel")}>
          {entries.map((entry) => {
            const key = `heritage_entry:${entry.id}`;
            const village = ctx.villageOf({ village_slug: entry.village_slug, village_id: entry.village_id });
            return (
              <li key={entry.id} className={styles.requestCard}>
                <p style={{ margin: 0 }}>
                  <strong>{pick(lang, entry.title_local, entry.title_en)}</strong>
                </p>
                <p className="small muted" style={{ margin: ".25rem 0 0" }}>
                  {[
                    entry.event_date ? `${t("visitor.calendar.date")}: ${fmtDate(lang, entry.event_date)}` : t("visitor.calendar.noDate"),
                    entry.recurrence_rule ? `${t("visitor.calendar.recurrence")}: ${entry.recurrence_rule}` : "",
                    village
                      ? `${pick(lang, village.name_local, village.name_en)} (${village.municipality})`
                      : (entry.municipality ?? ""),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {pick(lang, entry.summary_local, entry.summary_en) ? (
                  <p className="small" style={{ margin: ".25rem 0 0" }}>
                    {pick(lang, entry.summary_local, entry.summary_en)}
                  </p>
                ) : null}
                <p className={styles.inline} style={{ margin: ".35rem 0 0" }}>
                  {entry.coords_approximate ? <ApproximateBadge t={t} /> : null}
                  {entry.facts_verified === false ? <UnverifiedBadge t={t} /> : null}
                </p>
                <p className="cite small" style={{ margin: ".35rem 0 0" }}>
                  {t("common.source")}: {entry.source || t("visitor.source.missing")}
                </p>
                {ctx.featureByKey.has(key) ? (
                  <button type="button" className="btn btn-secondary btn-small" onClick={() => ctx.select(key)}>
                    {t("visitor.showOnMap")}
                  </button>
                ) : (
                  <p className="muted small" style={{ margin: ".35rem 0 0" }}>
                    {t("visitor.calendar.notOnMap")}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
