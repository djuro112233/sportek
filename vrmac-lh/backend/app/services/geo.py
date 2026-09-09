"""Geo services for innovation claim #5 — interactive map, directions, GPX trails, itinerary.

Everything visitor-facing here reads through the row-level-security-limited visitor session
(``get_public_db``) **and** filters with ``validation.approved_only`` (belt and braces), so a draft,
reviewed or rejected item can never reach the map, a GPX download or an itinerary.

**Territory.** The prototype covers Vrmac on both sides of the ridge. Every heritage entry, listing
and trail segment belongs to a :class:`~app.models.Village` which carries its municipality (Tivat or
Kotor); a trail segment additionally lists every village it connects (``village_slugs``). Every map
feature and every itinerary stop therefore carries ``village_slug`` and ``municipality``, and an
itinerary may span villages and municipalities (``multi_village``).

**Coordinates** are WGS84: ``lat``/``lng`` on the models, ``[lng, lat, ele]`` in GeoJSON. Seed
coordinates are hand-placed and marked ``coords_approximate=True``; every feature carries that flag
plus ``coords_source`` so the interface can say so instead of implying survey accuracy.

**Directions** are Google Maps *navigation* deep links — no API key, no server-side routing, no
request to Google from our servers and no visitor coordinates leaving the device:
``https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>&travelmode=walking|driving``.
"""
from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gpxpy
import gpxpy.gpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import HeritageEntry, Listing, TrailReport, TrailSegment, Village
from . import content
from .validation import approved_only

# --- constants -------------------------------------------------------------------------------

DIRECTIONS_BASE = "https://www.google.com/maps/dir/?api=1"
TRAVEL_MODES: tuple[str, ...] = ("walking", "driving")

MAP_ITEM_TYPES: tuple[str, ...] = ("heritage_entry", "listing", "trail_segment")

HERITAGE_KINDS: tuple[str, ...] = (
    "place", "church", "building", "event", "tradition", "institution", "landscape",
)
LISTING_CATEGORIES: tuple[str, ...] = (
    "accommodation", "food", "guiding", "craft", "experience", "transport", "other",
)
#: Values accepted in an itinerary's ``interests`` list (heritage kinds + listing categories).
INTEREST_VALUES: tuple[str, ...] = HERITAGE_KINDS + LISTING_CATEGORIES
#: Convenience aliases so a client may send a plural or a group name.
INTEREST_ALIASES: dict[str, tuple[str, ...]] = {
    "places": ("place",),
    "churches": ("church",),
    "buildings": ("building",),
    "events": ("event",),
    "festivals": ("event",),
    "traditions": ("tradition",),
    "institutions": ("institution",),
    "landscapes": ("landscape",),
    "nature": ("landscape",),
    "heritage": HERITAGE_KINDS,
    "culture": ("church", "building", "tradition", "institution"),
    "providers": LISTING_CATEGORIES,
    "hosts": LISTING_CATEGORIES,
    "stay": ("accommodation",),
    "accommodations": ("accommodation",),
    "eat": ("food",),
    "guides": ("guiding",),
    "crafts": ("craft",),
    "experiences": ("experience",),
}

#: Default itinerary start — the shore trailhead in Donja Lastva (approximate).
DEFAULT_START: tuple[float, float] = (42.4400, 18.6850)
WALK_KMH = 4.0  # average walking speed used for the time estimate
DETOUR_FACTOR = 1.3  # straight line × 1.3 ≈ path distance on the Vrmac slopes
MINUTES_PER_STOP = 20  # time spent at each stop
EARTH_RADIUS_M = 6_371_000.0
MAX_ITINERARY_HOURS = 12

GPX_CREATOR = "VRMAC-LH prototype (sample, approximate)"
GPX_MEDIA_TYPE = "application/gpx+xml"

#: Where a feature's coordinates come from, when the model has no ``coords_source`` column.
LISTING_COORDS_SOURCE = "host-entered (approximate)"

COORDS_NOTE = {
    "cnr": "Koordinate uzoraka podataka su približne (coords_approximate=true).",
    "en": "Coordinates of the sample data are approximate (coords_approximate=true).",
}

