#!/bin/bash
# Double-click this on a Mac to start the Pulse Admin Insights Pack app.
# The first run sets things up (a minute or two). Every run after that is instant.
cd "$(dirname "$0")" || exit 1

if [ ! -d ".venv" ]; then
  echo "First-time setup: creating a private workspace and downloading two small helpers..."
  echo "(This happens once and takes a minute or two.)"
  echo
  if ! python3 -m venv .venv; then
    echo
    echo "Python 3 was not found. Install it free from https://www.python.org/downloads/"
    echo "then double-click this file again."
    echo
    read -n 1 -s -r -p "Press any key to close."
    exit 1
  fi
  ./.venv/bin/pip install -q -r requirements.txt
  echo "Setup done."
  echo
fi

echo "Starting the app. Your browser will open in a moment."
echo "Leave this window open while you use the app. Close it (or press Ctrl+C) when you're finished."
echo
./.venv/bin/python app.py
