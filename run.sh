#!/usr/bin/env bash
# Quickstart script for Triage3AM

echo "=========================================="
echo "🚨 Starting Triage3AM (Protothon 2026)"
echo "Finding the signal in 10,000 log lines"
echo "=========================================="

cd "$(dirname "$0")"

# Generate test datasets if not already present
if [ ! -f "datasets/ecommerce_cascade_10k.log" ]; then
    echo "📦 Generating 10,000-line sample datasets..."
    python3 sample_generator.py
fi

# Run test suite
echo "🧪 Running automated test suite..."
python3 test_triage.py

if [ $? -ne 0 ]; then
    echo "❌ Tests failed!"
    exit 1
fi

echo "✅ All tests passed!"
echo ""
echo "🚀 Launching Web Dashboard on http://localhost:8000 ..."
python3 server.py
