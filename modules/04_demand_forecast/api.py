"""
Sportek d.o.o. — Demand Forecast — FastAPI Router
REST endpoints for forecasting, inventory optimization, analytics and ROI.

Mount into your main app:
    from modules.demand_forecast.api import router
    app.include_router(router)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .data_pipeline import DemandPipeline
from .inventory_optimizer import InventoryOptimizer
from .models import DemandForecaster

MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"

# ---------------------------------------------------------------------------
# Singletons (lazy-loaded)
# ---------------------------------------------------------------------------
_pipeline: DemandPipeline | None = None
_forecaster: DemandForecaster | None = None
_optimizer: InventoryOptimizer | None = None


def _get_pipeline() -> DemandPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = DemandPipeline()
        _pipeline.load_data()
        _pipeline.aggregate(freq="W")
        _pipeline.engineer_features()
    return _pipeline


def _get_forecaster() -> DemandForecaster:
    global _forecaster
    if _forecaster is None:
        pipe = _get_pipeline()
        _forecaster = DemandForecaster(pipeline=pipe)
        _forecaster.compare_models()
    return _forecaster


def _get_optimizer() -> InventoryOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = InventoryOptimizer()
    return _optimizer


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
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/api/forecast", tags=["Demand Forecasting"])


# ── GET /predict ──────────────────────────────────────────────────────────
@router.get("/predict")
async def predict(
    brand: Optional[str] = Query(None, description="Brand filter (Nike, Crocs, Decathlon)"),
    horizon: int = Query(30, ge=7, le=180, description="Forecast horizon in days"),
):
    """Return demand forecast with confidence intervals."""
    try:
        forecaster = _get_forecaster()
        best = forecaster.best_model_name or "random_forest"

        if brand:
            pipe = _get_pipeline()
            valid_brands = list(pipe.weekly_brand.columns)
            if brand not in valid_brands:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown brand '{brand}'. Valid: {valid_brands}",
                )
            # For brand-specific, return historical + note
            brand_data = pipe.weekly_brand[brand]
            result = {
                "brand": brand,
                "model": best,
                "horizon_days": horizon,
                "historical_weekly_avg": round(float(brand_data.mean()), 0),
                "historical_weekly_std": round(float(brand_data.std()), 0),
                "note": "Brand-level forecast uses total forecast proportionally allocated.",
            }
            total_forecast = forecaster.predict(best, horizon_days=horizon)
            brand_share = float(brand_data.sum()) / float(pipe.weekly_total["demand"].sum())
            result["forecast"] = {
                "dates": total_forecast["dates"],
                "forecast": [round(v * brand_share) for v in total_forecast["forecast"]],
                "lower_bound": [round(v * brand_share) for v in total_forecast["lower_bound"]],
                "upper_bound": [round(v * brand_share) for v in total_forecast["upper_bound"]],
            }
            return JSONResponse(content=result)

        forecast = forecaster.predict(best, horizon_days=horizon)
        return JSONResponse(content={
            "brand": "all",
            "model": best,
            "horizon_days": horizon,
            **forecast,
        })
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /models/compare ───────────────────────────────────────────────────
@router.get("/models/compare")
async def compare_models():
    """Return model comparison metrics."""
    return _load_json("model_comparison.json")


# ── GET /inventory/risk ───────────────────────────────────────────────────
@router.get("/inventory/risk")
async def inventory_risk():
    """Return stockout risk assessment."""
    return _load_json("stockout_risks.json")


# ── GET /inventory/optimize ───────────────────────────────────────────────
@router.get("/inventory/optimize")
async def inventory_optimize():
    """Return top 20 optimization recommendations."""
    try:
        opt = _get_optimizer()
        df = opt.optimize_all()
        # Top 20 by urgency: critical first, then by days_of_stock ascending
        status_order = {"critical": 0, "low": 1, "ok": 2, "overstocked": 3}
        df["_sort"] = df["status"].map(status_order)
        top20 = df.sort_values(["_sort", "days_of_stock"]).head(20)
        top20 = top20.drop(columns=["_sort"])
        return JSONResponse(content={
            "total_materials": len(df),
            "top_20_recommendations": top20.to_dict(orient="records"),
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /analytics ────────────────────────────────────────────────────────
@router.get("/analytics")
async def get_analytics():
    """Return all dashboard analytics data."""
    result: dict = {}

    # Model comparison
    try:
        result["model_comparison"] = _load_json("model_comparison.json")
    except HTTPException:
        result["model_comparison"] = None

    # Inventory optimization
    try:
        result["inventory_optimization"] = _load_json("optimization_results.json")
    except HTTPException:
        result["inventory_optimization"] = None

    # Stockout risks
    try:
        result["stockout_risks"] = _load_json("stockout_risks.json")
    except HTTPException:
        result["stockout_risks"] = None

    # ROI summary
    try:
        roi = _load_json("forecast_roi.json")
        result["roi_summary"] = roi.get("roi_summary")
    except HTTPException:
        result["roi_summary"] = None

    # Chart paths
    chart_names = [
        "forecast_vs_actual.png", "demand_by_brand.png", "seasonality.png",
        "model_comparison.png", "inventory_optimization.png", "stockout_risk.png",
    ]
    result["charts"] = {
        name: str(RESULT_DIR / name)
        for name in chart_names
        if (RESULT_DIR / name).exists()
    }

    return JSONResponse(content=result)


# ── GET /roi ──────────────────────────────────────────────────────────────
@router.get("/roi")
async def get_roi():
    """Return Demand Forecast ROI calculation."""
    return _load_json("forecast_roi.json")
