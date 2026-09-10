"""Interoperability stub (innovation claim #6).

Exports the *approved* heritage entries and provider listings of the whole Vrmac territory as
NGSI-LD ``PointOfInterest`` entities that follow the FIWARE / Smart Data Models
``dataModel.PointOfInterest`` schema, plus a DCAT-AP dataset description of the export.

Three representations are produced:

* **key-values** – the simplified NGSI-LD representation (``?options=keyValues``). This is the
  form the Smart Data Models JSON schema describes, so this is what is validated.
* **normalized** – the full NGSI-LD representation (``{"type": "Property", "value": …}``,
  ``GeoProperty`` for ``location``, ``Relationship`` for ``refSeeAlso``) with an ``@context``.
  This is what an NGSI-LD context broker such as Orion-LD ingests (see docs/interoperability.md
  for the ``entityOperations/upsert`` example).
* **DCAT-AP** – a JSON-LD ``dcat:Dataset`` describing the two distributions above.

**Territory.** The prototype covers Vrmac on both sides of the ridge, so every entity carries the
village it belongs to and that village's municipality:
``address = {addressLocality: <village name (en)>, addressRegion: "<municipality> municipality,
Bay of Kotor", addressCountry: "ME"}`` and a machine-readable ``[village: <slug> — …]`` note inside
``description``. Both attributes exist in the vendored schema, so nothing is invented.

Validation runs fully **offline**: the schemas are vendored under ``backend/schemas/sdm`` and a
``referencing.Registry`` maps the public schema URIs (``https://smart-data-models.github.io/…``)
to the vendored files, so no ``$ref`` is ever fetched over the network.

Privacy: no personal data is exported. Listings carry no host names, e-mails or phone numbers
(``contactPoint`` only points visitors to the platform's request form) and the fictional hosts'
user ids are not referenced (``owner`` is deliberately left out).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import BACKEND_DIR, PROTOTYPE_LABEL, settings
from ..models import MUNICIPALITIES, HeritageEntry, Listing, Village
from .validation import approved_only

log = logging.getLogger(__name__)

KeyValues = dict[str, Any]
Normalized = dict[str, Any]

# --- constants -----------------------------------------------------------------------------
SCHEMA_DIR = BACKEND_DIR / "schemas" / "sdm"
POI_SCHEMA_URI = "https://smart-data-models.github.io/dataModel.PointOfInterest/PointOfInterest/schema.json"
COMMON_SCHEMA_URI = "https://smart-data-models.github.io/data-models/common-schema.json"
POI_CONTEXT_URI = "https://smart-data-models.github.io/dataModel.PointOfInterest/context.jsonld"
NGSI_LD_CORE_CONTEXT_URI = "https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context-v1.6.jsonld"
NGSI_LD_CONTEXT: list[str] = [POI_CONTEXT_URI, NGSI_LD_CORE_CONTEXT_URI]

ENTITY_TYPE = "PointOfInterest"
ID_PREFIX = "urn:ngsi-ld:PointOfInterest:vrmac-lh:"
#: Item-type token inside every entity id. Slugs are unique **per table**, not across tables, so a
#: heritage entry and a listing may legitimately share one; an id built from the slug alone would
#: then collide (two different entities, one id) and the schema would still call the export valid.
HERITAGE_ITEM_TYPE = "heritage_entry"
LISTING_ITEM_TYPE = "listing"
ITEM_TYPES: tuple[str, ...] = (HERITAGE_ITEM_TYPE, LISTING_ITEM_TYPE)
DATA_PROVIDER = "VRMAC-LH prototype (SMART ERA)"
ADDRESS_COUNTRY = "ME"
# The Bay of Kotor is the region both municipalities of the territory belong to.
REGION_SUFFIX = "Bay of Kotor"
COORDS_APPROXIMATE_NOTE = "(coordinates approximate)"
LISTING_SOURCE = "VRMAC-LH host onboarding (host-confirmed, validated listing)"

# NGSI-LD attribute kinds used by the normalized form.
GEO_ATTRS: tuple[str, ...] = ("location",)
DATETIME_ATTRS: tuple[str, ...] = ("dateCreated", "dateModified")
RELATIONSHIP_ATTRS: tuple[str, ...] = ("refSeeAlso",)

# kind of a heritage entry → PointOfInterest category (a list; first item is the primary category)
HERITAGE_CATEGORY: dict[str, str] = {
    "church": "church",
    "building": "building",
    "event": "event",
    "tradition": "tradition",
    "institution": "institution",
    "landscape": "landscape",
}

MONTHS_EN = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
MONTHS_LOCAL = (
    "januar", "februar", "mart", "april", "maj", "jun",
    "jul", "avgust", "septembar", "oktobar", "novembar", "decembar",
)
MONTHS_LOCAL_GENITIVE = (
    "januara", "februara", "marta", "aprila", "maja", "juna",
    "jula", "avgusta", "septembra", "oktobra", "novembra", "decembra",
)

# labels for the host-confirmed structured fields (``Listing.confirmed_fields``)
CONFIRMED_LABELS: dict[str, tuple[str, str]] = {
    "price_min": ("price", "cijena"),
    "price_max": ("price", "cijena"),
    "currency": ("price", "cijena"),
    "season": ("season", "sezona"),
    "capacity": ("capacity", "kapacitet"),
    "accessibility": ("accessibility", "pristupačnost"),
    "coordinates": ("coordinates", "koordinate"),
}

EXPORT_FILES: dict[str, str] = {
    "normalized": "pois.ngsi-ld.json",
    "keyvalues": "pois.keyvalues.json",
    "dcat_ap": "dataset.dcat-ap.jsonld",
    "report": "validation-report.json",
}

DCAT_CONTEXT: dict[str, str] = {
    "dcat": "http://www.w3.org/ns/dcat#",
    "dct": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "vcard": "http://www.w3.org/2006/vcard/ns#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "locn": "http://www.w3.org/ns/locn#",
    "geo": "http://www.opengis.net/ont/geosparql#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
}
EU_THEME = "http://publications.europa.eu/resource/authority/data-theme/"
EU_FREQUENCY = "http://publications.europa.eu/resource/authority/frequency/"
EU_LANGUAGE = "http://publications.europa.eu/resource/authority/language/"
IANA_MEDIA_TYPE = "https://www.iana.org/assignments/media-types/"
LICENSE_URI = "https://creativecommons.org/licenses/by/4.0/"
PUBLISHER_NAME = "VRMAC-LH prototype consortium (sample)"


# --- helpers -------------------------------------------------------------------------------
def _iso_z(dt: datetime | None) -> str | None:
    """ISO 8601 UTC timestamp with a ``Z`` suffix (seconds precision), as NGSI-LD expects."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None`` / empty-string / empty-list values so we never emit a schema-invalid null."""
    return {k: v for k, v in d.items() if v is not None and v != "" and v != []}


