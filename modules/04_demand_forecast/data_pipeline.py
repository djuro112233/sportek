"""
Sportek d.o.o. — Demand Forecast — Data Pipeline
Loads production and purchase-order data, aggregates weekly demand,
and engineers ML features for forecasting.

Usage:
    python -m modules.04_demand_forecast.data_pipeline
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
PROD_CSV = PROJECT_ROOT / "data" / "production" / "production_log.csv"
PO_CSV = PROJECT_ROOT / "data" / "supply_chain" / "purchase_orders.csv"
PROCESSED_DIR = MODULE_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


class DemandPipeline:
    """Load, aggregate and feature-engineer demand data."""

    def __init__(self) -> None:
        self.production: pd.DataFrame | None = None
        self.orders: pd.DataFrame | None = None
        self.weekly_total: pd.DataFrame | None = None
        self.weekly_brand: pd.DataFrame | None = None
        self.features: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load_data(self) -> None:
        self.production = pd.read_csv(PROD_CSV, parse_dates=["date"])
        self.orders = pd.read_csv(PO_CSV, parse_dates=["date"])

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------
    def aggregate(self, freq: str = "W") -> tuple[pd.DataFrame, pd.DataFrame]:
        """Aggregate actual_qty by *freq* (W=weekly, M=monthly)."""
        if self.production is None:
            self.load_data()

        # Total weekly demand
        self.weekly_total = (
            self.production
            .set_index("date")
            .resample(freq)["actual_qty"]
            .sum()
            .to_frame("demand")
        )
        self.weekly_total.index.name = "date"

        # Per-brand weekly demand
        brand_frames = []
        for brand in sorted(self.production["brand"].unique()):
            s = (
                self.production[self.production["brand"] == brand]
                .set_index("date")
                .resample(freq)["actual_qty"]
                .sum()
                .rename(brand)
            )
            brand_frames.append(s)
        self.weekly_brand = pd.concat(brand_frames, axis=1).fillna(0).astype(int)
        self.weekly_brand.index.name = "date"

        return self.weekly_total, self.weekly_brand

    # ------------------------------------------------------------------
    # Feature engineering
    # ------------------------------------------------------------------
    def engineer_features(self, df: pd.DataFrame | None = None) -> pd.DataFrame:
        """Add time-series features to *df* (or weekly_total)."""
        if df is None:
            if self.weekly_total is None:
                self.aggregate()
            df = self.weekly_total.copy()

        feat = df.copy()
        idx = feat.index

        # Calendar features
        feat["month"] = idx.month
        feat["quarter"] = idx.quarter
        feat["day_of_week"] = idx.dayofweek
        feat["week_of_year"] = idx.isocalendar().week.values.astype(int)

        # High season: Mar-Jun, Sep-Nov
        feat["is_high_season"] = idx.month.map(
            lambda m: 1 if m in (3, 4, 5, 6, 9, 10, 11) else 0
        )

        # Rolling statistics
        for w in (7, 14, 30):
            # For weekly data use rolling windows in terms of rows
            row_w = max(w // 7, 1)
            feat[f"rolling_mean_{w}"] = feat["demand"].rolling(row_w, min_periods=1).mean()
            if w <= 14:
                feat[f"rolling_std_{w}"] = feat["demand"].rolling(row_w, min_periods=1).std().fillna(0)

        # Lags (in row terms for weekly data)
        for w in (7, 14, 30):
            row_lag = max(w // 7, 1)
            feat[f"lag_{w}"] = feat["demand"].shift(row_lag)

        # Trend (linear index)
        feat["trend"] = np.arange(len(feat))

        # Exponential weighted mean (span ~7 days → 1 week for weekly)
        feat["ewm_mean_7"] = feat["demand"].ewm(span=max(7 // 7, 1), min_periods=1).mean()

        # Fill NaN lags with backfill for ML readiness
        feat = feat.bfill()

        self.features = feat
        return feat

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save(self) -> None:
        if self.weekly_total is not None:
            self.weekly_total.to_csv(PROCESSED_DIR / "weekly_demand.csv")
        if self.weekly_brand is not None:
            self.weekly_brand.to_csv(PROCESSED_DIR / "weekly_demand_by_brand.csv")
        if self.features is not None:
            self.features.to_csv(PROCESSED_DIR / "features_matrix.csv")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    def print_stats(self) -> None:
        BOLD = "\033[1m"
        CYAN = "\033[96m"
        GREEN = "\033[92m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        print()
        print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")
        print(f"{BOLD}{CYAN}  SPORTEK — Demand Forecast — Data Pipeline{RESET}")
        print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")

        if self.weekly_total is not None:
            n_weeks = len(self.weekly_total)
            avg_demand = self.weekly_total["demand"].mean()
            total = self.weekly_total["demand"].sum()
            print(f"\n  Sedmica podataka:          {GREEN}{n_weeks}{RESET}")
            print(f"  Prosječna sedmična potražnja: {GREEN}{avg_demand:,.0f}{RESET} jedinica")
            print(f"  Ukupna proizvodnja:           {GREEN}{total:,.0f}{RESET} jedinica")

        if self.weekly_brand is not None:
            print(f"\n  {'Brend':<15s}  {'Ukupno':>10s}  {'Sedm. prosjek':>14s}")
            print(f"  {'─' * 15}  {'─' * 10}  {'─' * 14}")
            for col in self.weekly_brand.columns:
                tot = self.weekly_brand[col].sum()
                avg = self.weekly_brand[col].mean()
                print(f"  {col:<15s}  {tot:>10,}  {avg:>14,.0f}")

        if self.features is not None:
            print(f"\n  Feature matrica:  {GREEN}{self.features.shape[0]} redova × "
                  f"{self.features.shape[1]} kolona{RESET}")
            print(f"  {DIM}Features: {', '.join(c for c in self.features.columns if c != 'demand')}{RESET}")

        print(f"\n{'=' * 65}\n")


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------
def main() -> None:
    pipe = DemandPipeline()
    pipe.load_data()
    pipe.aggregate(freq="W")
    pipe.engineer_features()
    pipe.save()
    pipe.print_stats()
    print(f"  Saved → {PROCESSED_DIR}/\n")


if __name__ == "__main__":
    main()
