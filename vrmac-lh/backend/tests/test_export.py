"""Interoperability stub: NGSI-LD PointOfInterest export validated offline + DCAT-AP.

Claim #6 — definition of done: *the NGSI-LD export validates against the PointOfInterest schema*.
Everything here runs without network access: the Smart Data Models schemas are vendored under
``backend/schemas/sdm`` and resolved through a ``referencing.Registry``.
"""
from __future__ import annotations

import copy
import json

import pytest
from sqlalchemy import select

from app.models import HeritageEntry, Listing, Village
from app.services import export as ex

# Montenegro bounding box (generous)
MNE_LAT = (41.8, 43.6)
MNE_LNG = (18.4, 20.4)
NON_APPROVED_SAMPLES = {"sample-draft-zlatno-zvono", "sample-reviewed-stara-skola", "sample-rejected-rimska-vila"}
# Gornji Stoliv is the unverified village (facts_verified=false): nothing about it may be published.
UNVERIFIED_VILLAGES = {"gornji-stoliv", "pasiglav"}
NGSI_ATTR_TYPES = {"Property", "GeoProperty", "Relationship"}


@pytest.fixture()
def records(db):
    return ex.poi_records(db)


@pytest.fixture()
def pairs(db):
    return ex.poi_entities(db)


@pytest.fixture()
def keyvalues(pairs):
    return [kv for kv, _ in pairs]


@pytest.fixture()
def normalized(pairs):
    return [norm for _, norm in pairs]


def _expected_slugs(db) -> set[str]:
    entries = db.scalars(
        select(HeritageEntry.slug).where(
            HeritageEntry.status == "approved", HeritageEntry.lat.is_not(None), HeritageEntry.lng.is_not(None)
        )
    ).all()
    listings = db.scalars(
        select(Listing.slug).where(Listing.status == "approved", Listing.lat.is_not(None), Listing.lng.is_not(None))
    ).all()
    return set(entries) | set(listings)


def _expected_territory(db) -> dict[str, tuple[str, str, str]]:
    """item slug → (village slug, village name_en, municipality) for everything that is exported."""
    out: dict[str, tuple[str, str, str]] = {}
    for model in (HeritageEntry, Listing):
        rows = db.execute(
            select(model.slug, Village.slug, Village.name_en, Village.municipality)
            .join(Village, model.village_id == Village.id)
            .where(model.status == "approved", model.lat.is_not(None), model.lng.is_not(None))
        ).all()
        for item_slug, v_slug, v_name, municipality in rows:
            out[item_slug] = (v_slug, v_name, municipality)
    return out


# (1) every key-values entity validates against the vendored schema via the registry ---------------
def test_every_keyvalues_entity_validates(keyvalues):
    assert keyvalues, "seed must yield at least one exportable POI"
    errors = ex.validate_entities(keyvalues)
    assert errors == [], json.dumps(errors, indent=1, ensure_ascii=False)
    for kv in keyvalues:
        assert ex.validate_entity(kv) == []
        assert kv["type"] == "PointOfInterest"
        assert kv["id"].startswith("urn:ngsi-ld:PointOfInterest:vrmac-lh:")
        assert kv["name"] and kv["category"]


def test_validator_resolves_refs_offline():
    """The $ref URIs point at smart-data-models.github.io; the registry must serve them from disk."""
    v = ex.poi_validator()
    assert v.schema["$id"] == ex.POI_SCHEMA_URI
    resolver = ex.registry().resolver()
    assert resolver.lookup(ex.COMMON_SCHEMA_URI).contents["$id"] == ex.COMMON_SCHEMA_URI
    # the two allOf refs and a nested definition ref all resolve without touching the network
    assert "location" in resolver.lookup(f"{ex.COMMON_SCHEMA_URI}#/definitions/Location-Commons").contents["properties"]
    assert "name" in resolver.lookup(f"{ex.COMMON_SCHEMA_URI}#/definitions/GSMA-Commons").contents["properties"]
    assert ex.schema_version() == v.schema["$schemaVersion"]


