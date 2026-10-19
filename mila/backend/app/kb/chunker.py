"""Sentence-aware chunking of extracted document pages with heading tracking.

Token budget
------------
``estimate_tokens`` approximates sub-word token counts as ``ceil(1.3 * whitespace tokens)``:
for Latin-script English and BCMS text most multilingual tokenisers produce roughly 1.2-1.4
sub-word tokens per whitespace-separated word, so 1.3 is a conservative middle value. It is
computed with integer arithmetic (``(13 * n + 9) // 10``) so results are exact and
platform-independent.

Headings
--------
Headings are detected heuristically, line by line (see :func:`detect_heading`):

* Markdown ``#`` headings - level is the number of ``#``.
* Numbered headings such as ``2.3 Title`` - level is the number of components.
* ALL-CAPS lines - level 1.
* Short title-case lines followed by a body line - level 2.

``heading_path`` is the active heading stack joined with ``" > "`` (``"H1 > H2 > H3"``).
The stack carries over page boundaries; chunks never span pages, so ``page`` is exact.

Chunking
--------
Text under one heading is split into sentences (and list items). Sentences are packed
greedily into chunks of at most ``max_tokens``; a sentence is only split in the middle
when it is longer than the whole budget by itself. Consecutive chunks of the same section
overlap by the trailing sentences of the previous chunk, up to ``overlap_tokens``.
Empty chunks are never produced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKENS_PER_WORD_TENTHS = 13  # 1.3 sub-word tokens per whitespace token


@dataclass
class PageText:
    page: int
    text: str


@dataclass
class ChunkDraft:
    text: str
    page: int | None
    heading_path: str
    token_count: int


def estimate_tokens(text: str) -> int:
    """Approximate sub-word tokens as ``ceil(1.3 * whitespace tokens)`` (integer arithmetic)."""
    words = len(text.split())
    return (_TOKENS_PER_WORD_TENTHS * words + 9) // 10


def _max_words(max_tokens: int) -> int:
    """Largest word count whose ``estimate_tokens`` does not exceed ``max_tokens``."""
    return (10 * max_tokens) // _TOKENS_PER_WORD_TENTHS


# --- heading detection ---------------------------------------------------------------------
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*\s*$")
_NUMBERED_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3})*)\.?\s+([^\W\d_].*)$")
_LIST_MARKER_RE = re.compile(r"^(?:[-*•▪◦]|\d{1,3}[.)]|[a-z][.)])\s+")
_SENTENCE_END = ".,;:!?"
_SMALL_WORDS = frozenset(
    "a an and at by for from in into of on or the to vs with without "
    "i u na za od do iz o s sa po pri bez ili te ni a ali je li".split()
)
_MAX_HEADING_WORDS = 12
_MAX_TITLE_CASE_WORDS = 8


def _letters(text: str) -> str:
    return "".join(ch for ch in text if ch.isalpha())


def _is_title_case(text: str) -> bool:
    words = text.split()
    if not words or len(words) > _MAX_TITLE_CASE_WORDS:
        return False
    if len(words) == 1 and len(_letters(words[0])) < 4:
        return False
    for idx, word in enumerate(words):
        letters = _letters(word)
        if not letters:
            continue
        if word[0].isupper():
            continue
        if idx > 0 and word.lower() in _SMALL_WORDS:
            continue
        return False
    return True


def detect_heading(line: str, next_line: str | None = None) -> tuple[int, str] | None:
    """Return ``(level, title)`` when ``line`` looks like a heading, else ``None``.

    ``next_line`` (the next non-blank line, if any) is needed for the title-case rule: a
    short title-case line counts as a heading only when body text follows it.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 160:
        return None
    md = _MD_HEADING_RE.match(stripped)
    if md:
        return len(md.group(1)), md.group(2).strip()
    if _LIST_MARKER_RE.match(stripped) and not _NUMBERED_RE.match(stripped):
        return None
    words = stripped.split()
    if len(words) > _MAX_HEADING_WORDS or stripped[-1] in _SENTENCE_END:
        return None
    numbered = _NUMBERED_RE.match(stripped)
    if numbered:
        title = numbered.group(2).strip()
        if title[0].isupper():
            level = numbered.group(1).count(".") + 1
            return min(level, 6), stripped
    letters = _letters(stripped)
    if len(letters) >= 3 and stripped.isupper():
        return 1, stripped
    if next_line is not None and next_line.strip() and _is_title_case(stripped):
        nxt = next_line.strip()
        if _MD_HEADING_RE.match(nxt) is None and not nxt.isupper():
            return 2, stripped
    return None


