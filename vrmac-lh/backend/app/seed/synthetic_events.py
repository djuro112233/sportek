"""Synthetic event history for the KPI demo — deterministic, flagged and pseudonymised.

``app/seed/loader.py`` calls :func:`load_synthetic_events` at the end of the seed. It writes the
90-day event stream the institutions' dashboard is computed from, so ``python -m app.cli
kpi-compute`` produces a table with published cells, suppressed cells and a heat map instead of
zeros. Every event carries ``properties["synthetic"] = True`` and the whole history is regenerated
from ``random.Random(42)``: the same seed always yields the same numbers.

Two honesty notes, repeated in ``docs/events.md``:

* **Nothing here is real usage.** The events describe fictional sample hosts and 45 fictional
  visitor devices on the Vrmac plateau.
* The history contains a few **pseudonymous host actors beyond the 12 sample accounts**
  (``EXTRA_HOSTS``). They exist only so the gender cells straddle the k≥5 threshold and the
  disclosure rules — a suppressed cell, a secondary suppression, a surviving cell — are visible in
  the demo. ``K01`` on sample data is therefore not a claim about uptake. Events deliberately have
  no foreign key to ``users`` (see ``app/models.py``), so such an actor is just another pseudonym.

Property names follow the emitting modules exactly (onboarding, ask, itinerary, requests, trails);
the KPI engine reads them through the specs in ``backend/kpi_definitions/sip_section_11.json``.
"""
from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

SEED = 42
PERIOD_DAYS = 90
#: namespace for the extra host pseudonyms — stable across seeds, meaningless outside this prototype
ACTOR_NS = uuid.UUID("6f9b1f2e-0f1a-4c1e-9f3a-000000000042")

#: (lat, lng) of the cell centres of a 0.001° grid, so a jittered visit stays inside one cell
HOTSPOTS: dict[str, tuple[float, float, str]] = {
    "square": (42.4425, 18.6915, "gornja-lastva"),
    "church": (42.4465, 18.6985, "sveti-vid"),
    "waterfront": (42.4405, 18.6855, "donja-lastva"),
    "town": (42.4355, 18.7065, "tivat"),
    # deliberately quiet: too few devices to ever reach k≥5, so the heat map drops the cell
    "junction": (42.4455, 18.6875, "gornja-lastva"),
}
HOTSPOT_DEVICES = {"square": 14, "church": 10, "waterfront": 9, "town": 9, "junction": 3}
BUSY_HOTSPOTS = ("square", "church", "waterfront", "town")
JITTER_DEG = 0.0004  # < half a cell: a visit never leaves its hotspot's cell

N_DEVICES = sum(HOTSPOT_DEVICES.values())

#: sample accounts (seed_data/users.json). host9/host11 never self-reported, host10 chose
#: "prefer_not_to_say" — all three must land in the ``not_reported`` gender cell.
SAMPLE_HOSTS = [f"host{i}@example.org" for i in range(1, 13)]

#: extra pseudonymous host actors: (label, gender, self_reported) — see the module docstring
EXTRA_HOSTS: list[tuple[str, str, bool]] = [
    ("synthetic-host-13", "female", True),
    ("synthetic-host-14", "female", True),
    ("synthetic-host-15", "female", True),
    ("synthetic-host-16", "male", True),
    ("synthetic-host-17", "male", True),
    ("synthetic-host-18", "other", True),
    ("synthetic-host-19", "undisclosed", False),
    ("synthetic-host-20", "undisclosed", False),
    ("synthetic-host-21", "prefer_not_to_say", True),
]

CATEGORIES = ("accommodation", "food", "experience", "craft")
CONDITIONS = ("good", "good", "caution", "blocked")
INTERESTS = ("heritage", "food", "walking", "nature", "crafts")
LANGS = ("cnr", "cnr", "en")


class _Actor:
    """Duck-typed stand-in for :class:`app.models.User` — only what ``emit_event`` reads.

    Never added to the session: the events table has no foreign key to ``users`` and an actor is
    only ever a keyed HMAC pseudonym of this id.
    """

    __slots__ = ("id", "role", "gender", "gender_self_reported", "label")

    def __init__(self, label: str, gender: str, self_reported: bool, role: str = "host"):
        self.id = uuid.uuid5(ACTOR_NS, label)
        self.role = role
        self.gender = gender
        self.gender_self_reported = self_reported
        self.label = label


