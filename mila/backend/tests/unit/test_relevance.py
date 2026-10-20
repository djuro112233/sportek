"""Question relevance: rarity-weighted coverage of the question by the cited evidence."""

from __future__ import annotations

from app.core.relevance import (
    UNKNOWN_TERM_PENALTY,
    coverage,
    fold_yat,
    make_idf,
    question_relevance,
    stems,
)
from app.core.types import AnswerSentence, RetrievedChunk

CORPUS = [
    "metode kontracepcije kondom pilula spirala implant",
    "pregledi u trudnoci prvi pregled nedjelja trudnoce",
    "dojenje novorodjence mlijeko",
    "polno prenosive infekcije testiranje kondom kontracepcija",
]


def _chunk(text: str, lang: str = "sr") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c", source_id="s", source_title="t", source_version="v", text=text, lang=lang
    )


def test_fold_yat_merges_ijekavian_and_ekavian() -> None:
    assert fold_yat("nedjelja") == fold_yat("nedelja") == "nedelja"
    assert fold_yat("poslije") == fold_yat("posle")
    assert fold_yat("mlijeko") == "mleko" and fold_yat("ljekar") == fold_yat("lekar")
    assert fold_yat("jedan") == "jedan" and fold_yat("jesam") == "jesam"


def test_stems_drop_question_words_and_dedupe() -> None:
    assert stems("Koje metode kontracepcije postoje i koje metode su najbolje?") == [
        "metod",
        "kontr",
        "posto",
        "najbo",
    ]
    assert stems("Šta da radim?") == []


def test_make_idf_gives_unknown_stems_the_ceiling() -> None:
    idf = make_idf(stems(doc) for doc in CORPUS)
    assert idf("zzzzz") == idf.ceiling  # type: ignore[attr-defined]
    assert idf("kontr") < idf.ceiling  # type: ignore[attr-defined]
    assert idf("kondo") < idf("dojen")  # appears in more documents -> lower weight


def test_coverage_without_idf_is_the_plain_share() -> None:
    assert coverage("metode kontracepcije kondom", ["metode kondom"]) == 0.6667
    assert coverage("Šta da radim?", ["anything"]) is None


def test_coverage_penalises_an_unknown_unmatched_term() -> None:
    idf = make_idf(stems(doc) for doc in CORPUS)
    full = coverage("metode kontracepcije", ["metode kontracepcije"], idf)
    assert full == 1.0
    with_unknown = coverage("metode kontracepcije katarakta", ["metode kontracepcije"], idf)
    assert with_unknown is not None and with_unknown < UNKNOWN_TERM_PENALTY
    no_penalty = coverage(
        "metode kontracepcije katarakta", ["metode kontracepcije"], idf, unknown_term_penalty=1.0
    )
    assert no_penalty is not None and no_penalty > with_unknown


def test_question_relevance_uses_only_supported_cited_evidence() -> None:
    chunks = [_chunk("metode kontracepcije kondom pilula"), _chunk("dojenje novorodjence mlijeko")]
    supported = AnswerSentence(
        text="Kondom i pilula su metode kontracepcije.", citations=["S1"], supported=True, support_score=1.0
    )
    unsupported = AnswerSentence(text="Dojenje je važno.", citations=["S2"], supported=False)
    assert (
        question_relevance("Koje metode kontracepcije postoje?", "sr", [supported, unsupported], chunks)
        == 0.6667
    )
    assert question_relevance("Koje metode kontracepcije postoje?", "sr", [unsupported], chunks) is None
    flagged = supported.model_copy(update={"flagged_medication": True})
    assert question_relevance("Koje metode kontracepcije postoje?", "sr", [flagged], chunks) is None


def test_question_relevance_is_not_assessed_across_language_families() -> None:
    chunks = [_chunk("contraceptive methods condom pill", lang="en")]
    sentence = AnswerSentence(
        text="Condoms and pills are contraceptive methods.",
        citations=["S1"],
        supported=True,
        support_score=1.0,
    )
    assert question_relevance("Koje metode kontracepcije postoje?", "sr", [sentence], chunks) is None
    assert question_relevance("Which contraceptive methods are there?", "en", [sentence], chunks) == 1.0


def test_question_relevance_ignores_unknown_markers() -> None:
    chunks = [_chunk("metode kontracepcije")]
    sentence = AnswerSentence(text="x", citations=["S9"], supported=True, support_score=1.0)
    assert question_relevance("metode kontracepcije", "sr", [sentence], chunks) is None
