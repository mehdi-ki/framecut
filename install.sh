#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_VERSION="${FRAMECUT_VERSION:-3.10}"
if [[ -z "${FRAMECUT_VERSION:-}" && -f "$SCRIPT_DIR/VERSION" ]]; then
    APP_VERSION="$(<"$SCRIPT_DIR/VERSION")"
fi
DEFAULT_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/framecut/${APP_VERSION}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf 'Framecut %s installieren\n\nAufruf: bash install.sh [INSTALLATIONSORDNER]\n' "$APP_VERSION"
    printf 'Standard: %s\n' "$DEFAULT_ROOT"
    exit 0
fi

INSTALL_ROOT="${1:-$DEFAULT_ROOT}"
INSTALL_ROOT="$(mkdir -p -- "$INSTALL_ROOT" && cd -- "$INSTALL_ROOT" && pwd)"
if [[ "$INSTALL_ROOT" != "$SCRIPT_DIR" && "$INSTALL_ROOT/" == "$SCRIPT_DIR/"* ]]; then
    echo "Der Installationsordner darf nicht innerhalb des Quellordners liegen." >&2
    exit 1
fi

if [[ "$INSTALL_ROOT" != "$SCRIPT_DIR" ]]; then
    shopt -s dotglob nullglob
    for item in "$SCRIPT_DIR"/*; do
        name="${item##*/}"
        [[ "$name" == ".venv" || "$name" == "__pycache__" ]] && continue
        cp -a -- "$item" "$INSTALL_ROOT/"
    done
    shopt -u dotglob nullglob
fi

mkdir -p -- "$HOME/.local/bin" "$HOME/.local/share/applications" \
    "$HOME/.local/share/icons/hicolor/scalable/apps" \
    "$HOME/.local/share/mime/packages"
cat > "$HOME/.local/bin/framecut" <<EOF
#!/usr/bin/env bash
exec "$INSTALL_ROOT/start.sh" "\$@"
EOF
chmod +x "$HOME/.local/bin/framecut"

cat > "$HOME/.local/share/applications/framecut.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Framecut ${APP_VERSION}
Comment=Lokaler Linux-Videoschnitt
Exec=$HOME/.local/bin/framecut %F
Icon=framecut
Terminal=false
Categories=AudioVideo;Video;AudioVideoEditing;
MimeType=application/x-framecut;
StartupWMClass=Framecut
EOF

if [[ -f "$INSTALL_ROOT/framecut.svg" ]]; then
    cp -f -- "$INSTALL_ROOT/framecut.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/framecut.svg"
fi
if [[ -f "$INSTALL_ROOT/application-x-framecut.xml" ]]; then
    cp -f -- "$INSTALL_ROOT/application-x-framecut.xml" "$HOME/.local/share/mime/packages/application-x-framecut.xml"
fi
if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database "$HOME/.local/share/mime" >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

cat > "$HOME/.local/bin/framecut-update" <<EOF
#!/usr/bin/env bash
exec python3 "$INSTALL_ROOT/update.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/framecut-update"

echo "Framecut ${APP_VERSION} installiert: $INSTALL_ROOT"
echo "Start: $HOME/.local/bin/framecut"
echo "Update-CLI: $HOME/.local/bin/framecut-update"