def _reported(actor: Any) -> str:
    """The gender cell an actor's events land in (``not_reported`` unless self-reported)."""
    if getattr(actor, "gender_self_reported", False) and actor.gender in ("female", "male", "other"):
        return actor.gender
    return "not_reported"


def load_synthetic_events(db: Session, users_by_email: dict, villages_by_slug: dict) -> int:
    """Write the synthetic 90-day event history. Returns the number of events written.

    Raises loudly on any problem: the caller only tolerates a *missing* module, never a broken one.
    """
    try:
        from ..events import emit_event
    except ImportError as exc:  # never let the loader mistake a broken module for an absent one
        raise RuntimeError(f"synthetic event history could not be built: {exc}") from exc

    missing = [slug for slug in ("gornja-lastva", "donja-lastva", "sveti-vid", "tivat") if slug not in villages_by_slug]
    if missing:
        raise RuntimeError(f"synthetic events need the seeded villages, missing: {missing}")

    rng = random.Random(SEED)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    written: list[Any] = []

    def at(days_ago: float, hour: int = 10, minute: int = 0) -> datetime:
        base = now - timedelta(days=days_ago)
        return base.replace(hour=hour % 24, minute=minute % 60, second=0, microsecond=0)

    def emit(event_type: str, **kw) -> None:
        props = kw.pop("properties", {})
        written.append(emit_event(db, event_type, synthetic=True, **props, **kw))

    village = villages_by_slug.__getitem__
    validator = users_by_email["validator1@example.org"]
    ambassador = users_by_email["ambassador1@example.org"]

    # --- who the hosts are ------------------------------------------------------------------------
    hosts: list[Any] = [users_by_email[e] for e in SAMPLE_HOSTS if e in users_by_email]
    if len(hosts) != len(SAMPLE_HOSTS):
        raise RuntimeError("synthetic events expect the 12 sample hosts of seed_data/users.json")
    hosts += [_Actor(label, gender, reported) for label, gender, reported in EXTRA_HOSTS]

    by_gender: dict[str, list[Any]] = {}
    for h in hosts:
        by_gender.setdefault(_reported(h), []).append(h)

    # Two ambassador-run onboarding workshops: five hosts of the same gender on one day, so at least
    # one date × activity × gender cell survives the small-cell rule and the demo can show one.
    workshops = {
        h.id: (60, "female") for h in by_gender.get("female", [])[:5]
    } | {
        h.id: (45, "male") for h in by_gender.get("male", [])[:5]
    }
    village_cycle = ("gornja-lastva", "donja-lastva", "sveti-vid", "tivat")

    # --- host journeys: onboarding → transcript → draft → confirm → approval ----------------------
    for i, host in enumerate(hosts):
        vslug = village_cycle[i % len(village_cycle)]
        v = village(vslug)
        day = workshops[host.id][0] if host.id in workshops else rng.randint(5, 85)
        hour = 9 + (i % 8)
        via_ambassador = i % 3 == 0
        lang = "cnr" if i % 5 else "en"
        offline = i % 4 == 0
        audio_s = round(rng.uniform(45, 210), 1)
        active_s = int(rng.triangular(420, 2400, 1080))  # ~7–40 min of real authoring
        transcript_delay = rng.randint(3, 9)
        draft_delay = transcript_delay + rng.randint(2, 6)
        confirm_delay = draft_delay + rng.randint(3, 12)

        emit(
            "onboarding_started", actor=host, village=v, occurred_at=at(day, hour),
            properties={"language": lang, "via_ambassador": via_ambassador},
        )
        emit(
            "transcript_ready", actor=host, village=v, occurred_at=at(day, hour, transcript_delay),
            properties={
                "stt_provider": "faster-whisper", "stt_model": "small", "audio_duration_s": audio_s,
                "transcript_chars": int(audio_s * rng.uniform(9, 14)), "offline_captured": offline,
                "upload_deferred_seconds": rng.randint(600, 36000) if offline else 0,
                "seconds_since_start": transcript_delay * 60,
            },
        )
        emit(
            "draft_generated", actor=host, village=v, occurred_at=at(day, hour, draft_delay),
            properties={
                "llm_provider": "eu_api", "extraction_method": "llm" if i % 4 else "rules",
                "translation_pending": i % 6 == 0, "seconds_since_start": draft_delay * 60,
                "active_seconds": int(active_s * 0.6),
            },
        )
        emit(
            "listing_confirmed", actor=host, village=v, occurred_at=at(day, hour, confirm_delay),
            properties={
                "onboarding_session_id": str(uuid.uuid5(ACTOR_NS, f"session:{host.id}")),
                "active_seconds": active_s,
                "elapsed_to_confirm_seconds": confirm_delay * 60,
                "within_active_target": active_s <= 30 * 60,
                "category": CATEGORIES[i % len(CATEGORIES)],
                "extraction_method": "llm" if i % 4 else "rules",
                "offline_captured": offline,
            },
        )
        if i % 3 != 2:  # two thirds of the drafts made it through validation
            wait_days = rng.randint(1, 4)
            emit(
                "entry_approved", actor=validator, village=v, item_type="listing",
                occurred_at=at(max(0.5, day - wait_days), 12, i % 60),
                properties={
                    "version": 1, "from_status": "reviewed",
                    "elapsed_to_publish_seconds": wait_days * 86400 + confirm_delay * 60,
                },
            )

    # --- heritage entries through the validation gate ---------------------------------------------
    for i in range(8):
        vslug = village_cycle[i % len(village_cycle)]
        wait_days = rng.randint(2, 9)
        emit(
            "entry_approved", actor=validator, village=village(vslug), item_type="heritage_entry",
            occurred_at=at(rng.randint(6, 80), 14, i * 7 % 60),
            properties={"version": 1, "from_status": "reviewed", "elapsed_to_publish_seconds": wait_days * 86400},
        )
    for i, item_type in enumerate(("heritage_entry", "listing")):
        emit(
            "item_rejected", actor=validator, village=village(village_cycle[i]), item_type=item_type,
            occurred_at=at(rng.randint(10, 70), 15, i * 11 % 60),
            properties={"version": 1, "from_status": "draft"},
        )

    # --- visitors ---------------------------------------------------------------------------------
    devices: list[tuple[str, str]] = []  # (device_id, hotspot)
    n = 0
    for hotspot, count in HOTSPOT_DEVICES.items():
        for _ in range(count):
            n += 1
            devices.append((f"vrmac-demo-device-{n:02d}", hotspot))

    hosts_taking_requests = hosts[:14]
    request_no = 0

    for idx, (device_id, home) in enumerate(devices):
        for visit in range(rng.randint(1, 3)):
            day = rng.randint(1, 88)
            hour = 9 + rng.randint(0, 9)
            session_id = f"{device_id}-s{visit}"
            spots = [home]
            if rng.random() < 0.35:
                spots.append(rng.choice([s for s in BUSY_HOTSPOTS if s != home]))
            for spot in spots:
                lat, lng, vslug = HOTSPOTS[spot]
                v = village(vslug)
                emit(
                    "visit_recorded", session_id=session_id, device_id=device_id, village=v,
                    lat=round(lat + rng.uniform(-JITTER_DEG, JITTER_DEG), 6),
                    lng=round(lng + rng.uniform(-JITTER_DEG, JITTER_DEG), 6),
                    occurred_at=at(day, hour, rng.randint(0, 59)),
                )

            # the assistant: grounded answers, and refusals when nothing approved covers the question
            for q in range(rng.randint(0, 3)):
                lang = rng.choice(LANGS)
                withheld = rng.random() < 0.18
                v = village(HOTSPOTS[home][2])
                if withheld:
                    emit(
                        "answer_withheld", session_id=session_id, device_id=device_id, village=v,
                        occurred_at=at(day, hour, 5 + q * 7),
                        properties={
                            "lang": lang, "refusal_reason": rng.choice(["no_approved_source", "low_confidence", "unsupported_answer"]),
                            "confidence": round(rng.uniform(0.1, 0.55), 3), "dropped_sentences": rng.randint(0, 2),
                        },
                    )
                else:
                    emit(
                        "answer_served", session_id=session_id, device_id=device_id, village=v,
                        occurred_at=at(day, hour, 5 + q * 7),
                        properties={
                            "lang": lang, "confidence": round(rng.uniform(0.6, 0.95), 3),
                            "n_citations": rng.randint(1, 3), "dropped_sentences": rng.randint(0, 1),
                            "served_from_cache": rng.random() < 0.3, "llm_provider": "eu_api",
                            "support_provider": "lexical",
                        },
                    )

            if rng.random() < 0.45:
                multi = rng.random() < 0.4
                emit(
                    "itinerary_generated", session_id=session_id, device_id=device_id,
                    village=village(HOTSPOTS[home][2]), occurred_at=at(day, hour, 25),
                    properties={
                        "n_stops": rng.randint(2, 6), "hours": rng.choice([2, 3, 4, 6]),
                        "total_km": round(rng.uniform(1.5, 11.0), 2),
                        "interests": sorted(rng.sample(INTERESTS, rng.randint(1, 3))),
                        "multi_village": multi,
                    },
                )

            if rng.random() < 0.45:
                request_no += 1
                host = hosts_taking_requests[request_no % len(hosts_taking_requests)]
                vslug = HOTSPOTS[home][2]
                v = village(vslug)
                request_id = str(uuid.uuid5(ACTOR_NS, f"request:{request_no}"))
                emit(
                    "request_sent", session_id=session_id, device_id=device_id, village=v,
                    item_type="listing", occurred_at=at(day, hour, 40),
                    properties={"party_size": rng.randint(1, 6)},
                )
                outcome = rng.random()
                if outcome < 0.62:
                    emit(
                        "request_confirmed", actor=host, village=v, item_type="listing",
                        occurred_at=at(max(0.4, day - 0.3), hour + 2, 5),
                        properties={"request_id": request_id},
                    )
                    end = rng.random()
                    if end < 0.62:
                        emit("request_completed", actor=host, village=v, item_type="listing",
                             occurred_at=at(max(0.2, day - 2), 18, 0), properties={"request_id": request_id})
                    elif end < 0.85:
                        emit("request_cancelled", actor=host, village=v, item_type="listing",
                             occurred_at=at(max(0.2, day - 1), 9, 0), properties={"request_id": request_id})
                elif outcome < 0.82:
                    emit("request_refused", actor=host, village=v, item_type="listing",
                         occurred_at=at(max(0.4, day - 0.4), hour + 3, 0), properties={"request_id": request_id})
                else:
                    emit("request_expired", actor=None, actor_role="system", village=v, item_type="listing",
                         occurred_at=at(max(0.2, day - 7), 3, 0), properties={"request_id": request_id})

            if rng.random() < 0.09:
                lat, lng, vslug = HOTSPOTS[home]
                emit(
                    "trail_report", session_id=session_id, device_id=device_id, village=village(vslug),
                    item_type="trail_report",
                    lat=round(lat + rng.uniform(-0.002, 0.002), 6),
                    lng=round(lng + rng.uniform(-0.002, 0.002), 6),
                    occurred_at=at(day, hour, 50),
                    properties={
                        "condition": rng.choice(CONDITIONS),
                        "report_id": str(uuid.uuid5(ACTOR_NS, f"report:{idx}:{visit}")),
                    },
                )

    # --- the spend cap pausing the assistant ------------------------------------------------------
    for i in range(2):
        emit(
            "assistant_paused", session_id=f"vrmac-demo-device-0{i + 1}-s0", device_id=f"vrmac-demo-device-0{i + 1}",
            village=village("gornja-lastva"), occurred_at=at(3 + i, 20, 15),
            properties={"reason": "monthly_cap", "served_from_cache": bool(i)},
        )

    # An ambassador-assisted onboarding for the record: the ambassador is an actor too.
    emit(
        "onboarding_started", actor=ambassador, village=village("donja-lastva"), occurred_at=at(30, 11),
        properties={"language": "cnr", "via_ambassador": True},
    )

    db.flush()
    log.info(
        "synthetic event history: %d events, %d host actors, %d visitor devices, %d days",
        len(written), len(hosts), N_DEVICES, PERIOD_DAYS,
    )
    return len(written)