def _join(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip()).strip()


def _bilingual(en: str, local: str) -> str:
    """One description string carrying both languages (the schema's ``description`` is a string)."""
    en, local = (en or "").strip(), (local or "").strip()
    if en and local and en != local:
        return f"{en} | {settings.local_language}: {local}"
    return en or local


def _entity_id(item_type: str, slug: str) -> str:
    """``urn:ngsi-ld:PointOfInterest:vrmac-lh:<item type>:<slug>``.

    The item type is part of the id because ``heritage_entries.slug`` and ``listings.slug`` are only
    unique within their own table: a heritage entry and a listing may share a slug, and two entities
    with the same id would be one entity to any context broker or open-data harvester.
    """
    if item_type not in ITEM_TYPES:  # pragma: no cover - guarded by the callers
        raise ValueError(f"unknown export item type {item_type!r}")
    return f"{ID_PREFIX}{item_type}:{slug}"


def entity_slug(entity: dict[str, Any]) -> str:
    """The item slug behind an exported entity id (the last segment of the id)."""
    return str(entity["id"]).rsplit(":", 1)[-1]


def entity_item_type(entity: dict[str, Any]) -> str:
    """``"heritage_entry"`` / ``"listing"`` — the table an exported entity came from."""
    rest = str(entity["id"])[len(ID_PREFIX):]
    item_type = rest.split(":", 1)[0]
    return item_type if item_type in ITEM_TYPES else ""


def _ref_see_also(village_poi_id: str | None, own_id: str) -> list[str] | None:
    """The village anchor as a one-item ``refSeeAlso``, or ``None``.

    ``None`` when the village has no exported entry of its own **and** when the anchor is this very
    entity: a POI that pointed at itself would tell a context broker that the village is next to
    itself, which is noise at best and a cycle at worst.
    """
    if not village_poi_id or village_poi_id == own_id:
        return None
    return [village_poi_id]


# --- territory: village + municipality ------------------------------------------------------
VILLAGE_NOTE_RE = re.compile(r"\[village: (?P<slug>[a-z0-9-]+) — (?P<name>[^,]+), (?P<mun>[^\]]+?) municipality\]")


def address_of(village: Village) -> dict[str, str]:
    """``Location-Commons.address`` of a village: locality, region (municipality), country.

    Only properties defined by the vendored ``address`` definition are used.
    """
    return {
        "addressLocality": village.name_en or village.name_local,
        "addressRegion": f"{village.municipality} municipality, {REGION_SUFFIX}",
        "addressCountry": ADDRESS_COUNTRY,
    }


def village_note(village: Village) -> str:
    """Machine-readable territory note carried inside ``description`` (the schema has no
    village attribute, and inventing one would only pass because ``additionalProperties`` is
    unrestricted)."""
    return (
        f"[village: {village.slug} — {village.name_en or village.name_local}, "
        f"{village.municipality} municipality]"
    )


def village_slug_of(entity: dict[str, Any]) -> str | None:
    """Read the village slug back out of an exported (key-values) entity."""
    match = VILLAGE_NOTE_RE.search(str(entity.get("description", "")))
    return match.group("slug") if match else None


def municipality_of(entity: dict[str, Any]) -> str | None:
    """Read the municipality back out of an exported entity's ``address.addressRegion``."""
    region = (entity.get("address") or {}).get("addressRegion")
    return region.split(" municipality", 1)[0] if region else None


# --- listing helpers ------------------------------------------------------------------------
def _price_range(listing: Listing) -> str | None:
    lo, hi, cur = listing.price_min, listing.price_max, listing.currency or "EUR"
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None:
        core = f"{lo:g}–{hi:g} {cur}" if lo != hi else f"{lo:g} {cur}"
    elif lo is not None:
        core = f"from {lo:g} {cur}"
    else:
        core = f"up to {hi:g} {cur}"
    note = (listing.price_note_en or listing.price_note_local or "").strip()
    return f"{core} {note}".strip() if note else core


