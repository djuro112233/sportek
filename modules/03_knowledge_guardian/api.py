"""
Sportek d.o.o. — Knowledge Guardian — FastAPI Router
REST endpoints for RAG Q&A, document listing, search, analytics and ROI.

Mount into your main app:
    from modules.knowledge_guardian.api import router
    app.include_router(router)
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .doc_processor import DocumentProcessor
from .rag_engine import RAGEngine
from .vector_store import VectorStore

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"
STORE_PATH = MODULE_DIR / "store" / "vector_index.pkl"

# ---------------------------------------------------------------------------
# Singletons (lazy-loaded)
# ---------------------------------------------------------------------------
_engine: RAGEngine | None = None
_processor: DocumentProcessor | None = None


def _get_engine() -> RAGEngine:
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


def _get_processor() -> DocumentProcessor:
    global _processor
    if _processor is None:
        _processor = DocumentProcessor()
        _processor.load_documents()
        _processor.process_all()
    return _processor


def _load_json(name: str) -> dict:
    path = RESULT_DIR / name
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{name} not found. Run the corresponding script first.",
        )
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Guardian"])


# ── POST /ask ─────────────────────────────────────────────────────────────
@router.post("/ask")
async def ask_question(req: AskRequest):
    """Answer a question using RAG over internal documents."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    try:
        engine = _get_engine()
        result = engine.ask(req.question)
        return JSONResponse(content=result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /documents ────────────────────────────────────────────────────────
@router.get("/documents")
async def list_documents():
    """List all indexed documents with metadata."""
    proc = _get_processor()
    docs = []
    for doc in proc.documents:
        fname = doc["file_name"]
        n_chunks = sum(1 for c in proc.chunks if c["source_file"] == fname)
        docs.append({
            "file_name": fname,
            "word_count": doc["word_count"],
            "chunks": n_chunks,
        })
    return JSONResponse(content={
        "total_documents": len(docs),
        "documents": docs,
    })


# ── GET /stats ────────────────────────────────────────────────────────────
@router.get("/stats")
async def get_stats():
    """Return knowledge_stats.json data."""
    return _load_json("knowledge_stats.json")


# ── POST /search ──────────────────────────────────────────────────────────
@router.post("/search")
async def semantic_search(req: SearchRequest):
    """Semantic search over document chunks (raw results, no answer)."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty.")
    try:
        engine = _get_engine()
        results = engine.store.search(req.query, top_k=req.top_k)
        return JSONResponse(content={
            "query": req.query,
            "top_k": req.top_k,
            "results": results,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /analytics ────────────────────────────────────────────────────────
@router.get("/analytics")
async def get_analytics():
    """Return aggregated analytics data for the dashboard."""
    result: dict = {}

    # Knowledge stats
    try:
        result["knowledge_stats"] = _load_json("knowledge_stats.json")
    except HTTPException:
        result["knowledge_stats"] = None

    # Chart paths
    chart_names = [
        "document_usage.png",
        "query_topics.png",
        "response_time.png",
        "confidence_distribution.png",
    ]
    result["charts"] = {
        name: str(RESULT_DIR / name)
        for name in chart_names
        if (RESULT_DIR / name).exists()
    }

    # Query log summary
    log_path = MODULE_DIR / "logs" / "query_log.csv"
    if log_path.exists():
        import csv
        with open(log_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if rows:
            confs = [float(r["confidence"]) for r in rows]
            times = [float(r["response_time_ms"]) for r in rows]
            result["query_log_summary"] = {
                "total_queries": len(rows),
                "avg_confidence": round(sum(confs) / len(confs), 3),
                "avg_response_time_ms": round(sum(times) / len(times), 1),
            }

    # ROI summary
    try:
        roi = _load_json("knowledge_roi.json")
        result["roi_summary"] = roi.get("roi_summary")
    except HTTPException:
        result["roi_summary"] = None

    return JSONResponse(content=result)


# ── GET /roi ──────────────────────────────────────────────────────────────
@router.get("/roi")
async def get_roi():
    """Return Knowledge Guardian ROI calculation."""
    return _load_json("knowledge_roi.json")
