"""
Sportek d.o.o. — Brand Reporting — Report Templates
NikeScorecard, CrocsReport, DecathlonReport — each reads CSV data and
produces a structured dict for the corresponding brand.

Usage:
    python -m modules.06_brand_reporting.templates
"""

from __future__ import annotations

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


def _parse_quarter(period: str) -> tuple[int, int]:
    """Return (year, quarter) from '2025-Q4' style string."""
    parts = period.split("-")
    year = int(parts[0])
    quarter = int(parts[1].replace("Q", ""))
    return year, quarter


def _quarter_months(year: int, quarter: int) -> list[int]:
    """Return list of months belonging to a quarter."""
    return list(range((quarter - 1) * 3 + 1, quarter * 3 + 1))


def _filter_period(df: pd.DataFrame, period: str, date_col: str = "date") -> pd.DataFrame:
    """Filter dataframe to rows within the given quarter period."""
    year, quarter = _parse_quarter(period)
    months = _quarter_months(year, quarter)
    mask = (df[date_col].dt.year == year) & (df[date_col].dt.month.isin(months))
    return df[mask].copy()


# ── Nike SMSI Scorecard ──────────────────────────────────────────────────

class NikeScorecard:
    """Nike Supplier Manufacturing Sustainability Index scorecard."""

    def __init__(self) -> None:
        self.prod = pd.read_csv(PROD_CSV, parse_dates=["date"])
        self.defects = pd.read_csv(DEFECT_CSV, parse_dates=["date"])
        self.dpp = pd.read_csv(DPP_CSV, parse_dates=["production_date"])
        self.po = pd.read_csv(PO_CSV, parse_dates=["date", "expected_delivery", "actual_delivery"])

    def generate(self, period: str = "2025-Q4") -> dict:
        prod = _filter_period(self.prod[self.prod["brand"] == "Nike"], period)
        defects = _filter_period(self.defects[self.defects["brand"] == "Nike"], period)
        dpp = self.dpp[self.dpp["brand"] == "Nike"]

        total_actual = int(prod["actual_qty"].sum())
        total_defect_qty = int(prod["defect_qty"].sum())

        # ── Quality (weight 40) ───────────────────────────────────────
        defect_rate = round(total_defect_qty / total_actual, 4) if total_actual > 0 else 0
        rework_count = len(defects[defects["action"] == "rework"])
        total_defect_records = len(defects)
        rework_rate = round(rework_count / total_defect_records, 4) if total_defect_records > 0 else 0
        customer_returns = int(len(defects[defects["detection_point"] == "customer_return"]))
        customer_return_rate = round(customer_returns / total_actual, 4) if total_actual > 0 else 0
        aql_compliance = defect_rate < 0.025  # Nike AQL: 2.5%

        # Score: normalised 0-100 (defect_rate up to 15% → linear scale)
        defect_sub = max(0, min(100, (1 - defect_rate / 0.15) * 100))
        rework_sub = max(0, min(100, (1 - rework_rate) * 100))
        return_sub = max(0, min(100, (1 - customer_return_rate / 0.01) * 100))
        quality_score = round(defect_sub * 0.50 + rework_sub * 0.30 + return_sub * 0.20, 1)

        # ── Delivery (weight 25) ──────────────────────────────────────
        po_period = _filter_period(self.po, period)
        if len(po_period) > 0:
            on_time = len(po_period[po_period["delay_days"] <= 0])
            otd_pct = round(on_time / len(po_period) * 100, 1)
            avg_lead_time = round(float(po_period["delay_days"].mean() +
                                        (po_period["expected_delivery"] - po_period["date"]).dt.days.mean()), 1)
        else:
            otd_pct = 95.0
            avg_lead_time = 30.0

        # Flexibility: how well planned vs actual matches
        flex_ratio = prod["actual_qty"].sum() / prod["planned_qty"].sum() if prod["planned_qty"].sum() > 0 else 0
        flexibility_score = round(min(100, flex_ratio * 100), 1)

        delivery_score = round(otd_pct * 0.6 + flexibility_score * 0.4, 1)

        # ── Sustainability (weight 20) ────────────────────────────────
        carbon_per_pair = round(float(dpp["carbon_footprint_kg"].mean()), 2)
        recyclability = round(float(dpp["recyclability_score"].mean()), 1)
        waste_reduction_pct = round(recyclability * 0.5, 1)  # proxy
        # Carbon: 3 kg/pair = 100, 15 kg = 0 (linear scale)
        energy_efficiency = round(max(0, min(100, (15 - carbon_per_pair) / 12 * 100)), 1)

        sustainability_score = round(energy_efficiency * 0.35 + recyclability * 0.35 +
                                     waste_reduction_pct * 0.30, 1)

        # ── Innovation (weight 15) ────────────────────────────────────
        n_models = prod["model_name"].nunique()
        n_machines = prod["machine_id"].nunique()
        cost_opt = round((1 - defect_rate) * 100 - 90, 2)  # above 90% yield → saving

        process_improvements = n_models  # each model = process capability
        technology_adoption = round(min(100, n_machines * 5), 1)

        innovation_score = round(technology_adoption * 0.40 + min(100, process_improvements * 15) * 0.30 +
                                 max(0, min(100, cost_opt * 10)) * 0.30, 1)
        innovation_score = round(min(100, innovation_score), 1)

        # ── SMSI (weighted) ───────────────────────────────────────────
        smsi = round(
            quality_score * 0.40 +
            delivery_score * 0.25 +
            sustainability_score * 0.20 +
            innovation_score * 0.15, 1,
        )

        if smsi >= 90:
            grade = "Gold"
        elif smsi >= 75:
            grade = "Silver"
        elif smsi >= 60:
            grade = "Bronze"
        else:
            grade = "Needs Improvement"

        # Trend: compare first/second half of period
        mid = len(prod) // 2
        if mid > 0:
            oee_first = prod.iloc[:mid]["oee_score"].mean()
            oee_second = prod.iloc[mid:]["oee_score"].mean()
            diff = oee_second - oee_first
            trend = "improving" if diff > 0.01 else "declining" if diff < -0.01 else "stable"
        else:
            trend = "stable"

        return {
            "brand": "Nike",
            "period": period,
            "smsi_score": smsi,
            "quality": {
                "score": quality_score,
                "weight": 40,
                "defect_rate": defect_rate,
                "rework_rate": rework_rate,
                "customer_returns": customer_returns,
                "aql_compliance": aql_compliance,
            },
            "delivery": {
                "score": delivery_score,
                "weight": 25,
                "on_time_delivery_pct": otd_pct,
                "avg_lead_time_days": avg_lead_time,
                "flexibility_score": flexibility_score,
            },
            "sustainability": {
                "score": sustainability_score,
                "weight": 20,
                "carbon_per_pair_kg": carbon_per_pair,
                "waste_reduction_pct": waste_reduction_pct,
                "energy_efficiency": energy_efficiency,
            },
            "innovation": {
                "score": innovation_score,
                "weight": 15,
                "process_improvements": process_improvements,
                "technology_adoption": technology_adoption,
                "cost_optimization_pct": round(cost_opt, 2),
            },
            "overall_grade": grade,
            "trend": trend,
        }


