"""
Sportek d.o.o. — Brand Reporting — KPI Tracker
20 KPIs with thresholds, traffic-light status, trend detection.

Usage:
    python -m modules.06_brand_reporting.kpi_tracker
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
PROD_CSV = PROJECT_ROOT / "data" / "production" / "production_log.csv"
DEFECT_CSV = PROJECT_ROOT / "data" / "quality" / "defect_log.csv"
INV_CSV = PROJECT_ROOT / "data" / "supply_chain" / "inventory.csv"
PO_CSV = PROJECT_ROOT / "data" / "supply_chain" / "purchase_orders.csv"
DPP_CSV = PROJECT_ROOT / "data" / "compliance" / "products_dpp.csv"
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ── KPI definitions ───────────────────────────────────────────────────────
# Each KPI: (name, target, warning_threshold, direction)
# direction: "lower_is_better" → green if value < target
#            "higher_is_better" → green if value > target
#            "zero_is_best" → green if value == 0

KPI_DEFS = [
    # id, name, target, warning, critical, direction
    ("overall_defect_rate", "Overall Defect Rate", 0.03, 0.05, 0.05, "lower_is_better"),
    ("nike_defect_rate", "Nike Defect Rate", 0.025, 0.035, 0.05, "lower_is_better"),
    ("crocs_defect_rate", "Crocs Defect Rate", 0.035, 0.045, 0.06, "lower_is_better"),
    ("decathlon_defect_rate", "Decathlon Defect Rate", 0.04, 0.05, 0.07, "lower_is_better"),
    ("on_time_delivery", "On-Time Delivery", 95.0, 90.0, 85.0, "higher_is_better"),
    ("oee_average", "OEE Average", 80.0, 70.0, 60.0, "higher_is_better"),
    ("customer_return_rate", "Customer Return Rate", 0.01, 0.02, 0.03, "lower_is_better"),
    ("rework_rate", "Rework Rate", 0.05, 0.08, 0.10, "lower_is_better"),
    ("scrap_rate", "Scrap Rate", 0.02, 0.03, 0.05, "lower_is_better"),
    ("first_pass_yield", "First Pass Yield", 95.0, 92.0, 90.0, "higher_is_better"),
    ("changeover_time_avg", "Changeover Time Avg (min)", 30.0, 40.0, 50.0, "lower_is_better"),
    ("downtime_pct", "Downtime %", 10.0, 15.0, 20.0, "lower_is_better"),
    ("inventory_turnover", "Inventory Turnover", 8.0, 6.0, 4.0, "higher_is_better"),
    ("stockout_incidents", "Stockout Incidents", 0, 3, 10, "lower_is_better"),
    ("supplier_quality_score", "Supplier Quality Score", 4.0, 3.5, 3.0, "higher_is_better"),
    ("training_hours_per_emp", "Training Hours per Employee", 20.0, 15.0, 10.0, "higher_is_better"),
    ("safety_incidents", "Safety Incidents", 0, 1, 3, "lower_is_better"),
    ("energy_per_unit_kwh", "Energy per Unit (kWh)", 2.5, 3.0, 4.0, "lower_is_better"),
    ("waste_per_unit_kg", "Waste per Unit (kg)", 0.3, 0.4, 0.5, "lower_is_better"),
    ("smsi_score", "SMSI Score", 80.0, 70.0, 60.0, "higher_is_better"),
]


class KPITracker:
    """Track 20 KPIs with traffic-light status and trend detection."""

    def __init__(self) -> None:
        self.prod = pd.read_csv(PROD_CSV, parse_dates=["date"])
        self.defects = pd.read_csv(DEFECT_CSV, parse_dates=["date"])
        self.inv = pd.read_csv(INV_CSV)
        self.po = pd.read_csv(PO_CSV, parse_dates=["date", "expected_delivery", "actual_delivery"])
        self.dpp = pd.read_csv(DPP_CSV, parse_dates=["production_date"])

    def _compute_values(self) -> dict[str, float]:
        """Compute current value for each KPI from data."""
        prod = self.prod
        defects = self.defects
        inv = self.inv
        po = self.po
        dpp = self.dpp

        total_actual = prod["actual_qty"].sum()
        total_defect_qty = prod["defect_qty"].sum()
        total_planned = prod["planned_qty"].sum()
        total_shifts = len(prod)
        shift_minutes = 480

        # Brand-specific defect rates
        def brand_defect_rate(brand: str) -> float:
            bp = prod[prod["brand"] == brand]
            if bp["actual_qty"].sum() == 0:
                return 0
            return bp["defect_qty"].sum() / bp["actual_qty"].sum()

        # Defect log analysis
        total_defect_records = len(defects)
        rework_count = len(defects[defects["action"] == "rework"])
        scrap_count = len(defects[defects["action"] == "scrap"])
        customer_returns = len(defects[defects["detection_point"] == "customer_return"])

        # OEE
        oee_avg = float(prod["oee_score"].mean()) * 100

        # Delivery
        on_time = len(po[po["delay_days"] <= 0])
        otd_pct = on_time / len(po) * 100 if len(po) > 0 else 95.0

        # Changeover & downtime
        avg_changeover = float(prod["changeover_minutes"].mean())
        total_downtime = prod["downtime_minutes"].sum()
        total_available = total_shifts * shift_minutes
        downtime_pct = total_downtime / total_available * 100

        # First pass yield
        fpy = (1 - total_defect_qty / total_actual) * 100 if total_actual > 0 else 95.0

        # Inventory turnover
        total_consumption_annual = inv["consumption_rate_daily"].sum() * 365
        avg_stock_value = (inv["current_stock"] * inv["unit_price_eur"]).sum()
        annual_consumption_value = total_consumption_annual * inv["unit_price_eur"].mean()
        turnover = annual_consumption_value / avg_stock_value if avg_stock_value > 0 else 0

        # Stockout incidents
        stockouts = len(inv[inv["current_stock"] <= 0])

        # Supplier quality score
        supplier_quality = float(po["quality_score"].mean())

        # Training hours estimate (from operator data)
        avg_operators = prod["operator_count"].mean()
        training_hours_per_emp = avg_operators * 4  # 4h/operator/quarter proxy

        # Safety incidents (from critical defects as proxy)
        critical_defects = len(defects[defects["severity"] == "critical"])
        safety_incidents = max(0, critical_defects // 50)

        # Energy & waste from DPP
        avg_carbon = float(dpp["carbon_footprint_kg"].mean())
        energy_per_unit = round(avg_carbon * 0.35, 2)  # proxy: carbon → kWh
        avg_weight_kg = dpp["weight_grams"].mean() / 1000
        waste_per_unit = round(float(total_defect_qty / total_actual * avg_weight_kg), 4) if total_actual > 0 else 0

        # SMSI score — use Nike scorecard
        from .templates import NikeScorecard
        nike_report = NikeScorecard().generate("2025-Q4")
        smsi = nike_report["smsi_score"]

        return {
            "overall_defect_rate": round(total_defect_qty / total_actual, 4) if total_actual > 0 else 0,
            "nike_defect_rate": round(brand_defect_rate("Nike"), 4),
            "crocs_defect_rate": round(brand_defect_rate("Crocs"), 4),
            "decathlon_defect_rate": round(brand_defect_rate("Decathlon"), 4),
            "on_time_delivery": round(otd_pct, 1),
            "oee_average": round(oee_avg, 1),
            "customer_return_rate": round(customer_returns / total_actual, 4) if total_actual > 0 else 0,
            "rework_rate": round(rework_count / total_defect_records, 4) if total_defect_records > 0 else 0,
            "scrap_rate": round(scrap_count / total_defect_records, 4) if total_defect_records > 0 else 0,
            "first_pass_yield": round(fpy, 1),
            "changeover_time_avg": round(avg_changeover, 1),
            "downtime_pct": round(downtime_pct, 1),
            "inventory_turnover": round(turnover, 1),
            "stockout_incidents": stockouts,
            "supplier_quality_score": round(supplier_quality, 2),
            "training_hours_per_emp": round(training_hours_per_emp, 1),
            "safety_incidents": safety_incidents,
            "energy_per_unit_kwh": energy_per_unit,
            "waste_per_unit_kg": round(waste_per_unit, 4),
            "smsi_score": smsi,
        }

    def _compute_trend(self, kpi_id: str) -> str:
        """Compute trend by comparing first and second half of data."""
        prod = self.prod
        mid_date = prod["date"].min() + (prod["date"].max() - prod["date"].min()) / 2
        first_half = prod[prod["date"] <= mid_date]
        second_half = prod[prod["date"] > mid_date]

        if kpi_id == "oee_average":
            v1 = first_half["oee_score"].mean() * 100
            v2 = second_half["oee_score"].mean() * 100
        elif kpi_id == "overall_defect_rate":
            v1 = first_half["defect_qty"].sum() / first_half["actual_qty"].sum() if first_half["actual_qty"].sum() > 0 else 0
            v2 = second_half["defect_qty"].sum() / second_half["actual_qty"].sum() if second_half["actual_qty"].sum() > 0 else 0
        elif kpi_id == "downtime_pct":
            v1 = first_half["downtime_minutes"].sum() / (len(first_half) * 480) * 100
            v2 = second_half["downtime_minutes"].sum() / (len(second_half) * 480) * 100
        elif kpi_id == "changeover_time_avg":
            v1 = first_half["changeover_minutes"].mean()
            v2 = second_half["changeover_minutes"].mean()
        elif kpi_id == "first_pass_yield":
            v1 = (1 - first_half["defect_qty"].sum() / first_half["actual_qty"].sum()) * 100 if first_half["actual_qty"].sum() > 0 else 95
            v2 = (1 - second_half["defect_qty"].sum() / second_half["actual_qty"].sum()) * 100 if second_half["actual_qty"].sum() > 0 else 95
        else:
            return "stable"

        diff = v2 - v1
        if abs(diff) < 0.5:
            return "stable"
        return "up" if diff > 0 else "down"

    def _evaluate_status(self, value: float, target, warning, critical, direction: str) -> str:
        """Return green/yellow/red based on thresholds."""
        if direction == "lower_is_better":
            if value <= target:
                return "green"
            elif value <= warning:
                return "yellow"
            else:
                return "red"
        elif direction == "higher_is_better":
            if value >= target:
                return "green"
            elif value >= warning:
                return "yellow"
            else:
                return "red"
        else:  # zero_is_best
            if value == 0:
                return "green"
            elif value <= warning:
                return "yellow"
            else:
                return "red"

    def calculate_all(self) -> dict:
        """Calculate all 20 KPIs with status and trend."""
        values = self._compute_values()
        result = {}

        for kpi_id, name, target, warning, critical, direction in KPI_DEFS:
            val = values.get(kpi_id, 0)
            status = self._evaluate_status(val, target, warning, critical, direction)
            trend = self._compute_trend(kpi_id)

            result[kpi_id] = {
                "name": name,
                "value": val,
                "target": target,
                "status": status,
                "trend": trend,
            }

        # Save
        with open(RESULT_DIR / "kpi_status.json", "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return result

    def get_alerts(self) -> list[dict]:
        """Return KPIs that are yellow or red."""
        all_kpis = self.calculate_all()
        alerts = []
        for kpi_id, info in all_kpis.items():
            if info["status"] in ("yellow", "red"):
                alerts.append({
                    "kpi_id": kpi_id,
                    "name": info["name"],
                    "value": info["value"],
                    "target": info["target"],
                    "status": info["status"],
                    "trend": info["trend"],
                })
        alerts.sort(key=lambda x: (0 if x["status"] == "red" else 1, x["name"]))
        return alerts


# ── Main ──────────────────────────────────────────────────────────────────
def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    STATUS_COLORS = {"green": GREEN, "yellow": YELLOW, "red": RED}

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK — Brand Reporting — KPI Tracker{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}\n")

    tracker = KPITracker()
    kpis = tracker.calculate_all()

    print(f"  {BOLD}{'#':<4s} {'KPI':<32s} {'Value':>10s} {'Target':>10s} {'Status':>8s} {'Trend':>8s}{RESET}")
    print(f"  {'─'*4} {'─'*32} {'─'*10} {'─'*10} {'─'*8} {'─'*8}")

    for i, (kpi_id, info) in enumerate(kpis.items(), 1):
        sc = STATUS_COLORS.get(info["status"], RESET)
        val = info["value"]
        target = info["target"]
        # Format: rates as %, scores as numbers
        if "rate" in kpi_id:
            val_str = f"{val:.2%}"
            tgt_str = f"{target:.1%}" if isinstance(target, float) and target < 1 else str(target)
        elif kpi_id in ("on_time_delivery", "oee_average", "first_pass_yield", "smsi_score"):
            val_str = f"{val:.1f}"
            tgt_str = f">{target:.0f}"
        elif kpi_id in ("changeover_time_avg", "downtime_pct"):
            val_str = f"{val:.1f}"
            tgt_str = f"<{target:.0f}"
        elif kpi_id in ("energy_per_unit_kwh", "waste_per_unit_kg"):
            val_str = f"{val:.2f}"
            tgt_str = f"<{target}"
        elif kpi_id == "inventory_turnover":
            val_str = f"{val:.1f}x"
            tgt_str = f">{target:.0f}x"
        elif kpi_id == "supplier_quality_score":
            val_str = f"{val:.2f}"
            tgt_str = f">{target}"
        else:
            val_str = str(val)
            tgt_str = str(target)

        print(f"  {i:<4d} {info['name']:<32s} {val_str:>10s} {tgt_str:>10s} "
              f"{sc}{info['status']:>8s}{RESET} {info['trend']:>8s}")

    alerts = tracker.get_alerts()
    print(f"\n  {BOLD}Alerts ({len(alerts)}):{RESET}")
    for a in alerts:
        sc = STATUS_COLORS.get(a["status"], RESET)
        print(f"    {sc}●{RESET} {a['name']}: {a['value']} (target: {a['target']}) [{sc}{a['status']}{RESET}]")

    print(f"\n  {DIM}Saved → {RESULT_DIR}/kpi_status.json{RESET}")
    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()
