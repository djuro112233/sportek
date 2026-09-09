"""Geo services for innovation claim #5 — interactive map, directions, GPX trails, itinerary.

Everything visitor-facing here reads through the row-level-security-limited visitor session
(``get_public_db``) **and** filters with ``approved_only`` (belt and braces), so a draft, reviewed or
rejected item can never reach the map, a GPX download or an itinerary.

Coordinates are WGS84 (``lat``/``lng`` in the models, ``[lng, lat, ele]`` in GeoJSON). Seed coordinates
are marked ``coords_approximate=True`` and every feature carries that flag so the UI can say so.

Directions are plain Google Maps *navigation* deep links (no API key, no server-side routing):
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
from ..models import HeritageEntry, Listing, TrailReport, TrailSegment
from .validation import approved_only

# --- constants -------------------------------------------------------------------------------

DIRECTIONS_BASE = "https://www.google.com/maps/dir/?api=1"
TRAVEL_MODES: tuple[str, ...] = ("walking", "driving")

HERITAGE_KINDS: tuple[str, ...] = ("place", "church", "building", "event", "tradition", "institution", "landscape")
LISTING_CATEGORIES: tuple[str, ...] = ("accommodation", "food", "guiding", "craft", "experience", "transport", "other")
INTEREST_VALUES: tuple[str, ...] = HERITAGE_KINDS + LISTING_CATEGORIES

#: Default itinerary start — the Donja Lastva trailhead on the shore (approximate).
DEFAULT_START: tuple[float, float] = (42.4400, 18.6850)
WALK_KMH = 4.0  # average walking speed used for time estimates
DETOUR_FACTOR = 1.3  # straight-line distance × 1.3 ≈ path distance on the Vrmac slopes
MINUTES_PER_STOP = 20  # time spent at each stop
EARTH_RADIUS_M = 6_371_000.0

GPX_CREATOR = "VRMAC-LH prototype (sample, approximate)"

# Localised one-liners explaining why a stop is on the itinerary (by heritage kind / listing category).
WHY_BY_KIND: dict[str, dict[str, str]] = {
    "place": {"cnr": "Mjesto iz baštine Vrmca", "en": "A heritage place on Vrmac"},
    "church": {"cnr": "Crkva — sakralna baština", "en": "Church — sacred heritage"},
    "building": {"cnr": "Građevina iz baštine", "en": "Heritage building"},
    "event": {"cnr": "Manifestacija ili događaj zajednice", "en": "Community festival or event"},
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

    Format is fixed by the innovation claim:
    ``https://www.google.com/maps/dir/?api=1&destination={lat},{lng}&travelmode={walking|driving}``.
    Coordinates are rounded to 6 decimals (≈0.1 m) so URLs stay short and stable.
    """
    if mode not in TRAVEL_MODES:
        raise ValueError(f"travel mode must be one of {TRAVEL_MODES}, got {mode!r}")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        raise ValueError("coordinates out of WGS84 range")
    return f"{DIRECTIONS_BASE}&destination={round(float(lat), 6)},{round(float(lng), 6)}&travelmode={mode}"


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between two ``(lat, lng)`` points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(d))


def _positions(geometry: dict | None) -> list[Sequence[float]]:
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


def bounding_box(features: Iterable[dict]) -> list[float] | None:
    """GeoJSON ``bbox`` (``[min_lng, min_lat, max_lng, max_lat]``) over the features, or None if empty."""
    min_lng = min_lat = math.inf
    max_lng = max_lat = -math.inf
    found = False
    for f in features:
        for pos in _positions(f.get("geometry")):
            if len(pos) < 2:
                continue
            found = True
            lng, lat = float(pos[0]), float(pos[1])
            min_lng, max_lng = min(min_lng, lng), max(max_lng, lng)
            min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
    if not found:
        return None
    return [min_lng, min_lat, max_lng, max_lat]


