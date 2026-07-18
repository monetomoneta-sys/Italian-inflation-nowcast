#!/bin/sh
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
echo "Installazione completata. Avvia con: ./AVVIA_MAC_LINUX.sh"
