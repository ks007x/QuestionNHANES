#!/usr/bin/env bash
# One-time setup for GitHub Codespaces: Python + R packages + synthetic demo data.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo_() { if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" != 0 ]; then sudo "$@"; else "$@"; fi; }
sudo_ apt-get update -qq
sudo_ apt-get install -y -qq --no-install-recommends python3 python3-pip python3-venv curl unzip >/dev/null
python3 -m pip install -q --upgrade pip || true
python3 -m pip install -q -r requirements.txt || python3 -m pip install -q --break-system-packages -r requirements.txt
# rocker images point R at prebuilt Linux binaries, so this takes ~1-2 minutes
Rscript r/install_packages.R
Rscript r/synth/make_synthetic_nhanes.R data/synthetic 12000 20261010
mkdir -p workspace data/nhanes data/cache
echo "Setup complete."
