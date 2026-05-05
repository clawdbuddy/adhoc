#!/bin/bash
# MANET WiFi 频段 / 带宽 / 距离 / Adhoc 完整测试入口脚本
#
# Usage:
#   ./tests/run_all_tests.sh [CONTROLLER_URL]
#
# Environment:
#   CONTROLLER_URL  - 控制器 REST API 地址（默认: http://localhost:8000）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONTROLLER_URL="${1:-http://localhost:8000}"

echo "========================================"
echo "  MANET WiFi Test Suite"
echo "  Controller: $CONTROLLER_URL"
echo "========================================"

# 1. Health check
echo ""
echo "[1/4] Health check..."
if ! curl -sf "${CONTROLLER_URL}/api/health" > /dev/null 2>&1; then
    echo "ERROR: Controller not reachable at $CONTROLLER_URL"
    echo "Hint: docker compose up -d ns3-controller"
    exit 1
fi
echo "  OK"

# 2. Ensure no residual simulation
echo ""
echo "[2/4] Cleaning up any residual simulation..."
curl -sf -X POST "${CONTROLLER_URL}/api/sim/stop" > /dev/null 2>&1 || true
sleep 2
echo "  OK"

# 3. Run test suite
echo ""
echo "[3/4] Running WiFi test suite..."
cd "$PROJECT_DIR"
python3 tests/wifi_test_suite.py --url "$CONTROLLER_URL" all

# 4. Generate report
echo ""
echo "[4/4] Generating report..."
python3 tests/generate_report.py

echo ""
echo "========================================"
echo "  Test run complete"
echo "  Results: $PROJECT_DIR/test-results/"
echo "========================================"