def trail_start(seg: TrailSegment) -> tuple[float, float] | None:
    """``(lat, lng)`` of a segment's start: the stored start point, else the first geometry vertex."""
    if seg.lat is not None and seg.lng is not None:
        return float(seg.lat), float(seg.lng)
    pos = _positions(seg.geometry)
    if pos and len(pos[0]) >= 2:
        return float(pos[0][1]), float(pos[0][0])
    return None


def localized(lang: str, local: str, en: str) -> str:
    """Pick the text for ``lang`` (``cnr`` → ``*_local``), falling back to the other language."""
    if lang == "en":
        return en or local
    return local or en


# --- reports ---------------------------------------------------------------------------------


def approved_reports(db: Session, segment_id: uuid.UUID) -> list[TrailReport]:
    """Approved condition reports of a segment, newest first (by ``reported_at``)."""
    stmt = approved_only(select(TrailReport).where(TrailReport.segment_id == segment_id), TrailReport)
    stmt = stmt.order_by(TrailReport.reported_at.desc(), TrailReport.created_at.desc())
    return list(db.scalars(stmt))


def latest_approved_report(db: Session, segment_id: uuid.UUID) -> TrailReport | None:
    """The newest *approved* condition report of a segment, or None."""
    stmt = approved_only(select(TrailReport).where(TrailReport.segment_id == segment_id), TrailReport)
    stmt = stmt.order_by(TrailReport.reported_at.desc(), TrailReport.created_at.desc()).limit(1)
    return db.scalar(stmt)


def report_summary(rep: TrailReport | None) -> dict[str, Any] | None:
    """JSON-ready summary of a report for GeoJSON properties (``reported_at`` as ISO 8601)."""
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
    }


# --- GeoJSON features ------------------------------------------------------------------------


def _point(lat: float, lng: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [float(lng), float(lat)]}


def entry_feature(e: HeritageEntry) -> dict[str, Any]:
    """Point feature of an approved heritage entry (caller guarantees coordinates are present)."""
    return {
        "type": "Feature",
        "id": f"heritage_entry:{e.id}",
        "geometry": _point(e.lat, e.lng),
        "properties": {
            "item_type": "heritage_entry",
            "id": str(e.id),
            "slug": e.slug,
            "title_local": e.title_local,
            "title_en": e.title_en,
            "kind": e.kind,
            "summary_local": e.summary_local,
            "summary_en": e.summary_en,
            "coords_approximate": bool(e.coords_approximate),
            "coords_source": e.coords_source,
            "elevation_m": e.elevation_m,
            "source": e.source,
            "directions_walking": directions_url(e.lat, e.lng, "walking"),
            "directions_driving": directions_url(e.lat, e.lng, "driving"),
        },
    }


def listing_feature(l: Listing) -> dict[str, Any]:
    """Point feature of an approved listing (caller guarantees coordinates are present)."""
    return {
        "type": "Feature",
        "id": f"listing:{l.id}",
        "geometry": _point(l.lat, l.lng),
        "properties": {
            "item_type": "listing",
            "id": str(l.id),
            "slug": l.slug,
            "title_local": l.title_local,
            "title_en": l.title_en,
            "category": l.category,
            "summary_local": l.description_local,
            "summary_en": l.description_en,
            "price_min": l.price_min,
            "price_max": l.price_max,
            "currency": l.currency,
            "season": l.season,
            "capacity": l.capacity,
            "photo_url": l.photo_url,
            "is_sample": bool(l.is_sample),
            "accessibility_local": l.accessibility_local,
            "accessibility_en": l.accessibility_en,
            "coords_approximate": bool(l.coords_approximate),
            "directions_walking": directions_url(l.lat, l.lng, "walking"),
            "directions_driving": directions_url(l.lat, l.lng, "driving"),
        },
    }


