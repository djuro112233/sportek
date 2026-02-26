"""
Sportek d.o.o. — AI Platform API
FastAPI application mounting all 6 module routers + health check.

Usage:
    PYTHONPATH=. uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

import importlib
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is on path so numbered module dirs resolve
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

app = FastAPI(
    title="Sportek AI Platform",
    description="6 AI modules for intelligent manufacturing",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount module routers ────────────────────────────────────────────────
_modules_loaded = []

_ROUTER_SPECS = [
    ("modules.01_cv_quality.api",           "cv_quality"),
    ("modules.02_tradeflow.api",            "tradeflow"),
    ("modules.03_knowledge_guardian.api",    "knowledge_guardian"),
    ("modules.04_demand_forecast.api",      "demand_forecast"),
    ("modules.05_oee_dashboard.api",        "oee_dashboard"),
    ("modules.06_brand_reporting.api",      "brand_reporting"),
]

for module_path, label in _ROUTER_SPECS:
    try:
        mod = importlib.import_module(module_path)
        app.include_router(mod.router)
        _modules_loaded.append(label)
    except Exception:
        pass


# ── Health endpoint ─────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "platform": "Sportek AI",
        "version": "1.0.0",
        "modules": len(_modules_loaded),
        "modules_loaded": _modules_loaded,
    }
