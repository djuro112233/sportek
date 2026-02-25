"""
Sportek d.o.o. — OEE Dashboard — Visualizations
7 charts: OEE overview, trend, losses waterfall, heatmap, Gantt, predictions, anomalies.

Usage:
    python -m modules.05_oee_dashboard.visualizations
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from .oee_calculator import OEECalculator
from .scheduler import ProductionScheduler, DEMO_ORDERS
from .predictive import _prepare_data, train_downtime_predictor, train_anomaly_detector

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


# ── 1. OEE Overview — stacked bar ─────────────────────────────────────────
def chart_oee_overview(calc: OEECalculator) -> None:
    bench = calc.benchmark()
    lines = [b["line_id"] for b in bench]
    avail = [b["availability"] for b in bench]
    perf = [b["performance"] for b in bench]
    qual = [b["quality"] for b in bench]

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(lines))
    w = 0.6

    ax.bar(x, avail, w, label="Availability", color=TEAL)
    ax.bar(x, perf, w, bottom=avail, label="Performance", color=ORANGE)
    ax.bar(x, qual, w, bottom=[a + p for a, p in zip(avail, perf)], label="Quality", color=GREEN_C)
    ax.axhline(0.85, color=RED_C, linestyle="--", linewidth=1.5, label="World-class 85%")

    ax.set_xticks(x)
    ax.set_xticklabels(lines)
    ax.set_ylabel("Score (stacked A+P+Q)")
    ax.set_title("OEE Components po liniji", fontweight="bold", color=TEAL)
    ax.legend(facecolor=NAVY, edgecolor=GREY, fontsize=9, loc="upper right")
    ax.set_ylim(0, 3.0)
    _save(fig, "oee_overview.png")


# ── 2. OEE Trend — monthly line chart ─────────────────────────────────────
def chart_oee_trend(calc: OEECalculator) -> None:
    all_lines = calc.calculate_all_lines(period="monthly")

    fig, ax = plt.subplots(figsize=(12, 5))
    colors = plt.cm.Set2(np.linspace(0, 1, len(all_lines)))

    all_oee = []
    for i, (lid, df) in enumerate(sorted(all_lines.items())):
        dates = pd.to_datetime(df["period"])
        vals = df["oee"].values
        ax.plot(dates, vals, color=colors[i], linewidth=1, alpha=0.6, label=lid)
        all_oee.append(df.set_index("period")["oee"])

    # Average
    avg_df = pd.concat(all_oee, axis=1).mean(axis=1)
    avg_dates = pd.to_datetime(avg_df.index)
    ax.plot(avg_dates, avg_df.values, color=WHITE, linewidth=3, label="Prosjek")

    ax.set_title("Mjesečni OEE trend po liniji", fontweight="bold", color=TEAL)
    ax.set_ylabel("OEE")
    ax.set_xlabel("Mjesec")
    ax.legend(facecolor=NAVY, edgecolor=GREY, fontsize=8, ncol=3)
    ax.set_ylim(0.5, 1.0)
    _save(fig, "oee_trend.png")


# ── 3. Six Big Losses — waterfall ─────────────────────────────────────────
def chart_six_big_losses(calc: OEECalculator) -> None:
    data = calc.data
    total_shifts = len(data)
    total_min = total_shifts * 480

    downtime = data["downtime_minutes"].sum()
    changeover = data["changeover_minutes"].sum()
    avail_loss_pct = (downtime + changeover) / total_min * 100

    planned = data["planned_qty"].sum()
    actual = data["actual_qty"].sum()
    perf_loss_pct = (1 - actual / planned) * 100 if planned > 0 else 0

    defects = data["defect_qty"].sum()
    qual_loss_pct = defects / actual * 100 if actual > 0 else 0

    final_oee = (1 - avail_loss_pct / 100) * (1 - perf_loss_pct / 100) * (1 - qual_loss_pct / 100) * 100

    categories = ["Theoretical\n100%", "Availability\nLoss", "Performance\nLoss", "Quality\nLoss", "Final\nOEE"]
    values = [100, -avail_loss_pct, -perf_loss_pct, -qual_loss_pct, 0]

    fig, ax = plt.subplots(figsize=(10, 6))

    running = 0
    bars_x = []
    bars_h = []
    bars_bottom = []
    bar_colors = []

    for i, (cat, val) in enumerate(zip(categories, values)):
        if i == 0:
            bars_x.append(i)
            bars_h.append(100)
            bars_bottom.append(0)
            bar_colors.append(TEAL)
            running = 100
        elif i == len(categories) - 1:
            bars_x.append(i)
            bars_h.append(final_oee)
            bars_bottom.append(0)
            bar_colors.append(GREEN_C)
        else:
            bars_x.append(i)
            bars_h.append(abs(val))
            bars_bottom.append(running - abs(val))
            bar_colors.append(RED_C)
            running -= abs(val)

    ax.bar(bars_x, bars_h, bottom=bars_bottom, color=bar_colors, width=0.6, edgecolor=NAVY)

    for i, (bx, bh, bb) in enumerate(zip(bars_x, bars_h, bars_bottom)):
        txt = f"{bh:.1f}%" if i == 0 or i == len(categories) - 1 else f"-{bh:.1f}%"
        ax.text(bx, bb + bh / 2, txt, ha="center", va="center", fontweight="bold",
                color=WHITE, fontsize=11)

    ax.set_xticks(range(len(categories)))
    ax.set_xticklabels(categories, fontsize=10)
    ax.set_ylabel("% of Theoretical Output")
    ax.set_title("Six Big Losses — Waterfall", fontweight="bold", color=TEAL)
    ax.set_ylim(0, 110)
    _save(fig, "six_big_losses.png")


# ── 4. Line Comparison — heatmap ──────────────────────────────────────────
def chart_line_comparison(calc: OEECalculator) -> None:
    bench = calc.benchmark()
    lines = [b["line_id"] for b in bench]
    metrics = ["availability", "performance", "quality", "avg_oee"]
    labels = ["Availability", "Performance", "Quality", "OEE"]

    mat = np.array([[b.get(m, b.get("avg_oee", 0)) for m in metrics] for b in bench])

    fig, ax = plt.subplots(figsize=(8, 6))
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("oee", [RED_C, YELLOW_C, GREEN_C])
    im = ax.imshow(mat, aspect="auto", cmap=cmap, vmin=0.6, vmax=1.0)

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_yticks(range(len(lines)))
    ax.set_yticklabels(lines, fontsize=10)

    for i in range(len(lines)):
        for j in range(len(labels)):
            color = WHITE if mat[i, j] < 0.8 else NAVY
            ax.text(j, i, f"{mat[i, j]:.1%}", ha="center", va="center",
                    fontsize=10, fontweight="bold", color=color)

    ax.set_title("Line Comparison Heatmap", fontweight="bold", color=TEAL, pad=12)
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.set_label("Score", color=WHITE)
    cbar.ax.yaxis.set_tick_params(color=WHITE)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=WHITE)
    _save(fig, "line_comparison.png")


# ── 5. Schedule Gantt ──────────────────────────────────────────────────────
def chart_schedule_gantt() -> None:
    sched = ProductionScheduler()
    raw = sched.optimize_schedule(DEMO_ORDERS, days_ahead=5)
    schedule = sched.minimize_changeovers(raw)

    fig, ax = plt.subplots(figsize=(14, 7))
    lines = sorted(set(s["line"] for s in schedule))
    line_idx = {l: i for i, l in enumerate(lines)}

    for s in schedule:
        y = line_idx[s["line"]]
        x_start = (s["day"] - 1) * 24 + s["start_hour"]
        width = s["end_hour"] - s["start_hour"]
        color = BRAND_COLORS.get(s["brand"], GREY)
        ax.barh(y, width, left=x_start, height=0.6, color=color,
                edgecolor=NAVY, linewidth=0.5)

    ax.set_yticks(range(len(lines)))
    ax.set_yticklabels(lines)
    ax.set_xlabel("Sati (Dan 1-5)")
    ax.set_title("5-Day Production Schedule (Gantt)", fontweight="bold", color=TEAL)

    day_ticks = [d * 24 for d in range(6)]
    ax.set_xticks(day_ticks)
    ax.set_xticklabels([f"Dan {d}" if d > 0 else "Start" for d in range(6)])
    for d in day_ticks[1:]:
        ax.axvline(d, color=GREY, linestyle=":", linewidth=0.5, alpha=0.5)

    legend_patches = [mpatches.Patch(color=c, label=b) for b, c in BRAND_COLORS.items()]
    ax.legend(handles=legend_patches, facecolor=NAVY, edgecolor=GREY, fontsize=9)
    ax.invert_yaxis()
    _save(fig, "schedule_gantt.png")


# ── 6. Downtime Prediction scatter ────────────────────────────────────────
def chart_downtime_prediction(dt_result: dict) -> None:
    actuals = np.array(dt_result["actuals_test"])
    preds = np.array(dt_result["predictions_test"])
    r2 = dt_result["r2_score"]

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(actuals, preds, color=TEAL, alpha=0.4, s=15, edgecolors="none")

    lims = [0, max(actuals.max(), preds.max()) * 1.1]
    ax.plot(lims, lims, color=RED_C, linewidth=2, linestyle="--", label=f"Ideal (R²={r2:.4f})")

    ax.set_xlabel("Actual Downtime (min)")
    ax.set_ylabel("Predicted Downtime (min)")
    ax.set_title("Downtime Prediction — Actual vs Predicted", fontweight="bold", color=TEAL)
    ax.legend(facecolor=NAVY, edgecolor=GREY, fontsize=10)
    ax.set_xlim(lims)
    ax.set_ylim(lims)
    _save(fig, "downtime_prediction.png")


# ── 7. Anomaly Detection scatter ──────────────────────────────────────────
def chart_anomaly_detection(df: pd.DataFrame) -> None:
    normal = df[df["anomaly"] == 1]
    anomalies = df[df["anomaly"] == -1]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(normal["oee_score"], normal["defect_qty"],
               color=TEAL, alpha=0.3, s=12, edgecolors="none", label="Normal")
    ax.scatter(anomalies["oee_score"], anomalies["defect_qty"],
               color=RED_C, alpha=0.8, s=30, edgecolors=WHITE, linewidths=0.5,
               label=f"Anomaly ({len(anomalies)})")

    ax.set_xlabel("OEE Score")
    ax.set_ylabel("Defect Quantity")
    ax.set_title("Anomaly Detection — OEE vs Defects", fontweight="bold", color=TEAL)
    ax.legend(facecolor=NAVY, edgecolor=GREY, fontsize=10)
    _save(fig, "anomaly_detection.png")


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    BOLD = "\033[1m"
    CYAN_T = "\033[96m"
    GREEN_T = "\033[92m"
    RED_T = "\033[91m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN_T}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN_T}  SPORTEK — OEE Dashboard — Visualizations{RESET}")
    print(f"{BOLD}{CYAN_T}{'=' * 70}{RESET}\n")

    calc = OEECalculator()
    calc.load_data()

    # Prepare predictive data
    df, _, _ = _prepare_data()
    dt_result = train_downtime_predictor(df)
    anom_result = train_anomaly_detector(df)
    df["anomaly"] = anom_result["anomaly_labels"]

    print("  Generišem grafove...")

    chart_oee_overview(calc)
    print(f"    {GREEN_T}1. oee_overview.png{RESET}")

    chart_oee_trend(calc)
    print(f"    {GREEN_T}2. oee_trend.png{RESET}")

    chart_six_big_losses(calc)
    print(f"    {GREEN_T}3. six_big_losses.png{RESET}")

    chart_line_comparison(calc)
    print(f"    {GREEN_T}4. line_comparison.png{RESET}")

    chart_schedule_gantt()
    print(f"    {GREEN_T}5. schedule_gantt.png{RESET}")

    chart_downtime_prediction(dt_result)
    print(f"    {GREEN_T}6. downtime_prediction.png{RESET}")

    chart_anomaly_detection(df)
    print(f"    {GREEN_T}7. anomaly_detection.png{RESET}")

    # Summary
    bench = calc.benchmark()
    avg_oee = np.mean([b["avg_oee"] for b in bench])
    best_line = bench[0]
    worst_line = bench[-1]
    n_anomalies = anom_result["anomalies_detected"]

    print(f"\n  {BOLD}Summary:{RESET}")
    print(f"    Prosječan OEE fabrike:   {GREEN_T}{avg_oee:.1%}{RESET}")
    print(f"    Najbolja linija:         {GREEN_T}{best_line['line_id']} ({best_line['avg_oee']:.1%}){RESET}")
    print(f"    Najlošija linija:        {RED_T}{worst_line['line_id']} ({worst_line['avg_oee']:.1%}){RESET}")
    print(f"    Anomalije detektovane:   {RED_T}{n_anomalies}{RESET}")
    print(f"    Grafova generisano:      {GREEN_T}7{RESET}")
    print(f"\n  {DIM}Saved → {RESULT_DIR}/{RESET}")
    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()
