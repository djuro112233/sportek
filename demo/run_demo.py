#!/usr/bin/env python3
"""
Sportek d.o.o. — AI Platform Interactive Demo
Walks through all 6 modules with live results.

Usage:
    python demo/run_demo.py
"""

import sys
import os
import json
import time
import importlib
import importlib.util

# ── Project root ────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ── Colours ─────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
DIM = "\033[2m"
RESET = "\033[0m"
BG_CYAN = "\033[46m"
BG_GREEN = "\033[42m"
WHITE = "\033[97m"


# ── Module import helper (numbered dirs) ────────────────────────────────
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


def section(title: str):
    print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}\n")


def pause():
    input(f"\n  {DIM}Pritisnite ENTER za sljedeći modul...{RESET}\n")


def header_line(text: str):
    print(f"  {BOLD}{text}{RESET}")


# ════════════════════════════════════════════════════════════════════════
# INTRO
# ════════════════════════════════════════════════════════════════════════
print()
print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
print(f"{BOLD}{WHITE}")
print(f"     SPORTEK AI PLATFORM — INTERACTIVE DEMO")
print(f"     Sportek d.o.o. | Zecchetto Group")
print(f"{RESET}")
print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
print()
print(f"  {DIM}6 AI modula | 872K EUR uštede | Svi podaci iz produkcije{RESET}")
print(f"  {DIM}Ovo je funkcionalni sistem, ne PowerPoint.{RESET}")

input(f"\n  Pritisnite ENTER za početak demo-a...")


# ════════════════════════════════════════════════════════════════════════
# MODUL 1 — CV QUALITY CONTROL
# ════════════════════════════════════════════════════════════════════════
section("MODUL 1 — CV QUALITY CONTROL")
print(f"  {DIM}Computer Vision za automatsku detekciju defekata na obući{RESET}\n")

try:
    mod = import_from("01_cv_quality", "inference")
    detector = mod.DefectDetector()
    model_path = os.path.join(PROJECT_ROOT, "modules", "01_cv_quality", "models", "defect_classifier.pkl")
    scaler_path = os.path.join(PROJECT_ROOT, "modules", "01_cv_quality", "models", "scaler.pkl")
    detector.load_model(model_path, scaler_path)

    img_dir = os.path.join(PROJECT_ROOT, "data", "quality", "defect_images")
    test_images = ["ok_001.png", "defect_001.png", "ok_005.png"]

    header_line("Analiza 3 uzorka:")
    print(f"  {'Slika':<20s} {'Predikcija':<12s} {'Confidence':>12s} {'Vrijeme':>10s}")
    print(f"  {'─' * 20} {'─' * 12} {'─' * 12} {'─' * 10}")

    for img_name in test_images:
        result = detector.predict(os.path.join(img_dir, img_name))
        pred = result["prediction"]
        conf = result["confidence"]
        ms = result["processing_time_ms"]
        color = GREEN if pred == "ok" else RED
        print(f"  {img_name:<20s} {color}{pred:<12s}{RESET} {conf:>11.1%} {ms:>8.1f}ms")

    print(f"\n  {YELLOW}→ AI detektuje defekte 10x brže od inspektora{RESET}")
    print(f"  {YELLOW}→ 94.2% tačnosti, 4.5s po paru (vs 45s ručno){RESET}")
    print(f"  {GREEN}→ ROI: €99,271/godišnje | Payback: 3 mjeseca{RESET}")

except Exception as e:
    print(f"  {RED}Greška: {e}{RESET}")

pause()


# ════════════════════════════════════════════════════════════════════════
# MODUL 2 — TRADEFLOW AI
# ════════════════════════════════════════════════════════════════════════
section("MODUL 2 — TRADEFLOW AI")
print(f"  {DIM}Automatska HS klasifikacija, duty optimizacija, DPP priprema{RESET}\n")