# Localised one-liners explaining why a stop is on the itinerary (by heritage kind / listing category).
WHY_BY_KIND: dict[str, dict[str, str]] = {
    "place": {"cnr": "Mjesto iz baštine Vrmca", "en": "A heritage place on Vrmac"},
    "church": {"cnr": "Crkva — sakralna baština", "en": "Church — sacred heritage"},
    "building": {"cnr": "Građevina iz baštine", "en": "Heritage building"},
    "event": {"cnr": "Manifestacija zajednice", "en": "Community festival or event"},
    "tradition": {"cnr": "Živa tradicija kraja", "en": "Living tradition of the area"},
    "institution": {"cnr": "Ustanova zajednice", "en": "Community institution"},
    "landscape": {"cnr": "Kulturni pejzaž Vrmca", "en": "Cultural landscape of Vrmac"},
    "accommodation": {"cnr": "Smještaj kod lokalnog domaćina", "en": "Stay with a local host"},
    "food": {"cnr": "Domaća hrana i konoba", "en": "Local food and tavern"},
    "guiding": {"cnr": "Vođena šetnja s lokalnim vodičem", "en": "Guided walk with a local guide"},
    "craft": {"cnr": "Zanat i radionica", "en": "Craft and workshop"},
    "experience": {"cnr": "Lokalno iskustvo", "en": "Local experience"},
    "transport": {"cnr": "Lokalni prevoz", "en": "Local transport"},
    "other": {"cnr": "Lokalna ponuda", "en": "Local offer"},
}


# --- pure helpers ----------------------------------------------------------------------------


def directions_url(lat: float, lng: float, mode: str = "walking") -> str:
    """Google Maps navigation deep link to ``lat, lng``.

    The format is fixed by the innovation claim (real Google routing, opened on the visitor's own
    device, no API key and no server-side routing)::

        https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>&travelmode=walking|driving

    Coordinates are rounded to 6 decimals (≈0.1 m — far finer than our approximate seed data) so the
    links stay short and stable.
    """
    if mode not in TRAVEL_MODES:
        raise ValueError(f"travel mode must be one of {TRAVEL_MODES}, got {mode!r}")
    lat_f, lng_f = float(lat), float(lng)
    if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lng_f <= 180.0):
        raise ValueError("coordinates out of WGS84 range")
    return f"{DIRECTIONS_BASE}&destination={round(lat_f, 6)},{round(lng_f, 6)}&travelmode={mode}"


def directions_pair(lat: float | None, lng: float | None) -> tuple[str | None, str | None]:
    """``(walking_url, driving_url)`` — ``(None, None)`` when the item has no coordinates."""
    if lat is None or lng is None:
        return None, None
    return directions_url(lat, lng, "walking"), directions_url(lat, lng, "driving")


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between two ``(lat, lng)`` points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(d))


def _positions(geometry: dict | None) -> list[Sequence[float]]:
    """Every ``[lng, lat, ele?]`` position of a GeoJSON geometry (empty for an unknown type)."""
    if not geometry:
        return []
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Point":
        return [coords] if coords else []
    if kind in ("LineString", "MultiPoint"):
        return list(coords)
    if kind in ("Polygon", "MultiLineString"):
        return [p for ring in coords for p in ring]
    return []


def bounding_box(features_: Iterable[dict]) -> list[float] | None:
    """GeoJSON ``bbox`` (``[min_lng, min_lat, max_lng, max_lat]``), or None when nothing has geometry."""
    min_lng = min_lat = math.inf
    max_lng = max_lat = -math.inf
    found = False
    for f in features_:
        for pos in _positions(f.get("geometry")):
            if len(pos) < 2:
                continue
            found = True
            lng, lat = float(pos[0]), float(pos[1])
            min_lng, max_lng = min(min_lng, lng), max(max_lng, lng)
            min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
    return [min_lng, min_lat, max_lng, max_lat] if found else None


def trail_start(seg: TrailSegment) -> tuple[float, float] | None:
    """``(lat, lng)`` of a segment's start: the stored start point, else the first geometry vertex."""
    if seg.lat is not None and seg.lng is not None:
        return float(seg.lat), float(seg.lng)
    pos = _positions(seg.geometry)
    if pos and len(pos[0]) >= 2:
        return float(pos[0][1]), float(pos[0][0])
    return None