# ── Crocs Performance Report ─────────────────────────────────────────────

class CrocsReport:
    """Crocs quarterly performance report."""

    def __init__(self) -> None:
        self.prod = pd.read_csv(PROD_CSV, parse_dates=["date"])
        self.defects = pd.read_csv(DEFECT_CSV, parse_dates=["date"])
        self.inv = pd.read_csv(INV_CSV)
        self.po = pd.read_csv(PO_CSV, parse_dates=["date", "expected_delivery", "actual_delivery"])

    def generate(self, period: str = "2025-Q4") -> dict:
        prod = _filter_period(self.prod[self.prod["brand"] == "Crocs"], period)
        defects = _filter_period(self.defects[self.defects["brand"] == "Crocs"], period)

        # ── Production ────────────────────────────────────────────────
        total_units = int(prod["actual_qty"].sum())
        planned_total = int(prod["planned_qty"].sum())
        planned_vs_actual = round(total_units / planned_total * 100, 1) if planned_total > 0 else 0

        top_models = []
        for model, grp in prod.groupby("model_name"):
            top_models.append({
                "model": model,
                "units": int(grp["actual_qty"].sum()),
                "oee_avg": round(float(grp["oee_score"].mean()), 4),
            })
        top_models.sort(key=lambda x: x["units"], reverse=True)

        # ── Quality ───────────────────────────────────────────────────
        defect_qty = int(prod["defect_qty"].sum())
        defect_rate = round(defect_qty / total_units, 4) if total_units > 0 else 0
        fpy = round(1 - defect_rate, 4)  # first pass yield

        top_defects = []
        if len(defects) > 0:
            for dt, grp in defects.groupby("defect_type"):
                top_defects.append({"type": dt, "count": len(grp)})
            top_defects.sort(key=lambda x: x["count"], reverse=True)
            top_defects = top_defects[:5]

        aql_status = "pass" if defect_rate < 0.035 else "fail"

        # ── Delivery ──────────────────────────────────────────────────
        po_period = _filter_period(self.po, period)
        if len(po_period) > 0:
            on_time = len(po_period[po_period["delay_days"] <= 0])
            otd_pct = round(on_time / len(po_period) * 100, 1)
            avg_lead_time = round(float(
                (po_period["actual_delivery"] - po_period["date"]).dt.days.mean()
            ), 1)
        else:
            otd_pct = 95.0
            avg_lead_time = 30.0

        # ── Inventory (Croslite focus) ────────────────────────────────
        foam_materials = self.inv[self.inv["category"] == "Foam"]
        if len(foam_materials) > 0:
            croslite_stock_days = round(float(
                (foam_materials["current_stock"] / foam_materials["consumption_rate_daily"]).mean()
            ), 1)
        else:
            croslite_stock_days = 0

        critical = self.inv[self.inv["current_stock"] < self.inv["reorder_point"]]
        critical_materials = []
        for _, row in critical.head(5).iterrows():
            critical_materials.append({
                "material": row["material_name"],
                "stock": int(row["current_stock"]),
                "reorder_point": int(row["reorder_point"]),
            })

        return {
            "brand": "Crocs",
            "period": period,
            "production": {
                "total_units": total_units,
                "planned_vs_actual_pct": planned_vs_actual,
                "top_models": top_models,
            },
            "quality": {
                "fpy": fpy,
                "defect_rate": defect_rate,
                "top_defects": top_defects,
                "aql_status": aql_status,
            },
            "delivery": {
                "otd_pct": otd_pct,
                "avg_lead_time": avg_lead_time,
            },
            "inventory": {
                "croslite_stock_days": croslite_stock_days,
                "critical_materials": critical_materials,
            },
        }


