#!/bin/bash
# One-click launcher for macOS - double-click this file in Finder (after making it executable: chmod +x run_web_app.command)

# Change to project root
DIR="$(cd "$(dirname "$0")" && pwd)/.."
cd "$DIR"

# Activate virtual environment if present
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

# Start the Flask app in this terminal window
echo "Starting Unified Pipeline web app..."
python web_app/app.py

# Open browser (optional, app already prints URL)
open http://127.0.0.1:8501
