"""LLM client abstraction: a protocol, two deterministic local clients and one real provider.

* :class:`MockLLM` is the default and the one tests use. It is *extractive*: it copies
  sentences out of the source blocks it finds in the user prompt and appends the marker of
  the block each sentence came from, so every claim it makes is verbatim evidence with a
  correct citation. It never invents text.
* :class:`ScriptedLLM` replays given strings; tests use it to drive the verifier and the
  gate with hand-written answers (hallucinations, wrong markers, dosing text, ...).
* :class:`OpenAICompatibleLLM` talks to any OpenAI-compatible ``/chat/completions`` endpoint
  (vLLM, llama.cpp, TGI, ...). Requests carry ``store: false``; the only retry is a single
  one on connection errors, i.e. before any request bytes could have reached the server, so
  user text is never sent twice.

The source-block format that :func:`app.core.generation.Generator.build_prompt` writes and
that :class:`MockLLM` reads back is defined here (:func:`format_source_block`,
:func:`parse_source_blocks`) so the two sides cannot drift apart.

Nothing in this module logs prompt or completion content.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from app.config import Settings
from app.core.i18n import tokenize

log = logging.getLogger("mila.llm")

QUESTION_LABEL = "Question:"
ANSWER_LABEL_PREFIX = "Answer in "
SOURCES_LABEL = "Sources:"

_SOURCE_HEADER_RE = re.compile(r"^\[S(\d+)\] \((.*)\)$")
_ANSWER_LABEL_RE = re.compile(r"^Answer in .+:$")
_TERMINAL_PUNCT = (".", "!", "?", "…")


class LLMError(RuntimeError):
    """Raised for any HTTP, transport or response-format failure of a real LLM endpoint.

    The message never contains prompt or completion content.
    """


@runtime_checkable
class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 600) -> str: ...


# --- shared prompt format ---------------------------------------------------------------------
@dataclass(frozen=True)
class SourceBlock:
    """One numbered evidence block as it appears in the user prompt."""

    marker: str  # "S1"
    header: str  # "title | section | version | lang"
    text: str


def format_source_block(index: int, header: str, text: str) -> str:
    """Render one evidence block: ``[S<index>] (<header>)`` on its own line, then the text.

    Newlines are removed from the header so the header is always exactly one line, which is
    what :func:`parse_source_blocks` relies on.
    """
    one_line_header = " ".join(header.split())
    return f"[S{index}] ({one_line_header})\n{text.strip()}"


def parse_source_blocks(user_prompt: str) -> tuple[list[SourceBlock], str]:
    """Read the evidence blocks and the question back out of a prompt built by the generator.

    Layout expected (see ``Generator.build_prompt``)::

        Sources:
        [S1] (header)
        text...

        [S2] (header)
        text...

        Question:
        <question>

        Answer in <language>:

    Block headers must be numbered consecutively from ``[S1]``; a line that looks like a
    header but carries the wrong number is treated as ordinary block text. This keeps a
    source document that happens to contain ``[S1] (...)`` from being read as a new block.
    The question is the text between the last ``Question:`` line and the final
    ``Answer in ...:`` line, so a source containing the word ``Question:`` cannot shift it.
    Returns ``([], "")`` when the prompt does not follow the layout.
    """
    lines = user_prompt.replace("\r\n", "\n").split("\n")
    answer_idx = next(
        (i for i in range(len(lines) - 1, -1, -1) if _ANSWER_LABEL_RE.match(lines[i].strip())), -1
    )
    if answer_idx < 0:
        return [], ""
    question_idx = next((i for i in range(answer_idx - 1, -1, -1) if lines[i].strip() == QUESTION_LABEL), -1)
    if question_idx < 0:
        return [], ""
    question = "\n".join(lines[question_idx + 1 : answer_idx]).strip()

    blocks: list[SourceBlock] = []
    current_header: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_header is not None:
            blocks.append(
                SourceBlock(
                    marker=f"S{len(blocks) + 1}", header=current_header, text="\n".join(current_lines).strip()
                )
            )

    for line in lines[:question_idx]:
        match = _SOURCE_HEADER_RE.match(line)
        if match and int(match.group(1)) == len(blocks) + (1 if current_header is None else 2):
            flush()
            current_header = match.group(2)
            current_lines = []
        elif current_header is not None:
            current_lines.append(line)
    flush()
    return blocks, question


# --- deterministic local clients --------------------------------------------------------------
class MockLLM:
    """Deterministic extractive answerer used by default and in tests.

    For every source block in the prompt the text is split into sentences (with the same
    splitter the verifier uses), each sentence is scored by normalised token overlap with the
    question (``|S ∩ Q| / sqrt(|S| · |Q|)`` over the verifier's ``content_tokens``, i.e.
    ``tokenize`` tokens of at least three characters minus stopwords) and the best sentences
    are copied out verbatim, each followed by the marker of its own block. At most ``max_sentences`` sentences are returned, at most
    ``per_chunk`` from one block; the block with the best sentence is emitted first and
    sentences keep their original order inside a block. Ties break on block order, then
    sentence order. Headings and fragments (fewer than ``min_tokens`` tokens, or no terminal
    punctuation) are never selected. The result is ``""`` when nothing overlaps.
    """

    name = "mock"

    def __init__(self, max_sentences: int = 4, per_chunk: int = 2, min_tokens: int = 5) -> None:
        self.max_sentences = max_sentences
        self.per_chunk = per_chunk
        self.min_tokens = min_tokens

    def complete(self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 600) -> str:
        # Imported here: app.core.verifier imports this module (LLMJudge needs LLMClient and
        # LLMError), so a module-level import would be circular.
        from app.core.verifier import content_tokens, split_sentences

        blocks, question = parse_source_blocks(user)
        q_tokens = set(content_tokens(question))
        if not blocks or not q_tokens:
            return ""

        scored: list[tuple[float, int, int, str]] = []
        for block_idx, block in enumerate(blocks):
            for sent_idx, sentence in enumerate(split_sentences(block.text)):
                if not sentence.endswith(_TERMINAL_PUNCT):
                    continue
                s_tokens = set(content_tokens(sentence))
                if len(tokenize(sentence)) < self.min_tokens or not s_tokens:
                    continue
                overlap = len(s_tokens & q_tokens)
                if overlap == 0:
                    continue
                score = overlap / math.sqrt(len(s_tokens) * len(q_tokens))
                scored.append((score, block_idx, sent_idx, sentence))

        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        chosen: list[tuple[float, int, int, str]] = []
        per_block: dict[int, int] = {}
        for item in scored:
            if len(chosen) >= self.max_sentences:
                break
            if per_block.get(item[1], 0) >= self.per_chunk:
                continue
            per_block[item[1]] = per_block.get(item[1], 0) + 1
            chosen.append(item)
        if not chosen:
            return ""

        best_per_block = {idx: max(c[0] for c in chosen if c[1] == idx) for idx in per_block}
        chosen.sort(key=lambda item: (-best_per_block[item[1]], item[1], item[2]))
        return " ".join(f"{sentence} [{blocks[block_idx].marker}]" for _, block_idx, _, sentence in chosen)


class ScriptedLLM:
    """Returns the given responses in order and repeats the last one once they run out.

    ``calls`` keeps every ``(system, user)`` pair received so tests can inspect prompts.
    """

    name = "scripted"

    def __init__(self, responses: Sequence[str]) -> None:
        if not responses:
            raise ValueError("ScriptedLLM needs at least one response")
        self._responses = list(responses)
        self._next = 0
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 600) -> str:
        self.calls.append((system, user))
        response = self._responses[min(self._next, len(self._responses) - 1)]
        self._next += 1
        return response


# --- real provider ----------------------------------------------------------------------------
class OpenAICompatibleLLM:
    """Client for an OpenAI-compatible ``POST {base_url}/chat/completions`` endpoint.

    Every request carries ``"store": false`` so that a server honouring the OpenAI API does not
    keep the conversation. ``Authorization`` is sent only when an API key is configured. The
    only retry is one repeat after a connection error (``ConnectError`` / ``ConnectTimeout``),
    which by definition happens before any bytes were sent; a failure once the request is on
    the wire is raised immediately so the same user text is never delivered twice.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_s: float = 60.0,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = model
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    def close(self) -> None:
        self._client.close()

    def complete(self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 600) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "store": False,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        url = f"{self.base_url}/chat/completions"

        attempts = 0
        while True:
            attempts += 1
            try:
                response = self._client.post(url, json=payload, headers=headers)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempts >= 2:
                    raise LLMError("could not connect to the LLM endpoint") from exc
                log.warning("LLM endpoint connection failed before sending; retrying once")
            except httpx.HTTPError as exc:
                raise LLMError(f"LLM transport error: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            raise LLMError(f"LLM endpoint returned HTTP {response.status_code}")
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM endpoint returned a malformed response") from exc
        if not isinstance(content, str):
            raise LLMError("LLM endpoint returned a non-text completion")
        return content


def get_llm(settings: Settings) -> LLMClient:
    """Build the LLM client selected by ``settings.llm_provider``."""
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleLLM(
            settings.llm_base_url,
            settings.llm_model,
            api_key=settings.llm_api_key,
            timeout_s=settings.llm_timeout_s,
        )
    return MockLLM()
