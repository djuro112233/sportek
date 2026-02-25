"""
Sportek d.o.o. — CV Quality Module — FastAPI Router
Exposes defect-detection model, analytics and ROI data via REST endpoints.

Mount into your main app:
    from modules.cv_quality.api import router
    app.include_router(router)
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from .inference import DefectDetector

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"
PROJECT_ROOT = MODULE_DIR.parents[1]
DEFECT_CSV = PROJECT_ROOT / "data" / "quality" / "defect_log.csv"
PRODUCTION_CSV = PROJECT_ROOT / "data" / "production" / "production_log.csv"

# ---------------------------------------------------------------------------
# Singleton detector (loaded once)
# ---------------------------------------------------------------------------
_detector: DefectDetector | None = None


def _get_detector() -> DefectDetector:
    global _detector
    if _detector is None:
        _detector = DefectDetector()
        _detector.load_model()
    return _detector


def _load_json(name: str) -> dict:
    path = RESULT_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found. Run analytics/roi first.")
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/api/cv", tags=["Computer Vision QC"])


# ── POST /predict ─────────────────────────────────────────────────────────
@router.post("/predict")
async def predict_image(file: UploadFile = File(...)):
    """Upload an image and get a defect/ok prediction."""
    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
        raise HTTPException(status_code=400, detail="Unsupported image format. Use PNG or JPEG.")

    # Write to temp file so PIL can open it
    tmp_dir = tempfile.mkdtemp()
    tmp_path = Path(tmp_dir) / file.filename
    try:
        with open(tmp_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
        detector = _get_detector()
        result = detector.predict(tmp_path)
        result["filename"] = file.filename
        return JSONResponse(content=result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── GET /stats ────────────────────────────────────────────────────────────
@router.get("/stats")
async def get_stats():
    """Return QC summary statistics."""
    return _load_json("qc_summary.json")


# ── GET /pareto ───────────────────────────────────────────────────────────
@router.get("/pareto")
async def get_pareto():
    """Return Pareto-chart data (defect types sorted by count)."""
    if not DEFECT_CSV.exists():
        raise HTTPException(status_code=404, detail="defect_log.csv not found.")

    df = pd.read_csv(DEFECT_CSV)
    counts = df["defect_type"].value_counts().sort_values(ascending=False)
    total = counts.sum()
    cum = 0
    result = []
    for dtype, cnt in counts.items():
        cum += cnt
        result.append({
            "defect_type": dtype,
            "count": int(cnt),
            "percent": round(cnt / total * 100, 1),
            "cumulative_pct": round(cum / total * 100, 1),
        })
    return result


# ── GET /trend ────────────────────────────────────────────────────────────
@router.get("/trend")
async def get_trend():
    """Return monthly defect-rate trend per brand."""
    if not DEFECT_CSV.exists() or not PRODUCTION_CSV.exists():
        raise HTTPException(status_code=404, detail="CSV data not found.")

    df_d = pd.read_csv(DEFECT_CSV)
    df_p = pd.read_csv(PRODUCTION_CSV)

    df_d["month"] = pd.to_datetime(df_d["date"]).dt.to_period("M").astype(str)
    df_p["month"] = pd.to_datetime(df_p["date"]).dt.to_period("M").astype(str)

    d_counts = df_d.groupby(["month", "brand"]).size().reset_index(name="defects")
    p_totals = df_p.groupby(["month", "brand"])["actual_qty"].sum().reset_index()

    merged = pd.merge(d_counts, p_totals, on=["month", "brand"], how="inner")
    merged["defect_rate_pct"] = round(merged["defects"] / merged["actual_qty"] * 100, 3)

    # Build per-brand series
    result = {}
    for brand in sorted(merged["brand"].unique()):
        sub = merged[merged["brand"] == brand].sort_values("month")
        result[brand] = [
            {"month": row["month"],
             "defects": int(row["defects"]),
             "production": int(row["actual_qty"]),
             "defect_rate_pct": float(row["defect_rate_pct"])}
            for _, row in sub.iterrows()
        ]

    # Overall
    overall = merged.groupby("month").agg(
        defects=("defects", "sum"),
        production=("actual_qty", "sum"),
    ).reset_index()
    overall["defect_rate_pct"] = round(overall["defects"] / overall["production"] * 100, 3)
    result["Overall"] = [
        {"month": r["month"],
         "defects": int(r["defects"]),
         "production": int(r["production"]),
         "defect_rate_pct": float(r["defect_rate_pct"])}
        for _, r in overall.sort_values("month").iterrows()
    ]

    return result


# ── GET /roi ──────────────────────────────────────────────────────────────
@router.get("/roi")
async def get_roi():
    """Return ROI calculation results."""
    return _load_json("roi_calculation.json")
