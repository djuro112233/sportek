"""
Sportek d.o.o. — Knowledge Guardian — ROI Calculation
Estimates return on investment for AI-powered internal knowledge management.

Usage:
    python -m modules.03_knowledge_guardian.roi
"""

from __future__ import annotations

import json
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants — current manual operation
# ---------------------------------------------------------------------------
# Middle management answering worker questions
MGMT_PEOPLE = 5
MGMT_HOURS_PER_DAY = 1.5
MGMT_RATE_EUR_H = 15

# QC manager clarifying procedures
QC_PEOPLE = 1
QC_HOURS_PER_DAY = 1.0
QC_RATE_EUR_H = 18

# Common working-day constants
WORK_DAYS_PER_MONTH = 22
MONTHS_PER_YEAR = 12

# Errors from unknown procedures (rework, scrap, claims)
PROCEDURE_ERROR_COST_EUR_YEAR = 15_000

# Onboarding
NEW_HIRES_PER_YEAR = 10
ONBOARDING_DAYS = 10
ONBOARDING_HOURS_PER_DAY = 8
ONBOARDING_RATE_EUR_H = 12

# ---------------------------------------------------------------------------
# Constants — AI system
# ---------------------------------------------------------------------------
AUTO_ANSWER_PCT = 80            # % of questions answered automatically
RESPONSE_TIME_SEC = 3           # average response time
MGMT_LOAD_REDUCTION_PCT = 60   # reduction in management answering load
ERROR_REDUCTION_PCT = 40        # reduction in procedure-error incidents
ONBOARDING_DAYS_AFTER = 4      # reduced from 10 to 4 days
SOFTWARE_COST_EUR_YEAR = 12_000