def localized(lang: str, local: str, en: str) -> str:
    """Text for ``lang`` (``cnr`` → ``*_local``), falling back to the other language."""
    if lang == "en":
        return en or local
    return local or en


def gpx_url(seg: TrailSegment) -> str:
    return f"/api/trails/{seg.slug}/gpx"


# --- territory -------------------------------------------------------------------------------


def villages_by_id(db: Session) -> dict[uuid.UUID, Village]:
    """``{id: Village}`` for the whole territory (reference data, readable by the visitor role)."""
    return {v.id: v for v in db.scalars(select(Village).order_by(Village.slug))}


def villages_by_slug(db: Session) -> dict[str, Village]:
    return {v.slug: v for v in db.scalars(select(Village).order_by(Village.slug))}


def segment_villages(seg: TrailSegment, by_id: dict, by_slug: dict) -> list[Village]:
    """Every village a segment touches: its own village plus the ones in ``village_slugs``."""
    out: list[Village] = []
    seen: set[uuid.UUID] = set()
    own = by_id.get(seg.village_id)
    if own is not None:
        out.append(own)
        seen.add(own.id)
    for slug in seg.village_slugs or []:
        v = by_slug.get(slug)
        if v is not None and v.id not in seen:
            out.append(v)
            seen.add(v.id)
    return out


def _village_props(village: Village | None) -> dict[str, Any]:
    """The territory block every feature and every itinerary stop carries."""
    return {
        "village_slug": village.slug if village else None,
        "village_name_local": village.name_local if village else None,
        "village_name_en": village.name_en if village else None,
        "municipality": village.municipality if village else None,
    }


# --- condition reports -----------------------------------------------------------------------


def approved_reports(db: Session, segment_id: uuid.UUID) -> list[TrailReport]:
    """Approved condition reports of a segment, newest first. Drafts stay invisible."""
    stmt = approved_only(select(TrailReport).where(TrailReport.segment_id == segment_id), TrailReport)
    return list(db.scalars(stmt.order_by(TrailReport.reported_at.desc(), TrailReport.created_at.desc())))


def latest_approved_report(db: Session, segment_id: uuid.UUID) -> TrailReport | None:
    """The newest *approved* condition report of a segment, or None."""
    stmt = approved_only(select(TrailReport).where(TrailReport.segment_id == segment_id), TrailReport)
    return db.scalar(stmt.order_by(TrailReport.reported_at.desc(), TrailReport.created_at.desc()).limit(1))


def report_summary(rep: TrailReport | None, village: Village | None = None) -> dict[str, Any] | None:
    """JSON-ready summary of a report (``reported_at`` as ISO 8601), or None."""
    if rep is None:
        return None
    return {
        "id": str(rep.id),
        "condition": rep.condition,
        "note_local": rep.note_local,
        "note_en": rep.note_en,
        "reported_at": rep.reported_at.isoformat() if rep.reported_at else None,
        "lat": rep.lat,
        "lng": rep.lng,
        "reporter_role": rep.reporter_role,
        "is_sample": bool(rep.is_sample),
        "village_slug": village.slug if village else None,
    }


# --- approved rows ---------------------------------------------------------------------------


def approved_entries_with_coords(
    db: Session, *, village: str | None = None, municipality: str | None = None
) -> list[HeritageEntry]:
    stmt = select(HeritageEntry).where(HeritageEntry.lat.is_not(None), HeritageEntry.lng.is_not(None))
    stmt = content.filter_by_territory(stmt, HeritageEntry, village=village, municipality=municipality)
    return list(db.scalars(approved_only(stmt, HeritageEntry).order_by(HeritageEntry.slug)))


def approved_listings_with_coords(
    db: Session, *, village: str | None = None, municipality: str | None = None
) -> list[Listing]:
    stmt = select(Listing).where(Listing.lat.is_not(None), Listing.lng.is_not(None))
    stmt = content.filter_by_territory(stmt, Listing, village=village, municipality=municipality)
    return list(db.scalars(approved_only(stmt, Listing).order_by(Listing.slug)))


