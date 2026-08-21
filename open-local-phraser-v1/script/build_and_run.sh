#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="$ROOT_DIR/release/Pari.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/OpenLocalPhraserV2"

if [[ ! -x "$APP_BINARY" ]]; then
  echo "Pari.app is not built at $APP_BUNDLE. Run npm run build:desktop first." >&2
  exit 1
fi

case "$MODE" in
  run)
    /usr/bin/open -n "$APP_BUNDLE"
    ;;
  headless|--headless)
    # This uses a separate hidden WebKit instance and never activates or
    # closes the user's visible Pari window.
    "$APP_BINARY" --headless
    ;;
  headless-connected|--headless-connected)
    # Installed connected-path probe: keep the checkpoint outside the app
    # bundle and point this one hidden request at the separately installed
    # development model directory.
    env PARI_NATIVE_MODEL_PATH="$ROOT_DIR/native-models/Qwen/Qwen3-4B-MLX-4bit" \
      "$APP_BINARY" --headless --headless-require-native
    ;;
  headless-custom|--headless-custom)
    # Installed integration probe for an agent-created saved mode.
    "$APP_BINARY" --headless --headless-custom-style
    ;;
  headless-missing-model|--headless-missing-model)
    # Installed recovery probe: point only this hidden smoke request at a
    # deliberately absent native bundle and verify the deterministic fallback.
    "$APP_BINARY" --headless --headless-missing-model
    ;;
  verify|--verify)
    "$APP_BINARY" --headless
    ;;
  agent-style-backend|--agent-style-backend)
    IDLE_TIMEOUT_SECONDS="${PARI_AGENT_STYLE_IDLE_TIMEOUT_SECONDS:-600}"
    "$APP_BINARY" --agent-style-backend --idle-timeout-seconds "$IDLE_TIMEOUT_SECONDS"
    ;;
  logs|--logs)
    /usr/bin/open -g -n "$APP_BUNDLE"
    /usr/bin/log stream --info --style compact --predicate 'process == "OpenLocalPhraserV2"'
    ;;
  telemetry|--telemetry)
    /usr/bin/open -g -n "$APP_BUNDLE"
    /usr/bin/log stream --info --style compact --predicate 'process == "OpenLocalPhraserV2"'
    ;;
  debug|--debug)
    lldb -- "$APP_BINARY"
    ;;
  *)
    echo "usage: $0 [run|headless|headless-connected|headless-custom|headless-missing-model|verify|agent-style-backend|logs|telemetry|debug]" >&2
    exit 2
    ;;
esac
