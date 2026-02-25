"""
Sportek d.o.o. — OEE Dashboard — FastAPI Router
9 endpoints for OEE metrics, scheduling, predictions, and ROI.

Usage:
    from modules.05_oee_dashboard.api import router
    app.include_router(router)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .oee_calculator import OEECalculator
from .scheduler import ProductionScheduler, DEMO_ORDERS
from .predictive import _prepare_data, train_downtime_predictor, train_anomaly_detector
from .roi import calculate_roi

router = APIRouter(prefix="/api/oee", tags=["OEE Dashboard"])

# ── Lazy singletons ───────────────────────────────────────────────────────
_calc: OEECalculator | None = None
_scheduler: ProductionScheduler | None = None
_predictive_cache: dict | None = None


def _get_calc() -> OEECalculator:
    global _calc
    if _calc is None:
        _calc = OEECalculator()
        _calc.load_data()
    return _calc


def _get_scheduler() -> ProductionScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ProductionScheduler()
    return _scheduler


def _get_predictive() -> dict:
    global _predictive_cache
    if _predictive_cache is None:
        df, _, _ = _prepare_data()
        dt_result = train_downtime_predictor(df)
        anom_result = train_anomaly_detector(df)
        _predictive_cache = {
            "df": df,
            "downtime": dt_result,
            "anomaly": anom_result,
        }
    return _predictive_cache


# ── Request models ────────────────────────────────────────────────────────
class OrderItem(BaseModel):
    brand: str
    model: str
    qty: int
    deadline: str


class ScheduleRequest(BaseModel):
    orders: list[OrderItem]
    days_ahead: int = 5


# ── 1. GET /current ───────────────────────────────────────────────────────
@router.get("/current")
def get_current_oee():
    """Current OEE snapshot for all lines."""
    calc = _get_calc()
    return calc.get_current_oee()


# ── 2. GET /trend ─────────────────────────────────────────────────────────
@router.get("/trend")
def get_oee_trend(period: str = Query("monthly", enum=["monthly", "weekly"])):
    """OEE trend over time for all lines."""
    calc = _get_calc()
    all_lines = calc.calculate_all_lines(period=period)
    result = {}
    for lid, df in all_lines.items():
        result[lid] = df.to_dict(orient="records")
    return result


# ── 3. GET /losses ────────────────────────────────────────────────────────
@router.get("/losses")
def get_losses(line_id: str = Query(..., description="Line ID (e.g. L1)")):
    """Six Big Losses for a specific line."""
    calc = _get_calc()
    lines = sorted(calc.data["line_id"].unique())
    if line_id not in lines:
        raise HTTPException(status_code=404, detail=f"Line {line_id} not found. Available: {lines}")
    return calc.identify_losses(line_id)


# ── 4. GET /benchmark ────────────────────────────────────────────────────
@router.get("/benchmark")
def get_benchmark():
    """Benchmark ranking of all lines."""
    calc = _get_calc()
    return calc.benchmark()


# ── 5. POST /schedule/optimize ────────────────────────────────────────────
@router.post("/schedule/optimize")
def optimize_schedule(req: ScheduleRequest):
    """Optimize production schedule for given orders."""
    sched = _get_scheduler()
    orders = [o.model_dump() for o in req.orders]
    raw = sched.optimize_schedule(orders, days_ahead=req.days_ahead)
    optimized = sched.minimize_changeovers(raw)
    total_qty = sum(o["qty"] for o in orders)
    scheduled_qty = sum(s["qty"] for s in optimized)
    return {
        "schedule": optimized,
        "total_ordered": total_qty,
        "total_scheduled": scheduled_qty,
        "fulfillment_pct": round(scheduled_qty / total_qty * 100, 1) if total_qty > 0 else 0,
        "slots_used": len(optimized),
    }


# ── 6. GET /predictions ──────────────────────────────────────────────────
@router.get("/predictions")
def get_predictions():
    """Downtime prediction model results."""
    pred = _get_predictive()
    dt = pred["downtime"]
    return {
        "model": dt["model"],
        "target": dt["target"],
        "mae": dt["mae"],
        "r2_score": dt["r2_score"],
        "train_size": dt["train_size"],
        "test_size": dt["test_size"],
        "feature_importance": dt["feature_importance"],
    }


# ── 7. GET /anomalies ────────────────────────────────────────────────────
@router.get("/anomalies")
def get_anomalies():
    """Anomaly detection results."""
    pred = _get_predictive()
    anom = pred["anomaly"]
    return {
        "model": anom["model"],
        "contamination": anom["contamination"],
        "total_records": anom["total_records"],
        "anomalies_detected": anom["anomalies_detected"],
        "anomaly_pct": anom["anomaly_pct"],
        "top_5_anomalies": anom["top_5_anomalies"],
    }


# ── 8. GET /whatif ────────────────────────────────────────────────────────
@router.get("/whatif")
def get_whatif(
    scenario: str = Query(
        ...,
        description="Scenario name",
        enum=["add_shift_3", "remove_line_L4", "increase_capacity_10pct"],
    ),
):
    """Run a what-if scenario."""
    sched = _get_scheduler()
    return sched.what_if(scenario)


# ── 9. GET /roi ───────────────────────────────────────────────────────────
@router.get("/roi")
def get_roi():
    """ROI analysis for OEE Dashboard."""
    return calculate_roi()
