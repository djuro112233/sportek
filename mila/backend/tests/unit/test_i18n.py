"""Unit tests for app.core.i18n: transliteration, normalisation, language coercion and the catalogue."""

from __future__ import annotations

import re

import pytest

from app.core.i18n import (
    available_keys,
    catalogue_completeness,
    coerce_lang,
    cyrillic_to_latin,
    detect_script,
    is_bcms,
    language_name,
    latin_to_cyrillic,
    normalize_text,
    register_messages,
    render,
    strip_diacritics,
    t,
    tokenize,
)
from app.core.types import BCMS_LANGS, SUPPORTED_LANGS

# Every key the brief requires, plus the keys that were already in the catalogue.
REQUIRED_KEYS = (
    "disclaimer_short",
    "withheld",
    "redflag_emergency",
    "redflag_support",
    "redflag_child_protection",
    "referral_general",
    "demo_unreviewed",
    "translated_note",
    "minor_note",
    "call_now",
    "emergency_number_label",
    "sources_label",
    "confidence_label",
    "listen",
    "ask_by_voice",
    "type_question",
    "confirm_transcript",
    "yes",
    "no",
    "try_again",
    "delete_my_data",
    "save_my_questions",
    "low_bandwidth_mode",
    "not_medical_advice_banner",
    "withheld_title",
    "redflag_title",
    "under_18_question",
)

LATIN_LETTER_RE = re.compile(r"[A-Za-zčćšžđČĆŠŽĐ]")

PARAGRAPH_LATIN = (
    "Đurđevdan je praznik. Ljiljana i Njegoš piju džem od šljiva, a Žana čita knjigu o Đakovici. "
    "Dječak Dženan nosi đinđuve; njegova sestra Ljubica pjeva. Život je lijep u Žabljaku."
)
PARAGRAPH_CYRILLIC = (
    "Ђурђевдан је празник. Љиљана и Његош пију џем од шљива, а Жана чита књигу о Ђаковици. "
    "Дјечак Џенан носи ђинђуве; његова сестра Љубица пјева. Живот је лијеп у Жабљаку."
)


# --- transliteration ---------------------------------------------------------------------------
def test_latin_to_cyrillic_paragraph_matches_reference():
    assert latin_to_cyrillic(PARAGRAPH_LATIN) == PARAGRAPH_CYRILLIC


def test_cyrillic_to_latin_paragraph_matches_reference():
    assert cyrillic_to_latin(PARAGRAPH_CYRILLIC) == PARAGRAPH_LATIN


def test_round_trip_latin_cyrillic_latin_is_identity():
    assert cyrillic_to_latin(latin_to_cyrillic(PARAGRAPH_LATIN)) == PARAGRAPH_LATIN


def test_round_trip_cyrillic_latin_cyrillic_is_identity():
    assert latin_to_cyrillic(cyrillic_to_latin(PARAGRAPH_CYRILLIC)) == PARAGRAPH_CYRILLIC


@pytest.mark.parametrize(
    ("latin", "cyrillic"),
    [("đ", "ђ"), ("dž", "џ"), ("lj", "љ"), ("nj", "њ"), ("Đ", "Ђ"), ("Ž", "Ж"), ("Lj", "Љ"), ("Dž", "Џ"), ("Nj", "Њ")],
)
def test_special_letters_and_digraphs(latin: str, cyrillic: str):
    assert latin_to_cyrillic(latin) == cyrillic
    assert cyrillic_to_latin(cyrillic) == latin


def test_transliteration_keeps_digits_punctuation_and_placeholders():
    text = "Temperatura 38,5° - {0} ({1})!"
    assert latin_to_cyrillic(text) == "Температура 38,5° - {0} ({1})!"
    assert cyrillic_to_latin("38,5 - {0}") == "38,5 - {0}"


def test_cyrillic_to_latin_maps_foreign_cyrillic_letters_to_closest_sounds():
    assert cyrillic_to_latin("Юля") == "Julja"
    assert cyrillic_to_latin("ёлка") == "jolka"


# --- normalisation -----------------------------------------------------------------------------
def test_normalize_text_on_cyrillic_with_digits():
    assert normalize_text("Температура 38.5 и крварење у 12. недјељи") == "temperatura 38 5 i krvarenje u 12 nedjelji"


def test_normalize_text_gives_same_result_for_both_scripts():
    assert normalize_text("Krvarenje u trudnoći") == normalize_text("Крварење у трудноћи") == "krvarenje u trudnoci"


def test_normalize_text_collapses_whitespace_and_punctuation():
    assert normalize_text("  Boli   me,   stomak!!  ") == "boli me stomak"


def test_tokenize_returns_normalised_tokens():
    assert tokenize("Крварење, 38°C!") == ["krvarenje", "38", "c"]


def test_strip_diacritics():
    assert strip_diacritics("čćšžđ ČĆŠŽĐ") == "ccszdj CCSZDj"
    assert strip_diacritics("liječnik") == "lijecnik"