def approved_segments(
    db: Session, *, village: str | None = None, municipality: str | None = None
) -> list[TrailSegment]:
    """Approved segments, filtered on **every** village they connect (not only the start village)."""
    segments = list(db.scalars(approved_only(select(TrailSegment), TrailSegment).order_by(TrailSegment.slug)))
    municipality = content.canonical_municipality(municipality)
    if not (village and village.strip()) and municipality is None:
        return segments
    by_id, by_slug = villages_by_id(db), villages_by_slug(db)
    kept: list[TrailSegment] = []
    for seg in segments:
        touched = segment_villages(seg, by_id, by_slug)
        if village and village.strip() and not any(content.matches_village(v, village) for v in touched):
            continue
        if municipality is not None and not any(v.municipality == municipality for v in touched):
            continue
        kept.append(seg)
    return kept


# --- GeoJSON features ------------------------------------------------------------------------


def _point(lat: float, lng: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [float(lng), float(lat)]}


def entry_feature(e: HeritageEntry, village: Village | None) -> dict[str, Any]:
    """Point feature of an approved heritage entry (the caller guarantees it has coordinates)."""
    walking, driving = directions_pair(e.lat, e.lng)
    props: dict[str, Any] = {
        "item_type": "heritage_entry",
        "id": str(e.id),
        "slug": e.slug,
        "title_local": e.title_local,
        "title_en": e.title_en,
        **_village_props(village),
        "coords_approximate": bool(e.coords_approximate),
        "coords_source": e.coords_source,
        "directions_walking": walking,
        "directions_driving": driving,
        # type-specific
        "kind": e.kind,
        "summary_local": e.summary_local,
        "summary_en": e.summary_en,
        "elevation_m": e.elevation_m,
        "event_date": e.event_date.isoformat() if e.event_date else None,
        "source": e.source,
        "tags": list(e.tags or []),
    }
    return {"type": "Feature", "id": f"heritage_entry:{e.id}", "geometry": _point(e.lat, e.lng), "properties": props}


def listing_feature(l: Listing, village: Village | None) -> dict[str, Any]:
    """Point feature of an approved listing. Price/season/capacity/accessibility are host-confirmed."""
    walking, driving = directions_pair(l.lat, l.lng)
    props: dict[str, Any] = {
        "item_type": "listing",
        "id": str(l.id),
        "slug": l.slug,
        "title_local": l.title_local,
        "title_en": l.title_en,
        **_village_props(village),
        "coords_approximate": bool(l.coords_approximate),
        "coords_source": LISTING_COORDS_SOURCE,
        "directions_walking": walking,
        "directions_driving": driving,
        # type-specific (host-entered and host-confirmed; never model-inferred)
        "category": l.category,
        "summary_local": l.description_local,
        "summary_en": l.description_en,
        "price_min": l.price_min,
        "price_max": l.price_max,
        "currency": l.currency,
        "season_from": l.season_from,
        "season_to": l.season_to,
        "season_all_year": bool(l.season_all_year),
        "capacity": l.capacity,
        "accessibility_step_free": l.accessibility_step_free,
        "accessibility_note_local": l.accessibility_note_local,
        "accessibility_note_en": l.accessibility_note_en,
        "confirmed_fields": list(l.confirmed_fields or []),
        "photo_url": l.photo_url,
        "is_sample": bool(l.is_sample),
    }
    return {"type": "Feature", "id": f"listing:{l.id}", "geometry": _point(l.lat, l.lng), "properties": props}


def trail_feature(
    seg: TrailSegment, village: Village | None, latest: TrailReport | None, report_village: Village | None = None
) -> dict[str, Any]:
    """LineString feature of an approved segment with its latest **approved** condition report."""
    start = trail_start(seg)
    walking, driving = directions_pair(*(start or (None, None)))
    props: dict[str, Any] = {
        "item_type": "trail_segment",
        "id": str(seg.id),
        "slug": seg.slug,
        "title_local": seg.name_local,
        "title_en": seg.name_en,
        **_village_props(village),
        "coords_approximate": bool(seg.coords_approximate),
        "coords_source": seg.source,
        "directions_walking": walking,
        "directions_driving": driving,
        # type-specific
        "name_local": seg.name_local,
        "name_en": seg.name_en,
        "summary_local": seg.description_local,
        "summary_en": seg.description_en,
        "from_name": seg.from_name,
        "to_name": seg.to_name,
        "length_m": seg.length_m,
        "ascent_m": seg.ascent_m,
        "difficulty": seg.difficulty,
        "gpx_url": gpx_url(seg),
        "village_slugs": list(seg.village_slugs or []),
        "latest_report": report_summary(latest, report_village),
    }
    geometry = (
        seg.geometry if seg.geometry and seg.geometry.get("coordinates")
        else {"type": "LineString", "coordinates": []}
    )
    return {"type": "Feature", "id": f"trail_segment:{seg.id}", "geometry": geometry, "properties": props}