def test_export_only_uses_attributes_the_schema_defines(keyvalues):
    """`additionalProperties` is unrestricted in the SDM schema, so an invented attribute would
    validate. The export refuses to rely on that: it emits schema-defined attributes only."""
    known = ex.known_attributes()
    assert {"address", "location", "description", "alternateName", "refSeeAlso"} <= known
    for kv in keyvalues:
        assert ex.unknown_attributes(kv) == [], kv["id"]
    invented = copy.deepcopy(keyvalues[0])
    invented["villageSlug"] = "gornja-lastva"  # would pass plain JSON-Schema validation
    assert ex.unknown_attributes(invented) == ["villageSlug"]
    assert any(e["validator"] == "knownAttributes" for e in ex.validate_entity(invented))


# (2) exactly the approved entries-with-coordinates + approved listings; samples absent -------------
def test_exported_ids_cover_exactly_the_approved_items(db, keyvalues):
    exported = {ex.entity_slug(kv) for kv in keyvalues}
    assert exported == _expected_slugs(db)
    assert len(keyvalues) == len(exported), "ids must be unique"
    assert not exported & NON_APPROVED_SAMPLES
    assert {"gornja-lastva", "crkva-sv-vida", "lastovska-festa", "konoba-maslina-sample"} <= exported


def test_unverified_and_non_approved_content_is_absent(keyvalues, db):
    """Gornji Stoliv is not verified: its entry stays a draft and nothing about it is exported."""
    assert db.scalar(select(HeritageEntry.status).where(HeritageEntry.slug == "gornji-stoliv")) == "draft"
    payload = json.dumps(keyvalues, ensure_ascii=False)
    for slug in UNVERIFIED_VILLAGES | NON_APPROVED_SAMPLES:
        assert slug not in payload, slug
    assert not {ex.village_slug_of(kv) for kv in keyvalues} & UNVERIFIED_VILLAGES


def test_all_seed_statuses_present_so_the_gate_is_actually_exercised(db):
    statuses = set(db.scalars(select(HeritageEntry.status)).all())
    assert {"approved", "draft", "reviewed", "rejected"} <= statuses


def test_categories_follow_the_mapping(keyvalues):
    by_slug = {ex.entity_slug(kv): kv for kv in keyvalues}
    assert by_slug["gornja-lastva"]["category"] == ["village"]
    assert by_slug["tivat"]["category"] == ["town"]
    assert by_slug["crkva-sv-marije"]["category"] == ["church"]
    assert by_slug["lastovska-festa"]["category"] == ["event"]
    assert by_slug["mlinovi-za-masline"]["category"] == ["tradition"]
    assert by_slug["dom-kulture-ilija-markovic"]["category"] == ["culture_house"]
    assert by_slug["konoba-maslina-sample"]["category"] == ["food"]
    assert by_slug["apartman-lastva-sample"]["category"] == ["accommodation"]
    assert by_slug["vodic-vrmac-sample"]["category"] == ["guiding"]
    assert by_slug["radionica-maslinovog-ulja-sample"]["category"] == ["craft"]


def test_no_personal_data_and_prototype_marking(keyvalues):
    text = json.dumps(keyvalues, ensure_ascii=False).lower()
    assert "@example.org" not in text and "host1" not in text and "password" not in text
    for kv in keyvalues:
        assert "owner" not in kv
        cp = kv.get("contactPoint", {})
        assert "email" not in cp and "telephone" not in cp and "name" not in cp
        assert kv["dataProvider"] == ex.DATA_PROVIDER
        assert ex.COORDS_APPROXIMATE_NOTE in kv["description"]  # seed coordinates are approximate
        assert kv["dateCreated"].endswith("Z") and kv["dateModified"].endswith("Z")


