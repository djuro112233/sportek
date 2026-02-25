"""
Sportek d.o.o. — Brand Reporting — Analytics & Visualizations
4 charts: Nike SMSI radar, KPI dashboard grid, brand comparison, report timeline.

Usage:
    python -m modules.06_brand_reporting.analytics
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from .templates import NikeScorecard, CrocsReport, DecathlonReport
from .kpi_tracker import KPITracker

MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ── Colours ────────────────────────────────────────────────────────────────
NAVY = "#1B2A4A"
TEAL = "#0891B2"
TEAL_LIGHT = "#22d3ee"
ORANGE = "#f97316"
GREEN_C = "#22c55e"
RED_C = "#ef4444"
YELLOW_C = "#eab308"
WHITE = "#f8fafc"
GREY = "#94a3b8"
BRAND_COLORS = {"Nike": "#0891B2", "Crocs": "#22d3ee", "Decathlon": "#f97316"}

plt.rcParams.update({
    "figure.facecolor": NAVY,
    "axes.facecolor": NAVY,
    "axes.edgecolor": WHITE,
    "axes.labelcolor": WHITE,
    "xtick.color": WHITE,
    "ytick.color": WHITE,
    "text.color": WHITE,
    "font.size": 11,
    "figure.dpi": 150,
})


def _save(fig, name):
    fig.savefig(RESULT_DIR / name, bbox_inches="tight")
    plt.close(fig)


# ── 1. Nike SMSI Radar ────────────────────────────────────────────────────
def chart_nike_smsi_radar(nike_report: dict) -> None:
    categories = ["Quality", "Delivery", "Sustainability", "Innovation"]
    current = [
        nike_report["quality"]["score"],
        nike_report["delivery"]["score"],
        nike_report["sustainability"]["score"],
        nike_report["innovation"]["score"],
    ]
    targets = [85, 90, 75, 70]

    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]
    current += current[:1]
    targets += targets[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    ax.set_facecolor(NAVY)
    fig.patch.set_facecolor(NAVY)

    # Target polygon
    ax.fill(angles, targets, alpha=0.15, color=GREEN_C)
    ax.plot(angles, targets, color=GREEN_C, linewidth=2, linestyle="--",
            label="Target", marker="o", markersize=6)

    # Current polygon
    ax.fill(angles, current, alpha=0.25, color=TEAL)
    ax.plot(angles, current, color=TEAL, linewidth=2.5,
            label=f"Current (SMSI: {nike_report['smsi_score']})", marker="o", markersize=7)

    # Axis labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=12, fontweight="bold", color=WHITE)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=8, color=GREY)
    ax.spines["polar"].set_color(GREY)
    ax.grid(color=GREY, alpha=0.3)

    # Score annotations
    for i in range(N):
        angle = angles[i]
        ax.annotate(f"{current[i]:.0f}", xy=(angle, current[i]),
                    fontsize=10, fontweight="bold", color=TEAL_LIGHT,
                    ha="center", va="bottom", textcoords="offset points",
                    xytext=(0, 10))

    ax.set_title(f"Nike SMSI Scorecard — {nike_report['period']}\n"
                 f"Grade: {nike_report['overall_grade']} | Trend: {nike_report['trend']}",
                 fontweight="bold", color=TEAL, pad=25, fontsize=13)
    ax.legend(loc="lower right", bbox_to_anchor=(1.25, -0.05),
              facecolor=NAVY, edgecolor=GREY, fontsize=10)
    _save(fig, "nike_smsi_radar.png")


# ── 2. KPI Dashboard Grid ─────────────────────────────────────────────────
def chart_kpi_dashboard(kpis: dict) -> None:
    n_kpis = len(kpis)
    cols = 5
    rows = 4

    fig, axes = plt.subplots(rows, cols, figsize=(18, 12))
    fig.suptitle("KPI Dashboard — 20 Key Performance Indicators",
                 fontweight="bold", color=TEAL, fontsize=16, y=0.98)

    status_colors = {"green": GREEN_C, "yellow": YELLOW_C, "red": RED_C}
    trend_arrows = {"up": "\u2191", "down": "\u2193", "stable": "\u2192"}

    kpi_list = list(kpis.items())
    for idx in range(rows * cols):
        r, c = divmod(idx, cols)
        ax = axes[r][c]
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xticks([])
        ax.set_yticks([])

        if idx < n_kpis:
            kpi_id, info = kpi_list[idx]
            sc = status_colors.get(info["status"], GREY)
            arrow = trend_arrows.get(info["trend"], "")

            # Background indicator strip
            ax.axhspan(0, 0.08, color=sc, alpha=0.9)

            # KPI number
            ax.text(0.05, 0.88, f"#{idx+1}", fontsize=8, color=GREY,
                    fontweight="bold", transform=ax.transAxes)

            # Name (wrapped)
            name = info["name"]
            if len(name) > 22:
                mid = name[:22].rfind(" ")
                if mid > 0:
                    name = name[:mid] + "\n" + name[mid+1:]
            ax.text(0.5, 0.72, name, fontsize=9, color=WHITE,
                    ha="center", va="center", transform=ax.transAxes,
                    fontweight="bold")

            # Value
            val = info["value"]
            if "rate" in kpi_id:
                val_str = f"{val:.2%}"
            elif kpi_id in ("on_time_delivery", "oee_average", "first_pass_yield",
                            "smsi_score", "downtime_pct"):
                val_str = f"{val:.1f}"
            elif kpi_id == "inventory_turnover":
                val_str = f"{val:.1f}x"
            elif kpi_id in ("energy_per_unit_kwh", "supplier_quality_score"):
                val_str = f"{val:.2f}"
            else:
                val_str = str(val)

            ax.text(0.5, 0.42, val_str, fontsize=18, color=sc,
                    ha="center", va="center", transform=ax.transAxes,
                    fontweight="bold")

            # Trend arrow
            ax.text(0.9, 0.42, arrow, fontsize=16, color=WHITE,
                    ha="center", va="center", transform=ax.transAxes)

            # Status label
            ax.text(0.5, 0.15, info["status"].upper(), fontsize=9, color=sc,
                    ha="center", va="center", transform=ax.transAxes,
                    fontweight="bold")

            for spine in ax.spines.values():
                spine.set_color(GREY)
                spine.set_linewidth(0.5)
        else:
            ax.set_visible(False)

    fig.subplots_adjust(hspace=0.35, wspace=0.25)
    _save(fig, "kpi_dashboard.png")


# ── 3. Brand Comparison — grouped bar ─────────────────────────────────────
def chart_brand_comparison(nike: dict, crocs: dict, decathlon: dict) -> None:
    brands = ["Nike", "Crocs", "Decathlon"]
    colors = [BRAND_COLORS[b] for b in brands]

    # Metrics: defect rate, OTD, FPY, output (thousands)
    defect_rates = [
        nike["quality"]["defect_rate"] * 100,
        crocs["quality"]["defect_rate"] * 100,
        decathlon["quality"]["defect_rate"] * 100,
    ]
    # OTD: Nike has it in delivery, Crocs too, Decathlon proxy from production efficiency
    otd = [
        nike["delivery"]["on_time_delivery_pct"],
        crocs["delivery"]["otd_pct"],
        decathlon["production"]["efficiency"],
    ]
    fpy = [
        (1 - nike["quality"]["defect_rate"]) * 100,
        crocs["quality"]["fpy"] * 100,
        (1 - decathlon["quality"]["defect_rate"]) * 100,
    ]
    output_k = [
        sum(m["units"] for m in crocs["production"]["top_models"]) / 1000 if "top_models" in crocs.get("production", {}) else 0,
        crocs["production"]["total_units"] / 1000,
        decathlon["production"]["total_units"] / 1000,
    ]
    # For Nike output — derive from production data
    from .templates import PROD_CSV, _filter_period
    prod = pd.read_csv(PROD_CSV, parse_dates=["date"])
    nike_prod = _filter_period(prod[prod["brand"] == "Nike"], nike["period"])
    output_k[0] = nike_prod["actual_qty"].sum() / 1000

    metrics = ["Defect Rate (%)", "On-Time / Efficiency (%)", "First Pass Yield (%)", "Output (k units)"]
    data = [defect_rates, otd, fpy, output_k]

    fig, axes = plt.subplots(1, 4, figsize=(18, 6))
    fig.suptitle(f"Brand Comparison — {nike['period']}", fontweight="bold",
                 color=TEAL, fontsize=15, y=1.02)

    for i, (ax, metric, vals) in enumerate(zip(axes, metrics, data)):
        x = np.arange(len(brands))
        bars = ax.bar(x, vals, color=colors, width=0.6, edgecolor=NAVY)

        # Value labels
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(vals) * 0.02,
                    f"{val:.1f}", ha="center", va="bottom", fontsize=10,
                    fontweight="bold", color=WHITE)

        ax.set_xticks(x)
        ax.set_xticklabels(brands, fontsize=10)
        ax.set_title(metric, fontweight="bold", color=WHITE, fontsize=11)
        ax.set_ylim(0, max(vals) * 1.2 if max(vals) > 0 else 10)

        # Target lines for first 3 metrics
        if i == 0:
            ax.axhline(3.0, color=RED_C, linestyle="--", linewidth=1, alpha=0.7)
            ax.text(2.5, 3.2, "Target <3%", fontsize=8, color=RED_C)
        elif i == 1:
            ax.axhline(95.0, color=GREEN_C, linestyle="--", linewidth=1, alpha=0.7)
            ax.text(2.2, 95.5, "Target >95%", fontsize=8, color=GREEN_C)
        elif i == 2:
            ax.axhline(95.0, color=GREEN_C, linestyle="--", linewidth=1, alpha=0.7)
            ax.text(2.2, 95.5, "Target >95%", fontsize=8, color=GREEN_C)

    legend_patches = [mpatches.Patch(color=c, label=b) for b, c in zip(brands, colors)]
    fig.legend(handles=legend_patches, loc="lower center", ncol=3,
               facecolor=NAVY, edgecolor=GREY, fontsize=10,
               bbox_to_anchor=(0.5, -0.05))
    fig.subplots_adjust(wspace=0.35)
    _save(fig, "brand_comparison.png")


# ── 4. Report Timeline ────────────────────────────────────────────────────
def chart_report_timeline() -> None:
    now = datetime.now()
    brands = ["Nike", "Crocs", "Decathlon"]
    report_types = ["SMSI Scorecard", "Performance Report", "Sustainability Report"]
    colors = [BRAND_COLORS[b] for b in brands]

    # Quarterly schedule: Q1-Q4 for current year
    quarters = []
    year = now.year
    for q in range(1, 5):
        q_start = datetime(year, (q - 1) * 3 + 1, 1)
        q_end = datetime(year, q * 3, 28)
        q_due = q_end + timedelta(days=15)  # Due 15 days after quarter end
        label = f"{year}-Q{q}"
        quarters.append((label, q_start, q_end, q_due))

    fig, ax = plt.subplots(figsize=(16, 7))

    y_positions = []
    y_labels = []
    y_idx = 0

    for bi, (brand, report_type) in enumerate(zip(brands, report_types)):
        for qi, (q_label, q_start, q_end, q_due) in enumerate(quarters):
            y = y_idx
            y_positions.append(y)
            y_labels.append(f"{brand} {q_label}")

            # Period bar (data collection window)
            width_days = (q_end - q_start).days
            ax.barh(y, width_days, left=q_start, height=0.5,
                    color=colors[bi], alpha=0.4, edgecolor=NAVY)

            # Due date marker
            ax.plot(q_due, y, marker="d", color=colors[bi], markersize=10, zorder=5)

            # Generated marker (past quarters)
            if q_due < now:
                gen_date = q_due - timedelta(days=5)
                ax.plot(gen_date, y, marker="*", color=GREEN_C, markersize=14, zorder=6)
                ax.annotate("Done", xy=(gen_date, y), fontsize=7, color=GREEN_C,
                            ha="center", va="bottom", textcoords="offset points",
                            xytext=(0, 8))
            elif q_start <= now <= q_due:
                ax.annotate("In Progress", xy=(now, y), fontsize=7, color=YELLOW_C,
                            ha="center", va="bottom", textcoords="offset points",
                            xytext=(0, 8))

            y_idx += 1

        # Brand separator
        if bi < len(brands) - 1:
            ax.axhline(y_idx - 0.5, color=GREY, linestyle=":", linewidth=0.5, alpha=0.5)

    # Today line
    ax.axvline(now, color=RED_C, linestyle="--", linewidth=1.5, alpha=0.8, label="Today")

    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_title("Report Timeline — Generation Schedule", fontweight="bold",
                 color=TEAL, fontsize=14)
    ax.set_xlabel("Date")

    # Legend
    legend_elements = [
        mpatches.Patch(color=TEAL, alpha=0.4, label="Data Collection Period"),
        plt.Line2D([0], [0], marker="d", color=TEAL, markersize=8,
                   linestyle="None", label="Due Date"),
        plt.Line2D([0], [0], marker="*", color=GREEN_C, markersize=12,
                   linestyle="None", label="Generated"),
        plt.Line2D([0], [0], color=RED_C, linestyle="--", label="Today"),
    ]
    ax.legend(handles=legend_elements, loc="lower right",
              facecolor=NAVY, edgecolor=GREY, fontsize=9)
    _save(fig, "report_timeline.png")


# ── Dashboard JSON ─────────────────────────────────────────────────────────
def generate_dashboard_json(nike: dict, crocs: dict, decathlon: dict,
                            kpis: dict, alerts: list) -> dict:
    dashboard = {
        "generated_at": datetime.now().isoformat(),
        "period": nike["period"],
        "brands": {
            "Nike": {
                "smsi_score": nike["smsi_score"],
                "grade": nike["overall_grade"],
                "trend": nike["trend"],
                "quality_score": nike["quality"]["score"],
                "delivery_score": nike["delivery"]["score"],
                "sustainability_score": nike["sustainability"]["score"],
                "innovation_score": nike["innovation"]["score"],
                "defect_rate": nike["quality"]["defect_rate"],
                "otd_pct": nike["delivery"]["on_time_delivery_pct"],
            },
            "Crocs": {
                "total_units": crocs["production"]["total_units"],
                "fpy": crocs["quality"]["fpy"],
                "defect_rate": crocs["quality"]["defect_rate"],
                "aql_status": crocs["quality"]["aql_status"],
                "otd_pct": crocs["delivery"]["otd_pct"],
                "croslite_stock_days": crocs["inventory"]["croslite_stock_days"],
            },
            "Decathlon": {
                "total_units": decathlon["production"]["total_units"],
                "efficiency": decathlon["production"]["efficiency"],
                "defect_rate": decathlon["quality"]["defect_rate"],
                "customer_satisfaction": decathlon["quality"]["customer_satisfaction"],
                "carbon_per_unit": decathlon["sustainability"]["per_unit"],
                "safety_incidents": decathlon["social"]["safety_incidents"],
            },
        },
        "kpi_summary": {
            "total": len(kpis),
            "green": sum(1 for k in kpis.values() if k["status"] == "green"),
            "yellow": sum(1 for k in kpis.values() if k["status"] == "yellow"),
            "red": sum(1 for k in kpis.values() if k["status"] == "red"),
        },
        "alerts": alerts,
        "charts": [
            "nike_smsi_radar.png",
            "kpi_dashboard.png",
            "brand_comparison.png",
            "report_timeline.png",
        ],
    }

    with open(RESULT_DIR / "reporting_analytics.json", "w") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False, default=str)

    return dashboard


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    BOLD = "\033[1m"
    CYAN_T = "\033[96m"
    GREEN_T = "\033[92m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN_T}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN_T}  SPORTEK — Brand Reporting — Analytics & Visualizations{RESET}")
    print(f"{BOLD}{CYAN_T}{'=' * 70}{RESET}\n")

    period = "2025-Q4"

    # Generate reports
    nike = NikeScorecard().generate(period)
    crocs = CrocsReport().generate(period)
    decathlon = DecathlonReport().generate(period)

    # KPIs
    tracker = KPITracker()
    kpis = tracker.calculate_all()
    alerts = tracker.get_alerts()

    print("  Generišem grafove...\n")

    chart_nike_smsi_radar(nike)
    print(f"    {GREEN_T}1. nike_smsi_radar.png{RESET}")

    chart_kpi_dashboard(kpis)
    print(f"    {GREEN_T}2. kpi_dashboard.png{RESET}")

    chart_brand_comparison(nike, crocs, decathlon)
    print(f"    {GREEN_T}3. brand_comparison.png{RESET}")

    chart_report_timeline()
    print(f"    {GREEN_T}4. report_timeline.png{RESET}")

    # Dashboard JSON
    dashboard = generate_dashboard_json(nike, crocs, decathlon, kpis, alerts)

    print(f"\n  {BOLD}Summary:{RESET}")
    ks = dashboard["kpi_summary"]
    print(f"    KPIs: {GREEN_T}{ks['green']} green{RESET} / "
          f"\033[93m{ks['yellow']} yellow{RESET} / "
          f"\033[91m{ks['red']} red{RESET}")
    print(f"    Grafova generisano: {GREEN_T}4{RESET}")

    print(f"\n  {DIM}Saved → {RESULT_DIR}/{RESET}")
    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()