def features(
    db: Session,
    *,
    village: str | None = None,
    municipality: str | None = None,
    item_type: str | None = None,
) -> dict[str, Any]:
    """GeoJSON FeatureCollection of every **approved** item that has coordinates.

    ``db`` must be the visitor session (``get_public_db``): row-level security limits it to approved
    rows and :func:`~app.services.validation.approved_only` repeats the restriction explicitly.
    Ordering is deterministic — entries, then listings, then trails, each by slug. A ``bbox`` member
    is included so a map can fit the view without a second pass over the features.
    """
    wanted = item_type.strip() if item_type and item_type.strip() else None
    by_id = villages_by_id(db)
    feats: list[dict[str, Any]] = []

    if wanted in (None, "heritage_entry"):
        for e in approved_entries_with_coords(db, village=village, municipality=municipality):
            feats.append(entry_feature(e, by_id.get(e.village_id)))
    if wanted in (None, "listing"):
        for l in approved_listings_with_coords(db, village=village, municipality=municipality):
            feats.append(listing_feature(l, by_id.get(l.village_id)))
    if wanted in (None, "trail_segment"):
        for seg in approved_segments(db, village=village, municipality=municipality):
            latest = latest_approved_report(db, seg.id)
            feats.append(
                trail_feature(
                    seg, by_id.get(seg.village_id), latest,
                    by_id.get(latest.village_id) if latest is not None else None,
                )
            )

    return {
        "type": "FeatureCollection",
        "features": feats,
        "bbox": bounding_box(feats),
        "coords_note": COORDS_NOTE["en"],
        "coords_note_local": COORDS_NOTE["cnr"],
    }


def trail_payload(db: Session, seg: TrailSegment, by_id: dict, *, with_reports: bool = False) -> dict[str, Any]:
    """Trail segment as the ``/api/trails`` endpoints return it (feature properties + geometry)."""
    latest = latest_approved_report(db, seg.id)
    feature = trail_feature(
        seg, by_id.get(seg.village_id), latest, by_id.get(latest.village_id) if latest is not None else None
    )
    payload = dict(feature["properties"])
    payload["geometry"] = feature["geometry"]
    payload["village_id"] = str(seg.village_id)
    payload["status"] = seg.status
    payload["source"] = seg.source
    if with_reports:
        payload["reports"] = [report_summary(r, by_id.get(r.village_id)) for r in approved_reports(db, seg.id)]
    return payload


# --- GPX -------------------------------------------------------------------------------------


def safe_gpx_path(name: str | None) -> Path | None:
    """Resolve ``seed_data/gpx/<name>`` **only** for a bare ``*.gpx`` file name.

    Any name containing a path separator (or ``.``/``..``, or resolving outside the GPX directory)
    is rejected and the caller falls back to a generated track — a stored file name must never be
    able to read an arbitrary file.
    """
    if not name:
        return None
    if "/" in name or "\\" in name or name in (".", "..") or Path(name).name != name:
        return None
    if not name.lower().endswith(".gpx"):
        return None
    root = (Path(settings.seed_dir) / "gpx").resolve()
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def segment_to_gpx(seg: TrailSegment) -> str:
    """GPX 1.1 document (one track, one segment) generated from the stored GeoJSON geometry."""
    gpx = gpxpy.gpx.GPX()
    gpx.creator = GPX_CREATOR
    gpx.name = f"{seg.name_en} (sample)"
    description = seg.description_en
    if seg.coords_approximate:
        description = f"{description} Coordinates are approximate.".strip()
    gpx.description = description
    track = gpxpy.gpx.GPXTrack(name=seg.name_local, description=seg.description_local)
    track.type = "hiking"
    gpx.tracks.append(track)
    tseg = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(tseg)
    for pos in _positions(seg.geometry):
        if len(pos) < 2:
            continue
        ele = float(pos[2]) if len(pos) > 2 and pos[2] is not None else None
        tseg.points.append(gpxpy.gpx.GPXTrackPoint(latitude=float(pos[1]), longitude=float(pos[0]), elevation=ele))
    return gpx.to_xml(version="1.1")


