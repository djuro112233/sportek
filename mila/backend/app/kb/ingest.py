"""Knowledge-base ingestion: manifest loading, text extraction, versioned chunk storage.

Versioning rules (docs/architecture.md):

* ``SourceVersion.version_hash`` is the sha256 of the ingested file.
* Re-ingesting a file whose hash is already the current version is a no-op that returns
  the existing version.
* A new hash marks every older version ``is_current=False`` and deletes their chunks.
* ``Source.review_status`` is ``reviewed`` iff ``reviewed_by`` is non-empty in the manifest,
  else ``public_unreviewed``; a manifest entry may force ``status: blocked``.

Chunk ids are ``f"{source_id}:{version_hash[:8]}:{n}"`` with ``n`` counting from 0 in
document order. Chunks are embedded together with their heading path (``"<heading_path>\\n<text>"``)
so that section titles contribute to dense retrieval; ``Chunk.text`` holds the body only.

Nothing here touches user data; log lines carry document ids and counts only.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.config import Settings
from app.core.types import SUPPORTED_LANGS, TOPIC_CLASSES
from app.kb.chunker import PageText, chunk_pages, detect_heading
from app.kb.embed import Embedder, get_embedder
from app.models import Chunk, Source, SourceVersion

log = logging.getLogger("mila.kb")

ReviewStatus = Literal["reviewed", "public_unreviewed", "blocked"]

DOWNLOAD_TIMEOUT_S = 120.0
DEFAULT_MAX_TOKENS = 400
_DOWNLOAD_DIR = "downloads"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,59}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_PAGE_BREAK_LEVEL = 2  # .md/.txt sections at this heading level or above start a new page


class IngestError(ValueError):
    """A document could not be ingested (bad file, hash mismatch, unsupported type)."""


class ManifestDoc(BaseModel):
    """One entry of ``kb/manifest.yaml``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    publisher: str = ""
    year: int | None = None
    url: str = ""
    file: str
    licence: str = ""
    language: str = "en"
    published_on: str = ""
    sha256: str | None = None
    reviewed_by: str = ""
    reviewed_on: str = ""
    allowed_topics: list[str] = Field(default_factory=list)
    download: bool = False
    notes: str = ""
    status: ReviewStatus | None = None

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _ID_RE.match(value):
            raise ValueError("id must be lowercase [a-z0-9._-], 1-60 chars, starting with a letter or digit")
        return value

    @field_validator("file")
    @classmethod
    def _check_file(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or not value.strip():
            raise ValueError("file must be a relative path inside kb/ without '..'")
        return value

    @field_validator("language")
    @classmethod
    def _check_language(cls, value: str) -> str:
        if value not in SUPPORTED_LANGS:
            raise ValueError(f"language must be one of {SUPPORTED_LANGS}")
        return value

    @field_validator("sha256", mode="before")
    @classmethod
    def _check_sha256(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        value = str(value).strip().lower()
        if not _SHA256_RE.match(value):
            raise ValueError("sha256 must be 64 hex characters")
        return value

    @field_validator("allowed_topics")
    @classmethod
    def _check_topics(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(TOPIC_CLASSES))
        if unknown:
            raise ValueError(f"unknown allowed_topics {unknown}; expected a subset of {TOPIC_CLASSES}")
        return value

    @field_validator("published_on", "reviewed_on", mode="before")
    @classmethod
    def _dates_as_str(cls, value: object) -> str:
        # YAML parses bare dates into date objects; keep the ISO text.
        return "" if value is None else str(value)

    @property
    def review_status(self) -> str:
        """``blocked`` when forced in the manifest; else ``reviewed`` iff ``reviewed_by`` is set."""
        if self.status == "blocked":
            return "blocked"
        return "reviewed" if self.reviewed_by.strip() else "public_unreviewed"


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    documents: list[ManifestDoc]

    @model_validator(mode="after")
    def _check(self) -> Manifest:
        if self.version != 1:
            raise ValueError(f"unsupported manifest version {self.version}; expected 1")
        seen: set[str] = set()
        for doc in self.documents:
            if doc.id in seen:
                raise ValueError(f"duplicate manifest id: {doc.id}")
            seen.add(doc.id)
        return self


class IngestReport(BaseModel):
    """Outcome of :func:`ingest_manifest`; ids refer to manifest entries."""

    ingested: list[str] = Field(default_factory=list)
    skipped_unchanged: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    downloaded: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
    chunks_by_doc: dict[str, int] = Field(default_factory=dict)
    chunks_added: int = 0
    chunks_current: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def load_manifest(path: str | Path) -> list[ManifestDoc]:
    """Parse and validate ``kb/manifest.yaml``; raises ``ValueError`` on schema problems."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"manifest {path} must be a mapping with 'version' and 'documents'")
    return Manifest.model_validate(data).documents


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --- text extraction -------------------------------------------------------------------------
class _HTMLToText(HTMLParser):
    """Minimal HTML -> markdown-ish text: headings become ``#`` lines, blocks become paragraphs."""

    _SKIP = {"script", "style", "noscript", "head", "nav", "footer", "svg"}
    _BLOCK = {"p", "div", "li", "ul", "ol", "br", "section", "article", "table", "tr", "blockquote", "figure"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._heading: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            self._heading = int(tag[1])
            self.parts.append("\n\n" + "#" * self._heading + " ")
        elif tag in self._BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            self._heading = None
            self.parts.append("\n\n")
        elif tag in self._BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(" ".join(data.split()) if self._heading else data)

    def text(self) -> str:
        return "".join(self.parts)


def _html_to_text(html: str) -> str:
    parser = _HTMLToText()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in parser.text().splitlines()]
    return "\n".join(lines)


def _split_text_pages(text: str, *, markdown: bool) -> list[PageText]:
    """Split plain text into 'pages' at headings of level <= ``_PAGE_BREAK_LEVEL``."""
    pages: list[PageText] = []
    current: list[str] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if markdown:
            level = len(stripped) - len(stripped.lstrip("#")) if _MD_HEADING_RE.match(stripped) else 0
        else:
            next_line = next((ln for ln in lines[idx + 1 :] if ln.strip()), None)
            found = detect_heading(stripped, next_line)
            level = found[0] if found else 0
        if 0 < level <= _PAGE_BREAK_LEVEL and any(ln.strip() for ln in current):
            pages.append(PageText(page=len(pages) + 1, text="\n".join(current).strip()))
            current = []
        current.append(line)
    if any(ln.strip() for ln in current):
        pages.append(PageText(page=len(pages) + 1, text="\n".join(current).strip()))
    return pages


def extract_pages(file_path: Path) -> list[PageText]:
    """Extract text pages: ``.pdf`` via pypdf (physical pages), ``.md``/``.txt``/``.html`` one page per section.

    Blank pages are dropped; page numbers of PDFs stay physical (1-based), so citations
    point at the real page.
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(file_path))
        pages: list[PageText] = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(PageText(page=index, text=text))
        return pages
    if suffix in (".md", ".markdown", ".txt", ".html", ".htm"):
        raw = file_path.read_text(encoding="utf-8")
        if suffix in (".html", ".htm"):
            raw = _html_to_text(raw)
            suffix = ".md"
        raw = _HTML_COMMENT_RE.sub("", raw)
        return _split_text_pages(raw, markdown=suffix in (".md", ".markdown"))
    raise IngestError(f"unsupported file type '{suffix}' for {file_path.name}")


# --- database writes ---------------------------------------------------------------------------
def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def _upsert_source(db: DbSession, doc: ManifestDoc) -> Source:
    source = db.get(Source, doc.id)
    if source is None:
        source = Source(id=doc.id, title=doc.title)
        db.add(source)
    source.title = doc.title
    source.publisher = doc.publisher
    source.year = doc.year
    source.url = doc.url
    source.licence = doc.licence
    source.lang = doc.language
    source.allowed_topics = list(doc.allowed_topics)
    # A review status set at runtime through the admin API survives a manifest re-ingest:
    # a block always wins, and a clinician's sign-off is kept unless the manifest itself
    # names a reviewer (then the manifest is the record).
    runtime_blocked = source.review_status == "blocked" and doc.status != "blocked"
    runtime_reviewed = (
        source.review_status == "reviewed" and bool(source.reviewed_by) and not doc.reviewed_by.strip()
    )
    if runtime_blocked:
        log.warning("ingest: %s stays blocked (set at runtime); manifest status ignored", doc.id)
    elif runtime_reviewed:
        log.info("ingest: %s keeps its runtime review by %s", doc.id, source.reviewed_by)
    else:
        source.review_status = doc.review_status
        source.reviewed_by = doc.reviewed_by
        source.reviewed_on = _parse_date(doc.reviewed_on)
    return source


def _retire_other_versions(db: DbSession, source_id: str, keep_version_id: int | None) -> None:
    versions = db.scalars(select(SourceVersion).where(SourceVersion.source_id == source_id)).all()
    for version in versions:
        if version.id == keep_version_id:
            continue
        version.is_current = False
        db.execute(delete(Chunk).where(Chunk.version_id == version.id))


def ingest_document(
    db: DbSession,
    doc: ManifestDoc,
    file_path: Path,
    embedder: Embedder,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> SourceVersion:
    """Ingest one file for a manifest entry, honouring the sha256 versioning rules.

    Source metadata (title, review status, ...) is refreshed from the manifest even when the
    file is unchanged, so a manifest-only edit (e.g. a clinician sign-off) needs no re-chunking.
    """
    version, _changed = _ingest(db, doc, Path(file_path), embedder, max_tokens)
    return version


def _ingest(
    db: DbSession, doc: ManifestDoc, file_path: Path, embedder: Embedder, max_tokens: int
) -> tuple[SourceVersion, bool]:
    """Body of :func:`ingest_document`; the flag is False for the unchanged-hash no-op."""
    if not file_path.is_file():
        raise IngestError(f"file not found: {file_path}")
    version_hash = sha256_file(file_path)
    if doc.sha256 and doc.sha256 != version_hash:
        raise IngestError(
            f"sha256 mismatch for {doc.id}: manifest {doc.sha256[:8]}..., file {version_hash[:8]}..."
        )

    source = _upsert_source(db, doc)
    existing = db.scalars(
        select(SourceVersion).where(
            SourceVersion.source_id == doc.id, SourceVersion.version_hash == version_hash
        )
    ).first()
    if existing is not None and existing.is_current:
        db.commit()
        log.info("kb: %s unchanged (version %s)", doc.id, version_hash[:8])
        return existing, False

    pages = extract_pages(file_path)
    drafts = chunk_pages(pages, max_tokens=max_tokens)
    if not drafts:
        db.rollback()
        raise IngestError(f"no text could be extracted from {file_path.name} ({doc.id})")

    version = existing or SourceVersion(source_id=source.id, version_hash=version_hash)
    version.file_name = file_path.name
    version.published_on = doc.published_on
    version.is_current = True
    version.n_chunks = len(drafts)
    db.add(version)
    db.flush()
    _retire_other_versions(db, source.id, version.id)

    texts = [f"{d.heading_path}\n{d.text}" if d.heading_path else d.text for d in drafts]
    vectors = embedder.embed(texts)
    for n, (draft, vector) in enumerate(zip(drafts, vectors, strict=True)):
        db.add(
            Chunk(
                id=f"{doc.id}:{version_hash[:8]}:{n}",
                source_id=source.id,
                version_id=version.id,
                page=draft.page,
                heading_path=draft.heading_path[:500],
                text=draft.text,
                lang=doc.language,
                token_count=draft.token_count,
                embedding=vector,
            )
        )
    db.commit()
    log.info("kb: ingested %s version %s (%d chunks)", doc.id, version_hash[:8], len(drafts))
    return version, True


# --- downloads ---------------------------------------------------------------------------------
def _download_target(kb_dir: Path, doc: ManifestDoc) -> Path:
    rel = Path(doc.file)
    if rel.parts and rel.parts[0] == _DOWNLOAD_DIR:
        return kb_dir / rel
    return kb_dir / _DOWNLOAD_DIR / rel.name


def download_document(doc: ManifestDoc, target: Path) -> Path:
    """Stream ``doc.url`` into ``target`` (via a ``.part`` file), verifying sha256 when the manifest sets it."""
    if not doc.url:
        raise IngestError(f"{doc.id}: download requested but no url in manifest")
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with httpx.Client(trust_env=True, timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True) as client:
            with client.stream("GET", doc.url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if target.suffix.lower() == ".pdf" and "html" in content_type:
                    raise IngestError(
                        f"{doc.id}: url returned {content_type}, not a PDF; set url to the direct PDF link"
                    )
                with open(part, "wb") as fh:
                    for block in response.iter_bytes():
                        digest.update(block)
                        fh.write(block)
        actual = digest.hexdigest()
        if doc.sha256 and actual != doc.sha256:
            raise IngestError(
                f"{doc.id}: downloaded sha256 {actual[:8]}... does not match manifest {doc.sha256[:8]}..."
            )
        part.replace(target)
    except (httpx.HTTPError, OSError) as exc:
        raise IngestError(f"{doc.id}: download failed ({exc.__class__.__name__})") from exc
    finally:
        part.unlink(missing_ok=True)
    return target


def ingest_manifest(
    db: DbSession,
    settings: Settings,
    embedder: Embedder | None = None,
    *,
    only: set[str] | None = None,
    download: bool = False,
) -> IngestReport:
    """Ingest every manifest entry (or the ``only`` subset); never raises for a single bad document."""
    embedder = embedder or get_embedder(settings)
    kb_dir = Path(settings.kb_dir)
    report = IngestReport()
    docs = load_manifest(settings.manifest_path)
    if only is not None:
        known = {d.id for d in docs}
        for missing_id in sorted(only - known):
            report.errors[missing_id] = "not in manifest"
        docs = [d for d in docs if d.id in only]

    for doc in docs:
        file_path = kb_dir / doc.file
        if not file_path.is_file() and download and doc.download:
            try:
                file_path = download_document(doc, _download_target(kb_dir, doc))
                report.downloaded.append(doc.id)
            except IngestError as exc:
                report.errors[doc.id] = str(exc)
                continue
        if not file_path.is_file():
            report.missing_files.append(doc.id)
            continue
        try:
            version, changed = _ingest(db, doc, file_path, embedder, DEFAULT_MAX_TOKENS)
        except Exception as exc:
            db.rollback()
            report.errors[doc.id] = f"{exc.__class__.__name__}: {exc}"
            log.warning("kb: failed to ingest %s: %s", doc.id, exc.__class__.__name__)
            continue
        report.chunks_by_doc[doc.id] = version.n_chunks
        if changed:
            report.ingested.append(doc.id)
            report.chunks_added += version.n_chunks
        else:
            report.skipped_unchanged.append(doc.id)
    report.chunks_current = current_chunk_count(db)
    return report


def current_chunk_count(db: DbSession, source_id: str | None = None) -> int:
    """Number of chunks belonging to current source versions (optionally for one source)."""
    stmt = (
        select(Chunk.id)
        .join(SourceVersion, Chunk.version_id == SourceVersion.id)
        .where(SourceVersion.is_current)
    )
    if source_id is not None:
        stmt = stmt.where(Chunk.source_id == source_id)
    return len(db.scalars(stmt).all())
