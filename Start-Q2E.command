#!/bin/bash
# =====================================================================
#  Q2E launcher for Mac (and Linux). Double-click this file.
#  First run installs everything it needs (5-15 minutes). Later runs start in seconds.
#  To stop Q2E, close this window.
# =====================================================================
cd "$(dirname "$0")" || exit 1
echo ""
echo "  Q2E - Question to Evidence"
echo "  ------------------------------------------------------------"

# 1. Python
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "  Python 3.10 or newer is not installed."
  echo "  Install it from https://www.python.org/downloads/ and double-click this file again."
  open "https://www.python.org/downloads/" 2>/dev/null || xdg-open "https://www.python.org/downloads/" 2>/dev/null
  read -r -p "  Press Enter to close..." _; exit 1
fi

# 2. R
RS=""
if command -v Rscript >/dev/null 2>&1; then RS="Rscript"
elif [ -x /usr/local/bin/Rscript ]; then RS="/usr/local/bin/Rscript"
elif [ -x /Library/Frameworks/R.framework/Resources/bin/Rscript ]; then RS="/Library/Frameworks/R.framework/Resources/bin/Rscript"
fi
if [ -z "$RS" ]; then
  echo "  R is not installed."
  echo "  Install it from https://cloud.r-project.org/ (choose 'Download R for macOS') and double-click this file again."
  open "https://cloud.r-project.org/" 2>/dev/null || xdg-open "https://cloud.r-project.org/" 2>/dev/null
  read -r -p "  Press Enter to close..." _; exit 1
fi
export Q2E_RSCRIPT="$RS"

# 3. One-time setup
if [ ! -f ".venv/.q2e_ready" ]; then
  echo "  First-time setup: installing Python components..."
  "$PY" -m venv .venv || { echo "  Could not create a Python environment."; read -r -p "  Press Enter to close..." _; exit 1; }
  ./.venv/bin/python -m pip install --quiet --upgrade pip
  ./.venv/bin/python -m pip install --quiet -r requirements.txt || { echo "  Python install failed (check your internet connection)."; read -r -p "  Press Enter to close..." _; exit 1; }
  echo "  First-time setup: installing R statistics packages (this is the slow part)..."
  "$RS" r/install_packages.R || { echo "  R package install failed (check your internet connection)."; read -r -p "  Press Enter to close..." _; exit 1; }
  touch .venv/.q2e_ready
fi
if [ ! -f "data/synthetic/P_DEMO.xpt" ]; then
  echo "  Creating the synthetic demo dataset..."
  "$RS" r/synth/make_synthetic_nhanes.R data/synthetic 12000 20261010 >/dev/null
fi
mkdir -p data/nhanes workspace

# 4. Start and open the browser
echo ""
echo "  Starting Q2E at http://127.0.0.1:8000"
echo "  Keep this window open while you use Q2E. Close it to stop."
echo ""
( for i in $(seq 1 30); do
    sleep 1
    if curl -s -o /dev/null http://127.0.0.1:8000/ 2>/dev/null; then
      open "http://127.0.0.1:8000" 2>/dev/null || xdg-open "http://127.0.0.1:8000" 2>/dev/null; break
    fi
  done ) &
./.venv/bin/python -m q2e serve --port 8000
