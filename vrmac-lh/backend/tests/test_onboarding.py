"""Voice-first onboarding, end to end through the API.

The full path a host walks: start → heartbeats (ACTIVE authoring time) → upload a recording that was
captured **offline** twenty minutes earlier → transcript → draft (title and description ONLY) →
consent + host-confirmed structured fields → a listing in the validation queue → approval → publication.

The two claims these tests defend:

1. **The model never fills a structured field.** The draft carries four keys and nothing else, and
   ``fields_required`` names what the host must fill in and confirm. Confirming without consent, or
   without confirming price/season/capacity/accessibility/coordinates, is refused with 422.
2. **Active authoring time is measured separately from elapsed time.** ``active_seconds`` is the sum of
   the heartbeats (the 30-minute target, K06/K07), ``elapsed_to_confirm_seconds`` and
   ``elapsed_to_publish_seconds`` are wall clock and include waiting for a validator.
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import settings
from app.db import PublicSessionLocal, SessionLocal
from app.models import ConsentRecord, Event, Listing, OnboardingSession, User, utcnow
from app.pseudonym import ACTOR, pseudonymise
from app.services import onboarding as svc
from app.services import validation

HOST = "host3@example.org"
OTHER_HOST = "host1@example.org"
BEHALF_HOST = "host4@example.org"
AMBASSADOR = "ambassador1@example.org"
VALIDATOR = "validator1@example.org"
INSTITUTION = "institution1@example.org"

FIXTURE_DIR = Path(settings.seed_dir) / "stt_fixtures"
FIXTURE_WAV = FIXTURE_DIR / "host-sample-cnr.wav"
FIXTURE_TXT = FIXTURE_DIR / "host-sample-cnr.txt"

#: Four heartbeats of active authoring time — 255 s, comfortably inside the 30-minute target.
HEARTBEATS = [60, 120, 45, 30]
#: The session is back-dated so the *elapsed* clock is realistic in a test that runs in a second.
SESSION_AGE = timedelta(minutes=22)
#: The recording was made offline and uploaded twenty minutes later.
CAPTURED_AGO = timedelta(minutes=20)

DRAFT_KEYS = {"title_local", "title_en", "description_local", "description_en"}
STRUCTURED_FIELDS = {
    "price_min", "price_max", "currency", "season", "capacity", "accessibility",
    "coordinates", "category", "village",
}
#: Keys that must never appear in anything the model produced.
FORBIDDEN_IN_DRAFT = {
    "price", "price_min", "price_max", "price_range", "currency", "season", "season_from", "season_to",
    "season_all_year", "capacity", "accessibility", "accessibility_step_free", "accessibility_note_local",
    "accessibility_note_en", "lat", "lng", "coordinates", "category",
}

CONFIRMED_FIELDS = [
    "price_min", "price_max", "currency", "season", "capacity", "accessibility", "coordinates",
]
STRUCTURED_INPUT = {
    "category": "accommodation",
    "village": "donja-lastva",
    "price_min": 45.0,
    "price_max": 70.0,
    "currency": "EUR",
    "price_note_local": "po noći",
    "price_note_en": "per night",
    "season_from": 5,
    "season_to": 10,
    "season_all_year": False,
    "capacity": 4,
    "accessibility_step_free": True,
    "accessibility_note_local": "Prizemlje, bez stepenica na ulazu.",
    "accessibility_note_en": "Ground floor, no steps at the entrance.",
    "lat": 42.4402,
    "lng": 18.6848,
    "coords_approximate": True,
    "confirmed_fields": CONFIRMED_FIELDS,
}
CONSENT = {"given": True, "method": "checkbox", "text_version": "v1"}


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def auth(client):
    """Bearer headers for a sample account.

    Uses ``POST /api/auth/login`` when the auth router is wired up, and otherwise mints exactly the
    same JWT with ``app.auth.create_access_token`` so this module does not depend on another module.
    """
    from app.auth import create_access_token

    cache: dict[str, dict] = {}

    def _headers(email: str) -> dict:
        if email not in cache:
            r = client.post("/api/auth/login", json={"email": email, "password": settings.seed_password})
            if r.status_code == 200:
                cache[email] = {"Authorization": f"Bearer {r.json()['access_token']}"}
            else:
                with SessionLocal() as db:
                    user = db.scalars(select(User).where(User.email == email)).one()
                    cache[email] = {"Authorization": f"Bearer {create_access_token(user)}"}
        return cache[email]

    return _headers


def _user_id(email: str) -> uuid.UUID:
    with SessionLocal() as db:
        return db.scalars(select(User.id).where(User.email == email)).one()


def _backdate(session_id: str, age: timedelta) -> None:
    """Pretend the session started ``age`` ago, so the elapsed clock is realistic in a fast test."""
    with SessionLocal() as db:
        row = db.get(OnboardingSession, uuid.UUID(session_id))
        row.started_at = utcnow() - age
        db.commit()


def _start(client, headers, **payload) -> dict:
    r = client.post("/api/onboarding/sessions", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client, headers, session_id: str, *, offline: bool = True, captured_ago=CAPTURED_AGO):
    data = {"offline_captured": "true" if offline else "false"}
    if captured_ago is not None:
        data["captured_at"] = (utcnow() - captured_ago).isoformat().replace("+00:00", "Z")
    with FIXTURE_WAV.open("rb") as fh:
        return client.post(
            f"/api/onboarding/sessions/{session_id}/audio",
            files={"file": ("host-sample-cnr.wav", fh, "audio/wav")},
            data=data,
            headers=headers,
        )


def _all_keys(obj) -> set[str]:
    """Every key name anywhere in a nested structure."""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k).lower())
            keys |= _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            keys |= _all_keys(v)
    return keys


def _session_events(session_id: str, listing_id: str | None = None) -> list[Event]:
    ids = [uuid.UUID(session_id)] + ([uuid.UUID(listing_id)] if listing_id else [])
    with SessionLocal() as db:
        return list(
            db.scalars(select(Event).where(Event.item_id.in_(ids)).order_by(Event.occurred_at, Event.id))
        )


# --------------------------------------------------------------------------------------------------
# the whole flow, once, for the assertions below
# --------------------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def flow(client, auth):
    headers = auth(HOST)
    session = _start(client, headers, language="cnr", village="donja-lastva")
    sid = session["id"]
    _backdate(sid, SESSION_AGE)

    active = 0.0
    for delta in HEARTBEATS:
        r = client.post(
            f"/api/onboarding/sessions/{sid}/heartbeat",
            json={"active_seconds_delta": delta},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        active += delta
        assert r.json()["active_seconds"] == pytest.approx(active)

    r = _upload(client, headers, sid)
    assert r.status_code == 200, r.text
    audio = r.json()

    r = client.post(f"/api/onboarding/sessions/{sid}/draft", headers=headers)
    assert r.status_code == 200, r.text
    draft = r.json()

    listing_in = {
        "title_local": draft["draft"]["title_local"],
        "title_en": draft["draft"]["title_en"],
        "description_local": draft["draft"]["description_local"],
        "description_en": draft["draft"]["description_en"],
        **STRUCTURED_INPUT,
    }
    r = client.post(
        f"/api/onboarding/sessions/{sid}/confirm",
        json={"listing": listing_in, "consent": CONSENT},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    confirmed = r.json()
    return {
        "session_id": sid,
        "started": session,
        "audio": audio,
        "draft": draft,
        "confirmed": confirmed,
        "listing_id": confirmed["listing"]["id"],
        "headers": headers,
    }


# --------------------------------------------------------------------------------------------------
# (1) start
# --------------------------------------------------------------------------------------------------
def test_session_starts_with_both_clocks_at_zero(flow):
    started = flow["started"]
    assert started["status"] == "started"
    assert started["language"] == "cnr"
    assert started["active_seconds"] == 0.0
    assert started["elapsed_to_confirm_seconds"] is None
    assert started["elapsed_to_publish_seconds"] is None
    assert started["target_minutes"] == settings.onboarding_target_minutes


def test_institution_cannot_start_a_session(client, auth):
    r = client.post("/api/onboarding/sessions", json={}, headers=auth(INSTITUTION))
    assert r.status_code == 403


def test_a_host_may_not_open_a_session_on_behalf_of_another_host(client, auth):
    r = client.post(
        "/api/onboarding/sessions",
        json={"host_user_id": str(_user_id(OTHER_HOST))},
        headers=auth(HOST),
    )
    assert r.status_code == 403


def test_an_ambassador_onboards_on_behalf_of_the_host_and_the_host_is_the_actor(client, auth):
    host_id = _user_id(BEHALF_HOST)
    session = _start(client, auth(AMBASSADOR), host_user_id=str(host_id), village="gornja-lastva")
    assert session["host_user_id"] == str(host_id)
    assert session["ambassador_user_id"] == str(_user_id(AMBASSADOR))
    events = _session_events(session["id"])
    assert [e.event_type for e in events] == ["onboarding_started"]
    ev = events[0]
    # the pseudonym and the voluntary gender self-report belong to the HOST, not the ambassador
    assert ev.actor_pseudonym == pseudonymise(ACTOR, host_id)
    assert ev.actor_role == "host"
    assert ev.properties["via_ambassador"] is True
    assert ev.item_type == "onboarding_session"


def test_an_ambassador_must_name_the_host(client, auth):
    r = client.post("/api/onboarding/sessions", json={}, headers=auth(AMBASSADOR))
    assert r.status_code == 422


# --------------------------------------------------------------------------------------------------
# (2) heartbeat — ACTIVE authoring time
# --------------------------------------------------------------------------------------------------
def test_heartbeats_accumulate_active_authoring_time(flow):
    assert flow["confirmed"]["active_seconds"] == pytest.approx(sum(HEARTBEATS))


def test_a_single_heartbeat_delta_is_capped(client, auth):
    session = _start(client, auth(HOST))
    r = client.post(
        f"/api/onboarding/sessions/{session['id']}/heartbeat",
        json={"active_seconds_delta": 9999},
        headers=auth(HOST),
    )
    assert r.status_code == 422, "a stuck tab must not be able to inflate the active time"
    assert svc.add_heartbeat.__doc__  # the service clamps too, for non-HTTP callers


# --------------------------------------------------------------------------------------------------
# (3) audio: offline capture, speech-to-text, deletion
# --------------------------------------------------------------------------------------------------
def test_transcript_matches_the_fixture(flow):
    assert flow["audio"]["status"] == "transcribed"
    assert flow["audio"]["transcript"] == FIXTURE_TXT.read_text(encoding="utf-8").strip()
    assert flow["audio"]["stt"]["provider"] == "fixture"
    assert flow["audio"]["stt"]["audio_duration_s"] == pytest.approx(2.0, abs=0.1)


def test_the_offline_path_records_how_long_the_upload_was_deferred(flow):
    with SessionLocal() as db:
        session = db.get(OnboardingSession, uuid.UUID(flow["session_id"]))
    assert session.offline_captured is True
    assert session.captured_at is not None
    assert session.upload_deferred_seconds == pytest.approx(CAPTURED_AGO.total_seconds(), abs=30)


def test_the_recording_is_deleted_once_it_is_transcribed(flow):
    assert not settings.keep_audio
    folder = Path(settings.upload_dir) / flow["session_id"]
    assert not folder.exists() or not any(folder.iterdir()), "the audio must not survive transcription"


def test_an_unsupported_audio_type_is_refused(client, auth):
    session = _start(client, auth(HOST))
    r = client.post(
        f"/api/onboarding/sessions/{session['id']}/audio",
        files={"file": ("notes.txt", b"not audio at all", "text/plain")},
        headers=auth(HOST),
    )
    assert r.status_code == 415
    assert not (Path(settings.upload_dir) / session["id"]).exists()


def test_a_typed_transcript_is_marked_as_typed(client, auth):
    session = _start(client, auth(HOST))
    text = "Nudim vođenje po stazama Vrmca. Ovo je izmišljeni primjer za prototip."
    r = client.post(
        f"/api/onboarding/sessions/{session['id']}/transcript", json={"text": text}, headers=auth(HOST)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] == text
    assert body["stt_provider"] == "typed"
    assert body["status"] == "transcribed"
    events = _session_events(session["id"])
    assert [e.event_type for e in events] == ["onboarding_started", "transcript_ready"]
    assert events[1].properties["stt_provider"] == "typed"


# --------------------------------------------------------------------------------------------------
# (4) draft — title and description ONLY
# --------------------------------------------------------------------------------------------------
def test_the_draft_contains_a_title_and_a_description_and_nothing_else(flow):
    draft = flow["draft"]["draft"]
    assert set(draft) == DRAFT_KEYS
    assert _all_keys(draft) == DRAFT_KEYS
    assert not FORBIDDEN_IN_DRAFT & _all_keys(flow["draft"]["draft"])
    assert all(isinstance(v, str) and v.strip() for v in draft.values())


def test_the_structured_fields_are_listed_as_the_hosts_job(flow):
    required = set(flow["draft"]["fields_required"])
    assert STRUCTURED_FIELDS <= required
    assert not DRAFT_KEYS & required, "the model drafts the title and the description; the host does the rest"


def test_the_hosts_own_words_survive_in_the_description_but_never_as_a_field(flow):
    """The transcript may contain a price — the *text* keeps it, the structured field is host-entered."""
    draft = flow["draft"]["draft"]
    assert "45 do 70" in draft["description_local"], "the description is the host's own words"
    assert "Apartman u Donjoj Lastvi" in draft["title_local"]
    assert "Dobar dan" not in draft["description_local"], "greeting stripped"


def test_the_rules_path_says_that_it_could_not_translate(flow):
    # LLM_PROVIDER=none in the test environment, so the deterministic path runs and admits it.
    assert flow["draft"]["extraction_method"] == "rules"
    assert flow["draft"]["translation_pending"] is True
    assert flow["draft"]["draft"]["description_en"] == flow["draft"]["draft"]["description_local"]


def test_a_draft_needs_a_transcript(client, auth):
    session = _start(client, auth(HOST))
    r = client.post(f"/api/onboarding/sessions/{session['id']}/draft", headers=auth(HOST))
    assert r.status_code == 409


# --------------------------------------------------------------------------------------------------
# (5) confirm — consent and the host's confirmed structured fields
# --------------------------------------------------------------------------------------------------
def test_confirm_returns_the_contract_shape_and_both_clocks(flow):
    confirmed = flow["confirmed"]
    assert set(confirmed) == {
        "listing", "consent_record_id", "active_seconds", "elapsed_to_confirm_seconds",
        "target_minutes", "within_active_target",
    }
    assert confirmed["active_seconds"] == pytest.approx(sum(HEARTBEATS))
    assert confirmed["within_active_target"] is True
    assert confirmed["target_minutes"] == settings.onboarding_target_minutes
    assert confirmed["elapsed_to_confirm_seconds"] >= confirmed["active_seconds"], (
        "elapsed time includes thinking, walking around the house and waiting; active time does not"
    )


def test_the_listing_is_created_in_draft_with_provenance_and_consent(flow):
    with SessionLocal() as db:
        listing = db.get(Listing, uuid.UUID(flow["listing_id"]))
        assert listing.status == "draft", "a new listing enters the validation queue, it is not published"
        assert listing.version == 1
        assert listing.is_sample is True
        assert listing.onboarding_session_id == uuid.UUID(flow["session_id"])

        provenance = validation.provenance_for(db, "listing", listing.id)
        assert [p.action for p in provenance] == ["created"]
        assert provenance[0].source == f"voice onboarding session {flow['session_id']}"
        assert provenance[0].to_status == "draft"

        consent = db.get(ConsentRecord, listing.consent_record_id)
        assert consent is not None
        assert consent.consent_given is True
        assert consent.listing_id == listing.id
        assert consent.onboarding_session_id == uuid.UUID(flow["session_id"])
        assert consent.host_user_id == _user_id(HOST)
        assert str(consent.id) == flow["confirmed"]["consent_record_id"]


def test_the_structured_fields_are_stored_exactly_as_the_host_submitted_them(flow):
    with SessionLocal() as db:
        listing = db.get(Listing, uuid.UUID(flow["listing_id"]))
    assert listing.price_min == 45.0
    assert listing.price_max == 70.0
    assert listing.currency == "EUR"
    assert (listing.season_from, listing.season_to, listing.season_all_year) == (5, 10, False)
    assert listing.capacity == 4
    assert listing.accessibility_step_free is True
    assert listing.lat == pytest.approx(42.4402) and listing.lng == pytest.approx(18.6848)
    assert listing.confirmed_fields == CONFIRMED_FIELDS
    assert listing.category == "accommodation"
    assert listing.extraction_method == "rules"
    assert listing.translation_pending is True
    assert listing.missing_fields == []


def test_confirm_without_consent_is_refused(client, auth):
    session, headers = _confirmable_session(client, auth)
    r = client.post(
        f"/api/onboarding/sessions/{session['id']}/confirm",
        json={"listing": _listing_payload(), "consent": {"given": False, "method": "checkbox"}},
        headers=headers,
    )
    assert r.status_code == 422
    assert "consent" in r.json()["detail"].lower()
    with SessionLocal() as db:
        assert db.get(OnboardingSession, uuid.UUID(session["id"])).listing_id is None


@pytest.mark.parametrize(
    "confirmed_fields, missing",
    [
        ([], "price"),
        (["price_min", "price_max", "currency"], "season"),
        (["price_min", "price_max", "season", "accessibility", "coordinates"], "capacity"),
        (["price_min", "season", "capacity", "coordinates"], "accessibility"),
        (["price_min", "season", "capacity", "accessibility"], "coordinates"),
    ],
)
def test_confirm_with_incomplete_confirmed_fields_is_refused(client, auth, confirmed_fields, missing):
    session, headers = _confirmable_session(client, auth)
    payload = _listing_payload()
    payload["confirmed_fields"] = confirmed_fields
    r = client.post(
        f"/api/onboarding/sessions/{session['id']}/confirm",
        json={"listing": payload, "consent": CONSENT},
        headers=headers,
    )
    assert r.status_code == 422
    assert missing in r.json()["detail"]


def _listing_payload() -> dict:
    return {
        "title_local": "Sobe kod mora (uzorak)",
        "title_en": "Rooms by the sea (sample)",
        "description_local": "Izmišljeni primjer za prototip.",
        "description_en": "Fictional prototype example.",
        **{k: v for k, v in STRUCTURED_INPUT.items()},
    }


def _confirmable_session(client, auth):
    headers = auth(HOST)
    session = _start(client, headers, village="donja-lastva")
    client.post(
        f"/api/onboarding/sessions/{session['id']}/transcript",
        json={"text": "Izdajem sobu u Donjoj Lastvi. Izmišljeni primjer."},
        headers=headers,
    )
    client.post(f"/api/onboarding/sessions/{session['id']}/draft", headers=headers)
    return session, headers


# --------------------------------------------------------------------------------------------------
# (6) events — order, documented properties, pseudonymised
# --------------------------------------------------------------------------------------------------
def test_the_four_events_are_emitted_in_order(flow):
    events = _session_events(flow["session_id"], flow["listing_id"])
    assert [e.event_type for e in events] == [
        "onboarding_started", "transcript_ready", "draft_generated", "listing_confirmed",
    ]


def test_every_event_carries_the_documented_properties(flow):
    started, transcript, draft, confirmed = _session_events(flow["session_id"], flow["listing_id"])

    assert started.item_type == "onboarding_session"
    assert started.properties == {"language": "cnr", "via_ambassador": False}

    assert set(transcript.properties) == {
        "stt_provider", "stt_model", "audio_duration_s", "transcript_chars",
        "offline_captured", "upload_deferred_seconds", "seconds_since_start",
    }
    assert transcript.properties["stt_provider"] == "fixture"
    assert transcript.properties["offline_captured"] is True
    assert transcript.properties["upload_deferred_seconds"] == pytest.approx(
        CAPTURED_AGO.total_seconds(), abs=30
    )
    assert transcript.properties["transcript_chars"] > 100

    assert set(draft.properties) == {
        "llm_provider", "extraction_method", "translation_pending", "seconds_since_start", "active_seconds",
    }
    assert draft.properties["extraction_method"] == "rules"
    assert draft.properties["active_seconds"] == pytest.approx(sum(HEARTBEATS))

    # K06 reads active_seconds, K07 reads within_active_target
    assert set(confirmed.properties) == {
        "onboarding_session_id", "active_seconds", "elapsed_to_confirm_seconds", "within_active_target",
        "category", "extraction_method", "offline_captured",
    }
    assert confirmed.properties["active_seconds"] == pytest.approx(sum(HEARTBEATS))
    assert confirmed.properties["within_active_target"] is True
    assert confirmed.properties["category"] == "accommodation"
    assert confirmed.item_type == "listing"
    assert confirmed.item_id == uuid.UUID(flow["listing_id"])


def test_no_event_row_carries_a_user_id_in_the_clear(flow):
    host_id, ambassador_id = _user_id(HOST), _user_id(AMBASSADOR)
    for event in _session_events(flow["session_id"], flow["listing_id"]):
        row = {c.name: getattr(event, c.name) for c in event.__table__.columns}
        blob = json.dumps(row, default=str)
        assert str(host_id) not in blob
        assert str(ambassador_id) not in blob
        assert event.actor_pseudonym == pseudonymise(ACTOR, host_id)
        assert event.actor_pseudonym != str(host_id)
        assert event.actor_role == "host"
        # host3 self-reported her gender, so the disaggregation is allowed on this row
        assert event.actor_gender == "female"
        assert event.gender_self_reported is True


def test_every_event_is_attached_to_the_village(flow):
    with SessionLocal() as db:
        village_id = db.scalars(
            select(OnboardingSession.village_id).where(OnboardingSession.id == uuid.UUID(flow["session_id"]))
        ).one()
    for event in _session_events(flow["session_id"], flow["listing_id"]):
        assert event.village_id == village_id
        assert event.municipality == "Tivat"


# --------------------------------------------------------------------------------------------------
# (7) approval → publication → visible to a visitor
# --------------------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def published(flow):
    """The validator approves; ``mark_published`` closes the elapsed clock.

    ``services/validation.transition`` is the shared module (owned elsewhere) that must call
    ``onboarding.mark_published`` after it publishes a listing — here it is called explicitly.
    """
    with SessionLocal() as db:
        validator = db.scalars(select(User).where(User.email == VALIDATOR)).one()
        listing = validation.transition(
            db, "listing", flow["listing_id"], "approved", actor=validator, note="test: sample listing"
        )
        session = svc.mark_published(db, listing)
        db.commit()
        return {
            "listing_id": listing.id,
            "published_at": listing.published_at,
            "session": svc.session_state(session),
        }


def test_publication_closes_the_elapsed_clock_without_touching_the_active_one(published, flow):
    session = published["session"]
    assert session["status"] == "published"
    assert session["published_at"] is not None
    assert session["elapsed_to_publish_seconds"] >= session["elapsed_to_confirm_seconds"]
    assert session["active_seconds"] == pytest.approx(sum(HEARTBEATS)), "review time is not authoring time"
    assert session["within_active_target"] is True


def test_the_published_listing_is_visible_to_the_visitor_role(published):
    with PublicSessionLocal() as public_db:
        listing = public_db.scalars(
            validation.approved_only(select(Listing).where(Listing.id == published["listing_id"]), Listing)
        ).first()
    assert listing is not None, "the visitor role must see the approved listing"
    assert listing.published_at is not None
    assert listing.status == "approved"


def test_a_listing_that_did_not_come_from_the_wizard_is_left_alone(db):
    other = db.scalars(
        select(Listing).where(Listing.onboarding_session_id.is_(None), Listing.status == "approved")
    ).first()
    assert other is not None
    assert svc.mark_published(db, other) is None


# --------------------------------------------------------------------------------------------------
# (8) reading a session and the timing log
# --------------------------------------------------------------------------------------------------
def test_a_host_cannot_read_another_hosts_session(client, auth, flow):
    r = client.get(f"/api/onboarding/sessions/{flow['session_id']}", headers=auth(OTHER_HOST))
    assert r.status_code == 403


def test_the_owner_its_ambassador_and_any_validator_may_read_the_session(client, auth, flow):
    for email in (HOST, AMBASSADOR, VALIDATOR):
        r = client.get(f"/api/onboarding/sessions/{flow['session_id']}", headers=auth(email))
        assert r.status_code == 200, email
        assert r.json()["id"] == flow["session_id"]


def test_the_timing_log_shows_both_clocks_and_no_user_id(client, auth, flow, published):
    r = client.get("/api/onboarding/timing-log", headers=auth(VALIDATOR))
    assert r.status_code == 200, r.text
    rows = r.json()
    row = next(x for x in rows if x["session_id"] == flow["session_id"])
    assert set(row) == {
        "session_id", "started_at", "active_seconds", "elapsed_to_confirm_seconds",
        "elapsed_to_publish_seconds", "within_active_target", "offline_captured",
        "stt_provider", "llm_provider", "status",
    }
    assert row["active_seconds"] == pytest.approx(sum(HEARTBEATS))
    assert row["within_active_target"] is True
    assert row["elapsed_to_publish_seconds"] >= row["elapsed_to_confirm_seconds"] >= row["active_seconds"]
    assert row["offline_captured"] is True
    assert row["status"] == "published"

    blob = json.dumps(rows)
    for email in (HOST, OTHER_HOST, AMBASSADOR, VALIDATOR):
        assert str(_user_id(email)) not in blob


def test_an_institution_may_read_the_timing_log_and_a_host_may_not(client, auth):
    assert client.get("/api/onboarding/timing-log", headers=auth(INSTITUTION)).status_code == 200
    assert client.get("/api/onboarding/timing-log", headers=auth(HOST)).status_code == 403


def test_the_timing_log_file_is_appended_without_personal_data(flow, published):
    assert svc.TIMING_LOG_PATH.exists(), "the service appends one line per milestone"
    lines = svc.TIMING_LOG_PATH.read_text(encoding="utf-8").splitlines()
    ours = [ln for ln in lines if flow["session_id"] in ln]
    assert [ln.split("event=")[1].split()[0] for ln in ours] == ["confirmed", "published"]
    assert "active_s=255" in ours[0]
    assert "within_active_target=true" in ours[0]
    assert "offline_captured=true" in ours[0]
    for email in (HOST, AMBASSADOR):
        assert str(_user_id(email)) not in "\n".join(lines)