# (3) territory: every entity carries its village and municipality ---------------------------------
def test_every_entity_carries_its_village_and_municipality(db, keyvalues, records):
    expected = _expected_territory(db)
    assert expected, "seed must link every exported item to a village"
    for kv in keyvalues:
        slug = ex.entity_slug(kv)
        village_slug, village_name, municipality = expected[slug]
        address = kv["address"]
        assert set(address) == {"addressLocality", "addressRegion", "addressCountry"}
        assert address["addressLocality"] == village_name, slug
        assert address["addressRegion"] == f"{municipality} municipality, Bay of Kotor", slug
        assert address["addressCountry"] == "ME"
        assert ex.municipality_of(kv) == municipality
        # the village slug travels in a schema-valid way (inside `description`), not as an invented attribute
        assert ex.village_slug_of(kv) == village_slug, slug
        assert f"[village: {village_slug} — {village_name}, {municipality} municipality]" in kv["description"]

    localities = {kv["address"]["addressLocality"] for kv in keyvalues}
    assert len(localities) > 1, f"the export must span more than one village, got {localities}"
    assert {"Gornja Lastva", "Donja Lastva"} <= localities
    assert {r.village_slug for r in records} == {v[0] for v in expected.values()}
    assert {r.municipality for r in records} <= {"Tivat", "Kotor"}


def test_village_anchor_is_an_ngsi_ld_relationship(keyvalues, normalized):
    """Items link to the PointOfInterest of their own village with a real NGSI-LD Relationship."""
    by_slug = {ex.entity_slug(kv): kv for kv in keyvalues}
    assert by_slug["crkva-sv-marije"]["refSeeAlso"] == [ex.ID_PREFIX + "gornja-lastva"]
    assert by_slug["apartman-lastva-sample"]["refSeeAlso"] == [ex.ID_PREFIX + "donja-lastva"]
    assert "refSeeAlso" not in by_slug["gornja-lastva"], "a village must not point at itself"
    rel = next(n for n in normalized if n["id"].endswith("crkva-sv-marije"))["refSeeAlso"]
    assert rel == {"type": "Relationship", "object": [ex.ID_PREFIX + "gornja-lastva"]}


# (4) listings use the host-confirmed structured fields --------------------------------------------
def test_listing_season_and_accessibility_come_from_the_structured_fields(db, keyvalues):
    by_slug = {ex.entity_slug(kv): kv for kv in keyvalues}

    konoba = db.scalar(select(Listing).where(Listing.slug == "konoba-maslina-sample"))
    assert (konoba.season_from, konoba.season_to, konoba.season_all_year) == (5, 10, False)
    assert ex.season_text(konoba) == ("Season: May–October.", "Sezona: maj–oktobar.")
    assert "Season: May–October." in by_slug["konoba-maslina-sample"]["description"]
    assert "Sezona: maj–oktobar." in by_slug["konoba-maslina-sample"]["description"]

    apartman = db.scalar(select(Listing).where(Listing.slug == "apartman-lastva-sample"))
    assert apartman.season_all_year is True
    assert "Season: open all year." in by_slug["apartman-lastva-sample"]["description"]

    # accessibility_step_free + the host's note, in both languages
    assert konoba.accessibility_step_free is True
    text = by_slug["konoba-maslina-sample"]["description"]
    assert "Accessibility: step-free access." in text
    assert konoba.accessibility_note_en in text and konoba.accessibility_note_local in text
    vodic = db.scalar(select(Listing).where(Listing.slug == "vodic-vrmac-sample"))
    assert vodic.accessibility_step_free is False
    assert "Accessibility: not step-free." in by_slug["vodic-vrmac-sample"]["description"]
    assert vodic.accessibility_note_en in by_slug["vodic-vrmac-sample"]["description"]

    # price note + capacity + the "host-confirmed" marker (never model-inferred)
    assert by_slug["konoba-maslina-sample"]["priceRange"] == "12–30 EUR per person"
    assert by_slug["konoba-maslina-sample"]["capacity"] == konoba.capacity
    assert "Host-confirmed: price, season, capacity, accessibility, coordinates." in text
    assert "Domaćin potvrdio: cijena, sezona, kapacitet, pristupačnost, koordinate." in text
    assert "sample" in text.lower() and "uzorak" in text.lower()
    assert by_slug["konoba-maslina-sample"]["source"] == ex.LISTING_SOURCE


def test_heritage_entities_keep_their_citations(keyvalues):
    by_slug = {ex.entity_slug(kv): kv for kv in keyvalues}
    entry = by_slug["crkva-sv-marije"]
    assert entry["seeAlso"] == ["https://hr.wikipedia.org/wiki/Gornja_Lastva", "https://gornjalastva.org"]
    assert entry["source"].startswith("http")
    assert "14th century" in entry["description"]


