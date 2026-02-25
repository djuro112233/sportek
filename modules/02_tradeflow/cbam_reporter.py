"""
Sportek d.o.o. — TradeFlow AI — CBAM Reporter
EU Carbon Border Adjustment Mechanism quarterly reporting.

Usage:
    python modules/02_tradeflow/cbam_reporter.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
PRODUCTS_CSV = PROJECT_ROOT / "data" / "compliance" / "products_dpp.csv"
RESULT_DIR = MODULE_DIR / "results"

# ---------------------------------------------------------------------------
# Emission factors (kg CO2e per unit)
# ---------------------------------------------------------------------------
# Material-based embedded emissions (kg CO2e per kg of material)
MATERIAL_EMISSION_FACTORS = {
    "polyester": 5.5,
    "recycled polyester": 2.2,   # ~60% lower than virgin
    "nylon": 7.6,
    "elastane": 6.8,
    "rubber": 3.1,
    "eva": 3.8,
    "croslite": 4.2,
    "carbon fiber": 25.0,        # very energy-intensive
    "leather": 17.0,
}

# Energy grid emission factor by country (kg CO2e per kWh)
GRID_FACTORS = {
    "CN": 0.58, "VN": 0.52, "BD": 0.60, "IN": 0.71,
    "ID": 0.65, "KH": 0.54, "TW": 0.50, "BA": 0.73,
}

# Transport emission (kg CO2e per tonne-km, sea freight average)
TRANSPORT_SEA_KG_PER_TKM = 0.016


def _parse_materials_kg(composition_str: str, weight_grams: int) -> dict[str, float]:
    """Parse composition string → dict of {material: weight_kg}."""
    import re
    clean = re.sub(r"^[a-z]+:\s*", "", composition_str.strip())
    parts = re.findall(r"([a-z ]+?)\s+(\d+)%", clean, re.IGNORECASE)
    weight_kg = weight_grams / 1000
    result = {}
    if parts:
        for mat, pct in parts:
            result[mat.strip().lower()] = weight_kg * int(pct) / 100
    else:
        result[clean.lower()] = weight_kg
    return result


class CBAMReporter:
    """EU CBAM quarterly reporting for footwear imports."""

    def calculate_embedded_emissions(self, product_data: dict) -> float:
        """Calculate total embedded emissions (kg CO2e) for one product."""
        materials = _parse_materials_kg(
            product_data["materials_composition"],
            product_data["weight_grams"],
        )

        # Material emissions
        mat_emissions = 0.0
        for mat, kg in materials.items():
            factor = MATERIAL_EMISSION_FACTORS.get(mat, 5.0)  # default 5.0
            mat_emissions += kg * factor

        # Manufacturing energy emissions (from reported carbon footprint)
        # We treat the CSV carbon_footprint_kg as the total — use it directly
        # but also add transport estimate
        reported = product_data["carbon_footprint_kg"]

        # Transport estimate: avg 15,000 km sea freight to EU
        weight_tonnes = product_data["weight_grams"] / 1_000_000
        transport = weight_tonnes * 15_000 * TRANSPORT_SEA_KG_PER_TKM

        # Total = max(reported, material-based) + transport
        total = max(reported, mat_emissions) + transport
        return round(total, 3)

    def generate_report(self, products: list[dict], period: str) -> dict:
        """Generate a CBAM quarterly report for a list of products."""
        entries = []
        total_emissions = 0.0
        total_weight_kg = 0.0

        for p in products:
            emissions = self.calculate_embedded_emissions(p)
            total_emissions += emissions
            total_weight_kg += p["weight_grams"] / 1000
            entries.append({
                "product_id": p["product_id"],
                "product_name": p["product_name"],
                "brand": p["brand"],
                "hs_code": str(p["hs_code_6digit"]),
                "country_origin": p["country_origin"],
                "weight_kg": round(p["weight_grams"] / 1000, 3),
                "embedded_emissions_kg_co2e": emissions,
            })

        # Aggregate by country
        by_country = {}
        for e in entries:
            c = e["country_origin"]
            if c not in by_country:
                by_country[c] = {"products": 0, "emissions_kg": 0.0}
            by_country[c]["products"] += 1
            by_country[c]["emissions_kg"] = round(
                by_country[c]["emissions_kg"] + e["embedded_emissions_kg_co2e"], 3
            )

        # Aggregate by brand
        by_brand = {}
        for e in entries:
            b = e["brand"]
            if b not in by_brand:
                by_brand[b] = {"products": 0, "emissions_kg": 0.0}
            by_brand[b]["products"] += 1
            by_brand[b]["emissions_kg"] = round(
                by_brand[b]["emissions_kg"] + e["embedded_emissions_kg_co2e"], 3
            )

        total_tonnes = round(total_emissions / 1000, 4)

        report = {
            "report_type": "CBAM Quarterly Report",
            "reporting_entity": "Sportek d.o.o., Banja Luka, BiH",
            "period": period,
            "generated_date": str(date.today()),
            "summary": {
                "total_products": len(entries),
                "total_weight_kg": round(total_weight_kg, 2),
                "total_embedded_emissions_kg_co2e": round(total_emissions, 2),
                "total_embedded_emissions_tonnes_co2e": total_tonnes,
                "avg_emissions_per_product_kg": round(total_emissions / len(entries), 3),
            },
            "by_country_of_origin": by_country,
            "by_brand": by_brand,
            "product_details": entries,
        }
        return report

    def estimate_cbam_cost(
        self,
        total_emissions_tonnes: float,
        carbon_price_eur: float = 80.0,
    ) -> dict:
        """Estimate CBAM certificate cost based on ETS carbon price."""
        cost = round(total_emissions_tonnes * carbon_price_eur, 2)
        return {
            "total_emissions_tonnes": total_emissions_tonnes,
            "carbon_price_eur_per_tonne": carbon_price_eur,
            "estimated_cbam_cost_eur": cost,
            "note": "CBAM transitional period: reporting only (no payments) until 2025-12-31. "
                    "Full CBAM with certificates from 2026-01-01.",
        }


# ======================================================================
# CLI entry-point
# ======================================================================
def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print()
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK TradeFlow — CBAM Quarterly Reporter{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")

    reporter = CBAMReporter()

    # Load all products for Q4 2025 (Oct-Dec 2025)
    df = pd.read_csv(PRODUCTS_CSV)
    df["production_date"] = pd.to_datetime(df["production_date"])
    q4_mask = (
        (df["production_date"] >= "2025-10-01") &
        (df["production_date"] <= "2025-12-31")
    )
    q4_products = df[q4_mask].to_dict("records")

    print(f"\n  Products in Q4 2025: {len(q4_products)}")

    # Generate report
    report = reporter.generate_report(q4_products, period="Q4-2025")

    # CBAM cost estimate
    total_t = report["summary"]["total_embedded_emissions_tonnes_co2e"]
    cost = reporter.estimate_cbam_cost(total_t, carbon_price_eur=80.0)
    report["cbam_cost_estimate"] = cost

    # Save
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULT_DIR / "cbam_q4_2025.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Print summary
    s = report["summary"]
    print(f"\n  {BOLD}CBAM Report — {report['period']}{RESET}")
    print(f"    Total products:          {s['total_products']}")
    print(f"    Total weight:            {s['total_weight_kg']:,.2f} kg")
    print(f"    Total emissions:         {s['total_embedded_emissions_kg_co2e']:,.2f} kg CO2e")
    print(f"    Total emissions:         {s['total_embedded_emissions_tonnes_co2e']:.4f} tonnes CO2e")
    print(f"    Avg per product:         {s['avg_emissions_per_product_kg']:.3f} kg CO2e")

    print(f"\n  {BOLD}By Country of Origin:{RESET}")
    for country, data in sorted(report["by_country_of_origin"].items(),
                                 key=lambda x: -x[1]["emissions_kg"]):
        print(f"    {country}: {data['products']:>3} products, "
              f"{data['emissions_kg']:>8.2f} kg CO2e")

    print(f"\n  {BOLD}By Brand:{RESET}")
    for brand, data in sorted(report["by_brand"].items(),
                               key=lambda x: -x[1]["emissions_kg"]):
        print(f"    {brand:12s}: {data['products']:>3} products, "
              f"{data['emissions_kg']:>8.2f} kg CO2e")

    print(f"\n  {BOLD}CBAM Cost Estimate:{RESET}")
    print(f"    Carbon price:    {cost['carbon_price_eur_per_tonne']} EUR/tonne")
    print(f"    {YELLOW}Estimated cost:  {cost['estimated_cbam_cost_eur']:,.2f} EUR{RESET}")
    print(f"    {DIM}{cost['note']}{RESET}")

    print(f"\n  {DIM}Saved → {out_path}{RESET}")
    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}\n")


if __name__ == "__main__":
    main()
