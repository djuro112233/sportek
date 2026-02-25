"""
Sportek d.o.o. — TradeFlow AI — EU Digital Product Passport Generator
Generates ESPR-compliant DPPs with QR codes for footwear products.

Usage:
    python modules/02_tradeflow/dpp_generator.py
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import qrcode

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
PRODUCTS_CSV = PROJECT_ROOT / "data" / "compliance" / "products_dpp.csv"
RESULT_DIR = MODULE_DIR / "results"
DPP_DIR = RESULT_DIR / "dpp_examples"

# ---------------------------------------------------------------------------
# Required top-level DPP sections (ESPR)
# ---------------------------------------------------------------------------
REQUIRED_SECTIONS = [
    "dpp_version", "unique_id", "issued_date", "manufacturer",
    "product", "materials", "sustainability", "origin",
    "compliance", "durability", "end_of_life",
]

MANUFACTURER_INFO = {
    "name": "Sportek d.o.o.",
    "address": "Banja Luka, BiH",
    "id": "SPORTEK-BL-001",
}

# Care / repair / EOL templates per product line
CARE_TEMPLATES = {
    "Flyknit": {
        "care": "Remove insoles before washing. Machine wash cold 30 C, air dry. Do not tumble dry.",
        "repair": "Upper repair via Sportek Repair Centre or authorised Nike service points.",
        "disassembly": "Separate sole from upper via heat-activated adhesive at 80 C. Remove insole manually.",
        "recyclable": ["textile upper", "rubber outsole", "foam midsole"],
        "disposal": "Return via Nike Grind or Sportek take-back programme. Textile upper recyclable, sole to energy recovery.",
    },
    "Pegasus": {
        "care": "Spot clean with damp cloth. Air dry away from direct heat.",
        "repair": "Collar replacement available via Sportek Repair Centre.",
        "disassembly": "Knit collar detaches from shoe body via stitching removal.",
        "recyclable": ["recycled polyester knit", "elastane blend"],
        "disposal": "Return via Sportek take-back. 70%+ recycled content — prioritise textile recycling.",
    },
    "Clog": {
        "care": "Wash with warm soapy water. Air dry.",
        "repair": "Strap replacement kits available. Full refurbishment via Crocs ReNew.",
        "disassembly": "Strap detaches via pin release. Single-material body, no further disassembly needed.",
        "recyclable": ["Croslite foam body", "strap assembly"],
        "disposal": "Return via Crocs Old Crocs New programme. Croslite is 100% recyclable.",
    },
    "Kalenji": {
        "care": "Remove debris after use. Hand wash, air dry.",
        "repair": "Sole reattachment available at Decathlon workshops.",
        "disassembly": "Sole unit separates from upper via solvent release. EVA and rubber separable.",
        "recyclable": ["rubber outsole", "EVA midsole"],
        "disposal": "Return to Decathlon second-life programme. Rubber recycled, EVA to energy recovery.",
    },
    "ZoomX": {
        "care": "Wipe clean. Do not bend carbon plate. Store flat.",
        "repair": "Non-repairable component. Full shoe replacement if plate cracks.",
        "disassembly": "Carbon plate bonded with epoxy — requires industrial solvent for separation.",
        "recyclable": ["carbon fiber (industrial recycling only)"],
        "disposal": "Return via Nike Grind. Carbon fiber requires specialised recycling — do not place in household waste.",
    },
}


def _match_template(product_name: str) -> dict:
    """Find the best care/repair template for a product name."""
    for key, tpl in CARE_TEMPLATES.items():
        if key.lower() in product_name.lower():
            return tpl
    return CARE_TEMPLATES["Kalenji"]  # fallback


def _parse_materials(composition_str: str) -> dict:
    """Parse 'upper: polyester 55% elastane 30% nylon 15%' → dict."""
    result = {}
    clean = re.sub(r"^[a-z]+:\s*", "", composition_str.strip())
    parts = re.findall(r"([a-z ]+?)\s+(\d+)%", clean, re.IGNORECASE)
    for mat, pct in parts:
        result[mat.strip()] = int(pct)
    if not result:
        result[clean] = 100
    return result


def _generate_gtin(product_id: str) -> str:
    """Deterministic pseudo-GTIN-13 from product ID."""
    h = hashlib.md5(product_id.encode()).hexdigest()
    digits = "38" + "".join(c for c in h if c.isdigit())[:10]
    return digits.ljust(13, "0")[:13]


class DPPGenerator:
    """Generate ESPR-compliant Digital Product Passports."""

    def generate(self, product_data: dict) -> dict:
        """Build a complete DPP dict from a product row."""
        pid = product_data["product_id"]
        uid = f"DPP-SPT-{pid.replace('PROD-', '')}"
        tpl = _match_template(product_data["product_name"])
        mat_comp = _parse_materials(product_data["materials_composition"])
        recycled_pct = sum(v for k, v in mat_comp.items() if "recycled" in k.lower())

        # Estimate energy & water from weight + carbon footprint
        weight_kg = product_data["weight_grams"] / 1000
        carbon = product_data["carbon_footprint_kg"]
        energy_kwh = round(carbon * 2.8, 2)    # ~2.8 kWh per kg CO2 for footwear mfg
        water_litres = round(weight_kg * 45, 1)  # ~45 L/kg for textile footwear

        dpp = {
            "dpp_version": "1.0",
            "unique_id": uid,
            "issued_date": str(date.today()),
            "manufacturer": MANUFACTURER_INFO.copy(),
            "product": {
                "name": product_data["product_name"],
                "brand": product_data["brand"],
                "model": product_data["product_name"].split(" v")[0],
                "gtin": _generate_gtin(pid),
                "hs_code": str(product_data["hs_code_6digit"]),
                "weight_grams": product_data["weight_grams"],
            },
            "materials": {
                "composition": mat_comp,
                "recycled_content_pct": recycled_pct,
                "hazardous_substances": product_data.get("hazardous_substances", "REACH compliant"),
                "restricted_substances_tested": True,
            },
            "sustainability": {
                "carbon_footprint_kg": product_data["carbon_footprint_kg"],
                "carbon_footprint_methodology": "ISO 14067",
                "energy_consumption_kwh": energy_kwh,
                "water_consumption_liters": water_litres,
                "recyclability_score": product_data["recyclability_score"],
                "disassembly_instructions": tpl["disassembly"],
            },
            "origin": {
                "country": product_data["country_origin"],
                "factory": product_data["factory_id"],
                "production_date": product_data["production_date"],
                "batch": product_data["batch_number"],
            },
            "compliance": {
                "ce_marking": True,
                "reach": True,
                "oeko_tex": "SVHC" not in product_data.get("hazardous_substances", ""),
            },
            "durability": {
                "expected_lifetime_years": 3 if "Carbon" in product_data["product_name"] else 5,
                "care_instructions": tpl["care"],
                "repair_info": tpl["repair"],
            },
            "end_of_life": {
                "recyclable_components": tpl["recyclable"],
                "disposal_instructions": tpl["disposal"],
            },
        }
        return dpp

    def validate(self, dpp_data: dict) -> dict:
        """Check DPP completeness and return validation result."""
        missing = [s for s in REQUIRED_SECTIONS if s not in dpp_data]
        warnings = []

        # Check sub-fields
        if dpp_data.get("materials", {}).get("recycled_content_pct", 0) == 0:
            warnings.append("No recycled content declared — verify with supplier.")
        if dpp_data.get("sustainability", {}).get("recyclability_score", 0) < 50:
            warnings.append("Recyclability score below 50% — may not meet EU 2030 targets.")
        if not dpp_data.get("compliance", {}).get("oeko_tex"):
            warnings.append("OEKO-TEX certification missing — consider testing.")

        # Completeness = filled top-level sections / total
        filled = sum(1 for s in REQUIRED_SECTIONS if s in dpp_data and dpp_data[s])
        completeness = round(filled / len(REQUIRED_SECTIONS) * 100, 1)

        return {
            "valid": len(missing) == 0,
            "missing_fields": missing,
            "warnings": warnings,
            "completeness_pct": completeness,
        }

    def generate_qr(self, dpp_data: dict, output_path: Path) -> None:
        """Generate QR code PNG linking to the DPP unique ID."""
        url = f"https://dpp.sportek.ba/{dpp_data['unique_id']}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0D1B2A", back_color="white")
        img.save(str(output_path))


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
    print(f"{BOLD}{CYAN}  SPORTEK TradeFlow — Digital Product Passport Generator (ESPR){RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")

    gen = DPPGenerator()

    # Load products — first 5 for demo
    df = pd.read_csv(PRODUCTS_CSV)
    demo = df.head(5).to_dict("records")

    DPP_DIR.mkdir(parents=True, exist_ok=True)

    total_generated = 0
    total_valid = 0

    for row in demo:
        dpp = gen.generate(row)
        val = gen.validate(dpp)

        pid = row["product_id"]

        # Save DPP JSON
        json_path = DPP_DIR / f"dpp_{pid}.json"
        with open(json_path, "w") as f:
            json.dump(dpp, f, indent=2, ensure_ascii=False)

        # Save QR
        qr_path = DPP_DIR / f"qr_{pid}.png"
        gen.generate_qr(dpp, qr_path)

        total_generated += 1
        if val["valid"]:
            total_valid += 1

        status = f"{GREEN}VALID{RESET}" if val["valid"] else f"{YELLOW}INCOMPLETE{RESET}"
        warn_str = ""
        if val["warnings"]:
            warn_str = f"  {YELLOW}Warnings: {', '.join(val['warnings'])}{RESET}"

        print(f"\n  [{total_generated}] {BOLD}{row['product_name']}{RESET} ({row['brand']})")
        print(f"      DPP ID:      {dpp['unique_id']}")
        print(f"      Status:      {status} ({val['completeness_pct']}% complete)")
        print(f"      Carbon:      {dpp['sustainability']['carbon_footprint_kg']} kg CO2e")
        print(f"      Recyclable:  {dpp['sustainability']['recyclability_score']}%")
        print(f"      {DIM}JSON → {json_path}{RESET}")
        print(f"      {DIM}QR   → {qr_path}{RESET}")
        if warn_str:
            print(f"    {warn_str}")

    print(f"\n  {BOLD}Summary:{RESET} {total_generated} DPPs generated, "
          f"{total_valid} valid, {total_generated - total_valid} with issues")
    print(f"  {DIM}Output → {DPP_DIR}{RESET}")
    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}\n")


if __name__ == "__main__":
    main()
