#!/usr/bin/env python3
"""
Sportek d.o.o. — Integration Test Suite
Tests all 6 AI modules + API health.

Usage:
    python tests/test_integration.py
"""

import sys
import os
import json
import time
import importlib
import importlib.util
import traceback

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ── Colours ─────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
DIM = "\033[2m"
RESET = "\033[0m"

results = {}


def report(test_name: str, passed: bool, detail: str = ""):
    results[test_name] = passed
    tag = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    print(f"  [{tag}]  {detail}")


def import_from(module_dir: str, module_file: str):
    """Import a module from a numbered package directory."""
    import types
    if "modules" not in sys.modules:
        modules_pkg = types.ModuleType("modules")
        modules_pkg.__path__ = [os.path.join(PROJECT_ROOT, "modules")]
        sys.modules["modules"] = modules_pkg

    pkg_path = os.path.join(PROJECT_ROOT, "modules", module_dir)
    if f"modules.{module_dir}" not in sys.modules:
        pkg_spec = importlib.util.spec_from_file_location(
            f"modules.{module_dir}",
            os.path.join(pkg_path, "__init__.py"),
            submodule_search_locations=[pkg_path],
        )
        pkg_mod = importlib.util.module_from_spec(pkg_spec)
        sys.modules[f"modules.{module_dir}"] = pkg_mod
        pkg_spec.loader.exec_module(pkg_mod)

    spec = importlib.util.spec_from_file_location(
        f"modules.{module_dir}.{module_file}",
        os.path.join(pkg_path, f"{module_file}.py"),
        submodule_search_locations=[pkg_path],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


print()
print(f"{BOLD}{CYAN}{'═' * 55}{RESET}")
print(f"{BOLD}{CYAN}  SPORTEK AI — INTEGRATION TEST REPORT{RESET}")
print(f"{BOLD}{CYAN}{'═' * 55}{RESET}")


# ════════════════════════════════════════════════════════════════════════
# TEST 1 — CV Quality Control
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}Test 1 — CV Quality Control{RESET}")
try:
    mod = import_from("01_cv_quality", "inference")
    detector = mod.DefectDetector()

    # Check model file exists
    model_path = os.path.join(PROJECT_ROOT, "modules", "01_cv_quality", "models", "defect_classifier.pkl")
    scaler_path = os.path.join(PROJECT_ROOT, "modules", "01_cv_quality", "models", "scaler.pkl")
    assert os.path.isfile(model_path), f"Model not found: {model_path}"
    assert os.path.isfile(scaler_path), f"Scaler not found: {scaler_path}"

    detector.load_model(model_path, scaler_path)

    # Predict on test image
    image_path = os.path.join(PROJECT_ROOT, "data", "quality", "defect_images", "ok_001.png")
    result = detector.predict(image_path)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "prediction" in result, f"Missing key 'prediction'. Keys: {list(result.keys())}"
    assert "confidence" in result, f"Missing key 'confidence'. Keys: {list(result.keys())}"
    assert result["confidence"] > 0.5, f"Confidence too low: {result['confidence']}"

    report("CV Quality", True,
           f"CV Quality Control — model loaded, prediction={result['prediction']}, "
           f"confidence={result['confidence']:.2%}")

except Exception as e:
    report("CV Quality", False, f"CV Quality Control — {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 2 — TradeFlow (HS Classifier)
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}Test 2 — TradeFlow{RESET}")
try:
    hs_mod = import_from("02_tradeflow", "hs_classifier")
    clf = hs_mod.HSClassifier()
    clf.load_model()

    result = clf.predict("athletic shoe knitted upper")

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "hs_code" in result, f"Missing 'hs_code'. Keys: {list(result.keys())}"
    assert "confidence" in result, f"Missing 'confidence'. Keys: {list(result.keys())}"
    assert result["hs_code"].startswith("64"), f"HS code not footwear: {result['hs_code']}"
    assert result["confidence"] > 0, f"Confidence zero or negative: {result['confidence']}"

    report("TradeFlow", True,
           f"TradeFlow — HS={result['hs_code']}, confidence={result['confidence']:.2%}")

except Exception as e:
    report("TradeFlow", False, f"TradeFlow — {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 3 — Knowledge Guardian (RAG Engine)
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}Test 3 — Knowledge Guardian{RESET}")
try:
    import_from("03_knowledge_guardian", "doc_processor")
    import_from("03_knowledge_guardian", "vector_store")
    rag_mod = import_from("03_knowledge_guardian", "rag_engine")
    engine = rag_mod.RAGEngine()

    result = engine.ask("Koji su koraci finalne inspekcije?")

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "answer" in result, f"Missing 'answer'. Keys: {list(result.keys())}"
    assert "sources" in result, f"Missing 'sources'. Keys: {list(result.keys())}"
    assert len(result["answer"]) > 0, "Answer is empty"
    assert len(result["sources"]) > 0, "No sources returned"

    report("Knowledge Guardian", True,
           f"Knowledge Guardian — answer={len(result['answer'])} chars, "
           f"sources={len(result['sources'])}")

