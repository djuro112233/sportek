"""RAG index maintenance. Only *approved* heritage entries are ever embedded; the index is rebuilt
on approval and removed the moment an entry leaves the approved state."""
from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import EntryChunk, HeritageEntry
from ..providers.embeddings import get_embeddings

log = logging.getLogger(__name__)
MAX_CHUNK_CHARS = 700


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on paragraphs, then sentences, into chunks of at most ``max_chars``."""
    chunks: list[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = " ".join(para.split())
        if not para:
            continue
        if len(para) <= max_chars:
            chunks.append(para)
            continue
        current = ""
        for sentence in re.split(r"(?<=[.!?])\s+", para):
            if len(current) + len(sentence) + 1 > max_chars and current:
                chunks.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current.strip())
    return chunks


def build_chunks(entry: HeritageEntry) -> list[tuple[str, int, str]]:
    """(lang, index, text) for both languages. The title is prepended to every chunk so short
    questions about the entry's name match every chunk."""
    out: list[tuple[str, int, str]] = []
    for lang, title, summary, body in (
        ("local", entry.title_local, entry.summary_local, entry.body_local),
        ("en", entry.title_en, entry.summary_en, entry.body_en),
    ):
        full = "\n\n".join(p for p in (summary, body) if p and p.strip())
        pieces = chunk_text(full) or [title]
        for i, piece in enumerate(pieces):
            out.append((lang, i, f"{title}. {piece}"))
    return out


def remove_entry_index(db: Session, entry_id: uuid.UUID) -> None:
    db.execute(delete(EntryChunk).where(EntryChunk.entry_id == entry_id))
    db.flush()


def reindex_entry(db: Session, entry_id: uuid.UUID) -> int:
    """Rebuild the chunks of one entry. Returns the number of chunks written (0 if not approved)."""
    entry = db.get(HeritageEntry, entry_id)
    remove_entry_index(db, entry_id)
    if entry is None or entry.status != "approved":
        return 0
    emb = get_embeddings()
    pieces = build_chunks(entry)
    vectors = emb.embed([p[2] for p in pieces])
    for (lang, idx, text), vec in zip(pieces, vectors):
        db.add(
            EntryChunk(
                entry_id=entry.id,
                lang=lang,
                chunk_index=idx,
                text=text,
                source=entry.source,
                embedding_provider=f"{emb.name}:{emb.model}",
                embedding=vec,
            )
        )
    db.flush()
    return len(pieces)


def reindex_all_approved(db: Session) -> int:
    ids = db.scalars(select(HeritageEntry.id)).all()
    total = 0
    for eid in ids:
        total += reindex_entry(db, eid)
    db.commit()
    log.info("reindexed %d chunks", total)
    return total
