#!/bin/bash
# SHEET auto FILL — one-time setup on macOS.
# Double-click this file. It creates a private Python environment inside this
# folder and installs everything the app needs. Nothing is installed system-wide.
set -u
cd "$(dirname "$0")/.." || exit 1

echo "=============================================="
echo "  SHEET auto FILL — setting up (one time)"
echo "=============================================="
echo

PY=""
for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done

if [ -z "$PY" ]; then
    echo "Python 3 isn't installed yet."
    echo
    echo "Install it in one of these ways, then run this file again:"
    echo "  * Easiest: download from https://www.python.org/downloads/macos/"
    echo "  * Or, in Terminal:  xcode-select --install"
    echo
    read -r -p "Press Return to close."
    exit 1
fi

echo "Using $($PY --version)"

# The OCR engine ships prebuilt wheels only for released Python versions; a very
# new one has none and pip would try (and fail) to compile from source.
PYMINOR=$("$PY" -c 'import sys; print(sys.version_info[1])')
if [ "$PYMINOR" -ge 13 ]; then
    echo
    echo "NOTE: Python 3.$PYMINOR is newer than some packages provide builds for."
    echo "      If the install fails below, install Python 3.12 from"
    echo "      https://www.python.org/downloads/macos/ and run this again."
fi
echo

if [ ! -d ".venv" ]; then
    echo "Creating a private environment (.venv)…"
    "$PY" -m venv .venv || { echo "Could not create the environment."; read -r -p "Press Return."; exit 1; }
fi

echo "Installing the packages — this takes a few minutes the first time…"
./.venv/bin/python -m pip install --upgrade pip >/dev/null
if ! ./.venv/bin/python -m pip install -r requirements.txt; then
    echo
    echo "Something failed while installing. Scroll up for the first red error"
    echo "and send it over — that message says exactly what is missing."
    read -r -p "Press Return to close."
    exit 1
fi

chmod +x mac/run_mac.command 2>/dev/null

echo
echo "=============================================="
echo "  Setup finished."
echo "  Now double-click:  mac/run_mac.command"
echo "=============================================="
read -r -p "Press Return to close."
