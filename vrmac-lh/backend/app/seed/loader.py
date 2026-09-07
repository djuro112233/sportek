"""Seed loader. Idempotent: skips when sample accounts already exist unless ``reset=True``.

Every seeded content item gets provenance records (created → approved where applicable), approved
listings get a consent record, approved heritage entries are embedded into the RAG index.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import gpxpy
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..auth import hash_password
from ..config import settings
from ..models import (
    ConsentRecord,
    HeritageEntry,
    Listing,
    TrailReport,
    TrailSegment,
    User,
    utcnow,
)
from ..services import indexing
from ..services.validation import add_provenance

log = logging.getLogger(__name__)

TRUNCATE_ORDER = [
    "kpi_heat_cells", "kpi_aggregates", "events", "audit_log", "visitor_requests", "trail_reports",
    "trail_segments", "entry_chunks", "provenance", "listings", "consent_records", "onboarding_sessions",
    "heritage_entries", "users",
]


def seed_dir() -> Path:
    return Path(settings.seed_dir)


def _read(name: str) -> dict:
    return json.loads((seed_dir() / name).read_text(encoding="utf-8"))


def reset_all(db: Session) -> None:
    db.execute(text("TRUNCATE " + ", ".join(TRUNCATE_ORDER) + " CASCADE"))
    db.commit()


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    import math

    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(d))


def parse_gpx(path: Path) -> dict:
    """GPX → GeoJSON LineString [lng, lat, ele] plus length/ascent."""
    gpx = gpxpy.parse(path.read_text(encoding="utf-8"))
    coords: list[list[float]] = []
    for trk in gpx.tracks:
        for seg in trk.segments:
            for p in seg.points:
                coords.append([p.longitude, p.latitude, p.elevation if p.elevation is not None else 0.0])
    length = 0.0
    ascent = 0.0
    for p, q in zip(coords, coords[1:]):
        length += haversine_m((p[1], p[0]), (q[1], q[0]))
        if q[2] > p[2]:
            ascent += q[2] - p[2]
    return {"geometry": {"type": "LineString", "coordinates": coords}, "length_m": int(round(length)), "ascent_m": int(round(ascent))}


def geometry_stats(geometry: dict) -> tuple[int, int]:
    coords = geometry.get("coordinates", [])
    length = sum(haversine_m((p[1], p[0]), (q[1], q[0])) for p, q in zip(coords, coords[1:]))
    ascent = sum(max(0.0, (q[2] if len(q) > 2 else 0) - (p[2] if len(p) > 2 else 0)) for p, q in zip(coords, coords[1:]))
    return int(round(length)), int(round(ascent))


def _approve(db: Session, item_type: str, item, validator: User, source: str) -> None:
    item.status = "approved"
    item.approved_by = validator.id
    item.approved_at = utcnow()
    if item_type == "listing":
        item.published_at = item.approved_at
    add_provenance(db, item_type, item, "approved", actor=validator, source=source,
                   note="seed: approved sample/public-fact content", from_status="draft", to_status="approved")


def load_seed(db: Session, *, reset: bool = False) -> dict:
    if reset:
        reset_all(db)
    if db.scalar(select(User.id).limit(1)) is not None:
        return {"status": "already seeded", "hint": "use --reset to reload"}

    users_by_email: dict[str, User] = {}
    for u in _read("users.json")["users"]:
        user = User(
            email=u["email"].lower(), password_hash=hash_password(settings.seed_password), role=u["role"],
            display_name=u["display_name"], sex=u.get("sex"), is_sample=True,
        )
        db.add(user)
        users_by_email[user.email] = user
    db.flush()
    validator = users_by_email["validator1@example.org"]
    ambassador = users_by_email["ambassador1@example.org"]

    # --- heritage entries ---------------------------------------------------
    data = _read("heritage_entries.json")
    source_book = data["sources"]
    n_entries = 0
    for e in data["entries"]:
        target = e["status"]
        entry = HeritageEntry(
            slug=e["slug"], kind=e["kind"], title_local=e["title_local"], title_en=e["title_en"],
            summary_local=e.get("summary_local", ""), summary_en=e.get("summary_en", ""),
            body_local=e.get("body_local", ""), body_en=e.get("body_en", ""),
            lat=e.get("lat"), lng=e.get("lng"), coords_approximate=e.get("coords_approximate", True),
            coords_source=e.get("coords_source", ""), elevation_m=e.get("elevation_m"),
            event_date=datetime.fromisoformat(e["event_date"]).date() if e.get("event_date") else None,
            recurrence_rule=e.get("recurrence_rule"), established_year=e.get("established_year"),
            source=e["source"], sources=[source_book[k] for k in e.get("source_keys", [])], tags=e.get("tags", []),
            status="draft", version=1, created_by=ambassador.id,
        )
        db.add(entry)
        db.flush()
        add_provenance(db, "heritage_entry", entry, "created", actor=ambassador, source=e["source"],
                       note="seed: public facts with cited sources", to_status="draft")
        if target == "approved":
            _approve(db, "heritage_entry", entry, validator, e["source"])
        elif target == "reviewed":
            entry.status = "reviewed"
            add_provenance(db, "heritage_entry", entry, "reviewed", actor=ambassador, source=e["source"],
                           note="seed: sample reviewed entry", from_status="draft", to_status="reviewed")
        elif target == "rejected":
            entry.status = "rejected"
            add_provenance(db, "heritage_entry", entry, "rejected", actor=validator, source=e["source"],
                           note="seed: rejected — no source", from_status="draft", to_status="rejected")
        n_entries += 1
    db.flush()

    # --- listings (with consent records) ------------------------------------
    n_listings = 0
    for l in _read("listings.json")["listings"]:
        host = users_by_email[l["host_email"].lower()]
        consent = ConsentRecord(
            host_user_id=host.id, ambassador_user_id=ambassador.id, consent_text_version="v1",
            consent_given=True, method="checkbox",
        )
        db.add(consent)
        db.flush()
        listing = Listing(
            slug=l["slug"], host_user_id=host.id, category=l["category"], title_local=l["title_local"],
            title_en=l["title_en"], description_local=l["description_local"], description_en=l["description_en"],
            price_min=l.get("price_min"), price_max=l.get("price_max"), currency=l.get("currency", "EUR"),
            season=l.get("season"), capacity=l.get("capacity"), accessibility_local=l.get("accessibility_local", ""),
            accessibility_en=l.get("accessibility_en", ""), lat=l.get("lat"), lng=l.get("lng"),
            coords_approximate=l.get("coords_approximate", True), photo_url=l.get("photo_url", ""), is_sample=True,
            missing_fields=[], extraction_method="manual", translation_pending=False, consent_record_id=consent.id,
            status="draft", version=1,
        )
        db.add(listing)
        db.flush()
        consent.listing_id = listing.id
        add_provenance(db, "listing", listing, "created", actor=ambassador, source="seed: fictional sample provider",
                       note="seed", to_status="draft")
        if l["status"] == "approved":
            _approve(db, "listing", listing, validator, "seed: fictional sample provider")
        n_listings += 1
    db.flush()

    # --- trails + reports -----------------------------------------------------
    tdata = _read("trails.json")
    segments_by_slug: dict[str, TrailSegment] = {}
    for s in tdata["segments"]:
        if s.get("gpx_file"):
            parsed = parse_gpx(seed_dir() / "gpx" / s["gpx_file"])
            geometry, length_m, ascent_m = parsed["geometry"], parsed["length_m"], parsed["ascent_m"]
        else:
            geometry = s["geometry"]
            length_m, ascent_m = geometry_stats(geometry)
        start = geometry["coordinates"][0]
        seg = TrailSegment(
            slug=s["slug"], name_local=s["name_local"], name_en=s["name_en"],
            description_local=s.get("description_local", ""), description_en=s.get("description_en", ""),
            from_name=s.get("from_name", ""), to_name=s.get("to_name", ""), gpx_file=s.get("gpx_file"),
            geometry=geometry, length_m=length_m, ascent_m=ascent_m, difficulty=s.get("difficulty", "moderate"),
            lat=start[1], lng=start[0], coords_approximate=s.get("coords_approximate", True), source=s.get("source", ""),
            status="draft", version=1,
        )
        db.add(seg)
        db.flush()
        add_provenance(db, "trail_segment", seg, "created", actor=ambassador, source=s.get("source", ""), to_status="draft")
        if s["status"] == "approved":
            _approve(db, "trail_segment", seg, validator, s.get("source", ""))
        segments_by_slug[seg.slug] = seg
    n_reports = 0
    for r in tdata["reports"]:
        seg = segments_by_slug[r["segment_slug"]]
        rep = TrailReport(
            segment_id=seg.id, lat=r["lat"], lng=r["lng"], condition=r["condition"], note_local=r.get("note_local", ""),
            note_en=r.get("note_en", ""), reported_at=_parse_dt(r["reported_at"]), reporter_role=r.get("reporter_role", "visitor"),
            reporter_user_id=ambassador.id if r.get("reporter_role") == "ambassador" else None, is_sample=True,
            status="draft", version=1,
        )
        db.add(rep)
        db.flush()
        add_provenance(db, "trail_report", rep, "created", actor=ambassador if rep.reporter_user_id else None,
                       source="seed: sample condition report", to_status="draft")
        if r["status"] == "approved":
            _approve(db, "trail_report", rep, validator, "seed: sample condition report")
        n_reports += 1
    db.commit()

    # --- RAG index for approved entries -------------------------------------
    n_chunks = indexing.reindex_all_approved(db)

    # --- synthetic event history for the KPI demo (optional module) -----------
    n_events = 0
    try:
        from .synthetic_events import load_synthetic_events  # provided by the KPI module

        n_events = load_synthetic_events(db, users_by_email)
        db.commit()
    except ImportError:
        log.info("no synthetic event history module; skipping")

    summary = {
        "status": "seeded",
        "users": len(users_by_email),
        "heritage_entries": n_entries,
        "listings": n_listings,
        "trail_segments": len(segments_by_slug),
        "trail_reports": n_reports,
        "chunks": n_chunks,
        "synthetic_events": n_events,
        "embeddings_provider": settings.embeddings_provider,
    }
    log.info("seed complete: %s", summary)
    return summary