# (5) location is a GeoJSON Point [lng, lat] inside Montenegro ------------------------------------
def test_locations_are_points_within_montenegro(keyvalues):
    for kv in keyvalues:
        loc = kv["location"]
        assert loc["type"] == "Point"
        lng, lat = loc["coordinates"]
        assert MNE_LNG[0] <= lng <= MNE_LNG[1], kv["id"]
        assert MNE_LAT[0] <= lat <= MNE_LAT[1], kv["id"]


# (6) normalized NGSI-LD form ----------------------------------------------------------------------
def test_normalized_form_has_typed_attributes_and_context(normalized, keyvalues):
    assert len(normalized) == len(keyvalues)
    seen_types: set[str] = set()
    for kv, norm in zip(keyvalues, normalized):
        assert norm["id"] == kv["id"] and norm["type"] == "PointOfInterest"
        assert norm["@context"] == [ex.POI_CONTEXT_URI, ex.NGSI_LD_CORE_CONTEXT_URI]
        assert norm["location"]["type"] == "GeoProperty"
        assert norm["location"]["value"] == kv["location"]
        for key, attr in norm.items():
            if key in ("id", "type", "@context"):
                continue
            assert isinstance(attr, dict) and attr["type"] in NGSI_ATTR_TYPES, key
            seen_types.add(attr["type"])
            value_key = "object" if attr["type"] == "Relationship" else "value"
            assert value_key in attr, key
        assert norm["dateCreated"] == {"type": "Property", "value": {"@type": "DateTime", "@value": kv["dateCreated"]}}
        assert set(norm) - {"@context"} == set(kv), "normalized and key-values forms carry the same attributes"
        assert norm["name"] == {"type": "Property", "value": kv["name"]}
        assert norm["address"] == {"type": "Property", "value": kv["address"]}
    assert seen_types == NGSI_ATTR_TYPES, "all three NGSI-LD attribute kinds must appear"


# (7) export_all writes the four files + a passing validation report ------------------------------
def test_export_all_writes_files_and_valid_report(db, tmp_path):
    result = ex.export_all(db, tmp_path)
    assert result["valid"] is True and result["errors"] == []
    assert result["n_entities"] == len(_expected_slugs(db))
    names = {p.rsplit("/", 1)[-1] for p in result["files"]}
    assert names == {"pois.ngsi-ld.json", "pois.keyvalues.json", "dataset.dcat-ap.jsonld", "validation-report.json"}
    for p in result["files"]:
        assert (tmp_path / p.rsplit("/", 1)[-1]).is_file()
    assert len(result["villages"]) > 1 and result["municipalities"] == ["Tivat"]

    report = json.loads((tmp_path / "validation-report.json").read_text(encoding="utf-8"))
    assert report["valid"] is True and report["errors"] == []
    assert report["n_entities"] == result["n_entities"]
    assert report["schema_version"] == ex.schema_version() and report["schema_id"] == ex.POI_SCHEMA_URI
    assert set(report) >= {"schema_version", "n_entities", "valid", "errors"}
    assert report["villages"] == result["villages"]

    kvs = json.loads((tmp_path / "pois.keyvalues.json").read_text(encoding="utf-8"))
    norms = json.loads((tmp_path / "pois.ngsi-ld.json").read_text(encoding="utf-8"))
    assert len(kvs) == len(norms) == result["n_entities"]
    assert ex.validate_entities(kvs) == []  # re-validate what was actually written to disk
    assert all("@context" in n for n in norms)
    assert all(kv["address"]["addressCountry"] == "ME" for kv in kvs)

    doc = json.loads((tmp_path / "dataset.dcat-ap.jsonld").read_text(encoding="utf-8"))
    assert doc["@type"] == "dcat:Dataset" and len(doc["dcat:distribution"]) >= 2


def test_cli_export_command(db, tmp_path, capsys):
    from app.cli import main

    main(["export-ngsi-ld", "--out", str(tmp_path / "cli")])
    out = json.loads(capsys.readouterr().out)
    assert out["valid"] is True and out["n_entities"] > 0
    assert (tmp_path / "cli" / "validation-report.json").is_file()


