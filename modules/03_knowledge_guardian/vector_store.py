"""
Sportek d.o.o. — Knowledge Guardian — TF-IDF Vector Store
Lightweight offline vector search over document chunks using scikit-learn.

Usage:
    python modules/03_knowledge_guardian/vector_store.py
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .doc_processor import DocumentProcessor

MODULE_DIR = Path(__file__).resolve().parent
STORE_DIR = MODULE_DIR / "store"
STORE_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR = MODULE_DIR / "processed"
INDEX_PATH = STORE_DIR / "vector_index.pkl"


class VectorStore:
    """TF-IDF search index over Knowledge Guardian chunks."""

    def __init__(self) -> None:
        self.vectorizer = TfidfVectorizer(
            max_features=3000,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        self.tfidf_matrix = None
        self.chunks: list[dict] = []

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def build_index(self, chunks: list[dict]) -> None:
        """Fit the TF-IDF vectorizer on chunk texts and store the matrix."""
        self.chunks = chunks
        texts = [c["text"] for c in chunks]
        self.tfidf_matrix = self.vectorizer.fit_transform(texts)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return the *top_k* most similar chunks for *query*."""
        if self.tfidf_matrix is None:
            raise RuntimeError("Index not built. Call build_index() first.")

        q_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self.tfidf_matrix).flatten()
        top_idx = np.argsort(scores)[::-1][:top_k]

        results = []
        for rank, idx in enumerate(top_idx, start=1):
            ch = self.chunks[idx]
            results.append({
                "chunk_id": ch["chunk_id"],
                "source_file": ch["source_file"],
                "text": ch["text"][:300] + ("..." if len(ch["text"]) > 300 else ""),
                "similarity_score": round(float(scores[idx]), 4),
                "rank": rank,
            })
        return results

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    def save_index(self, path: str | Path | None = None) -> Path:
        path = Path(path) if path else INDEX_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "vectorizer": self.vectorizer,
            "tfidf_matrix": self.tfidf_matrix,
            "chunks": self.chunks,
        }, path)
        return path

    def load_index(self, path: str | Path | None = None) -> None:
        path = Path(path) if path else INDEX_PATH
        data = joblib.load(path)
        self.vectorizer = data["vectorizer"]
        self.tfidf_matrix = data["tfidf_matrix"]
        self.chunks = data["chunks"]


# -----------------------------------------------------------------------
# CLI: build index + run demo queries
# -----------------------------------------------------------------------
def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    # ── Process documents ──────────────────────────────────────────────
    proc = DocumentProcessor()
    proc.load_documents()
    proc.process_all()
    proc.save_chunks()
    proc.print_stats()

    # ── Build vector index ─────────────────────────────────────────────
    store = VectorStore()
    store.build_index(proc.chunks)
    idx_path = store.save_index()

    vocab_size = len(store.vectorizer.vocabulary_)
    n_chunks, n_features = store.tfidf_matrix.shape

    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")
    print(f"{BOLD}{CYAN}  Knowledge Guardian — Vector Index Built{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")
    print(f"\n  Chunks indexed:    {GREEN}{n_chunks}{RESET}")
    print(f"  Vocabulary size:   {GREEN}{vocab_size}{RESET}")
    print(f"  Feature dimension: {GREEN}{n_features}{RESET}")
    print(f"  Index saved →      {idx_path}\n")

    # ── Demo queries ───────────────────────────────────────────────────
    queries = [
        "Koji su koraci finalne inspekcije kvaliteta?",
        "Kako se podešava SHIMA SEIKI mašina?",
        "Koji su Nike SMSI zahtjevi?",
    ]

    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")
    print(f"{BOLD}{CYAN}  Knowledge Guardian — Search Demo{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")

    for q in queries:
        print(f"\n  {BOLD}UPIT: {YELLOW}{q}{RESET}\n")
        results = store.search(q, top_k=3)
        for r in results:
            score_color = GREEN if r["similarity_score"] >= 0.2 else DIM
            print(f"    #{r['rank']}  {score_color}score={r['similarity_score']:.4f}{RESET}"
                  f"  {BOLD}{r['source_file']}{RESET}")
            # Show first 150 chars of text
            snippet = r["text"][:150].replace("\n", " ")
            print(f"        {DIM}{snippet}...{RESET}")
        print()

    print(f"{'=' * 65}\n")


if __name__ == "__main__":
    main()
