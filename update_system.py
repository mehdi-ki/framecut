"""Small, dependency-free update client used by Framecut and its CLI.

Framecut checks the stable GitHub release manifest by default. Users can
override that endpoint with ``FRAMECUT_UPDATE_MANIFEST_URL`` or a config file,
or disable checks with ``FRAMECUT_DISABLE_UPDATE_CHECK``. A manifest names the
release artifacts and their SHA-256 checksums; every download is written
atomically only after the checksum matches.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


UPDATE_MANIFEST_ENV = "FRAMECUT_UPDATE_MANIFEST_URL"
UPDATE_DISABLE_ENV = "FRAMECUT_DISABLE_UPDATE_CHECK"
DEFAULT_UPDATE_MANIFEST_URL = "https://github.com/mehdi-ki/framecut/releases/latest/download/updates.json"
USER_AGENT = "Framecut-update/3.27.0"
_VERSION_PARTS = re.compile(r"\d+")


def version_key(value: str) -> tuple[int, ...]:
    """Return a comparison-friendly numeric version tuple."""
    parts = tuple(int(part) for part in _VERSION_PARTS.findall(str(value)))
    return parts or (0,)


def is_newer(candidate: str, current: str) -> bool:
    """Whether *candidate* is a newer release than *current*."""
    left, right = version_key(candidate), version_key(current)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def update_checks_disabled() -> bool:
    """Whether the user explicitly disabled background update checks."""
    return os.environ.get(UPDATE_DISABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def configured_manifest_url() -> str:
    """Read the update endpoint from env, config, or the stable default."""
    if update_checks_disabled():
        return ""
    value = os.environ.get(UPDATE_MANIFEST_ENV, "").strip()
    if value:
        return value
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "framecut" / "update-manifest.url"
    try:
        if config.is_file():
            configured = config.read_text(encoding="utf-8").strip()
            if configured:
                return configured
    except OSError:
        pass
    return DEFAULT_UPDATE_MANIFEST_URL


def _read_manifest_source(source: str, timeout: float) -> dict:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("", "file"):
        path = Path(urllib.request.url2pathname(parsed.path if parsed.scheme == "file" else source))
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Update-Manifest muss ein JSON-Objekt sein.")
    return payload


def fetch_manifest(source: str, timeout: float = 5.0) -> dict:
    """Load and minimally validate a local or HTTPS/HTTP manifest."""
    source = str(source or "").strip()
    if not source:
        raise ValueError("Keine Update-Manifest-URL konfiguriert.")
    manifest = _read_manifest_source(source, timeout)
    version = str(manifest.get("version", "")).strip()
    if not version:
        raise ValueError("Update-Manifest enthält keine Version.")
    if manifest.get("product", "Framecut") != "Framecut":
        raise ValueError("Update-Manifest gehört nicht zu Framecut.")
    return manifest


def _normalise_artifact(kind: str, artifact: object, manifest: dict) -> dict | None:
    if not isinstance(artifact, dict):
        return None
    url = str(artifact.get("url", "")).strip()
    checksum = str(artifact.get("sha256", "")).strip().lower()
    if not url or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        return None
    filename = str(artifact.get("filename", "")).strip()
    if not filename:
        filename = Path(urllib.parse.urlparse(url).path).name or f"Framecut-{manifest['version']}.{kind}"
    notes = manifest.get("release_notes", [])
    if isinstance(notes, str):
        notes = [notes]
    if not isinstance(notes, list):
        notes = []
    return {
        "kind": kind,
        "version": str(manifest["version"]),
        "url": url,
        "sha256": checksum,
        "filename": filename,
        "release_notes": [str(note) for note in notes],
    }


def select_artifact(manifest: dict, current_version: str, preferred: tuple[str, ...] = ("appimage", "deb")) -> dict | None:
    """Select a newer, checksum-pinned artifact from a release manifest."""
    version = str(manifest.get("version", "")).strip()
    if not version or not is_newer(version, current_version):
        return None
    artifacts = manifest.get("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
    for kind in preferred:
        candidate = _normalise_artifact(kind, artifacts.get(kind), manifest)
        if candidate:
            return candidate
        candidate = _normalise_artifact(kind, manifest.get(kind), manifest)
        if candidate:
            return candidate
    return None


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url: str, expected_sha256: str, target: str | Path, progress=None, timeout: float = 60.0) -> Path:
    """Download *url* to *target* and atomically publish it after verification."""
    expected = str(expected_sha256).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Ungültige SHA-256-Prüfsumme im Update-Manifest.")
    destination = Path(target).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.download-{os.getpid()}-{next(tempfile._get_candidate_names())}")
    try:
        request = urllib.request.Request(str(url), headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response, temporary.open("wb") as output:
            total = int(response.headers.get("Content-Length", "0") or 0)
            copied = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                copied += len(chunk)
                if progress:
                    progress(copied, total)
        actual = sha256_file(temporary)
        if actual != expected:
            raise ValueError(f"Prüfsumme stimmt nicht: erwartet {expected}, erhalten {actual}.")
        os.replace(temporary, destination)
        return destination
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def update_cache_directory() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    target = root / "framecut" / "updates"
    target.mkdir(parents=True, exist_ok=True)
    return target


def install_downloaded(path: str | Path, kind: str, current_path: str | Path | None = None) -> str:
    """Install an already verified artifact when the platform permits it."""
    artifact = Path(path).expanduser().resolve()
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    if kind == "appimage":
        target_value = current_path or os.environ.get("APPIMAGE", "")
        if not target_value:
            raise ValueError("Der aktuelle AppImage-Pfad ist nicht bekannt.")
        target = Path(target_value).expanduser().resolve()
        if target == artifact:
            return str(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = artifact.stat().st_mode | 0o111
        os.chmod(artifact, mode)
        os.replace(artifact, target)
        return f"AppImage ersetzt: {target}"
    if kind == "deb":
        command = ["pkexec", "dpkg", "-i", str(artifact)] if shutil.which("pkexec") else ["sudo", "dpkg", "-i", str(artifact)]
        completed = subprocess.run(command, check=False)
        if completed.returncode:
            raise RuntimeError(f"Debian-Installation fehlgeschlagen (Exit {completed.returncode}).")
        return f"Debian-Paket installiert: {artifact}"
    raise ValueError(f"Unbekannter Update-Typ: {kind}")


def preferred_kinds() -> tuple[str, ...]:
    """Prefer AppImage for an AppImage process, otherwise the .deb artifact."""
    return ("appimage", "deb") if os.environ.get("APPIMAGE") else ("deb", "appimage")


if __name__ == "__main__":
    # Keep accidental direct execution helpful without making the module a second CLI.
    print("Nutze update.py oder framecut-update für Framecut-Updates.")
