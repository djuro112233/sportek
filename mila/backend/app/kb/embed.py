"""Embedding providers.

Two implementations of the :class:`Embedder` protocol:

* :class:`HashEmbedder` - deterministic feature hashing (word unigrams + character
  3-grams of the normalised text) into a fixed number of signed buckets. No model, no
  network, no randomness. It is the default for development and tests and gives a
  lexical similarity signal that complements BM25 (it is tolerant to inflection and
  spelling variants through the character n-grams).
* :class:`BGEM3Embedder` - multilingual dense embeddings from ``BAAI/bge-m3`` via
  ``sentence_transformers``; imported lazily so the dependency is optional.

Every embedder returns L2-normalised vectors, so the dot product equals the cosine.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

from app.config import Settings
from app.core.i18n import normalize_text

if TYPE_CHECKING:  # pragma: no cover - typing only; the dependency is optional
    from sentence_transformers import SentenceTransformer


@runtime_checkable
class Embedder(Protocol):
    """A text -> vector provider. Vectors must be L2-normalised and have ``dim`` entries."""

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# Relative weight of character 3-gram features versus word unigram features.
_CHAR_NGRAM_WEIGHT = 0.5
_WORD_WEIGHT = 1.0
# Upper bound on the per-instance feature cache (features -> bucket/sign); cleared when hit.
_FEATURE_CACHE_LIMIT = 500_000


class HashEmbedder:
    """Deterministic feature-hashing embedder.

    Features of a text are the word unigrams and the boundary-padded character 3-grams of
    ``normalize_text(text)`` (Cyrillic -> Latin, diacritics stripped, lower-cased). Each
    feature is hashed with ``hashlib.blake2b`` (never Python's salted ``hash()``) to a
    bucket in ``[0, dim)`` and a sign in ``{-1, +1}``; feature counts are damped with
    ``1 + log(count)`` and the resulting vector is L2-normalised. Empty or non-alphanumeric
    text yields the zero vector.
    """

    def __init__(self, dim: int = 256) -> None:
        if dim < 8:
            raise ValueError("dim must be at least 8")
        self.dim = dim
        self._cache: dict[str, tuple[int, float]] = {}

    def _bucket(self, feature: str) -> tuple[int, float]:
        hit = self._cache.get(feature)
        if hit is not None:
            return hit
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        bucket = (value >> 1) % self.dim
        sign = 1.0 if value & 1 else -1.0
        if len(self._cache) >= _FEATURE_CACHE_LIMIT:
            self._cache.clear()
        self._cache[feature] = (bucket, sign)
        return bucket, sign

    @staticmethod
    def features(text: str) -> Counter[str]:
        """Feature multiset of a text: ``w:<word>`` and ``c:<3-gram>`` (padded with spaces)."""
        feats: Counter[str] = Counter()
        for word in normalize_text(text).split():
            feats["w:" + word] += 1
            padded = f" {word} "
            for i in range(len(padded) - 2):
                feats["c:" + padded[i : i + 3]] += 1
        return feats

    def _embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float64)
        for feature, count in self.features(text).items():
            bucket, sign = self._bucket(feature)
            weight = _WORD_WEIGHT if feature[0] == "w" else _CHAR_NGRAM_WEIGHT
            vec[bucket] += sign * weight * (1.0 + math.log(count))
        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec /= norm
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t).tolist() for t in texts]


class BGEM3Embedder:
    """Dense multilingual embeddings from ``BAAI/bge-m3`` (1024 dimensions).

    ``sentence_transformers`` is imported on first use, so constructing the object (and
    importing this module) never requires the optional dependency or a model download.
    """

    dim = 1024

    def __init__(
        self, model_name: str = "BAAI/bge-m3", device: str | None = None, batch_size: int = 16
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model: SentenceTransformer | None = None

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise ImportError(
                    "BGEM3Embedder needs the optional 'embed' extra: pip install 'mila[embed]'"
                ) from exc
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float64).tolist()


def get_embedder(settings: Settings) -> Embedder:
    """Select the embedder configured by ``settings.embedder`` ('hash' or 'bge_m3')."""
    if settings.embedder == "bge_m3":
        return BGEM3Embedder()
    return HashEmbedder(dim=settings.embedding_dim)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors; 0.0 when either is the zero vector or lengths differ."""
    if len(a) != len(b) or not a:
        return 0.0
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
