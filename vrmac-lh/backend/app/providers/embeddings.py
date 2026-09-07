"""Embeddings behind an interface.

EMBEDDINGS_PROVIDER=ollama                → multilingual open model served by Ollama (default: paraphrase-multilingual, 768-d)
EMBEDDINGS_PROVIDER=sentence-transformers → in-process model (needs requirements-st.txt)
EMBEDDINGS_PROVIDER=hash                  → deterministic hashed lexical features; no model download.
                                            Used by the CI test-suite so the grounding tests are reproducible offline.
                                            Cross-lingual matching relies on both languages being indexed.

All providers must return vectors of exactly EMBEDDING_DIM (the pgvector column width).
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Protocol

import httpx

from ..config import settings

# Provider-specific defaults for the retrieval-confidence threshold (cosine similarity).
DEFAULT_MIN_SIMILARITY = {"hash": 0.35, "ollama": 0.60, "sentence-transformers": 0.60}

_STOPWORDS = {
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "of", "in", "on", "at", "to", "and", "or",
    "what", "when", "where", "which", "who", "whom", "how", "does", "do", "did", "it", "its", "this", "that",
    "these", "those", "for", "with", "from", "by", "there", "as", "can", "i", "you", "we", "they", "he", "she",
    "me", "my", "your", "our", "their", "please", "tell", "about", "any", "some", "much", "many", "long", "far",
    # Montenegrin / Serbian / Croatian (Latin)
    "je", "su", "sam", "si", "smo", "ste", "li", "da", "u", "na", "i", "ili", "od", "do", "se", "za", "o", "sa",
    "s", "koji", "koja", "koje", "kog", "kojeg", "kada", "kad", "gde", "gdje", "sta", "kako", "sto", "ko", "ima",
    "te", "ne", "bio", "bila", "bilo", "bili", "ovo", "to", "ta", "taj", "ovaj", "ova", "mi", "vi", "oni", "one",
    "moze", "mogu", "molim", "recite", "koliko", "kolika", "koliki", "cemu", "cega", "a", "ali", "pa", "jos",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D").replace("ß", "ss")
    text = text.lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def content_tokens(text: str) -> list[str]:
    """Lower-cased, diacritic-folded tokens without stopwords (used for coverage scoring too)."""
    return [t for t in normalize(text).split() if t not in _STOPWORDS and len(t) > 1]


def _features(text: str) -> list[tuple[str, float]]:
    toks = content_tokens(text)
    feats: list[tuple[str, float]] = []
    for t in toks:
        feats.append(("w:" + t, 1.0))
        padded = f"#{t}#"
        for n in (3, 4):
            for i in range(len(padded) - n + 1):
                feats.append((f"c{n}:" + padded[i : i + n], 0.4))
    for a, b in zip(toks, toks[1:]):
        feats.append((f"b:{a}_{b}", 0.8))
    return feats


class Embeddings(Protocol):
    name: str
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbeddings:
    name = "hash"
    model = "hashed-lexical-v1"

    def __init__(self, dim: int):
        self.dim = dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat, weight in _features(text):
            h = int.from_bytes(hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest(), "big")
            idx = h % self.dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class OllamaEmbeddings:
    name = "ollama"

    def __init__(self, base_url: str, model: str, dim: int, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        r = httpx.post(
            f"{self.base_url}/api/embed", json={"model": self.model, "input": texts}, timeout=self.timeout
        )
        r.raise_for_status()
        vectors = r.json()["embeddings"]
        for v in vectors:
            if len(v) != self.dim:
                raise ValueError(
                    f"embedding model {self.model} returns {len(v)}-d vectors but EMBEDDING_DIM={self.dim}"
                )
        return vectors


class SentenceTransformersEmbeddings:
    name = "sentence-transformers"

    def __init__(self, model: str, dim: int):
        from sentence_transformers import SentenceTransformer  # lazy: optional dependency

        self.model = model
        self.dim = dim
        self._m = SentenceTransformer(model)
        real = self._m.get_sentence_embedding_dimension()
        if real != dim:
            raise ValueError(f"{model} produces {real}-d vectors but EMBEDDING_DIM={dim}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._m.encode(texts, normalize_embeddings=True)]


_instance: Embeddings | None = None


def get_embeddings() -> Embeddings:
    global _instance
    if _instance is None:
        p = settings.embeddings_provider
        if p == "hash":
            _instance = HashEmbeddings(settings.embedding_dim)
        elif p == "ollama":
            _instance = OllamaEmbeddings(settings.ollama_url, settings.embeddings_model, settings.embedding_dim)
        elif p == "sentence-transformers":
            _instance = SentenceTransformersEmbeddings(settings.embeddings_model, settings.embedding_dim)
        else:
            raise ValueError(f"unknown EMBEDDINGS_PROVIDER {p}")
    return _instance


def min_similarity() -> float:
    if settings.rag_min_similarity is not None:
        return settings.rag_min_similarity
    return DEFAULT_MIN_SIMILARITY.get(settings.embeddings_provider, 0.6)
