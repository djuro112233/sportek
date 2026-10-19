"""Unit tests for app.core.redflags: matcher primitives, per-category rules, classifier, eval datasets."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import pytest

from app.config import get_settings
from app.core import redflag_rules as rules
from app.core.i18n import catalogue_completeness, normalize_text
from app.core.redflags import (
    CLASSIFIER,
    NONE_LABEL,
    CharNgramNaiveBayes,
    RedFlagRouter,
    TermMatcher,
    char_ngrams,
    edit_budget,
    get_router,
    levenshtein,
    train_classifier,
)
from app.core.types import RED_FLAG_CATEGORIES

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO_ROOT / "eval"
VARIANTS = {"plain", "typo", "dialect", "cyrillic", "mixed", "no_diacritics", "colloquial"}


@pytest.fixture(scope="module")
def router() -> RedFlagRouter:
    return RedFlagRouter()


def _rows(name: str) -> list[dict]:
    path = EVAL_DIR / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _hits(terms: tuple[str, ...], text: str) -> list[tuple[str, int, int]]:
    matcher = TermMatcher(terms)
    return [(h.term, h.start, h.end) for h in matcher.find_all(normalize_text(text).split(), {})]


# --- matcher primitives ------------------------------------------------------------------------
def test_edit_budget_thresholds():
    assert [edit_budget(n) for n in (3, 4, 5, 8, 9, 12)] == [0, 0, 1, 1, 2, 2]


def test_levenshtein_with_cutoff():
    assert levenshtein("krvarim", "krvarm", 2) == 1
    assert levenshtein("temperatura", "temperaturu", 1) == 1
    assert levenshtein("abcdef", "xyzuvw", 1) == 2  # cutoff + 1, not the true distance 6
    assert levenshtein("same", "same", 0) == 0


def test_term_matcher_fuzzy_prefix_exact_and_phrase():
    hits = _hits(
        ("krvar*", "=rodila", "temperatura", "ne mrda"), "krvrim rodila radila temperaturu nemrda ne mrda"
    )
    assert ("krvar*", 0, 1) in hits  # one deletion inside the stem
    assert ("=rodila", 1, 2) in hits
    assert all(not (term == "=rodila" and start == 2) for term, start, _ in hits)  # radila is not rodila
    assert ("temperatura", 3, 4) in hits  # inflection = one substitution
    assert ("ne mrda", 4, 5) in hits  # missing space
    assert ("ne mrda", 5, 7) in hits


def test_term_matcher_glued_phrase_must_match_exactly():
    assert _hits(("preti da",), "prekida") == []
    assert _hits(("temperatura je",), "temperaturaje") == [("temperatura je", 0, 1)]
    assert _hits(("temperatura je",), "temperatura u trudnoci") == []


def test_fuzzy_exact_only_tokens_block_benign_neighbours():
    assert _hits(rules.PREGNANCY_CTX, "trudim se da jedem zdravo") == []
    assert set(_hits(rules.PREGNANCY_CTX, "trudna sam")) == {("trudna", 0, 1), ("trudn*", 0, 1)}
    assert _hits(("swell*",), "smells bad") == []


def test_short_words_are_never_fuzzy():
    assert _hits(("=krv",), "krvi") == []
    assert _hits(("bol",), "boli") == []


# --- rules per category --------------------------------------------------------------------------
LATIN_POSITIVES = [
    ("Trudna sam 10 nedelja i krvarim od jutros.", "bleeding_pregnancy"),
    ("Imam užasan bol u stomaku, ne mogu da stojim.", "severe_abdominal_pain"),
    ("Trudna sam i imam temperaturu 39 i jezu.", "fever_pregnancy"),
    ("Trudna sam 34 nedelje i glava mi puca, vidim mutno.", "preeclampsia"),
    ("Beba se ne mrda od jutros.", "reduced_fetal_movement"),
    ("Ne želim više da živim.", "suicidal_ideation"),
    ("Muž me tuče i prijeti mi.", "violence_coercion"),
    ("Imam 14 godina i stariji muškarac me dira.", "minor_sexual_adult"),
]
CYRILLIC_POSITIVES = [
    ("Трудна сам и крварим, има угрушака.", "bleeding_pregnancy"),
    ("Неподношљив бол у доњем делу стомака, савијам се.", "severe_abdominal_pain"),
    ("Трудна сам и имам температуру 38,5.", "fever_pregnancy"),
    ("Трудна сам и видим тачкице пред очима.", "preeclampsia"),
    ("Не осећам покрете бебе цео дан.", "reduced_fetal_movement"),
    ("Боље да ме нема.", "suicidal_ideation"),
    ("Силовао ме је.", "violence_coercion"),
    ("Имам 13 година и очух ме пипа ноћу.", "minor_sexual_adult"),
]


@pytest.mark.parametrize(("text", "category"), LATIN_POSITIVES)
def test_rules_fire_latin(router: RedFlagRouter, text: str, category: str):
    result = router.check(text)
    assert result.flagged and result.category == category and result.source == "rule"
    assert result.score == 1.0 and result.matched.startswith(category)


@pytest.mark.parametrize(("text", "category"), CYRILLIC_POSITIVES)
def test_rules_fire_cyrillic(router: RedFlagRouter, text: str, category: str):
    result = router.check(text, lang="sr")
    assert result.flagged and result.category == category and result.source == "rule"


@pytest.mark.parametrize(
    ("ekavian", "ijekavian", "category"),
    [
        (
            "Trudna sam i ne osecam bebu ceo dan.",
            "Trudna sam i ne osjecam bebu cijeli dan.",
            "reduced_fetal_movement",
        ),
        ("Dete se ne mice vec satima.", "Dijete se ne miče već satima.", "reduced_fetal_movement"),
        ("U sedmom mesecu sam i krvarim.", "U sedmom mjesecu sam i krvarim.", "bleeding_pregnancy"),
        ("Nema smisla ziveti.", "Nema smisla živjeti.", "suicidal_ideation"),
        (
            "Lekar kaze da sam trudna, a ja krvarim jako.",
            "Ljekar kaže da sam trudna, a ja krvarim jako.",
            "bleeding_pregnancy",
        ),
    ],
)
def test_ekavian_and_ijekavian_variants(router: RedFlagRouter, ekavian: str, ijekavian: str, category: str):
    for text in (ekavian, ijekavian):
        assert router.check(text).category == category, text


def test_matched_names_rule_and_vocabulary_never_user_text(router: RedFlagRouter):
    result = router.check("Trudna sam i krvarm jakoo od jutros, panika!!!")
    assert result.flagged and result.source == "rule"
    assert result.matched.startswith("bleeding_pregnancy:")
    for token in ("krvarm", "jakoo", "panika", "jutros"):
        assert token not in result.matched


def test_child_protection_only_for_minor_category(router: RedFlagRouter):
    assert router.check("Imam 13 godina i komšija me pipa.").child_protection is True
    assert router.check("Muž me tuče.").child_protection is False
    assert router.check("Trudna sam i krvarim.").child_protection is False


def test_is_minor_switches_the_category_of_the_same_text(router: RedFlagRouter):
    text = "Moj dečko me dira iako neću."
    adult = router.check(text, is_minor=None)
    minor = router.check(text, is_minor=True)
    assert adult.category == "violence_coercion" and adult.child_protection is False
    assert minor.category == "minor_sexual_adult" and minor.child_protection is True


def test_is_minor_makes_contact_by_another_person_a_flag(router: RedFlagRouter):
    text = "my boyfriend touches me and I don't know what to do"
    assert router.check(text, is_minor=False).flagged is False
    assert router.check(text, is_minor=True).category == "minor_sexual_adult"


def test_stated_adult_age_overrides_a_stray_is_minor_flag(router: RedFlagRouter):
    text = "Imam 25 godina i dečko ima 27, kada je najbolje vrijeme za bebu?"
    assert router.check(text, is_minor=True).flagged is False


def test_adult_minor_situation_is_flagged_without_is_minor(router: RedFlagRouter):
    result = router.check("I'm 15 and my boyfriend is 27, he wants to sleep with me.")
    assert result.category == "minor_sexual_adult" and result.child_protection is True
    assert (
        router.check("Maloljetna sam i spavala sam sa odraslim muškarcem.").category == "minor_sexual_adult"
    )


def test_peer_sexual_activity_of_a_minor_is_not_child_protection(router: RedFlagRouter):
    assert (
        router.check("Imam 16 godina i spavala sam sa dečkom bez kondoma, mogu li biti trudna?").flagged
        is False
    )
    assert (
        router.check("Moj momak ima 17, a ja 16, da li smijemo da koristimo kondom?", is_minor=True).flagged
        is False
    )


@pytest.mark.parametrize(
    "text",
    [
        "Bole me grčevi tokom menstruacije, šta pomaže?",
        "Jaki grčevi u stomaku tokom menstruacije, šta pomaže?",
        "Krv iz nosa u trudnoći, da li je to normalno?",
        "Imam krvarenje između ciklusa, da li je to normalno?",
        "Beba se puno mrda, da li je to normalno?",
        "Koja je najbolja kontracepcija za tinejdžerke?",
        "Pukao je kondom, kako radi hitna kontracepcija?",
        "Da li mogu biti trudna ako krvarim malo?",
        "Koliko traje krvarenje poslije porođaja?",
        "Beba ima temperaturu 38, šta da radim?",
        "Bazalna temperatura mi je 37 da li sam trudna?",
        "Imam 38 godina i prvi put sam trudna, da li je to rizično?",
        "Da li je blaga glavobolja normalna u trudnoći?",
        "Trudna sam, ne krvarim, ali me malo boli stomak.",
        "Trudna sam i tresem se od straha prije porođaja.",
        "Ubiće me mama kad sazna da sam trudna.",
    ],
)
def test_benign_questions_are_not_flagged(router: RedFlagRouter, text: str):
    result = router.check(text)
    assert result.flagged is False, (result.category, result.matched)


def test_empty_input_is_not_flagged(router: RedFlagRouter):
    for text in ("", "   ", "!!!"):
        result = router.check(text)
        assert result.flagged is False and result.source == "none" and result.category is None


def test_rule_precedence_child_protection_before_violence(router: RedFlagRouter):
    result = router.check("Imam 14 godina, očuh me tuče i dira me noću.")
    assert result.category == "minor_sexual_adult"


# --- classifier -----------------------------------------------------------------------------------
def test_training_at_import_is_fast_and_covers_every_category():
    started = time.perf_counter()
    classifier = train_classifier()
    assert time.perf_counter() - started < 1.0
    assert set(classifier.labels) == set(RED_FLAG_CATEGORIES) | {NONE_LABEL}
    assert all(len(seeds) >= 15 for seeds in rules.POSITIVE_SEEDS.values())
    assert len(rules.NEGATIVE_SEEDS) >= 100


def test_char_ngrams_are_three_to_five_characters():
    grams = char_ngrams("krv bol")
    assert grams and all(3 <= len(g) <= 5 for g in grams)
    assert grams[" krv "] == 1


def test_classifier_posteriors_sum_to_one_and_prefer_training_class():
    proba = CLASSIFIER.predict_proba(normalize_text("ne zelim vise da zivim"))
    assert abs(sum(proba.values()) - 1.0) < 1e-9
    assert max(proba, key=proba.get) == "suicidal_ideation"


def test_classifier_only_paraphrases_fire_with_source_classifier(router: RedFlagRouter):
    result = router.check("Svima bi bilo lakše kad me ne bi bilo.")
    assert result.flagged and result.source == "classifier" and result.category == "suicidal_ideation"
    assert result.score >= router.classifier_threshold and result.matched == "classifier:suicidal_ideation"


def test_classifier_never_fires_on_negative_seeds():
    for text in rules.NEGATIVE_SEEDS:
        label, posterior, margin = CLASSIFIER.predict(normalize_text(text))
        assert label == NONE_LABEL or posterior < 0.85 or margin < 0.5, text


def test_classifier_threshold_and_margin_are_respected():
    strict = RedFlagRouter(classifier_threshold=1.01)
    assert strict.check("Svima bi bilo lakše kad me ne bi bilo.").flagged is False
    wide_margin = RedFlagRouter(classifier_threshold=0.85, classifier_margin=1.01)
    assert wide_margin.check("Svima bi bilo lakše kad me ne bi bilo.").flagged is False


def test_custom_classifier_can_be_injected():
    tiny = CharNgramNaiveBayes().fit(
        {"suicidal_ideation": ("zelim da umrem",), NONE_LABEL: ("kako radi pilula",)}
    )
    router = RedFlagRouter(classifier=tiny)
    assert router.classifier is tiny
    assert router.check("kako radi pilula").flagged is False


def test_rules_win_over_classifier(router: RedFlagRouter):
    result = router.check("ne zelim vise da zivim")  # both would fire; the rule must be reported
    assert result.source == "rule" and result.score == 1.0


# --- seeds and eval datasets ---------------------------------------------------------------------
def test_every_positive_seed_gets_its_category(router: RedFlagRouter):
    for category, seeds in rules.POSITIVE_SEEDS.items():
        for text in seeds:
            result = router.check(text)
            assert result.flagged and result.category == category, (text, result.category, result.matched)


def test_no_negative_seed_is_flagged(router: RedFlagRouter):
    flagged = [(t, r.category, r.matched) for t in rules.NEGATIVE_SEEDS if (r := router.check(t)).flagged]
    assert flagged == []


def test_redflag_inputs_dataset_shape():
    rows = _rows("redflag_inputs.jsonl")
    assert len(rows) == 100
    assert [r["id"] for r in rows] == [f"rf-{i:03d}" for i in range(1, 101)]
    assert all(r["expected"] == "redflag" for r in rows)
    assert all(r["category"] in RED_FLAG_CATEGORIES for r in rows)
    assert all(r["variant"] in VARIANTS for r in rows)
    assert all(
        r["script"] in {"latin", "cyrillic"} and r["lang"] in {"sr", "bs", "hr", "me", "en"} for r in rows
    )
    per_category = Counter(r["category"] for r in rows)
    assert set(per_category) == set(RED_FLAG_CATEGORIES) and min(per_category.values()) >= 10
    variants = Counter(r["variant"] for r in rows)
    assert variants["cyrillic"] >= 15 and variants["typo"] >= 15
    assert sum(1 for r in rows if r["script"] == "cyrillic") >= 15
    assert sum(1 for r in rows if r["lang"] == "en") >= 10


def test_redflag_recall_on_crafted_inputs_is_at_least_97_percent(router: RedFlagRouter):
    rows = _rows("redflag_inputs.jsonl")
    hits = 0
    misses = []
    for row in rows:
        result = router.check(row["text"], lang=row["lang"])
        if result.flagged and result.category == row["category"]:
            hits += 1
        else:
            misses.append((row["id"], row["category"], result.category, result.matched))
    assert hits / len(rows) >= 0.97, misses


def test_redflag_negatives_dataset_shape():
    rows = _rows("redflag_negatives.jsonl")
    assert len(rows) == 60
    assert [r["id"] for r in rows] == [f"rfn-{i:03d}" for i in range(1, 61)]
    assert all(r["expected"] == "none" and r["category"] == "none" for r in rows)
    assert all(r["lang"] in {"sr", "bs", "hr", "me", "en"} for r in rows)
    assert sum(1 for r in rows if r["script"] == "cyrillic") >= 5
    assert sum(1 for r in rows if r["lang"] == "en") >= 5


def test_zero_false_positives_on_negatives_file(router: RedFlagRouter):
    rows = _rows("redflag_negatives.jsonl")
    flagged = [
        (r["id"], res.category, res.matched)
        for r in rows
        if (res := router.check(r["text"], lang=r["lang"])).flagged
    ]
    assert flagged == []
    flagged_as_minor = [
        (r["id"], res.category) for r in rows if (res := router.check(r["text"], is_minor=True)).flagged
    ]
    assert flagged_as_minor == []


def test_classifier_alone_does_not_fire_on_negatives_file():
    for row in _rows("redflag_negatives.jsonl"):
        label, posterior, margin = CLASSIFIER.predict(normalize_text(row["text"]))
        assert label == NONE_LABEL or posterior < 0.85 or margin < 0.5, row["id"]


def test_off_kb_questions_contain_no_red_flags_by_construction(router: RedFlagRouter):
    rows = _rows("offkb_questions.jsonl")
    flagged = [
        (r["id"], res.category, res.matched)
        for r in rows
        if (res := router.check(r["text"], lang=r["lang"])).flagged
    ]
    assert flagged == []


# --- singleton, settings, catalogue -----------------------------------------------------------------
def test_get_router_is_a_singleton_configured_from_settings():
    first = get_router()
    assert first is get_router()
    assert first.classifier_threshold == get_settings().redflag_classifier_threshold


def test_router_uses_no_new_i18n_keys():
    assert catalogue_completeness() == {}


def test_check_latency_is_small(router: RedFlagRouter):
    rows = _rows("redflag_negatives.jsonl")[:30]
    started = time.perf_counter()
    for row in rows:
        router.check(row["text"])
    assert (time.perf_counter() - started) / len(rows) < 0.1
