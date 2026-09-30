#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_VERSION="${FRAMECUT_VERSION:-$(<"$SCRIPT_DIR/VERSION")}" 
OUTPUT_DIR="${1:-${FRAMECUT_RELEASE_DIR:-$SCRIPT_DIR/../../..}}"
OUTPUT_DIR="$(mkdir -p -- "$OUTPUT_DIR" && cd -- "$OUTPUT_DIR" && pwd)"
APPDIR="$OUTPUT_DIR/.framecut-appimage-build/Framecut.AppDir"
APPIMAGE_ARCH="${FRAMECUT_APPIMAGE_ARCH:-x86_64}"

rm -rf -- "$OUTPUT_DIR/.framecut-appimage-build"
mkdir -p -- "$APPDIR/usr/bin" "$APPDIR/usr/lib/framecut/$APP_VERSION" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
    "$APPDIR/usr/share/mime/packages"

for file in app.py ai_tools.py core.py preview.py style.py timeline.py transcription.py requirements.txt start.sh update.py update_system.py VERSION LICENSE README.md START_HIER.txt; do
    cp -a -- "$SCRIPT_DIR/$file" "$APPDIR/usr/lib/framecut/$APP_VERSION/$file"
done
sed "s/^X-AppImage-Version=.*/X-AppImage-Version=$APP_VERSION/" "$SCRIPT_DIR/framecut.desktop" > "$APPDIR/framecut.desktop"
cp -a -- "$SCRIPT_DIR/framecut.svg" "$APPDIR/framecut.svg"
cp -a -- "$SCRIPT_DIR/framecut.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/framecut.svg"
cp -a -- "$SCRIPT_DIR/application-x-framecut.xml" "$APPDIR/usr/share/mime/packages/application-x-framecut.xml"

cat > "$APPDIR/usr/bin/framecut" <<EOF
#!/usr/bin/env bash
set -euo pipefail
HERE="\$(cd -- "\$(dirname -- "\${BASH_SOURCE[0]}")" && pwd)"
exec "\$HERE/../lib/framecut/${APP_VERSION}/start.sh" "\$@"
EOF
cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
APPDIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$APPDIR/usr/bin/framecut" "$@"
EOF
chmod 0755 "$APPDIR/usr/bin/framecut" "$APPDIR/AppRun" "$APPDIR/usr/lib/framecut/$APP_VERSION/start.sh" "$APPDIR/usr/lib/framecut/$APP_VERSION/update.py"

APPIMAGETOOL="${APPIMAGETOOL:-}"
if [[ -z "$APPIMAGETOOL" ]]; then
    APPIMAGETOOL="$(command -v appimagetool 2>/dev/null || true)"
fi
if [[ -z "$APPIMAGETOOL" || ! -x "$APPIMAGETOOL" ]]; then
    printf '%s\n' \
        'AppDir vorbereitet, aber kein appimagetool gefunden.' \
        'Für ein echtes Type-2-AppImage: offizielles appimagetool installieren' \
        'und dieses Skript erneut ausführen (oder APPIMAGETOOL=/pfad/appimagetool setzen).' >&2
    printf 'AppDir: %s\n' "$APPDIR" >&2
    exit 2
fi

OUTPUT="$OUTPUT_DIR/Framecut-${APP_VERSION}-${APPIMAGE_ARCH}.AppImage"
rm -f -- "$OUTPUT"
"$APPIMAGETOOL" "$APPDIR" "$OUTPUT"
chmod 0755 "$OUTPUT"
printf 'AppImage erstellt: %s\n' "$OUTPUT"
