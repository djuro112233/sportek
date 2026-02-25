"""
Sportek d.o.o. — TradeFlow AI — Compliance Analytics
Generates 5 charts (navy/teal colour scheme) for trade-compliance dashboard.

Usage:
    python modules/02_tradeflow/compliance_analytics.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
HS_CSV = PROJECT_ROOT / "data" / "compliance" / "hs_classifications.csv"
PRODUCTS_CSV = PROJECT_ROOT / "data" / "compliance" / "products_dpp.csv"
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Colour palette — navy / teal
# ---------------------------------------------------------------------------
NAVY = "#0D1B2A"
DARK_TEAL = "#004D40"
TEAL = "#00897B"
LIGHT_TEAL = "#B2DFDB"
CREAM = "#F5F5F0"
ACCENT = "#FF6F00"   # amber accent for highlights

PALETTE = ["#004D40", "#00695C", "#00897B", "#26A69A", "#4DB6AC",
           "#80CBC4", "#B2DFDB", "#0D1B2A", "#1B3A4B", "#3A6B7E"]


def _style_ax(ax, title: str) -> None:
    """Apply consistent navy/teal style to axes."""
    ax.set_facecolor(CREAM)
    ax.set_title(title, fontsize=13, fontweight="bold", color=NAVY, pad=12)
    ax.tick_params(colors=NAVY, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(NAVY)
        spine.set_linewidth(0.8)


# ======================================================================
# 1. HS Distribution — Pie Chart
# ======================================================================
def plot_hs_distribution(df_hs: pd.DataFrame) -> str:
    counts = df_hs["correct_hs_code"].astype(str).str.zfill(6).value_counts()
    labels = counts.index.tolist()
    sizes = counts.values

    fig, ax = plt.subplots(figsize=(9, 7))
    fig.set_facecolor("white")
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct="%1.1f%%",
        colors=PALETTE[:len(labels)],
        startangle=140,
        textprops={"fontsize": 9, "color": NAVY},
        pctdistance=0.82,
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
    )
    for t in autotexts:
        t.set_fontweight("bold")
        t.set_fontsize(8)
    ax.set_title("HS Code Distribution — Sportek Product Portfolio",
                 fontsize=13, fontweight="bold", color=NAVY, pad=15)
    plt.tight_layout()
    path = RESULT_DIR / "hs_distribution.png"
    plt.savefig(path, dpi=150, facecolor="white")
    plt.close()
    return str(path)


# ======================================================================
# 2. Duty Savings — Bar Chart
# ======================================================================
def plot_duty_savings(df_hs: pd.DataFrame) -> str:
    df = df_hs.copy()
    df["mfn_duty"] = df["duty_rate_percent"]
    df["pref_duty"] = df["preferential_rate"]
    df["saving"] = df["mfn_duty"] - df["pref_duty"]

    by_country = df.groupby("country_destination").agg(
        mfn=("mfn_duty", "mean"),
        pref=("pref_duty", "mean"),
        saving=("saving", "mean"),
    ).sort_values("saving", ascending=False).head(10)

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.set_facecolor("white")
    _style_ax(ax, "FTA Duty Savings — Top 10 Destinations (MFN vs Preferential)")

    x = np.arange(len(by_country))
    w = 0.35
    ax.bar(x - w / 2, by_country["mfn"], w, label="MFN Rate (%)", color=NAVY)
    ax.bar(x + w / 2, by_country["pref"], w, label="Preferential Rate (%)", color=TEAL)

    # Savings annotation
    for i, (_, row) in enumerate(by_country.iterrows()):
        if row["saving"] > 0:
            ax.annotate(f"-{row['saving']:.1f}%",
                        xy=(i + w / 2, row["pref"] + 0.3),
                        fontsize=8, color=ACCENT, fontweight="bold", ha="center")

    ax.set_xticks(x)
    ax.set_xticklabels(by_country.index, fontsize=9)
    ax.set_ylabel("Duty Rate (%)", color=NAVY)
    ax.legend(framealpha=0.9, fontsize=9)
    plt.tight_layout()
    path = RESULT_DIR / "duty_savings.png"
    plt.savefig(path, dpi=150, facecolor="white")
    plt.close()
    return str(path)


# ======================================================================
# 3. DPP Readiness — Horizontal Bar Chart
# ======================================================================
def plot_dpp_readiness(df_prod: pd.DataFrame) -> str:
    from dpp_generator import DPPGenerator
    gen = DPPGenerator()

    records = df_prod.to_dict("records")
    results = []
    for r in records:
        dpp = gen.generate(r)
        val = gen.validate(dpp)
        results.append({"brand": r["brand"], "completeness": val["completeness_pct"]})

    rdf = pd.DataFrame(results)
    by_brand = rdf.groupby("brand")["completeness"].mean().sort_values()

    fig, ax = plt.subplots(figsize=(9, 5))
    fig.set_facecolor("white")
    _style_ax(ax, "DPP Readiness by Brand — Average Completeness (%)")

    colours = [DARK_TEAL if v >= 90 else TEAL if v >= 70 else ACCENT
               for v in by_brand.values]
    bars = ax.barh(by_brand.index, by_brand.values, color=colours, edgecolor="white")

    for bar, val in zip(bars, by_brand.values):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%", va="center", fontsize=10, fontweight="bold", color=NAVY)

    ax.set_xlim(0, 110)
    ax.axvline(90, color=ACCENT, linestyle="--", linewidth=0.8, label="Target 90%")
    ax.set_xlabel("Completeness (%)", color=NAVY)
    ax.legend(fontsize=9)
    plt.tight_layout()
    path = RESULT_DIR / "dpp_readiness.png"
    plt.savefig(path, dpi=150, facecolor="white")
    plt.close()
    return str(path)


# ======================================================================
# 4. CBAM Exposure — Bar Chart (carbon footprint per product line)
# ======================================================================
def plot_cbam_exposure(df_prod: pd.DataFrame) -> str:
    # Product line = base name without version
    df = df_prod.copy()
    df["product_line"] = df["product_name"].str.replace(r"\s+v\d+$", "", regex=True)
    by_line = df.groupby("product_line")["carbon_footprint_kg"].agg(["mean", "sum", "count"])
    by_line = by_line.sort_values("mean", ascending=False)

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.set_facecolor("white")
    _style_ax(ax, "CBAM Exposure — Avg Carbon Footprint by Product Line")

    colours = [NAVY if v > 10 else DARK_TEAL if v > 5 else TEAL for v in by_line["mean"]]
    bars = ax.bar(range(len(by_line)), by_line["mean"], color=colours, edgecolor="white")

    ax.set_xticks(range(len(by_line)))
    ax.set_xticklabels(by_line.index, rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("Avg Carbon Footprint (kg CO2e)", color=NAVY)

    for bar, val in zip(bars, by_line["mean"]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                f"{val:.1f}", ha="center", fontsize=9, fontweight="bold", color=NAVY)

    plt.tight_layout()
    path = RESULT_DIR / "cbam_exposure.png"
    plt.savefig(path, dpi=150, facecolor="white")
    plt.close()
    return str(path)


# ======================================================================
# 5. Compliance Risk Matrix — Heatmap
# ======================================================================
def plot_compliance_risk_matrix(df_prod: pd.DataFrame) -> str:
    from dpp_generator import DPPGenerator
    gen = DPPGenerator()

    # Product lines
    df = df_prod.copy()
    df["product_line"] = df["product_name"].str.replace(r"\s+v\d+$", "", regex=True)
    lines = sorted(df["product_line"].unique())

    risk_categories = [
        "HS Misclassification",
        "DPP Gaps",
        "CBAM Exposure",
        "REACH Risk",
        "Origin Complexity",
    ]

    matrix = np.zeros((len(lines), len(risk_categories)))

    for i, line in enumerate(lines):
        sub = df[df["product_line"] == line]

        # HS Misclassification risk: more unique HS codes in line = higher risk
        n_hs = sub["hs_code_6digit"].nunique()
        matrix[i, 0] = min(n_hs * 2, 10)  # scale

        # DPP Gaps: based on recyclability (lower = more gaps)
        avg_recycle = sub["recyclability_score"].mean()
        matrix[i, 1] = max(0, 10 - avg_recycle / 10)

        # CBAM Exposure: carbon footprint
        avg_carbon = sub["carbon_footprint_kg"].mean()
        matrix[i, 2] = min(avg_carbon / 1.5, 10)

        # REACH Risk: if any mention of traces/epoxy → higher
        reach_risk = sub["hazardous_substances"].str.contains("traces|epoxy", case=False).mean()
        matrix[i, 3] = reach_risk * 8

        # Origin Complexity: number of distinct origin countries
        n_origins = sub["country_origin"].nunique()
        matrix[i, 4] = min(n_origins * 1.5, 10)

    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list(
        "risk", [LIGHT_TEAL, "#FFF9C4", ACCENT, "#D32F2F"]
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.set_facecolor("white")
    im = ax.imshow(matrix, cmap=cmap, aspect="auto", vmin=0, vmax=10)
    plt.colorbar(im, ax=ax, label="Risk Score (0-10)", shrink=0.8)

    ax.set_xticks(range(len(risk_categories)))
    ax.set_xticklabels(risk_categories, rotation=30, ha="right", fontsize=9)
    ax.set_yticks(range(len(lines)))
    ax.set_yticklabels(lines, fontsize=8)

    # Annotate
    for i in range(len(lines)):
        for j in range(len(risk_categories)):
            v = matrix[i, j]
            colour = "white" if v > 6 else NAVY
            ax.text(j, i, f"{v:.1f}", ha="center", va="center",
                    fontsize=8, fontweight="bold", color=colour)

    ax.set_title("Compliance Risk Matrix — Product Line x Risk Category",
                 fontsize=13, fontweight="bold", color=NAVY, pad=12)
    plt.tight_layout()
    path = RESULT_DIR / "compliance_risk_matrix.png"
    plt.savefig(path, dpi=150, facecolor="white")
    plt.close()
    return str(path)


# ======================================================================
# CLI entry-point
# ======================================================================
def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print()
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK TradeFlow — Compliance Analytics (5 Charts){RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")

    df_hs = pd.read_csv(HS_CSV)
    df_prod = pd.read_csv(PRODUCTS_CSV)

    charts = []

    print(f"\n  {BOLD}[1/5]{RESET} HS Distribution (pie chart) ...")
    charts.append(plot_hs_distribution(df_hs))

    print(f"  {BOLD}[2/5]{RESET} Duty Savings (bar chart) ...")
    charts.append(plot_duty_savings(df_hs))

    print(f"  {BOLD}[3/5]{RESET} DPP Readiness (horizontal bar) ...")
    charts.append(plot_dpp_readiness(df_prod))

    print(f"  {BOLD}[4/5]{RESET} CBAM Exposure (bar chart) ...")
    charts.append(plot_cbam_exposure(df_prod))

    print(f"  {BOLD}[5/5]{RESET} Compliance Risk Matrix (heatmap) ...")
    charts.append(plot_compliance_risk_matrix(df_prod))

    print(f"\n  {GREEN}{len(charts)} charts generated:{RESET}")
    for c in charts:
        print(f"    {DIM}→ {c}{RESET}")

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}\n")


if __name__ == "__main__":
    main()
