"""Interoperability stub (innovation claim #6).

Exports the *approved* heritage entries and provider listings as NGSI-LD ``PointOfInterest``
entities that follow the FIWARE / Smart Data Models ``dataModel.PointOfInterest`` schema, plus a
DCAT-AP dataset description of the export.

Three representations are produced:

* **key-values** – the simplified NGSI-LD representation (``?options=keyValues``). This is the
  form the Smart Data Models JSON schema describes, so this is what is validated.
* **normalized** – the full NGSI-LD representation (``{"type": "Property", "value": …}``,
  ``GeoProperty`` for ``location``) with an ``@context``. This is what an NGSI-LD context broker
  such as Orion-LD ingests (see docs/interoperability.md for the ``curl`` upsert example).
* **DCAT-AP** – a JSON-LD ``dcat:Dataset`` describing the two distributions above.

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
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BACKEND_DIR, PROTOTYPE_LABEL, settings
from ..models import HeritageEntry, Listing
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
DATA_PROVIDER = "VRMAC-LH prototype (SMART ERA)"
ADDRESS: dict[str, str] = {"addressLocality": "Tivat", "addressRegion": "Boka Kotorska", "addressCountry": "ME"}
COORDS_APPROXIMATE_NOTE = "(coordinates approximate)"

# kind of a heritage entry → PointOfInterest category (a list; first item is the primary category)
HERITAGE_CATEGORY: dict[str, str] = {
    "church": "church",
    "building": "building",
    "event": "event",
    "tradition": "tradition",
    "institution": "institution",
    "landscape": "landscape",
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


def _bilingual(en: str, local: str) -> str:
    """One description string carrying both languages (the schema's ``description`` is a string)."""
    en, local = (en or "").strip(), (local or "").strip()
    if en and local and en != local:
        return f"{en} | {settings.local_language}: {local}"
    return en or local


def _entity_id(slug: str) -> str:
    return f"{ID_PREFIX}{slug}"


def _heritage_category(entry: HeritageEntry) -> list[str]:
    tags = {str(t).lower() for t in (entry.tags or [])}
    if entry.kind == "place":
        return ["town" if "town" in tags else "village"]
    if entry.kind == "institution" and "culture-house" in tags:
        return ["culture_house"]
    return [HERITAGE_CATEGORY.get(entry.kind, entry.kind.replace("-", "_"))]


def _price_range(listing: Listing) -> str | None:
    lo, hi, cur = listing.price_min, listing.price_max, listing.currency or "EUR"
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None:
        return f"{lo:g}–{hi:g} {cur}" if lo != hi else f"{lo:g} {cur}"
    return f"from {lo:g} {cur}" if lo is not None else f"up to {hi:g} {cur}"


# --- mapping: our rows → key-values entities ------------------------------------------------
def heritage_entry_to_keyvalues(entry: HeritageEntry, base_url: str | None = None) -> KeyValues:
    """Map an approved heritage entry (with coordinates) to a key-values ``PointOfInterest``."""
    urls = [s.get("url") for s in (entry.sources or []) if isinstance(s, dict) and s.get("url")]
    see_also = list(dict.fromkeys(urls))  # unique, order preserved
    description = _bilingual(entry.summary_en, entry.summary_local)
    if entry.coords_approximate:
        description = f"{description} {COORDS_APPROXIMATE_NOTE}".strip()
    return _clean(
        {
            "id": _entity_id(entry.slug),
            "type": ENTITY_TYPE,
            "name": entry.title_en or entry.title_local,
            "alternateName": entry.title_local,
            "description": description,
            "category": _heritage_category(entry),
            "location": {"type": "Point", "coordinates": [entry.lng, entry.lat]},
            "address": dict(ADDRESS),
            "source": see_also[0] if see_also else entry.source,
            "seeAlso": see_also or None,
            "additionalInfoURL": f"{base_url}/api/heritage/{entry.slug}" if base_url else None,
            "dataProvider": DATA_PROVIDER,
            "dateCreated": _iso_z(entry.created_at),
            "dateModified": _iso_z(entry.updated_at),
        }
    )


def listing_to_keyvalues(listing: Listing, base_url: str | None = None) -> KeyValues:
    """Map an approved listing (with coordinates) to a key-values ``PointOfInterest``.

    Never exports host identity: no names, e-mails, phone numbers or user ids.
    """
    description = _bilingual(listing.description_en, listing.description_local)
    extras: list[str] = []
    if listing.season:
        extras.append(f"Season: {listing.season}.")
    if listing.accessibility_en or listing.accessibility_local:
        extras.append("Accessibility: " + _bilingual(listing.accessibility_en, listing.accessibility_local))
    if listing.is_sample and "sample" not in description.lower():
        extras.append("Sample provider (fictional).")
    if listing.coords_approximate:
        extras.append(COORDS_APPROXIMATE_NOTE)
    if extras:
        description = " ".join([description, *extras]).strip()
    contact_point = _clean(
        {
            "contactType": "visitor request through the VRMAC-LH platform (no direct contact details published)",
            "availableLanguage": [settings.local_language, "en"],
            "url": f"{base_url}/api/requests" if base_url else None,
        }
    )
    return _clean(
        {
            "id": _entity_id(listing.slug),
            "type": ENTITY_TYPE,
            "name": listing.title_en or listing.title_local,
            "alternateName": listing.title_local,
            "description": description,
            "category": [listing.category or "other"],
            "location": {"type": "Point", "coordinates": [listing.lng, listing.lat]},
            "address": dict(ADDRESS),
            "priceRange": _price_range(listing),
            "capacity": listing.capacity,
            "image": f"{base_url}{listing.photo_url}" if base_url and listing.photo_url.startswith("/") else None,
            "contactPoint": contact_point,
            "additionalInfoURL": f"{base_url}/api/listings/{listing.slug}" if base_url else None,
            "source": "VRMAC-LH host onboarding (validated listing)",
            "dataProvider": DATA_PROVIDER,
            "dateCreated": _iso_z(listing.created_at),
            "dateModified": _iso_z(listing.published_at or listing.updated_at),
        }
    )


# --- key-values → normalized NGSI-LD --------------------------------------------------------
def to_normalized(kv: KeyValues) -> Normalized:
    """Expand a key-values entity into the normalized NGSI-LD representation.

    * ``location`` → ``GeoProperty``; ``dateCreated``/``dateModified`` → ``DateTime`` values;
      everything else → ``Property``. There are no relationships in this export.
    * ``@context`` is the Smart Data Models PointOfInterest context + the NGSI-LD core context.
    """
    out: Normalized = {"id": kv["id"], "type": kv["type"]}
    for key, value in kv.items():
        if key in ("id", "type", "@context"):
            continue
        if key == "location":
            out[key] = {"type": "GeoProperty", "value": value}
        elif key in ("dateCreated", "dateModified"):
            out[key] = {"type": "Property", "value": {"@type": "DateTime", "@value": value}}
        else:
            out[key] = {"type": "Property", "value": value}
    out["@context"] = list(NGSI_LD_CONTEXT)
    return out


# --- data access -----------------------------------------------------------------------------
def _approved_rows(db: Session, model: type) -> list:
    """Approved rows with coordinates, deterministic order; re-checks ``status`` defensively."""
    stmt = approved_only(select(model), model).where(model.lat.is_not(None), model.lng.is_not(None))
    rows = list(db.scalars(stmt.order_by(model.slug)))
    for row in rows:
        if row.status != "approved":  # belt and braces: never export non-validated content
            raise RuntimeError(f"export refused: {model.__tablename__} {row.slug} has status {row.status!r}")
    return rows


def poi_entities(db: Session, base_url: str | None = None) -> list[tuple[KeyValues, Normalized]]:
    """All exportable POIs as ``(key_values_entity, normalized_entity)`` pairs.

    Exported: approved heritage entries with coordinates (every kind) followed by approved listings
    with coordinates. ``base_url`` (no trailing slash) is optional; when given, the entities carry
    absolute ``additionalInfoURL``/``image``/``contactPoint.url`` links into this deployment.
    """
    entries = [heritage_entry_to_keyvalues(e, base_url) for e in _approved_rows(db, HeritageEntry)]
    listings = [listing_to_keyvalues(l, base_url) for l in _approved_rows(db, Listing)]
    return [(kv, to_normalized(kv)) for kv in [*entries, *listings]]


# --- offline schema validation ---------------------------------------------------------------
def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


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
        if not isinstance(instance, str):
            return True
        parts = urlparse(instance)
        if not parts.scheme or not (parts.netloc or parts.path):
            raise ValueError(f"{instance!r} is not an absolute URI")
        return True

    return checker


@lru_cache(maxsize=1)
def poi_validator() -> Draft202012Validator:
    """Validator for the vendored PointOfInterest schema; every ``$ref`` resolves offline."""
    poi_schema = _load_schema("PointOfInterest.schema.json")
    common_schema = _load_schema("common-schema.json")
    registry = Registry().with_resources(
        [
            (POI_SCHEMA_URI, Resource.from_contents(poi_schema)),
            (COMMON_SCHEMA_URI, Resource.from_contents(common_schema)),
        ]
    )
    Draft202012Validator.check_schema(poi_schema)
    return Draft202012Validator(poi_schema, registry=registry, format_checker=_format_checker())


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


def dcat_ap(db: Session, base_url: str) -> dict[str, Any]:
    """DCAT-AP (JSON-LD) description of the NGSI-LD export as one ``dcat:Dataset``."""
    base_url = base_url.rstrip("/")
    entities = [kv for kv, _ in poi_entities(db)]
    points = [(kv["location"]["coordinates"][0], kv["location"]["coordinates"][1]) for kv in entities]
    bbox = _bbox(points)
    created = [kv["dateCreated"] for kv in entities if kv.get("dateCreated")]
    modified = [kv["dateModified"] for kv in entities if kv.get("dateModified")]
    now = _iso_z(datetime.now(timezone.utc))
    n_entries = sum(1 for kv in entities if kv["id"].endswith(tuple(f":{s}" for s in _heritage_slugs(entities))))
    categories = sorted({c for kv in entities for c in kv.get("category", [])})

    spatial: dict[str, Any] | None = None
    if bbox:
        min_lng, min_lat, max_lng, max_lat = bbox
        wkt = (
            f"POLYGON(({min_lng} {min_lat}, {max_lng} {min_lat}, {max_lng} {max_lat}, "
            f"{min_lng} {max_lat}, {min_lng} {min_lat}))"
        )
        geojson = {
            "type": "Polygon",
            "coordinates": [[[min_lng, min_lat], [max_lng, min_lat], [max_lng, max_lat], [min_lng, max_lat], [min_lng, min_lat]]],
        }
        spatial = {
            "@type": "dct:Location",
            "dcat:bbox": {"@value": wkt, "@type": "geo:wktLiteral"},
            "locn:geometry": {
                "@value": json.dumps(geojson, separators=(",", ":")),
                "@type": f"{IANA_MEDIA_TYPE}application/vnd.geo+json",
            },
        }

    prototype_note = (
        f"{PROTOTYPE_LABEL} The heritage entries are public facts with cited sources; the provider listings "
        "are fictional sample providers. Coordinates are approximate until surveyed. Only content that passed "
        "the validation gate (status 'approved') is exported."
    )
    distributions = [
        {
            "@id": f"{base_url}/api/export/dcat-ap#ngsi-ld-normalized",
            "@type": "dcat:Distribution",
            "dct:title": _lang("NGSI-LD PointOfInterest entities (normalized)", "NGSI-LD PointOfInterest entiteti (normalizovani)"),
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
            "dct:title": _lang("NGSI-LD PointOfInterest entities (key-values)", "NGSI-LD PointOfInterest entiteti (key-values)"),
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
        "dct:title": _lang(
            "Vrmac Living Heritage — points of interest (Gornja Lastva, Tivat)",
            "Vrmac živa baština — tačke interesa (Gornja Lastva, Tivat)",
        ),
        "dct:description": _lang(
            "Validated heritage entries (villages, churches, events, traditions, culture house, landscape) and "
            "provider listings (accommodation, food, guiding, craft) on the Vrmac peninsula, exported as NGSI-LD "
            "PointOfInterest entities following the FIWARE Smart Data Models. " + prototype_note,
            "Validirani unosi baštine (naselja, crkve, događaji, tradicije, dom kulture, pejzaž) i ponude "
            "(smještaj, hrana, vođenje, zanati) na poluostrvu Vrmac, izvezeni kao NGSI-LD PointOfInterest entiteti "
            "prema FIWARE Smart Data Models. Prototip — uzorak podataka; ponuđači su izmišljeni.",
        ),
        "dct:publisher": {"@type": "foaf:Agent", "foaf:name": PUBLISHER_NAME},
        "dcat:contactPoint": {
            "@type": "vcard:Kind",
            "vcard:fn": "VRMAC-LH prototype team (sample — no personal contact published)",
        },
        "dct:license": {"@id": LICENSE_URI},
        "dct:accessRights": {"@id": "http://publications.europa.eu/resource/authority/access-right/PUBLIC"},
        "dcat:keyword": [
            "heritage", "Vrmac", "Gornja Lastva", "Tivat", "Boka Kotorska", "Montenegro", "point of interest",
            "NGSI-LD", "Smart Data Models", "rural tourism", "cultural landscape", *categories,
        ],
        "dcat:theme": [{"@id": f"{EU_THEME}EDUC"}, {"@id": f"{EU_THEME}ENVI"}, {"@id": f"{EU_THEME}REGI"}],
        "dct:language": [{"@id": f"{EU_LANGUAGE}ENG"}, {"@id": f"{EU_LANGUAGE}CNR"}],
        "dct:spatial": spatial,
        "dct:accrualPeriodicity": {"@id": f"{EU_FREQUENCY}CONT"},
        "dct:issued": {"@value": min(created) if created else now, "@type": "xsd:dateTime"},
        "dct:modified": {"@value": max(modified) if modified else now, "@type": "xsd:dateTime"},
        "dct:conformsTo": {"@id": POI_SCHEMA_URI},
        "dct:provenance": {"@type": "dct:ProvenanceStatement", "rdfs:label": prototype_note},
        "dcat:landingPage": {"@id": f"{base_url}/api/docs"},
        "dcat:distribution": distributions,
        "rdfs:comment": (
            f"{len(entities)} PointOfInterest entities ({n_entries} heritage entries, {len(entities) - n_entries} "
            "sample listings). Key-values form validated offline against the vendored Smart Data Models schema "
            f"version {schema_version()}."
        ),
    }
    return _clean(dataset)


def _heritage_slugs(entities: list[KeyValues]) -> list[str]:
    """Slugs of the heritage entries among the entities (listings never carry ``seeAlso``/source URLs).

    Heritage entities are the ones whose ``source`` is not the platform's onboarding marker.
    """
    return [kv["id"][len(ID_PREFIX):] for kv in entities if kv.get("source") != "VRMAC-LH host onboarding (validated listing)"]


# --- files -----------------------------------------------------------------------------------
def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def export_all(db: Session, out_dir: str | Path, base_url: str = "http://localhost:8000") -> dict[str, Any]:
    """Write the NGSI-LD (normalized + key-values), DCAT-AP and validation-report files.

    Returns ``{n_entities, valid, files, errors, schema_version}``. ``valid`` is ``False`` (with the
    schema errors listed) when any entity fails validation — the files are still written so the
    problem can be inspected, but the result never claims success.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pairs = poi_entities(db)
    keyvalues = [kv for kv, _ in pairs]
    normalized = [norm for _, norm in pairs]
    errors = validate_entities(keyvalues)
    valid = not errors
    report = {
        "schema_id": POI_SCHEMA_URI,
        "schema_version": schema_version(),
        "validated_at": _iso_z(datetime.now(timezone.utc)),
        "n_entities": len(keyvalues),
        "valid": valid,
        "errors": errors,
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
        log.info("NGSI-LD export: %d entities validated against PointOfInterest %s", len(keyvalues), report["schema_version"])
    return {
        "n_entities": len(keyvalues),
        "valid": valid,
        "schema_version": report["schema_version"],
        "files": [str(p.resolve()) for p in files.values()],
        "errors": errors,
    }
