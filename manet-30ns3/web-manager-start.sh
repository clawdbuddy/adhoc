#!/bin/bash
# web-manager-start.sh - Launch the Web Management Panel locally
#
# This starts a simple HTTP server to serve the management panel.
# The panel provides:
#   - Visual configuration of all simulation parameters
#   - Preset scene selection (Default, Urban, Rural, Debug)
#   - Export configuration to .conf and .sh files
#   - Real-time node topology visualization
#   - Flow statistics and monitoring
#
# Usage: ./web-manager-start.sh [port]

PORT=${1:-8080}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGER_DIR="${SCRIPT_DIR}/web-manager"

if [ ! -d "${MANAGER_DIR}" ]; then
    echo "ERROR: web-manager directory not found at ${MANAGER_DIR}"
    echo "Please ensure the web manager has been built."
    exit 1
fi

echo "========================================"
echo "  NS-3 AdHoc Web Manager"
echo "========================================"
echo "  URL: http://localhost:${PORT}"
echo "  Dir: ${MANAGER_DIR}"
echo ""
echo "  Features:"
echo "    - Parameter configuration (80+ params)"
echo "    - Preset: Default, Urban, Rural, Debug"
echo "    - Export: .conf file + .sh launch script"
echo "    - Real-time topology + flow stats"
echo ""
echo "  Press Ctrl+C to stop"
echo "========================================"

cd "${MANAGER_DIR}"

# Try python3 first, then python, then fallback
if command -v python3 &> /dev/null; then
    python3 -m http.server ${PORT}
elif command -v python &> /dev/null; then
    python -m SimpleHTTPServer ${PORT}
else
    echo "ERROR: Python not found. Please install Python 3."
    exit 1
fi
