#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$HOME/drop-broker-api/drop-api/"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

mkdir -p "$APP_DIR/logs"
cd "$APP_DIR"
exec uv run main.py run