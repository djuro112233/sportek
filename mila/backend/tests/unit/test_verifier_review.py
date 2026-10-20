"""Verifier fixes from the 2026-10-20 review (AS-5, AS-6, AS-10)."""

from __future__ import annotations

import pytest

from app.core.types import RetrievedChunk
from app.core.verifier import LexicalJudge, Verifier, mentions_medication_dose


@pytest.mark.parametrize(
    "text",
    [
        "Imam menstruaciju dva puta u toku jednog mjeseca, je li to normalno?",
        "Da li je dovoljan pregled kod jednog ginekologa u trudnoci?",
        "Posle jednog nezasticenog odnosa, koliko traje rizik?",
        "jednog uloska na sat",
        "Ne uzimaj lijekove na svoju ruku zbog ovih znakova; zdravstveni radnik prvo mora da te pregleda.",
        "Do not take medicines on your own for these signs; the health worker needs to see you first.",
        "Nemoj uzimati tablete bez savjeta ljekara.",
        "Never take antibiotics without a prescription.",
    ],
)
def test_genitive_one_and_negated_imperatives_are_not_doses(text: str) -> None:
    assert not mentions_medication_dose(text)


@pytest.mark.parametrize(
    "text", ["Uzmi ibuprofen 400 mg.", "take two tablets", "jedna tableta dnevno", "1 g paracetamola"]
)
def test_real_doses_still_flag(text: str) -> None:
    assert mentions_medication_dose(text)


def _chunk(cid: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, source_id="s", source_title="t", source_version="v", text=text, lang="en"
    )


def test_only_supporting_markers_are_kept_as_citations() -> None:
    chunks = [
        _chunk("a", "Condoms protect against most sexually transmitted infections."),
        _chunk("b", "Breastfeeding on demand helps milk supply."),
    ]
    verifier = Verifier(LexicalJudge(), threshold=0.5)
    [sentence] = verifier.verify(
        "Condoms protect against most sexually transmitted infections. [S1][S2]", chunks
    )
    assert sentence.supported and sentence.citations == ["S1"]


def test_best_marker_is_kept_when_several_support() -> None:
    chunks = [
        _chunk("a", "Condoms protect against infections."),
        _chunk("b", "Condoms protect against infections and pregnancy."),
    ]
    verifier = Verifier(LexicalJudge(), threshold=0.5)
    [sentence] = verifier.verify("Condoms protect against infections. [S1, S2]", chunks)
    assert sentence.citations == ["S1", "S2"]
