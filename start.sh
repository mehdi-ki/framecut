#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_VERSION="${FRAMECUT_VERSION:-3.25.0}"
if [[ -z "${FRAMECUT_VERSION:-}" && -f "$SCRIPT_DIR/VERSION" ]]; then
  APP_VERSION="$(<"$SCRIPT_DIR/VERSION")"
fi
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo 'Bitte zuerst installieren: sudo apt install python3-venv ffmpeg'
  exit 1
fi
if [[ -n "${FRAMECUT_VENV:-}" ]]; then
  VENV_DIR="$FRAMECUT_VENV"
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" && -z "${FRAMECUT_USE_USER_VENV:-}" ]]; then
  VENV_DIR="$SCRIPT_DIR/.venv"
else
  VENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/framecut/${APP_VERSION}/.venv"
fi
if [ ! -x "$VENV_DIR/bin/python" ]; then
  mkdir -p -- "$(dirname -- "$VENV_DIR")"
  python3 -m venv "$VENV_DIR" || { echo 'Bitte installieren: sudo apt install python3-venv'; exit 1; }
fi
if ! "$VENV_DIR/bin/python" -c 'import PySide6, faster_whisper, cv2, rembg' 2>/dev/null; then
  "$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"
fi
exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/app.py" "$@"
