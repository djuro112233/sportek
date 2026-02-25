"""
Sportek d.o.o. — Demand Forecast — ROI Calculation
Computes ROI from REAL inventory.csv and purchase_orders.csv data.

Usage:
    python -m modules.04_demand_forecast.roi
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
INV_CSV = PROJECT_ROOT / "data" / "supply_chain" / "inventory.csv"
PO_CSV = PROJECT_ROOT / "data" / "supply_chain" / "purchase_orders.csv"
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# Constants
RUSH_ORDER_PREMIUM = 0.30       # 30% surcharge on rush orders
HOLDING_COST_PCT = 0.20         # 20% of value per year
PLANNING_PEOPLE = 2
PLANNING_HOURS_WEEK = 4
PLANNING_WEEKS = 52
PLANNING_RATE_EUR_H = 15
SOFTWARE_COST_EUR_YEAR = 18_000
STOCKOUT_REDUCTION_PCT = 40
OVERSTOCK_REDUCTION_PCT = 25
PLANNING_AUTOMATION_PCT = 80


def calculate_roi() -> dict:
    """Build ROI from actual inventory and PO data."""

    inv = pd.read_csv(INV_CSV)
    po = pd.read_csv(PO_CSV)

    # ── 1. Stockout cost ───────────────────────────────────────────────
    # Materials where current_stock < consumption_rate_daily × lead_time_days
    inv["needed_stock"] = inv["consumption_rate_daily"] * inv["lead_time_days"]
    stockout_mask = inv["current_stock"] < inv["needed_stock"]
    stockout_items = inv[stockout_mask].copy()
    n_stockout = len(stockout_items)

    # Deficit units that need rush ordering
    stockout_items["deficit"] = stockout_items["needed_stock"] - stockout_items["current_stock"]
    stockout_items["normal_cost"] = stockout_items["deficit"] * stockout_items["unit_price_eur"]
    stockout_items["rush_surcharge"] = stockout_items["normal_cost"] * RUSH_ORDER_PREMIUM

    # Annualise: assume this situation repeats ~4× per year (quarterly replenishment cycles)
    annual_rush_cost = round(float(stockout_items["rush_surcharge"].sum()) * 4, 2)
    total_deficit_value = round(float(stockout_items["normal_cost"].sum()), 2)

    # ── 2. Overstock cost ──────────────────────────────────────────────
    # Materials with days_of_stock > 90
    inv["days_of_stock"] = np.where(
        inv["consumption_rate_daily"] > 0,
        inv["current_stock"] / inv["consumption_rate_daily"],
        0,
    )
    overstock_mask = inv["days_of_stock"] > 90
    overstock_items = inv[overstock_mask].copy()
    n_overstock = len(overstock_items)

    overstock_items["inventory_value"] = (
        overstock_items["current_stock"] * overstock_items["unit_price_eur"]
    )
    tied_capital = round(float(overstock_items["inventory_value"].sum()), 2)
    annual_holding_cost = round(tied_capital * HOLDING_COST_PCT, 2)

    # ── 3. Manual planning cost ────────────────────────────────────────
    planning_cost = PLANNING_PEOPLE * PLANNING_HOURS_WEEK * PLANNING_WEEKS * PLANNING_RATE_EUR_H

    # ── Total current cost ─────────────────────────────────────────────
    total_current = annual_rush_cost + annual_holding_cost + planning_cost

    # ── AI savings ─────────────────────────────────────────────────────
    stockout_saving = round(annual_rush_cost * STOCKOUT_REDUCTION_PCT / 100, 2)
    holding_saving = round(annual_holding_cost * OVERSTOCK_REDUCTION_PCT / 100, 2)
    freed_capital = round(tied_capital * OVERSTOCK_REDUCTION_PCT / 100, 2)
    planning_saving = round(planning_cost * PLANNING_AUTOMATION_PCT / 100, 2)

    gross_annual = stockout_saving + holding_saving + planning_saving
    net_annual = gross_annual - SOFTWARE_COST_EUR_YEAR

    # Payback
    if gross_annual > 0:
        payback_months = round(SOFTWARE_COST_EUR_YEAR / gross_annual * 12, 1)
    else:
        payback_months = float("inf")

    # 3-year projection
    total_3y = net_annual * 3
    investment_3y = SOFTWARE_COST_EUR_YEAR * 3
    roi_3y_pct = round(total_3y / investment_3y * 100, 1) if investment_3y else 0

    # PO stats for context
    total_po_value = round(float(po["total_eur"].sum()), 2)
    avg_delay = round(float(po["delay_days"].mean()), 1)

    result = {
        "data_inputs": {
            "total_materials": len(inv),
            "total_purchase_orders": len(po),
            "total_po_value_eur": total_po_value,
            "avg_delivery_delay_days": avg_delay,
        },
        "current_costs_eur": {
            "stockout_rush_orders": {
                "materials_below_safety": n_stockout,
                "deficit_value_eur": total_deficit_value,
                "rush_premium_pct": RUSH_ORDER_PREMIUM * 100,
                "annual_rush_cost": annual_rush_cost,
            },
            "overstock_holding": {
                "materials_over_90_days": n_overstock,
                "tied_capital_eur": tied_capital,
                "holding_cost_pct": HOLDING_COST_PCT * 100,
                "annual_holding_cost": annual_holding_cost,
            },
            "manual_planning": {
                "people": PLANNING_PEOPLE,
                "hours_per_week": PLANNING_HOURS_WEEK,
                "rate_eur_h": PLANNING_RATE_EUR_H,
                "annual_cost": planning_cost,
            },
            "annual_total": round(total_current, 2),
        },
        "ai_savings_eur": {
            "stockout_reduction_40pct": stockout_saving,
            "holding_cost_reduction_25pct": holding_saving,
            "freed_capital_25pct": freed_capital,
            "planning_automation_80pct": planning_saving,
            "gross_annual_saving": round(gross_annual, 2),
            "minus_software_cost": -SOFTWARE_COST_EUR_YEAR,
            "net_annual_saving": round(net_annual, 2),
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
    RED = "\033[91m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN}{'=' * 65}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK d.o.o. — Demand Forecast — ROI Calculation{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")

    roi = calculate_roi()

    out_path = RESULT_DIR / "forecast_roi.json"
    with open(out_path, "w") as f:
        json.dump(roi, f, indent=2, ensure_ascii=False)
    print(f"\n  JSON saved → {out_path}\n")

    d = roi["data_inputs"]
    cur = roi["current_costs_eur"]
    sav = roi["ai_savings_eur"]
    sm = roi["roi_summary"]
    so = cur["stockout_rush_orders"]
    ov = cur["overstock_holding"]
    pl = cur["manual_planning"]

    print(f"  DATA INPUTS")
    print(f"    Materijala u inventaru:    {d['total_materials']}")
    print(f"    Purchase orders:           {d['total_purchase_orders']}")
    print(f"    Ukupna PO vrijednost:      {d['total_po_value_eur']:>12,.0f} EUR")
    print(f"    Prosječno kašnjenje:        {d['avg_delivery_delay_days']} dana")

    print(f"\n  TRENUTNI TROŠKOVI (EUR/god)")
    print(f"    {RED}Stockout / hitne narudžbe:{RESET}")
    print(f"      Materijala ispod safety:   {so['materials_below_safety']}")
    print(f"      Rush premium ({so['rush_premium_pct']:.0f}%):        = {so['annual_rush_cost']:>12,.0f}")
    print(f"    {YELLOW}Višak inventara (>90 dana):{RESET}")
    print(f"      Materijala sa viškom:       {ov['materials_over_90_days']}")
    print(f"      Vezani kapital:             = {ov['tied_capital_eur']:>12,.0f}")
    print(f"      Holding cost (20%):         = {ov['annual_holding_cost']:>12,.0f}")
    print(f"    Ručno planiranje:")
    print(f"      {pl['people']} osobe × {pl['hours_per_week']}h/sed × 52 × {pl['rate_eur_h']} EUR"
          f"  = {pl['annual_cost']:>12,}")
    print(f"    {'─' * 50}")
    print(f"    {BOLD}UKUPNO GODIŠNJE:                  = {cur['annual_total']:>12,.0f}{RESET}")

    print(f"\n  AI UŠTEDE (EUR/god)")
    print(f"    Smanjenje stockout-a (40%):   + {sav['stockout_reduction_40pct']:>10,.0f}")
    print(f"    Smanjenje holdinga (25%):     + {sav['holding_cost_reduction_25pct']:>10,.0f}")
    print(f"    {DIM}(oslobođen kapital:              {sav['freed_capital_25pct']:>10,.0f}){RESET}")
    print(f"    Automatizacija planir. (80%): + {sav['planning_automation_80pct']:>10,.0f}")
    print(f"    {'─' * 50}")
    print(f"    Bruto ušteda:                 = {sav['gross_annual_saving']:>10,.0f}")
    print(f"    Software trošak:              - {abs(sav['minus_software_cost']):>10,}")
    print(f"    {'─' * 50}")
    print(f"    {BOLD}NETO GODIŠNJA UŠTEDA:         = {GREEN}{sav['net_annual_saving']:>10,.0f} EUR{RESET}")

    print(f"\n  ROI SUMMARY")
    print(f"    Payback period:              {YELLOW}{sm['payback_period_months']} mjeseci{RESET}")
    print(f"    3-year ROI:                  {GREEN}{sm['roi_3_year_pct']}%{RESET}")
    print(f"    3-year total saving:         {GREEN}{sm['total_saving_3_years_eur']:,.0f} EUR{RESET}")

    print(f"\n{'=' * 65}\n")


if __name__ == "__main__":
    main()