def season_text(listing: Listing) -> tuple[str, str]:
    """(English, Montenegrin) sentence built from ``season_all_year`` / ``season_from`` / ``season_to``."""
    if listing.season_all_year:
        return ("Season: open all year.", "Sezona: otvoreno cijele godine.")
    start, end = listing.season_from, listing.season_to
    if start and end:
        return (
            f"Season: {MONTHS_EN[start - 1]}–{MONTHS_EN[end - 1]}.",
            f"Sezona: {MONTHS_LOCAL[start - 1]}–{MONTHS_LOCAL[end - 1]}.",
        )
    if start:
        return (
            f"Season: from {MONTHS_EN[start - 1]} onwards.",
            f"Sezona: od {MONTHS_LOCAL_GENITIVE[start - 1]} nadalje.",
        )
    if end:
        return (
            f"Season: until {MONTHS_EN[end - 1]}.",
            f"Sezona: do {MONTHS_LOCAL_GENITIVE[end - 1]}.",
        )
    return ("Season: not stated by the host.", "Sezona: domaćin nije naveo.")


def accessibility_text(listing: Listing) -> tuple[str, str]:
    """(English, Montenegrin) sentence built from ``accessibility_step_free`` + the host's note."""
    step_free = listing.accessibility_step_free
    if step_free is True:
        en, local = ["Accessibility: step-free access."], ["Pristupačnost: pristup bez stepenica."]
    elif step_free is False:
        en, local = ["Accessibility: not step-free."], ["Pristupačnost: nije bez stepenica."]
    else:
        en, local = ["Accessibility: not stated by the host."], ["Pristupačnost: domaćin nije naveo."]
    if (listing.accessibility_note_en or "").strip():
        en.append(listing.accessibility_note_en.strip())
    if (listing.accessibility_note_local or "").strip():
        local.append(listing.accessibility_note_local.strip())
    return (_join(en), _join(local))


def _confirmed_text(listing: Listing) -> tuple[str, str]:
    """What the host actually confirmed (``confirmed_fields``) — never model-inferred."""
    en_labels: list[str] = []
    local_labels: list[str] = []
    for field in listing.confirmed_fields or []:
        label = CONFIRMED_LABELS.get(str(field))
        if label is None:
            label = (str(field), str(field))
        if label[0] not in en_labels:
            en_labels.append(label[0])
            local_labels.append(label[1])
    if not en_labels:
        return ("Structured details were not confirmed by the host.", "Domaćin nije potvrdio strukturirana polja.")
    return (
        "Host-confirmed: " + ", ".join(en_labels) + ".",
        "Domaćin potvrdio: " + ", ".join(local_labels) + ".",
    )


# --- mapping: our rows → key-values entities ------------------------------------------------
def heritage_entry_to_keyvalues(
    entry: HeritageEntry, base_url: str | None = None, village_poi_id: str | None = None
) -> KeyValues:
    """Map an approved heritage entry (with coordinates) to a key-values ``PointOfInterest``."""
    village = entry.village
    urls = [s.get("url") for s in (entry.sources or []) if isinstance(s, dict) and s.get("url")]
    see_also = list(dict.fromkeys(urls))  # unique, order preserved
    description = _join(
        [
            _bilingual(entry.summary_en, entry.summary_local),
            village_note(village),
            COORDS_APPROXIMATE_NOTE if entry.coords_approximate else "",
        ]
    )
    return _clean(
        {
            "id": _entity_id(HERITAGE_ITEM_TYPE, entry.slug),
            "type": ENTITY_TYPE,
            "name": entry.title_en or entry.title_local,
            "alternateName": entry.title_local,
            "description": description,
            "category": _heritage_category(entry),
            "location": {"type": "Point", "coordinates": [entry.lng, entry.lat]},
            "address": address_of(village),
            "areaServed": village.name_en or village.name_local,
            # A village never points at itself: on the entity that *is* the village, the anchor
            # id equals this entity's own id.
            "refSeeAlso": _ref_see_also(village_poi_id, _entity_id(HERITAGE_ITEM_TYPE, entry.slug)),
            "source": see_also[0] if see_also else entry.source,
            "seeAlso": see_also or None,
            "additionalInfoURL": f"{base_url}/api/heritage/{entry.slug}" if base_url else None,
            "dataProvider": DATA_PROVIDER,
            "dateCreated": _iso_z(entry.created_at),
            "dateModified": _iso_z(entry.updated_at),
        }
    )


def _heritage_category(entry: HeritageEntry) -> list[str]:
    tags = {str(t).lower() for t in (entry.tags or [])}
    if entry.kind == "place":
        return ["town" if "town" in tags else "village"]
    if entry.kind == "institution" and "culture-house" in tags:
        return ["culture_house"]
    return [HERITAGE_CATEGORY.get(entry.kind, entry.kind.replace("-", "_"))]


