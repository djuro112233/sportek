"""
Sportek d.o.o. — TradeFlow AI — FastAPI Router
REST endpoints for HS classification, duty calculation, DPP, CBAM and analytics.

Mount into your main app:
    from modules.tradeflow.api import router
    app.include_router(router)
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .cbam_reporter import CBAMReporter
from .dpp_generator import DPPGenerator
from .duty_calculator import DutyCalculator
from .hs_classifier import HSClassifier

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
RESULT_DIR = MODULE_DIR / "results"
PRODUCTS_CSV = PROJECT_ROOT / "data" / "compliance" / "products_dpp.csv"

# ---------------------------------------------------------------------------
# Singletons (lazy-loaded)
# ---------------------------------------------------------------------------
_classifier: HSClassifier | None = None
_duty_calc: DutyCalculator | None = None
_dpp_gen: DPPGenerator | None = None
_cbam: CBAMReporter | None = None


def _get_classifier() -> HSClassifier:
    global _classifier
    if _classifier is None:
        _classifier = HSClassifier()
        _classifier.load_model()
    return _classifier


def _get_duty_calc() -> DutyCalculator:
    global _duty_calc
    if _duty_calc is None:
        _duty_calc = DutyCalculator()
    return _duty_calc


def _get_dpp_gen() -> DPPGenerator:
    global _dpp_gen
    if _dpp_gen is None:
        _dpp_gen = DPPGenerator()
    return _dpp_gen


def _get_cbam() -> CBAMReporter:
    global _cbam
    if _cbam is None:
        _cbam = CBAMReporter()
    return _cbam


def _load_json(name: str) -> dict:
    path = RESULT_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found. Run the corresponding script first.")
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ClassifyRequest(BaseModel):
    description: str


class DutyRequest(BaseModel):
    hs_code: str
    destination: str
    value_eur: float


class DPPGenerateRequest(BaseModel):
    product_id: str
    product_name: str
    brand: str
    hs_code_6digit: int
    hs_code_10digit: int | None = None
    country_origin: str
    materials_composition: str
    weight_grams: int
    carbon_footprint_kg: float
    recyclability_score: int
    hazardous_substances: str = "REACH compliant"
    factory_id: str = "SPORTEK-BL-001"
    production_date: str = ""
    batch_number: str = ""


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/api/trade", tags=["TradeFlow AI"])


# ── POST /classify ────────────────────────────────────────────────────────
@router.post("/classify")
async def classify_hs(req: ClassifyRequest):
    """Classify a product description into an HS tariff code."""
    if not req.description.strip():
        raise HTTPException(status_code=400, detail="Description must not be empty.")
    try:
        clf = _get_classifier()
        result = clf.predict(req.description)
        return JSONResponse(content=result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /duty ────────────────────────────────────────────────────────────
@router.post("/duty")
async def calculate_duty(req: DutyRequest):
    """Calculate import duty, VAT and landed cost for a shipment."""
    try:
        calc = _get_duty_calc()
        result = calc.calculate(req.hs_code, req.destination, req.value_eur)
        return JSONResponse(content=result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /dpp/generate ────────────────────────────────────────────────────
@router.post("/dpp/generate")
async def generate_dpp(req: DPPGenerateRequest):
    """Generate an ESPR-compliant Digital Product Passport."""
    try:
        gen = _get_dpp_gen()
        dpp = gen.generate(req.model_dump())
        validation = gen.validate(dpp)
        return JSONResponse(content={"dpp": dpp, "validation": validation})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /dpp/validate/{product_id} ────────────────────────────────────────
@router.get("/dpp/validate/{product_id}")
async def validate_dpp(product_id: str):
    """Validate a DPP for a product from the products CSV."""
    if not PRODUCTS_CSV.exists():
        raise HTTPException(status_code=404, detail="products_dpp.csv not found.")

    df = pd.read_csv(PRODUCTS_CSV)
    row = df[df["product_id"] == product_id]
    if row.empty:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found.")

    try:
        gen = _get_dpp_gen()
        dpp = gen.generate(row.iloc[0].to_dict())
        validation = gen.validate(dpp)
        return JSONResponse(content={
            "product_id": product_id,
            "dpp": dpp,
            "validation": validation,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /cbam/report ──────────────────────────────────────────────────────
@router.get("/cbam/report")
async def get_cbam_report():
    """Return the CBAM Q4 2025 quarterly report."""
    return _load_json("cbam_q4_2025.json")


# ── GET /analytics ────────────────────────────────────────────────────────
@router.get("/analytics")
async def get_analytics():
    """Return aggregated analytics data for the dashboard."""
    result = {}

    # HS metrics
    try:
        result["hs_metrics"] = _load_json("hs_metrics.json")
    except HTTPException:
        result["hs_metrics"] = None

    # CBAM summary
    try:
        cbam = _load_json("cbam_q4_2025.json")
        result["cbam_summary"] = cbam.get("summary")
        result["cbam_by_brand"] = cbam.get("by_brand")
        result["cbam_cost_estimate"] = cbam.get("cbam_cost_estimate")
    except HTTPException:
        result["cbam_summary"] = None

    # DPP readiness (compute live)
    if PRODUCTS_CSV.exists():
        df = pd.read_csv(PRODUCTS_CSV)
        gen = _get_dpp_gen()
        readiness = {}
        for _, row in df.iterrows():
            brand = row["brand"]
            dpp = gen.generate(row.to_dict())
            val = gen.validate(dpp)
            readiness.setdefault(brand, []).append(val["completeness_pct"])
        result["dpp_readiness_by_brand"] = {
            b: round(sum(v) / len(v), 1) for b, v in readiness.items()
        }

    # ROI summary
    try:
        roi = _load_json("tradeflow_roi.json")
        result["roi_summary"] = roi.get("roi_summary")
    except HTTPException:
        result["roi_summary"] = None

    # Chart paths
    chart_names = [
        "hs_distribution.png", "duty_savings.png", "dpp_readiness.png",
        "cbam_exposure.png", "compliance_risk_matrix.png",
    ]
    result["charts"] = {
        name: str(RESULT_DIR / name) for name in chart_names
        if (RESULT_DIR / name).exists()
    }

    return JSONResponse(content=result)


# ── GET /roi ──────────────────────────────────────────────────────────────
@router.get("/roi")
async def get_roi():
    """Return TradeFlow ROI calculation."""
    return _load_json("tradeflow_roi.json")
