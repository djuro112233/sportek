import csv
import os
import random
from datetime import date, timedelta

random.seed(42)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "compliance")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# DIO 1 — products_dpp.csv  (200 redova)
# ---------------------------------------------------------------------------

TEMPLATES = [
    {
        "product_name": "Air Max Flyknit Upper Assembly",
        "brand": "Nike",
        "hs_code_6digit": "640411",
        "hs_code_10digit": "6404110090",
        "materials_composition": "upper: polyester 55% elastane 30% nylon 15%",
        "weight_grams": 280,
        "carbon_footprint_kg": 8.5,
        "recyclability_score": 72,
        "hazardous_substances": "REACH compliant; no SVHC detected",
        "factory_id": "NKE-VN-",
    },
    {
        "product_name": "Pegasus 3D Knit Collar",
        "brand": "Nike",
        "hs_code_6digit": "640411",
        "hs_code_10digit": "6404110090",
        "materials_composition": "recycled polyester 70% elastane 30%",
        "weight_grams": 65,
        "carbon_footprint_kg": 3.2,
        "recyclability_score": 88,
        "hazardous_substances": "REACH compliant; no SVHC detected",
        "factory_id": "NKE-CN-",
    },
    {
        "product_name": "Classic Clog Strap Assembly",
        "brand": "Crocs",
        "hs_code_6digit": "640299",
        "hs_code_10digit": "6402990500",
        "materials_composition": "croslite 100%",
        "weight_grams": 45,
        "carbon_footprint_kg": 2.1,
        "recyclability_score": 65,
        "hazardous_substances": "phthalate-free; REACH compliant",
        "factory_id": "CRC-VN-",
    },
    {
        "product_name": "Kalenji Trail Sole Unit",
        "brand": "Decathlon",
        "hs_code_6digit": "640520",
        "hs_code_10digit": "6405201000",
        "materials_composition": "rubber 70% EVA 30%",
        "weight_grams": 320,
        "carbon_footprint_kg": 9.8,
        "recyclability_score": 55,
        "hazardous_substances": "PAH below EU limit; REACH compliant",
        "factory_id": "DCT-BD-",
    },
    {
        "product_name": "ZoomX Carbon Plate Insert",
        "brand": "Nike",
        "hs_code_6digit": "640411",
        "hs_code_10digit": "6404110090",
        "materials_composition": "carbon fiber 100%",
        "weight_grams": 42,
        "carbon_footprint_kg": 12.5,
        "recyclability_score": 30,
        "hazardous_substances": "epoxy resin traces; REACH compliant",
        "factory_id": "NKE-TW-",
    },
]

START_DATE = date(2025, 3, 1)
END_DATE = date(2026, 2, 28)
DATE_RANGE_DAYS = (END_DATE - START_DATE).days

products_path = os.path.join(OUTPUT_DIR, "products_dpp.csv")
PRODUCT_HEADER = [
    "product_id", "product_name", "brand", "hs_code_6digit", "hs_code_10digit",
    "country_origin", "materials_composition", "weight_grams", "carbon_footprint_kg",
    "recyclability_score", "hazardous_substances", "factory_id", "production_date",
    "batch_number",
]

ORIGIN_COUNTRIES = ["VN", "CN", "BD", "ID", "TW", "KH", "IN"]

