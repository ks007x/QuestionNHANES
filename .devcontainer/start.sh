#!/usr/bin/env bash
# Starts the Q2E web app. Codespaces shows it in a browser tab (Ports tab -> 8000 -> globe icon).
cd "$(dirname "$0")/.."
if curl -s -o /dev/null http://127.0.0.1:8000/; then echo "Q2E is already running on port 8000."; exit 0; fi
echo "Starting Q2E on port 8000 - a browser tab will open; if not, open the PORTS tab and click the globe next to 8000."
exec python3 -m q2e serve --host 0.0.0.0 --port 8000