except Exception as e:
    report("Knowledge Guardian", False, f"Knowledge Guardian — {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 4 — Demand Forecast
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}Test 4 — Demand Forecast{RESET}")
try:
    forecast_mod = import_from("04_demand_forecast", "models")
    forecaster = forecast_mod.DemandForecaster()

    # Check model file exists
    model_path = os.path.join(PROJECT_ROOT, "modules", "04_demand_forecast", "models", "best_forecast_model.pkl")
    assert os.path.isfile(model_path), f"Model not found: {model_path}"

    # Train model first, then forecast
    forecaster.train("random_forest")
    result = forecaster.predict("random_forest", horizon_days=30)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "forecast" in result, f"Missing 'forecast'. Keys: {list(result.keys())}"
    forecast_vals = result["forecast"]
    assert isinstance(forecast_vals, list), f"forecast not a list: {type(forecast_vals)}"
    assert len(forecast_vals) > 0, "Forecast list is empty"
    assert all(isinstance(v, (int, float)) for v in forecast_vals), "Forecast contains non-numeric values"

    report("Demand Forecast", True,
           f"Demand Forecast — model loaded, forecast={len(forecast_vals)} periods")

except Exception as e:
    report("Demand Forecast", False, f"Demand Forecast — {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 5 — OEE Dashboard
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}Test 5 — OEE Dashboard{RESET}")
try:
    oee_mod = import_from("05_oee_dashboard", "oee_calculator")
    calc = oee_mod.OEECalculator()
    calc.load_data()

    oee_df = calc.calculate_oee("L1", period="monthly")
    last = oee_df.iloc[-1]
    oee_pct = last["oee"] * 100  # convert 0-1 to 0-100

    assert 0 < oee_pct < 100, f"OEE out of range: {oee_pct}"
    assert all(c in oee_df.columns for c in ["availability", "performance", "quality", "oee"]), \
        f"Missing columns. Got: {list(oee_df.columns)}"

    report("OEE Dashboard", True,
           f"OEE Dashboard — L1 OEE={oee_pct:.1f}%, {len(oee_df)} periods")

except Exception as e:
    report("OEE Dashboard", False, f"OEE Dashboard — {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 6 — Brand Reporting
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}Test 6 — Brand Reporting{RESET}")
try:
    templates_mod = import_from("06_brand_reporting", "templates")
    scorecard = templates_mod.NikeScorecard()
    nike = scorecard.generate("2025-Q4")

    assert isinstance(nike, dict), f"Expected dict, got {type(nike)}"
    assert "smsi_score" in nike, f"Missing 'smsi_score'. Keys: {list(nike.keys())}"
    assert 0 <= nike["smsi_score"] <= 100, f"SMSI out of range: {nike['smsi_score']}"
    assert "overall_grade" in nike, f"Missing 'overall_grade'"

    report("Brand Reporting", True,
           f"Brand Reporting — SMSI={nike['smsi_score']}, grade={nike['overall_grade']}")

except Exception as e:
    report("Brand Reporting", False, f"Brand Reporting — {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 7 — API Health
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}Test 7 — API Health{RESET}")
try:
    import requests
    resp = requests.get("http://localhost:8000/api/health", timeout=3)
    assert resp.status_code == 200, f"Status {resp.status_code}"
    data = resp.json()
    assert data.get("status") == "healthy", f"Unexpected status: {data}"

    report("API Health", True,
           f"API Health — status=200, {data.get('modules', '?')} modules")

except requests.exceptions.ConnectionError:
    # API server not running — start it and retry
    print(f"  {DIM}API not running, attempting to start...{RESET}")
    import subprocess
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": PROJECT_ROOT},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    try:
        resp = requests.get("http://localhost:8000/api/health", timeout=3)
        assert resp.status_code == 200
        data = resp.json()
        report("API Health", True,
               f"API Health — status=200, {data.get('modules', '?')} modules (auto-started)")
    except Exception as e2:
        report("API Health", False, f"API Health — server start failed: {e2}")
    finally:
        proc.terminate()

except Exception as e:
    report("API Health", False, f"API Health — {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# FINAL REPORT
# ════════════════════════════════════════════════════════════════════════
total = len(results)
passed = sum(1 for v in results.values() if v)

print()
print(f"{BOLD}{CYAN}{'═' * 55}{RESET}")
print(f"{BOLD}{CYAN}  RESULTS{RESET}")
print(f"{BOLD}{CYAN}{'═' * 55}{RESET}")

labels = [
    ("CV Quality",         "CV Quality Control"),
    ("TradeFlow",          "TradeFlow AI"),
    ("Knowledge Guardian", "Knowledge Guardian"),
    ("Demand Forecast",    "Demand Forecasting"),
    ("OEE Dashboard",      "OEE Dashboard"),
    ("Brand Reporting",    "Brand Reporting"),
    ("API Health",         "API Health Check"),
]

for key, display in labels:
    ok = results.get(key, False)
    tag = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"  [{tag}]  {display}")

print(f"{BOLD}{CYAN}{'═' * 55}{RESET}")
color = GREEN if passed == total else YELLOW if passed >= total - 1 else RED
print(f"  {BOLD}Total: {color}{passed}/{total} PASS{RESET}")
print(f"{BOLD}{CYAN}{'═' * 55}{RESET}")
print()

sys.exit(0 if passed == total else 1)
