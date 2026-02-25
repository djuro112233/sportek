"""
Sportek d.o.o. — CV Quality Module — ROI Calculation
Estimates return on investment for AI-powered visual quality control.

Usage:
    python modules/01_cv_quality/roi.py
"""

import json
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
DEFECT_CSV = PROJECT_ROOT / "data" / "quality" / "defect_log.csv"
PRODUCTION_CSV = PROJECT_ROOT / "data" / "production" / "production_log.csv"
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants — current QC operation
# ---------------------------------------------------------------------------
INSPECTORS_CURRENT = 15
INSPECTOR_SALARY_EUR_MONTH = 1_200
MONTHS_PER_YEAR = 12
AVG_INSPECTION_SEC = 45          # seconds per pair
WORKING_HOURS_DAY = 8
WORKING_DAYS_YEAR = 250
CAPACITY_PER_INSPECTOR_DAY = int(WORKING_HOURS_DAY * 3600 / AVG_INSPECTION_SEC)

# ---------------------------------------------------------------------------
# Constants — AI system
# ---------------------------------------------------------------------------
HARDWARE_COST_EUR = 25_000       # 5 cameras + edge PC, one-time
SOFTWARE_ANNUAL_EUR = 36_000     # licence + maintenance
INSPECTORS_AFTER_AI = 6          # verification team

# ---------------------------------------------------------------------------
# Quality improvement factors
# ---------------------------------------------------------------------------
SCRAP_REDUCTION_PCT = 25
REWORK_SAVING_PCT = 15
RETURN_REDUCTION_PCT = 30

# Unit cost assumptions (EUR per pair)
COST_SCRAP_PER_PAIR = 8.0        # material + labour lost
COST_REWORK_PER_PAIR = 3.5       # rework labour + material
COST_RETURN_PER_PAIR = 18.0      # return handling + shipping + brand penalty


def calculate_roi() -> dict:
    """Build full ROI model and return results dict."""

    # ── Load data ──────────────────────────────────────────────────────
    df_defects = pd.read_csv(DEFECT_CSV)
    df_prod = pd.read_csv(PRODUCTION_CSV)

    total_pairs = int(df_prod["actual_qty"].sum())
    total_defects = len(df_defects)

    action_counts = df_defects["action"].value_counts().to_dict()
    scrap_count = action_counts.get("scrap", 0)
    rework_count = action_counts.get("rework", 0)

    # Customer returns = detection_point == "customer_return"
    return_count = int(
        (df_defects["detection_point"] == "customer_return").sum()
    )

    # ── Current annual costs ───────────────────────────────────────────
    salary_current = INSPECTORS_CURRENT * INSPECTOR_SALARY_EUR_MONTH * MONTHS_PER_YEAR
    scrap_cost_annual = scrap_count * COST_SCRAP_PER_PAIR
    rework_cost_annual = rework_count * COST_REWORK_PER_PAIR
    return_cost_annual = return_count * COST_RETURN_PER_PAIR
    quality_cost_current = scrap_cost_annual + rework_cost_annual + return_cost_annual
    total_current = salary_current + quality_cost_current

    # ── AI system annual costs ─────────────────────────────────────────
    salary_after = INSPECTORS_AFTER_AI * INSPECTOR_SALARY_EUR_MONTH * MONTHS_PER_YEAR
    ai_annual = SOFTWARE_ANNUAL_EUR  # hardware is one-time, amortised below

    # ── Annual savings ─────────────────────────────────────────────────
    salary_saving = salary_current - salary_after

    scrap_saving = scrap_cost_annual * SCRAP_REDUCTION_PCT / 100
    rework_saving = rework_cost_annual * REWORK_SAVING_PCT / 100
    return_saving = return_cost_annual * RETURN_REDUCTION_PCT / 100
    quality_saving = scrap_saving + rework_saving + return_saving

    gross_annual_saving = salary_saving + quality_saving
    net_annual_saving = gross_annual_saving - ai_annual  # minus software cost
    # Year-1 includes hardware
    net_year1 = net_annual_saving - HARDWARE_COST_EUR

    # ── Payback period ─────────────────────────────────────────────────
    total_investment = HARDWARE_COST_EUR  # + first year software is in running cost
    if net_annual_saving > 0:
        payback_months = round(
            (HARDWARE_COST_EUR / net_annual_saving) * 12, 1
        )
    else:
        payback_months = float("inf")

    # 3-year ROI
    total_saving_3y = net_year1 + net_annual_saving * 2
    roi_3y_pct = round(total_saving_3y / (HARDWARE_COST_EUR + ai_annual * 3) * 100, 1)

    # ── Assemble result ────────────────────────────────────────────────
    result = {
        "production_data": {
            "total_pairs_produced": total_pairs,
            "total_defects_logged": total_defects,
            "scrap_count": scrap_count,
            "rework_count": rework_count,
            "customer_return_count": return_count,
        },
        "current_qc_costs_eur": {
            "inspectors": INSPECTORS_CURRENT,
            "salary_per_inspector_month": INSPECTOR_SALARY_EUR_MONTH,
            "annual_salary_total": salary_current,
            "capacity_pairs_per_inspector_day": CAPACITY_PER_INSPECTOR_DAY,
            "annual_scrap_cost": round(scrap_cost_annual, 2),
            "annual_rework_cost": round(rework_cost_annual, 2),
            "annual_return_cost": round(return_cost_annual, 2),
            "annual_quality_cost": round(quality_cost_current, 2),
            "annual_total_qc_cost": round(total_current, 2),
        },
        "ai_system_costs_eur": {
            "hardware_one_time": HARDWARE_COST_EUR,
            "software_annual": SOFTWARE_ANNUAL_EUR,
            "inspectors_retained": INSPECTORS_AFTER_AI,
            "annual_salary_after": salary_after,
            "annual_running_cost": round(salary_after + ai_annual, 2),
        },
        "annual_savings_eur": {
            "salary_reduction": round(salary_saving, 2),
            "scrap_reduction_25pct": round(scrap_saving, 2),
            "rework_reduction_15pct": round(rework_saving, 2),
            "return_reduction_30pct": round(return_saving, 2),
            "quality_saving_total": round(quality_saving, 2),
            "gross_annual_saving": round(gross_annual_saving, 2),
            "minus_software_cost": -SOFTWARE_ANNUAL_EUR,
            "net_annual_saving": round(net_annual_saving, 2),
            "net_year1_incl_hardware": round(net_year1, 2),
        },
        "roi_summary": {
            "payback_period_months": payback_months,
            "roi_3_year_percent": roi_3y_pct,
            "total_saving_3_years": round(total_saving_3y, 2),
            "estimated_defect_reduction": "25%",
            "estimated_speed_improvement": "10x",
        },
    }

    return result


