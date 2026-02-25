"""
Sportek d.o.o. — TradeFlow AI — Duty & Landed-Cost Calculator
Calculates import duties, VAT and total landed cost for BiH footwear exports.

Usage:
    python modules/02_tradeflow/duty_calculator.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"

# ---------------------------------------------------------------------------
# FTA blocs (from BiH perspective)
# ---------------------------------------------------------------------------
EU_COUNTRIES = {"DE", "FR", "IT", "ES", "NL", "BE", "AT", "PL", "CZ",
                "HR", "SI", "RO", "BG", "SE", "DK"}
CEFTA_COUNTRIES = {"RS", "ME", "MK"}
EFTA_COUNTRIES = {"CH", "NO"}
PARTIAL_FTA = {"TR"}               # 50 % of MFN
MFN_COUNTRIES = {"US", "UK", "CA"}  # full MFN

FTA_MAP: dict[str, tuple[str, float]] = {}
# (fta_name, preferential_multiplier: 0.0 = free, 0.5 = 50% MFN)
for c in EU_COUNTRIES:
    FTA_MAP[c] = ("SAA EU-BiH", 0.0)
for c in CEFTA_COUNTRIES:
    FTA_MAP[c] = ("CEFTA 2006", 0.0)
for c in EFTA_COUNTRIES:
    FTA_MAP[c] = ("EFTA-BiH FTA", 0.0)
for c in PARTIAL_FTA:
    FTA_MAP[c] = ("BiH-Turkey partial FTA", 0.5)
for c in MFN_COUNTRIES:
    FTA_MAP[c] = ("No FTA (MFN)", 1.0)

# ---------------------------------------------------------------------------
# MFN duty rates  (% ad-valorem)   — Chapter 64, realistic values
# Keys: HS-6 code → destination group → rate
# We store per-bloc rates; if a specific country rate differs we override.
# ---------------------------------------------------------------------------
MFN_RATES: dict[str, dict[str, float]] = {
    "640110": {"EU": 17.0, "US": 37.5, "UK": 17.0, "CA": 20.0, "TR": 17.0, "CEFTA": 10.0, "EFTA": 5.6},
    "640299": {"EU": 16.9, "US":  6.0, "UK": 16.9, "CA": 18.0, "TR": 16.9, "CEFTA": 10.0, "EFTA": 5.0},
    "640391": {"EU":  8.0, "US": 20.0, "UK":  8.0, "CA": 18.0, "TR":  8.0, "CEFTA":  5.0, "EFTA": 3.0},
    "640411": {"EU": 16.9, "US": 20.0, "UK": 16.9, "CA": 18.0, "TR": 16.9, "CEFTA": 10.0, "EFTA": 5.0},
    "640419": {"EU": 16.9, "US": 20.0, "UK": 16.9, "CA": 18.0, "TR": 16.9, "CEFTA": 10.0, "EFTA": 5.0},
    "640420": {"EU":  8.0, "US": 20.0, "UK":  8.0, "CA": 18.0, "TR":  8.0, "CEFTA":  5.0, "EFTA": 3.0},
    "640520": {"EU": 16.9, "US": 12.5, "UK": 16.9, "CA": 18.0, "TR": 16.9, "CEFTA": 10.0, "EFTA": 5.0},
    "640610": {"EU":  3.0, "US":  5.3, "UK":  3.0, "CA":  8.0, "TR":  3.0, "CEFTA":  2.0, "EFTA": 1.5},
    "640620": {"EU":  3.0, "US":  3.4, "UK":  3.0, "CA":  8.0, "TR":  3.0, "CEFTA":  2.0, "EFTA": 1.5},
    "640699": {"EU":  7.5, "US":  5.1, "UK":  7.5, "CA": 11.0, "TR":  7.5, "CEFTA":  5.0, "EFTA": 2.5},
}

# ---------------------------------------------------------------------------
# VAT rates  (real, as of 2024-25)
# US: no federal VAT (sales-tax varies by state; 0 for B2B import calc)
# ---------------------------------------------------------------------------
VAT_RATES: dict[str, float] = {
    "DE": 19.0, "FR": 20.0, "IT": 22.0, "ES": 21.0, "NL": 21.0,
    "BE": 21.0, "AT": 20.0, "PL": 23.0, "CZ": 21.0, "HR": 25.0,
    "SI": 22.0, "RO": 19.0, "BG": 20.0, "SE": 25.0, "DK": 25.0,
    "RS": 20.0, "ME": 21.0, "MK": 18.0,
    "CH":  8.1, "NO": 25.0,
    "TR": 20.0,
    "US":  0.0, "UK": 20.0, "CA": 13.0,  # CA: avg HST
}


def _country_bloc(country: str) -> str:
    """Return rate-table key for a country."""
    if country in EU_COUNTRIES:
        return "EU"
    if country in CEFTA_COUNTRIES:
        return "CEFTA"
    if country in EFTA_COUNTRIES:
        return "EFTA"
    return country  # US, UK, CA, TR are keys themselves


class DutyCalculator:
    """Calculate import duty, VAT and landed cost for BiH footwear exports."""

    def calculate(
        self,
        hs_code: str,
        destination_country: str,
        value_eur: float,
    ) -> dict:
        """Return full duty breakdown for one shipment."""
        hs_code = str(hs_code).zfill(6)
        destination_country = destination_country.upper()

        # MFN rate
        bloc = _country_bloc(destination_country)
        code_rates = MFN_RATES.get(hs_code)
        if code_rates is None:
            raise ValueError(f"HS code {hs_code} not in rate table. "
                             f"Known codes: {sorted(MFN_RATES)}")
        mfn_rate = code_rates.get(bloc)
        if mfn_rate is None:
            raise ValueError(f"No MFN rate for bloc '{bloc}' on HS {hs_code}")

        # FTA / preferential
        fta_name, multiplier = FTA_MAP.get(destination_country, ("No FTA (MFN)", 1.0))
        pref_rate = round(mfn_rate * multiplier, 2)
        duty_eur = round(value_eur * pref_rate / 100, 2)
        savings_vs_mfn = round(value_eur * mfn_rate / 100 - duty_eur, 2)

        # VAT
        vat_rate = VAT_RATES.get(destination_country, 0.0)
        # VAT base = value + duty (standard EU import VAT basis)
        vat_base = value_eur + duty_eur
        vat_eur = round(vat_base * vat_rate / 100, 2)

        total_landed = round(value_eur + duty_eur + vat_eur, 2)

        return {
            "hs_code": hs_code,
            "destination": destination_country,
            "value_eur": value_eur,
            "mfn_rate_pct": mfn_rate,
            "preferential_rate_pct": pref_rate,
            "fta": fta_name,
            "duty_eur": duty_eur,
            "vat_rate_pct": vat_rate,
            "vat_eur": vat_eur,
            "total_landed_cost_eur": total_landed,
            "savings_vs_mfn_eur": savings_vs_mfn,
        }

    def calculate_batch(
        self,
        items: list[dict],
    ) -> list[dict]:
        """Calculate for a list of dicts with keys hs_code, destination, value_eur."""
        return [
            self.calculate(it["hs_code"], it["destination"], it["value_eur"])
            for it in items
        ]


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

    calc = DutyCalculator()

    print()
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK TradeFlow — Duty & Landed-Cost Calculator{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")

    # Demo scenarios
    scenarios = [
        {"hs_code": "640411", "destination": "DE", "value_eur": 50_000,
         "label": "Sports shoes → Germany (EU, SAA preferential)"},
        {"hs_code": "640411", "destination": "US", "value_eur": 50_000,
         "label": "Sports shoes → USA (no FTA, full MFN)"},
        {"hs_code": "640610", "destination": "RS", "value_eur": 20_000,
         "label": "Shoe uppers → Serbia (CEFTA, preferential)"},
    ]

    for i, sc in enumerate(scenarios, 1):
        r = calc.calculate(sc["hs_code"], sc["destination"], sc["value_eur"])

        print(f"\n  {BOLD}[{i}] {sc['label']}{RESET}")
        print(f"      HS code:           {r['hs_code']}")
        print(f"      Destination:       {r['destination']}")
        print(f"      Shipment value:    {r['value_eur']:>10,.2f} EUR")
        print(f"      MFN rate:          {r['mfn_rate_pct']:>10.1f}%")

        if r["preferential_rate_pct"] < r["mfn_rate_pct"]:
            print(f"      Preferential rate: {GREEN}{r['preferential_rate_pct']:>10.1f}%{RESET}"
                  f"  ({r['fta']})")
        else:
            print(f"      Applied rate:      {YELLOW}{r['preferential_rate_pct']:>10.1f}%{RESET}"
                  f"  ({r['fta']})")

        print(f"      Duty payable:      {r['duty_eur']:>10,.2f} EUR")
        print(f"      VAT ({r['vat_rate_pct']}%):       {r['vat_eur']:>10,.2f} EUR")
        print(f"      {BOLD}Total landed cost: {r['total_landed_cost_eur']:>10,.2f} EUR{RESET}")

        if r["savings_vs_mfn_eur"] > 0:
            print(f"      {GREEN}FTA savings:       {r['savings_vs_mfn_eur']:>10,.2f} EUR{RESET}")

    # Save all results
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    all_results = [calc.calculate(s["hs_code"], s["destination"], s["value_eur"])
                   for s in scenarios]
    out_path = RESULT_DIR / "duty_calculations.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\n  {DIM}Saved → {out_path}{RESET}")

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}\n")


if __name__ == "__main__":
    main()
