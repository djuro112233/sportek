"""
Sportek d.o.o. — CV Quality Module — Real-time QC Station Simulator
Simulates a production-line camera station running AI defect detection.

Usage:
    python modules/01_cv_quality/simulate_line.py          # 20 iterations
    python modules/01_cv_quality/simulate_line.py --count 50
"""

import argparse
import csv
import os
import random
import time
from datetime import datetime
from pathlib import Path

from inference import DefectDetector

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
IMAGE_DIR = PROJECT_ROOT / "data" / "quality" / "defect_images"
LOG_PATH = MODULE_DIR / "results" / "realtime_log.csv"

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def run_simulation(n_iterations: int = 20, delay: float = 2.0) -> None:
    """Run *n_iterations* rounds of simulated real-time QC inspection."""

    # Load detector
    detector = DefectDetector()
    detector.load_model()

    # Collect all images
    images = sorted(f for f in os.listdir(IMAGE_DIR) if f.endswith(".png"))
    if not images:
        print(f"{RED}No images found in {IMAGE_DIR}{RESET}")
        return

    # Prepare CSV log
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0
    log_file = open(LOG_PATH, "a", newline="")
    writer = csv.writer(log_file)
    if write_header:
        writer.writerow([
            "timestamp", "image", "prediction", "confidence",
            "processing_time_ms", "actual_label", "correct",
        ])

    # Counters
    ok_count = 0
    defect_count = 0

    print()
    print(f"{BOLD}{CYAN}{'=' * 75}{RESET}")
    print(f"{BOLD}{CYAN}  SPORTEK QC — Real-time Line Simulator  ({n_iterations} iteracija){RESET}")
    print(f"{BOLD}{CYAN}{'=' * 75}{RESET}")
    print()

    random.seed(None)  # true random each run

    for i in range(1, n_iterations + 1):
        img_name = random.choice(images)
        img_path = IMAGE_DIR / img_name
        actual = "defect" if img_name.startswith("defect_") else "ok"

        result = detector.predict(img_path)
        pred = result["prediction"]
        conf = result["confidence"]
        ms = result["processing_time_ms"]

        if pred == "ok":
            ok_count += 1
        else:
            defect_count += 1

        total = ok_count + defect_count
        defect_pct = defect_count / total * 100

        correct = pred == actual
        now = datetime.now()
        ts = now.strftime("%H:%M:%S")

        # Console output
        if pred == "ok":
            icon = f"{GREEN}✅ OK    {RESET}"
        else:
            icon = f"{RED}❌ DEFECT{RESET}"

        match_str = "" if correct else f"  {RED}[MISS]{RESET}"

        print(
            f"  {DIM}[{ts}]{RESET} "
            f"Slika: {BOLD}{img_name:20s}{RESET} → {icon} "
            f"{DIM}(confidence: {conf:.2f}){RESET} | "
            f"Total: {ok_count}/{total} ok, {defect_count}/{total} defect "
            f"({defect_pct:.1f}%){match_str}"
        )

        # CSV log
        writer.writerow([
            now.isoformat(timespec="milliseconds"),
            img_name,
            pred,
            round(conf, 4),
            round(ms, 2),
            actual,
            correct,
        ])
        log_file.flush()

        if i < n_iterations:
            time.sleep(delay)

    log_file.close()

    # Summary
    print()
    print(f"{BOLD}{CYAN}{'=' * 75}{RESET}")
    print(f"  Ukupno: {total} inspekcija | "
          f"{GREEN}{ok_count} OK{RESET} | "
          f"{RED}{defect_count} DEFECT{RESET} | "
          f"Defect rate: {defect_pct:.1f}%")
    print(f"  Log sačuvan → {LOG_PATH}")
    print(f"{BOLD}{CYAN}{'=' * 75}{RESET}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sportek QC line simulator")
    parser.add_argument("--count", type=int, default=20,
                        help="Number of iterations (default: 20)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Delay between iterations in seconds (default: 2.0)")
    args = parser.parse_args()
    run_simulation(n_iterations=args.count, delay=args.delay)
