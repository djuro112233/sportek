#!/bin/bash

echo "============================================"
echo "  SPORTEK AI PLATFORM — Start"
echo "============================================"
echo ""

export PYTHONPATH="${PYTHONPATH}:$(pwd)"

echo "Dashboard: open dashboard/index.html in browser"
echo "API:       http://localhost:8000/docs"
echo ""

python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
