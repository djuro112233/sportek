"""Interoperability stub: NGSI-LD PointOfInterest export validated offline + DCAT-AP."""
from __future__ import annotations

import copy
import json

import pytest
from sqlalchemy import select

from app.models import HeritageEntry, Listing
from app.services import export as ex

# Montenegro bounding box (generous)
MNE_LAT = (41.8, 43.6)
MNE_LNG = (18.4, 20.4)
NON_APPROVED_SAMPLES = {"sample-draft-zlatno-zvono", "sample-reviewed-stara-skola", "sample-rejected-rimska-vila"}
NGSI_ATTR_TYPES = {"Property", "GeoProperty", "Relationship"}


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
    resolver = v._resolver  # noqa: SLF001 — inspect the registry the validator was built with
    assert resolver.lookup(ex.COMMON_SCHEMA_URI).contents["$id"] == ex.COMMON_SCHEMA_URI
    assert ex.schema_version() == v.schema["$schemaVersion"]


# (2) exactly the approved entries-with-coordinates + approved listings; samples absent -------------
def test_exported_ids_cover_exactly_the_approved_items(db, keyvalues):
    exported = {kv["id"][len(ex.ID_PREFIX):] for kv in keyvalues}
    assert exported == _expected_slugs(db)
    assert len(keyvalues) == len(exported), "ids must be unique"
    assert not exported & NON_APPROVED_SAMPLES
    assert {"gornja-lastva", "crkva-sv-vida", "lastovska-festa", "konoba-maslina-sample"} <= exported


def test_all_seed_statuses_present_so_the_gate_is_actually_exercised(db):
    statuses = set(db.scalars(select(HeritageEntry.status)).all())
    assert {"approved", "draft", "reviewed", "rejected"} <= statuses


def test_categories_follow_the_mapping(keyvalues):
    by_slug = {kv["id"][len(ex.ID_PREFIX):]: kv for kv in keyvalues}
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
        assert kv["address"] == {"addressLocality": "Tivat", "addressRegion": "Boka Kotorska", "addressCountry": "ME"}
        assert ex.COORDS_APPROXIMATE_NOTE in kv["description"]  # seed coordinates are approximate
        assert kv["dateCreated"].endswith("Z") and kv["dateModified"].endswith("Z")


# (3) location is a GeoJSON Point [lng, lat] inside Montenegro ------------------------------------
def test_locations_are_points_within_montenegro(keyvalues):
    for kv in keyvalues:
        loc = kv["location"]
        assert loc["type"] == "Point"
        lng, lat = loc["coordinates"]
        assert MNE_LNG[0] <= lng <= MNE_LNG[1], kv["id"]
        assert MNE_LAT[0] <= lat <= MNE_LAT[1], kv["id"]


# (4) normalized NGSI-LD form ----------------------------------------------------------------------
def test_normalized_form_has_typed_attributes_and_context(normalized, keyvalues):
    assert len(normalized) == len(keyvalues)
    for kv, norm in zip(keyvalues, normalized):
        assert norm["id"] == kv["id"] and norm["type"] == "PointOfInterest"
        assert norm["@context"] == [ex.POI_CONTEXT_URI, ex.NGSI_LD_CORE_CONTEXT_URI]
        assert norm["location"]["type"] == "GeoProperty"
        assert norm["location"]["value"] == kv["location"]
        for key, attr in norm.items():
            if key in ("id", "type", "@context"):
                continue
            assert isinstance(attr, dict) and attr["type"] in NGSI_ATTR_TYPES, key
        assert norm["dateCreated"] == {"type": "Property", "value": {"@type": "DateTime", "@value": kv["dateCreated"]}}
        assert set(norm) - {"@context"} == set(kv), "normalized and key-values forms carry the same attributes"
        assert norm["name"] == {"type": "Property", "value": kv["name"]}


