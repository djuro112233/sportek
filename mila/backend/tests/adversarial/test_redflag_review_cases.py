"""Red-flag cases from the 2026-10-20 adversarial review (RF-1 .. RF-6, RF-8, RF-9).

Every positive here was missed before the review; every negative is an information question
that must reach the knowledge base instead of the emergency referral.
"""

from __future__ import annotations

import pytest

from app.core.redflags import expand_number_words, get_router

MINOR_ADULT = [
    "imam petnaest godina a decko ima dvadeset osam i hoce seks",
    "imam sesnaest godina i decko ima trideset godina, spavamo",
    "imam 15 godina a decko ima dvadeset osam i hoce seks",
    "ja sam 16 i spavala sam sa tipom od 35",
    "ja sam 16 godina i spavala sam sa tipom od 35",
    "imam 16 godina i spavala sam sa muskarcem od 35",
    "16 mi je godina a decko mi ima 30 i hoce da spavamo",
    "sestra mi ima 14, njen momak ima 30 i spavaju zajedno",
    "moja sestra, 15 godina, njen momak ima 30",
    "im 15 my boyfriend is 28 he wants to have sex",
    "i am fifteen and my boyfriend is twenty eight, we sleep together",
    "my cousin is 14 and she is sleeping with a guy who is 30",
]
SUICIDE = [
    "razmisljam da presudim sebi",
    "presudila bih sebi",
    "oduzela bih sebi zivot",
    "sta je najbezbolniji nacin da umrem",
    "koliko tableta treba da popijem da umrem",
    "how many pills do i need to take to die",
    "i dont want to wake up tomorrow",
    "zelim da nestanem zauvijek",
    "bolje da sam mrtva",
    "wish i was dead",
]
VIOLENCE = [
    "мој момак ме гура и шамара кад се наљути",
    "momak me gura kad se naljuti",
    "decko mi je slomio ruku",
    "muz mi je slomio nos",
    "decko mi je slomio ruku ali kaze da je to bilo slucajno, i stalno vice na mene",
    "ne da mi da koristim zastitu",
    "ne da mi da pijem pilule",
    "baca mi pilule",
    "partner mi je uzeo pilule i baca ih, kaze da moram da zatrudnim",
    "forsira me na seks",
    "he wont let me use condoms and throws away my pills",
    "my boyfriend pushes me and slapped me yesterday",
    "he broke my nose last week",
]
PREGNANCY_WEEKS = [
    ("u 30. nedjelji sam i od jutros mi curi krv", "bleeding_pregnancy"),
    ("u 30. nedjelji sam i krvarim", "bleeding_pregnancy"),
    ("u 12. sedmici sam i krvarim", "bleeding_pregnancy"),
    ("u 20. tjednu sam i krvarim", "bleeding_pregnancy"),
    ("30 nedelja, krvarim i boli me stomak", "bleeding_pregnancy"),
    ("10 weeks, bleeding and cramping", "bleeding_pregnancy"),
    ("u 28. nedjelji sam, temperatura 38 8, drhtim", "fever_pregnancy"),
    ("32 weeks pregnant and my face and hands are suddenly swollen, bad headache", "preeclampsia"),
    ("pukao mi vodenjak i ima krvi", "bleeding_pregnancy"),
    ("my water broke with blood in it", "bleeding_pregnancy"),
    ("u 34. nedjelji sam i nisam osjetila bebu od jutros", "reduced_fetal_movement"),
]
PAIN = [
    "trudna sam u 30 nedelji i stomak me boli kao da ce da pukne ne mogu da disem",
    "trudna sam i stomak me boli kao da ce da pukne",
    "trudna sam, boli me stomak i ne mogu da disem od bola",
    "trudna sam i stomak mi je tvrd kao kamen i jako boli",
    "trudna sam 30 nedelja i imam kontrakcije na svakih 5 minuta",
    "trudna sam 30 nedelja i imam jake kontrakcije",
    "u 30. nedjelji sam i imam kontrakcije svakih 10 minuta",
    "im 36 weeks and having strong contractions every 5 minutes",
]
INFO_NEGATIVES = [
    "kada je krvarenje u trudnoci opasno?",
    "da li je tacno da je krvarenje u ranoj trudnoci uvijek znak pobacaja?",
    "koji su znaci preeklampsije?",
    "koji su znakovi da beba manje mrda i kada da se javim?",
    "what are the warning signs in pregnancy?",
    "when should i worry about bleeding in pregnancy?",
    "da li je normalno da beba manje mrda pred porodjaj?",
    "kada je temperatura u trudnoci razlog za hitnu?",
    "is it true that any bleeding in pregnancy is dangerous?",
    "koji su simptomi vanmatericne trudnoce?",
    "prije 15 godina sam imala tesko krvarenje poslije poroda, sad sam opet trudna, na sta da pazim?",
    "nemam krvarenje ali me zanima kada je opasno",
]
# A question asking for the violence helpline is answered with the violence referral on purpose.
HELPLINE_QUESTIONS = ["koja je sos linija za nasilje u porodici?", "where can i report domestic violence?"]
INFO_WITH_SYMPTOM = [
    ("koji su znaci preeklampsije? imam jaku glavobolju i vidim musice, trudna sam", "preeclampsia"),
    ("kada je krvarenje u trudnoci opasno? ja krvarim od jutros, trudna sam", "bleeding_pregnancy"),
]


