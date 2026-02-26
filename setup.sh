#!/bin/bash
set -e

echo "============================================"
echo "  SPORTEK AI PLATFORM — Setup"
echo "============================================"
echo ""

echo "Installing dependencies..."
pip install pandas numpy scikit-learn joblib fastapi uvicorn matplotlib seaborn --break-system-packages -q
echo "  ✓ Dependencies installed"
echo ""

echo "Checking data..."
for f in data/production/production_log.csv data/quality/defect_log.csv data/supply_chain/inventory.csv; do
  if [ -f "$f" ]; then
    echo "  ✓ $f"
  else
    echo "  ✗ MISSING: $f"
  fi
done
echo ""

echo "Setup complete."
