#!/usr/bin/env bash
set -euo pipefail

PLATFORM="${1:-$(uname | tr '[:upper:]' '[:lower:]')}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$DESKTOP_DIR/.." && pwd)"
BACKEND_REQUIREMENTS="$PROJECT_ROOT/backend/requirements.txt"

case "$PLATFORM" in
  darwin|mac|macos)
    TARGET_DIR="$DESKTOP_DIR/runtime/python/macos"
    ;;
  linux)
    TARGET_DIR="$DESKTOP_DIR/runtime/python/linux"
    ;;
  *)
    echo "Unsupported platform: $PLATFORM"
    exit 1
    ;;
esac

mkdir -p "$TARGET_DIR"
python3 -m venv "$TARGET_DIR"
"$TARGET_DIR/bin/python" -m pip install --upgrade pip
"$TARGET_DIR/bin/python" -m pip install -r "$BACKEND_REQUIREMENTS"

echo "Portable runtime prepared in $TARGET_DIR"