def listing_to_keyvalues(
    listing: Listing, base_url: str | None = None, village_poi_id: str | None = None
) -> KeyValues:
    """Map an approved listing (with coordinates) to a key-values ``PointOfInterest``.

    ``season``, ``accessibility``, price and capacity come from the **host-confirmed structured
    fields**; nothing here is inferred by a model. Never exports host identity: no names,
    e-mails, phone numbers or user ids.
    """
    village = listing.village
    season_en, season_local = season_text(listing)
    access_en, access_local = accessibility_text(listing)
    confirmed_en, confirmed_local = _confirmed_text(listing)
    en_parts = [(listing.description_en or "").strip(), season_en, access_en, confirmed_en]
    local_parts = [(listing.description_local or "").strip(), season_local, access_local, confirmed_local]
    if listing.is_sample:
        if "sample" not in " ".join(en_parts).lower():
            en_parts.append("Sample provider (fictional).")
        if "uzorak" not in " ".join(local_parts).lower():
            local_parts.append("Uzorak — nije stvarni ponuđač.")
    description = _join(
        [
            _bilingual(_join(en_parts), _join(local_parts)),
            village_note(village),
            COORDS_APPROXIMATE_NOTE if listing.coords_approximate else "",
        ]
    )
    contact_point = _clean(
        {
            "contactType": "visitor request through the VRMAC-LH platform (no direct contact details published)",
            "availableLanguage": [settings.local_language, "en"],
            "url": f"{base_url}/api/requests" if base_url else None,
        }
    )
    return _clean(
        {
            "id": _entity_id(LISTING_ITEM_TYPE, listing.slug),
            "type": ENTITY_TYPE,
            "name": listing.title_en or listing.title_local,
            "alternateName": listing.title_local,
            "description": description,
            "category": [listing.category or "other"],
            "location": {"type": "Point", "coordinates": [listing.lng, listing.lat]},
            "address": address_of(village),
            "areaServed": village.name_en or village.name_local,
            # Same rule as for heritage entries: an entity is never its own village anchor.
            "refSeeAlso": _ref_see_also(village_poi_id, _entity_id(LISTING_ITEM_TYPE, listing.slug)),
            "priceRange": _price_range(listing),
            "capacity": listing.capacity,
            "image": f"{base_url}{listing.photo_url}" if base_url and listing.photo_url.startswith("/") else None,
            "contactPoint": contact_point,
            "additionalInfoURL": f"{base_url}/api/listings/{listing.slug}" if base_url else None,
            "source": LISTING_SOURCE,
            "dataProvider": DATA_PROVIDER,
            "dateCreated": _iso_z(listing.created_at),
            "dateModified": _iso_z(listing.published_at or listing.updated_at),
        }
    )


# --- key-values → normalized NGSI-LD --------------------------------------------------------
def to_normalized(kv: KeyValues) -> Normalized:
    """Expand a key-values entity into the normalized NGSI-LD representation.

    * ``location`` → ``GeoProperty``; ``refSeeAlso`` → ``Relationship`` (its ``object`` is the
      entity id of the village's own PointOfInterest); ``dateCreated``/``dateModified`` carry a
      typed ``DateTime`` value; everything else → ``Property``.
    * ``@context`` is the Smart Data Models PointOfInterest context + the NGSI-LD core context.
    """
    out: Normalized = {"id": kv["id"], "type": kv["type"]}
    for key, value in kv.items():
        if key in ("id", "type", "@context"):
            continue
        if key in GEO_ATTRS:
            out[key] = {"type": "GeoProperty", "value": value}
        elif key in RELATIONSHIP_ATTRS:
            out[key] = {"type": "Relationship", "object": value}
        elif key in DATETIME_ATTRS:
            out[key] = {"type": "Property", "value": {"@type": "DateTime", "@value": value}}
        else:
            out[key] = {"type": "Property", "value": value}
    out["@context"] = list(NGSI_LD_CONTEXT)
    return out


# --- data access -----------------------------------------------------------------------------
@dataclass(frozen=True)
class PoiRecord:
    """One exported point of interest and where it belongs in the territory."""

    item_type: str  # "heritage_entry" | "listing"
    slug: str
    village_slug: str
    village_name: str
    municipality: str
    keyvalues: KeyValues
    normalized: Normalized


def _approved_rows(db: Session, model: type) -> list:
    """Approved rows with coordinates, deterministic order; re-checks ``status`` defensively."""
    stmt = (
        approved_only(select(model), model)
        .where(model.lat.is_not(None), model.lng.is_not(None))
        .options(joinedload(model.village))
    )
    rows = list(db.scalars(stmt.order_by(model.slug)))
    for row in rows:
        if row.status != "approved":  # belt and braces: never export non-validated content
            raise RuntimeError(f"export refused: {model.__tablename__} {row.slug} has status {row.status!r}")
        if row.village is None:  # village_id is mandatory; a NULL would lose the territory
            raise RuntimeError(f"export refused: {model.__tablename__} {row.slug} has no village")
    return rows


