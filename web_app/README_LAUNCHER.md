macOS One-Click Launcher

This directory contains `run_web_app.command` — a double-clickable launcher for macOS that starts the local Flask web UI for the unified pipeline.

How to use

1. Make the launcher executable (only needed once):

```bash
cd web_app
chmod +x run_web_app.command
```

2. Double-click `run_web_app.command` in Finder. A Terminal window will open and run the launcher.

What the launcher does

- cd's to project root
- activates `.venv` if present
- runs `python web_app/app.py` (the Flask web app)
- opens http://127.0.0.1:8501 in your default browser

If you prefer an app bundle (double-click an Application icon):

- Open `Automator` on macOS
- Create a new `Application`
- Add `Run Shell Script` action
- Paste the contents of `run_web_app.command` into the shell field
- Save as `Unified Pipeline.app` and double-click to run

Notes

- The launcher runs locally and does not expose the app to the network. Keep it on your machine.
- If you update the pipeline code, stop the Terminal and re-run the launcher to pick up changes.
