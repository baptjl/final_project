#!/bin/bash
set -e

# Build a double-clickable macOS application that launches the web UI.
# Usage: ./build_automator_app.sh

ROOT="$(cd "$(dirname "$0")" && pwd)/.."
APP_NAME="Unified Pipeline.app"
OUT_APP="$ROOT/web_app/$APP_NAME"

echo "Building Automator app at: $OUT_APP"

ASCRIPT_FILE="$(mktemp /tmp/run_web_app.XXXX.applescript)"

cat > "$ASCRIPT_FILE" <<'APPLESCRIPT'
do shell script "cd '<<ROOT>>' && chmod +x web_app/run_web_app.command && nohup ./web_app/run_web_app.command >/tmp/unified_pipeline_launcher.log 2>&1 &"
APPLESCRIPT

# Replace placeholder with actual ROOT path
perl -pi -e "s#<<ROOT>>#$ROOT#g" "$ASCRIPT_FILE"

# Compile to application bundle
if command -v osacompile >/dev/null 2>&1; then
  osacompile -o "$OUT_APP" "$ASCRIPT_FILE"
  echo "Created application: $OUT_APP"
else
  echo "osacompile not found. Please open the file $ASCRIPT_FILE in Script Editor and save as an application named '$APP_NAME' to $ROOT/web_app/"
fi

rm -f "$ASCRIPT_FILE"