def poi_records(db: Session, base_url: str | None = None) -> list[PoiRecord]:
    """All exportable POIs with their territory metadata.

    Exported: approved heritage entries with coordinates (every kind) followed by approved
    listings with coordinates. ``base_url`` (no trailing slash) is optional; when given, the
    entities carry absolute ``additionalInfoURL``/``image``/``contactPoint.url`` links into this
    deployment.
    """
    entries = _approved_rows(db, HeritageEntry)
    listings = _approved_rows(db, Listing)
    # A village that has its own approved "place" entry becomes the anchor entity every other POI
    # of that village points at with an NGSI-LD Relationship.
    village_poi: dict[str, str] = {
        e.village.slug: _entity_id(HERITAGE_ITEM_TYPE, e.slug)
        for e in entries
        if e.kind == "place" and e.slug == e.village.slug
    }
    records: list[PoiRecord] = []
    for entry in entries:
        kv = heritage_entry_to_keyvalues(entry, base_url, village_poi.get(entry.village.slug))
        records.append(
            PoiRecord(
                item_type="heritage_entry",
                slug=entry.slug,
                village_slug=entry.village.slug,
                village_name=entry.village.name_en or entry.village.name_local,
                municipality=entry.village.municipality,
                keyvalues=kv,
                normalized=to_normalized(kv),
            )
        )
    for listing in listings:
        kv = listing_to_keyvalues(listing, base_url, village_poi.get(listing.village.slug))
        records.append(
            PoiRecord(
                item_type="listing",
                slug=listing.slug,
                village_slug=listing.village.slug,
                village_name=listing.village.name_en or listing.village.name_local,
                municipality=listing.village.municipality,
                keyvalues=kv,
                normalized=to_normalized(kv),
            )
        )
    return records


def poi_entities(db: Session, base_url: str | None = None) -> list[tuple[KeyValues, Normalized]]:
    """All exportable POIs as ``(key_values_entity, normalized_entity)`` pairs."""
    return [(r.keyvalues, r.normalized) for r in poi_records(db, base_url)]


# --- offline schema validation ---------------------------------------------------------------
def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


#: RFC 3986 absolute-URI shape, checked without ``rfc3987`` — that package is not in ``backend/.venv``
#: and the export has to validate on an offline demo laptop, so the check stays dependency-free:
#: ``scheme ":" hier-part [ "?" query ] [ "#" fragment ]`` where every character after the scheme is
#: from the RFC 3986 set — a raw space, a tab, a newline or any other character outside that set is
#: rejected instead of quietly accepted. (Non-ASCII IRIs are rejected too; the export emits none.)
URI_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9+.\-]*:"                      # scheme, then the hier-part:
    r"[A-Za-z0-9\-._~%!$&'()*+,;=:@/?#\[\]]+$"          # unreserved / pct-encoded / sub-delims / …
)


def _format_checker() -> FormatChecker:
    """Format checks that work without optional dependencies (rfc3339-validator, rfc3987)."""
    checker = FormatChecker(formats=())

    @checker.checks("date-time", raises=ValueError)
    def _date_time(instance: Any) -> bool:
        if not isinstance(instance, str):
            return True
        parsed = datetime.fromisoformat(instance)
        if parsed.tzinfo is None or "T" not in instance.upper():
            raise ValueError(f"{instance!r} is not an RFC 3339 date-time with time zone")
        return True

    @checker.checks("uri", raises=ValueError)
    def _uri(instance: Any) -> bool:
        """Absolute URI (RFC 3986). Deliberately stricter than "has a scheme and something after it":
        a value with a space, a control character or an empty authority is not a URI, and a harvester
        that dereferences ``seeAlso`` would choke on it."""
        if not isinstance(instance, str):
            return True
        if not URI_RE.match(instance):
            raise ValueError(f"{instance!r} is not an absolute RFC 3986 URI")
        parts = urlparse(instance)
        if not parts.scheme or not (parts.netloc or parts.path):
            raise ValueError(f"{instance!r} is not an absolute URI")
        # "scheme://" with no host: urlparse is happy, RFC 3986 is not.
        if instance[len(parts.scheme) + 1:].startswith("//") and not parts.netloc:
            raise ValueError(f"{instance!r} has an empty authority")
        return True

    return checker


@lru_cache(maxsize=1)
def registry() -> Registry:
    """Offline ``referencing`` registry: the public Smart Data Models URIs → the vendored files.

    ``smart-data-models.github.io`` is never contacted; every ``$ref`` in the PointOfInterest
    schema resolves from ``backend/schemas/sdm``.
    """
    return Registry().with_resources(
        [
            (POI_SCHEMA_URI, Resource.from_contents(_load_schema("PointOfInterest.schema.json"))),
            (COMMON_SCHEMA_URI, Resource.from_contents(_load_schema("common-schema.json"))),
        ]
    )


@lru_cache(maxsize=1)
def poi_validator() -> Draft202012Validator:
    """Validator for the vendored PointOfInterest schema; every ``$ref`` resolves offline."""
    poi_schema = _load_schema("PointOfInterest.schema.json")
    Draft202012Validator.check_schema(poi_schema)
    return Draft202012Validator(poi_schema, registry=registry(), format_checker=_format_checker())


@lru_cache(maxsize=1)
def known_attributes() -> frozenset[str]:
    """Every attribute name the vendored PointOfInterest schema (and its ``allOf`` refs) defines.

    The schema does not set ``additionalProperties: false``, so an invented attribute would slip
    through validation unnoticed. The export therefore restricts itself to these names and
    ``export_all`` reports any drift (``unknown_attributes``).
    """
    resolver = registry().resolver()
    names: set[str] = set()

    def collect(subschema: dict[str, Any]) -> None:
        ref = subschema.get("$ref")
        if ref:
            subschema = resolver.lookup(ref).contents
        names.update(subschema.get("properties", {}))
        for branch in subschema.get("allOf", []):
            collect(branch)

    collect(poi_validator().schema)
    return frozenset(names)


