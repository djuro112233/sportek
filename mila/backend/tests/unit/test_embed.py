"""Tests for app.kb.embed: determinism, dimensionality, normalisation, lexical relatedness."""

from __future__ import annotations

import math
import sys

import numpy as np
import pytest
from conftest import make_test_settings
from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

from app.kb.embed import BGEM3Embedder, Embedder, HashEmbedder, cosine, get_embedder


def _norm(vec: list[float]) -> float:
    return float(np.linalg.norm(np.asarray(vec)))


def test_hash_embedder_is_deterministic_across_instances() -> None:
    text = "Emergency contraception can be used up to five days after unprotected sex."
    first = HashEmbedder(dim=256).embed([text])[0]
    second = HashEmbedder(dim=256).embed([text])[0]
    assert first == second
    assert HashEmbedder(dim=256).embed([text, text]) == [first, first]


def test_hash_embedder_dim_and_unit_norm() -> None:
    emb = HashEmbedder(dim=128)
    vectors = emb.embed(["antenatal care visits", "Znaci opasnosti u trudnoći"])
    assert emb.dim == 128
    assert all(len(v) == 128 for v in vectors)
    assert all(math.isclose(_norm(v), 1.0, abs_tol=1e-9) for v in vectors)


def test_empty_or_symbol_only_text_gives_zero_vector() -> None:
    emb = HashEmbedder(dim=64)
    for text in ("", "   ", "!!! ???"):
        vec = emb.embed([text])[0]
        assert len(vec) == 64
        assert _norm(vec) == 0.0


def test_related_texts_score_clearly_higher_than_unrelated() -> None:
    emb = HashEmbedder()
    anchor = "Emergency contraceptive pills are taken after unprotected sex to prevent pregnancy."
    related = "After unprotected sex, emergency contraception can prevent a pregnancy."
    unrelated = "The train to the coast leaves the station every morning at nine."
    a, r, u = emb.embed([anchor, related, unrelated])
    assert cosine(a, r) > cosine(a, u) + 0.25
    assert cosine(a, u) < 0.3


def test_script_and_diacritics_do_not_change_the_vector() -> None:
    emb = HashEmbedder()
    latin, cyrillic, ascii_ = emb.embed(["Hitna kontracepcija", "Хитна контрацепција", "hitna kontracepcija"])
    assert latin == cyrillic == ascii_
    with_diacritics, without = emb.embed(["trudnoća i porođaj", "trudnoca i porodjaj"])
    assert with_diacritics == without


def test_inflected_forms_share_character_ngrams() -> None:
    emb = HashEmbedder()
    base, inflected, other = emb.embed(["trudnoća", "trudnoće", "kondom"])
    assert cosine(base, inflected) > 0.5
    assert cosine(base, other) < 0.2


def test_batch_embedding_matches_single_calls() -> None:
    emb = HashEmbedder(dim=96)
    texts = ["first text about periods", "second text about breastfeeding", ""]
    assert emb.embed(texts) == [emb.embed([t])[0] for t in texts]


def test_hash_embedder_rejects_tiny_dim() -> None:
    with pytest.raises(ValueError):
        HashEmbedder(dim=4)


def test_hash_embedder_satisfies_protocol() -> None:
    assert isinstance(HashEmbedder(), Embedder)
    assert isinstance(BGEM3Embedder(), Embedder)


def test_get_embedder_selects_by_settings(tmp_path) -> None:
    hashed = get_embedder(make_test_settings(tmp_path, embedder="hash", embedding_dim=128))
    assert isinstance(hashed, HashEmbedder)
    assert hashed.dim == 128

    dense = get_embedder(make_test_settings(tmp_path, embedder="bge_m3"))
    assert isinstance(dense, BGEM3Embedder)
    assert dense.dim == 1024
    assert dense.model_name == "BAAI/bge-m3"
    # Constructing the object must not import the optional dependency or download anything.
    assert "sentence_transformers" not in sys.modules


def test_cosine_edge_cases() -> None:
    assert math.isclose(cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine([], []) == 0.0
    assert cosine([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0
    assert math.isclose(cosine([1.0, 0.0], [-1.0, 0.0]), -1.0)


@h_settings(max_examples=60, deadline=None)
@given(st.text(max_size=300))
def test_property_vectors_are_unit_or_zero_and_finite(text: str) -> None:
    emb = HashEmbedder(dim=32)
    vec = emb.embed([text])[0]
    assert len(vec) == 32
    assert all(math.isfinite(v) for v in vec)
    norm = _norm(vec)
    assert norm == 0.0 or math.isclose(norm, 1.0, abs_tol=1e-9)
