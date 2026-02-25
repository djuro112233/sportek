"""
Sportek d.o.o. — Demand Forecast — ML Models
Three forecasting models: Holt-Winters, Random Forest, Gradient Boosting.

Usage:
    python -m modules.04_demand_forecast.models
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from .data_pipeline import DemandPipeline

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

MODULE_DIR = Path(__file__).resolve().parent
MODELS_DIR = MODULE_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# Train/test split ratio
TRAIN_RATIO = 0.80


class DemandForecaster:
    """Train and compare Holt-Winters, Random Forest, and Gradient Boosting."""

    def __init__(self, pipeline: DemandPipeline | None = None) -> None:
        if pipeline is None:
            pipeline = DemandPipeline()
            pipeline.load_data()
            pipeline.aggregate(freq="W")
            pipeline.engineer_features()
        self.pipeline = pipeline

        demand = pipeline.weekly_total["demand"]
        features = pipeline.features

        split = int(len(demand) * TRAIN_RATIO)
        self.train_ts = demand.iloc[:split]
        self.test_ts = demand.iloc[split:]

        self.train_feat = features.iloc[:split]
        self.test_feat = features.iloc[split:]

        self._feature_cols = [
            c for c in features.columns if c != "demand"
        ]

        self.models: dict[str, object] = {}
        self.predictions: dict[str, np.ndarray] = {}
        self.metrics: dict[str, dict] = {}
        self.best_model_name: str | None = None

    # ------------------------------------------------------------------
    # Train
    # ------------------------------------------------------------------
    def train(self, model_type: str) -> None:
        """Train one of: holt_winters, random_forest, gradient_boosting."""
        if model_type == "holt_winters":
            self._train_hw()
        elif model_type == "random_forest":
            self._train_rf()
        elif model_type == "gradient_boosting":
            self._train_gb()
        else:
            raise ValueError(f"Unknown model_type: {model_type}")

    def _train_hw(self) -> None:
        seasonal_periods = min(4, len(self.train_ts) // 2)
        model = ExponentialSmoothing(
            self.train_ts,
            trend="add",
            seasonal="add",
            seasonal_periods=seasonal_periods,
        ).fit(optimized=True)
        self.models["holt_winters"] = model
        self.predictions["holt_winters"] = model.forecast(len(self.test_ts)).values

    def _train_rf(self) -> None:
        model = RandomForestRegressor(
            n_estimators=100, max_depth=10, random_state=42, n_jobs=-1,
        )
        X_train = self.train_feat[self._feature_cols]
        y_train = self.train_feat["demand"]
        model.fit(X_train, y_train)
        self.models["random_forest"] = model
        X_test = self.test_feat[self._feature_cols]
        self.predictions["random_forest"] = model.predict(X_test)

    def _train_gb(self) -> None:
        model = GradientBoostingRegressor(
            n_estimators=200, learning_rate=0.1, max_depth=5, random_state=42,
        )
        X_train = self.train_feat[self._feature_cols]
        y_train = self.train_feat["demand"]
        model.fit(X_train, y_train)
        self.models["gradient_boosting"] = model
        X_test = self.test_feat[self._feature_cols]
        self.predictions["gradient_boosting"] = model.predict(X_test)

    # ------------------------------------------------------------------
    # Predict (future horizon)
    # ------------------------------------------------------------------
    def predict(self, model_type: str, horizon_days: int = 30) -> dict:
        """Forecast *horizon_days* into the future."""
        horizon_weeks = max(horizon_days // 7, 1)
        hist_std = float(self.train_ts.std())
        last_date = self.pipeline.weekly_total.index[-1]
        future_dates = pd.date_range(
            start=last_date + pd.Timedelta(weeks=1),
            periods=horizon_weeks,
            freq="W",
        )

        if model_type == "holt_winters":
            hw = self.models["holt_winters"]
            fc = hw.forecast(horizon_weeks).values
        else:
            # Build future feature rows
            rows = []
            feat_last = self.pipeline.features.iloc[-1].copy()
            for i, dt in enumerate(future_dates):
                row = {}
                row["month"] = dt.month
                row["quarter"] = dt.quarter
                row["day_of_week"] = dt.dayofweek
                row["week_of_year"] = dt.isocalendar()[1]
                row["is_high_season"] = 1 if dt.month in (3,4,5,6,9,10,11) else 0
                row["trend"] = int(feat_last["trend"]) + i + 1
                for c in self._feature_cols:
                    if c not in row:
                        row[c] = float(feat_last.get(c, 0))
                rows.append(row)
            X_future = pd.DataFrame(rows)[self._feature_cols]
            fc = self.models[model_type].predict(X_future)

        margin = 1.96 * hist_std
        return {
            "dates": [str(d.date()) for d in future_dates],
            "forecast": [round(float(v), 0) for v in fc],
            "lower_bound": [round(float(v - margin), 0) for v in fc],
            "upper_bound": [round(float(v + margin), 0) for v in fc],
        }

    # ------------------------------------------------------------------
    # Evaluate
    # ------------------------------------------------------------------
    def evaluate(self, model_type: str) -> dict:
        actual = self.test_ts.values
        pred = self.predictions[model_type]
        mae = float(mean_absolute_error(actual, pred))
        rmse = float(np.sqrt(mean_squared_error(actual, pred)))
        # MAPE — guard against zero
        nonzero = actual != 0
        if nonzero.any():
            mape = float(np.mean(np.abs((actual[nonzero] - pred[nonzero]) / actual[nonzero])) * 100)
        else:
            mape = 0.0
        self.metrics[model_type] = {
            "mae": round(mae, 1),
            "rmse": round(rmse, 1),
            "mape": round(mape, 2),
        }
        return self.metrics[model_type]

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------
    def compare_models(self) -> pd.DataFrame:
        """Train all 3, evaluate, return comparison DataFrame."""
        for mt in ("holt_winters", "random_forest", "gradient_boosting"):
            if mt not in self.models:
                self.train(mt)
            if mt not in self.metrics:
                self.evaluate(mt)

        rows = []
        for name, m in self.metrics.items():
            rows.append({"model": name, **m})
        comp = pd.DataFrame(rows)

        # Best = lowest RMSE
        best_idx = comp["rmse"].idxmin()
        self.best_model_name = comp.loc[best_idx, "model"]
        comp["best"] = ""
        comp.loc[best_idx, "best"] = "<-- BEST"

        # Save best model
        best_model = self.models[self.best_model_name]
        joblib.dump(best_model, MODELS_DIR / "best_forecast_model.pkl")

        # Save comparison JSON
        comparison = {
            "models": {r["model"]: {k: v for k, v in r.items() if k != "best"} for _, r in comp.iterrows()},
            "best_model": self.best_model_name,
            "train_size": len(self.train_ts),
            "test_size": len(self.test_ts),
        }

        # Add feature importance for tree models
        for mt in ("random_forest", "gradient_boosting"):
            if mt in self.models and hasattr(self.models[mt], "feature_importances_"):
                imp = dict(zip(self._feature_cols, self.models[mt].feature_importances_))
                imp_sorted = dict(sorted(imp.items(), key=lambda x: x[1], reverse=True))
                comparison["models"][mt]["feature_importance"] = {
                    k: round(float(v), 4) for k, v in imp_sorted.items()
                }

        with open(RESULT_DIR / "model_comparison.json", "w") as f:
            json.dump(comparison, f, indent=2, ensure_ascii=False)

        return comp

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------
    def print_comparison(self, comp: pd.DataFrame) -> None:
        BOLD = "\033[1m"
        CYAN = "\033[96m"
        GREEN = "\033[92m"
        YELLOW = "\033[93m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        print()
        print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")
        print(f"{BOLD}{CYAN}  SPORTEK — Demand Forecast — Model Comparison{RESET}")
        print(f"{BOLD}{CYAN}{'=' * 65}{RESET}")

        print(f"\n  Train: {len(self.train_ts)} sedmica  |  Test: {len(self.test_ts)} sedmica\n")
        print(f"  {'Model':<22s}  {'MAE':>10s}  {'RMSE':>10s}  {'MAPE %':>8s}  {'':>10s}")
        print(f"  {'─' * 22}  {'─' * 10}  {'─' * 10}  {'─' * 8}  {'─' * 10}")
        for _, row in comp.iterrows():
            tag = f"{GREEN}{BOLD}<-- BEST{RESET}" if row["best"] else ""
            print(f"  {row['model']:<22s}  {row['mae']:>10,.1f}  {row['rmse']:>10,.1f}  "
                  f"{row['mape']:>8.2f}  {tag}")

        print(f"\n  {BOLD}Najbolji model: {YELLOW}{self.best_model_name}{RESET}")
        print(f"  {DIM}Saved → models/best_forecast_model.pkl{RESET}")
        print(f"  {DIM}Saved → results/model_comparison.json{RESET}")

        # Feature importance for best tree model
        for mt in ("random_forest", "gradient_boosting"):
            if mt in self.models and hasattr(self.models[mt], "feature_importances_"):
                imp = sorted(
                    zip(self._feature_cols, self.models[mt].feature_importances_),
                    key=lambda x: x[1], reverse=True,
                )
                print(f"\n  {BOLD}Feature Importance ({mt}):{RESET}")
                for fname, val in imp[:8]:
                    bar = "█" * int(val * 80)
                    print(f"    {fname:<20s} {val:.4f}  {DIM}{bar}{RESET}")

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

    forecaster = DemandForecaster(pipeline=pipe)
    comp = forecaster.compare_models()
    forecaster.print_comparison(comp)


if __name__ == "__main__":
    main()
