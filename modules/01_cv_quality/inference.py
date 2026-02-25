"""
Sportek d.o.o. — CV Quality Control Module
Inference engine for defect detection.

Usage:
    from modules.cv_quality.inference import DefectDetector

    detector = DefectDetector()
    detector.load_model("models/defect_classifier.pkl", "models/scaler.pkl")
    result = detector.predict("path/to/image.png")
"""

import os
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from PIL import Image

# Re-use the same constants as training
IMG_SIZE = (64, 64)
HIST_BINS = 16

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = MODULE_DIR / "models" / "defect_classifier.pkl"
DEFAULT_SCALER_PATH = MODULE_DIR / "models" / "scaler.pkl"


class DefectDetector:
    """Lightweight defect / OK classifier for Sportek QC pipeline."""

    def __init__(self):
        self.model = None
        self.scaler = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Model I/O
    # ------------------------------------------------------------------
    def load_model(
        self,
        model_path: str | Path | None = None,
        scaler_path: str | Path | None = None,
    ) -> None:
        """Load a trained sklearn model and its scaler from disk."""
        model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        scaler_path = Path(scaler_path) if scaler_path else DEFAULT_SCALER_PATH

        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        if not scaler_path.exists():
            raise FileNotFoundError(f"Scaler not found: {scaler_path}")

        self.model = joblib.load(model_path)
        self.scaler = joblib.load(scaler_path)
        self._loaded = True

    # ------------------------------------------------------------------
    # Feature extraction  (mirrors train.py exactly)
    # ------------------------------------------------------------------
    @staticmethod
    def extract_features(image_path: str | Path) -> np.ndarray:
        """Extract the same 62-dim feature vector used during training."""
        img = Image.open(image_path).convert("RGB").resize(IMG_SIZE)
        arr = np.array(img, dtype=np.float64)

        features: list[float] = []

        # Per-channel mean & std (6)
        for c in range(3):
            ch = arr[:, :, c]
            features.append(ch.mean())
            features.append(ch.std())

        # Histogram per channel — 16 bins, normalised (48)
        for c in range(3):
            hist, _ = np.histogram(arr[:, :, c], bins=HIST_BINS, range=(0, 256))
            hist = hist / hist.sum()
            features.extend(hist.tolist())

        # Edge density — Sobel-like gradient on grayscale (1)
        gray = arr.mean(axis=2)
        gx = np.diff(gray, axis=1)
        gy = np.diff(gray, axis=0)
        gx = gx[: gy.shape[0], : gy.shape[1]]
        gy = gy[: gx.shape[0], : gx.shape[1]]
        edge_mag = np.sqrt(gx ** 2 + gy ** 2)
        features.append(edge_mag.mean())

        # Texture variance per channel (3)
        for c in range(3):
            ch = arr[:, :, c]
            patches = ch[: (ch.shape[0] // 4) * 4, : (ch.shape[1] // 4) * 4]
            patches = patches.reshape(ch.shape[0] // 4, 4, ch.shape[1] // 4, 4)
            patch_means = patches.mean(axis=(1, 3))
            features.append(patch_means.var())

        # Brightness (1)
        features.append(gray.mean())

        # Contrast per channel (3)
        for c in range(3):
            ch = arr[:, :, c]
            features.append(ch.max() - ch.min())

        return np.array(features, dtype=np.float64)

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------
    def predict(self, image_path: str | Path) -> dict[str, Any]:
        """Run inference on a single image.

        Returns:
            {"prediction": "defect"|"ok",
             "confidence": float,
             "processing_time_ms": float}
        """
        if not self._loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        t0 = time.perf_counter()

        features = self.extract_features(image_path)
        features_scaled = self.scaler.transform(features.reshape(1, -1))

        pred_label = self.model.predict(features_scaled)[0]
        proba = self.model.predict_proba(features_scaled)[0]
        confidence = float(proba.max())

        elapsed_ms = (time.perf_counter() - t0) * 1000

        return {
            "prediction": "defect" if pred_label == 1 else "ok",
            "confidence": round(confidence, 4),
            "processing_time_ms": round(elapsed_ms, 2),
        }

    def predict_batch(self, folder_path: str | Path) -> list[dict[str, Any]]:
        """Run inference on every .png image in *folder_path*.

        Returns a list of dicts (same schema as predict()) with an added
        ``image`` key holding the filename.
        """
        if not self._loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        folder = Path(folder_path)
        results = []
        for fname in sorted(os.listdir(folder)):
            if not fname.lower().endswith(".png"):
                continue
            res = self.predict(folder / fname)
            res["image"] = fname
            results.append(res)
        return results


# ----------------------------------------------------------------------
# Quick CLI demo
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import random

    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    IMG_DIR = PROJECT_ROOT / "data" / "quality" / "defect_images"

    detector = DefectDetector()
    detector.load_model()

    # Pick 5 random images
    all_imgs = sorted(f for f in os.listdir(IMG_DIR) if f.endswith(".png"))
    random.seed(42)
    sample = random.sample(all_imgs, 5)

    print("=" * 65)
    print("  SPORTEK QC — Inference Demo (5 random images)")
    print("=" * 65)
    for fname in sample:
        res = detector.predict(IMG_DIR / fname)
        actual = "defect" if fname.startswith("defect_") else "ok"
        match = "OK" if res["prediction"] == actual else "MISS"
        print(f"  {fname:20s}  actual={actual:6s}  pred={res['prediction']:6s}  "
              f"conf={res['confidence']:.2f}  {res['processing_time_ms']:5.1f}ms  [{match}]")
    print("=" * 65)