# --- sentence splitting ---------------------------------------------------------------------
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-ZČĆŠŽĐ0-9])")
_EMPHASIS_RE = re.compile(r"(\*\*|__)")


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences on ``.!?`` followed by an upper-case/digit start."""
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _clean_line(line: str) -> str:
    line = _EMPHASIS_RE.sub("", line.strip())
    if line[:1] in "-*•▪◦" and len(line) > 1 and line[1] == " ":
        line = line[2:].strip()
    return line


@dataclass
class _Unit:
    """A sentence or list item with its word count."""

    text: str
    words: int


@dataclass
class _Section:
    page: int
    heading_path: str
    units: list[_Unit]


def _split_long_unit(unit: _Unit, max_words: int) -> list[_Unit]:
    if unit.words <= max_words:
        return [unit]
    words = unit.text.split()
    return [
        _Unit(" ".join(words[i : i + max_words]), len(words[i : i + max_words]))
        for i in range(0, len(words), max_words)
    ]


def _page_sections(page: PageText, stack: list[tuple[int, str]]) -> list[_Section]:
    """Walk one page, updating the heading stack, and return its text sections in order."""
    lines = page.text.splitlines()
    sections: list[_Section] = []
    paragraph: list[str] = []

    def current_path() -> str:
        return " > ".join(title for _level, title in stack)

    def open_section() -> _Section:
        if sections and sections[-1].heading_path == current_path():
            return sections[-1]
        sec = _Section(page=page.page, heading_path=current_path(), units=[])
        sections.append(sec)
        return sec

    def flush_paragraph() -> None:
        if not paragraph:
            return
        sec = open_section()
        for sentence in split_sentences(" ".join(paragraph)):
            sec.units.append(_Unit(sentence, len(sentence.split())))
        paragraph.clear()

    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            flush_paragraph()
            continue
        next_line = next((ln for ln in lines[idx + 1 :] if ln.strip()), None)
        heading = detect_heading(line, next_line)
        if heading is not None:
            flush_paragraph()
            level, title = heading
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            continue
        cleaned = _clean_line(line)
        if not cleaned:
            continue
        if _LIST_MARKER_RE.match(line) or raw.strip()[:1] in "-*•▪◦":
            flush_paragraph()
            paragraph.append(cleaned)
            flush_paragraph()
        else:
            paragraph.append(cleaned)
    flush_paragraph()
    return [s for s in sections if s.units]


def _pack_section(section: _Section, max_words: int, overlap_words: int) -> list[ChunkDraft]:
    units: list[_Unit] = []
    for unit in section.units:
        units.extend(_split_long_unit(unit, max_words))
    chunks: list[ChunkDraft] = []
    current: list[_Unit] = []
    current_words = 0

    def emit() -> None:
        text = " ".join(u.text for u in current)
        chunks.append(
            ChunkDraft(
                text=text,
                page=section.page,
                heading_path=section.heading_path,
                token_count=estimate_tokens(text),
            )
        )

    for unit in units:
        if current and current_words + unit.words > max_words:
            emit()
            carry: list[_Unit] = []
            carry_words = 0
            for prev in reversed(current):
                if carry_words + prev.words > overlap_words:
                    break
                carry.insert(0, prev)
                carry_words += prev.words
            while carry and carry_words + unit.words > max_words:
                carry_words -= carry.pop(0).words
            current = carry
            current_words = carry_words
        current.append(unit)
        current_words += unit.words
    if current:
        emit()
    return chunks


def chunk_pages(pages: list[PageText], max_tokens: int = 400, overlap_tokens: int = 40) -> list[ChunkDraft]:
    """Chunk extracted pages into sentence-aware drafts of at most ``max_tokens`` each."""
    if max_tokens < 2:
        raise ValueError("max_tokens must be at least 2")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than max_tokens")
    max_words = max(1, _max_words(max_tokens))
    overlap_words = _max_words(overlap_tokens)
    stack: list[tuple[int, str]] = []
    chunks: list[ChunkDraft] = []
    for page in pages:
        for section in _page_sections(page, stack):
            chunks.extend(_pack_section(section, max_words, overlap_words))
    return [c for c in chunks if c.text.strip()]