try:
    hs_mod = import_from("02_tradeflow", "hs_classifier")
    duty_mod = import_from("02_tradeflow", "duty_calculator")
    HSClassifier = hs_mod.HSClassifier
    DutyCalculator = duty_mod.DutyCalculator

    clf = HSClassifier()
    clf.load_model()
    calc = DutyCalculator()

    # HS Classification
    descs = [
        "Men's sports shoes with textile upper and rubber sole",
        "Waterproof rain boots, fully rubber, children's size",
    ]

    header_line("HS Klasifikacija:")
    for desc in descs:
        r = clf.predict(desc)
        print(f"  {DIM}\"{desc}\"{RESET}")
        print(f"    → {GREEN}{r['hs_code']}{RESET} {r['description']}  "
              f"(confidence: {r['confidence']:.0%})")
        if r.get("alternatives"):
            alt = r["alternatives"][0]
            print(f"      Alt: {alt['hs_code']} {alt['description']} ({alt['confidence']:.0%})")
        print()

    # Duty comparison: DE (SAA, 0%) vs US (MFN, 20%)
    header_line("Duty kalkulacija — HS 640411 (sportska obuća), €50,000 shipment:")
    print(f"  {'Destinacija':<14s} {'MFN Rate':>10s} {'Pref Rate':>10s} {'Duty':>12s} {'FTA':>20s} {'Ušteda':>12s}")
    print(f"  {'─' * 14} {'─' * 10} {'─' * 10} {'─' * 12} {'─' * 20} {'─' * 12}")

    for country in ["DE", "US"]:
        d = calc.calculate("640411", country, 50_000)
        savings = d["savings_vs_mfn_eur"]
        sav_str = f"{GREEN}€{savings:,.0f}{RESET}" if savings > 0 else "—"
        print(f"  {d['destination']:<14s} {d['mfn_rate_pct']:>9.1f}% {d['preferential_rate_pct']:>9.1f}% "
              f"€{d['duty_eur']:>10,.0f} {d['fta']:>20s} {sav_str:>12s}")

    print(f"\n  {YELLOW}→ SAA EU-BiH: 0% carina za izvoz u EU (vs 16.9% MFN){RESET}")
    print(f"  {YELLOW}→ DPP spremnost za EU regulativu 2027{RESET}")
    print(f"  {GREEN}→ ROI: €354,734/godišnje | Payback: <1 mjesec{RESET}")

except Exception as e:
    print(f"  {RED}Greška: {e}{RESET}")

pause()


# ════════════════════════════════════════════════════════════════════════
# MODUL 3 — KNOWLEDGE GUARDIAN
# ════════════════════════════════════════════════════════════════════════
section("MODUL 3 — KNOWLEDGE GUARDIAN")
print(f"  {DIM}RAG sistem za pretragu internih dokumenata na bosanskom jeziku{RESET}\n")

try:
    import_from("03_knowledge_guardian", "doc_processor")
    vs_mod = import_from("03_knowledge_guardian", "vector_store")
    VectorStore = vs_mod.VectorStore

    store = VectorStore()
    index_path = os.path.join(PROJECT_ROOT, "modules", "03_knowledge_guardian", "store", "vector_index.pkl")
    store.load_index(index_path)

    queries = [
        "Koji su koraci finalne inspekcije kvaliteta?",
        "Kako se podešava SHIMA SEIKI mašina za 3D knit?",
    ]

    for q in queries:
        header_line(f"UPIT: {q}")
        t0 = time.perf_counter()
        results = store.search(q, top_k=3)
        elapsed = (time.perf_counter() - t0) * 1000

        for r in results[:2]:
            score_color = GREEN if r["similarity_score"] >= 0.05 else DIM
            print(f"    #{r['rank']}  {score_color}score={r['similarity_score']:.4f}{RESET}"
                  f"  {BOLD}{r['source_file']}{RESET}")
            snippet = r["text"][:120].replace("\n", " ")
            print(f"        {DIM}{snippet}...{RESET}")

        print(f"    {DIM}Vrijeme: {elapsed:.0f}ms{RESET}\n")

    print(f"  {YELLOW}→ 247 document chunks indeksirano{RESET}")
    print(f"  {YELLOW}→ 80% pitanja odgovoreno za <1 sekundu{RESET}")
    print(f"  {GREEN}→ ROI: €20,431/godišnje | Payback: 7 mjeseci{RESET}")

except Exception as e:
    print(f"  {RED}Greška: {e}{RESET}")

pause()


# ════════════════════════════════════════════════════════════════════════
# MODUL 4 — DEMAND FORECASTING
# ════════════════════════════════════════════════════════════════════════
section("MODUL 4 — DEMAND FORECASTING")
print(f"  {DIM}ML predviđanje potražnje + optimizacija zaliha{RESET}\n")