def trail_feature(seg: TrailSegment, latest: TrailReport | None) -> dict[str, Any]:
    """LineString feature of an approved trail segment with its latest approved report (or null)."""
    start = trail_start(seg)
    props: dict[str, Any] = {
        "item_type": "trail_segment",
        "id": str(seg.id),
        "slug": seg.slug,
        "title_local": seg.name_local,
        "title_en": seg.name_en,
        "name_local": seg.name_local,
        "name_en": seg.name_en,
        "summary_local": seg.description_local,
        "summary_en": seg.description_en,
        "from_name": seg.from_name,
        "to_name": seg.to_name,
        "length_m": seg.length_m,
        "ascent_m": seg.ascent_m,
        "difficulty": seg.difficulty,
        "coords_approximate": bool(seg.coords_approximate),
        "source": seg.source,
        "gpx_url": gpx_url(seg),
        "latest_report": report_summary(latest),
        "directions_walking": directions_url(start[0], start[1], "walking") if start else None,
        "directions_driving": directions_url(start[0], start[1], "driving") if start else None,
    }
    geometry = seg.geometry if seg.geometry and seg.geometry.get("coordinates") else {"type": "LineString", "coordinates": []}
    return {"type": "Feature", "id": f"trail_segment:{seg.id}", "geometry": geometry, "properties": props}


def gpx_url(seg: TrailSegment) -> str:
    return f"/api/trails/{seg.slug}/gpx"


def approved_entries_with_coords(db: Session) -> list[HeritageEntry]:
    stmt = select(HeritageEntry).where(HeritageEntry.lat.is_not(None), HeritageEntry.lng.is_not(None))
    return list(db.scalars(approved_only(stmt, HeritageEntry).order_by(HeritageEntry.slug)))


def approved_listings_with_coords(db: Session) -> list[Listing]:
    stmt = select(Listing).where(Listing.lat.is_not(None), Listing.lng.is_not(None))
    return list(db.scalars(approved_only(stmt, Listing).order_by(Listing.slug)))


def approved_segments(db: Session) -> list[TrailSegment]:
    return list(db.scalars(approved_only(select(TrailSegment), TrailSegment).order_by(TrailSegment.slug)))


def features(db: Session) -> dict[str, Any]:
    """GeoJSON FeatureCollection of every approved item with coordinates.

    ``db`` must be the visitor session (``get_public_db``). Ordering is deterministic (by slug within
    entries → listings → trails). A ``bbox`` member is included for map fitting.
    """
    feats: list[dict[str, Any]] = []
    feats.extend(entry_feature(e) for e in approved_entries_with_coords(db))
    feats.extend(listing_feature(l) for l in approved_listings_with_coords(db))
    for seg in approved_segments(db):
        feats.append(trail_feature(seg, latest_approved_report(db, seg.id)))
    return {
        "type": "FeatureCollection",
        "features": feats,
        "bbox": bounding_box(feats),
        "coords_note": "Coordinates of sample data are approximate (coords_approximate=true).",
    }


# --- GPX -------------------------------------------------------------------------------------


def safe_gpx_path(name: str | None) -> Path | None:
    """Resolve ``seed_data/gpx/<name>`` only if ``name`` is a bare file name (no path separators)."""
    if not name:
        return None
    if "/" in name or "\\" in name or name in (".", "..") or Path(name).name != name:
        return None
    if not name.lower().endswith(".gpx"):
        return None
    path = (Path(settings.seed_dir) / "gpx" / name).resolve()
    if not path.is_file():
        return None
    return path


def segment_to_gpx(seg: TrailSegment) -> str:
    """Generate a GPX 1.1 document (one track, one segment) from the stored GeoJSON geometry."""
    gpx = gpxpy.gpx.GPX()
    gpx.creator = GPX_CREATOR
    gpx.name = f"{seg.name_en} (sample)"
    gpx.description = (
        f"{seg.description_en} Coordinates are approximate."
        if seg.coords_approximate
        else seg.description_en
    ).strip()
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


def gpx_for_segment(seg: TrailSegment) -> str:
    """The seed GPX file when the segment references one (validated name), else a generated document."""
    path = safe_gpx_path(seg.gpx_file)
    if path is not None:
        return path.read_text(encoding="utf-8")
    return segment_to_gpx(seg)


# --- itinerary -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """A stop candidate: an approved heritage entry or listing with coordinates."""

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