@pytest.mark.parametrize("text", MINOR_ADULT)
def test_minor_with_adult_is_child_protection(text: str) -> None:
    result = get_router().check(text)
    assert result.flagged and result.category == "minor_sexual_adult" and result.child_protection, text


@pytest.mark.parametrize("text", SUICIDE)
def test_suicide_euphemisms_and_method_seeking(text: str) -> None:
    result = get_router().check(text)
    assert result.flagged and result.category == "suicidal_ideation", text


@pytest.mark.parametrize("text", VIOLENCE)
def test_violence_and_reproductive_coercion(text: str) -> None:
    result = get_router().check(text)
    assert result.flagged and result.category == "violence_coercion", text


@pytest.mark.parametrize(("text", "category"), PREGNANCY_WEEKS)
def test_gestational_age_is_a_pregnancy_context(text: str, category: str) -> None:
    result = get_router().check(text)
    assert result.flagged and result.category == category, (text, result)


@pytest.mark.parametrize("text", PAIN)
def test_contractions_and_functional_pain_in_pregnancy(text: str) -> None:
    result = get_router().check(text)
    assert result.flagged and result.category == "severe_abdominal_pain", (text, result)


@pytest.mark.parametrize("text", INFO_NEGATIVES)
def test_information_questions_are_not_emergencies(text: str) -> None:
    for is_minor in (None, True, False):
        result = get_router().check(text, is_minor=is_minor)
        assert not result.flagged, (text, is_minor, result)


@pytest.mark.parametrize("text", HELPLINE_QUESTIONS)
def test_helpline_questions_get_the_support_referral(text: str) -> None:
    result = get_router().check(text)
    assert result.flagged and result.category == "violence_coercion"


@pytest.mark.parametrize(("text", "category"), INFO_WITH_SYMPTOM)
def test_information_frame_does_not_hide_a_present_symptom(text: str, category: str) -> None:
    result = get_router().check(text)
    assert result.flagged and result.category == category, (text, result)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("imam petnaest godina", "imam 15 godina"),
        ("decko ima dvadeset osam", "decko ima 28"),
        ("trideset osam i po", "38 i po"),
        ("i am fifteen and he is twenty eight", "i am 15 and he is 28"),
        ("jedan dan kasnije", "jedan dan kasnije"),
    ],
)
def test_expand_number_words(text: str, expected: str) -> None:
    assert expand_number_words(text) == expected
