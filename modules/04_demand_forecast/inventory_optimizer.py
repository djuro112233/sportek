"""
Sportek d.o.o. — Demand Forecast — Inventory Optimizer
Safety stock, EOQ, reorder point, stockout risk detection.

Usage:
    python -m modules.04_demand_forecast.inventory_optimizer
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
INV_CSV = PROJECT_ROOT / "data" / "supply_chain" / "inventory.csv"
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# Constants
ORDER_COST_EUR = 50          # fixed cost per order
HOLDING_COST_PCT = 0.20      # 20% of unit price per year
Z_95 = 1.645                 # Z-score for 95% service level


class InventoryOptimizer:
    """Optimize inventory levels for Sportek materials."""

    def __init__(self) -> None:
        self.inventory = pd.read_csv(INV_CSV)
        # Precompute daily demand std as 30% of consumption_rate (realistic variability)
        self.inventory["demand_std_daily"] = (
            self.inventory["consumption_rate_daily"] * 0.30
        )

    # ------------------------------------------------------------------
    # Safety stock
    # ------------------------------------------------------------------
    def calculate_safety_stock(
        self, material_id: str, service_level: float = 0.95,
    ) -> float:
        row = self.inventory[self.inventory["material_id"] == material_id]
        if row.empty:
            raise ValueError(f"Material {material_id} not found")
        row = row.iloc[0]
        z = Z_95 if service_level == 0.95 else abs(float(np.percentile(
            np.random.standard_normal(10000), service_level * 100
        )))
        sigma_d = row["demand_std_daily"]
        lt = row["lead_time_days"]
        return round(z * sigma_d * math.sqrt(lt / 7), 1)

    # ------------------------------------------------------------------
    # EOQ
    # ------------------------------------------------------------------
    def calculate_eoq(self, material_id: str) -> float:
        row = self.inventory[self.inventory["material_id"] == material_id]
        if row.empty:
            raise ValueError(f"Material {material_id} not found")
        row = row.iloc[0]
        annual_demand = row["consumption_rate_daily"] * 365
        holding_cost = row["unit_price_eur"] * HOLDING_COST_PCT
        if holding_cost <= 0:
            holding_cost = 0.01  # guard
        return round(math.sqrt(2 * annual_demand * ORDER_COST_EUR / holding_cost), 0)

    # ------------------------------------------------------------------
    # Reorder point
    # ------------------------------------------------------------------
    def calculate_reorder_point(self, material_id: str) -> float:
        row = self.inventory[self.inventory["material_id"] == material_id]
        if row.empty:
            raise ValueError(f"Material {material_id} not found")
        row = row.iloc[0]
        avg_daily = row["consumption_rate_daily"]
        lt = row["lead_time_days"]
        ss = self.calculate_safety_stock(material_id)
        return round(avg_daily * lt + ss, 0)

    # ------------------------------------------------------------------
    # Optimize all
    # ------------------------------------------------------------------
    def optimize_all(self) -> pd.DataFrame:
        records = []
        for _, row in self.inventory.iterrows():
            mid = row["material_id"]
            ss = self.calculate_safety_stock(mid)
            eoq = self.calculate_eoq(mid)
            rop = self.calculate_reorder_point(mid)

            daily = row["consumption_rate_daily"]
            days_of_stock = (
                round(row["current_stock"] / daily, 1) if daily > 0 else 999
            )
            lt = row["lead_time_days"]

            if days_of_stock < lt:
                status = "critical"
            elif days_of_stock < 2 * lt:
                status = "low"
            elif days_of_stock > 4 * lt:
                status = "overstocked"
            else:
                status = "ok"

            records.append({
                "material_id": mid,
                "material_name": row["material_name"],
                "current_stock": int(row["current_stock"]),
                "optimal_reorder_point": int(rop),
                "current_reorder_point": int(row["reorder_point"]),
                "safety_stock": round(ss, 0),
                "eoq": int(eoq),
                "days_of_stock": days_of_stock,
                "lead_time_days": lt,
                "unit_price_eur": row["unit_price_eur"],
                "status": status,
            })
        return pd.DataFrame(records)

    # ------------------------------------------------------------------
    # Stockout risk
    # ------------------------------------------------------------------
    def detect_stockout_risk(self, days_ahead: int = 30) -> list[dict]:
        risks = []
        for _, row in self.inventory.iterrows():
            daily = row["consumption_rate_daily"]
            if daily <= 0:
                continue
            days_left = row["current_stock"] / daily
            if days_left > days_ahead:
                continue

            lt = row["lead_time_days"]
            if days_left < lt:
                level = "high"
            elif days_left < lt * 2:
                level = "medium"
            else:
                level = "low"

            ss = self.calculate_safety_stock(row["material_id"])
            eoq = self.calculate_eoq(row["material_id"])
            order_qty = max(eoq, daily * lt + ss - row["current_stock"])

            risks.append({
                "material_id": row["material_id"],
                "material_name": row["material_name"],
                "current_stock": int(row["current_stock"]),
                "days_until_stockout": round(days_left, 1),
                "lead_time_days": lt,
                "risk_level": level,
                "recommended_order_qty": int(round(order_qty)),
                "estimated_cost": round(order_qty * row["unit_price_eur"], 2),
            })

        risks.sort(key=lambda x: x["days_until_stockout"])
        return risks

    # ------------------------------------------------------------------
    # Savings calculation
    # ------------------------------------------------------------------
    def calculate_savings(self, opt_df: pd.DataFrame) -> dict:
        # Current excess stock value (overstocked items)
        over = opt_df[opt_df["status"] == "overstocked"]
        optimal_stock = over["optimal_reorder_point"] + over["safety_stock"]
        excess_units = (over["current_stock"] - optimal_stock).clip(lower=0)
        excess_value = (excess_units * over["unit_price_eur"]).sum()

        # Stockout cost avoidance (critical items × estimated rework)
        critical = opt_df[opt_df["status"] == "critical"]
        stockout_cost_avoided = len(critical) * 500  # avg 500 EUR per stockout event

        # Order optimisation (EOQ vs current ad-hoc ordering)
        # Merge consumption_rate from original inventory into opt_df
        inv_rates = self.inventory.set_index("material_id")["consumption_rate_daily"]
        merged = opt_df.set_index("material_id").join(inv_rates)
        total_current_orders = len(opt_df) * 24  # assume 24 orders/yr each
        eoq_orders = sum(
            (r["consumption_rate_daily"] * 365) / max(r["eoq"], 1)
            for _, r in merged.iterrows()
        )
        order_cost_current = total_current_orders * ORDER_COST_EUR
        order_cost_optimal = round(eoq_orders * ORDER_COST_EUR)
        order_saving = order_cost_current - order_cost_optimal

        # Holding cost reduction from reducing overstock
        holding_saving = round(excess_value * HOLDING_COST_PCT, 2)

        return {
            "overstock_items": len(over),
            "excess_inventory_value_eur": round(excess_value, 2),
            "freed_capital_eur": round(excess_value, 2),
            "holding_cost_saving_eur_year": holding_saving,
            "stockout_events_prevented": len(critical),
            "stockout_cost_avoided_eur": stockout_cost_avoided,
            "order_cost_current_eur": order_cost_current,
            "order_cost_optimal_eur": order_cost_optimal,
            "order_cost_saving_eur": order_saving,
            "total_annual_saving_eur": round(
                holding_saving + stockout_cost_avoided + order_saving, 2
            ),
        }


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

    print(f"\n{BOLD}{CYAN}{'=' * 65}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK — Demand Forecast — Inventory Optimization{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 65}{RESET}\n")

    opt = InventoryOptimizer()
    df = opt.optimize_all()

    # Status summary
    status_counts = df["status"].value_counts()
    print(f"  Ukupno materijala: {GREEN}{len(df)}{RESET}")
    for st in ("critical", "low", "ok", "overstocked"):
        cnt = status_counts.get(st, 0)
        color = RED if st == "critical" else YELLOW if st == "low" else GREEN if st == "ok" else CYAN
        print(f"    {color}{st:<14s}{RESET} {cnt:>4d}")

    # Stockout risks
    risks = opt.detect_stockout_risk(days_ahead=30)
    high_risk = [r for r in risks if r["risk_level"] == "high"]
    med_risk = [r for r in risks if r["risk_level"] == "medium"]
    total_risk_value = sum(r["estimated_cost"] for r in risks)

    print(f"\n  {BOLD}Stockout rizik (30 dana):{RESET}")
    print(f"    Ukupno rizičnih:     {YELLOW}{len(risks)}{RESET}")
    print(f"    Visok rizik:         {RED}{len(high_risk)}{RESET}")
    print(f"    Srednji rizik:       {YELLOW}{len(med_risk)}{RESET}")
    print(f"    Ukupna vrijednost narudžbi: {GREEN}{total_risk_value:,.0f} EUR{RESET}")

    if risks[:5]:
        print(f"\n  {BOLD}Top 5 najkritičnijih:{RESET}")
        for r in risks[:5]:
            color = RED if r["risk_level"] == "high" else YELLOW
            print(f"    {color}{r['material_id']}{RESET}  {r['material_name'][:30]:<30s}"
                  f"  {r['days_until_stockout']:>5.1f} dana  {r['risk_level']:>6s}"
                  f"  naruči: {r['recommended_order_qty']:>6,}  ({r['estimated_cost']:>10,.0f} EUR)")

    # Savings
    savings = opt.calculate_savings(df)
    print(f"\n  {BOLD}Uštede vs trenutni pristup:{RESET}")
    print(f"    Oslobođen kapital (overstock): {GREEN}{savings['freed_capital_eur']:>12,.0f} EUR{RESET}")
    print(f"    Holding cost ušteda:           {GREEN}{savings['holding_cost_saving_eur_year']:>12,.0f} EUR/god{RESET}")
    print(f"    Izbjegnuti stockout troškovi:   {GREEN}{savings['stockout_cost_avoided_eur']:>12,.0f} EUR{RESET}")
    print(f"    Ušteda troškova narudžbi:       {GREEN}{savings['order_cost_saving_eur']:>12,.0f} EUR/god{RESET}")
    print(f"    {BOLD}UKUPNA GODIŠNJA UŠTEDA:        {GREEN}{savings['total_annual_saving_eur']:>12,.0f} EUR{RESET}")

    # Save results
    opt_records = df.to_dict(orient="records")
    with open(RESULT_DIR / "optimization_results.json", "w") as f:
        json.dump({
            "total_materials": len(df),
            "status_summary": status_counts.to_dict(),
            "savings": savings,
            "materials": opt_records,
        }, f, indent=2, ensure_ascii=False)

    with open(RESULT_DIR / "stockout_risks.json", "w") as f:
        json.dump({
            "days_ahead": 30,
            "total_at_risk": len(risks),
            "high_risk": len(high_risk),
            "medium_risk": len(med_risk),
            "total_order_value_eur": round(total_risk_value, 2),
            "risks": risks,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n  {DIM}Saved → results/optimization_results.json{RESET}")
    print(f"  {DIM}Saved → results/stockout_risks.json{RESET}")
    print(f"\n{'=' * 65}\n")


if __name__ == "__main__":
    main()
