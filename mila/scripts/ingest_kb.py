#!/usr/bin/env python
"""Ingest the knowledge base described by kb/manifest.yaml into the database.

Usage (from the repository root):

    .venv/bin/python scripts/ingest_kb.py [--manifest PATH] [--only id[,id...]] [--download]
                                          [--database-url URL] [--embedder hash|bge_m3]

Prints the IngestReport as JSON. Exit code 1 when any document failed, or when a document
explicitly requested with --only is missing.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import init_engine, session_factory  # noqa: E402
from app.kb.embed import get_embedder  # noqa: E402
from app.kb.ingest import ingest_manifest  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", help="path to manifest.yaml (default: settings.manifest_path)")
    parser.add_argument("--only", help="comma-separated manifest ids to ingest")
    parser.add_argument(
        "--download", action="store_true", help="fetch missing files whose entry has download: true"
    )
    parser.add_argument("--database-url", help="SQLAlchemy URL (default: settings.database_url)")
    parser.add_argument(
        "--embedder", choices=("hash", "bge_m3"), help="embedding provider (default: settings.embedder)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log every document")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    overrides: dict[str, object] = {}
    if args.manifest:
        manifest = Path(args.manifest).resolve()
        overrides["manifest_path"] = str(manifest)
        overrides["kb_dir"] = str(manifest.parent)
    if args.database_url:
        overrides["database_url"] = args.database_url
    if args.embedder:
        overrides["embedder"] = args.embedder
    settings = get_settings().model_copy(update=overrides)

    only = {part.strip() for part in args.only.split(",") if part.strip()} if args.only else None
    init_engine(settings.database_url)
    db = session_factory()()
    try:
        report = ingest_manifest(db, settings, get_embedder(settings), only=only, download=args.download)
    finally:
        db.close()

    print(report.model_dump_json(indent=2))
    requested_missing = bool(only) and any(doc_id in only for doc_id in report.missing_files)
    return 1 if report.errors or requested_missing else 0


if __name__ == "__main__":
    sys.exit(main())