# (5) export_all writes the four files + a passing validation report ------------------------------
def test_export_all_writes_files_and_valid_report(db, tmp_path):
    result = ex.export_all(db, tmp_path)
    assert result["valid"] is True and result["errors"] == []
    assert result["n_entities"] == len(_expected_slugs(db))
    names = {p.rsplit("/", 1)[-1] for p in result["files"]}
    assert names == {"pois.ngsi-ld.json", "pois.keyvalues.json", "dataset.dcat-ap.jsonld", "validation-report.json"}
    for p in result["files"]:
        assert (tmp_path / p.rsplit("/", 1)[-1]).is_file()

    report = json.loads((tmp_path / "validation-report.json").read_text(encoding="utf-8"))
    assert report["valid"] is True and report["errors"] == []
    assert report["n_entities"] == result["n_entities"]
    assert report["schema_version"] == ex.schema_version() and report["schema_id"] == ex.POI_SCHEMA_URI

    kvs = json.loads((tmp_path / "pois.keyvalues.json").read_text(encoding="utf-8"))
    norms = json.loads((tmp_path / "pois.ngsi-ld.json").read_text(encoding="utf-8"))
    assert len(kvs) == len(norms) == result["n_entities"]
    assert ex.validate_entities(kvs) == []  # re-validate what was actually written to disk
    assert all("@context" in n for n in norms)


def test_cli_export_command(db, tmp_path, capsys):
    from app.cli import main

    main(["export-ngsi-ld", "--out", str(tmp_path / "cli")])
    out = json.loads(capsys.readouterr().out)
    assert out["valid"] is True and out["n_entities"] > 0
    assert (tmp_path / "cli" / "validation-report.json").is_file()


# (6) DCAT-AP -------------------------------------------------------------------------------------
def test_dcat_ap_document(db):
    base = "https://vrmac.example"
    doc = ex.dcat_ap(db, base)
    assert doc["@context"]["dcat"] == "http://www.w3.org/ns/dcat#"
    assert {"dct", "foaf", "vcard", "xsd"} <= set(doc["@context"])
    assert doc["@type"] == "dcat:Dataset"
    assert doc["@id"] == f"{base}/api/export/dcat-ap#dataset"
    langs = {t["@language"] for t in doc["dct:title"]}
    assert langs == {"en", "cnr"}
    assert doc["dct:publisher"]["@type"] == "foaf:Agent"
    assert doc["dct:license"]["@id"] == "https://creativecommons.org/licenses/by/4.0/"
    assert {"@id": f"{ex.EU_THEME}EDUC"} in doc["dcat:theme"]
    assert doc["dcat:keyword"]

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
    assert doc["dct:accrualPeriodicity"]["@id"].startswith(ex.EU_FREQUENCY)
    assert doc["dct:issued"]["@type"] == "xsd:dateTime" and doc["dct:modified"]["@value"].endswith("Z")
    assert "prototype" in doc["dct:provenance"]["rdfs:label"].lower()
    assert "sample" in doc["dct:provenance"]["rdfs:label"].lower()


# (7) API endpoints --------------------------------------------------------------------------------
def test_api_ngsi_ld_endpoints(client, db):
    expected = _expected_slugs(db)

    r = client.get("/api/export/ngsi-ld")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/ld+json")
    assert r.headers["X-Schema-Valid"] == "true"
    body = r.json()
    assert isinstance(body, list) and {e["id"][len(ex.ID_PREFIX):] for e in body} == expected
    assert all(e["location"]["type"] == "GeoProperty" and e["@context"] == ex.NGSI_LD_CONTEXT for e in body)

    r = client.get("/api/export/ngsi-ld/keyvalues")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["X-Schema-Valid"] == "true"
    assert r.headers["X-Schema-Id"] == ex.POI_SCHEMA_URI
    kvs = r.json()
    assert {e["id"][len(ex.ID_PREFIX):] for e in kvs} == expected
    assert ex.validate_entities(kvs) == []
    # absolute links into this deployment are derived from the request's base URL
    assert all(e["additionalInfoURL"].startswith("http://testserver/api/") for e in kvs)
    listing = next(e for e in kvs if e["id"].endswith("konoba-maslina-sample"))
    assert listing["image"].startswith("http://testserver/api/static/")
    assert listing["contactPoint"]["url"] == "http://testserver/api/requests"


def test_api_dcat_ap_endpoint(client):
    r = client.get("/api/export/dcat-ap")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/ld+json")
    doc = r.json()
    assert doc["@type"] == "dcat:Dataset" and "@context" in doc
    assert doc["@id"] == "http://testserver/api/export/dcat-ap#dataset"
    assert len(doc["dcat:distribution"]) >= 2 and "dcat:bbox" in doc["dct:spatial"]


# (8) negative: the validator is real --------------------------------------------------------------
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
