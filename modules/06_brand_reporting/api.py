"""
Sportek d.o.o. — Brand Reporting — FastAPI Router
6 endpoints for brand reports, KPIs, alerts, history, analytics, and ROI.

Usage:
    from modules.06_brand_reporting.api import router
    app.include_router(router)
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .templates import NikeScorecard, CrocsReport, DecathlonReport
from .generator import ReportGenerator
from .kpi_tracker import KPITracker
from .roi import calculate_roi

router = APIRouter(prefix="/api/reports", tags=["Brand Reporting"])

MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"
REPORT_DIR = RESULT_DIR / "reports"

# ── Lazy singletons ───────────────────────────────────────────────────────
_generator: ReportGenerator | None = None
_tracker: KPITracker | None = None


def _get_generator() -> ReportGenerator:
    global _generator
    if _generator is None:
        _generator = ReportGenerator()
    return _generator


def _get_tracker() -> KPITracker:
    global _tracker
    if _tracker is None:
        _tracker = KPITracker()
    return _tracker


def _load_json(name: str) -> dict:
    path = RESULT_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {name}")
    with open(path) as f:
        return json.load(f)


# ── Request models ────────────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    brand: str
    period: str = "2025-Q4"


# ── 1. POST /generate ────────────────────────────────────────────────────
@router.post("/generate")
def generate_report(req: GenerateRequest):
    """Generate a brand report for the given brand and period."""
    gen = _get_generator()
    brand = req.brand.strip()
    period = req.period.strip()

    if brand == "Nike":
        report = gen.generate_nike_scorecard(period)
    elif brand == "Crocs":
        report = gen.generate_crocs_report(period)
    elif brand == "Decathlon":
        report = gen.generate_decathlon_report(period)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown brand: {brand}. Available: Nike, Crocs, Decathlon",
        )

    return {"status": "generated", "brand": brand, "period": period, "report": report}


# ── 2. GET /kpis ──────────────────────────────────────────────────────────
@router.get("/kpis")
def get_kpis():
    """All 20 KPIs with current values, status (green/yellow/red), and trend."""
    tracker = _get_tracker()
    return tracker.calculate_all()


# ── 3. GET /alerts ────────────────────────────────────────────────────────
@router.get("/alerts")
def get_alerts():
    """Active alerts — KPIs that are yellow or red."""
    tracker = _get_tracker()
    alerts = tracker.get_alerts()
    return {
        "total_alerts": len(alerts),
        "red": [a for a in alerts if a["status"] == "red"],
        "yellow": [a for a in alerts if a["status"] == "yellow"],
    }


# ── 4. GET /history ──────────────────────────────────────────────────────
@router.get("/history")
def get_history():
    """List all generated reports from results/reports/ directory."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    for f in sorted(REPORT_DIR.glob("*.json")):
        if f.name == ".gitkeep":
            continue
        stat = f.stat()
        with open(f) as fh:
            data = json.load(fh)
        reports.append({
            "filename": f.name,
            "brand": data.get("brand", "unknown"),
            "period": data.get("period", "unknown"),
            "size_bytes": stat.st_size,
            "generated_at": stat.st_mtime,
        })
    return {"total_reports": len(reports), "reports": reports}


# ── 5. GET /analytics ────────────────────────────────────────────────────
@router.get("/analytics")
def get_analytics():
    """Dashboard data including brand summaries, KPI overview, and chart paths."""
    return _load_json("reporting_analytics.json")


# ── 6. GET /roi ───────────────────────────────────────────────────────────
@router.get("/roi")
def get_roi():
    """ROI analysis for Brand Reporting automation."""
    return calculate_roi()