def gpx_for_segment(seg: TrailSegment) -> tuple[str, str]:
    """``(gpx_document, origin)`` — the seed file when the name is safe and present, else generated."""
    path = safe_gpx_path(seg.gpx_file)
    if path is not None:
        return path.read_text(encoding="utf-8"), "file"
    return segment_to_gpx(seg), "generated"


# --- itinerary -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """A stop candidate: an approved heritage entry or listing with coordinates, in a village."""

    item_type: str
    id: uuid.UUID
    slug: str
    title_local: str
    title_en: str
    kind: str  # heritage kind or listing category
    lat: float
    lng: float
    coords_approximate: bool
    is_sample: bool
    village_slug: str | None
    village_name_local: str | None
    village_name_en: str | None
    municipality: str | None


def normalise_interests(interests: Sequence[str]) -> tuple[set[str], list[str]]:
    """``(kinds, unknown)`` — expand aliases, lower-case, keep unknown values for a 422."""
    kinds: set[str] = set()
    unknown: list[str] = []
    for raw in interests or []:
        value = str(raw or "").strip().lower()
        if not value:
            continue
        if value in INTEREST_VALUES:
            kinds.add(value)
        elif value in INTEREST_ALIASES:
            kinds.update(INTEREST_ALIASES[value])
        else:
            unknown.append(str(raw))
    return kinds, unknown


def _candidate(item_type: str, row, kind: str, village: Village | None) -> Candidate:
    return Candidate(
        item_type=item_type,
        id=row.id,
        slug=row.slug,
        title_local=row.title_local,
        title_en=row.title_en,
        kind=kind,
        lat=float(row.lat),
        lng=float(row.lng),
        coords_approximate=bool(row.coords_approximate),
        is_sample=bool(getattr(row, "is_sample", False)),
        village_slug=village.slug if village else None,
        village_name_local=village.name_local if village else None,
        village_name_en=village.name_en if village else None,
        municipality=village.municipality if village else None,
    )


def itinerary_candidates(
    db: Session,
    interests: Sequence[str] = (),
    *,
    villages: Sequence[str] | None = None,
    municipality: str | None = None,
) -> list[Candidate]:
    """Approved entries and listings with coordinates matching the interests and the territory filter.

    ``interests`` empty means "everything". ``villages`` is a list of village slugs or ids; an empty
    list means the whole territory, which is what makes a **multi-village** itinerary the default.
    """
    kinds, _ = normalise_interests(interests)
    wanted_villages = [v for v in (villages or []) if str(v).strip()]
    by_id = villages_by_id(db)
    out: list[Candidate] = []

    def in_territory(village: Village | None) -> bool:
        if municipality and (village is None or village.municipality != content.canonical_municipality(municipality)):
            return False
        if wanted_villages and not any(content.matches_village(village, w) for w in wanted_villages):
            return False
        return True

    for e in approved_entries_with_coords(db, municipality=municipality):
        if kinds and e.kind not in kinds:
            continue
        village = by_id.get(e.village_id)
        if not in_territory(village):
            continue
        out.append(_candidate("heritage_entry", e, e.kind, village))
    for l in approved_listings_with_coords(db, municipality=municipality):
        if kinds and l.category not in kinds:
            continue
        village = by_id.get(l.village_id)
        if not in_territory(village):
            continue
        out.append(_candidate("listing", l, l.category, village))

    out.sort(key=lambda c: (c.slug, c.item_type))
    return out


def travel_minutes(distance_m: float) -> float:
    """Walking minutes for a *path* distance (the detour factor is already applied)."""
    return distance_m / 1000.0 / WALK_KMH * 60.0


