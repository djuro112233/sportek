#!/usr/bin/env python3
"""
Sportek d.o.o. — Integration Test Suite
Tests all 6 AI modules + dashboard + data integrity.

Usage:
    python tests/test_integration.py
"""

import sys
import os
import json
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
    status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    print(f"  {status}  {detail}")


def import_from(module_dir: str, module_file: str):
    """Import a module from a numbered package directory (e.g. 01_cv_quality)."""
    pkg_path = os.path.join(PROJECT_ROOT, "modules", module_dir)
    # Temporarily add the parent so relative imports within the package work
    spec = importlib.util.spec_from_file_location(
        f"modules.{module_dir}.{module_file}",
        os.path.join(pkg_path, f"{module_file}.py"),
        submodule_search_locations=[pkg_path],
    )
    # First, ensure the package itself is registered
    if f"modules.{module_dir}" not in sys.modules:
        pkg_spec = importlib.util.spec_from_file_location(
            f"modules.{module_dir}",
            os.path.join(pkg_path, "__init__.py"),
            submodule_search_locations=[pkg_path],
        )
        pkg_mod = importlib.util.module_from_spec(pkg_spec)
        sys.modules[f"modules.{module_dir}"] = pkg_mod
        pkg_spec.loader.exec_module(pkg_mod)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# Also register the top-level 'modules' package if not present
if "modules" not in sys.modules:
    import types
    modules_pkg = types.ModuleType("modules")
    modules_pkg.__path__ = [os.path.join(PROJECT_ROOT, "modules")]
    sys.modules["modules"] = modules_pkg


# ════════════════════════════════════════════════════════════════════════
# TEST 1 — CV Quality Control
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}TEST 1 — CV Quality Control{RESET}")
print(f"{DIM}{'─' * 55}{RESET}")
try:
    mod = import_from("01_cv_quality", "inference")
    DefectDetector = mod.DefectDetector

    detector = DefectDetector()
    model_path = os.path.join(PROJECT_ROOT, "modules", "01_cv_quality", "models", "defect_classifier.pkl")
    scaler_path = os.path.join(PROJECT_ROOT, "modules", "01_cv_quality", "models", "scaler.pkl")
    detector.load_model(model_path, scaler_path)

    image_path = os.path.join(PROJECT_ROOT, "data", "quality", "defect_images", "ok_001.png")
    result = detector.predict(image_path)

    has_keys = all(k in result for k in ["prediction", "confidence", "processing_time_ms"])
    conf_ok = result["confidence"] > 0.5

    report("CV Quality", has_keys and conf_ok,
           f"prediction={result['prediction']}, confidence={result['confidence']:.4f}, "
           f"time={result['processing_time_ms']:.1f}ms")

    if not has_keys:
        print(f"    {RED}Missing keys. Got: {list(result.keys())}{RESET}")
    if not conf_ok:
        print(f"    {RED}Confidence too low: {result['confidence']}{RESET}")

except Exception as e:
    results["CV Quality"] = False
    print(f"  {RED}FAIL{RESET}  {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 2 — TradeFlow (HS Classifier + Duty Calculator)
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}TEST 2 — TradeFlow{RESET}")
print(f"{DIM}{'─' * 55}{RESET}")
try:
    hs_mod = import_from("02_tradeflow", "hs_classifier")
    duty_mod = import_from("02_tradeflow", "duty_calculator")
    HSClassifier = hs_mod.HSClassifier
    DutyCalculator = duty_mod.DutyCalculator

    # HS Classification
    clf = HSClassifier()
    clf.load_model()
    hs_result = clf.predict("Sports footwear with textile upper")

    has_hs_keys = all(k in hs_result for k in ["hs_code", "confidence"])
    starts_64 = hs_result["hs_code"].startswith("64")

    print(f"  HS Classifier: hs_code={hs_result['hs_code']}, confidence={hs_result['confidence']:.4f}")
    if not has_hs_keys:
        print(f"    {RED}Missing keys. Got: {list(hs_result.keys())}{RESET}")
    if not starts_64:
        print(f"    {RED}HS code does not start with 64: {hs_result['hs_code']}{RESET}")

    # Duty Calculation
    calc = DutyCalculator()
    duty_result = calc.calculate(hs_code="640411", destination_country="DE", value_eur=100)

    pref_zero = duty_result["preferential_rate_pct"] == 0
    has_duty_keys = all(k in duty_result for k in ["duty_eur", "fta", "total_landed_cost_eur"])

    print(f"  Duty Calculator: pref_rate={duty_result['preferential_rate_pct']}%, "
          f"fta={duty_result['fta']}, duty={duty_result['duty_eur']}EUR")

    all_ok = has_hs_keys and starts_64 and pref_zero and has_duty_keys
    report("TradeFlow", all_ok,
           f"HS={hs_result['hs_code']} + Duty SAA=0% → LANDED={duty_result['total_landed_cost_eur']}EUR")

