"""
Sportek d.o.o. — TradeFlow AI — HS Code Classifier
TF-IDF + RandomForest classifier for 6-digit HS code prediction.

Usage:
    python modules/02_tradeflow/hs_classifier.py
"""

import json
import os
import pickle
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    top_k_accuracy_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "compliance" / "hs_classifications.csv"
MODEL_DIR = MODULE_DIR / "models"
RESULT_DIR = MODULE_DIR / "results"

# HS code human-readable names
HS_NAMES = {
    "640110": "Waterproof rubber/plastic footwear",
    "640299": "Rubber/plastic sole & upper, other",
    "640391": "Rubber/plastic sole, leather upper, ankle",
    "640411": "Sports footwear, textile upper",
    "640419": "Other footwear, textile upper",
    "640420": "Leather sole, textile upper",
    "640520": "Textile upper, other sole",
    "640610": "Uppers and parts thereof",
    "640620": "Outer soles and heels",
    "640699": "Parts of footwear, other",
}


class HSClassifier:
    """HS tariff code classifier using TF-IDF + RandomForest."""

    def __init__(self):
        self.vectorizer: TfidfVectorizer | None = None
        self.model: RandomForestClassifier | None = None
        self.label_encoder: LabelEncoder | None = None
        self.classes_: list[str] = []

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def train(self, data_path: str | Path | None = None) -> dict:
        """Train on *data_path* CSV. Returns metrics dict."""
        data_path = Path(data_path or DATA_PATH)
        df = pd.read_csv(data_path)

        # Ensure HS codes are strings (6-digit)
        df["correct_hs_code"] = df["correct_hs_code"].astype(str).str.zfill(6)

        X_text = df["product_description"].values
        y = df["correct_hs_code"].values

        # Label encoding
        self.label_encoder = LabelEncoder()
        y_enc = self.label_encoder.fit_transform(y)
        self.classes_ = list(self.label_encoder.classes_)

        # TF-IDF
        self.vectorizer = TfidfVectorizer(
            max_features=500,
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
        )

        # Train/test split — stratified
        X_train_txt, X_test_txt, y_train, y_test = train_test_split(
            X_text, y_enc, test_size=0.20, random_state=42, stratify=y_enc
        )

        X_train = self.vectorizer.fit_transform(X_train_txt)
        X_test = self.vectorizer.transform(X_test_txt)

        # RandomForest
        self.model = RandomForestClassifier(
            n_estimators=200,
            max_depth=None,
            min_samples_split=3,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        self.model.fit(X_train, y_train)

        # Evaluate
        y_pred = self.model.predict(X_test)
        y_proba = self.model.predict_proba(X_test)

        acc = accuracy_score(y_test, y_pred)
        top3 = top_k_accuracy_score(y_test, y_proba, k=min(3, len(self.classes_)))

        metrics = {
            "accuracy": round(acc, 4),
            "top3_accuracy": round(top3, 4),
            "total_classes": len(self.classes_),
            "train_size": int(len(y_train)),
            "test_size": int(len(y_test)),
        }

        # Save artefacts
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        RESULT_DIR.mkdir(parents=True, exist_ok=True)

        with open(MODEL_DIR / "hs_classifier.pkl", "wb") as f:
            pickle.dump({"model": self.model, "label_encoder": self.label_encoder}, f)
        with open(MODEL_DIR / "tfidf_vectorizer.pkl", "wb") as f:
            pickle.dump(self.vectorizer, f)

        with open(RESULT_DIR / "hs_metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)

        # Confusion matrix plot
        self._plot_confusion_matrix(y_test, y_pred)

        return metrics

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------
    def predict(self, description: str) -> dict:
        """Predict HS code for a single product description."""
        self._ensure_loaded()

        X = self.vectorizer.transform([description])
        proba = self.model.predict_proba(X)[0]
        sorted_idx = np.argsort(proba)[::-1]

        top_idx = sorted_idx[0]
        top_code = self.classes_[top_idx]

        alternatives = []
        for idx in sorted_idx[1:4]:
            if proba[idx] > 0.01:
                alt_code = self.classes_[idx]
                alternatives.append({
                    "hs_code": alt_code,
                    "description": HS_NAMES.get(alt_code, ""),
                    "confidence": round(float(proba[idx]), 4),
                })

        return {
            "hs_code": top_code,
            "description": HS_NAMES.get(top_code, ""),
            "confidence": round(float(proba[top_idx]), 4),
            "alternatives": alternatives,
        }

    def predict_batch(self, descriptions: list[str]) -> list[dict]:
        """Predict HS codes for a list of descriptions."""
        return [self.predict(d) for d in descriptions]

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------
    def load_model(self) -> None:
        """Load persisted model + vectorizer from disk."""
        with open(MODEL_DIR / "hs_classifier.pkl", "rb") as f:
            bundle = pickle.load(f)
            self.model = bundle["model"]
            self.label_encoder = bundle["label_encoder"]
            self.classes_ = list(self.label_encoder.classes_)
        with open(MODEL_DIR / "tfidf_vectorizer.pkl", "rb") as f:
            self.vectorizer = pickle.load(f)

    def _ensure_loaded(self) -> None:
        if self.model is None:
            self.load_model()

    # ------------------------------------------------------------------
    # Visualisation
    # ------------------------------------------------------------------
    def _plot_confusion_matrix(self, y_true, y_pred) -> None:
        """Save a navy/teal confusion matrix heatmap."""
        cm = confusion_matrix(y_true, y_pred)
        labels = self.classes_

        from matplotlib.colors import LinearSegmentedColormap
        cmap = LinearSegmentedColormap.from_list(
            "navy_teal", ["#FFFFFF", "#B2DFDB", "#00897B", "#004D40", "#0D1B2A"]
        )

        fig, ax = plt.subplots(figsize=(10, 8))
        im = ax.imshow(cm, interpolation="nearest", cmap=cmap)
        plt.colorbar(im, ax=ax, shrink=0.8)

        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        ax.set_yticklabels(labels, fontsize=8)

        # Annotate cells
        thresh = cm.max() / 2
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                colour = "white" if cm[i, j] > thresh else "#0D1B2A"
                ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                        color=colour, fontsize=9, fontweight="bold")

        ax.set_xlabel("Predicted HS Code", fontsize=11)
        ax.set_ylabel("True HS Code", fontsize=11)
        ax.set_title("Sportek TradeFlow — HS Code Classification\nConfusion Matrix",
                      fontsize=13, fontweight="bold", color="#0D1B2A")

        plt.tight_layout()
        plt.savefig(RESULT_DIR / "classification_report.png", dpi=150)
        plt.close()


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
    print(f"{BOLD}{CYAN}  SPORTEK TradeFlow — HS Code Classifier{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")

    clf = HSClassifier()

    # ── Train ──────────────────────────────────────────────────────────
    print(f"\n  {BOLD}[1] Training model ...{RESET}")
    metrics = clf.train()
    print(f"      Accuracy:       {GREEN}{metrics['accuracy']:.2%}{RESET}")
    print(f"      Top-3 accuracy: {GREEN}{metrics['top3_accuracy']:.2%}{RESET}")
    print(f"      Classes:        {metrics['total_classes']}")
    print(f"      Train / test:   {metrics['train_size']} / {metrics['test_size']}")
    print(f"      {DIM}Model  → {MODEL_DIR / 'hs_classifier.pkl'}{RESET}")
    print(f"      {DIM}Metrics→ {RESULT_DIR / 'hs_metrics.json'}{RESET}")
    print(f"      {DIM}Plot   → {RESULT_DIR / 'classification_report.png'}{RESET}")

    # ── Test predictions ───────────────────────────────────────────────
    test_descs = [
        "Men's sports shoes with textile upper and rubber sole for running",
        "Children's waterproof rain boots, fully rubber",
        "Women's leather ankle boots with rubber sole",
        "Rubber outer soles and heels for shoe manufacturing",
        "Textile upper casual sneakers for men, plastic sole",
    ]

    print(f"\n  {BOLD}[2] Test predictions (5 descriptions){RESET}\n")
    for desc in test_descs:
        r = clf.predict(desc)
        alts = ", ".join(f"{a['hs_code']}({a['confidence']:.0%})" for a in r["alternatives"][:2])
        print(f"    {DIM}\"{desc[:60]}...\"{RESET}")
        print(f"      → {GREEN}{r['hs_code']}{RESET} {r['description']}  "
              f"{DIM}(conf: {r['confidence']:.2%}){RESET}"
              f"  alts: [{alts}]")
        print()

    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}\n")


if __name__ == "__main__":
    main()
