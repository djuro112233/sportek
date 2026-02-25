"""
Sportek d.o.o. — Brand Reporting — Report Generator
Orchestrates report generation for all 3 brands + email drafts.

Usage:
    python -m modules.06_brand_reporting.generator
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .templates import NikeScorecard, CrocsReport, DecathlonReport

MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"
REPORT_DIR = RESULT_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


class ReportGenerator:
    """Generate and save brand reports."""

    def __init__(self) -> None:
        self.nike_tpl = NikeScorecard()
        self.crocs_tpl = CrocsReport()
        self.decathlon_tpl = DecathlonReport()

    # ── Individual generators ─────────────────────────────────────────

    def generate_nike_scorecard(self, period: str = "2025-Q4") -> dict:
        report = self.nike_tpl.generate(period)
        qtr = period.split("-")[1]
        year = period.split("-")[0]
        filename = f"Nike_SMSI_{qtr}_{year}.json"
        with open(REPORT_DIR / filename, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return report

    def generate_crocs_report(self, period: str = "2025-Q4") -> dict:
        report = self.crocs_tpl.generate(period)
        qtr = period.split("-")[1]
        year = period.split("-")[0]
        filename = f"Crocs_Performance_{qtr}_{year}.json"
        with open(REPORT_DIR / filename, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return report

    def generate_decathlon_report(self, period: str = "2025-Q4") -> dict:
        report = self.decathlon_tpl.generate(period)
        qtr = period.split("-")[1]
        year = period.split("-")[0]
        filename = f"Decathlon_Sustainability_{qtr}_{year}.json"
        with open(REPORT_DIR / filename, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return report

    # ── All at once ───────────────────────────────────────────────────

    def generate_all(self, period: str = "2025-Q4") -> dict:
        return {
            "nike": self.generate_nike_scorecard(period),
            "crocs": self.generate_crocs_report(period),
            "decathlon": self.generate_decathlon_report(period),
        }

    # ── Email draft ───────────────────────────────────────────────────

    def create_email_draft(self, brand: str, period: str = "2025-Q4") -> dict:
        qtr = period.split("-")[1]
        year = period.split("-")[0]

        if brand == "Nike":
            report = self.nike_tpl.generate(period)
            subject = f"Sportek — Nike SMSI Scorecard {qtr} {year}"
            attachment = f"Nike_SMSI_{qtr}_{year}.json"
            body = (
                f"Dear Nike Quality Team,\n\n"
                f"Please find attached the Sportek SMSI Scorecard for {period}.\n\n"
                f"Highlights:\n"
                f"  - SMSI Score: {report['smsi_score']}\n"
                f"  - Overall Grade: {report['overall_grade']}\n"
                f"  - Quality Score: {report['quality']['score']} (defect rate: {report['quality']['defect_rate']:.2%})\n"
                f"  - On-Time Delivery: {report['delivery']['on_time_delivery_pct']}%\n"
                f"  - Carbon per pair: {report['sustainability']['carbon_per_pair_kg']} kg\n"
                f"  - Trend: {report['trend']}\n\n"
                f"Best regards,\n"
                f"Sportek d.o.o. — Quality & Compliance Team"
            )

        elif brand == "Crocs":
            report = self.crocs_tpl.generate(period)
            subject = f"Sportek — Crocs Performance Report {qtr} {year}"
            attachment = f"Crocs_Performance_{qtr}_{year}.json"
            body = (
                f"Dear Crocs Operations Team,\n\n"
                f"Quarterly performance report for {period}:\n\n"
                f"  - Total units produced: {report['production']['total_units']:,}\n"
                f"  - First Pass Yield: {report['quality']['fpy']:.2%}\n"
                f"  - AQL Status: {report['quality']['aql_status'].upper()}\n"
                f"  - On-Time Delivery: {report['delivery']['otd_pct']}%\n"
                f"  - Croslite stock: {report['inventory']['croslite_stock_days']} days\n\n"
                f"Best regards,\n"
                f"Sportek d.o.o. — Production Management"
            )

        elif brand == "Decathlon":
            report = self.decathlon_tpl.generate(period)
            subject = f"Sportek — Decathlon Sustainability Report {qtr} {year}"
            attachment = f"Decathlon_Sustainability_{qtr}_{year}.json"
            body = (
                f"Dear Decathlon Sustainability Team,\n\n"
                f"Sustainability & performance report for {period}:\n\n"
                f"  - Carbon footprint: {report['sustainability']['carbon_footprint_total']} kg total "
                f"({report['sustainability']['per_unit']} kg/unit)\n"
                f"  - Recycled content: {report['sustainability']['recycled_content_pct']}%\n"
                f"  - Waste: {report['sustainability']['waste_kg']} kg\n"
                f"  - Production efficiency: {report['production']['efficiency']}%\n"
                f"  - Safety incidents: {report['social']['safety_incidents']}\n\n"
                f"Best regards,\n"
                f"Sportek d.o.o. — Sustainability Office"
            )
        else:
            raise ValueError(f"Unknown brand: {brand}")

        return {
            "to": f"{brand.lower()}-team@{brand.lower()}.com",
            "subject": subject,
            "body": body,
            "attachments": [attachment],
        }


# ── Main ──────────────────────────────────────────────────────────────────
def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK — Brand Reporting — Report Generator{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}\n")

    gen = ReportGenerator()
    period = "2025-Q4"

    print(f"  Generating reports for {period}...\n")
    reports = gen.generate_all(period)

    nike = reports["nike"]
    print(f"  {GREEN}1. Nike SMSI Scorecard{RESET}")
    print(f"     SMSI Score: {nike['smsi_score']}  Grade: {nike['overall_grade']}")

    crocs = reports["crocs"]
    print(f"  {GREEN}2. Crocs Performance Report{RESET}")
    print(f"     Units: {crocs['production']['total_units']:,}  FPY: {crocs['quality']['fpy']:.2%}")

    deca = reports["decathlon"]
    print(f"  {GREEN}3. Decathlon Sustainability Report{RESET}")
    print(f"     Carbon/unit: {deca['sustainability']['per_unit']} kg  Efficiency: {deca['production']['efficiency']}%")

    # Email drafts
    print(f"\n  {BOLD}Email Drafts:{RESET}")
    for brand in ("Nike", "Crocs", "Decathlon"):
        draft = gen.create_email_draft(brand, period)
        print(f"    {brand}: {draft['subject']}")

    print(f"\n  {DIM}Reports saved → {REPORT_DIR}/{RESET}")
    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()