# ── Decathlon Sustainability Report ───────────────────────────────────────

class DecathlonReport:
    """Decathlon quarterly sustainability & performance report."""

    def __init__(self) -> None:
        self.prod = pd.read_csv(PROD_CSV, parse_dates=["date"])
        self.defects = pd.read_csv(DEFECT_CSV, parse_dates=["date"])
        self.dpp = pd.read_csv(DPP_CSV, parse_dates=["production_date"])

    def generate(self, period: str = "2025-Q4") -> dict:
        prod = _filter_period(self.prod[self.prod["brand"] == "Decathlon"], period)
        defects = _filter_period(self.defects[self.defects["brand"] == "Decathlon"], period)
        dpp = self.dpp[self.dpp["brand"] == "Decathlon"]

        total_units = int(prod["actual_qty"].sum())
        total_planned = int(prod["planned_qty"].sum())
        defect_qty = int(prod["defect_qty"].sum())

        # ── Sustainability ────────────────────────────────────────────
        carbon_total = round(float(dpp["carbon_footprint_kg"].sum()), 1)
        carbon_per_unit = round(float(dpp["carbon_footprint_kg"].mean()), 2)
        recyclability = float(dpp["recyclability_score"].mean())

        # Estimate recycled content from materials_composition
        recycled_count = dpp["materials_composition"].str.contains("recycled", case=False, na=False).sum()
        recycled_content_pct = round(recycled_count / len(dpp) * 100, 1) if len(dpp) > 0 else 0

        # Waste estimate: defects × avg weight
        avg_weight_kg = dpp["weight_grams"].mean() / 1000
        waste_kg = round(defect_qty * avg_weight_kg, 1)

        # ── Quality ───────────────────────────────────────────────────
        defect_rate = round(defect_qty / total_units, 4) if total_units > 0 else 0

        # Customer satisfaction proxy: inverse of customer returns + overall quality
        customer_return_count = len(defects[defects["detection_point"] == "customer_return"])
        satisfaction = round(max(0, min(100, 100 - customer_return_count * 0.5 - defect_rate * 500)), 1)

        # ── Social ────────────────────────────────────────────────────
        avg_operators = float(prod["operator_count"].mean()) if len(prod) > 0 else 0
        total_shifts = len(prod)
        # Simulate: compliance if avg operators ≤ 8 (reasonable shift)
        working_hours_compliance = avg_operators <= 8
        # Safety: assume minor incidents proportional to defect severity
        critical_defects = len(defects[defects["severity"] == "critical"])
        safety_incidents = max(0, critical_defects // 10)
        # Training hours estimate: proportional to operator count
        training_hours = round(avg_operators * 4 * 3, 1)  # 4h/operator/month × 3 months

        # ── Production ────────────────────────────────────────────────
        efficiency = round(total_units / total_planned * 100, 1) if total_planned > 0 else 0

        return {
            "brand": "Decathlon",
            "period": period,
            "sustainability": {
                "carbon_footprint_total": carbon_total,
                "per_unit": carbon_per_unit,
                "recycled_content_pct": recycled_content_pct,
                "waste_kg": waste_kg,
            },
            "quality": {
                "defect_rate": defect_rate,
                "customer_satisfaction": satisfaction,
            },
            "social": {
                "working_hours_compliance": working_hours_compliance,
                "safety_incidents": safety_incidents,
                "training_hours": training_hours,
            },
            "production": {
                "total_units": total_units,
                "efficiency": efficiency,
            },
        }


# ── Main ──────────────────────────────────────────────────────────────────
def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK — Brand Reporting — Templates Test{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}\n")

    period = "2025-Q4"

    nike = NikeScorecard().generate(period)
    print(f"  {BOLD}Nike SMSI:{RESET} {GREEN}{nike['smsi_score']}{RESET}  Grade: {nike['overall_grade']}  Trend: {nike['trend']}")

    crocs = CrocsReport().generate(period)
    print(f"  {BOLD}Crocs:{RESET}    Units={crocs['production']['total_units']:,}  FPY={crocs['quality']['fpy']:.2%}  AQL={crocs['quality']['aql_status']}")

    deca = DecathlonReport().generate(period)
    print(f"  {BOLD}Decathlon:{RESET} Units={deca['production']['total_units']:,}  Carbon/unit={deca['sustainability']['per_unit']}kg  Efficiency={deca['production']['efficiency']}%")

    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()
