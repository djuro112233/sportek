"""
Sportek d.o.o. — OEE Dashboard — Production Scheduler
Heuristic scheduling: assign orders to lines by OEE+brand affinity,
minimise changeovers, what-if simulation.

Usage:
    python -m modules.05_oee_dashboard.scheduler
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .oee_calculator import OEECalculator

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
PROD_CSV = PROJECT_ROOT / "data" / "production" / "production_log.csv"

SHIFT_HOURS = 8
SHIFTS_PER_DAY = 3


class ProductionScheduler:
    """Heuristic production scheduler using OEE-aware line assignment."""

    def __init__(self) -> None:
        self.calc = OEECalculator()
        self.calc.load_data()
        self.data = self.calc.data

        # Per-line capacity: avg actual_qty per shift
        self._line_capacity = (
            self.data.groupby("line_id")["actual_qty"].mean().to_dict()
        )
        # Per line × brand OEE (affinity)
        self._line_brand_oee = self._compute_line_brand_oee()
        # Lines
        self.lines = sorted(self.data["line_id"].unique())

    def _compute_line_brand_oee(self) -> dict[tuple[str, str], float]:
        """Average OEE by (line, brand) pair."""
        result = {}
        for (lid, brand), grp in self.data.groupby(["line_id", "brand"]):
            total_min = len(grp) * 480
            avail = np.clip(
                (total_min - grp["downtime_minutes"].sum() - grp["changeover_minutes"].sum()) / total_min, 0, 1,
            )
            perf = np.clip(grp["actual_qty"].sum() / grp["planned_qty"].sum(), 0, 1)
            qual = np.clip((grp["actual_qty"].sum() - grp["defect_qty"].sum()) / grp["actual_qty"].sum(), 0, 1)
            result[(lid, brand)] = float(avail * perf * qual)
        return result

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------
    def optimize_schedule(
        self, orders: list[dict], days_ahead: int = 5,
    ) -> list[dict]:
        """Assign orders to lines across *days_ahead* days, 3 shifts each."""
        # Build slot grid: day × line × shift
        slots: list[dict] = []  # available slots
        for day in range(1, days_ahead + 1):
            for lid in self.lines:
                for shift in range(1, SHIFTS_PER_DAY + 1):
                    slots.append({
                        "day": day, "line": lid, "shift": shift,
                        "capacity": int(self._line_capacity.get(lid, 130)),
                        "assigned": None,
                    })

        # Sort orders by deadline (earliest first), then qty descending
        sorted_orders = sorted(
            orders,
            key=lambda o: (o.get("deadline", "9999-12-31"), -o["qty"]),
        )

        schedule: list[dict] = []

        for order in sorted_orders:
            remaining = order["qty"]
            brand = order["brand"]
            model = order["model"]

            # Rank available slots by brand-line affinity (OEE)
            available = [s for s in slots if s["assigned"] is None]
            available.sort(
                key=lambda s: (
                    -self._line_brand_oee.get((s["line"], brand), 0.5),
                    s["day"],
                    s["shift"],
                ),
            )

            for slot in available:
                if remaining <= 0:
                    break
                cap = slot["capacity"]
                produce = min(remaining, cap)
                start_h = (slot["shift"] - 1) * SHIFT_HOURS
                end_h = start_h + SHIFT_HOURS

                schedule.append({
                    "day": slot["day"],
                    "line": slot["line"],
                    "shift": slot["shift"],
                    "brand": brand,
                    "model": model,
                    "qty": produce,
                    "start_hour": start_h,
                    "end_hour": end_h,
                })
                slot["assigned"] = brand
                remaining -= produce

        return schedule

    # ------------------------------------------------------------------
    # Minimize changeovers
    # ------------------------------------------------------------------
    def minimize_changeovers(self, schedule: list[dict]) -> list[dict]:
        """Re-order schedule to group same brand on same line per day."""
        df = pd.DataFrame(schedule)
        if df.empty:
            return schedule

        optimized = []
        for (day, line), grp in df.groupby(["day", "line"]):
            # Sort by brand so same brand shifts are adjacent
            sorted_grp = grp.sort_values("brand")
            # Reassign shift numbers
            for i, (_, row) in enumerate(sorted_grp.iterrows()):
                new_shift = i + 1
                entry = row.to_dict()
                entry["shift"] = new_shift
                entry["start_hour"] = (new_shift - 1) * SHIFT_HOURS
                entry["end_hour"] = new_shift * SHIFT_HOURS
                optimized.append(entry)

        optimized.sort(key=lambda x: (x["day"], x["line"], x["shift"]))
        return optimized

    # ------------------------------------------------------------------
    # What-if simulation
    # ------------------------------------------------------------------
    def what_if(self, scenario: str) -> dict:
        """Run a what-if scenario on current production data."""
        # Current baseline
        current_daily = float(self.data.groupby("date")["actual_qty"].sum().mean())
        current_oee = float(self.data["oee_score"].mean())
        lines = self.lines[:]

        if scenario == "add_shift_3":
            # Currently some lines may have <3 shifts; adding shift 3 everywhere
            shift_counts = self.data.groupby("line_id")["shift"].nunique()
            lines_under_3 = shift_counts[shift_counts < 3].index.tolist()
            extra_per_line = current_daily / len(lines) / 3  # ~1 shift worth
            extra = extra_per_line * len(lines_under_3)
            projected = current_daily + extra
            oee_impact = current_oee * 0.97  # slight OEE drop from fatigue

        elif scenario == "remove_line_L4":
            l4_output = float(
                self.data[self.data["line_id"] == "L4"]
                .groupby("date")["actual_qty"].sum().mean()
            )
            projected = current_daily - l4_output
            oee_impact = current_oee * 1.02  # remaining lines less strained

        elif scenario == "increase_capacity_10pct":
            projected = current_daily * 1.10
            oee_impact = current_oee * 0.98  # slight OEE drop pushing harder

        else:
            raise ValueError(f"Unknown scenario: {scenario}")

        return {
            "scenario": scenario,
            "current_daily_output": round(current_daily, 0),
            "projected_daily_output": round(projected, 0),
            "change_pct": round((projected - current_daily) / current_daily * 100, 1),
            "current_oee": round(current_oee, 4),
            "projected_oee": round(float(oee_impact), 4),
        }


# -----------------------------------------------------------------------
# Demo orders
# -----------------------------------------------------------------------
DEMO_ORDERS = [
    {"brand": "Nike", "model": "Air Max Flyknit Upper", "qty": 2000, "deadline": "2026-03-05"},
    {"brand": "Nike", "model": "Dunk Low Textile Upper", "qty": 1500, "deadline": "2026-03-04"},
    {"brand": "Nike", "model": "Pegasus 3D Knit Collar", "qty": 1200, "deadline": "2026-03-06"},
    {"brand": "Nike", "model": "Vaporfly Engineered Mesh", "qty": 800, "deadline": "2026-03-03"},
    {"brand": "Crocs", "model": "Classic Clog Strap Assembly", "qty": 1800, "deadline": "2026-03-05"},
    {"brand": "Crocs", "model": "LiteRide Insole Unit", "qty": 1000, "deadline": "2026-03-04"},
    {"brand": "Crocs", "model": "Bayaband Slide Upper", "qty": 600, "deadline": "2026-03-06"},
    {"brand": "Decathlon", "model": "Quechua Hiking Upper", "qty": 1400, "deadline": "2026-03-05"},
    {"brand": "Decathlon", "model": "Kalenji Trail Sole Unit", "qty": 900, "deadline": "2026-03-04"},
    {"brand": "Decathlon", "model": "Kiprun Carbon Plate", "qty": 700, "deadline": "2026-03-06"},
]


def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    # OEE
    calc = OEECalculator()
    calc.load_data()

    print(f"\n{BOLD}{CYAN}{'=' * 75}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK — OEE Dashboard + Production Scheduler{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 75}{RESET}")

    current = calc.get_current_oee()
    print(f"\n  {BOLD}Current OEE:{RESET}\n")
    print(f"  {'Linija':<8s} {'Avail':>7s} {'Perf':>7s} {'Qual':>7s} {'OEE':>7s}  {'Trend':>10s}")
    print(f"  {'─' * 8} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 7}  {'─' * 10}")
    for lid in sorted(current):
        m = current[lid]
        oee_c = GREEN if m["oee"] >= 0.75 else YELLOW
        print(f"  {lid:<8s} {m['availability']:>7.1%} {m['performance']:>7.1%} "
              f"{m['quality']:>7.1%} {oee_c}{m['oee']:>7.1%}{RESET}  {m['trend']:>10s}")

    # Scheduling
    sched = ProductionScheduler()
    print(f"\n  {BOLD}Demo Orders (10):{RESET}")
    total_qty = sum(o["qty"] for o in DEMO_ORDERS)
    for o in DEMO_ORDERS:
        print(f"    {o['brand']:<12s} {o['model']:<30s} qty={o['qty']:>5,}  deadline={o['deadline']}")
    print(f"    {'─' * 60}")
    print(f"    {BOLD}Total: {total_qty:,} units{RESET}")

    raw_schedule = sched.optimize_schedule(DEMO_ORDERS, days_ahead=5)
    schedule = sched.minimize_changeovers(raw_schedule)

    print(f"\n  {BOLD}Optimized Schedule (changeovers minimized):{RESET}\n")
    print(f"  {'Day':<5s} {'Line':<6s} {'Shift':<6s} {'Brand':<12s} {'Model':<30s} {'Qty':>6s}  {'Hours':>8s}")
    print(f"  {'─' * 5} {'─' * 6} {'─' * 6} {'─' * 12} {'─' * 30} {'─' * 6}  {'─' * 8}")

    prev_day = None
    for s in schedule[:30]:  # show first 30 slots
        if s["day"] != prev_day:
            if prev_day is not None:
                print()
            prev_day = s["day"]
        print(f"  {s['day']:<5d} {s['line']:<6s} {s['shift']:<6d} {s['brand']:<12s} "
              f"{s['model'][:29]:<30s} {s['qty']:>6,}  {s['start_hour']:>2d}:00-{s['end_hour']:>2d}:00")

    sched_total = sum(s["qty"] for s in schedule)
    print(f"\n  {DIM}Scheduled: {sched_total:,} / {total_qty:,} units "
          f"({sched_total/total_qty*100:.0f}%){RESET}")

    # What-if
    print(f"\n  {BOLD}What-If Scenarios:{RESET}\n")
    for scenario in ("add_shift_3", "remove_line_L4", "increase_capacity_10pct"):
        wf = sched.what_if(scenario)
        color = GREEN if wf["change_pct"] > 0 else YELLOW
        print(f"    {scenario:<25s}  output: {wf['current_daily_output']:>6,.0f} → "
              f"{color}{wf['projected_daily_output']:>6,.0f}{RESET}  "
              f"({wf['change_pct']:>+5.1f}%)  OEE: {wf['projected_oee']:.1%}")

    print(f"\n{'=' * 75}\n")


if __name__ == "__main__":
    main()
