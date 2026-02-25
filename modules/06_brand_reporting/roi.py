"""
Sportek d.o.o. — Brand Reporting — ROI Analysis
ROI calculation: manual reporting costs vs. AI-automated brand reporting system.

Usage:
    python -m modules.06_brand_reporting.roi
"""

from __future__ import annotations

import json
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ── Business Constants ────────────────────────────────────────────────────
# Manual reporting costs
REPORT_PREP_PERSON = 1          # person
REPORT_PREP_DAYS_MONTH = 3      # days per month
REPORT_PREP_HOURS_DAY = 8       # hours per day
REPORT_PREP_RATE_EUR_H = 15     # EUR/hour
REPORT_PREP_MONTHS = 12

QC_REVIEW_HOURS_MONTH = 8       # hours per month
QC_REVIEW_RATE_EUR_H = 18       # EUR/hour
QC_REVIEW_MONTHS = 12

REPORTING_ERROR_PENALTY_EUR = 5_000  # Nike late submission / inaccurate data penalties

# AI system costs
SOFTWARE_COST_EUR_YEAR = 8_000   # EUR/year

# AI improvements
AI_GENERATION_MINUTES = 15       # vs 3 days manual
AI_REVIEW_HOURS = 2              # vs 8 hours manual
AI_DATA_ERROR_RATE = 0.0         # zero data errors
GOLD_SMSI_EXTRA_ORDERS_EUR = 50_000  # estimated extra orders if Gold SMSI achieved


