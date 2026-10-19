"""Tests for app.kb.ingest: manifest schema, text extraction, sha256 versioning, downloads."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml
from conftest import REPO_ROOT, make_test_settings
from fpdf import FPDF
from sqlalchemy import select

from app.core.types import TOPIC_CLASSES
from app.kb import ingest as ingest_module
from app.kb.embed import HashEmbedder
from app.kb.ingest import (
    IngestError,
    IngestReport,
    ManifestDoc,
    extract_pages,
    ingest_document,
    ingest_manifest,
    load_manifest,
    sha256_file,
)
from app.models import Chunk, Source, SourceVersion

MANIFEST_PATH = REPO_ROOT / "kb" / "manifest.yaml"
DEMO_HEADER = "<!-- DEMO CONTENT: project-authored paraphrase of WHO guidance"

SAMPLE_MD = """<!-- licence comment that must never reach a chunk -->
# Demo guide

Intro sentence for the guide. Another intro sentence.

## First section

First section body. It has two sentences.

## Second section

Second section body here.

### Nested

Nested body text.
"""


def _doc(**overrides) -> ManifestDoc:
    base = dict(id="doc-a", title="Doc A", file="doc-a.md", language="en", published_on="2026-01-02")
    base.update(overrides)
    return ManifestDoc(**base)


def _write_manifest(path: Path, docs: list[dict]) -> None:
    path.write_text(yaml.safe_dump({"version": 1, "documents": docs}, allow_unicode=True), encoding="utf-8")


def _make_pdf(path: Path, pages: list[str]) -> None:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in pages:
        pdf.add_page()
        if text:
            pdf.multi_cell(0, 8, text)
    pdf.output(str(path))


@pytest.fixture
def kb(tmp_path: Path):
    """A throw-away kb/ directory with one markdown document and matching settings."""
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "doc-a.md").write_text(SAMPLE_MD, encoding="utf-8")
    settings = make_test_settings(tmp_path, kb_dir=str(kb_dir), manifest_path=str(kb_dir / "manifest.yaml"))
    return kb_dir, settings


# --- manifest ----------------------------------------------------------------------------------
def test_real_manifest_loads_and_is_consistent() -> None:
    docs = load_manifest(MANIFEST_PATH)
    ids = [d.id for d in docs]
    assert len(ids) == len(set(ids))
    who = [d for d in docs if d.id.startswith("who-")]
    demo = [d for d in docs if d.id.startswith("demo-")]
    assert len(who) == 5
    assert len(demo) == 22
    for doc in who:
        assert doc.download is True
        assert doc.licence == "CC BY-NC-SA 3.0 IGO"
        assert doc.reviewed_by == ""
        assert doc.file.startswith("downloads/")
        assert "verify licence + sha256 on first download" in doc.notes
        assert doc.url.startswith(("https://iris.who.int/", "https://www.who.int/"))
    assert sum(d.language == "en" for d in demo) == 11
    assert sum(d.language == "sr" for d in demo) == 11
    for doc in demo:
        assert doc.licence == "Apache-2.0"
        assert doc.publisher == "MILA project (paraphrase of WHO guidance; demo only)"
        assert doc.review_status == "public_unreviewed"
        assert doc.allowed_topics and set(doc.allowed_topics) <= set(TOPIC_CLASSES)
        path = REPO_ROOT / "kb" / doc.file
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith(DEMO_HEADER), doc.id
        assert 35 <= len(lines) <= 70, doc.id
        assert lines[1].startswith("# "), doc.id
        assert any(line.startswith("## ") for line in lines), doc.id


def test_manifest_doc_review_status_rules() -> None:
    assert _doc().review_status == "public_unreviewed"
    assert _doc(reviewed_by="   ").review_status == "public_unreviewed"
    assert _doc(reviewed_by="Dr Example", reviewed_on="2026-02-03").review_status == "reviewed"
    assert _doc(reviewed_by="Dr Example", status="blocked").review_status == "blocked"
    assert _doc(sha256="").sha256 is None
    assert _doc(sha256="A" * 64).sha256 == "a" * 64


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "Bad Id"},
        {"file": "../outside.md"},
        {"file": "/abs/path.md"},
        {"language": "de"},
        {"allowed_topics": ["nonsense"]},
        {"sha256": "zz"},
        {"status": "secret"},
        {"unknown_field": 1},
    ],
)
def test_manifest_doc_validation_errors(bad: dict) -> None:
    with pytest.raises(ValueError):
        _doc(**bad)


def test_load_manifest_rejects_bad_versions_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    entry = {"id": "x", "title": "X", "file": "x.md"}
    _write_manifest(path, [entry, dict(entry)])
    with pytest.raises(ValueError, match="duplicate"):
        load_manifest(path)
    path.write_text(yaml.safe_dump({"version": 2, "documents": [entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        load_manifest(path)
    path.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest(path)


# --- extraction ---------------------------------------------------------------------------------
def test_extract_pages_markdown_splits_on_headings_and_drops_comments(kb) -> None:
    kb_dir, _ = kb
    pages = extract_pages(kb_dir / "doc-a.md")
    assert [p.page for p in pages] == [1, 2, 3]
    assert pages[0].text.startswith("# Demo guide")
    assert pages[1].text.startswith("## First section")
    assert "### Nested" in pages[2].text  # level-3 headings do not start a page
    assert all("<!--" not in p.text and "licence comment" not in p.text for p in pages)


def test_extract_pages_txt_uses_heuristic_headings(tmp_path: Path) -> None:
    path = tmp_path / "doc.txt"
    path.write_text(
        "1 INTRODUCTION\nIntro text here.\n2 METHODS\nMethods text here.\n2.1 Sampling\nSampling text.\n",
        encoding="utf-8",
    )
    pages = extract_pages(path)
    assert [p.page for p in pages] == [1, 2, 3]
    assert pages[1].text.startswith("2 METHODS")
    assert pages[2].text.startswith("2.1 Sampling")  # level-2 headings start a page, like "##"


def test_extract_pages_pdf_keeps_physical_page_numbers(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    _make_pdf(path, ["Page one talks about antenatal visits.", "", "Page three talks about danger signs."])
    pages = extract_pages(path)
    assert [p.page for p in pages] == [1, 3]
    assert "antenatal visits" in pages[0].text
    assert "danger signs" in pages[1].text


def test_extract_pages_html_converts_headings(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><title>T</title><style>p{}</style></head><body><nav>skip me</nav>"
        "<h1>Adolescent pregnancy</h1><p>Key facts here.</p><h2>Overview</h2><p>Overview text.</p>"
        "<script>alert(1)</script></body></html>",
        encoding="utf-8",
    )
    pages = extract_pages(path)
    assert [p.page for p in pages] == [1, 2]
    assert pages[0].text.startswith("# Adolescent pregnancy")
    assert "Key facts here." in pages[0].text
    assert pages[1].text.startswith("## Overview")
    joined = "\n".join(p.text for p in pages)
    assert "skip me" not in joined and "alert" not in joined


def test_extract_pages_unsupported_type(tmp_path: Path) -> None:
    path = tmp_path / "doc.docx"
    path.write_bytes(b"PK")
    with pytest.raises(IngestError):
        extract_pages(path)


# --- ingest_document ----------------------------------------------------------------------------
def test_ingest_markdown_document_creates_source_version_and_chunks(db, kb) -> None:
    kb_dir, _ = kb
    doc = _doc(
        publisher="Pub",
        year=2026,
        url="https://example.org",
        licence="Apache-2.0",
        allowed_topics=["pregnancy"],
    )
    version = ingest_document(db, doc, kb_dir / "doc-a.md", HashEmbedder(dim=64))

    source = db.get(Source, "doc-a")
    assert source is not None
    assert (source.title, source.publisher, source.year, source.licence, source.lang) == (
        "Doc A",
        "Pub",
        2026,
        "Apache-2.0",
        "en",
    )
    assert source.allowed_topics == ["pregnancy"]
    assert source.review_status == "public_unreviewed"

    assert version.is_current is True
    assert version.version_hash == sha256_file(kb_dir / "doc-a.md")
    assert version.published_on == "2026-01-02"
    assert version.file_name == "doc-a.md"

    chunks = db.scalars(select(Chunk).where(Chunk.source_id == "doc-a").order_by(Chunk.id)).all()
    assert len(chunks) == version.n_chunks == 4
    prefix = f"doc-a:{version.version_hash[:8]}:"
    assert sorted(c.id for c in chunks) == sorted(f"{prefix}{n}" for n in range(4))
    assert {c.heading_path for c in chunks} == {
        "Demo guide",
        "Demo guide > First section",
        "Demo guide > Second section",
        "Demo guide > Second section > Nested",
    }
    assert all(c.lang == "en" and c.version_id == version.id and len(c.embedding) == 64 for c in chunks)
    assert all(c.token_count > 0 and "<!--" not in c.text for c in chunks)
    assert {c.page for c in chunks} == {1, 2, 3}


def test_ingest_pdf_document_records_pdf_pages(db, tmp_path: Path) -> None:
    path = tmp_path / "guide.pdf"
    _make_pdf(
        path, ["First page about antenatal care contacts.", "Second page about postnatal care contacts."]
    )
    version = ingest_document(db, _doc(id="pdf-doc", file="guide.pdf"), path, HashEmbedder(dim=32))
    chunks = db.scalars(select(Chunk).where(Chunk.version_id == version.id)).all()
    assert sorted(c.page for c in chunks) == [1, 2]
    assert any("antenatal" in c.text for c in chunks)


def test_reingesting_same_hash_is_a_noop(db, kb) -> None:
    kb_dir, _ = kb
    embedder = HashEmbedder(dim=32)
    first = ingest_document(db, _doc(), kb_dir / "doc-a.md", embedder)
    ids_before = sorted(db.scalars(select(Chunk.id)).all())
    second = ingest_document(db, _doc(), kb_dir / "doc-a.md", embedder)
    assert second.id == first.id
    assert sorted(db.scalars(select(Chunk.id)).all()) == ids_before
    assert db.scalars(select(SourceVersion)).all().__len__() == 1


def test_new_hash_supersedes_old_version_and_deletes_its_chunks(db, kb) -> None:
    kb_dir, _ = kb
    embedder = HashEmbedder(dim=32)
    old = ingest_document(db, _doc(), kb_dir / "doc-a.md", embedder)
    old_ids = set(db.scalars(select(Chunk.id)).all())
    (kb_dir / "doc-a.md").write_text(
        SAMPLE_MD + "\n## Third section\n\nBrand new text about a third section.\n", encoding="utf-8"
    )
    new = ingest_document(db, _doc(), kb_dir / "doc-a.md", embedder)

    assert new.id != old.id and new.version_hash != old.version_hash
    db.refresh(old)
    assert old.is_current is False and new.is_current is True
    current_ids = set(db.scalars(select(Chunk.id)).all())
    assert current_ids.isdisjoint(old_ids)
    assert all(cid.startswith(f"doc-a:{new.version_hash[:8]}:") for cid in current_ids)
    assert len(current_ids) == new.n_chunks == 5


def test_rolling_back_to_an_older_hash_reactivates_it(db, kb) -> None:
    kb_dir, _ = kb
    embedder = HashEmbedder(dim=32)
    v1 = ingest_document(db, _doc(), kb_dir / "doc-a.md", embedder)
    (kb_dir / "doc-a.md").write_text(SAMPLE_MD + "\nExtra line.\n", encoding="utf-8")
    v2 = ingest_document(db, _doc(), kb_dir / "doc-a.md", embedder)
    (kb_dir / "doc-a.md").write_text(SAMPLE_MD, encoding="utf-8")
    again = ingest_document(db, _doc(), kb_dir / "doc-a.md", embedder)
    db.refresh(v2)
    assert again.id == v1.id and again.is_current is True and v2.is_current is False
    assert all(cid.startswith(f"doc-a:{v1.version_hash[:8]}:") for cid in db.scalars(select(Chunk.id)).all())
    assert len(db.scalars(select(Chunk.id)).all()) == v1.n_chunks


def test_manifest_metadata_refresh_does_not_rechunk(db, kb) -> None:
    kb_dir, _ = kb
    embedder = HashEmbedder(dim=32)
    first = ingest_document(db, _doc(), kb_dir / "doc-a.md", embedder)
    second = ingest_document(
        db,
        _doc(reviewed_by="Dr Example", reviewed_on="2026-03-04", title="Doc A v2"),
        kb_dir / "doc-a.md",
        embedder,
    )
    assert second.id == first.id
    source = db.get(Source, "doc-a")
    assert source.review_status == "reviewed"
    assert source.reviewed_by == "Dr Example"
    assert source.reviewed_on is not None and source.reviewed_on.year == 2026
    assert source.title == "Doc A v2"


def test_sha256_mismatch_raises_and_writes_nothing(db, kb) -> None:
    kb_dir, _ = kb
    with pytest.raises(IngestError, match="sha256 mismatch"):
        ingest_document(db, _doc(sha256="0" * 64), kb_dir / "doc-a.md", HashEmbedder(dim=32))
    assert db.get(Source, "doc-a") is None


def test_matching_sha256_is_accepted(db, kb) -> None:
    kb_dir, _ = kb
    digest = sha256_file(kb_dir / "doc-a.md")
    version = ingest_document(db, _doc(sha256=digest), kb_dir / "doc-a.md", HashEmbedder(dim=32))
    assert version.version_hash == digest


def test_missing_file_raises(db, tmp_path: Path) -> None:
    with pytest.raises(IngestError, match="not found"):
        ingest_document(db, _doc(), tmp_path / "nope.md", HashEmbedder(dim=32))


# --- ingest_manifest ----------------------------------------------------------------------------
def test_ingest_manifest_report_covers_every_outcome(db, kb) -> None:
    kb_dir, settings = kb
    (kb_dir / "blocked.md").write_text(
        "# Blocked\n\nThis text must never be answered from.\n", encoding="utf-8"
    )
    (kb_dir / "broken.xyz").write_text("binary-ish", encoding="utf-8")
    _write_manifest(
        kb_dir / "manifest.yaml",
        [
            {"id": "doc-a", "title": "Doc A", "file": "doc-a.md"},
            {"id": "doc-missing", "title": "Missing", "file": "missing.md"},
            {
                "id": "doc-blocked",
                "title": "Blocked",
                "file": "blocked.md",
                "status": "blocked",
                "reviewed_by": "Dr X",
            },
            {"id": "doc-broken", "title": "Broken", "file": "broken.xyz"},
        ],
    )
    report = ingest_manifest(db, settings)
    assert isinstance(report, IngestReport)
    assert report.ingested == ["doc-a", "doc-blocked"]
    assert report.missing_files == ["doc-missing"]
    assert set(report.errors) == {"doc-broken"} and "unsupported file type" in report.errors["doc-broken"]
    assert report.skipped_unchanged == [] and report.downloaded == []
    assert report.chunks_by_doc == {"doc-a": 4, "doc-blocked": 1}
    assert report.chunks_added == 5 and report.chunks_current == 5
    assert report.ok is False
    assert db.get(Source, "doc-blocked").review_status == "blocked"
    assert db.get(Source, "doc-broken") is None

    second = ingest_manifest(db, settings)
    assert second.ingested == [] and second.skipped_unchanged == ["doc-a", "doc-blocked"]
    assert second.chunks_added == 0 and second.chunks_current == 5


def test_ingest_manifest_only_filter_and_unknown_ids(db, kb) -> None:
    kb_dir, settings = kb
    _write_manifest(kb_dir / "manifest.yaml", [{"id": "doc-a", "title": "Doc A", "file": "doc-a.md"}])
    report = ingest_manifest(db, settings, HashEmbedder(dim=16), only={"doc-a", "ghost"})
    assert report.ingested == ["doc-a"]
    assert report.errors == {"ghost": "not in manifest"}
    assert len(db.scalars(select(Chunk)).first().embedding) == 16


def test_missing_who_files_are_handled_gracefully_with_the_real_manifest(db, tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    who_ids = {d.id for d in load_manifest(settings.manifest_path) if d.id.startswith("who-")}
    report = ingest_manifest(db, settings, HashEmbedder(dim=16), only=who_ids)
    assert set(report.missing_files) == who_ids
    assert report.errors == {} and report.ingested == []


# --- downloads ----------------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.body = body
        self.headers = {"content-type": content_type}
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise httpx.HTTPError(f"status {self.status}")

    def iter_bytes(self) -> Iterator[bytes]:
        for i in range(0, len(self.body), 7):
            yield self.body[i : i + 7]


def _install_fake_client(monkeypatch, response: _FakeResponse | Exception, seen: dict) -> None:
    class _FakeClient:
        def __init__(self, **kwargs) -> None:
            seen.update(kwargs)

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *exc) -> None:
            return None

        def stream(self, method: str, url: str):
            seen["method"], seen["url"] = method, url
            if isinstance(response, Exception):
                raise response
            return response

    monkeypatch.setattr(ingest_module.httpx, "Client", _FakeClient)


def test_download_fetches_verifies_and_ingests(db, kb, monkeypatch) -> None:
    kb_dir, settings = kb
    body = b"# Remote guide\n\nRemote text about contraception.\n"
    import hashlib

    digest = hashlib.sha256(body).hexdigest()
    seen: dict = {}
    _install_fake_client(monkeypatch, _FakeResponse(body, "text/markdown"), seen)
    _write_manifest(
        kb_dir / "manifest.yaml",
        [
            {
                "id": "remote",
                "title": "Remote",
                "file": "downloads/remote.md",
                "url": "https://example.org/r.md",
                "download": True,
                "sha256": digest,
            }
        ],
    )
    report = ingest_manifest(db, settings, HashEmbedder(dim=16), download=True)
    assert report.downloaded == ["remote"] and report.ingested == ["remote"] and report.errors == {}
    assert (kb_dir / "downloads" / "remote.md").read_bytes() == body
    assert not (kb_dir / "downloads" / "remote.md.part").exists()
    assert (
        seen["trust_env"] is True and seen["timeout"] == 120.0 and seen["url"] == "https://example.org/r.md"
    )

    # Without --download (or when download: false) a missing file is just reported.
    (kb_dir / "downloads" / "remote.md").unlink()
    assert ingest_manifest(db, settings, HashEmbedder(dim=16), download=False).missing_files == ["remote"]


def test_download_sha256_mismatch_is_an_error_and_leaves_no_file(db, kb, monkeypatch) -> None:
    kb_dir, settings = kb
    _install_fake_client(monkeypatch, _FakeResponse(b"# X\n\nbody.\n", "text/markdown"), {})
    _write_manifest(
        kb_dir / "manifest.yaml",
        [
            {
                "id": "remote",
                "title": "Remote",
                "file": "downloads/remote.md",
                "url": "https://example.org/r.md",
                "download": True,
                "sha256": "1" * 64,
            }
        ],
    )
    report = ingest_manifest(db, settings, HashEmbedder(dim=16), download=True)
    assert "sha256" in report.errors["remote"] and report.downloaded == []
    assert not (kb_dir / "downloads" / "remote.md").exists()
    assert not list((kb_dir / "downloads").glob("*.part"))


def test_download_network_failure_is_recorded_and_ingest_continues(db, kb, monkeypatch) -> None:
    kb_dir, settings = kb
    _install_fake_client(monkeypatch, httpx.ConnectError("refused"), {})
    _write_manifest(
        kb_dir / "manifest.yaml",
        [
            {
                "id": "remote",
                "title": "Remote",
                "file": "downloads/remote.pdf",
                "url": "https://example.org/r.pdf",
                "download": True,
            },
            {"id": "doc-a", "title": "Doc A", "file": "doc-a.md"},
        ],
    )
    report = ingest_manifest(db, settings, HashEmbedder(dim=16), download=True)
    assert "download failed" in report.errors["remote"] and "ConnectError" in report.errors["remote"]
    assert report.ingested == ["doc-a"]


def test_download_refuses_html_for_pdf_target(db, kb, monkeypatch) -> None:
    kb_dir, settings = kb
    _install_fake_client(
        monkeypatch, _FakeResponse(b"<html>landing page</html>", "text/html; charset=utf-8"), {}
    )
    _write_manifest(
        kb_dir / "manifest.yaml",
        [
            {
                "id": "remote",
                "title": "Remote",
                "file": "downloads/remote.pdf",
                "url": "https://example.org/landing",
                "download": True,
            }
        ],
    )
    report = ingest_manifest(db, settings, HashEmbedder(dim=16), download=True)
    assert "not a PDF" in report.errors["remote"]
    assert not (kb_dir / "downloads" / "remote.pdf").exists()


def test_download_without_url_is_an_error(db, kb) -> None:
    kb_dir, settings = kb
    _write_manifest(
        kb_dir / "manifest.yaml",
        [{"id": "remote", "title": "Remote", "file": "downloads/remote.pdf", "download": True}],
    )
    report = ingest_manifest(db, settings, HashEmbedder(dim=16), download=True)
    assert "no url" in report.errors["remote"]
