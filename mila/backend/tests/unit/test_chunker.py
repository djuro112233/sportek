"""Tests for app.kb.chunker: token budget, overlap, heading paths, sentence integrity."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

from app.kb.chunker import ChunkDraft, PageText, chunk_pages, detect_heading, estimate_tokens, split_sentences


def _sentences(n: int, words: int = 6) -> str:
    return " ".join(
        f"Sentence number {i} " + " ".join("word" for _ in range(words - 3)) + "." for i in range(n)
    )


def test_estimate_tokens_is_ceil_of_1_3_words_without_float_error() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("   ") == 0
    assert estimate_tokens("one") == 2
    assert estimate_tokens(" ".join(["w"] * 10)) == 13  # 1.3 * 10 == 13.000000000000002 in floating point
    for n in range(1, 60):
        assert estimate_tokens(" ".join(["w"] * n)) == math.ceil(13 * n / 10)


def test_chunks_never_exceed_max_tokens_and_are_never_empty() -> None:
    page = PageText(1, _sentences(60, words=9))
    chunks = chunk_pages([page], max_tokens=50, overlap_tokens=10)
    assert len(chunks) > 5
    for chunk in chunks:
        assert isinstance(chunk, ChunkDraft)
        assert chunk.text.strip()
        assert chunk.token_count == estimate_tokens(chunk.text)
        assert chunk.token_count <= 50
        assert chunk.page == 1


def test_consecutive_chunks_overlap_by_trailing_sentences() -> None:
    page = PageText(1, _sentences(40))
    chunks = chunk_pages([page], max_tokens=40, overlap_tokens=15)
    assert len(chunks) >= 3
    for previous, following in zip(chunks, chunks[1:], strict=False):
        last_sentence = split_sentences(previous.text)[-1]
        assert following.text.startswith(last_sentence)


def test_zero_overlap_shares_nothing() -> None:
    page = PageText(1, _sentences(30))
    chunks = chunk_pages([page], max_tokens=40, overlap_tokens=0)
    seen: set[str] = set()
    for chunk in chunks:
        for sentence in split_sentences(chunk.text):
            assert sentence not in seen
            seen.add(sentence)
    assert len(seen) == 30


def test_markdown_heading_paths() -> None:
    text = "# Title\n\n## Alpha\nAlpha body.\n\n### Deep\nDeep body.\n\n## Beta\nBeta body."
    chunks = chunk_pages([PageText(1, text)])
    assert [(c.heading_path, c.text) for c in chunks] == [
        ("Title > Alpha", "Alpha body."),
        ("Title > Alpha > Deep", "Deep body."),
        ("Title > Beta", "Beta body."),
    ]


def test_numbered_and_all_caps_headings() -> None:
    text = "CHAPTER ONE\n1.1 Scope of the guideline\nBody one.\n1.2 Terms\nBody two.\n2 Methods\nBody three."
    chunks = chunk_pages([PageText(3, text)])
    assert [c.heading_path for c in chunks] == [
        "CHAPTER ONE > 1.1 Scope of the guideline",
        "CHAPTER ONE > 1.2 Terms",
        "2 Methods",  # a single-number heading is level 1, like an ALL-CAPS line
    ]
    assert all(c.page == 3 for c in chunks)


def test_title_case_line_is_a_heading_only_when_body_follows() -> None:
    assert detect_heading("Danger Signs in Pregnancy", "Seek care if you bleed.") == (
        2,
        "Danger Signs in Pregnancy",
    )
    assert detect_heading("Danger Signs in Pregnancy", None) is None
    assert detect_heading("Danger Signs in Pregnancy", "") is None
    chunks = chunk_pages([PageText(1, "Danger Signs\nSeek care if you bleed.\nAnd rest.")])
    assert chunks[0].heading_path == "Danger Signs"
    assert chunks[0].text == "Seek care if you bleed. And rest."


def test_sentences_and_list_items_are_not_headings() -> None:
    assert detect_heading("1. Take the booklet with you.", "Next line.") is None
    assert detect_heading("- Condoms protect against infections", "Next line.") is None
    assert detect_heading("Yes", "Something follows.") is None
    assert detect_heading("She said the visit was quick and easy today", "More.") is None
    assert detect_heading("# Markdown Heading") == (1, "Markdown Heading")
    assert detect_heading("### Third") == (3, "Third")


def test_list_items_become_separate_sentences_without_markers() -> None:
    text = "## Where to get it\n- Pharmacies sell it.\n- Clinics give it\n* Youth centres help"
    chunks = chunk_pages([PageText(1, text)])
    assert len(chunks) == 1
    assert chunks[0].text == "Pharmacies sell it. Clinics give it Youth centres help"
    assert chunks[0].heading_path == "Where to get it"


def test_heading_stack_carries_across_pages_but_chunks_do_not() -> None:
    pages = [PageText(1, "# Guide\n## Section\nFirst page text."), PageText(2, "Second page text continues.")]
    chunks = chunk_pages(pages)
    assert [(c.page, c.heading_path) for c in chunks] == [(1, "Guide > Section"), (2, "Guide > Section")]


def test_short_sentences_are_never_split_mid_sentence() -> None:
    page = PageText(1, _sentences(50, words=7))
    for chunk in chunk_pages([page], max_tokens=30, overlap_tokens=5):
        assert chunk.text.endswith(".")
        for sentence in split_sentences(chunk.text):
            assert sentence.startswith("Sentence number")


def test_overlong_sentence_is_split_on_words_only_when_unavoidable() -> None:
    words = [f"w{i}" for i in range(200)]
    page = PageText(1, " ".join(words) + ".")
    chunks = chunk_pages([page], max_tokens=50, overlap_tokens=0)
    assert len(chunks) > 1
    assert all(c.token_count <= 50 for c in chunks)
    assert " ".join(c.text for c in chunks).split() == (words[:-1] + [words[-1] + "."])


def test_empty_pages_produce_no_chunks() -> None:
    assert chunk_pages([]) == []
    assert chunk_pages([PageText(1, ""), PageText(2, " \n\n  ")]) == []
    assert chunk_pages([PageText(1, "# Only a heading")]) == []


def test_invalid_parameters_are_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_pages([PageText(1, "x.")], max_tokens=1)
    with pytest.raises(ValueError):
        chunk_pages([PageText(1, "x.")], max_tokens=20, overlap_tokens=20)


@h_settings(max_examples=80, deadline=None)
@given(st.text(max_size=600), st.integers(min_value=5, max_value=80))
def test_property_chunks_are_bounded_and_non_empty(text: str, max_tokens: int) -> None:
    chunks = chunk_pages([PageText(1, text)], max_tokens=max_tokens, overlap_tokens=max_tokens // 4)
    for chunk in chunks:
        assert chunk.text.strip()
        assert 0 < chunk.token_count <= max_tokens
        assert chunk.page == 1