def calculate_roi() -> dict:
    """Calculate ROI from automated brand reporting system."""

    # ── Current Manual Costs ───────────────────────────────────────────
    report_prep_cost = (REPORT_PREP_PERSON * REPORT_PREP_DAYS_MONTH *
                        REPORT_PREP_HOURS_DAY * REPORT_PREP_MONTHS *
                        REPORT_PREP_RATE_EUR_H)
    # = 1 × 3 × 8 × 12 × 15 = 4,320 EUR/god

    qc_review_cost = (QC_REVIEW_HOURS_MONTH * QC_REVIEW_MONTHS *
                      QC_REVIEW_RATE_EUR_H)
    # = 8 × 12 × 18 = 1,728 EUR/god

    error_penalty_cost = REPORTING_ERROR_PENALTY_EUR
    # = 5,000 EUR/god

    total_manual_cost = report_prep_cost + qc_review_cost + error_penalty_cost
    # = 11,048 EUR/god

    # ── AI System Savings ──────────────────────────────────────────────
    # Time savings: report prep
    manual_prep_hours = REPORT_PREP_DAYS_MONTH * REPORT_PREP_HOURS_DAY * REPORT_PREP_MONTHS
    ai_prep_hours = (AI_GENERATION_MINUTES / 60) * REPORT_PREP_MONTHS
    prep_time_saved_hours = manual_prep_hours - ai_prep_hours
    prep_saving_eur = round(prep_time_saved_hours * REPORT_PREP_RATE_EUR_H)

    # Time savings: QC review
    manual_review_hours = QC_REVIEW_HOURS_MONTH * QC_REVIEW_MONTHS
    ai_review_hours = AI_REVIEW_HOURS * QC_REVIEW_MONTHS
    review_time_saved_hours = manual_review_hours - ai_review_hours
    review_saving_eur = round(review_time_saved_hours * QC_REVIEW_RATE_EUR_H)

    # Error elimination
    error_saving_eur = REPORTING_ERROR_PENALTY_EUR

    # SMSI improvement opportunity (Gold status)
    smsi_opportunity_eur = GOLD_SMSI_EXTRA_ORDERS_EUR

    # ── Financial Summary ──────────────────────────────────────────────
    direct_savings = prep_saving_eur + review_saving_eur + error_saving_eur
    total_annual_benefit = direct_savings + smsi_opportunity_eur
    net_annual_saving = total_annual_benefit - SOFTWARE_COST_EUR_YEAR
    payback_months = round(SOFTWARE_COST_EUR_YEAR / (total_annual_benefit / 12), 1) if total_annual_benefit > 0 else 0
    roi_3yr = round((net_annual_saving * 3) / SOFTWARE_COST_EUR_YEAR * 100, 1)

    result = {
        "current_costs_eur": {
            "report_preparation": {
                "description": f"{REPORT_PREP_PERSON} person × {REPORT_PREP_DAYS_MONTH} days/month × 12 months × {REPORT_PREP_RATE_EUR_H} EUR/h",
                "annual_cost": report_prep_cost,
            },
            "qc_manager_review": {
                "description": f"{QC_REVIEW_HOURS_MONTH}h/month × 12 months × {QC_REVIEW_RATE_EUR_H} EUR/h",
                "annual_cost": qc_review_cost,
            },
            "reporting_errors_penalties": {
                "description": "Nike late submission penalties, inaccurate data corrections",
                "annual_cost": error_penalty_cost,
            },
            "total_manual_cost": total_manual_cost,
        },
        "ai_improvements": {
            "report_generation": {
                "description": f"15 min vs {REPORT_PREP_DAYS_MONTH} days — automated generation",
                "time_saved_hours_annual": round(prep_time_saved_hours, 1),
                "saving_eur": prep_saving_eur,
            },
            "review_optimization": {
                "description": f"{AI_REVIEW_HOURS}h vs {QC_REVIEW_HOURS_MONTH}h review — pre-validated data",
                "time_saved_hours_annual": round(review_time_saved_hours, 1),
                "saving_eur": review_saving_eur,
            },
            "error_elimination": {
                "description": "Zero data errors — eliminates penalties",
                "error_rate": AI_DATA_ERROR_RATE,
                "saving_eur": error_saving_eur,
            },
            "smsi_improvement_opportunity": {
                "description": "Gold SMSI = priority for new orders (+50k EUR/year estimated)",
                "potential_extra_revenue_eur": smsi_opportunity_eur,
            },
        },
        "roi_summary": {
            "total_manual_cost_eur": total_manual_cost,
            "direct_savings_eur": direct_savings,
            "smsi_opportunity_eur": smsi_opportunity_eur,
            "total_annual_benefit_eur": total_annual_benefit,
            "software_cost_annual_eur": SOFTWARE_COST_EUR_YEAR,
            "net_annual_saving_eur": net_annual_saving,
            "payback_months": payback_months,
            "roi_3yr_pct": roi_3yr,
        },
    }

    # Save
    with open(RESULT_DIR / "reporting_roi.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK — Brand Reporting — ROI Analysis{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}\n")

    result = calculate_roi()
    cc = result["current_costs_eur"]
    ai = result["ai_improvements"]
    rs = result["roi_summary"]

    # Current costs
    print(f"  {BOLD}Trenutni troškovi ručnog reportinga:{RESET}")
    print(f"    Priprema izvještaja:     {RED}{cc['report_preparation']['annual_cost']:>10,} EUR/god{RESET}")
    print(f"    QC menadžer review:      {RED}{cc['qc_manager_review']['annual_cost']:>10,} EUR/god{RESET}")
    print(f"    Greške/penali:           {RED}{cc['reporting_errors_penalties']['annual_cost']:>10,} EUR/god{RESET}")
    print(f"    {'─' * 50}")
    print(f"    Ukupno ručno:            {RED}{cc['total_manual_cost']:>10,} EUR/god{RESET}")

    # AI savings
    print(f"\n  {BOLD}AI sistem — uštede:{RESET}")
    print(f"    Automatska generacija:   {GREEN}{ai['report_generation']['saving_eur']:>10,} EUR{RESET}  ({ai['report_generation']['time_saved_hours_annual']}h saved)")
    print(f"    Optimizirani review:     {GREEN}{ai['review_optimization']['saving_eur']:>10,} EUR{RESET}  ({ai['review_optimization']['time_saved_hours_annual']}h saved)")
    print(f"    Eliminacija grešaka:     {GREEN}{ai['error_elimination']['saving_eur']:>10,} EUR{RESET}")
    print(f"    SMSI Gold opportunity:   {GREEN}{ai['smsi_improvement_opportunity']['potential_extra_revenue_eur']:>10,} EUR{RESET}")

    # Financial summary
    print(f"\n  {BOLD}Finansijski pregled:{RESET}")
    print(f"    Direktne uštede:         {GREEN}{rs['direct_savings_eur']:>10,} EUR/god{RESET}")
    print(f"    SMSI opportunity:        {GREEN}{rs['smsi_opportunity_eur']:>10,} EUR/god{RESET}")
    print(f"    Ukupan benefit:          {GREEN}{rs['total_annual_benefit_eur']:>10,} EUR/god{RESET}")
    print(f"    Software trošak:         {RED}{rs['software_cost_annual_eur']:>10,} EUR/god{RESET}")
    print(f"    {'─' * 50}")
    print(f"    Neto ušteda:             {BOLD}{GREEN}{rs['net_annual_saving_eur']:>10,} EUR/god{RESET}")
    print(f"    Payback period:          {GREEN}{rs['payback_months']} mjeseci{RESET}")
    print(f"    3-godišnji ROI:          {GREEN}{rs['roi_3yr_pct']:.1f}%{RESET}")

    print(f"\n  {DIM}Saved → {RESULT_DIR}/reporting_roi.json{RESET}")
    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()