def unknown_attributes(kv: KeyValues) -> list[str]:
    """Attributes of an entity that the schema does not define (must always be empty)."""
    return sorted(k for k in kv if k not in known_attributes() and k != "@context")


def schema_version() -> str:
    return str(poi_validator().schema.get("$schemaVersion", "unknown"))


def validate_entity(kv: KeyValues) -> list[dict[str, Any]]:
    """Errors (empty list = valid) of one key-values entity against the PointOfInterest schema."""
    errors = []
    for err in sorted(poi_validator().iter_errors(kv), key=lambda e: list(e.path)):
        errors.append(
            {
                "id": kv.get("id"),
                "path": "/".join(str(p) for p in err.path) or "<entity>",
                "message": err.message,
                "validator": err.validator,
            }
        )
    for name in unknown_attributes(kv):
        errors.append(
            {
                "id": kv.get("id"),
                "path": name,
                "message": f"{name!r} is not defined by the PointOfInterest schema",
                "validator": "knownAttributes",
            }
        )
    return errors


def validate_entities(entities: list[KeyValues]) -> list[dict[str, Any]]:
    """Errors over a whole key-values list (empty list = the export validates)."""
    out: list[dict[str, Any]] = []
    for kv in entities:
        out.extend(validate_entity(kv))
    return out


# --- DCAT-AP ---------------------------------------------------------------------------------
def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    """(min_lng, min_lat, max_lng, max_lat) of the exported points."""
    if not points:
        return None
    lngs = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lngs), min(lats), max(lngs), max(lats))


def _lang(en: str, local: str) -> list[dict[str, str]]:
    return [{"@value": en, "@language": "en"}, {"@value": local, "@language": settings.local_language}]


def _xsd_dt(value: str) -> dict[str, str]:
    return {"@value": value, "@type": "xsd:dateTime"}


def municipalities_en(municipalities: list[str]) -> str:
    """``["Tivat"]`` → ``"Tivat municipality"``; two → ``"Tivat and Kotor municipalities"``."""
    if not municipalities:
        return ""
    if len(municipalities) == 1:
        return f"{municipalities[0]} municipality"
    return " and ".join(municipalities) + " municipalities"


def municipalities_local(municipalities: list[str]) -> str:
    """``["Tivat"]`` → ``"opština Tivat"``; two → ``"opštine Tivat i Kotor"``."""
    if not municipalities:
        return ""
    if len(municipalities) == 1:
        return f"opština {municipalities[0]}"
    return "opštine " + " i ".join(municipalities)


def territory_note(municipalities: list[str]) -> tuple[str, str]:
    """What the export *covers* and what it does not — derived from the exported entities.

    The dataset title must never name a municipality the payload does not contain: a harvester reads
    the title as the dataset's scope. Anything of the territory that is not (yet) exported is stated
    here, in the description, as a limitation instead of being asserted as coverage.
    """
    covered = [m for m in MUNICIPALITIES if m in municipalities] + [
        m for m in municipalities if m not in MUNICIPALITIES
    ]
    missing = [m for m in MUNICIPALITIES if m not in municipalities]
    if not covered:
        return (
            "This export currently contains no validated point of interest, so it covers no "
            "municipality of the Vrmac territory yet.",
            "Ovaj izvoz trenutno ne sadrži nijednu validiranu tačku interesa, pa još ne pokriva "
            "nijednu opštinu vrmačke teritorije.",
        )
    en = f"Territory covered by this export: {municipalities_en(covered)}, Bay of Kotor."
    local = f"Teritorija koju pokriva ovaj izvoz: {municipalities_local(covered)}, Boka Kotorska."
    if missing:
        en += (
            " The prototype's territory also reaches the other side of the ridge "
            f"({municipalities_en(missing)}), but nothing from there has passed the validation gate "
            "yet — its facts could not be checked against a public source in this build — so this "
            "dataset contains none of it."
        )
        local += (
            " Teritorija prototipa obuhvata i drugu stranu grebena "
            f"({municipalities_local(missing)}), ali odatle još ništa nije prošlo validaciju, pa "
            "ovaj skup podataka to ne sadrži."
        )
    return en, local


