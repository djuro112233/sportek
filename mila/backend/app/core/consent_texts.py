"""Plain-language consent copy, shown and spoken before the first question.

The copy is written for a 15-year-old reader in the second person singular, in sr, bs, me,
hr and en. It is registered in the shared i18n catalogue under ``consent_*`` keys at import
time, so Cyrillic rendering goes through :func:`app.core.i18n.render` like every other
message and :func:`app.core.i18n.catalogue_completeness` keeps enforcing that every key has
all five languages.

Writing rules (checked by the unit tests):

- the written text (all items joined) stays under :data:`MAX_WRITTEN_WORDS`;
- the spoken text (read aloud by TTS) stays under :data:`MAX_SPOKEN_WORDS`;
- BCMS copy avoids the letters q, w, x and y and digraphs that span a morpheme boundary,
  so the Cyrillic rendering is exact;
- the minor variant adds one item (trusted adult, child-protection help) and uses a shorter
  spoken text; nothing else changes between the two variants.

The consent *version* is not part of the copy: it comes from ``Settings.consent_version``
and must change whenever this copy changes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.i18n import register_messages, t

MAX_WRITTEN_WORDS = 120
MAX_SPOKEN_WORDS = 45

# Item keys in display order. ``trusted_adult`` is appended only for minors.
ADULT_ITEM_KEYS: tuple[str, ...] = (
    "what_mila_is",
    "nothing_stored",
    "counts_only",
    "save_questions",
    "delete",
    "emergency",
)
MINOR_ITEM_KEY = "trusted_adult"
MINOR_ITEM_KEYS: tuple[str, ...] = (*ADULT_ITEM_KEYS, MINOR_ITEM_KEY)

_ITEM_PREFIX = "consent_item_"
SPOKEN_KEY = "consent_spoken"
SPOKEN_MINOR_KEY = "consent_spoken_minor"

_LQ = "„"  # „ opening quote used in BCMS
_RQ = "“"  # “ closing quote in BCMS / opening quote in English
_ERQ = "”"  # ” closing quote in English


def _bcms(sr: str, *, hr: str | None = None, bs: str | None = None) -> dict[str, str]:
    """Build the four BCMS variants from the Serbian text.

    ``me`` always equals ``sr``; ``bs`` and ``hr`` default to ``sr`` unless given. Keeping
    the variants side by side makes the deliberate regional differences easy to review
    (ljekar / liječnik, pozovi / nazovi, sačuvaj / spremi, neko / netko, ponovo / ponovno).
    """
    return {"sr": sr, "me": sr, "bs": bs if bs is not None else sr, "hr": hr if hr is not None else sr}


_MESSAGES: dict[str, dict[str, str]] = {
    f"{_ITEM_PREFIX}what_mila_is": {
        "en": "MILA gives you health information and shows you where to get help. MILA is not a doctor and does not make a diagnosis.",
        **_bcms(
            "MILA ti daje informacije o zdravlju i pokazuje gdje možeš dobiti pomoć. MILA nije ljekar i ne postavlja dijagnozu.",
            hr="MILA ti daje informacije o zdravlju i pokazuje gdje možeš dobiti pomoć. MILA nije liječnik i ne postavlja dijagnozu.",
        ),
    },
    f"{_ITEM_PREFIX}nothing_stored": {
        "en": "Unless you choose otherwise, nothing about you is stored: no name, no phone number, no voice and no questions.",
        **_bcms(
            "Ako sama ne odlučiš drugačije, ništa o tebi se ne čuva: ni ime, ni broj telefona, ni glas, ni pitanja.",
        ),
    },
    f"{_ITEM_PREFIX}counts_only": {
        "en": "MILA only counts how many people ask about what, with no names and never for fewer than 5 people.",
        **_bcms(
            "MILA samo broji koliko ljudi pita o čemu, bez imena i nikad za manje od 5 osoba.",
        ),
    },
    f"{_ITEM_PREFIX}save_questions": {
        "en": f"You can switch {_RQ}save my questions{_ERQ} on, and off again, whenever you want.",
        **_bcms(
            f"Opciju {_LQ}sačuvaj moja pitanja{_RQ} možeš uključiti, i ponovo isključiti, kad god želiš.",
            hr=f"Opciju {_LQ}spremi moja pitanja{_RQ} možeš uključiti, i ponovno isključiti, kad god želiš.",
        ),
    },
    f"{_ITEM_PREFIX}delete": {
        "en": f"You can delete everything with {_RQ}Delete my data{_ERQ}.",
        **_bcms(f"Sve možeš obrisati pomoću {_LQ}Obriši moje podatke{_RQ}."),
    },
    f"{_ITEM_PREFIX}emergency": {
        "en": "In an emergency, call 124.",
        **_bcms("U hitnom slučaju pozovi 124.", hr="U hitnom slučaju nazovi 124."),
    },
    f"{_ITEM_PREFIX}{MINOR_ITEM_KEY}": {
        "en": "If you are under 18, you can also talk to an adult you trust. If someone is hurting you, MILA will point you to child protection help.",
        **_bcms(
            "Ako imaš manje od 18 godina, možeš razgovarati i sa odraslom osobom kojoj vjeruješ. Ako ti neko nanosi zlo, MILA će te uputiti na pomoć za zaštitu djece.",
            bs="Ako imaš manje od 18 godina, možeš razgovarati i s odraslom osobom kojoj vjeruješ. Ako ti neko nanosi zlo, MILA će te uputiti na pomoć za zaštitu djece.",
            hr="Ako imaš manje od 18 godina, možeš razgovarati i s odraslom osobom kojoj vjeruješ. Ako ti netko nanosi zlo, MILA će te uputiti na pomoć za zaštitu djece.",
        ),
    },
    SPOKEN_KEY: {
        "en": (
            "I am MILA. I give health information and show where to get help. I am not a doctor. "
            f"Nothing about you is stored unless you turn on {_RQ}save my questions{_ERQ}. "
            "You can delete everything whenever you want. In an emergency, call 124."
        ),
        **_bcms(
            "Ja sam MILA. Dajem informacije o zdravlju i pokazujem gdje možeš dobiti pomoć. Nisam ljekar. "
            f"Ništa o tebi se ne čuva, osim ako sama ne uključiš {_LQ}sačuvaj moja pitanja{_RQ}. "
            "Sve možeš obrisati kad god želiš. U hitnom slučaju pozovi 124.",
            hr=(
                "Ja sam MILA. Dajem informacije o zdravlju i pokazujem gdje možeš dobiti pomoć. Nisam liječnik. "
                f"Ništa o tebi se ne čuva, osim ako sama ne uključiš {_LQ}spremi moja pitanja{_RQ}. "
                "Sve možeš obrisati kad god želiš. U hitnom slučaju nazovi 124."
            ),
        ),
    },
    SPOKEN_MINOR_KEY: {
        "en": (
            "I am MILA. I give health information and show where to get help. I am not a doctor. "
            "Nothing about you is stored unless you choose it. You can delete everything. "
            "In an emergency, call 124. You can also talk to an adult you trust."
        ),
        **_bcms(
            "Ja sam MILA. Dajem informacije o zdravlju i pokazujem gdje možeš dobiti pomoć. Nisam ljekar. "
            "Ništa o tebi se ne čuva, osim ako to sama ne odlučiš. Sve možeš obrisati. "
            "U hitnom slučaju pozovi 124. Možeš razgovarati i sa odraslom osobom kojoj vjeruješ.",
            bs=(
                "Ja sam MILA. Dajem informacije o zdravlju i pokazujem gdje možeš dobiti pomoć. Nisam ljekar. "
                "Ništa o tebi se ne čuva, osim ako to sama ne odlučiš. Sve možeš obrisati. "
                "U hitnom slučaju pozovi 124. Možeš razgovarati i s odraslom osobom kojoj vjeruješ."
            ),
            hr=(
                "Ja sam MILA. Dajem informacije o zdravlju i pokazujem gdje možeš dobiti pomoć. Nisam liječnik. "
                "Ništa o tebi se ne čuva, osim ako to sama ne odlučiš. Sve možeš obrisati. "
                "U hitnom slučaju nazovi 124. Možeš razgovarati i s odraslom osobom kojoj vjeruješ."
            ),
        ),
    },
}

CONSENT_KEYS: tuple[str, ...] = tuple(_MESSAGES)

for _key, _translations in _MESSAGES.items():
    register_messages(_key, _translations)


def item_keys(is_minor: bool) -> tuple[str, ...]:
    """Item keys shown for an adult or a minor, in display order."""
    return MINOR_ITEM_KEYS if is_minor else ADULT_ITEM_KEYS


def word_count(text: str) -> int:
    """Whitespace-separated word count; the unit the length limits are expressed in."""
    return len(text.split())


class ConsentItem(BaseModel):
    key: str
    text: str


class ConsentText(BaseModel):
    """What ``GET /api/consent/text`` returns and what the UI shows and reads aloud."""

    version: str
    text: str
    spoken_text: str
    items: list[ConsentItem] = Field(default_factory=list)
    lang: str
    script: str


def build_consent_text(lang: str, script: str, is_minor: bool, *, version: str) -> ConsentText:
    """Assemble the consent screen for one language, script and audience.

    ``text`` is the items joined by a space; ``spoken_text`` is the shorter version read by
    TTS. Cyrillic rendering is applied by :func:`app.core.i18n.t` (through ``render``), so
    English and the Latin script come back unchanged.
    """
    items = [
        ConsentItem(key=key, text=t(f"{_ITEM_PREFIX}{key}", lang, script)) for key in item_keys(is_minor)
    ]
    spoken = t(SPOKEN_MINOR_KEY if is_minor else SPOKEN_KEY, lang, script)
    return ConsentText(
        version=version,
        text=" ".join(item.text for item in items),
        spoken_text=spoken,
        items=items,
        lang=lang,
        script=script,
    )