def calculate_roi() -> dict:
    """Build full Knowledge Guardian ROI model."""

    # ── Current annual costs ───────────────────────────────────────────
    mgmt_annual = (
        MGMT_PEOPLE * MGMT_HOURS_PER_DAY
        * WORK_DAYS_PER_MONTH * MONTHS_PER_YEAR * MGMT_RATE_EUR_H
    )
    qc_annual = (
        QC_PEOPLE * QC_HOURS_PER_DAY
        * WORK_DAYS_PER_MONTH * MONTHS_PER_YEAR * QC_RATE_EUR_H
    )
    error_annual = PROCEDURE_ERROR_COST_EUR_YEAR
    onboarding_annual = (
        NEW_HIRES_PER_YEAR * ONBOARDING_DAYS
        * ONBOARDING_HOURS_PER_DAY * ONBOARDING_RATE_EUR_H
    )
    total_current = mgmt_annual + qc_annual + error_annual + onboarding_annual

    # ── AI system savings ──────────────────────────────────────────────
    mgmt_saving = round(mgmt_annual * MGMT_LOAD_REDUCTION_PCT / 100, 2)
    qc_saving = round(qc_annual * MGMT_LOAD_REDUCTION_PCT / 100, 2)
    error_saving = round(error_annual * ERROR_REDUCTION_PCT / 100, 2)
    onboarding_saving = round(
        onboarding_annual * (1 - ONBOARDING_DAYS_AFTER / ONBOARDING_DAYS), 2
    )

    gross_annual = mgmt_saving + qc_saving + error_saving + onboarding_saving
    net_annual = gross_annual - SOFTWARE_COST_EUR_YEAR

    # Payback
    if net_annual > 0:
        payback_months = round(SOFTWARE_COST_EUR_YEAR / gross_annual * 12, 1)
    else:
        payback_months = float("inf")

    # 3-year projection
    total_3y = net_annual * 3
    investment_3y = SOFTWARE_COST_EUR_YEAR * 3
    roi_3y_pct = round(total_3y / investment_3y * 100, 1) if investment_3y else 0

    result = {
        "current_costs_eur": {
            "management_answering_questions": {
                "people": MGMT_PEOPLE,
                "hours_per_day": MGMT_HOURS_PER_DAY,
                "rate_eur_h": MGMT_RATE_EUR_H,
                "annual_cost": round(mgmt_annual, 2),
            },
            "qc_manager_clarifications": {
                "people": QC_PEOPLE,
                "hours_per_day": QC_HOURS_PER_DAY,
                "rate_eur_h": QC_RATE_EUR_H,
                "annual_cost": round(qc_annual, 2),
            },
            "procedure_errors_rework_scrap": round(error_annual, 2),
            "onboarding_new_workers": {
                "new_hires_per_year": NEW_HIRES_PER_YEAR,
                "days_per_hire": ONBOARDING_DAYS,
                "hours_per_day": ONBOARDING_HOURS_PER_DAY,
                "rate_eur_h": ONBOARDING_RATE_EUR_H,
                "annual_cost": round(onboarding_annual, 2),
            },
            "annual_total": round(total_current, 2),
        },
        "ai_system": {
            "auto_answer_pct": AUTO_ANSWER_PCT,
            "avg_response_time_sec": RESPONSE_TIME_SEC,
            "management_load_reduction_pct": MGMT_LOAD_REDUCTION_PCT,
            "error_reduction_pct": ERROR_REDUCTION_PCT,
            "onboarding_days_before": ONBOARDING_DAYS,
            "onboarding_days_after": ONBOARDING_DAYS_AFTER,
            "software_cost_annual": SOFTWARE_COST_EUR_YEAR,
        },
        "annual_savings_eur": {
            "management_time_saved": round(mgmt_saving, 2),
            "qc_manager_time_saved": round(qc_saving, 2),
            "error_reduction": round(error_saving, 2),
            "onboarding_acceleration": round(onboarding_saving, 2),
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
    DIM = "\033[2m"
    RESET = "\033[0m"

    print()
    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK d.o.o. — Knowledge Guardian — ROI Calculation{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")

    roi = calculate_roi()

    # Save JSON
    out_path = RESULT_DIR / "knowledge_roi.json"
    with open(out_path, "w") as f:
        json.dump(roi, f, indent=2, ensure_ascii=False)
    print(f"\n  JSON saved → {out_path}\n")

    cur = roi["current_costs_eur"]
    ai = roi["ai_system"]
    sav = roi["annual_savings_eur"]
    sm = roi["roi_summary"]

    print("  TRENUTNI TROŠKOVI (EUR/god)")
    m = cur["management_answering_questions"]
    print(f"    Menadžment ({m['people']} osoba × {m['hours_per_day']}h/dan × {m['rate_eur_h']} EUR/h):"
          f"  = {m['annual_cost']:>10,.0f}")
    q = cur["qc_manager_clarifications"]
    print(f"    QC menadžer ({q['people']} × {q['hours_per_day']}h/dan × {q['rate_eur_h']} EUR/h):"
          f"        = {q['annual_cost']:>10,.0f}")
    print(f"    Greške (nepoznavanje procedura):"
          f"                  = {cur['procedure_errors_rework_scrap']:>10,.0f}")
    o = cur["onboarding_new_workers"]
    print(f"    Onboarding ({o['new_hires_per_year']} novih × {o['days_per_hire']} dana × {o['hours_per_day']}h):"
          f"        = {o['annual_cost']:>10,.0f}")
    print(f"    {'─' * 50}")
    print(f"    UKUPNO GODIŠNJE:                                  = {cur['annual_total']:>10,.0f}")

    print(f"\n  AI SISTEM")
    print(f"    Automatski odgovoreno:           {ai['auto_answer_pct']}%")
    print(f"    Prosječno vrijeme odgovora:      <{ai['avg_response_time_sec']} sekunde")
    print(f"    Smanjenje opterećenja mgmt:      {ai['management_load_reduction_pct']}%")
    print(f"    Smanjenje grešaka:               {ai['error_reduction_pct']}%")
    print(f"    Onboarding:                      {ai['onboarding_days_before']} → {ai['onboarding_days_after']} dana")
    print(f"    Software trošak:                 = {ai['software_cost_annual']:>10,}/god")

    print(f"\n  GODIŠNJE UŠTEDE (EUR)")
    print(f"    Menadžment vrijeme:          + {sav['management_time_saved']:>10,.0f}")
    print(f"    QC menadžer vrijeme:         + {sav['qc_manager_time_saved']:>10,.0f}")
    print(f"    Smanjenje grešaka:           + {sav['error_reduction']:>10,.0f}")
    print(f"    Ubrzanje onboardinga:        + {sav['onboarding_acceleration']:>10,.0f}")
    print(f"    {'─' * 50}")
    print(f"    Bruto godišnja ušteda:       = {sav['gross_annual_saving']:>10,.0f}")
    print(f"    Software trošak:             - {ai['software_cost_annual']:>10,}")
    print(f"    {'─' * 50}")
    print(f"    {BOLD}NETO GODIŠNJA UŠTEDA:        = {GREEN}{sav['net_annual_saving']:>10,.0f} EUR{RESET}")

    print(f"\n  ROI SUMMARY")
    print(f"    Payback period:              {YELLOW}{sm['payback_period_months']} mjeseci{RESET}")
    print(f"    3-year ROI:                  {GREEN}{sm['roi_3_year_pct']}%{RESET}")
    print(f"    3-year total saving:         {GREEN}{sm['total_saving_3_years_eur']:,.0f} EUR{RESET}")

    print(f"\n{'=' * 65}\n")


if __name__ == "__main__":
    main()