except Exception as e:
    results["TradeFlow"] = False
    print(f"  {RED}FAIL{RESET}  {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 3 — Knowledge Guardian (Vector Store)
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}TEST 3 — Knowledge Guardian{RESET}")
print(f"{DIM}{'─' * 55}{RESET}")
try:
    # Knowledge Guardian's vector_store.py uses relative import: from .doc_processor import ...
    # We need to register the package and its submodule first
    kg_dir = os.path.join(PROJECT_ROOT, "modules", "03_knowledge_guardian")
    doc_proc_mod = import_from("03_knowledge_guardian", "doc_processor")
    vs_mod = import_from("03_knowledge_guardian", "vector_store")
    VectorStore = vs_mod.VectorStore

    store = VectorStore()
    index_path = os.path.join(kg_dir, "store", "vector_index.pkl")
    store.load_index(index_path)

    search_results = store.search("finalna inspekcija kvaliteta", top_k=5)

    has_results = len(search_results) >= 1
    top_result = search_results[0] if has_results else {}
    sim_ok = top_result.get("similarity_score", 0) > 0.05
    has_source = "source_file" in top_result

    print(f"  Results: {len(search_results)} chunks found")
    if has_results:
        print(f"  Top: score={top_result['similarity_score']:.4f}, source={top_result.get('source_file', 'N/A')}")

    report("Knowledge Guardian", has_results and sim_ok and has_source,
           f"{len(search_results)} results, top_sim={top_result.get('similarity_score', 0):.4f}")

except Exception as e:
    results["Knowledge Guardian"] = False
    print(f"  {RED}FAIL{RESET}  {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 4 — Demand Forecast (Model Comparison)
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}TEST 4 — Demand Forecast{RESET}")
print(f"{DIM}{'─' * 55}{RESET}")
try:
    json_path = os.path.join(PROJECT_ROOT, "modules", "04_demand_forecast", "results", "model_comparison.json")
    with open(json_path) as f:
        comparison = json.load(f)

    models = comparison["models"]
    has_3_models = len(models) == 3

    all_metrics_ok = True
    for name, m in models.items():
        has_metrics = all(k in m for k in ["mae", "rmse", "mape"])
        if not has_metrics:
            all_metrics_ok = False
            print(f"    {RED}Model '{name}' missing metrics. Keys: {list(m.keys())}{RESET}")
        else:
            print(f"  {name}: MAE={m['mae']}, RMSE={m['rmse']}, MAPE={m['mape']}%")

    best = comparison.get("best_model", "")
    best_mape = models.get(best, {}).get("mape", 999)
    mape_ok = best_mape < 10

    report("Demand Forecast", has_3_models and all_metrics_ok and mape_ok,
           f"3 models, best={best} (MAPE={best_mape}%)")

except Exception as e:
    results["Demand Forecast"] = False
    print(f"  {RED}FAIL{RESET}  {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 5 — OEE Dashboard
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}TEST 5 — OEE Dashboard{RESET}")
print(f"{DIM}{'─' * 55}{RESET}")
try:
    oee_mod = import_from("05_oee_dashboard", "oee_calculator")
    OEECalculator = oee_mod.OEECalculator

    calc = OEECalculator()
    calc.load_data()

    oee_df = calc.calculate_oee("L1", period="monthly")

    has_columns = all(c in oee_df.columns for c in ["availability", "performance", "quality", "oee"])
    has_data = len(oee_df) > 0

    last = oee_df.iloc[-1]
    values_ok = all(0 <= last[c] <= 1 for c in ["availability", "performance", "quality", "oee"])

    print(f"  L1 OEE periods: {len(oee_df)}")
    print(f"  Latest: A={last['availability']:.2%} x P={last['performance']:.2%} "
          f"x Q={last['quality']:.2%} = OEE={last['oee']:.2%}")

    report("OEE Dashboard", has_columns and has_data and values_ok,
           f"L1 OEE={last['oee']:.2%}, {len(oee_df)} periods")

except Exception as e:
    results["OEE Dashboard"] = False
    print(f"  {RED}FAIL{RESET}  {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 6 — Brand Reporting (Nike Scorecard)
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}TEST 6 — Brand Reporting{RESET}")
print(f"{DIM}{'─' * 55}{RESET}")
try:
    templates_mod = import_from("06_brand_reporting", "templates")
    NikeScorecard = templates_mod.NikeScorecard

    scorecard = NikeScorecard()
    nike = scorecard.generate("2025-Q4")

    has_keys = all(k in nike for k in ["smsi_score", "quality", "delivery", "sustainability", "innovation"])
    smsi_range = 0 <= nike["smsi_score"] <= 100
    has_grade = "overall_grade" in nike

    print(f"  SMSI Score: {nike['smsi_score']}")
    print(f"  Grade: {nike['overall_grade']}, Trend: {nike.get('trend', 'N/A')}")
    print(f"  Quality: {nike['quality']['score']}, Delivery: {nike['delivery']['score']}, "
          f"Sustainability: {nike['sustainability']['score']}, Innovation: {nike['innovation']['score']}")

    report("Brand Reporting", has_keys and smsi_range and has_grade,
           f"SMSI={nike['smsi_score']}, Grade={nike['overall_grade']}")

