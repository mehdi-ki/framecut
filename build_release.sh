#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_VERSION="${FRAMECUT_VERSION:-$(<"$SCRIPT_DIR/VERSION")}" 
OUTPUT_DIR="${1:-${FRAMECUT_RELEASE_DIR:-$SCRIPT_DIR/../../..}}"
OUTPUT_DIR="$(mkdir -p -- "$OUTPUT_DIR" && cd -- "$OUTPUT_DIR" && pwd)"
STAGE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/framecut-release.XXXXXX")"
trap 'rm -rf -- "$STAGE_ROOT"' EXIT

SOURCE_STAGE="$STAGE_ROOT/Framecut-${APP_VERSION}"
mkdir -p -- "$SOURCE_STAGE"
while IFS= read -r -d '' item; do
    name="${item##*/}"
    [[ "$name" == '.git' || "$name" == '.venv' || "$name" == '__pycache__' || "$name" == *.pyc ]] && continue
    cp -a -- "$item" "$SOURCE_STAGE/"
done < <(find "$SCRIPT_DIR" -mindepth 1 -maxdepth 1 -print0 | sort -z)

ZIP_OUTPUT="$OUTPUT_DIR/Framecut-${APP_VERSION}-Linux.zip"
rm -f -- "$ZIP_OUTPUT"
(cd "$STAGE_ROOT" && zip -qr "$ZIP_OUTPUT" "Framecut-${APP_VERSION}")
printf 'Quellpaket erstellt: %s\n' "$ZIP_OUTPUT"

bash "$SCRIPT_DIR/build_deb.sh" "$OUTPUT_DIR"

APPIMAGE_OUTPUT="$OUTPUT_DIR/Framecut-${APP_VERSION}-x86_64.AppImage"
if bash "$SCRIPT_DIR/build_appimage.sh" "$OUTPUT_DIR"; then
    :
else
    appimage_status=$?
    if [[ "$appimage_status" -ne 2 ]]; then
        exit "$appimage_status"
    fi
    printf '%s\n' \
        'Noch kein AppImage erzeugt: appimagetool ist in dieser Umgebung nicht installiert.' \
        'Das AppImage-Build-Skript und die vorbereitete AppDir-Struktur sind enthalten.' \
        'Installiere appimagetool und führe build_appimage.sh erneut aus.' \
        > "$OUTPUT_DIR/Framecut-${APP_VERSION}-AppImage-BUILD-REQUIRED.txt"
fi

if [[ -n "${FRAMECUT_RELEASE_BASE_URL:-}" ]]; then
    deb_name="framecut_${APP_VERSION}_$(dpkg --print-architecture 2>/dev/null || printf 'amd64').deb"
    deb_file="$OUTPUT_DIR/$deb_name"
    appimage_file="$APPIMAGE_OUTPUT"
    {
        printf '{\n  "product": "Framecut",\n  "version": "%s",\n' "$APP_VERSION"
        printf '  "release_notes": ["Framecut 3.9: repariertes Timeline-Kontextmenü und kompakte Symbolleiste für die Timeline."],\n'
        printf '  "artifacts": {\n'
        if [[ -f "$appimage_file" ]]; then
            printf '    "appimage": {"filename": "%s", "url": "%s/%s", "sha256": "%s"},\n' \
                "$(basename "$appimage_file")" "${FRAMECUT_RELEASE_BASE_URL%/}" "$(basename "$appimage_file")" "$(sha256sum "$appimage_file" | awk '{print $1}')"
        fi
        printf '    "deb": {"filename": "%s", "url": "%s/%s", "sha256": "%s"}\n' \
            "$deb_name" "${FRAMECUT_RELEASE_BASE_URL%/}" "$deb_name" "$(sha256sum "$deb_file" | awk '{print $1}')"
        printf '  }\n}\n'
    } > "$OUTPUT_DIR/updates.json"
    printf 'Update-Manifest erstellt: %s\n' "$OUTPUT_DIR/updates.json"
fi

sha256sum "$ZIP_OUTPUT" "$OUTPUT_DIR/framecut_${APP_VERSION}_$(dpkg --print-architecture 2>/dev/null || printf 'amd64').deb" > "$OUTPUT_DIR/SHA256SUMS"
printf 'Prüfsummen erstellt: %s\n' "$OUTPUT_DIR/SHA256SUMS"