with open(products_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=PRODUCT_HEADER)
    writer.writeheader()

    for i in range(200):
        tpl = TEMPLATES[i % len(TEMPLATES)]
        variant = (i // len(TEMPLATES)) + 1
        prod_date = START_DATE + timedelta(days=random.randint(0, DATE_RANGE_DAYS))
        origin = random.choice(ORIGIN_COUNTRIES)
        factory_num = random.randint(1, 20)
        weight_var = tpl["weight_grams"] + random.randint(-10, 10)
        carbon_var = round(tpl["carbon_footprint_kg"] + random.uniform(-1.0, 1.0), 2)
        recycle_var = max(0, min(100, tpl["recyclability_score"] + random.randint(-5, 5)))

        row = {
            "product_id": f"PROD-{i+1:04d}",
            "product_name": f"{tpl['product_name']} v{variant}",
            "brand": tpl["brand"],
            "hs_code_6digit": tpl["hs_code_6digit"],
            "hs_code_10digit": tpl["hs_code_10digit"],
            "country_origin": origin,
            "materials_composition": tpl["materials_composition"],
            "weight_grams": weight_var,
            "carbon_footprint_kg": carbon_var,
            "recyclability_score": recycle_var,
            "hazardous_substances": tpl["hazardous_substances"],
            "factory_id": f"{tpl['factory_id']}{factory_num:03d}",
            "production_date": prod_date.isoformat(),
            "batch_number": f"B{prod_date.strftime('%Y%m')}-{random.randint(1000,9999)}",
        }
        writer.writerow(row)

print(f"products_dpp.csv: {200} redova zapisano -> {products_path}")

# ---------------------------------------------------------------------------
# DIO 2 — hs_classifications.csv  (300 redova)
# ---------------------------------------------------------------------------

HS_CODES = {
    "640411": "Footwear with outer soles of rubber/plastics, uppers of textile, sports",
    "640419": "Footwear with outer soles of rubber/plastics, uppers of textile, other",
    "640299": "Footwear with outer soles and uppers of rubber/plastics, other",
    "640110": "Waterproof footwear with rubber/plastic soles and uppers",
    "640391": "Footwear with outer soles of rubber/plastics, uppers of leather, ankle-covering",
    "640610": "Uppers and parts thereof, other than stiffeners",
    "640620": "Outer soles and heels, of rubber or plastics",
    "640699": "Parts of footwear, other",
    "640520": "Footwear with uppers of textile, other",
    "640420": "Footwear with outer soles of leather, uppers of textile",
}

COUNTRIES = [
    "DE", "FR", "IT", "ES", "NL", "BE", "AT", "PL", "CZ", "HR",
    "SI", "RO", "BG", "SE", "DK",  # EU
    "US", "UK", "CA",               # MFN full duty
    "CH", "NO",                      # EFTA
    "TR",                            # Turkey
    "RS", "ME", "MK",               # CEFTA
]

EU_COUNTRIES = {"DE", "FR", "IT", "ES", "NL", "BE", "AT", "PL", "CZ", "HR",
                "SI", "RO", "BG", "SE", "DK"}
EFTA_COUNTRIES = {"CH", "NO"}
CEFTA_COUNTRIES = {"RS", "ME", "MK"}

MFN_RATES = {
    "640411": 16.9, "640419": 16.9, "640299": 16.9, "640110": 17.0,
    "640391": 8.0, "640610": 7.5, "640620": 7.5, "640699": 7.5,
    "640520": 16.9, "640420": 8.0,
}

US_RATES = {
    "640411": 20.0, "640419": 20.0, "640299": 6.0, "640110": 37.5,
    "640391": 10.0, "640610": 5.1, "640620": 3.4, "640699": 5.3,
    "640520": 12.5, "640420": 10.0,
}

hs_path = os.path.join(OUTPUT_DIR, "hs_classifications.csv")
HS_HEADER = [
    "product_description", "correct_hs_code", "country_destination",
    "duty_rate_percent", "preferential_rate", "fta_applicable",
    "special_requirements",
]

with open(hs_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=HS_HEADER)
    writer.writeheader()

    hs_list = list(HS_CODES.keys())

    for i in range(300):
        hs = hs_list[i % len(hs_list)]
        country = COUNTRIES[i % len(COUNTRIES)]
        mfn = MFN_RATES[hs]

        if country in EU_COUNTRIES:
            pref = 0.0
            fta = "SAA BiH-EU"
            special = "CE marking; REACH; EU DPP 2027+"
            duty = mfn
        elif country in CEFTA_COUNTRIES:
            pref = 0.0
            fta = "CEFTA"
            special = "Certificate of origin EUR.1"
            duty = mfn
        elif country in EFTA_COUNTRIES:
            pref = 0.0
            fta = "EFTA-BiH FTA"
            special = "EUR.1 certificate; Swiss/Norwegian import declaration"
            duty = mfn
        elif country == "TR":
            pref = round(mfn * 0.5, 1)
            fta = "Turkey-BiH FTA"
            special = "ATR certificate; Turkish customs declaration"
            duty = mfn
        elif country == "US":
            duty = US_RATES[hs]
            pref = duty  # full MFN, no preference
            fta = "None"
            special = "FDA; CPSIA"
        elif country == "UK":
            duty = mfn
            pref = duty
            fta = "None"
            special = "UKCA marking; UK REACH"
        elif country == "CA":
            duty = round(mfn * 0.9, 1)
            pref = duty
            fta = "None"
            special = "Canada Consumer Product Safety Act"
        else:
            duty = mfn
            pref = mfn
            fta = "None"
            special = ""

        desc_variant = random.choice([
            HS_CODES[hs],
            f"{HS_CODES[hs]} — {random.choice(['men', 'women', 'children', 'unisex'])}",
        ])

        row = {
            "product_description": desc_variant,
            "correct_hs_code": hs,
            "country_destination": country,
            "duty_rate_percent": duty,
            "preferential_rate": pref,
            "fta_applicable": fta,
            "special_requirements": special,
        }
        writer.writerow(row)

print(f"hs_classifications.csv: {300} redova zapisano -> {hs_path}")

# ---------------------------------------------------------------------------
# Verifikacija
# ---------------------------------------------------------------------------
for fname in ["products_dpp.csv", "hs_classifications.csv"]:
    fpath = os.path.join(OUTPUT_DIR, fname)
    with open(fpath, encoding="utf-8") as f:
        reader = csv.reader(f)
        count = sum(1 for _ in reader) - 1  # minus header
    print(f"  VERIFY {fname}: {count} redova")