# (8) DCAT-AP -------------------------------------------------------------------------------------
def test_dcat_ap_document(db):
    base = "https://vrmac.example"
    doc = ex.dcat_ap(db, base)
    assert doc["@context"]["dcat"] == "http://www.w3.org/ns/dcat#"
    assert {"dct", "foaf", "vcard", "xsd"} <= set(doc["@context"])
    assert doc["@type"] == "dcat:Dataset"
    assert doc["@id"] == f"{base}/api/export/dcat-ap#dataset"
    langs = {t["@language"] for t in doc["dct:title"]}
    assert langs == {"en", "cnr"}
    assert {d["@language"] for d in doc["dct:description"]} == {"en", "cnr"}
    assert doc["dct:publisher"]["@type"] == "foaf:Agent" and doc["dct:publisher"]["foaf:name"]
    assert doc["dct:license"]["@id"] == "https://creativecommons.org/licenses/by/4.0/"
    assert {"@id": f"{ex.EU_THEME}EDUC"} in doc["dcat:theme"]
    keywords = doc["dcat:keyword"]
    assert "Vrmac" in keywords and "Tivat municipality" in keywords and "Gornja Lastva" in keywords

    dists = doc["dcat:distribution"]
    assert len(dists) >= 2
    urls = {d["dcat:accessURL"]["@id"] for d in dists}
    assert {f"{base}/api/export/ngsi-ld", f"{base}/api/export/ngsi-ld/keyvalues"} <= urls
    assert all(d["dct:conformsTo"]["@id"] == ex.POI_SCHEMA_URI for d in dists)
    media = {d["dcat:mediaType"]["@id"].rsplit("/", 2)[-1] for d in dists}
    assert "ld+json" in media

    spatial = doc["dct:spatial"]
    assert spatial["@type"] == "dct:Location"
    wkt = spatial["dcat:bbox"]["@value"]
    assert wkt.startswith("POLYGON((")
    geom = json.loads(spatial["locn:geometry"]["@value"])
    assert geom["type"] == "Polygon"
    ring = geom["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 5
    for lng, lat in ring:
        assert MNE_LNG[0] <= lng <= MNE_LNG[1] and MNE_LAT[0] <= lat <= MNE_LAT[1]
    # the bbox really is the extent of the exported points
    points = [kv["location"]["coordinates"] for kv, _ in ex.poi_entities(db)]
    assert min(p[0] for p in points) == min(p[0] for p in ring)
    assert max(p[1] for p in points) == max(p[1] for p in ring)

    temporal = doc["dct:temporal"]
    assert temporal["@type"] == "dct:PeriodOfTime"
    assert temporal["dcat:startDate"]["@type"] == "xsd:dateTime"
    assert temporal["dcat:startDate"]["@value"] <= temporal["dcat:endDate"]["@value"]

    assert doc["dct:accrualPeriodicity"]["@id"].startswith(ex.EU_FREQUENCY)
    assert doc["dct:issued"]["@type"] == "xsd:dateTime" and doc["dct:modified"]["@value"].endswith("Z")
    provenance = doc["dct:provenance"]["rdfs:label"].lower()
    assert "prototype" in provenance and "sample" in provenance


# (9) API endpoints --------------------------------------------------------------------------------
def test_api_ngsi_ld_endpoints(client, db):
    expected = _expected_slugs(db)

    r = client.get("/api/export/ngsi-ld")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/ld+json")
    assert r.headers["X-Schema-Valid"] == "true"
    body = r.json()
    assert isinstance(body, list) and {ex.entity_slug(e) for e in body} == expected
    assert all(e["location"]["type"] == "GeoProperty" and e["@context"] == ex.NGSI_LD_CONTEXT for e in body)
    assert all(e["address"]["value"]["addressCountry"] == "ME" for e in body)

    r = client.get("/api/export/ngsi-ld/keyvalues")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["X-Schema-Valid"] == "true"
    assert r.headers["X-Schema-Id"] == ex.POI_SCHEMA_URI
    assert r.headers["X-Schema-Version"] == ex.schema_version()
    kvs = r.json()
    assert {ex.entity_slug(e) for e in kvs} == expected
    assert ex.validate_entities(kvs) == []
    assert len({e["address"]["addressLocality"] for e in kvs}) > 1
    # absolute links into this deployment are derived from the request's base URL
    assert all(e["additionalInfoURL"].startswith("http://testserver/api/") for e in kvs)
    listing = next(e for e in kvs if e["id"].endswith("konoba-maslina-sample"))
    assert listing["image"].startswith("http://testserver/api/static/")
    assert listing["contactPoint"]["url"] == "http://testserver/api/requests"


def test_api_dcat_ap_endpoint(client):
    r = client.get("/api/export/dcat-ap")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/ld+json")
    assert r.headers["X-Schema-Valid"] == "true"
    doc = r.json()
    assert doc["@type"] == "dcat:Dataset" and "@context" in doc
    assert doc["@id"] == "http://testserver/api/export/dcat-ap#dataset"
    assert len(doc["dcat:distribution"]) >= 2 and "dcat:bbox" in doc["dct:spatial"]


# (10) negative: the validator is real --------------------------------------------------------------
def test_broken_entities_fail_validation(keyvalues):
    good = keyvalues[0]
    assert ex.validate_entity(good) == []

    wrong_type = copy.deepcopy(good)
    wrong_type["type"] = "Poi"
    errs = ex.validate_entity(wrong_type)
    assert errs and any(e["path"] == "type" and e["validator"] == "enum" for e in errs)

    string_location = copy.deepcopy(good)
    string_location["location"] = "42.44, 18.69"
    errs = ex.validate_entity(string_location)
    assert errs and any(e["path"] == "location" for e in errs)

    missing_name = copy.deepcopy(good)
    del missing_name["name"]
    errs = ex.validate_entity(missing_name)
    assert errs and any(e["validator"] == "required" and "name" in e["message"] for e in errs)

    bad_category = copy.deepcopy(good)
    bad_category["category"] = "church"  # must be an array of strings
    assert any(e["path"] == "category" for e in ex.validate_entity(bad_category))

    bad_address = copy.deepcopy(good)
    bad_address["address"] = {"addressLocality": ["Gornja Lastva"]}  # must be a string
    assert any(e["path"].startswith("address") for e in ex.validate_entity(bad_address))

    bad_date = copy.deepcopy(good)
    bad_date["dateModified"] = "yesterday"
    assert any(e["path"] == "dateModified" and e["validator"] == "format" for e in ex.validate_entity(bad_date))

    bad_see_also = copy.deepcopy(good)
    bad_see_also["seeAlso"] = ["not a uri"]
    assert any(e["path"].startswith("seeAlso") for e in ex.validate_entity(bad_see_also))

    # the whole-list helper reports each broken entity with its id
    errs = ex.validate_entities([good, wrong_type])
    assert {e["id"] for e in errs} == {wrong_type["id"]}


def test_export_all_reports_invalid_instead_of_silently_passing(db, tmp_path, monkeypatch):
    def broken_pairs(_db, base_url=None):
        kv = {"id": "urn:ngsi-ld:PointOfInterest:vrmac-lh:broken", "type": "Poi", "name": "x", "location": "nope"}
        return [(kv, ex.to_normalized(kv))]

    monkeypatch.setattr(ex, "poi_entities", broken_pairs)
    result = ex.export_all(db, tmp_path)
    assert result["valid"] is False and result["errors"]
    report = json.loads((tmp_path / "validation-report.json").read_text(encoding="utf-8"))
    assert report["valid"] is False and report["n_entities"] == 1 and report["errors"]


def test_export_refuses_rows_that_are_not_approved(db, monkeypatch):
    """Belt-and-braces: if the approved filter were ever removed, the mapper still refuses."""
    original = ex.approved_only
    monkeypatch.setattr(ex, "approved_only", lambda stmt, model: stmt)
    with pytest.raises(RuntimeError, match="export refused"):
        ex.poi_records(db)
    monkeypatch.setattr(ex, "approved_only", original)
    assert ex.poi_records(db)
