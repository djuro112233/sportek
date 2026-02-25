"""
Sportek d.o.o. — OEE Dashboard — OEE Calculator
Overall Equipment Effectiveness calculation, Six Big Losses, benchmarking.

Usage:
    python -m modules.05_oee_dashboard.oee_calculator
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
PROD_CSV = PROJECT_ROOT / "data" / "production" / "production_log.csv"

SHIFT_MINUTES = 480  # 8-hour shift


class OEECalculator:
    """Calculate OEE metrics from production log data."""

    def __init__(self) -> None:
        self.data: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load_data(self, path: str | Path = PROD_CSV) -> pd.DataFrame:
        self.data = pd.read_csv(path, parse_dates=["date"])
        return self.data

    # ------------------------------------------------------------------
    # OEE for a single line
    # ------------------------------------------------------------------
    def calculate_oee(
        self, line_id: str, period: str = "monthly",
    ) -> pd.DataFrame:
        if self.data is None:
            self.load_data()

        df = self.data[self.data["line_id"] == line_id].copy()
        df = df.set_index("date")

        freq = "MS" if period == "monthly" else "W"
        grouped = df.resample(freq)

        records = []
        for period_start, grp in grouped:
            if grp.empty:
                continue
            total_shifts = len(grp)
            total_shift_min = total_shifts * SHIFT_MINUTES

            avail_min = total_shift_min - grp["downtime_minutes"].sum() - grp["changeover_minutes"].sum()
            availability = np.clip(avail_min / total_shift_min, 0, 1)

            planned = grp["planned_qty"].sum()
            actual = grp["actual_qty"].sum()
            performance = np.clip(actual / planned, 0, 1) if planned > 0 else 0

            defects = grp["defect_qty"].sum()
            quality = np.clip((actual - defects) / actual, 0, 1) if actual > 0 else 0

            oee = float(availability * performance * quality)

            records.append({
                "period": str(period_start.date()),
                "availability": round(float(availability), 4),
                "performance": round(float(performance), 4),
                "quality": round(float(quality), 4),
                "oee": round(oee, 4),
            })

        return pd.DataFrame(records)

    # ------------------------------------------------------------------
    # All lines
    # ------------------------------------------------------------------
    def calculate_all_lines(
        self, period: str = "monthly",
    ) -> dict[str, pd.DataFrame]:
        if self.data is None:
            self.load_data()
        lines = sorted(self.data["line_id"].unique())
        return {lid: self.calculate_oee(lid, period) for lid in lines}

    # ------------------------------------------------------------------
    # Current OEE snapshot
    # ------------------------------------------------------------------
    def get_current_oee(self) -> dict[str, dict]:
        all_lines = self.calculate_all_lines(period="monthly")
        result = {}
        for lid, df in all_lines.items():
            if df.empty:
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else last

            trend_val = last["oee"] - prev["oee"]
            if trend_val > 0.01:
                trend = "improving"
            elif trend_val < -0.01:
                trend = "declining"
            else:
                trend = "stable"

            result[lid] = {
                "availability": last["availability"],
                "performance": last["performance"],
                "quality": last["quality"],
                "oee": last["oee"],
                "trend": trend,
            }
        return result

    # ------------------------------------------------------------------
    # Six Big Losses
    # ------------------------------------------------------------------
    def identify_losses(self, line_id: str) -> dict:
        if self.data is None:
            self.load_data()

        df = self.data[self.data["line_id"] == line_id]
        total_shifts = len(df)
        total_shift_min = total_shifts * SHIFT_MINUTES

        # Availability losses
        breakdown_min = int(df["downtime_minutes"].sum())
        changeover_min = int(df["changeover_minutes"].sum())

        # Performance losses
        available_min = total_shift_min - breakdown_min - changeover_min
        planned_total = int(df["planned_qty"].sum())
        actual_total = int(df["actual_qty"].sum())
        # Speed loss in equivalent minutes
        if planned_total > 0:
            ideal_cycle_time = available_min / planned_total
            speed_loss_min = int((planned_total - actual_total) * ideal_cycle_time * 0.6)
            minor_stops_min = int((planned_total - actual_total) * ideal_cycle_time * 0.4)
        else:
            speed_loss_min = 0
            minor_stops_min = 0

        # Quality losses
        defects_total = int(df["defect_qty"].sum())
        startup_rejects = int(defects_total * 0.15)  # estimate 15% are startup
        process_defects = defects_total - startup_rejects

        total_loss = breakdown_min + changeover_min + speed_loss_min + minor_stops_min

        return {
            "availability_losses": {
                "breakdowns_min": breakdown_min,
                "setup_changeover_min": changeover_min,
            },
            "performance_losses": {
                "minor_stops_min": minor_stops_min,
                "speed_loss_min": speed_loss_min,
            },
            "quality_losses": {
                "defects_units": process_defects,
                "startup_rejects_units": startup_rejects,
            },
            "total_loss_minutes": total_loss,
            "theoretical_output": planned_total,
            "actual_output": actual_total,
        }

    # ------------------------------------------------------------------
    # Benchmark
    # ------------------------------------------------------------------
    def benchmark(self) -> list[dict]:
        if self.data is None:
            self.load_data()

        lines = sorted(self.data["line_id"].unique())
        records = []
        for lid in lines:
            df = self.data[self.data["line_id"] == lid]
            total_shifts = len(df)
            total_min = total_shifts * SHIFT_MINUTES

            avail = np.clip(
                (total_min - df["downtime_minutes"].sum() - df["changeover_minutes"].sum()) / total_min, 0, 1
            )
            perf = np.clip(df["actual_qty"].sum() / df["planned_qty"].sum(), 0, 1)
            qual = np.clip(
                (df["actual_qty"].sum() - df["defect_qty"].sum()) / df["actual_qty"].sum(), 0, 1
            )
            oee = float(avail * perf * qual)

            metrics = {"availability": float(avail), "performance": float(perf), "quality": float(qual)}
            best_m = max(metrics, key=metrics.get)
            worst_m = min(metrics, key=metrics.get)

            records.append({
                "line_id": lid,
                "avg_oee": round(oee, 4),
                "availability": round(float(avail), 4),
                "performance": round(float(perf), 4),
                "quality": round(float(qual), 4),
                "best_metric": best_m,
                "worst_metric": worst_m,
            })

        records.sort(key=lambda x: x["avg_oee"], reverse=True)
        for i, r in enumerate(records, 1):
            r["rank"] = i
        return records


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------
def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    calc = OEECalculator()
    calc.load_data()

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK d.o.o. — OEE Dashboard{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")

    # Current OEE
    current = calc.get_current_oee()
    print(f"\n  {BOLD}Current OEE (zadnji mjesec):{RESET}\n")
    print(f"  {'Linija':<8s} {'Avail':>7s} {'Perf':>7s} {'Qual':>7s} {'OEE':>7s}  {'Trend':>10s}")
    print(f"  {'─' * 8} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 7}  {'─' * 10}")
    for lid in sorted(current):
        m = current[lid]
        oee_val = m["oee"]
        color = GREEN if oee_val >= 0.75 else YELLOW if oee_val >= 0.65 else RED
        trend_color = GREEN if m["trend"] == "improving" else RED if m["trend"] == "declining" else DIM
        print(f"  {lid:<8s} {m['availability']:>7.1%} {m['performance']:>7.1%} "
              f"{m['quality']:>7.1%} {color}{oee_val:>7.1%}{RESET}  "
              f"{trend_color}{m['trend']:>10s}{RESET}")

    # Benchmark
    bench = calc.benchmark()
    print(f"\n  {BOLD}Benchmark Ranking:{RESET}\n")
    print(f"  {'#':<4s} {'Linija':<8s} {'OEE':>7s} {'Best':>14s} {'Worst':>14s}")
    print(f"  {'─' * 4} {'─' * 8} {'─' * 7} {'─' * 14} {'─' * 14}")
    for r in bench:
        color = GREEN if r["rank"] <= 3 else RESET
        print(f"  {color}{r['rank']:<4d} {r['line_id']:<8s} {r['avg_oee']:>7.1%} "
              f"{r['best_metric']:>14s} {r['worst_metric']:>14s}{RESET}")

    # Six Big Losses for worst line
    worst_line = bench[-1]["line_id"]
    losses = calc.identify_losses(worst_line)
    print(f"\n  {BOLD}Six Big Losses — {worst_line} (najlošija linija):{RESET}")
    al = losses["availability_losses"]
    pl = losses["performance_losses"]
    ql = losses["quality_losses"]
    print(f"    Availability: breakdowns={al['breakdowns_min']:,} min, changeover={al['setup_changeover_min']:,} min")
    print(f"    Performance:  minor_stops={pl['minor_stops_min']:,} min, speed_loss={pl['speed_loss_min']:,} min")
    print(f"    Quality:      defects={ql['defects_units']:,} units, startup_rejects={ql['startup_rejects_units']:,} units")
    print(f"    Total loss: {losses['total_loss_minutes']:,} min | "
          f"Theoretical: {losses['theoretical_output']:,} | Actual: {losses['actual_output']:,}")

    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()
