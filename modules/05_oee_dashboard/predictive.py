"""
Sportek d.o.o. — OEE Dashboard — Predictive Analytics
Downtime predictor (RF), defect rate predictor (GB), anomaly detector (IF).

Usage:
    python -m modules.05_oee_dashboard.predictive
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    GradientBoostingRegressor,
    IsolationForest,
    RandomForestRegressor,
)
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.preprocessing import LabelEncoder

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
PROD_CSV = PROJECT_ROOT / "data" / "production" / "production_log.csv"
MODELS_DIR = MODULE_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_RATIO = 0.80


def _prepare_data() -> pd.DataFrame:
    """Load and enrich production data with derived features."""
    df = pd.read_csv(PROD_CSV, parse_dates=["date"])
    df = df.sort_values(["line_id", "date", "shift"]).reset_index(drop=True)

    # Calendar features
    df["day_of_week"] = df["date"].dt.dayofweek
    df["month"] = df["date"].dt.month

    # Encode categoricals
    le_line = LabelEncoder()
    le_brand = LabelEncoder()
    df["line_enc"] = le_line.fit_transform(df["line_id"])
    df["brand_enc"] = le_brand.fit_transform(df["brand"])

    # Rolling average downtime (7-day window per line)
    df["rolling_avg_downtime_7d"] = (
        df.groupby("line_id")["downtime_minutes"]
        .transform(lambda s: s.rolling(7, min_periods=1).mean())
    )

    # Defect rate
    df["defect_rate"] = np.where(
        df["actual_qty"] > 0,
        df["defect_qty"] / df["actual_qty"],
        0,
    )

    return df, le_line, le_brand


# ── 1. Downtime Predictor ─────────────────────────────────────────────────
def train_downtime_predictor(df: pd.DataFrame) -> dict:
    features = ["line_enc", "brand_enc", "shift", "day_of_week", "month",
                "operator_count", "rolling_avg_downtime_7d"]
    target = "downtime_minutes"

    X = df[features].values
    y = df[target].values
    split = int(len(df) * TRAIN_RATIO)

    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    model = RandomForestRegressor(
        n_estimators=100, max_depth=10, random_state=42, n_jobs=-1,
    )
    model.fit(X_train, y_train)
    preds = model.predict(X_test)

    mae = float(mean_absolute_error(y_test, preds))
    r2 = float(r2_score(y_test, preds))

    imp = sorted(zip(features, model.feature_importances_),
                 key=lambda x: x[1], reverse=True)

    joblib.dump(model, MODELS_DIR / "downtime_predictor.pkl")

    return {
        "model": "RandomForest",
        "target": target,
        "mae": round(mae, 2),
        "r2_score": round(r2, 4),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "feature_importance": {f: round(float(v), 4) for f, v in imp},
        "predictions_test": preds.tolist(),
        "actuals_test": y_test.tolist(),
    }


# ── 2. Defect Rate Predictor ──────────────────────────────────────────────
def train_defect_predictor(df: pd.DataFrame) -> dict:
    features = ["line_enc", "brand_enc", "shift", "operator_count",
                "downtime_minutes", "changeover_minutes", "month"]
    target = "defect_rate"

    X = df[features].values
    y = df[target].values
    split = int(len(df) * TRAIN_RATIO)

    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    model = GradientBoostingRegressor(
        n_estimators=200, learning_rate=0.1, max_depth=5, random_state=42,
    )
    model.fit(X_train, y_train)
    preds = model.predict(X_test)

    mae = float(mean_absolute_error(y_test, preds))
    r2 = float(r2_score(y_test, preds))

    imp = sorted(zip(features, model.feature_importances_),
                 key=lambda x: x[1], reverse=True)

    joblib.dump(model, MODELS_DIR / "defect_predictor.pkl")

    return {
        "model": "GradientBoosting",
        "target": target,
        "mae": round(mae, 4),
        "r2_score": round(r2, 4),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "feature_importance": {f: round(float(v), 4) for f, v in imp},
    }


# ── 3. Anomaly Detector ───────────────────────────────────────────────────
def train_anomaly_detector(df: pd.DataFrame) -> dict:
    features = ["oee_score", "downtime_minutes", "defect_qty", "actual_qty"]
    X = df[features].values

    model = IsolationForest(
        contamination=0.05, random_state=42, n_jobs=-1,
    )
    labels = model.fit_predict(X)  # -1 = anomaly, 1 = normal

    df["anomaly"] = labels
    anomalies = df[df["anomaly"] == -1]
    n_anomalies = len(anomalies)

    # Top 5 most anomalous (by decision function score)
    scores = model.decision_function(X)
    df["anomaly_score"] = scores
    top5 = df.nsmallest(5, "anomaly_score")
    top5_records = []
    for _, row in top5.iterrows():
        top5_records.append({
            "date": str(row["date"].date()),
            "line_id": row["line_id"],
            "brand": row["brand"],
            "shift": int(row["shift"]),
            "oee_score": round(float(row["oee_score"]), 4),
            "downtime_minutes": int(row["downtime_minutes"]),
            "defect_qty": int(row["defect_qty"]),
            "anomaly_score": round(float(row["anomaly_score"]), 4),
        })

    joblib.dump(model, MODELS_DIR / "anomaly_detector.pkl")

    return {
        "model": "IsolationForest",
        "contamination": 0.05,
        "total_records": len(df),
        "anomalies_detected": n_anomalies,
        "anomaly_pct": round(n_anomalies / len(df) * 100, 1),
        "top_5_anomalies": top5_records,
        "anomaly_labels": labels.tolist(),
        "anomaly_scores": scores.tolist(),
    }


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK — OEE Dashboard — Predictive Analytics{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}\n")

    df, le_line, le_brand = _prepare_data()

    # 1. Downtime
    print(f"  {BOLD}1. Downtime Predictor (RandomForest){RESET}")
    dt_result = train_downtime_predictor(df)
    print(f"     MAE:      {GREEN}{dt_result['mae']:.2f} min{RESET}")
    print(f"     R² Score: {GREEN}{dt_result['r2_score']:.4f}{RESET}")
    print(f"     Top 5 features:")
    for f, v in list(dt_result["feature_importance"].items())[:5]:
        bar = "█" * int(v * 60)
        print(f"       {f:<28s} {v:.4f}  {DIM}{bar}{RESET}")

    # 2. Defect rate
    print(f"\n  {BOLD}2. Defect Rate Predictor (GradientBoosting){RESET}")
    def_result = train_defect_predictor(df)
    print(f"     MAE:      {GREEN}{def_result['mae']:.4f}{RESET}")
    print(f"     R² Score: {GREEN}{def_result['r2_score']:.4f}{RESET}")
    print(f"     Top 5 features:")
    for f, v in list(def_result["feature_importance"].items())[:5]:
        bar = "█" * int(v * 60)
        print(f"       {f:<28s} {v:.4f}  {DIM}{bar}{RESET}")

    # 3. Anomaly detection
    print(f"\n  {BOLD}3. Anomaly Detector (IsolationForest){RESET}")
    anom_result = train_anomaly_detector(df)
    print(f"     Anomalije: {RED}{anom_result['anomalies_detected']}{RESET} "
          f"/ {anom_result['total_records']} ({anom_result['anomaly_pct']}%)")
    print(f"     Top 5 anomalija:")
    for a in anom_result["top_5_anomalies"]:
        print(f"       {a['date']}  {a['line_id']}  {a['brand']:<10s}  "
              f"OEE={a['oee_score']:.2f}  downtime={a['downtime_minutes']}min  "
              f"defects={a['defect_qty']}  score={a['anomaly_score']:.4f}")

    # Save results (without large arrays for JSON readability)
    save_dt = {k: v for k, v in dt_result.items() if k not in ("predictions_test", "actuals_test")}
    save_anom = {k: v for k, v in anom_result.items() if k not in ("anomaly_labels", "anomaly_scores")}
    results = {
        "downtime_predictor": save_dt,
        "defect_predictor": def_result,
        "anomaly_detector": save_anom,
    }
    with open(RESULT_DIR / "predictive_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n  {DIM}Models saved → {MODELS_DIR}/{RESET}")
    print(f"  {DIM}Results saved → {RESULT_DIR}/predictive_results.json{RESET}")
    print(f"\n{'=' * 70}\n")

    # Return for use by visualizations
    return dt_result, def_result, anom_result, df


if __name__ == "__main__":
    main()
