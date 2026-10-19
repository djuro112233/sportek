"""Event logging (aggregate-only) and lightweight topic classification."""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app.core.i18n import normalize_text
from app.core.types import TOPIC_CLASSES
from app.models import Event

_FORBIDDEN_PAYLOAD_KEYS = {"text", "question", "transcript", "audio", "ip", "email", "phone", "name"}

# Keyword seeds per topic class, in normalised (diacritic-free, Latin) form. Order matters: first hit wins
# except that more specific classes are listed before generic ones.
_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "antenatal_care": ("prenatal", "antenatal", "pregled u trudnoci", "kontrola u trudnoci", "ultrazvuk", "folna", "folic", "anc visit"),
    "postnatal": ("postnatal", "postpartum", "posle porodaja", "poslije porodaja", "nakon porodaja", "dojenje", "breastfeed", "babinje", "lohije", "newborn", "novorodjen"),
    "contraception": ("kontracep", "contracep", "pilul", "pill", "kondom", "condom", "spiral", "iud", "implant", "injekcij", "injection", "jutro poslije", "morning after", "emergency contraception", "hitna kontracepcija", "zastita od trudnoce", "prekid trudnoce", "abortion", "abortus"),
    "pregnancy": ("trudn", "pregnan", "zacece", "conceiv", "ovulac", "ovulat", "plodni dani", "fertile", "test na trudnocu", "pregnancy test", "beba", "fetus", "porodjaj", "porodaj", "labour", "labor"),
    "menstruation": ("menstru", "period", "ciklus", "cycle", "pms", "krvarenje izmedju", "spotting", "ulosci", "tampon", "pad"),
    "sti": ("sti", "std", "polno prenosiv", "spolno prenosiv", "sexually transmitted", "hiv", "hpv", "klamidij", "chlamyd", "gonore", "sifilis", "syphilis", "herpes", "vaginit", "iscjedak", "iscedak", "discharge", "infekcij", "infection"),
    "mental_health": ("depres", "anksio", "anxie", "tuzna", "tuzno", "sad", "stres", "stress", "panik", "panic", "mental", "psihic", "psiholog", "bebi bluz", "baby blues"),
    "adolescent": ("tinejdz", "teen", "adolescen", "pubert", "prvi put", "first time", "maloljetn", "maloletn", "minor"),
}


def classify_topic(text: str) -> str:
    norm = normalize_text(text)
    for topic, keys in _TOPIC_KEYWORDS.items():
        if any(k in norm for k in keys):
            return topic
    return "other"


def log_event(
    db: DbSession,
    *,
    type: str,
    session_id: str | None,
    lang: str = "",
    topic_class: str = "",
    outcome: str = "",
    latency_ms: int | None = None,
    support_ratio: float | None = None,
    redflag_category: str = "",
    input_mode: str = "text",
    payload: dict | None = None,
) -> Event:
    """Persist an aggregate-only event. Raises if a payload key could carry user content."""
    payload = dict(payload or {})
    bad = _FORBIDDEN_PAYLOAD_KEYS.intersection(k.lower() for k in payload)
    if bad:
        raise ValueError(f"event payload must not contain user content keys: {sorted(bad)}")
    if topic_class and topic_class not in TOPIC_CLASSES:
        topic_class = "other"
    ev = Event(
        session_id=session_id,
        type=type,
        lang=lang,
        topic_class=topic_class,
        outcome=outcome,
        latency_ms=latency_ms,
        support_ratio=support_ratio,
        redflag_category=redflag_category,
        input_mode=input_mode,
        payload=payload,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev
