"""
Sportek d.o.o. — OEE Dashboard — ROI Analysis
Calculate ROI from OEE improvements based on real production_log.csv data.

Usage:
    python -m modules.05_oee_dashboard.roi
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .oee_calculator import OEECalculator

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
PROD_CSV = PROJECT_ROOT / "data" / "production" / "production_log.csv"
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# Constants
TARGET_OEE = 0.85  # World-class benchmark
REVENUE_PER_PAIR = 12  # EUR per pair
SOFTWARE_COST_ANNUAL = 24_000  # EUR/year
OEE_IMPROVEMENT_PP = 5  # Percentage points
CHANGEOVER_REDUCTION_PCT = 0.20  # 20% reduction
DOWNTIME_REDUCTION_PCT = 0.30  # 30% predictive maintenance
SCHEDULING_IMPROVEMENT_PCT = 0.05  # 5% throughput gain


def calculate_roi() -> dict:
    """Calculate ROI from OEE dashboard improvements."""
    calc = OEECalculator()
    calc.load_data()
    data = calc.data
    bench = calc.benchmark()

    # ── Current State ─────────────────────────────────────────────────
    current_avg_oee = np.mean([b["avg_oee"] for b in bench])
    oee_gap = TARGET_OEE - current_avg_oee

    total_shifts = len(data)
    total_planned = int(data["planned_qty"].sum())
    total_actual = int(data["actual_qty"].sum())
    total_defects = int(data["defect_qty"].sum())
    total_downtime = int(data["downtime_minutes"].sum())
    total_changeover = int(data["changeover_minutes"].sum())

    # Data spans
    date_range = (data["date"].max() - data["date"].min()).days
    months_in_data = max(date_range / 30.44, 1)

    # Annualise
    annual_planned = int(total_planned / months_in_data * 12)
    annual_actual = int(total_actual / months_in_data * 12)
    annual_defects = int(total_defects / months_in_data * 12)
    annual_downtime = int(total_downtime / months_in_data * 12)
    annual_changeover = int(total_changeover / months_in_data * 12)

    lines = sorted(data["line_id"].unique())
    n_lines = len(lines)

    # ── 1. OEE Improvement Value ──────────────────────────────────────
    # Extra pairs from +5pp OEE improvement
    improvement_fraction = OEE_IMPROVEMENT_PP / 100
    extra_pairs_annual = int(annual_planned * improvement_fraction)
    oee_improvement_eur = extra_pairs_annual * REVENUE_PER_PAIR

    # ── 2. Changeover Reduction ───────────────────────────────────────
    # 20% less changeover → more productive minutes
    changeover_saved_min = int(annual_changeover * CHANGEOVER_REDUCTION_PCT)
    # Convert saved minutes to pairs (using avg throughput per minute)
    avg_throughput_per_min = annual_actual / (total_shifts / months_in_data * 12 * 480)
    changeover_extra_pairs = int(changeover_saved_min * avg_throughput_per_min)
    changeover_saving_eur = changeover_extra_pairs * REVENUE_PER_PAIR

    # ── 3. Predictive Maintenance ─────────────────────────────────────
    # 30% downtime reduction
    downtime_saved_min = int(annual_downtime * DOWNTIME_REDUCTION_PCT)
    maintenance_extra_pairs = int(downtime_saved_min * avg_throughput_per_min)
    maintenance_saving_eur = maintenance_extra_pairs * REVENUE_PER_PAIR

    # ── 4. Scheduling Optimization ────────────────────────────────────
    # 5% throughput improvement from better scheduling
    scheduling_extra_pairs = int(annual_actual * SCHEDULING_IMPROVEMENT_PCT)
    scheduling_saving_eur = scheduling_extra_pairs * REVENUE_PER_PAIR

    # ── Total ─────────────────────────────────────────────────────────
    total_annual_saving = (
        oee_improvement_eur
        + changeover_saving_eur
        + maintenance_saving_eur
        + scheduling_saving_eur
    )
    net_annual_saving = total_annual_saving - SOFTWARE_COST_ANNUAL
    payback_months = round(SOFTWARE_COST_ANNUAL / (total_annual_saving / 12), 1) if total_annual_saving > 0 else 0
    roi_3yr = round((net_annual_saving * 3) / SOFTWARE_COST_ANNUAL * 100, 1)

    # ── Per-line breakdown ────────────────────────────────────────────
    line_breakdown = []
    for b in bench:
        lid = b["line_id"]
        line_data = data[data["line_id"] == lid]
        line_planned = int(line_data["planned_qty"].sum() / months_in_data * 12)
        line_extra = int(line_planned * improvement_fraction)
        line_value = line_extra * REVENUE_PER_PAIR
        line_breakdown.append({
            "line_id": lid,
            "current_oee": b["avg_oee"],
            "target_oee": TARGET_OEE,
            "gap_pp": round((TARGET_OEE - b["avg_oee"]) * 100, 1),
            "annual_extra_pairs": line_extra,
            "annual_value_eur": line_value,
        })

    result = {
        "current_state": {
            "avg_oee": round(current_avg_oee, 4),
            "target_oee": TARGET_OEE,
            "oee_gap_pp": round(oee_gap * 100, 1),
            "lines": n_lines,
            "total_shifts": total_shifts,
            "annual_planned_qty": annual_planned,
            "annual_actual_qty": annual_actual,
            "annual_defects": annual_defects,
            "annual_downtime_min": annual_downtime,
            "annual_changeover_min": annual_changeover,
        },
        "savings": {
            "oee_improvement": {
                "description": f"+{OEE_IMPROVEMENT_PP}pp OEE improvement",
                "extra_pairs_annual": extra_pairs_annual,
                "value_eur": oee_improvement_eur,
            },
            "changeover_reduction": {
                "description": f"{int(CHANGEOVER_REDUCTION_PCT*100)}% changeover reduction",
                "saved_minutes_annual": changeover_saved_min,
                "extra_pairs_annual": changeover_extra_pairs,
                "value_eur": changeover_saving_eur,
            },
            "predictive_maintenance": {
                "description": f"{int(DOWNTIME_REDUCTION_PCT*100)}% downtime reduction",
                "saved_minutes_annual": downtime_saved_min,
                "extra_pairs_annual": maintenance_extra_pairs,
                "value_eur": maintenance_saving_eur,
            },
            "scheduling_optimization": {
                "description": f"{int(SCHEDULING_IMPROVEMENT_PCT*100)}% throughput gain",
                "extra_pairs_annual": scheduling_extra_pairs,
                "value_eur": scheduling_saving_eur,
            },
        },
        "financial_summary": {
            "total_annual_saving_eur": total_annual_saving,
            "software_cost_annual_eur": SOFTWARE_COST_ANNUAL,
            "net_annual_saving_eur": net_annual_saving,
            "payback_months": payback_months,
            "roi_3yr_pct": roi_3yr,
        },
        "line_breakdown": line_breakdown,
    }

    # Save
    with open(RESULT_DIR / "oee_roi.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK — OEE Dashboard — ROI Analysis{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}\n")

    result = calculate_roi()
    cs = result["current_state"]
    sav = result["savings"]
    fs = result["financial_summary"]

    # Current state
    print(f"  {BOLD}Current State:{RESET}")
    print(f"    Average OEE:          {YELLOW}{cs['avg_oee']:.1%}{RESET}")
    print(f"    Target OEE:           {GREEN}{cs['target_oee']:.0%}{RESET}")
    print(f"    Gap:                  {RED}{cs['oee_gap_pp']:.1f} pp{RESET}")
    print(f"    Lines:                {cs['lines']}")
    print(f"    Annual planned qty:   {cs['annual_planned_qty']:,}")
    print(f"    Annual actual qty:    {cs['annual_actual_qty']:,}")
    print(f"    Annual downtime:      {cs['annual_downtime_min']:,} min")
    print(f"    Annual changeover:    {cs['annual_changeover_min']:,} min")

    # Savings
    print(f"\n  {BOLD}Annual Savings:{RESET}")
    for key, s in sav.items():
        print(f"    {s['description']:<35s}  {GREEN}{s['value_eur']:>12,} EUR{RESET}")

    # Financial summary
    print(f"\n  {BOLD}Financial Summary:{RESET}")
    print(f"    Total annual saving:  {GREEN}{fs['total_annual_saving_eur']:>12,} EUR{RESET}")
    print(f"    Software cost:        {RED}{fs['software_cost_annual_eur']:>12,} EUR{RESET}")
    print(f"    Net annual saving:    {BOLD}{GREEN}{fs['net_annual_saving_eur']:>12,} EUR{RESET}")
    print(f"    Payback period:       {GREEN}{fs['payback_months']} months{RESET}")
    print(f"    3-year ROI:           {GREEN}{fs['roi_3yr_pct']:.1f}%{RESET}")

    # Per-line breakdown
    print(f"\n  {BOLD}Per-Line Breakdown:{RESET}")
    print(f"    {'Line':<8s} {'Current':>8s} {'Target':>8s} {'Gap':>6s} {'Extra Pairs':>12s} {'Value EUR':>12s}")
    print(f"    {'─'*8} {'─'*8} {'─'*8} {'─'*6} {'─'*12} {'─'*12}")
    for lb in result["line_breakdown"]:
        color = GREEN if lb["gap_pp"] < 15 else YELLOW
        print(f"    {lb['line_id']:<8s} {lb['current_oee']:>8.1%} {lb['target_oee']:>8.0%} "
              f"{color}{lb['gap_pp']:>5.1f}pp{RESET} {lb['annual_extra_pairs']:>12,} {lb['annual_value_eur']:>12,}")

    print(f"\n  {DIM}Saved → {RESULT_DIR}/oee_roi.json{RESET}")
    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()
