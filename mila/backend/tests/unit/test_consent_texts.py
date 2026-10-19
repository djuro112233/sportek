"""Unit tests for app.core.consent_texts: plain-language consent copy in five languages."""

from __future__ import annotations

import re

import pytest

from app.core.consent_texts import (
    ADULT_ITEM_KEYS,
    CONSENT_KEYS,
    MAX_SPOKEN_WORDS,
    MAX_WRITTEN_WORDS,
    MINOR_ITEM_KEY,
    MINOR_ITEM_KEYS,
    ConsentText,
    build_consent_text,
    item_keys,
    word_count,
)
from app.core.i18n import catalogue_completeness, cyrillic_to_latin, t
from app.core.types import BCMS_LANGS, SUPPORTED_LANGS

LATIN_LETTER_RE = re.compile(r"[A-Za-zčćšžđČĆŠŽĐ]")
NO_CYRILLIC_EQUIVALENT_RE = re.compile(r"[qwxyQWXY]")
VARIANTS = [(lang, is_minor) for lang in SUPPORTED_LANGS for is_minor in (False, True)]


# --- catalogue ---------------------------------------------------------------------------------
def test_consent_keys_are_registered_with_all_five_languages():
    assert CONSENT_KEYS
    assert all(key.startswith("consent_") for key in CONSENT_KEYS)
    assert catalogue_completeness(keys=CONSENT_KEYS) == {}
    assert catalogue_completeness() == {}


def test_every_consent_key_renders_through_t():
    for key in CONSENT_KEYS:
        for lang in SUPPORTED_LANGS:
            assert t(key, lang).strip()


# --- structure ---------------------------------------------------------------------------------
def test_item_keys_helper():
    assert item_keys(False) == ADULT_ITEM_KEYS
    assert item_keys(True) == MINOR_ITEM_KEYS
    assert MINOR_ITEM_KEYS == (*ADULT_ITEM_KEYS, MINOR_ITEM_KEY)


def test_adult_items_cover_everything_the_user_must_know():
    assert ADULT_ITEM_KEYS == (
        "what_mila_is",
        "nothing_stored",
        "counts_only",
        "save_questions",
        "delete",
        "emergency",
    )


@pytest.mark.parametrize(("lang", "is_minor"), VARIANTS)
def test_build_returns_items_in_order_and_text_is_items_joined(lang: str, is_minor: bool):
    ct = build_consent_text(lang, "latin", is_minor, version="2026-10-01")
    assert isinstance(ct, ConsentText)
    assert [item.key for item in ct.items] == list(item_keys(is_minor))
    assert ct.text == " ".join(item.text for item in ct.items)
    assert ct.lang == lang and ct.script == "latin" and ct.version == "2026-10-01"


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_minor_variant_only_adds_the_trusted_adult_item(lang: str):
    adult = build_consent_text(lang, "latin", False, version="v")
    minor = build_consent_text(lang, "latin", True, version="v")
    assert minor.items[:-1] == adult.items
    assert minor.items[-1].key == MINOR_ITEM_KEY
    assert "18" in minor.items[-1].text
    assert minor.spoken_text != adult.spoken_text


# --- length limits -----------------------------------------------------------------------------
def test_word_count_helper():
    assert word_count("") == 0
    assert word_count("  jedna   dvije\ntri ") == 3


@pytest.mark.parametrize(("lang", "is_minor"), VARIANTS)
def test_written_text_within_limit(lang: str, is_minor: bool):
    ct = build_consent_text(lang, "latin", is_minor, version="v")
    assert 0 < word_count(ct.text) <= MAX_WRITTEN_WORDS


@pytest.mark.parametrize(("lang", "is_minor"), VARIANTS)
def test_spoken_text_within_limit(lang: str, is_minor: bool):
    ct = build_consent_text(lang, "latin", is_minor, version="v")
    assert 0 < word_count(ct.spoken_text) <= MAX_SPOKEN_WORDS
    assert word_count(ct.spoken_text) < word_count(ct.text)


# --- content -----------------------------------------------------------------------------------
@pytest.mark.parametrize(("lang", "is_minor"), VARIANTS)
def test_required_facts_are_present(lang: str, is_minor: bool):
    ct = build_consent_text(lang, "latin", is_minor, version="v")
    assert "124" in ct.text and "124" in ct.spoken_text
    assert "5" in ct.text  # never fewer than 5 people
    assert "MILA" in ct.text and "MILA" in ct.spoken_text


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_second_person_singular(lang: str):
    ct = build_consent_text(lang, "latin", True, version="v")
    if lang == "en":
        assert " you " in f" {ct.text.lower()} "
    else:
        assert "možeš" in ct.text and "možeš" in ct.spoken_text


def test_regional_wording_differences():
    assert "liječnik" in build_consent_text("hr", "latin", False, version="v").text
    assert "nazovi 124" in build_consent_text("hr", "latin", False, version="v").text
    assert "spremi moja pitanja" in build_consent_text("hr", "latin", False, version="v").text
    assert "netko" in build_consent_text("hr", "latin", True, version="v").text
    for lang in ("sr", "bs", "me"):
        text = build_consent_text(lang, "latin", True, version="v").text
        assert "ljekar" in text and "pozovi 124" in text and "sačuvaj moja pitanja" in text
    assert "sa odraslom" in build_consent_text("sr", "latin", True, version="v").text
    assert "s odraslom" in build_consent_text("bs", "latin", True, version="v").text


# --- scripts -----------------------------------------------------------------------------------
@pytest.mark.parametrize("lang", BCMS_LANGS)
def test_bcms_copy_avoids_letters_without_cyrillic_equivalent(lang: str):
    for is_minor in (False, True):
        ct = build_consent_text(lang, "latin", is_minor, version="v")
        assert not NO_CYRILLIC_EQUIVALENT_RE.search(ct.text + ct.spoken_text)


@pytest.mark.parametrize("lang", BCMS_LANGS)
@pytest.mark.parametrize("is_minor", [False, True])
def test_cyrillic_rendering_is_exact(lang: str, is_minor: bool):
    latin = build_consent_text(lang, "latin", is_minor, version="v")
    cyrillic = build_consent_text(lang, "cyrillic", is_minor, version="v")
    for text in (cyrillic.text, cyrillic.spoken_text, *(i.text for i in cyrillic.items)):
        assert not LATIN_LETTER_RE.search(text), text
    assert cyrillic_to_latin(cyrillic.text) == latin.text
    assert cyrillic_to_latin(cyrillic.spoken_text) == latin.spoken_text
    assert [i.key for i in cyrillic.items] == [i.key for i in latin.items]
    assert cyrillic.script == "cyrillic"


def test_english_is_unchanged_by_the_cyrillic_script():
    latin = build_consent_text("en", "latin", False, version="v")
    cyrillic = build_consent_text("en", "cyrillic", False, version="v")
    assert cyrillic.text == latin.text and cyrillic.spoken_text == latin.spoken_text
    assert cyrillic.script == "cyrillic"


def test_version_is_passed_through_untouched():
    assert build_consent_text("sr", "cyrillic", False, version="2027-01-01").version == "2027-01-01"