def main() -> None:
    print("=" * 65)
    print("  SPORTEK d.o.o. — AI QC System — ROI Calculation")
    print("=" * 65)

    roi = calculate_roi()

    # Save JSON
    out_path = RESULT_DIR / "roi_calculation.json"
    with open(out_path, "w") as f:
        json.dump(roi, f, indent=2, ensure_ascii=False)
    print(f"\n  JSON saved → {out_path}\n")

    # Pretty-print summary
    cur = roi["current_qc_costs_eur"]
    ai = roi["ai_system_costs_eur"]
    sav = roi["annual_savings_eur"]
    sm = roi["roi_summary"]
    pd_ = roi["production_data"]

    print("  PRODUCTION DATA")
    print(f"    Total pairs produced:    {pd_['total_pairs_produced']:>10,}")
    print(f"    Total defects logged:    {pd_['total_defects_logged']:>10,}")
    print(f"    Scrap:                   {pd_['scrap_count']:>10,}")
    print(f"    Rework:                  {pd_['rework_count']:>10,}")
    print(f"    Customer returns:        {pd_['customer_return_count']:>10,}")

    print("\n  CURRENT QC COSTS (EUR/year)")
    print(f"    {cur['inspectors']} inspektora × {cur['salary_per_inspector_month']:,}/mj"
          f"    = {cur['annual_salary_total']:>10,}")
    print(f"    Troškovi škarta:         = {cur['annual_scrap_cost']:>10,.0f}")
    print(f"    Troškovi rework-a:       = {cur['annual_rework_cost']:>10,.0f}")
    print(f"    Troškovi vraćanja:       = {cur['annual_return_cost']:>10,.0f}")
    print(f"    ─────────────────────────────────────")
    print(f"    UKUPNO GODIŠNJE:         = {cur['annual_total_qc_cost']:>10,.0f}")

    print("\n  AI SYSTEM COSTS (EUR)")
    print(f"    Hardware (jednokratno):   = {ai['hardware_one_time']:>10,}")
    print(f"    Software (godišnje):      = {ai['software_annual']:>10,}")
    print(f"    {ai['inspectors_retained']} inspektora zadržano:      "
          f"= {ai['annual_salary_after']:>10,}/god")

    print("\n  ANNUAL SAVINGS (EUR)")
    print(f"    Smanjenje plata:         + {sav['salary_reduction']:>10,.0f}")
    print(f"    Smanjenje škarta (25%):  + {sav['scrap_reduction_25pct']:>10,.0f}")
    print(f"    Smanjenje rework (15%):  + {sav['rework_reduction_15pct']:>10,.0f}")
    print(f"    Smanjenje vraćanja (30%):+ {sav['return_reduction_30pct']:>10,.0f}")
    print(f"    Software trošak:         - {ai['software_annual']:>10,}")
    print(f"    ─────────────────────────────────────")
    print(f"    NETO GODIŠNJA UŠTEDA:    = {sav['net_annual_saving']:>10,.0f}")

    print(f"\n  ROI SUMMARY")
    print(f"    Payback period:            {sm['payback_period_months']} mjeseci")
    print(f"    3-year ROI:                {sm['roi_3_year_percent']}%")
    print(f"    3-year total saving:       {sm['total_saving_3_years']:,.0f} EUR")
    print(f"    Defect reduction:          {sm['estimated_defect_reduction']}")
    print(f"    Speed improvement:         {sm['estimated_speed_improvement']}")

    print("\n" + "=" * 65)


if __name__ == "__main__":
    main()