# --- language and script detection ------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [("sr-Latn", "sr"), ("cnr", "me"), ("SR", "sr"), (None, "sr"), ("xx", "sr"), ("", "sr"), ("srp", "sr"),
     ("hr-HR", "hr"), ("bs", "bs"), ("en-US", "en"), ("me", "me")],
)
def test_coerce_lang(value: str | None, expected: str):
    assert coerce_lang(value) == expected


def test_coerce_lang_honours_custom_default():
    assert coerce_lang("xx", default="en") == "en"
    assert coerce_lang(None, default="hr") == "hr"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Крварење", "cyrillic"), ("Krvarenje", "latin"), ("mixed Ћирилица", "cyrillic"), ("38.5", "latin"), ("", "latin")],
)
def test_detect_script(text: str, expected: str):
    assert detect_script(text) == expected


def test_is_bcms():
    assert all(is_bcms(lang) for lang in BCMS_LANGS)
    assert not is_bcms("en")


# --- render ------------------------------------------------------------------------------------
def test_render_applies_cyrillic_only_for_bcms_languages():
    assert render("Pitaj glasom", "sr", "cyrillic") == "Питај гласом"
    assert render("Pitaj glasom", "sr", "latin") == "Pitaj glasom"
    assert render("Ask by voice", "en", "cyrillic") == "Ask by voice"


# --- catalogue ---------------------------------------------------------------------------------
def test_all_required_keys_are_present():
    keys = set(available_keys())
    missing = [k for k in REQUIRED_KEYS if k not in keys]
    assert missing == []


def test_catalogue_completeness_is_empty():
    assert catalogue_completeness() == {}


def test_catalogue_completeness_reports_gaps_for_registered_partial_key():
    key = "_test_partial_key"
    register_messages(key, {"en": "only english"})
    try:
        gaps = catalogue_completeness()
        assert gaps == {key: ["sr", "bs", "hr", "me"]}
        assert catalogue_completeness(keys=REQUIRED_KEYS) == {}
    finally:
        from app.core import i18n as _mod

        _mod._MESSAGES.pop(key, None)
    assert catalogue_completeness() == {}


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_every_key_has_non_empty_text_in_every_language(key: str):
    for lang in SUPPORTED_LANGS:
        assert t(key, lang).strip(), f"{key}/{lang} is empty"


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_every_key_renders_in_cyrillic_without_latin_letters(key: str):
    for lang in BCMS_LANGS:
        rendered = t(key, lang, "cyrillic")
        leftovers = LATIN_LETTER_RE.findall(rendered)
        assert leftovers == [], f"{key}/{lang}: {rendered!r} still contains {leftovers}"


def test_t_falls_back_to_serbian_for_unknown_language():
    assert t("withheld", "xx") == t("withheld", "sr")
    assert t("call_now", None) == t("call_now", "sr")


def test_t_raises_for_unknown_key():
    with pytest.raises(KeyError):
        t("no_such_key", "sr")


def test_confirm_transcript_placeholder_survives_cyrillic_rendering():
    for lang in SUPPORTED_LANGS:
        for script in ("latin", "cyrillic"):
            template = t("confirm_transcript", lang, script)
            assert "{0}" in template
            assert "boli me stomak" in template.format("boli me stomak")


def test_regional_wording_differences():
    assert "liječnikom" in t("disclaimer_short", "hr")
    assert "s ljekarom" in t("disclaimer_short", "bs")
    assert "sa ljekarom" in t("disclaimer_short", "sr")
    assert "sa ljekarom" in t("disclaimer_short", "me")
    assert t("call_now", "hr") == "Nazovi odmah"
    assert t("call_now", "sr") == "Pozovi odmah"
    assert "točno" in t("confirm_transcript", "hr")
    assert "tačno" in t("confirm_transcript", "bs")


def test_under_18_question_and_titles_wording():
    assert t("under_18_question", "en") == "Are you under 18?"
    assert t("withheld_title", "en").startswith("I don't know this")
    assert "18" in t("under_18_question", "sr", "cyrillic")
    assert t("yes", "sr") == "Da" and t("no", "sr") == "Ne"


def test_register_messages_extends_and_updates_catalogue():
    key = "_test_registered"
    try:
        register_messages(key, {lang: f"text-{lang}" for lang in SUPPORTED_LANGS})
        assert t(key, "hr") == "text-hr"
        register_messages(key, {"hr": "updated"})
        assert t(key, "hr") == "updated"
        assert t(key, "sr") == "text-sr"
    finally:
        from app.core import i18n as _mod

        _mod._MESSAGES.pop(key, None)


# --- language names ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("lang", "expected"),
    [("sr", "srpski"), ("bs", "bosanski"), ("me", "crnogorski"), ("hr", "hrvatski"), ("en", "English"), ("cnr", "crnogorski")],
)
def test_language_name(lang: str, expected: str):
    assert language_name(lang) == expected


def test_language_name_cyrillic_and_fallback():
    assert language_name("sr", "cyrillic") == "српски"
    assert language_name("en", "cyrillic") == "English"
    assert language_name(None) == "srpski"
    assert language_name("xx") == "srpski"
