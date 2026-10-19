"""Tests for app.api.metrics: k-anonymised public aggregates and the admin-only internal view."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.metrics import (
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    TOP_TOPICS,
    clamp_window,
    compute_internal_metrics,
    compute_public_metrics,
)
from app.main import create_app
from app.models import Event, GateRecord, Session
from tests.conftest import make_test_settings

K = 5
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
ADMIN = {"X-Admin-Token": "test-admin-token"}
PUBLIC_KEYS = {
    "generated_at",
    "k",
    "window_days",
    "sessions_total",
    "sessions_per_day",
    "outcomes",
    "ratios",
    "top_topics",
    "referral_rate",
    "redflag_rate",
    "input_modes",
    "median_latency_ms",
    "p90_latency_ms",
    "mean_support_ratio",
    "translated_rate",
}


def _add_sessions(db, n: int, *, when: datetime = NOW, prefix: str = "sess") -> list[str]:
    ids = [f"{prefix}-{when.date().isoformat()}-{i:03d}" for i in range(n)]
    for sid in ids:
        db.add(Session(id=sid, created_at=when, consent_given=True))
    db.commit()
    return ids


def _add_events(
    db,
    n: int,
    *,
    ev_type: str = "ask",
    outcome: str = "answered",
    topic: str = "pregnancy",
    when: datetime = NOW,
    input_mode: str = "text",
    latencies: list[int] | None = None,
    support: list[float] | None = None,
    translated: bool = False,
    category: str = "",
    session_id: str | None = None,
) -> None:
    for i in range(n):
        db.add(
            Event(
                session_id=session_id,
                type=ev_type,
                outcome=outcome,
                topic_class=topic,
                input_mode=input_mode,
                latency_ms=latencies[i] if latencies else None,
                support_ratio=support[i] if support else None,
                redflag_category=category,
                payload={"translated": True} if translated else {},
                created_at=when,
            )
        )
    db.commit()


# --- compute_public_metrics with a fixed now ---------------------------------------------------
def test_empty_database_gives_all_nulls(db):
    m = compute_public_metrics(db, K, 30, NOW).model_dump()
    assert set(m) == PUBLIC_KEYS
    assert m["generated_at"] == NOW.isoformat()
    assert m["k"] == K and m["window_days"] == 30
    assert m["sessions_total"] is None
    assert m["sessions_per_day"] == [] and m["top_topics"] == []
    assert m["outcomes"] == {"answered": None, "withheld": None, "redflag": None}
    assert m["ratios"] == {"answered": None, "withheld": None, "redflag": None}
    assert m["input_modes"] == {"text": None, "voice": None}
    for key in (
        "referral_rate",
        "redflag_rate",
        "median_latency_ms",
        "p90_latency_ms",
        "mean_support_ratio",
        "translated_rate",
    ):
        assert m[key] is None


def test_counts_at_k_minus_one_are_suppressed(db):
    _add_sessions(db, K - 1)
    _add_events(db, K - 1, latencies=[100] * (K - 1), support=[1.0] * (K - 1), translated=True)
    m = compute_public_metrics(db, K, 30, NOW).model_dump()
    assert m["sessions_total"] is None
    assert m["sessions_per_day"] == []
    assert m["outcomes"]["answered"] is None
    assert m["ratios"]["answered"] is None
    assert m["top_topics"] == []
    assert m["input_modes"]["text"] is None
    assert m["median_latency_ms"] is None and m["p90_latency_ms"] is None
    assert m["mean_support_ratio"] is None and m["translated_rate"] is None
    assert m["referral_rate"] is None and m["redflag_rate"] is None


def test_counts_at_k_are_disclosed(db):
    _add_sessions(db, K)
    _add_events(
        db, K, latencies=[100, 200, 300, 400, 500], support=[0.6, 0.8, 1.0, 0.9, 0.7], translated=True
    )
    m = compute_public_metrics(db, K, 30, NOW).model_dump()
    assert m["sessions_total"] == K
    assert m["sessions_per_day"] == [{"date": "2026-10-15", "count": K}]
    assert m["outcomes"] == {"answered": K, "withheld": None, "redflag": None}
    assert m["ratios"] == {"answered": 1.0, "withheld": None, "redflag": None}
    assert m["top_topics"] == [{"topic": "pregnancy", "count": K}]
    assert m["input_modes"] == {"text": K, "voice": None}
    assert m["median_latency_ms"] == 300.0 and m["p90_latency_ms"] == 500.0
    assert m["mean_support_ratio"] == 0.8
    assert m["translated_rate"] == 1.0
    assert m["referral_rate"] is None and m["redflag_rate"] is None


def test_mixed_outcomes_ratios_and_rates(db):
    _add_events(db, 10, outcome="answered", topic="contraception")
    _add_events(db, 5, outcome="withheld", topic="other")
    _add_events(db, 5, ev_type="redflag", outcome="redflag", topic="pregnancy", category="bleeding_pregnancy")
    m = compute_public_metrics(db, K, 30, NOW).model_dump()
    assert m["outcomes"] == {"answered": 10, "withheld": 5, "redflag": 5}
    assert m["ratios"] == {"answered": 0.5, "withheld": 0.25, "redflag": 0.25}
    assert m["referral_rate"] == 0.5
    assert m["redflag_rate"] == 0.25
    assert m["top_topics"] == [
        {"topic": "contraception", "count": 10},
        {"topic": "other", "count": 5},
        {"topic": "pregnancy", "count": 5},
    ]


def test_ratio_with_small_numerator_is_null_even_when_n_is_large(db):
    _add_events(db, 10, outcome="answered")
    _add_events(db, 2, ev_type="redflag", outcome="redflag")
    m = compute_public_metrics(db, K, 30, NOW).model_dump()
    assert m["outcomes"]["redflag"] is None
    assert m["ratios"]["redflag"] is None and m["redflag_rate"] is None
    assert m["ratios"]["answered"] == round(10 / 12, 3)


def test_per_day_rows_below_k_are_dropped(db):
    _add_sessions(db, K, when=NOW - timedelta(days=2), prefix="a")
    _add_sessions(db, K - 2, when=NOW - timedelta(days=1), prefix="b")
    m = compute_public_metrics(db, K, 30, NOW).model_dump()
    assert m["sessions_total"] == 2 * K - 2
    assert m["sessions_per_day"] == [{"date": "2026-10-13", "count": K}]


def test_topics_below_k_dropped_sorted_and_capped(db):
    for i in range(12):
        _add_events(db, K + i, topic=f"t{i:02d}")
    _add_events(db, K - 1, topic="rare")
    rows = compute_public_metrics(db, K, 30, NOW).model_dump()["top_topics"]
    assert len(rows) == TOP_TOPICS
    assert [r["count"] for r in rows] == sorted((r["count"] for r in rows), reverse=True)
    assert rows[0] == {"topic": "t11", "count": K + 11}
    assert "rare" not in {r["topic"] for r in rows}
    assert "t00" not in {r["topic"] for r in rows} and "t01" not in {r["topic"] for r in rows}


def test_window_excludes_old_and_future_events(db):
    _add_events(db, K, when=NOW - timedelta(days=40), topic="old")
    _add_events(db, K, when=NOW + timedelta(days=1), topic="future")
    _add_events(db, K, when=NOW - timedelta(days=29), topic="recent")
    _add_sessions(db, K, when=NOW - timedelta(days=40), prefix="old")
    m = compute_public_metrics(db, K, 30, NOW).model_dump()
    assert m["top_topics"] == [{"topic": "recent", "count": K}]
    assert m["sessions_total"] is None
    wide = compute_public_metrics(db, K, 60, NOW).model_dump()
    assert {r["topic"] for r in wide["top_topics"]} == {"old", "recent"}
    assert wide["sessions_total"] == K


@pytest.mark.parametrize(
    ("requested", "effective"),
    [(None, DEFAULT_WINDOW_DAYS), (0, 1), (-5, 1), (7, 7), (1000, MAX_WINDOW_DAYS)],
)
def test_window_is_clamped(db, requested: int | None, effective: int):
    assert clamp_window(requested) == effective
    assert compute_public_metrics(db, K, requested, NOW).window_days == effective


def test_latency_percentiles_use_nearest_rank(db):
    _add_events(db, 10, latencies=list(range(100, 1100, 100)))
    m = compute_public_metrics(db, K, 30, NOW)
    assert m.median_latency_ms == 550.0
    assert m.p90_latency_ms == 900.0


def test_translated_rate_needs_k_translated_answers(db):
    _add_events(db, 5, translated=True)
    _add_events(db, 5, translated=False)
    assert compute_public_metrics(db, K, 30, NOW).translated_rate == 0.5
    _add_events(db, 10, translated=False)
    assert compute_public_metrics(db, K, 30, NOW).translated_rate == 0.25
    assert compute_public_metrics(db, 6, 30, NOW).translated_rate is None


def test_input_modes_are_suppressed_independently(db):
    _add_events(db, 6, input_mode="voice")
    _add_events(db, 4, input_mode="text")
    m = compute_public_metrics(db, K, 30, NOW).input_modes
    assert m.voice == 6 and m.text is None


def test_non_question_events_are_not_counted_as_questions(db):
    for ev_type in ("consent", "transcribe", "speak", "delete", "referral_view"):
        _add_events(db, K, ev_type=ev_type, outcome="ok", topic="")
    _add_events(db, K, ev_type="ask", outcome="error", topic="pregnancy")  # failed asks are not outcomes
    public = compute_public_metrics(db, K, 30, NOW).model_dump()
    assert public["outcomes"] == {"answered": None, "withheld": None, "redflag": None}
    assert public["top_topics"] == []
    internal = compute_internal_metrics(db, K, 30, NOW)
    assert internal.unsuppressed.questions == 0
    assert internal.events_by_type == {
        "ask": K,
        "consent": K,
        "delete": K,
        "referral_view": K,
        "speak": K,
        "transcribe": K,
    }


def test_compute_is_deterministic_for_a_fixed_now(db):
    _add_sessions(db, 7)
    _add_events(db, 7, latencies=[10, 20, 30, 40, 50, 60, 70])
    assert compute_public_metrics(db, K, 30, NOW) == compute_public_metrics(db, K, 30, NOW)


def test_naive_now_is_treated_as_utc(db):
    _add_sessions(db, K)
    naive = NOW.replace(tzinfo=None)
    assert compute_public_metrics(db, K, 30, naive).sessions_total == K


# --- compute_internal_metrics ------------------------------------------------------------------
def test_internal_metrics_add_unsuppressed_counts_and_histograms(db):
    sids = _add_sessions(db, 3)
    _add_events(
        db,
        3,
        outcome="answered",
        topic="menstruation",
        input_mode="voice",
        translated=True,
        session_id=sids[0],
    )
    _add_events(db, 2, ev_type="redflag", outcome="redflag", topic="pregnancy", category="bleeding_pregnancy")
    _add_events(
        db, 1, ev_type="redflag", outcome="redflag", topic="mental_health", category="suicidal_ideation"
    )
    for reasons, status in (
        (["low_support_ratio", "no_citations"], "withheld"),
        (["low_support_ratio"], "withheld"),
        ([], "approved"),
    ):
        db.add(GateRecord(gate_version="1.0.0", status=status, reasons=reasons, created_at=NOW))
    db.commit()

    m = compute_internal_metrics(db, K, 30, NOW)
    # public part is still suppressed
    assert m.sessions_total is None and m.outcomes.answered is None and m.top_topics == []
    # internal part is not
    assert m.unsuppressed.sessions_total == 3
    assert m.unsuppressed.questions == 6
    assert (m.unsuppressed.answered, m.unsuppressed.withheld, m.unsuppressed.redflag) == (3, 0, 3)
    assert (m.unsuppressed.text, m.unsuppressed.voice, m.unsuppressed.translated) == (3, 3, 3)
    assert [d.model_dump() for d in m.unsuppressed.sessions_per_day] == [{"date": "2026-10-15", "count": 3}]
    assert [t.model_dump() for t in m.unsuppressed.topics] == [
        {"topic": "menstruation", "count": 3},
        {"topic": "pregnancy", "count": 2},
        {"topic": "mental_health", "count": 1},
    ]
    assert m.redflag_categories == {"bleeding_pregnancy": 2, "suicidal_ideation": 1}
    assert m.gate_reasons == {"low_support_ratio": 2, "no_citations": 1}
    assert m.gate_decisions == {"approved": 1, "withheld": 2}
    assert m.events_by_type == {"ask": 3, "redflag": 3}


def test_internal_metrics_respect_the_window_for_gate_records(db):
    db.add(
        GateRecord(
            gate_version="1.0.0",
            status="withheld",
            reasons=["no_sentences"],
            created_at=NOW - timedelta(days=90),
        )
    )
    db.commit()
    assert compute_internal_metrics(db, K, 30, NOW).gate_reasons == {}
    assert compute_internal_metrics(db, K, 120, NOW).gate_reasons == {"no_sentences": 1}


# --- endpoints ---------------------------------------------------------------------------------
def test_public_endpoint_returns_json_without_session_ids(client, db):
    sids = _add_sessions(db, 8, when=datetime.now(UTC))
    for sid in sids:
        _add_events(db, 1, session_id=sid, when=datetime.now(UTC), latencies=[250])
    r = client.get("/api/metrics/public")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == PUBLIC_KEYS
    assert body["k"] == 5 and body["window_days"] == DEFAULT_WINDOW_DAYS
    assert body["sessions_total"] == 8 and body["outcomes"]["answered"] == 8
    dumped = json.dumps(body)
    for sid in sids:
        assert sid not in dumped
    assert "session_id" not in dumped and "sess-" not in dumped


def test_public_endpoint_clamps_the_window(client):
    assert (
        client.get("/api/metrics/public", params={"window_days": 1000}).json()["window_days"]
        == MAX_WINDOW_DAYS
    )
    assert client.get("/api/metrics/public", params={"window_days": 0}).json()["window_days"] == 1
    assert client.get("/api/metrics/public", params={"window_days": "many"}).status_code == 422


def test_public_endpoint_is_open_without_token(client):
    assert client.get("/api/metrics/public").status_code == 200


def test_internal_endpoint_requires_admin_token(client):
    assert client.get("/api/metrics/internal").status_code == 403
    assert client.get("/api/metrics/internal", headers={"X-Admin-Token": "wrong"}).status_code == 403
    r = client.get("/api/metrics/internal", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert PUBLIC_KEYS < set(body)
    assert {"unsuppressed", "redflag_categories", "gate_reasons", "gate_decisions", "events_by_type"} <= set(
        body
    )


def test_internal_endpoint_is_404_when_admin_is_disabled(tmp_path):
    app = create_app(make_test_settings(tmp_path, admin_token=""))
    with TestClient(app) as c:
        assert c.get("/api/metrics/internal", headers=ADMIN).status_code == 404
        assert c.get("/api/metrics/public").status_code == 200
