#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME="framecut"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_VERSION="${FRAMECUT_VERSION:-$(<"$SCRIPT_DIR/VERSION")}" 
OUTPUT_DIR="${1:-${FRAMECUT_RELEASE_DIR:-$SCRIPT_DIR/../../..}}"
DEB_ARCH="${FRAMECUT_DEB_ARCH:-$(dpkg --print-architecture 2>/dev/null || printf 'amd64')}"
OUTPUT_DIR="$(mkdir -p -- "$OUTPUT_DIR" && cd -- "$OUTPUT_DIR" && pwd)"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/framecut-deb.XXXXXX")"
trap 'rm -rf -- "$BUILD_ROOT"' EXIT

DEB_ROOT="$BUILD_ROOT/root"
APP_ROOT="$DEB_ROOT/usr/lib/framecut/$APP_VERSION"
mkdir -p -- "$DEB_ROOT/DEBIAN" "$APP_ROOT" \
    "$DEB_ROOT/usr/bin" "$DEB_ROOT/usr/share/applications" \
    "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps" \
    "$DEB_ROOT/usr/share/mime/packages"

printf '%s\n' \
    'Package: framecut' \
    "Version: ${APP_VERSION}-1" \
    "Architecture: ${DEB_ARCH}" \
    'Section: video' \
    'Priority: optional' \
    'Depends: python3 (>= 3.10), python3-venv, ffmpeg, libxcb-cursor0' \
    'Maintainer: Framecut Project' \
    'Description: Framecut local Linux video editor' \
    ' Native multitrack video editing with FFmpeg and PySide6.' \
    > "$DEB_ROOT/DEBIAN/control"

for file in app.py ai_tools.py core.py preview.py style.py timeline.py transcription.py requirements.txt start.sh update.py update_system.py VERSION LICENSE README.md START_HIER.txt; do
    cp -a -- "$SCRIPT_DIR/$file" "$APP_ROOT/$file"
done
cp -a -- "$SCRIPT_DIR/framecut.svg" "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps/framecut.svg"
cp -a -- "$SCRIPT_DIR/application-x-framecut.xml" "$DEB_ROOT/usr/share/mime/packages/application-x-framecut.xml"
sed "s/^X-AppImage-Version=.*/X-AppImage-Version=$APP_VERSION/" "$SCRIPT_DIR/framecut.desktop" > "$DEB_ROOT/usr/share/applications/framecut.desktop"

cat > "$DEB_ROOT/usr/bin/framecut" <<EOF
#!/usr/bin/env bash
exec /usr/lib/framecut/${APP_VERSION}/start.sh "\$@"
EOF
cat > "$DEB_ROOT/usr/bin/framecut-update" <<EOF
#!/usr/bin/env bash
exec python3 /usr/lib/framecut/${APP_VERSION}/update.py "\$@"
EOF
chmod 0755 "$DEB_ROOT/usr/bin/framecut" "$DEB_ROOT/usr/bin/framecut-update" "$APP_ROOT/start.sh" "$APP_ROOT/update.py"

cat > "$DEB_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-mime-database >/dev/null 2>&1; then
    update-mime-database /usr/share/mime >/dev/null 2>&1 || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "$DEB_ROOT/DEBIAN/postinst"

OUTPUT="$OUTPUT_DIR/${PACKAGE_NAME}_${APP_VERSION}_${DEB_ARCH}.deb"
rm -f -- "$OUTPUT"
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$OUTPUT" >/dev/null
printf 'Debian-Paket erstellt: %s\n' "$OUTPUT"