def _why(kind: str, village_name: str | None, lang: str) -> str:
    texts = WHY_BY_KIND.get(kind, WHY_BY_KIND["other"])
    base = texts.get(lang, texts["en"])
    if not village_name:
        return base
    return f"{base} in {village_name}" if lang == "en" else f"{base}, {village_name}"


def plan_itinerary(
    candidates: Sequence[Candidate],
    start: tuple[float, float],
    hours: float,
    lang: str = "cnr",
) -> dict[str, Any]:
    """Greedy nearest-neighbour walk from ``start`` within ``hours``.

    A stop is added while ``elapsed + travel + MINUTES_PER_STOP <= hours × 60``; travel time is the
    haversine distance × :data:`DETOUR_FACTOR` at :data:`WALK_KMH`. Ties break on the slug, so the
    same request always yields the same itinerary. The walk deliberately ignores village boundaries:
    the nearest next stop may be in another village or municipality, which is what makes the
    itinerary multi-village (``multi_village``, read by KPI K15).
    """
    budget_min = float(hours) * 60.0
    elapsed = 0.0
    total_m = 0.0
    current = (float(start[0]), float(start[1]))
    remaining = sorted(candidates, key=lambda c: (c.slug, c.item_type))
    stops: list[dict[str, Any]] = []
    route: list[list[float]] = [[current[1], current[0]]]

    while remaining:
        best = min(remaining, key=lambda c: (round(haversine_m(current, (c.lat, c.lng)), 3), c.slug))
        leg_m = haversine_m(current, (best.lat, best.lng)) * DETOUR_FACTOR
        leg_min = travel_minutes(leg_m)
        if elapsed + leg_min + MINUTES_PER_STOP > budget_min:
            break  # the nearest remaining candidate does not fit → nothing farther will either
        elapsed += leg_min + MINUTES_PER_STOP
        total_m += leg_m
        stops.append(
            {
                "order": len(stops) + 1,
                "item_type": best.item_type,
                "id": str(best.id),
                "slug": best.slug,
                "title": localized(lang, best.title_local, best.title_en),
                "title_local": best.title_local,
                "title_en": best.title_en,
                "kind": best.kind,
                "village_slug": best.village_slug,
                "village_name": localized(lang, best.village_name_local or "", best.village_name_en or "") or None,
                "municipality": best.municipality,
                "lat": best.lat,
                "lng": best.lng,
                "coords_approximate": best.coords_approximate,
                "is_sample": best.is_sample,
                "directions_url": directions_url(best.lat, best.lng, "walking"),
                "directions_driving": directions_url(best.lat, best.lng, "driving"),
                "minutes_from_previous": int(round(leg_min)),
                "arrive_after_minutes": int(round(elapsed - MINUTES_PER_STOP)),
                "why": _why(best.kind, localized(lang, best.village_name_local or "", best.village_name_en or ""), lang),
            }
        )
        route.append([best.lng, best.lat])
        current = (best.lat, best.lng)
        remaining.remove(best)

    village_slugs = list(dict.fromkeys(s["village_slug"] for s in stops if s["village_slug"]))
    municipalities = list(dict.fromkeys(s["municipality"] for s in stops if s["municipality"]))
    return {
        "stops": stops,
        "route": {"type": "LineString", "coordinates": route},
        "start": {"lat": float(start[0]), "lng": float(start[1])},
        "total_km": round(total_m / 1000.0, 2),
        "est_hours": round(elapsed / 60.0, 2),
        "hours": float(hours),
        "lang": lang,
        "villages": village_slugs,
        "municipalities": municipalities,
        "multi_village": len(village_slugs) > 1,
        "multi_municipality": len(municipalities) > 1,
        "assumptions": {
            "walk_kmh": WALK_KMH,
            "detour_factor": DETOUR_FACTOR,
            "minutes_per_stop": MINUTES_PER_STOP,
            "note_local": (
                "Procjena: hod 4 km/h po vazdušnoj liniji × 1,3 i 20 min po stanici. "
                "Koordinate su približne."
            ),
            "note_en": (
                "Estimate: walking 4 km/h over straight-line distance × 1.3, plus 20 min per stop. "
                "Coordinates are approximate."
            ),
        },
    }
