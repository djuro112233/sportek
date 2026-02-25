"""
Sportek d.o.o. — CV Quality Control Module
Training pipeline for defect detection classifier.

Loads synthetic defect/ok images, extracts handcrafted features,
trains multiple sklearn classifiers, selects best by F1, and persists
the winning model + scaler.
"""

import json
import os
import sys
import time
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = PROJECT_ROOT / "data" / "quality" / "defect_images"
MODEL_DIR = Path(__file__).resolve().parent / "models"
RESULT_DIR = Path(__file__).resolve().parent / "results"

MODEL_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)

IMG_SIZE = (64, 64)
HIST_BINS = 16
RANDOM_STATE = 42

# Sportek brand colours for plots
NAVY = "#1B2A4A"
TEAL = "#0891B2"
LIGHT_TEAL = "#67E8F9"
LIGHT_NAVY = "#3B5998"


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------
def extract_features(image_path: str | Path) -> np.ndarray:
    """Return a ~60-dim feature vector from a single image.

    Features:
      - mean R, G, B                     (3)
      - std  R, G, B                     (3)
      - histogram per channel (16 bins)  (48)
      - edge density (Sobel-like)        (1)
      - texture variance per channel     (3)
      - brightness                       (1)
      - contrast (max-min per channel)   (3)
    Total: 62 features
    """
    img = Image.open(image_path).convert("RGB").resize(IMG_SIZE)
    arr = np.array(img, dtype=np.float64)  # (64, 64, 3)

    features = []

    # Per-channel statistics
    for c in range(3):
        ch = arr[:, :, c]
        features.append(ch.mean())
        features.append(ch.std())

    # Histograms (16 bins per channel, normalised)
    for c in range(3):
        hist, _ = np.histogram(arr[:, :, c], bins=HIST_BINS, range=(0, 256))
        hist = hist / hist.sum()
        features.extend(hist.tolist())

    # Edge density — simple Sobel-like gradient magnitude on grayscale
    gray = arr.mean(axis=2)
    gx = np.diff(gray, axis=1)  # horizontal gradient
    gy = np.diff(gray, axis=0)  # vertical gradient
    # Trim to same shape
    gx = gx[: gy.shape[0], : gy.shape[1]]
    gy = gy[: gx.shape[0], : gx.shape[1]]
    edge_mag = np.sqrt(gx ** 2 + gy ** 2)
    features.append(edge_mag.mean())

    # Texture variance (local variance via sliding approach — approximate)
    for c in range(3):
        ch = arr[:, :, c]
        # Variance of 4×4 patch means vs global
        patches = ch[: (ch.shape[0] // 4) * 4, : (ch.shape[1] // 4) * 4]
        patches = patches.reshape(ch.shape[0] // 4, 4, ch.shape[1] // 4, 4)
        patch_means = patches.mean(axis=(1, 3))
        features.append(patch_means.var())

    # Brightness (mean of grayscale)
    features.append(gray.mean())

    # Contrast (range per channel)
    for c in range(3):
        ch = arr[:, :, c]
        features.append(ch.max() - ch.min())

    return np.array(features, dtype=np.float64)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_dataset(image_dir: Path):
    """Walk image_dir and return feature matrix X and label vector y."""
    X_list, y_list, paths = [], [], []

    for fname in sorted(os.listdir(image_dir)):
        if not fname.endswith(".png"):
            continue
        fpath = image_dir / fname
        label = 1 if fname.startswith("defect_") else 0  # 1=defect, 0=ok
        feats = extract_features(fpath)
        X_list.append(feats)
        y_list.append(label)
        paths.append(str(fpath))

    return np.vstack(X_list), np.array(y_list), paths


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------
def plot_confusion_matrix(cm, labels, save_path):
    """Render a professional confusion-matrix heatmap in Sportek brand colours."""
    fig, ax = plt.subplots(figsize=(7, 6))

    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("sportek", [LIGHT_TEAL, TEAL, NAVY])

    im = ax.imshow(cm, interpolation="nearest", cmap=cmap)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.ax.tick_params(labelsize=11)

    ax.set(
        xticks=range(len(labels)),
        yticks=range(len(labels)),
        xticklabels=labels,
        yticklabels=labels,
    )
    ax.set_xlabel("Predicted", fontsize=13, fontweight="bold", color=NAVY, labelpad=10)
    ax.set_ylabel("Actual", fontsize=13, fontweight="bold", color=NAVY, labelpad=10)
    ax.set_title(
        "Sportek QC — Defect Detection Confusion Matrix",
        fontsize=14,
        fontweight="bold",
        color=NAVY,
        pad=16,
    )
    ax.tick_params(labelsize=12)

    # Annotate cells
    thresh = cm.max() / 2
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            colour = "white" if cm[i, j] > thresh else NAVY
            ax.text(j, i, f"{cm[i, j]}", ha="center", va="center",
                    fontsize=20, fontweight="bold", color=colour)

    fig.tight_layout()
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Confusion matrix saved → {save_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 65)
    print("  SPORTEK d.o.o. — CV Quality Module — Training Pipeline")
    print("=" * 65)

    # ---- Load data --------------------------------------------------------
    print(f"\n[1/5] Loading images from {IMAGE_DIR} ...")
    t0 = time.time()
    X, y, paths = load_dataset(IMAGE_DIR)
    print(f"  Loaded {len(y)} images  ({(y == 1).sum()} defect, {(y == 0).sum()} ok)")
    print(f"  Feature vector length: {X.shape[1]}")
    print(f"  Load time: {time.time() - t0:.1f}s")

    # ---- Split ------------------------------------------------------------
    print("\n[2/5] Train/val split (80/20, stratified) ...")
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y,
    )
    print(f"  Train: {len(y_train)} samples  |  Val: {len(y_val)} samples")

    # ---- Scale ------------------------------------------------------------
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_val_s = scaler.transform(X_val)

    # ---- Train models -----------------------------------------------------
    print("\n[3/5] Training 3 classifiers ...")
    models = {
        "RandomForest": RandomForestClassifier(
            n_estimators=200, max_depth=10, random_state=RANDOM_STATE,
        ),
        "SVM_RBF": SVC(
            kernel="rbf", C=10, gamma="scale", probability=True,
            random_state=RANDOM_STATE,
        ),
        "GradientBoosting": GradientBoostingClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1,
            random_state=RANDOM_STATE,
        ),
    }

    results = {}
    for name, clf in models.items():
        t0 = time.time()
        clf.fit(X_train_s, y_train)
        y_pred = clf.predict(X_val_s)
        elapsed = time.time() - t0

        acc = accuracy_score(y_val, y_pred)
        prec = precision_score(y_val, y_pred, zero_division=0)
        rec = recall_score(y_val, y_pred, zero_division=0)
        f1 = f1_score(y_val, y_pred, zero_division=0)

        results[name] = {
            "model": clf,
            "accuracy": round(acc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "train_time_s": round(elapsed, 2),
            "y_pred": y_pred,
        }
        print(f"  {name:20s}  acc={acc:.2f}  prec={prec:.2f}  "
              f"rec={rec:.2f}  F1={f1:.2f}  ({elapsed:.2f}s)")

    # ---- Best model -------------------------------------------------------
    print("\n[4/5] Selecting best model by F1 score ...")
    best_name = max(results, key=lambda k: results[k]["f1"])
    best = results[best_name]
    print(f"  Winner: {best_name}  (F1 = {best['f1']})")

    # ---- Save artefacts ---------------------------------------------------
    print("\n[5/5] Saving artefacts ...")

    model_path = MODEL_DIR / "defect_classifier.pkl"
    scaler_path = MODEL_DIR / "scaler.pkl"
    joblib.dump(best["model"], model_path)
    joblib.dump(scaler, scaler_path)
    print(f"  Model  → {model_path}")
    print(f"  Scaler → {scaler_path}")

    # Metrics JSON
    metrics = {
        "best_model": best_name,
        "accuracy": best["accuracy"],
        "precision": best["precision"],
        "recall": best["recall"],
        "f1": best["f1"],
        "train_size": len(y_train),
        "val_size": len(y_val),
        "feature_count": X.shape[1],
        "all_models": {
            n: {k: v for k, v in r.items() if k not in ("model", "y_pred")}
            for n, r in results.items()
        },
    }
    metrics_path = RESULT_DIR / "training_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"  Metrics → {metrics_path}")

    # Confusion matrix plot
    cm = confusion_matrix(y_val, best["y_pred"])
    cm_path = RESULT_DIR / "confusion_matrix.png"
    plot_confusion_matrix(cm, labels=["OK", "Defect"], save_path=cm_path)

    # ---- Summary ----------------------------------------------------------
    print("\n" + "=" * 65)
    print("  TRAINING COMPLETE")
    print("=" * 65)
    print(f"  Best model : {best_name}")
    print(f"  Accuracy   : {best['accuracy']}")
    print(f"  Precision  : {best['precision']}")
    print(f"  Recall     : {best['recall']}")
    print(f"  F1 Score   : {best['f1']}")
    print(f"  Train/Val  : {len(y_train)} / {len(y_val)}")
    print("=" * 65)


if __name__ == "__main__":
    main()
