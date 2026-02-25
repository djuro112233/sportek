"""
Sportek d.o.o. — Demand Forecast — Visualizations
6 charts: forecast, demand by brand, seasonality, model comparison,
inventory optimization, stockout risk heatmap.

Usage:
    python -m modules.04_demand_forecast.visualizations
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd

from .data_pipeline import DemandPipeline
from .inventory_optimizer import InventoryOptimizer
from .models import DemandForecaster

MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ── Sportek brand colours ──────────────────────────────────────────────────
NAVY = "#1B2A4A"
TEAL = "#0891B2"
TEAL_LIGHT = "#22d3ee"
TEAL_DARK = "#0e7490"
RED_ACCENT = "#ef4444"
GREEN_OK = "#22c55e"
YELLOW_WARN = "#eab308"
BLUE_OVER = "#3b82f6"
WHITE = "#f8fafc"
GREY = "#94a3b8"

BRAND_COLORS = {"Nike": "#0891B2", "Crocs": "#22d3ee", "Decathlon": "#0e7490"}

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


def _save(fig: plt.Figure, name: str) -> None:
    fig.savefig(RESULT_DIR / name, bbox_inches="tight")
    plt.close(fig)


# ── 1. Forecast vs Actual ─────────────────────────────────────────────────
def chart_forecast_vs_actual(
    pipe: DemandPipeline, forecaster: DemandForecaster,
) -> None:
    demand = pipe.weekly_total["demand"]
    split = int(len(demand) * 0.80)
    train = demand.iloc[:split]
    test = demand.iloc[split:]

    # Get forecasts for all 3, use best
    best = forecaster.best_model_name or "random_forest"
    pred = forecaster.predictions.get(best, np.zeros(len(test)))
    hist_std = float(train.std())

    fig, ax = plt.subplots(figsize=(12, 5))

    ax.plot(train.index, train.values, color=TEAL, linewidth=2, label="Actual (train)")
    ax.plot(test.index, test.values, color=TEAL_LIGHT, linewidth=2,
            linestyle=":", label="Actual (test)")
    ax.plot(test.index, pred, color=RED_ACCENT, linewidth=2, label=f"Forecast ({best})")

    ax.fill_between(
        test.index,
        pred - 1.96 * hist_std,
        pred + 1.96 * hist_std,
        color=RED_ACCENT, alpha=0.15, label="95% CI",
    )

    split_date = train.index[-1]
    ax.axvline(split_date, color=GREY, linestyle="--", linewidth=1, label="Train/Test split")

    ax.set_title("Sedmična potražnja — Forecast vs Actual", fontweight="bold", color=TEAL)
    ax.set_xlabel("Datum")
    ax.set_ylabel("Jedinice / sedmicu")
    ax.legend(facecolor=NAVY, edgecolor=GREY, fontsize=9)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    _save(fig, "forecast_vs_actual.png")


# ── 2. Demand by Brand (stacked area) ─────────────────────────────────────
def chart_demand_by_brand(pipe: DemandPipeline) -> None:
    wb = pipe.weekly_brand
    fig, ax = plt.subplots(figsize=(12, 5))

    brands = list(wb.columns)
    colors = [BRAND_COLORS.get(b, TEAL) for b in brands]
    ax.stackplot(wb.index, *[wb[b].values for b in brands],
                 labels=brands, colors=colors, alpha=0.85)

    ax.set_title("Sedmična potražnja po brendu", fontweight="bold", color=TEAL)
    ax.set_xlabel("Datum")
    ax.set_ylabel("Jedinice / sedmicu")
    ax.legend(loc="upper left", facecolor=NAVY, edgecolor=GREY, fontsize=9)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    _save(fig, "demand_by_brand.png")


# ── 3. Seasonality (2 panels) ─────────────────────────────────────────────
def chart_seasonality(pipe: DemandPipeline) -> None:
    prod = pipe.production.copy()
    prod["month"] = prod["date"].dt.month
    prod["dow"] = prod["date"].dt.dayofweek

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Monthly average
    monthly = prod.groupby("month")["actual_qty"].mean()
    ax1.bar(monthly.index, monthly.values, color=TEAL, edgecolor=TEAL_DARK)
    ax1.set_title("Mjesečni prosjek proizvodnje", fontweight="bold", color=TEAL)
    ax1.set_xlabel("Mjesec")
    ax1.set_ylabel("Prosjek jedinica/dan")
    ax1.set_xticks(range(1, 13))
    ax1.set_xticklabels(["Jan","Feb","Mar","Apr","Maj","Jun",
                         "Jul","Aug","Sep","Okt","Nov","Dec"], fontsize=9)

    # Day of week
    dow = prod.groupby("dow")["actual_qty"].mean()
    ax2.bar(dow.index, dow.values, color=TEAL_LIGHT, edgecolor=TEAL_DARK)
    ax2.set_title("Dnevni pattern (dan u sedmici)", fontweight="bold", color=TEAL)
    ax2.set_xlabel("Dan")
    ax2.set_ylabel("Prosjek jedinica")
    ax2.set_xticks(range(7))
    ax2.set_xticklabels(["Pon","Uto","Sri","Čet","Pet","Sub","Ned"], fontsize=9)

    plt.tight_layout()
    _save(fig, "seasonality.png")


# ── 4. Model Comparison (grouped bar) ─────────────────────────────────────
def chart_model_comparison(forecaster: DemandForecaster) -> None:
    metrics = forecaster.metrics
    models = list(metrics.keys())
    metric_names = ["MAE", "RMSE", "MAPE"]
    best = forecaster.best_model_name

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    x = np.arange(len(models))
    bar_w = 0.5

    for i, (mname, key) in enumerate(zip(metric_names, ["mae", "rmse", "mape"])):
        vals = [metrics[m][key] for m in models]
        colors = [GREEN_OK if m == best else TEAL for m in models]
        bars = axes[i].bar(x, vals, bar_w, color=colors, edgecolor=TEAL_DARK)

        # Star on best
        best_idx = models.index(best) if best in models else 0
        axes[i].annotate("★", (best_idx, vals[best_idx]),
                         textcoords="offset points", xytext=(0, 8),
                         ha="center", fontsize=16, color=YELLOW_WARN)

        axes[i].set_title(mname, fontweight="bold", color=TEAL)
        axes[i].set_xticks(x)
        axes[i].set_xticklabels([m.replace("_", "\n") for m in models], fontsize=8)

        for bar, val in zip(bars, vals):
            axes[i].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                         f"{val:,.1f}", ha="center", va="bottom", fontsize=9, color=WHITE)

    plt.suptitle("Model Comparison", fontweight="bold", color=TEAL, fontsize=14, y=1.02)
    plt.tight_layout()
    _save(fig, "model_comparison.png")


# ── 5. Inventory Optimization (horizontal bar top 20) ─────────────────────
def chart_inventory_optimization(opt_df: pd.DataFrame) -> None:
    # Top 20 by inventory value
    opt_df = opt_df.copy()
    opt_df["value"] = opt_df["current_stock"] * opt_df["unit_price_eur"]
    top20 = opt_df.nlargest(20, "value")

    status_colors = {
        "ok": GREEN_OK, "low": YELLOW_WARN,
        "critical": RED_ACCENT, "overstocked": BLUE_OVER,
    }

    fig, ax = plt.subplots(figsize=(11, 7))
    y_pos = np.arange(len(top20))
    colors = [status_colors.get(s, TEAL) for s in top20["status"]]

    bars = ax.barh(y_pos, top20["value"].values, color=colors, edgecolor=NAVY)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(
        [f"{r['material_id']}  {r['material_name'][:25]}" for _, r in top20.iterrows()],
        fontsize=8,
    )
    ax.invert_yaxis()
    ax.set_xlabel("Vrijednost inventara (EUR)")
    ax.set_title("Top 20 materijala po vrijednosti inventara", fontweight="bold", color=TEAL)
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{x:,.0f}"))

    # Legend
    from matplotlib.patches import Patch
    legend_items = [Patch(facecolor=c, label=s) for s, c in status_colors.items()]
    ax.legend(handles=legend_items, loc="lower right", facecolor=NAVY, edgecolor=GREY, fontsize=9)

    plt.tight_layout()
    _save(fig, "inventory_optimization.png")


# ── 6. Stockout Risk Heatmap ──────────────────────────────────────────────
def chart_stockout_risk(risks: list[dict]) -> None:
    if not risks:
        return

    top15 = risks[:15]
    weeks = [f"Sedmica {w}" for w in range(1, 5)]

    # Build heatmap matrix: rows=materials, cols=weeks 1-4
    mat = np.zeros((len(top15), 4))
    for i, r in enumerate(top15):
        days_left = r["days_until_stockout"]
        daily = r["current_stock"] / max(days_left, 0.1)
        for w in range(4):
            remaining = r["current_stock"] - daily * (w + 1) * 7
            if remaining <= 0:
                mat[i, w] = 1.0  # stockout
            elif remaining < daily * r["lead_time_days"]:
                mat[i, w] = 0.7  # high risk
            elif remaining < daily * r["lead_time_days"] * 2:
                mat[i, w] = 0.4  # medium
            else:
                mat[i, w] = 0.1  # low

    fig, ax = plt.subplots(figsize=(10, 7))
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("risk", [NAVY, TEAL, YELLOW_WARN, RED_ACCENT])
    im = ax.imshow(mat, aspect="auto", cmap=cmap, vmin=0, vmax=1)

    ax.set_xticks(range(4))
    ax.set_xticklabels(weeks, fontsize=10)
    ax.set_yticks(range(len(top15)))
    labels = [f"{r['material_id']}  {r['material_name'][:22]}" for r in top15]
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_title("Stockout Risk Heatmap — naredne 4 sedmice",
                 fontweight="bold", color=TEAL, pad=12)

    # Cell annotations
    for i in range(len(top15)):
        for j in range(4):
            val = mat[i, j]
            label = "OUT" if val >= 0.9 else "HIGH" if val >= 0.6 else "MED" if val >= 0.3 else "LOW"
            color = WHITE if val >= 0.5 else GREY
            ax.text(j, i, label, ha="center", va="center", fontsize=8,
                    fontweight="bold", color=color)

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.set_label("Nivo rizika", color=WHITE)
    cbar.ax.yaxis.set_tick_params(color=WHITE)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=WHITE)

    plt.tight_layout()
    _save(fig, "stockout_risk.png")


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    BOLD = "\033[1m"
    CYAN_C = "\033[96m"
    GREEN_C = "\033[92m"
    RED_C = "\033[91m"
    YELLOW_C = "\033[93m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN_C}{'=' * 65}{RESET}")
    print(f"{BOLD}{CYAN_C}  SPORTEK — Demand Forecast — Visualizations{RESET}")
    print(f"{BOLD}{CYAN_C}{'=' * 65}{RESET}\n")

    # Pipeline
    pipe = DemandPipeline()
    pipe.load_data()
    pipe.aggregate(freq="W")
    pipe.engineer_features()

    # Forecaster
    forecaster = DemandForecaster(pipeline=pipe)
    forecaster.compare_models()

    # Inventory
    inv_opt = InventoryOptimizer()
    opt_df = inv_opt.optimize_all()
    risks = inv_opt.detect_stockout_risk(days_ahead=30)

    # Generate all 6 charts
    charts = []

    print("  Generišem grafove...")
    chart_forecast_vs_actual(pipe, forecaster)
    charts.append("forecast_vs_actual.png")
    print(f"    {GREEN_C}1. forecast_vs_actual.png{RESET}")

    chart_demand_by_brand(pipe)
    charts.append("demand_by_brand.png")
    print(f"    {GREEN_C}2. demand_by_brand.png{RESET}")

    chart_seasonality(pipe)
    charts.append("seasonality.png")
    print(f"    {GREEN_C}3. seasonality.png{RESET}")

    chart_model_comparison(forecaster)
    charts.append("model_comparison.png")
    print(f"    {GREEN_C}4. model_comparison.png{RESET}")

    chart_inventory_optimization(opt_df)
    charts.append("inventory_optimization.png")
    print(f"    {GREEN_C}5. inventory_optimization.png{RESET}")

    chart_stockout_risk(risks)
    charts.append("stockout_risk.png")
    print(f"    {GREEN_C}6. stockout_risk.png{RESET}")

    # Summary
    status_counts = opt_df["status"].value_counts()
    critical = status_counts.get("critical", 0)
    low = status_counts.get("low", 0)
    high_risk = [r for r in risks if r["risk_level"] == "high"]
    total_risk_value = sum(r["estimated_cost"] for r in risks)

    print(f"\n  {BOLD}Summary:{RESET}")
    print(f"    Rizičnih materijala (30 dana):  {RED_C}{len(risks)}{RESET}")
    print(f"      — visok rizik:                {RED_C}{len(high_risk)}{RESET}")
    print(f"      — kritičan stock:             {RED_C}{critical}{RESET}")
    print(f"      — nizak stock:                {YELLOW_C}{low}{RESET}")
    print(f"    Ukupna vrijednost ugroženog:    {GREEN_C}{total_risk_value:,.0f} EUR{RESET}")
    print(f"    Grafova generisano:             {GREEN_C}{len(charts)}{RESET}")
    print(f"\n  {DIM}Saved → {RESULT_DIR}/{RESET}")
    print(f"\n{'=' * 65}\n")


if __name__ == "__main__":
    main()