def dcat_ap(db: Session, base_url: str) -> dict[str, Any]:
    """DCAT-AP (JSON-LD) description of the NGSI-LD export as one ``dcat:Dataset``."""
    base_url = base_url.rstrip("/")
    records = poi_records(db)
    entities = [r.keyvalues for r in records]
    points = [(kv["location"]["coordinates"][0], kv["location"]["coordinates"][1]) for kv in entities]
    bbox = _bbox(points)
    created = [kv["dateCreated"] for kv in entities if kv.get("dateCreated")]
    modified = [kv["dateModified"] for kv in entities if kv.get("dateModified")]
    now = _iso_z(datetime.now(timezone.utc))
    n_entries = sum(1 for r in records if r.item_type == "heritage_entry")
    n_listings = sum(1 for r in records if r.item_type == "listing")
    categories = sorted({c for kv in entities for c in kv.get("category", [])})
    villages = sorted({r.village_name for r in records})
    municipalities = sorted({r.municipality for r in records})
    # The title names the municipalities the payload actually contains — never the territory the
    # prototype hopes to cover. What is missing is said in the description (see territory_note).
    territory_en, territory_local = territory_note(municipalities)
    scope_en, scope_local = municipalities_en(municipalities), municipalities_local(municipalities)
    title_en = "Vrmac Living Heritage — points of interest" + (f" ({scope_en})" if scope_en else "")
    title_local = "Vrmac živa baština — tačke interesa" + (f" ({scope_local})" if scope_local else "")

    spatial: dict[str, Any] | None = None
    if bbox:
        min_lng, min_lat, max_lng, max_lat = bbox
        wkt = (
            f"POLYGON(({min_lng} {min_lat}, {max_lng} {min_lat}, {max_lng} {max_lat}, "
            f"{min_lng} {max_lat}, {min_lng} {min_lat}))"
        )
        geojson = {
            "type": "Polygon",
            "coordinates": [
                [
                    [min_lng, min_lat],
                    [max_lng, min_lat],
                    [max_lng, max_lat],
                    [min_lng, max_lat],
                    [min_lng, min_lat],
                ]
            ],
        }
        spatial = {
            "@type": "dct:Location",
            "rdfs:label": _lang(
                "Vrmac — " + " and ".join(f"{m} municipality" for m in municipalities) + ", Bay of Kotor, Montenegro",
                "Vrmac — " + " i ".join(f"opština {m}" for m in municipalities) + ", Boka Kotorska, Crna Gora",
            ),
            "dcat:bbox": {"@value": wkt, "@type": "geo:wktLiteral"},
            "locn:geometry": {
                "@value": json.dumps(geojson, separators=(",", ":")),
                "@type": f"{IANA_MEDIA_TYPE}application/vnd.geo+json",
            },
        }

    temporal = {
        "@type": "dct:PeriodOfTime",
        "dcat:startDate": _xsd_dt(min(created) if created else now),
        "dcat:endDate": _xsd_dt(max(modified) if modified else now),
    }

    prototype_note = (
        f"{PROTOTYPE_LABEL} The heritage entries are public facts with cited sources; the provider listings "
        "are fictional sample providers. Coordinates are approximate until surveyed. Only content that passed "
        "the validation gate (status 'approved') is exported — unverified villages and their entries are not."
    )
    prototype_note_local = (
        "Prototip za prijavu SMART ERA, septembar–oktobar 2026. Uzorak podataka: unosi baštine su javne "
        "činjenice sa izvorima, a ponuđači su izmišljeni uzorci. Koordinate su približne. Izvozi se samo "
        "sadržaj koji je prošao validaciju."
    )
    distributions = [
        {
            "@id": f"{base_url}/api/export/dcat-ap#ngsi-ld-normalized",
            "@type": "dcat:Distribution",
            "dct:title": _lang(
                "NGSI-LD PointOfInterest entities (normalized)",
                "NGSI-LD PointOfInterest entiteti (normalizovani)",
            ),
            "dct:description": _lang(
                "Full NGSI-LD representation (Property / GeoProperty / Relationship) with @context, ready for "
                "POST /ngsi-ld/v1/entityOperations/upsert on an NGSI-LD context broker.",
                "Puna NGSI-LD reprezentacija (Property / GeoProperty / Relationship) sa @context, spremna za "
                "upsert u NGSI-LD broker.",
            ),
            "dcat:accessURL": {"@id": f"{base_url}/api/export/ngsi-ld"},
            "dcat:downloadURL": {"@id": f"{base_url}/api/export/ngsi-ld"},
            "dcat:mediaType": {"@id": f"{IANA_MEDIA_TYPE}application/ld+json"},
            "dct:format": {"@id": "http://publications.europa.eu/resource/authority/file-type/JSON_LD"},
            "dct:conformsTo": {"@id": POI_SCHEMA_URI},
            "dct:license": {"@id": LICENSE_URI},
        },
        {
            "@id": f"{base_url}/api/export/dcat-ap#ngsi-ld-keyvalues",
            "@type": "dcat:Distribution",
            "dct:title": _lang(
                "NGSI-LD PointOfInterest entities (key-values)",
                "NGSI-LD PointOfInterest entiteti (key-values)",
            ),
            "dct:description": _lang(
                "Simplified key-values representation — the form the Smart Data Models JSON schema describes "
                f"and the one validated offline against PointOfInterest {schema_version()}.",
                "Pojednostavljena key-values reprezentacija — oblik koji opisuje JSON šema Smart Data Models "
                f"i koji se offline validira prema PointOfInterest {schema_version()}.",
            ),
            "dcat:accessURL": {"@id": f"{base_url}/api/export/ngsi-ld/keyvalues"},
            "dcat:downloadURL": {"@id": f"{base_url}/api/export/ngsi-ld/keyvalues"},
            "dcat:mediaType": {"@id": f"{IANA_MEDIA_TYPE}application/json"},
            "dct:format": {"@id": "http://publications.europa.eu/resource/authority/file-type/JSON"},
            "dct:conformsTo": {"@id": POI_SCHEMA_URI},
            "dct:license": {"@id": LICENSE_URI},
        },
    ]

    dataset: dict[str, Any] = {
        "@context": dict(DCAT_CONTEXT),
        "@id": f"{base_url}/api/export/dcat-ap#dataset",
        "@type": "dcat:Dataset",
        "dct:identifier": "vrmac-lh-points-of-interest",
        "dct:title": _lang(title_en, title_local),
        "dct:description": _lang(
            "Validated heritage entries (villages, churches, events, traditions, culture house, landscape) and "
            "provider listings (accommodation, food, guiding, craft) of the Vrmac plateau, exported as NGSI-LD "
            "PointOfInterest entities following the FIWARE Smart Data Models. Every entity carries its village "
            f"(addressLocality) and municipality (addressRegion). {territory_en} " + prototype_note,
            "Validirani unosi baštine (naselja, crkve, događaji, tradicije, dom kulture, pejzaž) i ponude "
            "(smještaj, hrana, vođenje, zanati) sa vrmačke visoravni, izvezeni kao NGSI-LD PointOfInterest "
            "entiteti prema FIWARE Smart Data Models. Svaki entitet nosi svoje selo (addressLocality) i opštinu "
            f"(addressRegion). {territory_local} " + prototype_note_local,
        ),
        "dct:publisher": {"@type": "foaf:Agent", "foaf:name": PUBLISHER_NAME},
        "dcat:contactPoint": {
            "@type": "vcard:Kind",
            "vcard:fn": "VRMAC-LH prototype team (sample — no personal contact published)",
        },
        "dct:license": {"@id": LICENSE_URI},
        "dct:accessRights": {"@id": "http://publications.europa.eu/resource/authority/access-right/PUBLIC"},
        "dcat:keyword": [
            "heritage", "Vrmac", "Boka Kotorska", "Bay of Kotor", "Montenegro", "point of interest",
            "NGSI-LD", "Smart Data Models", "DCAT-AP", "rural tourism", "cultural landscape",
            *[f"{m} municipality" for m in municipalities], *villages, *categories,
        ],
        "dcat:theme": [{"@id": f"{EU_THEME}EDUC"}, {"@id": f"{EU_THEME}ENVI"}, {"@id": f"{EU_THEME}REGI"}],
        "dct:language": [{"@id": f"{EU_LANGUAGE}ENG"}, {"@id": f"{EU_LANGUAGE}CNR"}],
        "dct:spatial": spatial,
        "dct:temporal": temporal,
        "dct:accrualPeriodicity": {"@id": f"{EU_FREQUENCY}CONT"},
        "dct:issued": _xsd_dt(min(created) if created else now),
        "dct:modified": _xsd_dt(max(modified) if modified else now),
        "dct:conformsTo": {"@id": POI_SCHEMA_URI},
        "dct:provenance": {"@type": "dct:ProvenanceStatement", "rdfs:label": prototype_note},
        "dcat:landingPage": {"@id": f"{base_url}/api/docs"},
        "dcat:distribution": distributions,
        "rdfs:comment": (
            f"{len(entities)} PointOfInterest entities ({n_entries} heritage entries, {n_listings} sample "
            f"listings) in {len(villages)} village(s) of {len(municipalities)} municipality(ies). Key-values "
            f"form validated offline against the vendored Smart Data Models schema version {schema_version()}."
        ),
    }
    return _clean(dataset)


