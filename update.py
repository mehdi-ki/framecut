#!/usr/bin/env python3
"""Command-line updater for Framecut Linux installations."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from update_system import (
    configured_manifest_url,
    download_verified,
    fetch_manifest,
    install_downloaded,
    preferred_kinds,
    select_artifact,
    update_cache_directory,
)

try:
    DEFAULT_VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip() or "3.26.0"
except OSError:
    DEFAULT_VERSION = "3.26.0"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Framecut-Updates prüfen und verifiziert herunterladen")
    parser.add_argument("--manifest", help="Manifest-URL oder lokale JSON-Datei; sonst Standard-GitHub-Manifest bzw. FRAMECUT_UPDATE_MANIFEST_URL")
    parser.add_argument("--current", default=DEFAULT_VERSION, help=f"Aktuelle Framecut-Version (Standard: {DEFAULT_VERSION})")
    parser.add_argument("--kind", choices=("appimage", "deb"), action="append", help="Bevorzugtes Paketformat; mehrfach möglich")
    parser.add_argument("--target", help="Zielpfad für den Download")
    parser.add_argument("--install", action="store_true", help="Nach dem Download installieren")
    args = parser.parse_args(argv)

    source = (args.manifest or configured_manifest_url()).strip()
    if not source:
        print("Keine Manifest-URL. Setze FRAMECUT_UPDATE_MANIFEST_URL oder nutze --manifest.", file=sys.stderr)
        return 2
    try:
        manifest = fetch_manifest(source)
        kinds = tuple(args.kind or preferred_kinds())
        artifact = select_artifact(manifest, args.current, kinds)
        if not artifact:
            print(f"Kein neuer Framecut-Stand für {args.current} gefunden.")
            return 0
        print(f"Update verfügbar: Framecut {artifact['version']} ({artifact['kind']})")
        print(" · ".join(artifact["release_notes"]) or "Keine Release-Notizen.")
        if args.target:
            target = Path(args.target).expanduser()
        else:
            target = update_cache_directory() / artifact["filename"]
        downloaded = download_verified(artifact["url"], artifact["sha256"], target)
        print(f"Verifiziert heruntergeladen: {downloaded}")
        if args.install:
            message = install_downloaded(downloaded, artifact["kind"], os.environ.get("APPIMAGE"))
            print(message)
        elif artifact["kind"] == "deb":
            print(f"Installation: sudo dpkg -i '{downloaded}'")
        return 0
    except Exception as exc:
        print(f"Update fehlgeschlagen: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
