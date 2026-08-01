#!/bin/bash
# SHEET auto FILL — start the app on macOS. Double-click this file.
set -u
cd "$(dirname "$0")/.." || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo "Setup hasn't been run yet."
    echo "Double-click  mac/install_mac.command  first."
    read -r -p "Press Return to close."
    exit 1
fi

echo "Starting SHEET auto FILL…"
echo "(Closing this Terminal window quits the app.)"
exec ./.venv/bin/python desktop.py