# --- files -----------------------------------------------------------------------------------
def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def export_all(db: Session, out_dir: str | Path, base_url: str = "http://localhost:8000") -> dict[str, Any]:
    """Write the NGSI-LD (normalized + key-values), DCAT-AP and validation-report files.

    Returns ``{n_entities, valid, files, errors, schema_version, villages, municipalities}``.
    ``valid`` is ``False`` (with the schema errors listed) when any entity fails validation — the
    files are still written so the problem can be inspected, but the result never claims success.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pairs = poi_entities(db, base_url)
    keyvalues = [kv for kv, _ in pairs]
    normalized = [norm for _, norm in pairs]
    errors = validate_entities(keyvalues)
    valid = not errors
    villages = sorted({v for v in (village_slug_of(kv) for kv in keyvalues) if v})
    municipalities = sorted({m for m in (municipality_of(kv) for kv in keyvalues) if m})
    report = {
        "schema_id": POI_SCHEMA_URI,
        "schema_version": schema_version(),
        "validated_at": _iso_z(datetime.now(timezone.utc)),
        "n_entities": len(keyvalues),
        "valid": valid,
        "errors": errors,
        "villages": villages,
        "municipalities": municipalities,
        "offline": True,
    }
    files = {
        "normalized": out / EXPORT_FILES["normalized"],
        "keyvalues": out / EXPORT_FILES["keyvalues"],
        "dcat_ap": out / EXPORT_FILES["dcat_ap"],
        "report": out / EXPORT_FILES["report"],
    }
    _write_json(files["normalized"], normalized)
    _write_json(files["keyvalues"], keyvalues)
    _write_json(files["dcat_ap"], dcat_ap(db, base_url))
    _write_json(files["report"], report)
    if not valid:
        log.warning("NGSI-LD export does NOT validate: %d error(s)", len(errors))
    else:
        log.info(
            "NGSI-LD export: %d entities validated against PointOfInterest %s",
            len(keyvalues),
            report["schema_version"],
        )
    return {
        "n_entities": len(keyvalues),
        "valid": valid,
        "schema_version": report["schema_version"],
        "villages": villages,
        "municipalities": municipalities,
        "files": [str(p.resolve()) for p in files.values()],
        "errors": errors,
    }
