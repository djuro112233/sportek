"""
Sportek d.o.o. — Knowledge Guardian — Document Processor
Loads internal .txt documents, splits into overlapping word-level chunks,
and persists the chunk index as JSON.

Usage:
    python modules/03_knowledge_guardian/doc_processor.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
DOCS_DIR = PROJECT_ROOT / "data" / "documents"
PROCESSED_DIR = MODULE_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


class DocumentProcessor:
    """Load Sportek internal documents and split them into searchable chunks."""

    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.chunks: list[dict] = []

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load_documents(self, docs_path: str | Path = DOCS_DIR) -> list[dict]:
        """Read every .txt file under *docs_path*."""
        docs_path = Path(docs_path)
        self.documents = []
        for txt in sorted(docs_path.glob("*.txt")):
            text = txt.read_text(encoding="utf-8")
            self.documents.append({
                "file_name": txt.name,
                "text": text,
                "word_count": len(text.split()),
            })
        return self.documents

    # ------------------------------------------------------------------
    # Chunk
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_title(text: str, file_name: str) -> str:
        """Try to pull a human-readable title from the document header."""
        for line in text.splitlines()[:20]:
            line = line.strip()
            if line.startswith("Naziv:"):
                return line.split(":", 1)[1].strip()
            if line.startswith("Document:") or line.startswith("Title:"):
                return line.split(":", 1)[1].strip()
        # Fallback: prettify the filename
        name = re.sub(r"\.txt$", "", file_name)
        return name.replace("_", " ")

    def chunk_document(
        self,
        text: str,
        source_file: str,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> list[dict]:
        """Split *text* into word-level chunks with overlap."""
        words = text.split()
        title = self._extract_title(text, source_file)

        # doc index for chunk_id prefix
        doc_idx = None
        for i, doc in enumerate(self.documents):
            if doc["file_name"] == source_file:
                doc_idx = i + 1
                break
        doc_tag = f"DOC_{doc_idx:03d}" if doc_idx else "DOC_000"

        chunks: list[dict] = []
        start = 0
        chunk_num = 0
        step = max(chunk_size - overlap, 1)

        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk_words = words[start:end]
            chunk_num += 1
            chunks.append({
                "chunk_id": f"{doc_tag}_CH_{chunk_num:03d}",
                "source_file": source_file,
                "text": " ".join(chunk_words),
                "word_count": len(chunk_words),
                "metadata": {
                    "document_title": title,
                },
            })
            if end >= len(words):
                break
            start += step

        return chunks

    # ------------------------------------------------------------------
    # Process all
    # ------------------------------------------------------------------
    def process_all(
        self,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> list[dict]:
        """Chunk every loaded document and return the combined list."""
        if not self.documents:
            self.load_documents()

        self.chunks = []
        for doc in self.documents:
            doc_chunks = self.chunk_document(
                doc["text"], doc["file_name"], chunk_size, overlap,
            )
            self.chunks.extend(doc_chunks)
        return self.chunks

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    def save_chunks(self, path: str | Path | None = None) -> Path:
        out = Path(path) if path else PROCESSED_DIR / "chunks.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(self.chunks, f, indent=2, ensure_ascii=False)
        return out

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def print_stats(self) -> None:
        BOLD = "\033[1m"
        CYAN = "\033[96m"
        GREEN = "\033[92m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        print()
        print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")
        print(f"{BOLD}{CYAN}  SPORTEK — Knowledge Guardian — Document Processing Stats{RESET}")
        print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")

        print(f"\n  Ukupno dokumenata:   {GREEN}{len(self.documents)}{RESET}")
        print(f"  Ukupno chunkova:     {GREEN}{len(self.chunks)}{RESET}")

        if self.chunks:
            sizes = [c["word_count"] for c in self.chunks]
            avg = sum(sizes) / len(sizes)
            print(f"  Prosječna veličina:  {avg:.0f} riječi/chunk")

        print(f"\n  {'Dokument':<45s} {'Chunkova':>8s}  {'Riječi':>8s}")
        print(f"  {'─' * 45}  {'─' * 8}  {'─' * 8}")

        for doc in self.documents:
            fname = doc["file_name"]
            n_chunks = sum(1 for c in self.chunks if c["source_file"] == fname)
            print(f"  {fname:<45s} {n_chunks:>8d}  {doc['word_count']:>8,}")

        print(f"\n{'=' * 65}\n")


# -----------------------------------------------------------------------
# CLI entry-point
# -----------------------------------------------------------------------
def main() -> None:
    proc = DocumentProcessor()
    proc.load_documents()
    proc.process_all()
    path = proc.save_chunks()
    proc.print_stats()
    print(f"  Chunks saved → {path}\n")


if __name__ == "__main__":
    main()
