"""Authentication and the voluntary gender self-report (/api/auth).

Proves, against the real database:

* login succeeds for the sample accounts and fails without leaking the e-mail into the audit log;
* ``GET /api/auth/me`` needs a valid token — a tampered one is rejected;
* ``POST /api/auth/me/gender`` is the **only** way ``gender_self_reported`` becomes true, the value
  appears in ``UserOut``, and the audit row records the fact without the value.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, User

#: A sample host who has never answered the gender question (users.json: undisclosed).
UNREPORTED_EMAIL = "host9@example.org"


@pytest.fixture()
def unreported_user(db):
    """``host9`` before and after the test: gender ``undisclosed``, never self-reported."""
    user = db.scalars(select(User).where(User.email == UNREPORTED_EMAIL)).one()
    assert user.gender == "undisclosed" and user.gender_self_reported is False
    yield user
    db.rollback()
    user = db.scalars(select(User).where(User.email == UNREPORTED_EMAIL)).one()
    user.gender = "undisclosed"
    user.gender_self_reported = False
    db.commit()


def _token(client, email: str) -> str:
    r = client.post("/api/auth/login", json={"email": email, "password": settings.seed_password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_login_returns_a_token_and_the_user(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "validator1@example.org", "password": settings.seed_password},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    assert body["user"]["role"] == "validator"
    assert body["user"]["email"] == "validator1@example.org"
    assert "password" not in body["user"] and "password_hash" not in body["user"]


def test_login_is_case_insensitive_in_the_local_part_of_the_domain(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "Validator1@Example.org", "password": settings.seed_password},
    )
    assert r.status_code == 200, r.text


def test_login_with_a_wrong_password_is_401_and_audits_no_email(client, db):
    r = client.post(
        "/api/auth/login", json={"email": "validator1@example.org", "password": "wrong-password"}
    )
    assert r.status_code == 401
    assert "access_token" not in r.json()

    rows = db.scalars(
        select(AuditLog).where(AuditLog.action == "auth.login_failed").order_by(AuditLog.occurred_at.desc())
    ).all()
    assert rows, "a failed login must leave an audit row"
    latest = rows[0]
    assert latest.user_id is None and latest.role == "anonymous"
    serialised = json.dumps(latest.detail)
    assert "@" not in serialised and "validator1" not in serialised


def test_login_with_an_unknown_email_is_401(client):
    r = client.post(
        "/api/auth/login", json={"email": "nobody@example.org", "password": settings.seed_password}
    )
    assert r.status_code == 401


def test_me_requires_a_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_the_signed_in_user(client, login):
    r = client.get("/api/auth/me", headers=login("ambassador"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "ambassador"
    assert set(body) >= {"id", "email", "role", "display_name", "gender", "gender_self_reported", "is_sample"}


def test_a_tampered_token_is_rejected(client):
    token = _token(client, "validator1@example.org")
    head, payload, signature = token.split(".")
    tampered = f"{head}.{payload}.{signature[:-4]}xxxx"  # same shape, broken signature
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


def test_gender_self_report_round_trip(client, db, unreported_user):
    """The voluntary self-report is the only thing that sets ``gender_self_reported``."""
    headers = {"Authorization": f"Bearer {_token(client, UNREPORTED_EMAIL)}"}

    before = client.get("/api/auth/me", headers=headers).json()
    assert before["gender"] == "undisclosed" and before["gender_self_reported"] is False

    r = client.post("/api/auth/me/gender", json={"gender": "female"}, headers=headers)
    assert r.status_code == 200, r.text
    reported = r.json()
    assert reported["gender"] == "female" and reported["gender_self_reported"] is True

    # It is persisted, and it appears in UserOut everywhere (GET /me and the login response).
    after = client.get("/api/auth/me", headers=headers).json()
    assert after["gender"] == "female" and after["gender_self_reported"] is True
    relogin = client.post(
        "/api/auth/login", json={"email": UNREPORTED_EMAIL, "password": settings.seed_password}
    ).json()
    assert relogin["user"]["gender"] == "female"
    assert relogin["user"]["gender_self_reported"] is True

    db.expire_all()
    row = db.scalars(select(User).where(User.email == UNREPORTED_EMAIL)).one()
    assert row.gender == "female" and row.gender_self_reported is True


def test_gender_self_report_is_audited_without_the_value(client, db, unreported_user):
    headers = {"Authorization": f"Bearer {_token(client, UNREPORTED_EMAIL)}"}
    assert client.post("/api/auth/me/gender", json={"gender": "other"}, headers=headers).status_code == 200

    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "user.gender_self_report")
        .order_by(AuditLog.occurred_at.desc())
    ).all()
    assert rows, "the self-report must be audited"
    latest = rows[0]
    assert latest.role == "host" and latest.user_id == unreported_user.id
    serialised = json.dumps(latest.detail)
    # The row already identifies the person; the value must not sit next to that identifier.
    for value in ("female", "male", "other", "prefer_not_to_say"):
        assert value not in serialised


def test_prefer_not_to_say_is_an_answer_but_is_not_disaggregated(client, db, unreported_user):
    headers = {"Authorization": f"Bearer {_token(client, UNREPORTED_EMAIL)}"}
    r = client.post("/api/auth/me/gender", json={"gender": "prefer_not_to_say"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["gender"] == "prefer_not_to_say"
    assert r.json()["gender_self_reported"] is True  # answered, but excluded from gender cells

    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "user.gender_self_report")
        .order_by(AuditLog.occurred_at.desc())
    ).all()
    assert rows[0].detail.get("disaggregated") is False


def test_gender_self_report_rejects_unknown_values(client, login):
    for value in ("undisclosed", "f", "", None, 1):
        r = client.post("/api/auth/me/gender", json={"gender": value}, headers=login("host"))
        assert r.status_code == 422, f"{value!r} must be refused"


def test_gender_self_report_requires_a_token(client):
    assert client.post("/api/auth/me/gender", json={"gender": "female"}).status_code == 401