try:
    # Model comparison
    json_path = os.path.join(PROJECT_ROOT, "modules", "04_demand_forecast", "results", "model_comparison.json")
    with open(json_path) as f:
        comparison = json.load(f)

    header_line("Model Performance Comparison:")
    print(f"  {'Model':<22s} {'MAE':>10s} {'RMSE':>10s} {'MAPE':>8s} {'Status':>10s}")
    print(f"  {'─' * 22} {'─' * 10} {'─' * 10} {'─' * 8} {'─' * 10}")

    best = comparison["best_model"]
    for name, m in comparison["models"].items():
        is_best = name == best
        color = GREEN if is_best else RESET
        star = " ★" if is_best else ""
        print(f"  {color}{name:<22s} {m['mae']:>10.1f} {m['rmse']:>10.1f} {m['mape']:>7.2f}% {star:>10s}{RESET}")

    # Stockout risks
    inv_mod = import_from("04_demand_forecast", "inventory_optimizer")
    optimizer = inv_mod.InventoryOptimizer()
    risks = optimizer.detect_stockout_risk(days_ahead=30)

    print()
    header_line(f"Stockout rizici (30 dana) — {len(risks)} materijala:")
    print(f"  {'Material':<16s} {'Naziv':<26s} {'Dana':>6s} {'Rizik':>8s} {'Narudžba':>10s}")
    print(f"  {'─' * 16} {'─' * 26} {'─' * 6} {'─' * 8} {'─' * 10}")

    for r in risks[:5]:
        color = RED if r["risk_level"] == "high" else YELLOW
        print(f"  {r['material_id']:<16s} {r['material_name'][:26]:<26s} "
              f"{r['days_until_stockout']:>5.1f} {color}{r['risk_level']:>8s}{RESET} "
              f"{r['recommended_order_qty']:>9,}")

    if len(risks) > 5:
        print(f"  {DIM}... i još {len(risks) - 5} materijala{RESET}")

    print(f"\n  {YELLOW}→ Random Forest: MAPE 3.03% — greška 3% na sedmičnom nivou{RESET}")
    print(f"  {YELLOW}→ {len(risks)} materijala sa rizikom stockout-a u 30 dana{RESET}")
    print(f"  {GREEN}→ ROI: €147,000/godišnje | Payback: 1 mjesec{RESET}")

except Exception as e:
    print(f"  {RED}Greška: {e}{RESET}")

pause()


# ════════════════════════════════════════════════════════════════════════
# MODUL 5 — OEE DASHBOARD
# ════════════════════════════════════════════════════════════════════════
section("MODUL 5 — OEE DASHBOARD")
print(f"  {DIM}Overall Equipment Effectiveness + Six Big Losses + prediktivna analitika{RESET}\n")

try:
    oee_mod = import_from("05_oee_dashboard", "oee_calculator")
    OEECalculator = oee_mod.OEECalculator

    calc = OEECalculator()
    calc.load_data()

    current = calc.get_current_oee()

    header_line("OEE po proizvodnim linijama (zadnji mjesec):")
    print(f"  {'Linija':<8s} {'Avail':>8s} {'Perf':>8s} {'Qual':>8s} {'OEE':>8s}  {'Trend':>12s}")
    print(f"  {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8}  {'─' * 12}")

    best_line = None
    worst_line = None
    best_oee = 0
    worst_oee = 1

    for lid in sorted(current):
        m = current[lid]
        oee_val = m["oee"]
        if oee_val > best_oee:
            best_oee = oee_val
            best_line = lid
        if oee_val < worst_oee:
            worst_oee = oee_val
            worst_line = lid

        color = GREEN if oee_val >= 0.75 else YELLOW if oee_val >= 0.65 else RED
        trend_color = GREEN if m["trend"] == "improving" else RED if m["trend"] == "declining" else DIM
        print(f"  {lid:<8s} {m['availability']:>7.1%} {m['performance']:>7.1%} "
              f"{m['quality']:>7.1%} {color}{oee_val:>7.1%}{RESET}  "
              f"{trend_color}{m['trend']:>12s}{RESET}")

    print(f"\n  {GREEN}Najbolja: {best_line} ({best_oee:.1%}){RESET}")
    print(f"  {RED}Najlošija: {worst_line} ({worst_oee:.1%}){RESET}")

    # Six Big Losses for worst line
    losses = calc.identify_losses(worst_line)
    al = losses["availability_losses"]
    pl = losses["performance_losses"]

    print(f"\n  {BOLD}Six Big Losses — {worst_line}:{RESET}")
    print(f"    Breakdowns:    {RED}{al['breakdowns_min']:>6,} min{RESET}")
    print(f"    Changeover:    {YELLOW}{al['setup_changeover_min']:>6,} min{RESET}")
    print(f"    Speed Loss:    {YELLOW}{pl['speed_loss_min']:>6,} min{RESET}")
    print(f"    Minor Stops:   {DIM}{pl['minor_stops_min']:>6,} min{RESET}")

    print(f"\n  {YELLOW}→ Prosječan OEE: 76.3% (World-class target: 85%){RESET}")
    print(f"  {YELLOW}→ Svaki procentni poen OEE = ~€22K godišnje{RESET}")
    print(f"  {GREEN}→ ROI: €198,000/godišnje | Payback: <1 mjesec{RESET}")

except Exception as e:
    print(f"  {RED}Greška: {e}{RESET}")

pause()


# ════════════════════════════════════════════════════════════════════════
# MODUL 6 — BRAND REPORTING
# ════════════════════════════════════════════════════════════════════════
section("MODUL 6 — BRAND REPORTING")
print(f"  {DIM}Automatski izvještaji za Nike SMSI, Crocs, Decathlon{RESET}\n")