except Exception as e:
    results["Brand Reporting"] = False
    print(f"  {RED}FAIL{RESET}  {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 7 — Dashboard HTML
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}TEST 7 — Dashboard{RESET}")
print(f"{DIM}{'─' * 55}{RESET}")
try:
    dashboard_path = os.path.join(PROJECT_ROOT, "dashboard", "index.html")
    exists = os.path.isfile(dashboard_path)

    with open(dashboard_path, "r", encoding="utf-8") as f:
        content = f.read()

    has_title = "SPORTEK AI PLATFORMA" in content
    line_count = content.count("\n") + 1
    enough_lines = line_count > 500

    print(f"  File exists: {exists}")
    print(f"  Contains 'SPORTEK AI PLATFORMA': {has_title}")
    print(f"  Lines: {line_count}")

    report("Dashboard", exists and has_title and enough_lines,
           f"{line_count} lines, title present")

except Exception as e:
    results["Dashboard"] = False
    print(f"  {RED}FAIL{RESET}  {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# TEST 8 — Data Integrity
# ════════════════════════════════════════════════════════════════════════
print(f"\n{BOLD}{CYAN}TEST 8 — Data Integrity{RESET}")
print(f"{DIM}{'─' * 55}{RESET}")
try:
    import pandas as pd

    all_ok = True

    # production_log: date, line_id, brand not null
    prod_path = os.path.join(PROJECT_ROOT, "data", "production", "production_log.csv")
    prod = pd.read_csv(prod_path)
    prod_nulls = prod[["date", "line_id", "brand"]].isnull().sum().sum()
    if prod_nulls > 0:
        print(f"    {RED}production_log: {prod_nulls} nulls in critical columns{RESET}")
        all_ok = False
    else:
        print(f"  production_log.csv: {len(prod)} rows, 0 nulls in date/line_id/brand")

    # defect_log: defect_type, severity not null
    defect_path = os.path.join(PROJECT_ROOT, "data", "quality", "defect_log.csv")
    defects = pd.read_csv(defect_path)
    defect_nulls = defects[["defect_type", "severity"]].isnull().sum().sum()
    if defect_nulls > 0:
        print(f"    {RED}defect_log: {defect_nulls} nulls in critical columns{RESET}")
        all_ok = False
    else:
        print(f"  defect_log.csv: {len(defects)} rows, 0 nulls in defect_type/severity")

    # inventory: material_id, hs_code not null
    inv_path = os.path.join(PROJECT_ROOT, "data", "supply_chain", "inventory.csv")
    inv = pd.read_csv(inv_path)
    inv_nulls = inv[["material_id", "hs_code"]].isnull().sum().sum()
    if inv_nulls > 0:
        print(f"    {RED}inventory: {inv_nulls} nulls in critical columns{RESET}")
        all_ok = False
    else:
        print(f"  inventory.csv: {len(inv)} rows, 0 nulls in material_id/hs_code")

    report("Data Integrity", all_ok,
           f"prod={len(prod)} rows, defects={len(defects)} rows, inv={len(inv)} rows")

except Exception as e:
    results["Data Integrity"] = False
    print(f"  {RED}FAIL{RESET}  {e}")
    traceback.print_exc()


# ════════════════════════════════════════════════════════════════════════
# FINAL REPORT
# ════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 55}")
print(f"{BOLD}{CYAN}  INTEGRATION TEST RESULTS{RESET}")
print(f"{'=' * 55}")

test_names = [
    ("Test 1 — CV Quality:     ", "CV Quality"),
    ("Test 2 — TradeFlow:      ", "TradeFlow"),
    ("Test 3 — Knowledge:      ", "Knowledge Guardian"),
    ("Test 4 — Demand Forecast:", "Demand Forecast"),
    ("Test 5 — OEE:            ", "OEE Dashboard"),
    ("Test 6 — Brand Reporting:", "Brand Reporting"),
    ("Test 7 — Dashboard:      ", "Dashboard"),
    ("Test 8 — Data Integrity: ", "Data Integrity"),
]

passed = 0
for label, key in test_names:
    status = results.get(key, False)
    if status:
        passed += 1
    indicator = f"{GREEN}PASS{RESET}" if status else f"{RED}FAIL{RESET}"
    print(f"  {label} {indicator}")

print(f"{'=' * 55}")
color = GREEN if passed == 8 else YELLOW if passed >= 6 else RED
print(f"  {BOLD}RESULT: {color}{passed}/8 PASSED{RESET}")
print(f"{'=' * 55}\n")

sys.exit(0 if passed == 8 else 1)
