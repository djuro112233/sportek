"""
Sportek d.o.o. — TradeFlow AI — ROI Calculation
Estimates return on investment for AI-powered trade-compliance automation.

Usage:
    python modules/02_tradeflow/roi.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
PO_CSV = PROJECT_ROOT / "data" / "supply_chain" / "purchase_orders.csv"
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants — current manual operation
# ---------------------------------------------------------------------------
COMPLIANCE_WORKERS = 2
COMPLIANCE_SALARY_EUR_MONTH = 1_800
MONTHS_PER_YEAR = 12
EXTERNAL_BROKER_EUR_YEAR = 12_000
CLASSIFICATION_ERROR_RATE = 0.03       # 3 % of shipments mis-classified
PENALTY_PER_ERROR_EUR = 25_000         # annual total: penalties + delays + reship

# ---------------------------------------------------------------------------
# Constants — AI system
# ---------------------------------------------------------------------------
AI_AUTO_CLASSIFICATION_PCT = 95        # % automated
AI_ERROR_RATE = 0.02                   # 2 % vs 5 % manual
WORKERS_AFTER_AI = 1
SOFTWARE_COST_EUR_YEAR = 24_000
FTA_OPTIMISATION_SAVING_PCT = 3.0      # on total export value

# ---------------------------------------------------------------------------
# DPP non-compliance risk (EU 2027+)
# ---------------------------------------------------------------------------
DPP_PENALTY_LOW = 50_000
DPP_PENALTY_HIGH = 100_000


def calculate_roi() -> dict:
    """Build full TradeFlow ROI model."""

    # ── Load export value from PO data ─────────────────────────────────
    df_po = pd.read_csv(PO_CSV)
    total_export_value = float(df_po["total_eur"].sum())
    total_shipments = len(df_po)

    # ── Current annual costs ───────────────────────────────────────────
    salary_current = COMPLIANCE_WORKERS * COMPLIANCE_SALARY_EUR_MONTH * MONTHS_PER_YEAR
    broker_cost = EXTERNAL_BROKER_EUR_YEAR
    error_cost = PENALTY_PER_ERROR_EUR  # already annual total
    total_current = salary_current + broker_cost + error_cost

    # ── AI system savings ──────────────────────────────────────────────
    salary_after = WORKERS_AFTER_AI * COMPLIANCE_SALARY_EUR_MONTH * MONTHS_PER_YEAR
    salary_saving = salary_current - salary_after

    # Error reduction: from 3% to <2% — saves 20,000 EUR/year
    error_reduction_saving = round(error_cost * (1 - AI_ERROR_RATE / CLASSIFICATION_ERROR_RATE), 2)

    # FTA optimisation: 3% of total export value
    fta_saving = round(total_export_value * FTA_OPTIMISATION_SAVING_PCT / 100, 2)

    # DPP readiness: avoided penalties (mid estimate)
    dpp_avoided = round((DPP_PENALTY_LOW + DPP_PENALTY_HIGH) / 2, 2)

    # Gross & net
    gross_annual = salary_saving + error_reduction_saving + fta_saving
    net_annual = gross_annual - SOFTWARE_COST_EUR_YEAR
    net_annual_with_dpp = net_annual + dpp_avoided  # from 2027

    # Payback
    if net_annual > 0:
        payback_months = round(SOFTWARE_COST_EUR_YEAR / net_annual * 12, 1)
    else:
        payback_months = float("inf")

    # 3-year: years 1-2 without DPP penalty avoidance, year 3 with it
    total_3y = net_annual * 2 + net_annual_with_dpp
    investment_3y = SOFTWARE_COST_EUR_YEAR * 3
    roi_3y_pct = round(total_3y / investment_3y * 100, 1)

    result = {
        "data_inputs": {
            "total_export_value_eur": round(total_export_value, 2),
            "total_shipments": total_shipments,
            "source": "data/supply_chain/purchase_orders.csv",
        },
        "current_costs_eur": {
            "compliance_workers": COMPLIANCE_WORKERS,
            "salary_per_worker_month": COMPLIANCE_SALARY_EUR_MONTH,
            "annual_salary_total": salary_current,
            "external_broker_annual": broker_cost,
            "classification_error_rate_pct": CLASSIFICATION_ERROR_RATE * 100,
            "annual_error_penalties": error_cost,
            "annual_total": total_current,
        },
        "ai_system": {
            "auto_classification_pct": AI_AUTO_CLASSIFICATION_PCT,
            "ai_error_rate_pct": AI_ERROR_RATE * 100,
            "workers_retained": WORKERS_AFTER_AI,
            "annual_salary_after": salary_after,
            "software_cost_annual": SOFTWARE_COST_EUR_YEAR,
            "annual_running_cost": salary_after + SOFTWARE_COST_EUR_YEAR,
        },
        "annual_savings_eur": {
            "salary_reduction": round(salary_saving, 2),
            "error_reduction": round(error_reduction_saving, 2),
            "fta_optimisation_3pct": round(fta_saving, 2),
            "fta_calculation_base": round(total_export_value, 2),
            "gross_annual_saving": round(gross_annual, 2),
            "minus_software_cost": -SOFTWARE_COST_EUR_YEAR,
            "net_annual_saving": round(net_annual, 2),
            "dpp_penalty_avoidance_2027": round(dpp_avoided, 2),
            "net_annual_with_dpp_2027": round(net_annual_with_dpp, 2),
        },
        "roi_summary": {
            "payback_period_months": payback_months,
            "roi_3_year_pct": roi_3y_pct,
            "total_saving_3_years_eur": round(total_3y, 2),
            "software_investment_3_years_eur": investment_3y,
        },
    }
    return result


def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print()
    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK d.o.o. — TradeFlow AI — ROI Calculation{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")

    roi = calculate_roi()

    # Save JSON
    out_path = RESULT_DIR / "tradeflow_roi.json"
    with open(out_path, "w") as f:
        json.dump(roi, f, indent=2, ensure_ascii=False)
    print(f"\n  JSON saved → {out_path}\n")

    d = roi["data_inputs"]
    cur = roi["current_costs_eur"]
    ai = roi["ai_system"]
    sav = roi["annual_savings_eur"]
    sm = roi["roi_summary"]

    print("  DATA INPUTS")
    print(f"    Total export value:      {d['total_export_value_eur']:>12,.2f} EUR")
    print(f"    Total shipments:         {d['total_shipments']:>12,}")

    print("\n  CURRENT COSTS (EUR/year)")
    print(f"    {cur['compliance_workers']} compliance radnika × {cur['salary_per_worker_month']:,}/mj"
          f"  = {cur['annual_salary_total']:>10,}")
    print(f"    Vanjski customs broker:       = {cur['external_broker_annual']:>10,}")
    print(f"    Greške ({cur['classification_error_rate_pct']}% shipments):"
          f"    = {cur['annual_error_penalties']:>10,}")
    print(f"    ─────────────────────────────────────")
    print(f"    UKUPNO GODIŠNJE:              = {cur['annual_total']:>10,}")

    print("\n  AI SYSTEM")
    print(f"    Automatska klasifikacija:       {ai['auto_classification_pct']}%")
    print(f"    AI error rate:                  {ai['ai_error_rate_pct']}% (vs {cur['classification_error_rate_pct']}% manual)")
    print(f"    Zadržan {ai['workers_retained']} radnik:              = {ai['annual_salary_after']:>10,}/god")
    print(f"    Software trošak:                = {ai['software_cost_annual']:>10,}/god")

    print("\n  ANNUAL SAVINGS (EUR)")
    print(f"    Smanjenje plata (2→1):       + {sav['salary_reduction']:>10,.0f}")
    print(f"    Smanjenje grešaka:           + {sav['error_reduction']:>10,.0f}")
    print(f"    FTA optimizacija (3%):       + {sav['fta_optimisation_3pct']:>10,.0f}")
    print(f"    {DIM}  (3% od {sav['fta_calculation_base']:,.0f} EUR export){RESET}")
    print(f"    Software trošak:             - {ai['software_cost_annual']:>10,}")
    print(f"    ─────────────────────────────────────")
    print(f"    {BOLD}NETO GODIŠNJA UŠTEDA:        = {GREEN}{sav['net_annual_saving']:>10,.0f} EUR{RESET}")
    print(f"    DPP izbjegnute kazne (2027+):+ {YELLOW}{sav['dpp_penalty_avoidance_2027']:>10,.0f} EUR{RESET}")
    print(f"    Neto sa DPP (od 2027):       = {GREEN}{sav['net_annual_with_dpp_2027']:>10,.0f} EUR{RESET}")

    print(f"\n  ROI SUMMARY")
    print(f"    Payback period:              {sm['payback_period_months']} mjeseci")
    print(f"    3-year ROI:                  {sm['roi_3_year_pct']}%")
    print(f"    3-year total saving:         {sm['total_saving_3_years_eur']:,.0f} EUR")

    print(f"\n{'=' * 65}\n")


if __name__ == "__main__":
    main()