try:
    templates_mod = import_from("06_brand_reporting", "templates")
    NikeScorecard = templates_mod.NikeScorecard
    CrocsReport = templates_mod.CrocsReport
    DecathlonReport = templates_mod.DecathlonReport

    period = "2025-Q4"

    # Nike SMSI
    nike = NikeScorecard().generate(period)
    grade = nike["overall_grade"]
    grade_color = GREEN if grade == "Gold" else YELLOW if grade in ("Silver", "Bronze") else RED

    header_line(f"Nike SMSI Scorecard — {period}:")
    print(f"  {'Kategorija':<18s} {'Score':>8s} {'Weight':>8s}")
    print(f"  {'─' * 18} {'─' * 8} {'─' * 8}")
    for cat in ["quality", "delivery", "sustainability", "innovation"]:
        data = nike[cat]
        print(f"  {cat.capitalize():<18s} {data['score']:>7.1f} {data['weight']:>7d}%")
    print(f"  {'─' * 36}")
    print(f"  {BOLD}{'SMSI Score':<18s} {grade_color}{nike['smsi_score']:>7.1f}{RESET}  {grade_color}{grade}{RESET}")
    print(f"  Trend: {nike['trend']}")

    # Crocs
    crocs = CrocsReport().generate(period)
    print(f"\n  {BOLD}Crocs:{RESET} {crocs['production']['total_units']:,} units | "
          f"FPY={crocs['quality']['fpy']:.1%} | OTD={crocs['delivery']['otd_pct']}%")

    # Decathlon
    deca = DecathlonReport().generate(period)
    print(f"  {BOLD}Decathlon:{RESET} {deca['production']['total_units']:,} units | "
          f"Carbon={deca['sustainability']['per_unit']}kg/unit | Efficiency={deca['production']['efficiency']}%")

    # Alerts
    alerts = 0
    if nike["smsi_score"] < 75:
        alerts += 1
    if crocs["quality"]["aql_status"] == "fail":
        alerts += 1
    if deca["sustainability"]["per_unit"] > 10:
        alerts += 1

    alert_color = RED if alerts > 0 else GREEN
    print(f"\n  {alert_color}Aktivni alerti: {alerts}{RESET}")

    print(f"\n  {YELLOW}→ Izvještaj se generiše za 15 sekundi (vs 3 dana ručno){RESET}")
    print(f"  {YELLOW}→ Gold SMSI (82+) = prioritet za nove Nike modele{RESET}")
    print(f"  {GREEN}→ ROI: €52,571/godišnje | Payback: <1 mjesec{RESET}")

except Exception as e:
    print(f"  {RED}Greška: {e}{RESET}")

pause()


# ════════════════════════════════════════════════════════════════════════
# FINALE — AGREGIRANI ROI
# ════════════════════════════════════════════════════════════════════════
print()
print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
print(f"{BOLD}{WHITE}  AGREGIRANI ROI — SPORTEK AI PLATFORMA{RESET}")
print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")

roi_data = [
    ("CV Quality Control",  99_271, 205, "3 mj"),
    ("TradeFlow AI",       354_734, 1582, "<1 mj"),
    ("Knowledge Guardian",  20_431, 170, "7 mj"),
    ("Demand Forecasting", 147_000, 720, "1 mj"),
    ("OEE Dashboard",      198_000, 890, "<1 mj"),
    ("Brand Reporting",     52_571, 1971, "<1 mj"),
]

print(f"\n  {'Modul':<24s} {'Godišnja ušteda':>16s} {'ROI':>8s} {'Payback':>10s}")
print(f"  {'─' * 24} {'─' * 16} {'─' * 8} {'─' * 10}")

total = 0
for name, savings, roi, payback in roi_data:
    total += savings
    print(f"  {name:<24s} {GREEN}€{savings:>13,}{RESET} {roi:>7,}% {payback:>10s}")

print(f"  {'─' * 60}")
print(f"  {BOLD}{'UKUPNO':<24s} {GREEN}€{total:>13,}{RESET}{BOLD} {'':>8s} {'':>10s}{RESET}")
print(f"\n  {BOLD}Investicija:     €142,000{RESET}")
print(f"  {BOLD}Godišnja ušteda: {GREEN}€{total:,}{RESET}")
print(f"  {BOLD}ROI:             {GREEN}614%{RESET}")
print(f"  {BOLD}Payback:         {GREEN}<2 mjeseca{RESET}")

print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
print(f"\n  {BOLD}Demo završen. Hvala na pažnji!{RESET}")
print(f"  {DIM}Kontakt: info@sportek.ba | Zecchetto Group{RESET}")
print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}\n")
