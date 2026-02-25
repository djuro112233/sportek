"""
Sportek d.o.o. — Knowledge Guardian — RAG Engine
Retrieval-Augmented Generation engine that answers questions using
internal documents via TF-IDF retrieval — no external LLM required.

Usage:
    from modules.knowledge_guardian.rag_engine import RAGEngine
    engine = RAGEngine()
    result = engine.ask("Koji su koraci finalne inspekcije?")
"""

from __future__ import annotations

import csv
import re
import time
from datetime import datetime
from pathlib import Path

from .vector_store import VectorStore

MODULE_DIR = Path(__file__).resolve().parent
STORE_PATH = MODULE_DIR / "store" / "vector_index.pkl"
LOG_DIR = MODULE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
QUERY_LOG = LOG_DIR / "query_log.csv"

# Confidence threshold — below this we say "not enough info"
CONFIDENCE_THRESHOLD = 0.05


class RAGEngine:
    """Answer questions over Sportek internal docs using TF-IDF retrieval."""

    def __init__(self, vector_store_path: str | Path | None = None) -> None:
        self.store = VectorStore()
        path = Path(vector_store_path) if vector_store_path else STORE_PATH
        self.store.load_index(path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ask(self, question: str, top_k: int = 5) -> dict:
        t0 = time.perf_counter()

        results = self.store.search(question, top_k=top_k)
        top_score = results[0]["similarity_score"] if results else 0.0

        if top_score >= CONFIDENCE_THRESHOLD:
            answer = self._build_answer(question, results)
            confidence = round(min(top_score * 3.5, 1.0), 2)
        else:
            answer = (
                "Nemam dovoljno informacija u dostupnim dokumentima "
                "za odgovor na ovo pitanje."
            )
            confidence = round(top_score, 2)

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        sources = []
        for r in results:
            sources.append({
                "file": r["source_file"],
                "chunk_id": r["chunk_id"],
                "relevance": r["similarity_score"],
                "excerpt": r["text"][:100] + "...",
            })

        response = {
            "question": question,
            "answer": answer,
            "sources": sources,
            "confidence": confidence,
            "response_time_ms": elapsed_ms,
        }

        self._log_query(response)
        return response

    # ------------------------------------------------------------------
    # Answer construction (no LLM)
    # ------------------------------------------------------------------
    def _build_answer(self, question: str, results: list[dict]) -> str:
        """Construct a readable answer from retrieved chunks."""
        # Combine text from top 3 chunks for richer context
        parts: list[str] = []
        for r in results[:3]:
            if r["similarity_score"] > 0.04:
                parts.append(r["text"])
        combined = " ".join(parts)

        # Pick the most relevant paragraph
        best_paragraph = self._extract_best_paragraph(question, combined)

        # Build source citations
        seen_files: list[str] = []
        for r in results[:3]:
            fname = r["source_file"]
            if fname not in seen_files:
                seen_files.append(fname)

        primary = seen_files[0] if seen_files else "nepoznat izvor"
        source_tag = ", ".join(seen_files[:3])

        answer = (
            f"Na osnovu dokumenta [{primary}]: {best_paragraph} "
            f"(Izvori: {source_tag})"
        )
        return answer

    @staticmethod
    def _extract_best_paragraph(question: str, text: str) -> str:
        """Find the paragraph in *text* most related to *question*."""
        # Split into segments on double-newlines or section dividers
        paragraphs = re.split(r"\n\s*\n|={3,}|-{3,}", text)
        paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > 40]

        if not paragraphs:
            # Fall back to sentence splitting
            paragraphs = re.split(r"(?<=[.!?])\s+", text)
            paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > 20]

        if not paragraphs:
            return text[:500]

        # Filter out header / boilerplate / metadata paragraphs
        _header_re = re.compile(
            r"^(SPORTEK|STANDARDNA|Dokument:|Naziv:|Revizija:|Datum|Pripremio:|"
            r"Odobrio:|Klasifikacija:|SADRŽAJ|PLAN ODRŽAVANJA|PRIRUČNIK|"
            r"SPECIFIKACIJA|Document:|Title:|1\.\s|2\.\s|3\.\s)",
            re.IGNORECASE,
        )
        content_paras = [
            p for p in paragraphs
            if not _header_re.match(p) and len(p) > 80
        ]
        if not content_paras:
            content_paras = paragraphs

        # Keyword overlap scoring — prefer paragraphs with more query terms
        stop = {"su", "se", "za", "na", "je", "u", "i", "koji", "koja",
                "koje", "kako", "što", "iz", "sa", "od", "do", "li", "da",
                "the", "a", "an", "in", "of", "to", "for"}
        q_words = set(question.lower().split()) - stop
        best, best_score = content_paras[0], -1
        for para in content_paras:
            p_words = set(para.lower().split())
            overlap = len(q_words & p_words)
            # Bonus for longer, content-rich paragraphs
            length_bonus = min(len(para) / 500, 0.5)
            score = overlap + length_bonus
            if score > best_score:
                best_score = score
                best = para

        # Trim to ~500 chars for readability
        if len(best) > 500:
            best = best[:500].rsplit(" ", 1)[0] + "..."

        return best

    # ------------------------------------------------------------------
    # Query logging
    # ------------------------------------------------------------------
    def _log_query(self, response: dict) -> None:
        write_header = not QUERY_LOG.exists()
        with open(QUERY_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    "timestamp", "question", "answer_length",
                    "top_source", "confidence", "response_time_ms",
                ])
            top_src = response["sources"][0]["file"] if response["sources"] else ""
            writer.writerow([
                datetime.now().isoformat(timespec="seconds"),
                response["question"],
                len(response["answer"]),
                top_src,
                response["confidence"],
                response["response_time_ms"],
            ])
