"""Pseudonymisation of identifiers written to the event stream.

Events must never carry a direct identifier. Every actor, visitor session and device id is replaced
by a keyed HMAC-SHA256 digest truncated to 32 hex characters:

    pseudonym = HMAC(EVENT_PSEUDONYM_KEY, "<kind>:<value>")[:32]

Properties this gives us:

* **Stable** for the same input and key, so KPIs can count *distinct* persons or devices
  (K11 counts distinct device pseudonyms over the pilot period, deduplicated once per 180 days).
* **Not reversible** without the key, and not linkable across deployments.
* **Revocable**: rotating EVENT_PSEUDONYM_KEY makes all historical pseudonyms unlinkable to any
  new data (documented in docs/security.md).

In development the key may be empty, in which case a fixed development key is used and a warning is
logged; ``APP_ENV=prod`` refuses to start without a real key (see app/main.py).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import uuid

from .config import settings

log = logging.getLogger(__name__)
_DEV_KEY = "development-pseudonym-key-not-for-production"
_warned = False

DEVICE = "device"
SESSION = "session"
ACTOR = "actor"


def _key() -> bytes:
    global _warned
    key = settings.event_pseudonym_key
    if not key:
        if not _warned and settings.app_env not in ("test",):
            log.warning("EVENT_PSEUDONYM_KEY is empty — using the development key. Set it in .env.")
            _warned = True
        key = _DEV_KEY
    return key.encode("utf-8")


def pseudonymise(kind: str, value: str | uuid.UUID | None) -> str | None:
    """Keyed, non-reversible pseudonym for one identifier (None passes through)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digest = hmac.new(_key(), f"{kind}:{text}".encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:32]
