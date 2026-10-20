"""Internationalisation helpers: normalisation, transliteration and message catalogues.

Supported UI languages: sr (Latin or Cyrillic output), bs, me, hr, en.
`normalize_text` is the single canonical normalisation used by the red-flag router,
BM25 tokenisation and the lexical judge, so all of them see the same text.

Catalogue conventions (see `_MESSAGES`):
- every key has all five languages; `catalogue_completeness()` must return an empty dict
  and the unit tests enforce it;
- BCMS variants stay close to each other on purpose; the deliberate differences are
  hr: liječnik / nazovi / točno / ponovno, bs: ljekar / "s ljekarom" / tačno,
  sr and me: ljekar / "sa ljekarom" / tačno;
- messages that take a value use a positional placeholder (`{0}`) so that Cyrillic
  rendering leaves it intact: `t("confirm_transcript", lang, script).format(text)`;
- BCMS texts avoid letters that have no Cyrillic equivalent (q, w, x, y) and digraphs
  that span a morpheme boundary (e.g. "injekcija"), so Cyrillic rendering is exact.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.core.types import BCMS_LANGS, SUPPORTED_LANGS

# --- Serbian Cyrillic <-> Latin -------------------------------------------------------------
_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e", "ж": "ž", "з": "z",
    "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "ć", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "č", "џ": "dž", "ш": "š",
    # Montenegrin additions
    "с́": "ś", "з́": "ź",
    # letters that appear in Russian/Macedonian-keyboard typing, mapped to closest Serbian sounds
    "ё": "jo", "й": "j", "ы": "i", "э": "e", "ю": "ju", "я": "ja", "ь": "", "ъ": "", "щ": "šč",
    "ѓ": "đ", "ќ": "ć", "ѕ": "dz",
}
_LAT_TO_CYR_DIGRAPHS = {"lj": "љ", "nj": "њ", "dž": "џ", "Lj": "Љ", "Nj": "Њ", "Dž": "Џ", "LJ": "Љ", "NJ": "Њ", "DŽ": "Џ"}
_LAT_TO_CYR = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "đ": "ђ", "e": "е", "ž": "ж", "z": "з",
    "i": "и", "j": "ј", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "r": "р",
    "s": "с", "t": "т", "ć": "ћ", "u": "у", "f": "ф", "h": "х", "c": "ц", "č": "ч", "š": "ш",
}
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def cyrillic_to_latin(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        if low in _CYR_TO_LAT:
            rep = _CYR_TO_LAT[low]
            if ch.isupper() and rep:
                rep = rep[0].upper() + rep[1:]
            out.append(rep)
        else:
            out.append(ch)
    return "".join(out)


def latin_to_cyrillic(text: str) -> str:
    """Serbian Latin -> Cyrillic. Digraphs first (lj, nj, dž), then single letters."""
    for dg, cy in _LAT_TO_CYR_DIGRAPHS.items():
        text = text.replace(dg, cy)
    out = []
    for ch in text:
        low = ch.lower()
        if low in _LAT_TO_CYR:
            cy = _LAT_TO_CYR[low]
            out.append(cy.upper() if ch.isupper() else cy)
        else:
            out.append(ch)
    return "".join(out)


def detect_script(text: str) -> str:
    return "cyrillic" if _CYRILLIC_RE.search(text) else "latin"


def strip_diacritics(text: str) -> str:
    """č->c, ć->c, š->s, ž->z, đ->dj (đ is not decomposable in NFKD)."""
    text = text.replace("đ", "dj").replace("Đ", "Dj")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    """Canonical normalisation: Cyrillic->Latin, strip diacritics, lowercase, collapse whitespace.

    Punctuation is kept as spaces so tokens separate cleanly. Digits are kept (fever: 38).
    """
    text = cyrillic_to_latin(text)
    text = strip_diacritics(text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return _WS_RE.sub(" ", text).strip()


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(text))


def coerce_lang(lang: str | None, default: str = "sr") -> str:
    if not lang:
        return default
    lang = lang.lower().split("-")[0]
    if lang == "cnr":  # ISO 639-3 Montenegrin
        return "me"
    if lang == "srp":
        return "sr"
    return lang if lang in SUPPORTED_LANGS else default


def is_bcms(lang: str) -> bool:
    return lang in BCMS_LANGS


def render(text: str, lang: str, script: str = "latin") -> str:
    """Apply the requested output script. Cyrillic output is offered for sr (and me on request)."""
    if script == "cyrillic" and is_bcms(lang):
        return latin_to_cyrillic(text)
    return text


# --- message catalogue -----------------------------------------------------------------------
# Keys are stable identifiers used by the pipeline and the API. BCMS variants are kept close to
# each other on purpose (same wording is understood across sr/bs/me/hr); differences are minimal.
_MESSAGES: dict[str, dict[str, str]] = {
    "disclaimer_short": {
        "en": "This is general information, not medical advice. For your situation, talk to a clinician.",
        "sr": "Ovo su opšte informacije, a ne medicinski savjet. Za svoju situaciju razgovaraj sa ljekarom.",
        "bs": "Ovo su opće informacije, a ne medicinski savjet. Za svoju situaciju razgovaraj s ljekarom.",
        "me": "Ovo su opšte informacije, a ne medicinski savjet. Za svoju situaciju razgovaraj sa ljekarom.",
        "hr": "Ovo su opće informacije, a ne medicinski savjet. Za svoju situaciju razgovaraj s liječnikom.",
    },
    "withheld": {
        "en": "I don't have reliable, approved information to answer this. Here is where you can get help.",
        "sr": "Nemam pouzdane, provjerene informacije da odgovorim na ovo. Evo gdje možeš dobiti pomoć.",
        "bs": "Nemam pouzdane, provjerene informacije da odgovorim na ovo. Evo gdje možeš dobiti pomoć.",
        "me": "Nemam pouzdane, provjerene informacije da odgovorim na ovo. Evo gdje možeš dobiti pomoć.",
        "hr": "Nemam pouzdane, provjerene informacije da odgovorim na ovo. Evo gdje možeš dobiti pomoć.",
    },
    "redflag_emergency": {
        "en": "What you describe can be an emergency. Please call emergency services or go to the nearest emergency department now.",
        "sr": "Ovo što opisuješ može biti hitno stanje. Molim te, odmah pozovi hitnu pomoć ili idi u najbližu hitnu službu.",
        "bs": "Ovo što opisuješ može biti hitno stanje. Molim te, odmah pozovi hitnu pomoć ili idi u najbližu hitnu službu.",
        "me": "Ovo što opisuješ može biti hitno stanje. Molim te, odmah pozovi hitnu pomoć ili idi u najbližu hitnu službu.",
        "hr": "Ovo što opisuješ može biti hitno stanje. Molim te, odmah nazovi hitnu pomoć ili idi u najbližu hitnu službu.",
    },
    "redflag_support": {
        "en": "You are not alone. People who can help are listed below; you can call them now and you don't have to explain everything.",
        "sr": "Nisi sama. Ispod su ljudi koji mogu pomoći; možeš ih pozvati odmah i ne moraš ništa objašnjavati.",
        "bs": "Nisi sama. Ispod su ljudi koji mogu pomoći; možeš ih pozvati odmah i ne moraš ništa objašnjavati.",
        "me": "Nisi sama. Ispod su ljudi koji mogu pomoći; možeš ih pozvati odmah i ne moraš ništa objašnjavati.",
        "hr": "Nisi sama. Ispod su ljudi koji mogu pomoći; možeš ih nazvati odmah i ne moraš ništa objašnjavati.",
    },
    "redflag_child_protection": {
        "en": "Thank you for telling me. What you describe is not okay and it is not your fault. Please contact one of the services below; they are there to protect you.",
        "sr": "Hvala što si mi rekla. Ovo što opisuješ nije u redu i nije tvoja krivica. Molim te, javi se nekoj od službi ispod; one su tu da te zaštite.",
        "bs": "Hvala što si mi rekla. Ovo što opisuješ nije u redu i nije tvoja krivica. Molim te, javi se nekoj od službi ispod; one su tu da te zaštite.",
        "me": "Hvala što si mi rekla. Ovo što opisuješ nije u redu i nije tvoja krivica. Molim te, javi se nekoj od službi ispod; one su tu da te zaštite.",
        "hr": "Hvala što si mi rekla. Ovo što opisuješ nije u redu i nije tvoja krivica. Molim te, javi se nekoj od službi ispod; one su tu da te zaštite.",
    },
    "withheld_dose": {
        "en": "I can't advise on medicines or doses. A clinician or pharmacist who knows your situation decides that. Here is where you can get help.",
        "sr": "Ne mogu da savjetujem o lijekovima i dozama. O tome odlučuje ljekar ili farmaceut koji zna tvoju situaciju. Evo gdje možeš dobiti pomoć.",
        "bs": "Ne mogu savjetovati o lijekovima i dozama. O tome odlučuje ljekar ili farmaceut koji zna tvoju situaciju. Evo gdje možeš dobiti pomoć.",
        "me": "Ne mogu da savjetujem o lijekovima i dozama. O tome odlučuje ljekar ili farmaceut koji zna tvoju situaciju. Evo gdje možeš dobiti pomoć.",
        "hr": "Ne mogu savjetovati o lijekovima i dozama. O tome odlučuje liječnik ili ljekarnik koji zna tvoju situaciju. Evo gdje možeš dobiti pomoć.",
    },
    "withheld_diagnosis": {
        "en": "I can't tell whether you have a condition; only a clinician can, with an examination. Here is where you can get help.",
        "sr": "Ne mogu da kažem imaš li neko stanje ili bolest; to može samo ljekar pregledom. Evo gdje možeš dobiti pomoć.",
        "bs": "Ne mogu reći imaš li neko stanje ili bolest; to može samo ljekar pregledom. Evo gdje možeš dobiti pomoć.",
        "me": "Ne mogu da kažem imaš li neko stanje ili bolest; to može samo ljekar pregledom. Evo gdje možeš dobiti pomoć.",
        "hr": "Ne mogu reći imaš li neko stanje ili bolest; to može samo liječnik pregledom. Evo gdje možeš dobiti pomoć.",
    },
    "withheld_test_results": {
        "en": "I can't interpret test results; the clinician who ordered them does that. Here is where you can get help.",
        "sr": "Ne mogu da tumačim nalaze ni rezultate testova; to radi ljekar koji ih je tražio. Evo gdje možeš dobiti pomoć.",
        "bs": "Ne mogu tumačiti nalaze ni rezultate testova; to radi ljekar koji ih je tražio. Evo gdje možeš dobiti pomoć.",
        "me": "Ne mogu da tumačim nalaze ni rezultate testova; to radi ljekar koji ih je tražio. Evo gdje možeš dobiti pomoć.",
        "hr": "Ne mogu tumačiti nalaze ni rezultate testova; to radi liječnik koji ih je tražio. Evo gdje možeš dobiti pomoć.",
    },
    "withheld_manipulation": {
        "en": "I only answer from checked sources and can't change my rules. Here is where you can get help.",
        "sr": "Odgovaram samo na osnovu provjerenih izvora i ne mogu da promijenim svoja pravila. Evo gdje možeš dobiti pomoć.",
        "bs": "Odgovaram samo na osnovu provjerenih izvora i ne mogu promijeniti svoja pravila. Evo gdje možeš dobiti pomoć.",
        "me": "Odgovaram samo na osnovu provjerenih izvora i ne mogu da promijenim svoja pravila. Evo gdje možeš dobiti pomoć.",
        "hr": "Odgovaram samo na temelju provjerenih izvora i ne mogu promijeniti svoja pravila. Evo gdje možeš dobiti pomoć.",
    },
    "referral_general": {
        "en": "For your situation, a clinician can help. Nearest options:",
        "sr": "Za tvoju situaciju može pomoći ljekar. Najbliže opcije:",
        "bs": "Za tvoju situaciju može pomoći ljekar. Najbliže opcije:",
        "me": "Za tvoju situaciju može pomoći ljekar. Najbliže opcije:",
        "hr": "Za tvoju situaciju može pomoći liječnik. Najbliže opcije:",
    },
    "demo_unreviewed": {
        "en": "Demo mode: sources below are public but not yet reviewed by a clinician.",
        "sr": "Demo režim: izvori ispod su javni, ali ih ljekar još nije pregledao.",
        "bs": "Demo režim: izvori ispod su javni, ali ih ljekar još nije pregledao.",
        "me": "Demo režim: izvori ispod su javni, ali ih ljekar još nije pregledao.",
        "hr": "Demo način: izvori ispod su javni, ali ih liječnik još nije pregledao.",
    },
    # --- answer annotations --------------------------------------------------------------
    "translated_note": {
        "en": "This answer was composed from an English source and checked sentence by sentence.",
        "sr": "Ovaj odgovor je sastavljen na osnovu izvora na engleskom i provjeren rečenicu po rečenicu.",
        "bs": "Ovaj odgovor je sastavljen na osnovu izvora na engleskom i provjeren rečenicu po rečenicu.",
        "me": "Ovaj odgovor je sastavljen na osnovu izvora na engleskom i provjeren rečenicu po rečenicu.",
        "hr": "Ovaj odgovor je sastavljen na temelju izvora na engleskom i provjeren rečenicu po rečenicu.",
    },
    "minor_note": {
        "en": "You can also talk to a trusted adult about this.",
        "sr": "O ovome možeš razgovarati i sa odraslom osobom kojoj vjeruješ.",
        "bs": "O ovome možeš razgovarati i s odraslom osobom kojoj vjeruješ.",
        "me": "O ovome možeš razgovarati i sa odraslom osobom kojoj vjeruješ.",
        "hr": "O ovome možeš razgovarati i s odraslom osobom kojoj vjeruješ.",
    },
    "not_medical_advice_banner": {
        "en": "Not medical advice. MILA gives information and points you to help; it does not diagnose.",
        "sr": "Nije medicinski savjet. MILA daje informacije i upućuje na pomoć; ne postavlja dijagnozu.",
        "bs": "Nije medicinski savjet. MILA daje informacije i upućuje na pomoć; ne postavlja dijagnozu.",
        "me": "Nije medicinski savjet. MILA daje informacije i upućuje na pomoć; ne postavlja dijagnozu.",
        "hr": "Nije medicinski savjet. MILA daje informacije i upućuje na pomoć; ne postavlja dijagnozu.",
    },
    "withheld_title": {
        "en": "I don't know this - here is where to get help",
        "sr": "Ovo ne znam - evo gdje možeš dobiti pomoć",
        "bs": "Ovo ne znam - evo gdje možeš dobiti pomoć",
        "me": "Ovo ne znam - evo gdje možeš dobiti pomoć",
        "hr": "Ovo ne znam - evo gdje možeš dobiti pomoć",
    },
    "redflag_title": {
        "en": "This may be urgent",
        "sr": "Ovo može biti hitno",
        "bs": "Ovo može biti hitno",
        "me": "Ovo može biti hitno",
        "hr": "Ovo može biti hitno",
    },
    # --- referral block ---------------------------------------------------------------------
    "call_now": {
        "en": "Call now",
        "sr": "Pozovi odmah",
        "bs": "Pozovi odmah",
        "me": "Pozovi odmah",
        "hr": "Nazovi odmah",
    },
    "emergency_number_label": {
        "en": "Emergency number",
        "sr": "Broj hitne pomoći",
        "bs": "Broj hitne pomoći",
        "me": "Broj hitne pomoći",
        "hr": "Broj hitne pomoći",
    },
    "sources_label": {
        "en": "Sources",
        "sr": "Izvori",
        "bs": "Izvori",
        "me": "Izvori",
        "hr": "Izvori",
    },
    "confidence_label": {
        "en": "Confidence",
        "sr": "Pouzdanost",
        "bs": "Pouzdanost",
        "me": "Pouzdanost",
        "hr": "Pouzdanost",
    },
    # --- voice and input controls -----------------------------------------------------------
    "listen": {
        "en": "Listen",
        "sr": "Poslušaj",
        "bs": "Poslušaj",
        "me": "Poslušaj",
        "hr": "Poslušaj",
    },
    "ask_by_voice": {
        "en": "Ask by voice",
        "sr": "Pitaj glasom",
        "bs": "Pitaj glasom",
        "me": "Pitaj glasom",
        "hr": "Pitaj glasom",
    },
    "type_question": {
        "en": "Type your question",
        "sr": "Upiši pitanje",
        "bs": "Upiši pitanje",
        "me": "Upiši pitanje",
        "hr": "Upiši pitanje",
    },
    "confirm_transcript": {
        "en": "I heard: \u201c{0}\u201d Is this right?",
        "sr": "Čula sam: \u201e{0}\u201c Je li tačno?",
        "bs": "Čula sam: \u201e{0}\u201c Je li tačno?",
        "me": "Čula sam: \u201e{0}\u201c Je li tačno?",
        "hr": "Čula sam: \u201e{0}\u201c Je li točno?",
    },
    "yes": {"en": "Yes", "sr": "Da", "bs": "Da", "me": "Da", "hr": "Da"},
    "no": {"en": "No", "sr": "Ne", "bs": "Ne", "me": "Ne", "hr": "Ne"},
    "try_again": {
        "en": "Try again",
        "sr": "Pokušaj ponovo",
        "bs": "Pokušaj ponovo",
        "me": "Pokušaj ponovo",
        "hr": "Pokušaj ponovno",
    },
    # --- consent and settings ---------------------------------------------------------------
    "delete_my_data": {
        "en": "Delete my data",
        "sr": "Obriši moje podatke",
        "bs": "Obriši moje podatke",
        "me": "Obriši moje podatke",
        "hr": "Obriši moje podatke",
    },
    "save_my_questions": {
        "en": "Save my questions",
        "sr": "Sačuvaj moja pitanja",
        "bs": "Sačuvaj moja pitanja",
        "me": "Sačuvaj moja pitanja",
        "hr": "Spremi moja pitanja",
    },
    "low_bandwidth_mode": {
        "en": "Low-bandwidth mode",
        "sr": "Režim za slabu vezu",
        "bs": "Režim za slabu vezu",
        "me": "Režim za slabu vezu",
        "hr": "Način rada za slabu vezu",
    },
    "under_18_question": {
        "en": "Are you under 18?",
        "sr": "Imaš li manje od 18 godina?",
        "bs": "Imaš li manje od 18 godina?",
        "me": "Imaš li manje od 18 godina?",
        "hr": "Imaš li manje od 18 godina?",
    },
}


def t(key: str, lang: str = "sr", script: str = "latin") -> str:
    lang = coerce_lang(lang)
    table = _MESSAGES.get(key)
    if table is None:
        raise KeyError(f"unknown i18n key: {key}")
    text = table.get(lang) or table.get("sr") or table["en"]
    return render(text, lang, script)


def available_keys() -> list[str]:
    return sorted(_MESSAGES)


def register_messages(key: str, translations: dict[str, str]) -> None:
    """Allow other modules (consent, referral) to extend the catalogue at import time."""
    _MESSAGES.setdefault(key, {}).update(translations)


# Native names of the supported UI languages (Latin script; `language_name` renders Cyrillic
# on request for the BCMS languages).
_LANGUAGE_NAMES: dict[str, str] = {
    "sr": "srpski",
    "bs": "bosanski",
    "me": "crnogorski",
    "hr": "hrvatski",
    "en": "English",
}


def language_name(lang: str | None, script: str = "latin") -> str:
    """Native (endonym) name of a supported language, e.g. ``"sr" -> "srpski"``.

    Unknown or empty codes are coerced the same way as everywhere else (default: sr).
    """
    lang = coerce_lang(lang)
    return render(_LANGUAGE_NAMES[lang], lang, script)


def catalogue_completeness(keys: Iterable[str] | None = None) -> dict[str, list[str]]:
    """Return ``{key: [languages missing or empty]}`` for the catalogue; empty when complete.

    Checks every key in `_MESSAGES` (including keys added through `register_messages`)
    against `SUPPORTED_LANGS`, or only `keys` when given. The unit tests require an empty
    result, so a key can never ship with a silent fallback to Serbian.
    """
    wanted = list(keys) if keys is not None else sorted(_MESSAGES)
    missing: dict[str, list[str]] = {}
    for key in wanted:
        table = _MESSAGES.get(key, {})
        gaps = [lang for lang in SUPPORTED_LANGS if not (table.get(lang) or "").strip()]
        if gaps:
            missing[key] = gaps
    return missing