def itinerary_candidates(db: Session, interests: Sequence[str]) -> list[Candidate]:
    """Approved entries + listings with coordinates whose kind/category is in ``interests`` (empty = all)."""
    wanted = {i.strip().lower() for i in interests if i and i.strip()}
    out: list[Candidate] = []
    for e in approved_entries_with_coords(db):
        if wanted and e.kind not in wanted:
            continue
        out.append(Candidate("heritage_entry", e.id, e.slug, e.title_local, e.title_en, e.kind,
                             float(e.lat), float(e.lng), bool(e.coords_approximate), False))
    for l in approved_listings_with_coords(db):
        if wanted and l.category not in wanted:
            continue
        out.append(Candidate("listing", l.id, l.slug, l.title_local, l.title_en, l.category,
                             float(l.lat), float(l.lng), bool(l.coords_approximate), bool(l.is_sample)))
    out.sort(key=lambda c: (c.slug, c.item_type))
    return out


def travel_minutes(distance_m: float) -> float:
    """Walking time for a *path* distance (detour factor already applied)."""
    return distance_m / 1000.0 / WALK_KMH * 60.0


def plan_itinerary(
    candidates: Sequence[Candidate],
    start: tuple[float, float],
    hours: float,
    lang: str = "cnr",
) -> dict[str, Any]:
    """Greedy nearest-neighbour walk from ``start``.

    Stops are added while ``elapsed + travel + MINUTES_PER_STOP <= hours*60``; travel time is the
    haversine distance × ``DETOUR_FACTOR`` at ``WALK_KMH``. Ties are broken by slug, so the result is
    deterministic for the same inputs. Returns the response dict (stops, route, totals, assumptions).
    """
    budget_min = float(hours) * 60.0
    elapsed = 0.0
    total_m = 0.0
    current = (float(start[0]), float(start[1]))
    remaining = sorted(candidates, key=lambda c: (c.slug, c.item_type))
    stops: list[dict[str, Any]] = []
    route: list[list[float]] = [[current[1], current[0]]]

    while remaining:
        best = min(remaining, key=lambda c: (haversine_m(current, (c.lat, c.lng)), c.slug))
        leg_m = haversine_m(current, (best.lat, best.lng)) * DETOUR_FACTOR
        leg_min = travel_minutes(leg_m)
        if elapsed + leg_min + MINUTES_PER_STOP > budget_min:
            break  # the nearest candidate does not fit → nothing farther will
        elapsed += leg_min + MINUTES_PER_STOP
        total_m += leg_m
        why = WHY_BY_KIND.get(best.kind, WHY_BY_KIND["other"])
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
                "lat": best.lat,
                "lng": best.lng,
                "coords_approximate": best.coords_approximate,
                "is_sample": best.is_sample,
                "directions_url": directions_url(best.lat, best.lng, "walking"),
                "minutes_from_previous": int(round(leg_min)),
                "minutes": int(round(leg_min)),
                "arrive_after_minutes": int(round(elapsed - MINUTES_PER_STOP)),
                "why": why.get(lang, why["en"]),
            }
        )
        route.append([best.lng, best.lat])
        current = (best.lat, best.lng)
        remaining.remove(best)

    return {
        "stops": stops,
        "route": {"type": "LineString", "coordinates": route},
        "start": {"lat": float(start[0]), "lng": float(start[1])},
        "total_km": round(total_m / 1000.0, 2),
        "est_hours": round(elapsed / 60.0, 2),
        "hours": float(hours),
        "lang": lang,
        "assumptions": {
            "walk_kmh": WALK_KMH,
            "detour_factor": DETOUR_FACTOR,
            "minutes_per_stop": MINUTES_PER_STOP,
            "note_local": "Procjena: hod 4 km/h po vazdušnoj liniji × 1,3, 20 min po stanici. Koordinate su približne.",
            "note_en": "Estimate: walking 4 km/h on straight-line distance × 1.3, 20 min per stop. Coordinates are approximate.",
        },
    }
