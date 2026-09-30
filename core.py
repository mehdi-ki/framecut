"""Framecut core: timeline, media, effects and professional trim operations."""
from dataclasses import dataclass, asdict, field, replace
from pathlib import Path
import json
import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import zipfile
from functools import lru_cache

MIN_CLIP = 0.04
DEFAULT_STILL_DURATION = 5.0
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'}
SUBTITLE_EXTENSIONS = {'.srt', '.vtt'}
TEXT_ANIMATIONS = ('none', 'fade', 'slide_left', 'slide_right', 'slide_up', 'slide_down')
KEYFRAME_CURVES = ('linear', 'ease_in', 'ease_out', 'ease_in_out')
KEYFRAME_CURVE_LABELS = {
    'linear': 'Linear',
    'ease_in': 'Ease in',
    'ease_out': 'Ease out',
    'ease_in_out': 'Ease in/out',
}
EFFECT_PRESETS = {
    'clean': {
        'brightness': 0.0, 'contrast': 1.0, 'saturation': 1.0,
        'filter_preset': 'none', 'opacity': 1.0, 'blur': 0.0,
        'sharpen': 0.0, 'stabilization': 0.0,
    },
    'cinematic': {
        'brightness': -0.02, 'contrast': 1.18, 'saturation': 0.86,
        'filter_preset': 'cinematic', 'opacity': 1.0, 'blur': 0.0,
        'sharpen': 0.15, 'stabilization': 0.0,
    },
    'dream': {
        'brightness': 0.05, 'contrast': 1.02, 'saturation': 1.08,
        'filter_preset': 'warm', 'opacity': 1.0, 'blur': 0.65,
        'sharpen': 0.0, 'stabilization': 0.0,
    },
    'noir': {
        'brightness': -0.02, 'contrast': 1.25, 'saturation': 0.0,
        'filter_preset': 'noir', 'opacity': 1.0, 'blur': 0.0,
        'sharpen': 0.25, 'stabilization': 0.0,
    },
    'vivid': {
        'brightness': 0.01, 'contrast': 1.10, 'saturation': 1.30,
        'filter_preset': 'vivid', 'opacity': 1.0, 'blur': 0.0,
        'sharpen': 0.35, 'stabilization': 0.0,
    },
    'soft_focus': {
        'brightness': 0.03, 'contrast': 0.98, 'saturation': 1.04,
        'filter_preset': 'none', 'opacity': 1.0, 'blur': 1.2,
        'sharpen': 0.0, 'stabilization': 0.0,
    },
}
TEXT_STYLE_PRESETS = {
    'title': {
        'font_size': 72, 'color': '#ffffff', 'font_family': 'DejaVu Sans',
        'font_bold': True, 'font_italic': False, 'outline_width': 3.0,
        'outline_color': '#000000', 'shadow_size': 4.0, 'shadow_color': '#000000',
        'background_enabled': False, 'background_color': '#000000',
        'background_opacity': 0.0, 'background_padding': 16,
        'text_animation': 'fade', 'text_animation_duration': 0.35, 'x': 0.5, 'y': 0.22,
    },
    'subtitle': {
        'font_size': 42, 'color': '#ffffff', 'font_family': 'DejaVu Sans',
        'font_bold': False, 'font_italic': False, 'outline_width': 2.0,
        'outline_color': '#000000', 'shadow_size': 2.0, 'shadow_color': '#000000',
        'background_enabled': True, 'background_color': '#000000',
        'background_opacity': 0.65, 'background_padding': 12,
        'text_animation': 'none', 'text_animation_duration': 0.35, 'x': 0.5, 'y': 0.86,
    },
    'lower_third': {
        'font_size': 44, 'color': '#ffffff', 'font_family': 'DejaVu Sans',
        'font_bold': True, 'font_italic': False, 'outline_width': 1.0,
        'outline_color': '#101820', 'shadow_size': 2.0, 'shadow_color': '#000000',
        'background_enabled': True, 'background_color': '#0b1220',
        'background_opacity': 0.82, 'background_padding': 18,
        'text_animation': 'slide_left', 'text_animation_duration': 0.35, 'x': 0.08, 'y': 0.78,
    },
}
TRANSITION_TYPES = ('none', 'dissolve', 'slide_left', 'slide_right', 'slide_up', 'slide_down',
                    'wipe_left', 'wipe_right', 'wipe_up', 'wipe_down', 'zoom', 'dip_to_black',
                    'fade_white', 'blur_in', 'circle_open', 'circle_close', 'radial',
                    'pixelize', 'smooth_left', 'smooth_right', 'smooth_up', 'smooth_down',
                    'cover_left', 'cover_right', 'cover_up', 'cover_down')
FILTER_PRESETS = ('none', 'vivid', 'warm', 'cool', 'cinematic', 'vintage', 'noir')
MASK_TYPES = ('none', 'rectangle', 'ellipse')
AUDIO_CHANNEL_MODES = ('stereo', 'mono', 'left', 'right')
EXPORT_FORMATS = {
    'mp4': {'label': 'MP4 · kompatibel', 'extension': '.mp4', 'muxer': 'mp4', 'codecs': ('h264', 'hevc')},
    'mkv': {'label': 'Matroska MKV', 'extension': '.mkv', 'muxer': 'matroska', 'codecs': ('h264', 'hevc', 'vp9', 'av1')},
    'webm': {'label': 'WebM', 'extension': '.webm', 'muxer': 'webm', 'codecs': ('vp9', 'av1')},
    'mov': {'label': 'QuickTime MOV', 'extension': '.mov', 'muxer': 'mov', 'codecs': ('h264', 'hevc')},
}
EXPORT_CODEC_LABELS = {
    'h264': 'H.264 / AVC',
    'hevc': 'H.265 / HEVC',
    'vp9': 'VP9',
    'av1': 'AV1',
}
EXPORT_ENCODER_LABELS = {
    'software': 'Software / CPU',
    'auto': 'Auto · Hardware wenn verfügbar',
    'nvenc': 'NVIDIA NVENC',
    'vaapi': 'VAAPI · Intel/AMD',
}
EXPORT_VIDEO_ENCODERS = {
    'h264': 'libx264',
    'hevc': 'libx265',
    'vp9': 'libvpx-vp9',
    'av1': 'libaom-av1',
}
PROXY_PROFILES = {
    '360p': {'label': '360p · schnell', 'width': 640, 'height': 360, 'crf': 31, 'preset': 'ultrafast'},
    '720p': {'label': '720p · sauber', 'width': 1280, 'height': 720, 'crf': 28, 'preset': 'veryfast'},
}
MARKER_KINDS = ('marker', 'chapter')
MARKER_COLORS = {'marker': '#63ead4', 'chapter': '#f8c86f'}
DEFAULT_EXPORT_SETTINGS = {
    'format': 'mp4',
    'video_codec': 'h264',
    'fps': 30.0,
    'bitrate_kbps': 12000,
    'encoder': 'software',
    'hdr': False,
}
DEFAULT_MASTER_MIXER = {
    'volume': 1.0,
    'pan': 0.0,
    'loudness_normalization': False,
    'loudness_target': -16.0,
}
PRESETS = {"1080p · 16:9": (1920, 1080), "720p · 16:9": (1280, 720),
           "1080p · 9:16": (1080, 1920), "Quadratisch": (1080, 1080)}
_PROBE_CACHE = {}


@lru_cache(maxsize=1)
def preview_acceleration_info():
    """Detect a usable Linux hardware decoder without making it mandatory."""
    try:
        result = subprocess.run(['ffmpeg', '-hide_banner', '-hwaccels'],
                                capture_output=True, text=True, timeout=10)
        hwaccels = {line.strip().lower() for line in result.stdout.splitlines()
                    if line.strip() and not line.lower().startswith('hardware acceleration methods')}
    except (OSError, subprocess.SubprocessError):
        hwaccels = set()
    dri = any(path.is_char_device() for path in Path('/dev/dri').glob('renderD*')) if Path('/dev/dri').is_dir() else False
    nvidia = Path('/dev/nvidia0').exists()
    if dri and 'vaapi' in hwaccels:
        return {'available': True, 'backend': 'VAAPI', 'label': 'GPU-Decoding · VAAPI'}
    if nvidia and ('cuda' in hwaccels or 'cuvid' in hwaccels):
        return {'available': True, 'backend': 'CUDA', 'label': 'GPU-Decoding · CUDA'}
    return {'available': False, 'backend': 'software', 'label': 'GPU-Decoding nicht verfügbar'}


def cache_size(path):
    """Return the size of generated cache files below a directory."""
    root = Path(path)
    total = 0
    if not root.exists():
        return 0
    for item in root.rglob('*'):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def prune_cache(path, max_bytes, keep=()):
    """Remove least-recently-used generated files until a cache budget fits."""
    if not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError('Das Cache-Limit muss eine nichtnegative Ganzzahl sein.')
    root = Path(path)
    if not root.exists():
        return {'before': 0, 'after': 0, 'removed': 0}
    keep = {str(Path(item).resolve()) for item in keep}
    files = []
    total = 0
    for item in root.rglob('*'):
        try:
            if item.is_file() and not item.is_symlink():
                stat = item.stat()
                files.append((stat.st_atime_ns, stat.st_mtime_ns, item, stat.st_size))
                total += stat.st_size
        except OSError:
            continue
    before = total
    removed = 0
    for _, _, item, size in sorted(files, key=lambda value: (value[0], value[1])):
        if total <= max_bytes:
            break
        try:
            if str(item.resolve()) in keep:
                continue
            item.unlink()
            total -= size
            removed += size
        except OSError:
            continue
    return {'before': before, 'after': total, 'removed': removed}


def speed_at_keyframes(frames, time, default):
    """Interpolate a speed-ramp value in source-local seconds."""
    if not frames:
        return float(default)
    time = max(0.0, float(time))
    first = frames[0]
    if time <= float(first['time']):
        return float(default if time < float(first['time']) else first['speed'])
    for left, right in zip(frames, frames[1:]):
        left_time, right_time = float(left['time']), float(right['time'])
        if time <= right_time:
            ratio = (time-left_time) / max(1e-9, right_time-left_time)
            return float(left['speed']) + (float(right['speed'])-float(left['speed'])) * ratio
    return float(frames[-1]['speed'])


def speed_ramp_duration(source_span, default, frames):
    """Integrate 1/speed for a piecewise-linear speed ramp."""
    source_span = max(0.0, float(source_span))
    if source_span <= 0:
        return 0.0
    points = [0.0] + [float(frame['time']) for frame in frames if 0 < float(frame['time']) < source_span] + [source_span]
    points = sorted(set(round(point, 7) for point in points))
    total = 0.0
    for left, right in zip(points, points[1:]):
        span = right-left
        if frames and left < float(frames[0]['time'])-1e-9:
            left_speed = right_speed = float(default)
        else:
            left_speed = speed_at_keyframes(frames, left, default)
            right_speed = speed_at_keyframes(frames, right, default)
        left_speed = max(.25, min(4.0, left_speed)); right_speed = max(.25, min(4.0, right_speed))
        if abs(right_speed-left_speed) <= 1e-9:
            total += span/left_speed
        else:
            slope = (right_speed-left_speed)/span
            total += math.log(right_speed/left_speed)/slope
    return total


def speed_ramp_source_offset(source_span, default, frames, timeline_time):
    """Invert the speed-ramp integral for a timeline-local split/trim time."""
    source_span = max(0.0, float(source_span))
    target = max(0.0, min(speed_ramp_duration(source_span, default, frames), float(timeline_time)))
    if not frames:
        return max(0.0, min(source_span, target*float(default)))
    low, high = 0.0, source_span
    for _ in range(42):
        middle = (low+high)/2
        if speed_ramp_duration(middle, default, frames) < target:
            low = middle
        else:
            high = middle
    return (low+high)/2


@dataclass
class Clip:
    path: str
    duration: float
    start: float = 0.0
    end: float = 0.0
    volume: float = 1.0
    position: float = 0.0
    track: int = 1
    kind: str = "video"
    has_audio: bool = True
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)
    text: str = ""
    font_size: int = 56
    color: str = "#ffffff"
    font_family: str = "DejaVu Sans"
    font_bold: bool = False
    font_italic: bool = False
    outline_width: float = 0.0
    outline_color: str = "#000000"
    shadow_size: float = 0.0
    shadow_color: str = "#000000"
    background_enabled: bool = True
    background_color: str = "#000000"
    background_opacity: float = 0.35
    background_padding: int = 16
    text_animation: str = "none"
    text_animation_duration: float = 0.35
    x: float = 0.5
    y: float = 0.5
    speed: float = 1.0
    speed_keyframes: list = field(default_factory=list)
    fade_in: float = 0.0
    fade_out: float = 0.0
    freeze_frame: bool = False
    freeze_duration: float = 0.0
    reverse: bool = False
    # Resolution-independent video transform controls.
    video_scale: float = 1.0
    video_x: float = 0.5
    video_y: float = 0.5
    crop_left: float = 0.0
    crop_top: float = 0.0
    crop_right: float = 0.0
    crop_bottom: float = 0.0
    rotation: float = 0.0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    transition_type: str = "none"
    transition_duration: float = 0.0
    # Local clip-time transform keyframes.  Each entry stores time, zoom,
    # normalized position and rotation so projects remain resolution-independent.
    keyframes: list = field(default_factory=list)
    # Simple, deterministic per-clip color correction.
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    filter_preset: str = "none"
    lut_path: str = ""
    # Deterministic per-clip compositing/effect controls.
    opacity: float = 1.0
    blur: float = 0.0
    sharpen: float = 0.0
    stabilization: float = 0.0
    # Optional local AI/video-analysis derivatives.  The original media path
    # remains authoritative; these fields only describe generated helpers.
    background_removal_enabled: bool = False
    background_removed_path: str = ""
    tracking_keyframes: list = field(default_factory=list)
    object_removal_enabled: bool = False
    effect_preset: str = "clean"
    chroma_key_enabled: bool = False
    chroma_key_color: str = "#00ff00"
    chroma_key_similarity: float = 0.1
    chroma_key_blend: float = 0.1
    mask_type: str = "none"
    mask_x: float = 0.0
    mask_y: float = 0.0
    mask_width: float = 1.0
    mask_height: float = 1.0
    mask_feather: float = 0.0
    # Local clip-time volume automation for audio and video source audio.
    volume_keyframes: list = field(default_factory=list)
    # Native FFmpeg audio processing controls. These defaults keep older
    # Framecut project files fully compatible.
    audio_noise_reduction: float = 0.0
    audio_eq_low: float = 0.0
    audio_eq_mid: float = 0.0
    audio_eq_high: float = 0.0
    audio_compressor_enabled: bool = False
    audio_compressor_threshold: float = -18.0
    audio_compressor_ratio: float = 4.0
    audio_ducking: float = 0.0
    audio_voice_isolation: float = 0.0
    audio_channel_mode: str = "stereo"
    audio_pan: float = 0.0
    # Editing workflow metadata. These fields were added after the first
    # project format and deliberately keep defaults for older .framecut files.
    group_id: str = ""
    source_type: str = "video"  # video, audio, image, image_sequence, text, adjustment
    source_paths: list = field(default_factory=list)
    source_fps: float = 24.0

    @property
    def length(self):
        base = speed_ramp_duration(self.end-self.start, self.speed, self.speed_keyframes)
        return base + (self.freeze_duration if self.freeze_frame else 0.0)

    @property
    def finish(self):
        return self.position + self.length

    def validate(self, files=True):
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in
                   (self.duration, self.start, self.end, self.volume, self.position, self.speed,
                    self.video_scale, self.video_x, self.video_y, self.crop_left, self.crop_top,
                    self.crop_right, self.crop_bottom, self.rotation, self.transition_duration,
                    self.brightness, self.contrast, self.saturation, self.opacity, self.blur,
                    self.stabilization,
                    self.sharpen, self.freeze_duration, self.chroma_key_similarity,
                    self.chroma_key_blend, self.mask_x, self.mask_y, self.mask_width,
                    self.mask_height, self.mask_feather, self.audio_noise_reduction,
                    self.audio_eq_low, self.audio_eq_mid, self.audio_eq_high,
                    self.audio_compressor_threshold, self.audio_compressor_ratio,
                    self.audio_ducking, self.audio_voice_isolation, self.audio_pan)):
            raise ValueError("Ungültige Zahl im Projekt.")
        if not (0 <= self.start < self.end <= self.duration + 0.02):
            raise ValueError("Start und Ende müssen innerhalb der Quelldatei liegen.")
        if (self.length < MIN_CLIP - 1e-7 or self.position < 0 or not 0 <= self.volume <= 1
                or not 0.25 <= self.speed <= 4 or self.fade_in < 0 or self.fade_out < 0
                or self.fade_in > self.length or self.fade_out > self.length
                or self.fade_in+self.fade_out > self.length+1e-7):
            raise ValueError("Clip zu kurz, negative Position oder ungültige Lautstärke.")
        if type(self.freeze_frame) is not bool or not 0 <= self.freeze_duration <= 600:
            raise ValueError("Ungültiger Freeze-Frame.")
        if type(self.reverse) is not bool:
            raise ValueError("Ungültige Rückwärtswiedergabe.")
        if not isinstance(self.speed_keyframes, list):
            raise ValueError("Ungültige Speed-Ramping-Keyframes.")
        if self.kind != "video" and self.speed_keyframes:
            raise ValueError("Speed-Ramping ist nur für Videoclips erlaubt.")
        previous_speed_time = -1.0
        source_span = self.end-self.start
        for keyframe in self.speed_keyframes:
            if not isinstance(keyframe, dict) or "time" not in keyframe or "speed" not in keyframe:
                raise ValueError("Ungültiger Speed-Ramping-Keyframe.")
            time, value = keyframe["time"], keyframe["speed"]
            if (not all(isinstance(item, (int, float)) and not isinstance(item, bool)
                        and math.isfinite(item) for item in (time, value))):
                raise ValueError("Ungültige Zahl im Speed-Ramping-Keyframe.")
            time, value = float(time), float(value)
            if time < -1e-7 or time > source_span + 1e-7 or time <= previous_speed_time + 1e-7:
                raise ValueError("Speed-Ramping-Zeit muss sortiert im Quellbereich liegen.")
            if not 0.25 <= value <= 4:
                raise ValueError("Speed-Ramping muss zwischen 0,25× und 4× liegen.")
            previous_speed_time = time
        if self.kind not in ("audio", "video", "text") or type(self.track) is not int or not self.track:
            raise ValueError("Ungültiger Spurtyp.")
        if (self.kind in ("video", "text")) != (self.track > 0):
            raise ValueError("Videos und Texte gehören auf Video-, Audiodateien auf Audiospuren.")
        if not isinstance(self.uid, str) or not self.uid:
            raise ValueError("Clip-ID fehlt.")
        if not isinstance(self.keyframes, list):
            raise ValueError("Ungültige Keyframes.")
        if self.kind != "video" and self.keyframes:
            raise ValueError("Keyframes sind nur für Videoclips erlaubt.")
        if not isinstance(self.volume_keyframes, list):
            raise ValueError("Ungültige Lautstärke-Keyframes.")
        if self.kind not in ("video", "audio") and self.volume_keyframes:
            raise ValueError("Lautstärke-Keyframes sind nur für Medienclips erlaubt.")
        if self.kind in ("video", "audio"):
            if not 0 <= self.audio_noise_reduction <= 30:
                raise ValueError("Rauschunterdrückung muss zwischen 0 und 30 dB liegen.")
            if not all(-12 <= value <= 12 for value in (self.audio_eq_low, self.audio_eq_mid, self.audio_eq_high)):
                raise ValueError("EQ-Bänder müssen zwischen -12 und +12 dB liegen.")
            if type(self.audio_compressor_enabled) is not bool:
                raise ValueError("Ungültiger Kompressorstatus.")
            if not -60 <= self.audio_compressor_threshold <= 0 or not 1 <= self.audio_compressor_ratio <= 20:
                raise ValueError("Ungültige Kompressoreinstellung.")
            if not 0 <= self.audio_ducking <= 1:
                raise ValueError("Audio-Ducking muss zwischen 0 und 100 % liegen.")
            if not 0 <= self.audio_voice_isolation <= 1:
                raise ValueError("Sprachisolierung muss zwischen 0 und 100 % liegen.")
            if self.audio_channel_mode not in AUDIO_CHANNEL_MODES or not -1 <= self.audio_pan <= 1:
                raise ValueError("Ungültige Kanalsteuerung.")
        previous_volume_time = -1.0
        for keyframe in self.volume_keyframes:
            if not isinstance(keyframe, dict):
                raise ValueError("Ungültiger Lautstärke-Keyframe.")
            try:
                time, value = keyframe["time"], keyframe["volume"]
            except KeyError as exc:
                raise ValueError("Lautstärke-Keyframe-Daten fehlen.") from exc
            if (not all(isinstance(item, (int, float)) and not isinstance(item, bool)
                        and math.isfinite(item) for item in (time, value))):
                raise ValueError("Ungültige Zahl im Lautstärke-Keyframe.")
            time, value = float(time), float(value)
            if time < -1e-7 or time > self.length + 1e-7 or time <= previous_volume_time + 1e-7:
                raise ValueError("Lautstärke-Keyframe-Zeit muss sortiert im Clip liegen.")
            if not 0 <= value <= 1:
                raise ValueError("Lautstärke-Keyframe muss zwischen 0 und 100 % liegen.")
            if keyframe.get("curve", "linear") not in KEYFRAME_CURVES:
                raise ValueError("Ungültige Lautstärke-Keyframe-Kurve.")
            previous_volume_time = time
        if not isinstance(self.group_id, str):
            raise ValueError("Ungültige Clip-Gruppe.")
        if self.source_type not in ("video", "audio", "image", "image_sequence", "text", "adjustment"):
            raise ValueError("Ungültiger Quellentyp.")
        if not isinstance(self.source_paths, list) or any(not isinstance(path, str) or not path for path in self.source_paths):
            raise ValueError("Ungültige Bildsequenz.")
        if not isinstance(self.source_fps, (int, float)) or isinstance(self.source_fps, bool) or not math.isfinite(self.source_fps) or not 1 <= self.source_fps <= 120:
            raise ValueError("Ungültige Bildrate der Bildsequenz.")
        if self.source_type == "image_sequence" and not self.source_paths:
            raise ValueError("Bildsequenz enthält keine Bilder.")
        if self.source_type == "image" and self.kind != "video":
            raise ValueError("Ein Standbild muss auf einer Videospur liegen.")
        if self.source_type == "image_sequence" and self.kind != "video":
            raise ValueError("Eine Bildsequenz muss auf einer Videospur liegen.")
        if self.source_type == "adjustment" and self.kind != "video":
            raise ValueError("Eine Adjustment-Layer muss auf einer Videospur liegen.")
        if not isinstance(self.background_removed_path, str):
            raise ValueError("Ungültiger Pfad der KI-Hintergrundmaske.")
        if type(self.background_removal_enabled) is not bool or type(self.object_removal_enabled) is not bool:
            raise ValueError("Ungültiger KI-Effektstatus.")
        if self.background_removal_enabled and (self.kind != "video" or self.source_type not in ("video", "image")):
            raise ValueError("KI-Hintergrundentfernung ist nur für Video- und Bildclips erlaubt.")
        if self.object_removal_enabled and self.kind != "video":
            raise ValueError("Objektentfernung ist nur für Videoclips erlaubt.")
        if not isinstance(self.tracking_keyframes, list):
            raise ValueError("Ungültige Motion-Tracking-Daten.")
        if self.kind != "video" and self.tracking_keyframes:
            raise ValueError("Motion-Tracking ist nur für Videoclips erlaubt.")
        previous_tracking_time = -1.0
        for point in self.tracking_keyframes:
            if not isinstance(point, dict):
                raise ValueError("Ungültiger Motion-Tracking-Punkt.")
            try:
                values = (point["time"], point["x"], point["y"], point["width"], point["height"])
            except KeyError as exc:
                raise ValueError("Motion-Tracking-Punkt enthält unvollständige Daten.") from exc
            if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(float(value)) for value in values):
                raise ValueError("Ungültige Motion-Tracking-Zahl.")
            time, x, y, width, height = map(float, values)
            if time < -1e-7 or time > self.length + 1e-7 or time <= previous_tracking_time + 1e-7:
                raise ValueError("Motion-Tracking-Zeit muss sortiert im Clip liegen.")
            if not 0 <= x <= 1 or not 0 <= y <= 1 or not 0 < width <= 1 or not 0 < height <= 1:
                raise ValueError("Motion-Tracking-Bereich liegt außerhalb des Bildes.")
            if x + width > 1.000001 or y + height > 1.000001:
                raise ValueError("Motion-Tracking-Bereich liegt außerhalb des Bildes.")
            previous_tracking_time = time
        if self.kind == "text":
            if not isinstance(self.text, str) or not self.text.strip():
                raise ValueError("Textclip darf nicht leer sein.")
            if type(self.font_size) is not int or not 8 <= self.font_size <= 240:
                raise ValueError("Ungültige Textgröße.")
            for color in (self.color, self.outline_color, self.shadow_color, self.background_color):
                if (not isinstance(color, str) or not color.startswith("#") or len(color) not in (4, 7)
                        or any(ch not in "0123456789abcdefABCDEF" for ch in color[1:])):
                    raise ValueError("Ungültige Textfarbe oder Stilfarbe.")
            if not isinstance(self.font_family, str) or not self.font_family.strip() or len(self.font_family) > 120:
                raise ValueError("Ungültige Schriftart.")
            if type(self.font_bold) is not bool or type(self.font_italic) is not bool:
                raise ValueError("Ungültiger Schriftschnitt.")
            if (not isinstance(self.outline_width, (int, float)) or not math.isfinite(self.outline_width)
                    or not 0 <= self.outline_width <= 20):
                raise ValueError("Die Konturstärke muss zwischen 0 und 20 liegen.")
            if (not isinstance(self.shadow_size, (int, float)) or not math.isfinite(self.shadow_size)
                    or not 0 <= self.shadow_size <= 40):
                raise ValueError("Die Schattenstärke muss zwischen 0 und 40 liegen.")
            if type(self.background_enabled) is not bool or type(self.background_padding) is not int or not 0 <= self.background_padding <= 80:
                raise ValueError("Ungültiger Texthintergrund.")
            if not isinstance(self.background_opacity, (int, float)) or not math.isfinite(self.background_opacity) or not 0 <= self.background_opacity <= 1:
                raise ValueError("Die Hintergrunddeckkraft muss zwischen 0 und 100 % liegen.")
            if self.text_animation not in TEXT_ANIMATIONS:
                raise ValueError("Ungültige Textanimation.")
            if (not isinstance(self.text_animation_duration, (int, float)) or not math.isfinite(self.text_animation_duration)
                    or not 0.05 <= self.text_animation_duration <= 10):
                raise ValueError("Die Animationsdauer muss zwischen 0,05 und 10 Sekunden liegen.")
            if not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in (self.x, self.y)):
                raise ValueError("Textposition muss zwischen 0 und 1 liegen.")
            return
        if self.kind == "video":
            if not 0.1 <= self.video_scale <= 4:
                raise ValueError("Der Bildzoom muss zwischen 0,1× und 4× liegen.")
            if not all(0 <= value <= 1 for value in (self.video_x, self.video_y)):
                raise ValueError("Die Bildposition muss zwischen 0 % und 100 % liegen.")
            if not all(0 <= value < 1 for value in
                       (self.crop_left, self.crop_top, self.crop_right, self.crop_bottom)):
                raise ValueError("Zuschneiden muss zwischen 0 % und 100 % liegen.")
            if self.crop_left+self.crop_right >= 0.99 or self.crop_top+self.crop_bottom >= 0.99:
                raise ValueError("Der Zuschnitt darf nicht das gesamte Bild entfernen.")
            if type(self.flip_horizontal) is not bool or type(self.flip_vertical) is not bool:
                raise ValueError("Ungültige Spiegelungsoption.")
            if not -360 <= self.rotation <= 360:
                raise ValueError("Die Rotation muss zwischen -360° und 360° liegen.")
            if not -1 <= self.brightness <= 1 or not 0 <= self.contrast <= 3 or not 0 <= self.saturation <= 3:
                raise ValueError("Ungültige Farbkorrektur.")
            if not 0 <= self.opacity <= 1 or not 0 <= self.blur <= 20 or not 0 <= self.sharpen <= 5:
                raise ValueError("Ungültiger Videoeffekt.")
            if not 0 <= self.stabilization <= 1:
                raise ValueError("Stabilisierung muss zwischen 0 und 100 % liegen.")
            if self.effect_preset not in EFFECT_PRESETS and self.effect_preset != "custom":
                raise ValueError("Ungültiges Effekt-Preset.")
            if self.filter_preset not in FILTER_PRESETS:
                raise ValueError("Ungültiger Filter.")
            if not isinstance(self.lut_path, str):
                raise ValueError("Ungültiger LUT-Pfad.")
            if type(self.chroma_key_enabled) is not bool or not isinstance(self.chroma_key_color, str):
                raise ValueError("Ungültiger Greenscreen.")
            if (not self.chroma_key_color.startswith("#") or len(self.chroma_key_color) not in (4, 7)
                    or any(ch not in "0123456789abcdefABCDEF" for ch in self.chroma_key_color[1:])):
                raise ValueError("Ungültige Greenscreen-Farbe.")
            if not 0 <= self.chroma_key_similarity <= 1 or not 0 <= self.chroma_key_blend <= 1:
                raise ValueError("Greenscreen-Werte müssen zwischen 0 und 100 % liegen.")
            if self.mask_type not in MASK_TYPES or not all(0 <= value <= 1 for value in
                                                            (self.mask_x, self.mask_y, self.mask_width,
                                                             self.mask_height, self.mask_feather)):
                raise ValueError("Ungültige Maske.")
            if self.mask_width <= 0 or self.mask_height <= 0 or self.mask_x+self.mask_width > 1.000001 or self.mask_y+self.mask_height > 1.000001:
                raise ValueError("Die Maske muss innerhalb des Bildes liegen.")
            previous_time = -1.0
            for keyframe in self.keyframes:
                if not isinstance(keyframe, dict):
                    raise ValueError("Ungültiger Keyframe.")
                try:
                    values = (keyframe["time"], keyframe["scale"], keyframe["x"],
                              keyframe["y"], keyframe["rotation"],
                              keyframe.get("opacity", self.opacity),
                              keyframe.get("blur", self.blur))
                except KeyError as exc:
                    raise ValueError("Keyframe-Daten fehlen.") from exc
                if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                           and math.isfinite(value) for value in values):
                    raise ValueError("Ungültige Zahl im Keyframe.")
                time, scale, x, y, rotation, opacity, blur = map(float, values)
                if keyframe.get("curve", "linear") not in KEYFRAME_CURVES:
                    raise ValueError("Ungültige Keyframe-Kurve.")
                if time < -1e-7 or time > self.length + 1e-7 or time <= previous_time + 1e-7:
                    raise ValueError("Keyframe-Zeit muss sortiert im Clip liegen.")
                if not 0.1 <= scale <= 4 or not all(0 <= value <= 1 for value in (x, y)):
                    raise ValueError("Ungültige Keyframe-Transformation.")
                if not -360 <= rotation <= 360:
                    raise ValueError("Die Keyframe-Rotation muss zwischen -360° und 360° liegen.")
                if not 0 <= opacity <= 1 or not 0 <= blur <= 20:
                    raise ValueError("Ungültiger Keyframe-Videoeffekt.")
                previous_time = time
        if self.transition_type not in TRANSITION_TYPES or self.transition_duration < 0:
            raise ValueError("Ungültiger Übergang.")
        if self.transition_duration > self.length:
            raise ValueError("Die Übergangsdauer darf nicht länger als der Clip sein.")
        if files and self.lut_path and not Path(self.lut_path).is_file():
            raise ValueError(f"LUT-Datei fehlt:\n{self.lut_path}")
        if files and self.source_type != "adjustment" and not Path(self.path).is_file():
            raise ValueError(f"Quelldatei fehlt:\n{self.path}")
        if files and self.source_type == "image_sequence":
            missing = next((path for path in self.source_paths if not Path(path).is_file()), None)
            if missing:
                raise ValueError(f"Bild der Bildsequenz fehlt:\n{missing}")


def probe(path):
    resolved = Path(path).resolve()
    try:
        stat = resolved.stat()
        cache_key = (str(resolved), stat.st_mtime_ns, stat.st_size)
        cached = _PROBE_CACHE.get(cache_key)
        if cached is not None:
            return cached
    except OSError:
        cache_key = None
    r = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(resolved)],
                       capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise ValueError("Datei nicht lesbar: " + Path(path).name)
    data = json.loads(r.stdout)
    streams = data.get("streams", [])
    video = any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic") for s in streams)
    audio = any(s.get("codec_type") == "audio" for s in streams)
    durations = [float(s.get("duration") or 0) for s in streams]
    duration = float(data.get("format", {}).get("duration") or max(durations, default=0))
    if video and duration < MIN_CLIP and resolved.suffix.lower() in IMAGE_EXTENSIONS:
        duration = DEFAULT_STILL_DURATION
    if not (video or audio) or not math.isfinite(duration) or duration < MIN_CLIP:
        raise ValueError("Keine unterstützte Video-/Audiodatei: " + Path(path).name)
    result = (duration, video, audio)
    if cache_key is not None:
        _PROBE_CACHE[cache_key] = result
        # Keep the cache bounded for long editing sessions with many imports.
        if len(_PROBE_CACHE) > 512:
            _PROBE_CACHE.pop(next(iter(_PROBE_CACHE)))
    return result


def import_clip(path):
    path = str(Path(path).resolve())
    duration, video, audio = probe(path)
    kind = "video" if video else "audio"
    source_type = "image" if video and Path(path).suffix.lower() in IMAGE_EXTENSIONS else kind
    return Clip(path, duration, end=duration, kind=kind, track=1 if video else -1,
                has_audio=audio, source_type=source_type)


def import_image_sequence(paths, fps=24.0):
    """Create one video-track asset from an ordered list of still images."""
    resolved = [str(Path(path).resolve()) for path in paths]
    if not resolved or any(Path(path).suffix.lower() not in IMAGE_EXTENSIONS for path in resolved):
        raise ValueError("Eine Bildsequenz darf nur PNG-, JPG-, BMP-, WebP- oder TIFF-Bilder enthalten.")
    for path in resolved:
        if not Path(path).is_file():
            raise ValueError(f"Bild fehlt:\n{path}")
        # ffprobe validates that the image is actually decodable. Its duration
        # is intentionally ignored because a still image has no useful source
        # duration of its own.
        probe(path)
    fps = float(fps)
    if not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError("Die Bildrate muss zwischen 1 und 120 FPS liegen.")
    duration = len(resolved) / fps
    return Clip(resolved[0], duration, end=duration, kind="video", track=1,
                has_audio=False, source_type="image_sequence", source_paths=resolved,
                source_fps=fps)


def parse_subtitle_timestamp(value):
    """Parse SRT/VTT timestamps into seconds."""
    token = str(value).strip().split()[0].replace(',', '.')
    parts = token.split(':')
    try:
        if len(parts) == 2:
            minutes, seconds = parts
            hours = 0.0
        elif len(parts) == 3:
            hours, minutes, seconds = parts
        else:
            raise ValueError
        result = float(hours) * 3600 + float(minutes) * 60 + float(seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Ungültiger Untertitel-Zeitstempel: {value}") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Ungültiger Untertitel-Zeitstempel: {value}")
    return result


def _clean_subtitle_text(value):
    """Convert common SRT/VTT markup to plain multiline text for drawtext."""
    value = value.replace('\\N', '\n')
    value = re.sub(r'\{\\an[1-9]\}', '', value, flags=re.IGNORECASE)
    value = re.sub(r'<br\s*/?>', '\n', value, flags=re.IGNORECASE)
    value = re.sub(r'</?(?:b|i|u|ruby|rt)(?:\s[^>]*)?>', '', value, flags=re.IGNORECASE)
    value = re.sub(r'<c(?:\.[^ >]+)?[^>]*>', '', value, flags=re.IGNORECASE)
    value = re.sub(r'</c>', '', value, flags=re.IGNORECASE)
    value = re.sub(r'<[^>]+>', '', value)
    return value.strip()


def parse_subtitle_file(path):
    """Read an SRT or WebVTT file and return sorted start/end/text cues."""
    source = Path(path).resolve()
    if source.suffix.lower() not in SUBTITLE_EXTENSIONS:
        raise ValueError("Unterstützt werden nur SRT- und VTT-Dateien.")
    try:
        raw = source.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError:
        raw = source.read_text(encoding='cp1252')
    normalized = raw.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n\s*\n', normalized)
    cues = []
    for block in blocks:
        lines = [line.strip() for line in block.split('\n')]
        lines = [line for line in lines if line or not lines]
        timing_index = next((index for index, line in enumerate(lines) if '-->' in line), None)
        if timing_index is None:
            continue
        left, right = lines[timing_index].split('-->', 1)
        right = right.strip().split()[0]
        start = parse_subtitle_timestamp(left)
        end = parse_subtitle_timestamp(right)
        text = _clean_subtitle_text('\n'.join(lines[timing_index + 1:]))
        if end <= start or not text:
            continue
        cues.append({'start': round(start, 6), 'end': round(end, 6), 'text': text})
    cues.sort(key=lambda cue: (cue['start'], cue['end'], cue['text']))
    if not cues:
        raise ValueError(f"Keine gültigen Untertitel in {source.name} gefunden.")
    return cues


def subtitle_cues_from_clips(clips, track_names=None):
    """Convert subtitle text clips to sorted, exportable cue dictionaries.

    If the project has explicitly named subtitle tracks, only those tracks are
    exported. Otherwise all text clips are treated as subtitle cues, which is
    useful for projects created manually with ``+ Text``.
    """
    track_names = track_names or {}
    text_clips = [clip for clip in clips if clip.kind == 'text' and str(clip.text).strip()]
    named_subtitle_tracks = {
        int(track) for track, name in track_names.items()
        if isinstance(name, str) and name.strip().casefold().startswith(('untertitel', 'subtitle', 'caption'))
    }
    if named_subtitle_tracks:
        text_clips = [clip for clip in text_clips if clip.track in named_subtitle_tracks]
    cues = []
    for clip in text_clips:
        start = max(0.0, float(clip.position))
        end = max(start, float(clip.finish))
        if end <= start + 1e-7:
            continue
        cues.append({'start': round(start, 6), 'end': round(end, 6), 'text': str(clip.text).strip()})
    cues.sort(key=lambda cue: (cue['start'], cue['end'], cue['text']))
    return cues


def _subtitle_timestamp(seconds, separator=','):
    """Format a timestamp for SRT or WebVTT without float drift."""
    milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{milliseconds:03d}"


def write_subtitle_file(path, clips, track_names=None, format=None):
    """Write text clips as an SRT or WebVTT sidecar subtitle file."""
    target = Path(path).expanduser().resolve()
    format = (format or target.suffix.lstrip('.')).casefold()
    if format not in ('srt', 'vtt'):
        raise ValueError("Untertitelformat muss SRT oder VTT sein.")
    cues = subtitle_cues_from_clips(clips, track_names)
    if not cues:
        raise ValueError("Keine exportierbaren Untertitel gefunden.")
    blocks = []
    separator = '.' if format == 'vtt' else ','
    for index, cue in enumerate(cues, 1):
        timing = f"{_subtitle_timestamp(cue['start'], separator)} --> {_subtitle_timestamp(cue['end'], separator)}"
        if format == 'vtt':
            blocks.append(f"{timing}\n{cue['text']}")
        else:
            blocks.append(f"{index}\n{timing}\n{cue['text']}")
    content = ('WEBVTT\n\n' if format == 'vtt' else '') + '\n\n'.join(blocks) + '\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(content, encoding='utf-8', newline='\n')
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return str(target)


def length(clips):
    return max((c.finish for c in clips), default=0.0)


def normalize_markers(markers, duration=None):
    """Validate and normalize timeline markers while keeping old projects valid."""
    if markers is None:
        return []
    if not isinstance(markers, list):
        raise ValueError("Ungültige Marker-Daten.")
    limit = 864000.0 if duration is None else max(0.0, float(duration))
    normalized = []
    for raw in markers:
        if not isinstance(raw, dict):
            raise ValueError("Ungültiger Timeline-Marker.")
        try:
            time = float(raw.get('time', 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Ungültige Marker-Zeit.") from exc
        if not math.isfinite(time) or time < -1e-7 or time > limit + 1e-6:
            raise ValueError("Marker-Zeit liegt außerhalb der Timeline.")
        kind = str(raw.get('kind', 'marker'))
        if kind not in MARKER_KINDS:
            raise ValueError("Ungültiger Marker-Typ.")
        label = raw.get('label', '')
        if not isinstance(label, str):
            raise ValueError("Marker-Name muss Text sein.")
        label = label.strip()[:80]
        if not label:
            label = 'Kapitel' if kind == 'chapter' else 'Marker'
        color = raw.get('color', MARKER_COLORS[kind])
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            color = MARKER_COLORS[kind]
        normalized.append({'time': round(max(0.0, min(limit, time)), 6),
                           'label': label, 'kind': kind, 'color': color.lower()})
    normalized.sort(key=lambda value: (value['time'], value['kind'], value['label'].casefold()))
    return normalized


def normalize_track_states(track_states, tracks):
    """Return validated mixer and edit flags for every track.

    The extra mixer fields are intentionally optional so v1/v2/v3 projects
    load with neutral audio settings.
    """
    if track_states is None:
        track_states = {}
    if not isinstance(track_states, dict):
        raise ValueError("Ungültige Spurstatus-Daten.")
    normalized = {}
    for track in tracks:
        raw = track_states.get(track, track_states.get(str(track), {}))
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("Ungültiger Spurstatus.")
        muted = raw.get("muted", False)
        locked = raw.get("locked", False)
        solo = raw.get("solo", False)
        volume = raw.get("volume", 1.0)
        pan = raw.get("pan", 0.0)
        if (type(muted) is not bool or type(locked) is not bool or type(solo) is not bool
                or not isinstance(volume, (int, float)) or isinstance(volume, bool)
                or not math.isfinite(float(volume)) or not 0 <= float(volume) <= 2
                or not isinstance(pan, (int, float)) or isinstance(pan, bool)
                or not math.isfinite(float(pan)) or not -1 <= float(pan) <= 1):
            raise ValueError("Spurstatus enthält ungültige Mute-, Solo-, Fader- oder Panoramawerte.")
        normalized[int(track)] = {"muted": muted, "locked": locked, "solo": solo,
                                  "volume": round(float(volume), 6), "pan": round(float(pan), 6)}
    return normalized


def normalize_master_mixer(settings=None):
    """Validate master mixer settings while keeping old projects neutral."""
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError("Ungültige Master-Mixer-Daten.")
    volume = settings.get('volume', DEFAULT_MASTER_MIXER['volume'])
    pan = settings.get('pan', DEFAULT_MASTER_MIXER['pan'])
    normalization = settings.get('loudness_normalization', DEFAULT_MASTER_MIXER['loudness_normalization'])
    target = settings.get('loudness_target', DEFAULT_MASTER_MIXER['loudness_target'])
    if (not isinstance(volume, (int, float)) or isinstance(volume, bool)
            or not math.isfinite(float(volume)) or not 0 <= float(volume) <= 2
            or not isinstance(pan, (int, float)) or isinstance(pan, bool)
            or not math.isfinite(float(pan)) or not -1 <= float(pan) <= 1
            or type(normalization) is not bool
            or not isinstance(target, (int, float)) or isinstance(target, bool)
            or not math.isfinite(float(target)) or not -30 <= float(target) <= -5):
        raise ValueError("Ungültige Master-Mixer-Daten.")
    return {'volume': round(float(volume), 6), 'pan': round(float(pan), 6),
            'loudness_normalization': normalization, 'loudness_target': round(float(target), 6)}


def normalize_track_names(track_names, tracks):
    """Keep only non-empty custom names for the currently existing tracks."""
    if track_names is None:
        track_names = {}
    if not isinstance(track_names, dict):
        raise ValueError("Ungültige Spurnamen.")
    normalized = {}
    for track in tracks:
        raw = track_names.get(track, track_names.get(str(track), ""))
        if raw is None:
            raw = ""
        if not isinstance(raw, str):
            raise ValueError("Spurname muss Text sein.")
        raw = raw.strip()
        if raw:
            normalized[int(track)] = raw[:48]
    return normalized


def validate_timeline(clips, tracks, files=True):
    if not tracks or any(type(t) is not int or t == 0 for t in tracks) or len(set(tracks)) != len(tracks):
        raise ValueError("Ungültige Spurliste.")
    if len({c.uid for c in clips}) != len(clips):
        raise ValueError("Doppelte Clip-ID.")
    for c in clips:
        c.validate(files)
        if c.track not in tracks:
            raise ValueError("Clip verweist auf eine fehlende Spur.")
    for track in tracks:
        ordered = sorted((c for c in clips if c.track == track), key=lambda c: c.position)
        for a, b in zip(ordered, ordered[1:]):
            if a.finish > b.position + 1e-6:
                raise ValueError("Clips dürfen sich auf derselben Spur nicht überlappen.\nNutze eine andere Spur oder eine freie Stelle.")
    transition_pairs(clips)


def transition_pairs(clips):
    """Return incoming-clip transitions and reject transitions without a neighbour."""
    pairs = {}
    for incoming in clips:
        if (incoming.kind not in ("video", "audio") or incoming.source_type == "adjustment"
                or incoming.transition_type == "none" or incoming.transition_duration <= 0):
            continue
        previous = max((candidate for candidate in clips
                        if candidate.uid != incoming.uid and candidate.track == incoming.track
                        and candidate.kind == incoming.kind and candidate.finish <= incoming.position + 1e-6),
                       key=lambda candidate: candidate.finish, default=None)
        if previous is None or abs(previous.finish-incoming.position) > 1e-5:
            raise ValueError("Ein Übergang braucht einen direkt angrenzenden Clip derselben Spur.")
        duration = min(incoming.transition_duration, previous.length, incoming.length)
        if duration <= 0:
            raise ValueError("Der Übergang ist zu kurz.")
        pairs[incoming.uid] = (previous.uid, duration, incoming.transition_type)
    return pairs


def split_clip(clip, timeline_time):
    offset = timeline_time - clip.position
    if offset < MIN_CLIP or clip.length-offset < MIN_CLIP:
        raise ValueError("Setze den Abspielkopf innerhalb des ausgewählten Clips.")
    base_length = speed_ramp_duration(clip.end-clip.start, clip.speed, clip.speed_keyframes)
    if clip.freeze_frame and offset > base_length + 1e-7:
        raise ValueError("Ein Freeze-Frame-Bereich kann nicht geteilt werden.")
    source_offset = speed_ramp_source_offset(clip.end-clip.start, clip.speed, clip.speed_keyframes, offset)
    split_source_time = clip.start+source_offset
    first = replace(clip, end=split_source_time,
                    freeze_frame=False,freeze_duration=0.0,
                    keyframes=retime_keyframes(clip,clip.start,split_source_time,clip.speed),
                    volume_keyframes=retime_volume_keyframes(clip,clip.start,split_source_time,clip.speed),
                    speed_keyframes=retime_speed_keyframes(clip,clip.start,split_source_time),
                    tracking_keyframes=retime_tracking_keyframes(clip,clip.start,split_source_time,clip.speed))
    second = replace(clip, start=split_source_time, position=timeline_time, uid=uuid.uuid4().hex,
                     keyframes=retime_keyframes(clip,split_source_time,clip.end,clip.speed),
                     volume_keyframes=retime_volume_keyframes(clip,split_source_time,clip.end,clip.speed),
                     speed_keyframes=retime_speed_keyframes(clip,split_source_time,clip.end),
                     tracking_keyframes=retime_tracking_keyframes(clip,split_source_time,clip.end,clip.speed))
    return first, second


def snap_time(time, targets, tolerance):
    if targets:
        nearest = min(targets, key=lambda t: abs(t-time))
        if abs(nearest-time) <= tolerance:
            return max(0.0, nearest)
    return max(0.0, time)


KEYFRAME_FIELDS = ("scale", "x", "y", "rotation", "opacity", "blur")
KEYFRAME_DEFAULTS = {"scale": "video_scale", "x": "video_x", "y": "video_y",
                     "rotation": "rotation", "opacity": "opacity", "blur": "blur"}

def curve_progress(progress, curve="linear"):
    """Map a normalized 0..1 progress value through a keyframe curve."""
    value = max(0.0, min(1.0, float(progress)))
    curve = curve if curve in KEYFRAME_CURVES else "linear"
    if curve == "ease_in":
        return value * value
    if curve == "ease_out":
        return 1.0 - (1.0-value) * (1.0-value)
    if curve == "ease_in_out":
        return 2.0*value*value if value < .5 else 1.0-((-2.0*value+2.0)**2)/2.0
    return value


def keyframe_curve_expression(progress_expression, curve="linear"):
    """Build an FFmpeg expression for a normalized keyframe curve."""
    p = f"({progress_expression})"
    curve = curve if curve in KEYFRAME_CURVES else "linear"
    if curve == "ease_in":
        return f"pow({p},2)"
    if curve == "ease_out":
        return f"(1-pow(1-{p},2))"
    if curve == "ease_in_out":
        return f"if(lt({p},0.5),2*pow({p},2),1-pow(-2*{p}+2,2)/2)"
    return p


def _keyframe_curve_at(clip, local_time):
    """Return the outgoing curve at a local time for retiming operations."""
    frames = clip.keyframes if clip.kind == "video" else []
    curve = "linear"
    for frame in frames:
        if float(frame.get("time", 0.0)) <= float(local_time) + 1e-7:
            curve = frame.get("curve", "linear")
        else:
            break
    return curve if curve in KEYFRAME_CURVES else "linear"


def _volume_keyframe_curve_at(clip, local_time):
    frames = clip.volume_keyframes if clip.kind in ("video", "audio") else []
    curve = "linear"
    for frame in frames:
        if float(frame.get("time", 0.0)) <= float(local_time) + 1e-7:
            curve = frame.get("curve", "linear")
        else:
            break
    return curve if curve in KEYFRAME_CURVES else "linear"


def _keyframe_value(clip, frame, field):
    """Read a keyframe field while keeping older project files valid."""
    return float(frame.get(field, getattr(clip, KEYFRAME_DEFAULTS[field])))


def _keyframe_values(clip, local_time):
    """Interpolate animated transform values at a local clip time."""
    values = {field: float(getattr(clip, KEYFRAME_DEFAULTS[field])) for field in KEYFRAME_FIELDS}
    frames = clip.keyframes if clip.kind == "video" else []
    if not frames:
        return values
    time = max(0.0, float(local_time))
    first = frames[0]
    if time < float(first["time"]):
        return values
    if time <= float(first["time"]):
        return {field: _keyframe_value(clip, first, field) for field in KEYFRAME_FIELDS}
    for left, right in zip(frames, frames[1:]):
        left_time = float(left["time"])
        right_time = float(right["time"])
        if time <= right_time:
            ratio = (time-left_time)/max(1e-9, right_time-left_time)
            ratio = curve_progress(ratio, left.get("curve", "linear"))
            return {field: _keyframe_value(clip, left, field) +
                    (_keyframe_value(clip, right, field)-_keyframe_value(clip, left, field))*ratio
                    for field in KEYFRAME_FIELDS}
    return {field: _keyframe_value(clip, frames[-1], field) for field in KEYFRAME_FIELDS}


def animated_blur_filters(clip, subdivisions_per_second=8):
    """Approximate a smooth blur curve with cheap timeline-enabled filters.

    FFmpeg's Gaussian blur accepts a fixed sigma per filter. Short enabled
    segments avoid a per-pixel blend expression, keeping live preview fast
    while following the same keyframe values in preview and export.
    """
    if clip.kind != "video" or not clip.keyframes or not any("blur" in frame for frame in clip.keyframes):
        return []
    boundaries = {0.0, round(float(clip.length), 6)}
    boundaries.update(round(float(frame["time"]), 6) for frame in clip.keyframes)
    boundaries = sorted(value for value in boundaries if 0 <= value <= clip.length + 1e-7)
    result = []
    for left, right in zip(boundaries, boundaries[1:]):
        duration = right-left
        if duration <= 1e-7:
            continue
        steps = max(1, min(16, math.ceil(duration*subdivisions_per_second)))
        for index in range(steps):
            start = left + duration*index/steps
            end = left + duration*(index+1)/steps
            value = _keyframe_values(clip, (start+end)/2)["blur"]
            if value > 1e-7:
                result.append(f"gblur=sigma={value:.6f}:enable='gte(t,{start:.6f})*lt(t,{end:.6f})'")
    return result


def keyframe_expression(clip, field, time_expression="t"):
    """Build an FFmpeg expression for one animated transform property."""
    if field not in KEYFRAME_FIELDS:
        raise ValueError("Unbekannte Keyframe-Eigenschaft.")

    def number(value):
        return f"{float(value):.6f}"

    frames = clip.keyframes if clip.kind == "video" else []
    if not frames:
        return number(getattr(clip, KEYFRAME_DEFAULTS[field]))
    expression = number(_keyframe_value(clip, frames[-1], field))
    for left, right in reversed(list(zip(frames, frames[1:]))):
        left_time = float(left["time"])
        right_time = float(right["time"])
        duration = max(1e-9, right_time-left_time)
        left_value = _keyframe_value(clip, left, field)
        right_value = _keyframe_value(clip, right, field)
        curve = keyframe_curve_expression(
            f"(({time_expression}-{number(left_time)})/{number(duration)})",
            left.get("curve", "linear"))
        interpolated = (f"({number(left_value)}+({number(right_value)}-{number(left_value)})*"
                        f"{curve})")
        expression = f"if(lt({time_expression},{number(right_time)}),{interpolated},{expression})"
    first_time = float(frames[0]["time"])
    if first_time > 1e-7:
        base = number(getattr(clip, KEYFRAME_DEFAULTS[field]))
        expression = f"if(lt({time_expression},{number(first_time)}),{base},{expression})"
    return expression


def _volume_keyframe_value(clip, local_time):
    """Interpolate automated volume at a local clip time."""
    frames = clip.volume_keyframes if clip.kind in ("video", "audio") else []
    if not frames:
        return clip.volume
    time = max(0.0, float(local_time))
    first = frames[0]
    if time < float(first["time"]):
        return clip.volume
    if time <= float(first["time"]):
        return float(first["volume"])
    for left, right in zip(frames, frames[1:]):
        left_time = float(left["time"])
        right_time = float(right["time"])
        if time <= right_time:
            ratio = (time-left_time)/max(1e-9, right_time-left_time)
            ratio = curve_progress(ratio, left.get("curve", "linear"))
            return float(left["volume"])+(float(right["volume"])-float(left["volume"]))*ratio
    return float(frames[-1]["volume"])


def volume_keyframe_expression(clip, time_expression="t"):
    """Build an FFmpeg expression for animated clip volume."""
    def number(value):
        return f"{float(value):.6f}"

    frames = clip.volume_keyframes if clip.kind in ("video", "audio") else []
    if not frames:
        return number(clip.volume)
    expression = number(frames[-1]["volume"])
    for left, right in reversed(list(zip(frames, frames[1:]))):
        left_time = float(left["time"])
        right_time = float(right["time"])
        duration = max(1e-9, right_time-left_time)
        curve = keyframe_curve_expression(
            f"(({time_expression}-{number(left_time)})/{number(duration)})",
            left.get("curve", "linear"))
        interpolated = (f"({number(left['volume'])}+({number(right['volume'])}-{number(left['volume'])})*"
                        f"{curve})")
        expression = f"if(lt({time_expression},{number(right_time)}),{interpolated},{expression})"
    first_time = float(frames[0]["time"])
    if first_time > 1e-7:
        expression = f"if(lt({time_expression},{number(first_time)}),{number(clip.volume)},{expression})"
    return expression


def audio_effect_filters(clip):
    """Build deterministic FFmpeg audio filters for one media clip."""
    filters = []
    if clip.audio_noise_reduction > 1e-7:
        filters.append(f"afftdn=nr={clip.audio_noise_reduction:.6f}:nf=-50")
    if clip.audio_voice_isolation > 1e-7:
        # Keep this deliberately portable: distro FFmpeg builds do not all
        # ship the optional dialoguenhance/speechnorm filters.  Mixing both
        # channels towards the centre reduces stereo ambience, while the
        # speech-band limits, denoiser and compressor keep dialogue present
        # without requiring a cloud service or a proprietary model.
        strength = float(clip.audio_voice_isolation)
        cross = .5 * strength
        direct = 1.0 - cross
        filters.append(
            f"pan=stereo|c0={direct:.6f}*c0+{cross:.6f}*c1|"
            f"c1={cross:.6f}*c0+{direct:.6f}*c1"
        )
        filters.append(f"highpass=f={60.0 + 40.0 * strength:.6f}")
        filters.append(f"lowpass=f={16000.0 - 5000.0 * strength:.6f}")
        filters.append(f"afftdn=nr={6.0 + 9.0 * strength:.6f}:nf=-50")
        filters.append(
            f"acompressor=threshold={.125 - .045 * strength:.6f}:"
            f"ratio={2.0 + 2.0 * strength:.6f}:attack=10:release=180:makeup=1"
        )
    bands = ((120, clip.audio_eq_low), (1000, clip.audio_eq_mid), (8000, clip.audio_eq_high))
    for frequency, gain in bands:
        if abs(gain) > 1e-7:
            filters.append(f"equalizer=f={frequency}:t=q:w=1:g={gain:.6f}")
    if clip.audio_compressor_enabled:
        threshold = 10 ** (float(clip.audio_compressor_threshold) / 20.0)
        filters.append(f"acompressor=threshold={threshold:.6f}:ratio={clip.audio_compressor_ratio:.6f}:"
                       "attack=20:release=250:makeup=1")
    if clip.audio_channel_mode == 'mono':
        filters.append("pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1")
    elif clip.audio_channel_mode == 'left':
        filters.append("pan=stereo|c0=c0|c1=c0")
    elif clip.audio_channel_mode == 'right':
        filters.append("pan=stereo|c0=c1|c1=c1")
    if abs(clip.audio_pan) > 1e-7:
        pan = float(clip.audio_pan)
        left_gain = 1.0 if pan < 0 else 1.0-pan
        right_gain = 1.0+pan if pan < 0 else 1.0
        filters.append(f"pan=stereo|c0={left_gain:.6f}*c0|c1={right_gain:.6f}*c1")
    return filters


def track_audio_filters(state):
    """Build a small, deterministic filter chain for one mixer strip."""
    filters = []
    volume = float(state.get('volume', 1.0))
    if abs(volume - 1.0) > 1e-7:
        filters.append(f"volume={volume:.6f}")
    pan = float(state.get('pan', 0.0))
    if abs(pan) > 1e-7:
        left_gain = 1.0 - max(0.0, pan)
        right_gain = 1.0 + min(0.0, pan)
        filters.append(f"pan=stereo|c0={left_gain:.6f}*c0|c1={right_gain:.6f}*c1")
    return filters


def master_audio_filters(settings):
    """Build the final master strip, including optional LUFS normalization."""
    settings = normalize_master_mixer(settings)
    filters = []
    if abs(settings['volume'] - 1.0) > 1e-7:
        filters.append(f"volume={settings['volume']:.6f}")
    if abs(settings['pan']) > 1e-7:
        pan = settings['pan']
        left_gain = 1.0 - max(0.0, pan)
        right_gain = 1.0 + min(0.0, pan)
        filters.append(f"pan=stereo|c0={left_gain:.6f}*c0|c1={right_gain:.6f}*c1")
    if settings['loudness_normalization']:
        filters.append(f"loudnorm=I={settings['loudness_target']:.2f}:TP=-1.5:LRA=11:linear=true")
    # Keep the limiter compatible with the FFmpeg version shipped by Ubuntu.
    # The optional `latency` parameter is unavailable in older FFmpeg builds.
    filters.append("alimiter=limit=0.95:level=0")
    return filters


def retime_speed_keyframes(clip, start, end):
    """Map source-local speed-ramp markers onto a changed source range."""
    if clip.kind != "video" or not clip.speed_keyframes:
        return []
    new_span = max(0.0, end-start)
    old_offset = start-clip.start
    points = [0.0, new_span]
    for frame in clip.speed_keyframes:
        source_time = float(frame['time']) + clip.start
        if start-1e-7 <= source_time <= end+1e-7:
            points.append(source_time-start)
    result = []
    for point in sorted(points):
        point = max(0.0, min(new_span, point))
        value = speed_at_keyframes(clip.speed_keyframes, old_offset+point, clip.speed)
        item = {'time': min(new_span, round(point, 6)), 'speed': round(value, 6)}
        if result and abs(result[-1]['time']-item['time']) <= 1e-6:
            result[-1] = item
        else:
            result.append(item)
    return result


def _filter_escape(value):
    """Escape a filesystem value for an FFmpeg filtergraph script."""
    return (str(value).replace('\\', '\\\\').replace(':', '\\:')
            .replace(',', '\\,').replace("'", "\\'"))


def _ffmpeg_color(value, alpha=None):
    digits = value.lstrip('#')
    if len(digits) == 3:
        digits = ''.join(ch * 2 for ch in digits)
    result = '0x' + digits.lower()
    if alpha is not None:
        result += '@' + f'{float(alpha):.6f}'
    return result


def _text_font_file(clip):
    """Resolve the selected family and style through Linux fontconfig."""
    style = []
    if clip.font_bold:
        style.append('Bold')
    if clip.font_italic:
        style.append('Italic')
    query = clip.font_family.strip()
    if style:
        query += ':style=' + ' '.join(style)
    try:
        result = subprocess.run(['fc-match', '-f', '%{file}', query],
                                capture_output=True, text=True, timeout=5)
        candidate = result.stdout.strip()
        if candidate and Path(candidate).is_file():
            return candidate
    except (OSError, subprocess.SubprocessError):
        pass
    fallback = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    return fallback if Path(fallback).is_file() else None


def _text_animation_expressions(clip):
    """Return x/y/alpha expressions for the selected text animation."""
    target_x = f'(w-text_w)*{clip.x:.6f}'
    target_y = f'(h-text_h)*{clip.y:.6f}'
    if clip.text_animation == 'none':
        return target_x, target_y, None
    duration = max(0.05, float(clip.text_animation_duration))
    entering = f'clip((t-{clip.position:.6f})/{duration:.6f},0,1)'
    leaving = f'clip(({clip.finish:.6f}-t)/{duration:.6f},0,1)'
    alpha = f'min({entering},{leaving})'
    horizontal = '(w+text_w)'
    vertical = '(h+text_h)'
    if clip.text_animation == 'slide_left':
        x = f'({target_x})-{horizontal}*(1-{entering})+{horizontal}*(1-{leaving})'
        return x, target_y, alpha
    if clip.text_animation == 'slide_right':
        x = f'({target_x})+{horizontal}*(1-{entering})-{horizontal}*(1-{leaving})'
        return x, target_y, alpha
    if clip.text_animation == 'slide_up':
        y = f'({target_y})-{vertical}*(1-{entering})+{vertical}*(1-{leaving})'
        return target_x, y, alpha
    if clip.text_animation == 'slide_down':
        y = f'({target_y})+{vertical}*(1-{entering})-{vertical}*(1-{leaving})'
        return target_x, y, alpha
    return target_x, target_y, alpha


def speed_keyframe_expression(clip, time_expression="T"):
    """Build a source-local FFmpeg expression for speed-ramping."""
    if not clip.speed_keyframes:
        return f'{float(clip.speed):.6f}'
    def number(value):
        return f'{float(value):.6f}'
    frames = clip.speed_keyframes
    expression = number(frames[-1]['speed'])
    for left, right in reversed(list(zip(frames, frames[1:]))):
        left_time, right_time = float(left['time']), float(right['time'])
        duration = max(1e-9, right_time-left_time)
        interpolated = (f'({number(left["speed"])}+({number(right["speed"])}-{number(left["speed"])})*'
                        f'(({time_expression}-{number(left_time)})/{number(duration)}))')
        expression = f'if(lt({time_expression},{number(right_time)}),{interpolated},{expression})'
    first_time = float(frames[0]['time'])
    if first_time > 1e-7:
        expression = f'if(lt({time_expression},{number(first_time)}),{number(clip.speed)},{expression})'
    return expression


def preset_filters(clip):
    """Return deterministic built-in filter chains."""
    presets = {
        'vivid': ['eq=contrast=1.1:saturation=1.35'],
        'warm': ['colorbalance=rs=.10:gs=.03:bs=-.08', 'eq=saturation=1.08'],
        'cool': ['colorbalance=rs=-.08:gs=.02:bs=.12', 'eq=saturation=1.04'],
        'cinematic': ['eq=contrast=1.18:saturation=.86:brightness=-.015', 'colorbalance=rs=.03:gs=.01:bs=-.03'],
        'vintage': ['eq=contrast=1.08:saturation=.78:brightness=.025', 'colorbalance=rs=.08:gs=.02:bs=-.06'],
        'noir': ['hue=s=0', 'eq=contrast=1.25:brightness=-.02'],
    }
    return list(presets.get(clip.filter_preset, []))


def tracking_expression(clip, field, time_expression="t"):
    """Interpolate a tracked rectangle field in local clip seconds."""
    defaults = {'x': clip.mask_x, 'y': clip.mask_y,
                'width': clip.mask_width, 'height': clip.mask_height}
    if field not in defaults:
        raise ValueError("Unbekanntes Tracking-Feld.")
    frames = clip.tracking_keyframes if clip.kind == 'video' else []
    if not frames:
        return f'{float(defaults[field]):.6f}'
    def number(value):
        return f'{float(value):.6f}'
    expression = number(frames[-1][field])
    for left, right in reversed(list(zip(frames, frames[1:]))):
        left_time, right_time = float(left['time']), float(right['time'])
        ratio = f'(({time_expression}-{number(left_time)})/{number(max(1e-9, right_time-left_time))})'
        interpolated = f'({number(left[field])}+({number(right[field])}-{number(left[field])})*{ratio})'
        expression = f'if(lt({time_expression},{number(right_time)}),{interpolated},{expression})'
    first_time = float(frames[0]['time'])
    if first_time > 1e-7:
        expression = f'if(lt({time_expression},{number(first_time)}),{number(defaults[field])},{expression})'
    return expression


def mask_filter(clip):
    """Create a soft rectangle/ellipse alpha mask after the frame is scaled."""
    if clip.mask_type == 'none':
        return None
    feather = max(0.0001, float(clip.mask_feather))
    if clip.mask_type == 'rectangle':
        # geq exposes the current frame dimensions as W/H (not iw/ih).
        x_expression = tracking_expression(clip, 'x', 'T')
        y_expression = tracking_expression(clip, 'y', 'T')
        width_expression = tracking_expression(clip, 'width', 'T')
        height_expression = tracking_expression(clip, 'height', 'T')
        left, top = f'W*({x_expression})', f'H*({y_expression})'
        right, bottom = f'W*(({x_expression})+({width_expression}))', f'H*(({y_expression})+({height_expression}))'
        edge = f'min(min(X-({left}),({right})-X),min(Y-({top}),({bottom})-Y))'
        feather_px = f'min(W,H)*{feather:.6f}'
        alpha = f'if(lt({edge},0),0,if(lt({edge},{feather_px}),{edge}/{feather_px},1))'
    else:
        x_expression = tracking_expression(clip, 'x', 'T')
        y_expression = tracking_expression(clip, 'y', 'T')
        width_expression = tracking_expression(clip, 'width', 'T')
        height_expression = tracking_expression(clip, 'height', 'T')
        center_x = f'W*((({x_expression})+({width_expression})/2))'
        center_y = f'H*((({y_expression})+({height_expression})/2))'
        radius_x = f'W*(({width_expression})/2)'
        radius_y = f'H*(({height_expression})/2)'
        distance = f'hypot((X-({center_x}))/({radius_x}),(Y-({center_y}))/({radius_y}))'
        alpha = f'if(gt({distance},1),0,if(gt({distance},1-{feather:.6f}),(1-{distance})/{feather:.6f},1))'
    return f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({alpha})'"


def retime_keyframes(clip, start, end, speed):
    """Map existing keyframes onto a changed source range/speed."""
    if clip.kind != "video" or not clip.keyframes:
        return []
    new_length = (end-start)/speed
    old_local_start = (start-clip.start)/clip.speed
    points = [0.0, new_length]
    for frame in clip.keyframes:
        source_time = clip.start+float(frame["time"])*clip.speed
        if start-1e-7 <= source_time <= end+1e-7:
            points.append((source_time-start)/speed)
    result = []
    for point in sorted(points):
        point = max(0.0, min(new_length, point))
        values = _keyframe_values(clip, old_local_start+point*speed/clip.speed)
        source_time = old_local_start+point*speed/clip.speed
        item = {"time": round(point, 6), "curve": _keyframe_curve_at(clip, source_time),
                **{field: round(values[field], 6) for field in KEYFRAME_FIELDS}}
        if result and abs(result[-1]["time"]-item["time"]) <= 1e-6:
            result[-1] = item
        else:
            result.append(item)
    return result


def retime_volume_keyframes(clip, start, end, speed):
    """Map volume automation onto a changed source range/speed."""
    if clip.kind not in ("video", "audio") or not clip.volume_keyframes:
        return []
    new_length = (end-start)/speed
    old_local_start = (start-clip.start)/clip.speed
    points = [0.0, new_length]
    for frame in clip.volume_keyframes:
        source_time = clip.start+float(frame["time"])*clip.speed
        if start-1e-7 <= source_time <= end+1e-7:
            points.append((source_time-start)/speed)
    result = []
    for point in sorted(points):
        point = max(0.0, min(new_length, point))
        value = _volume_keyframe_value(clip, old_local_start+point*speed/clip.speed)
        source_time = old_local_start+point*speed/clip.speed
        item = {"time": round(point, 6), "volume": round(value, 6),
                "curve": _volume_keyframe_curve_at(clip, source_time)}
        if result and abs(result[-1]["time"]-item["time"]) <= 1e-6:
            result[-1] = item
        else:
            result.append(item)
    return result


def retime_tracking_keyframes(clip, start, end, speed):
    """Keep tracked rectangles aligned after trim, split or speed changes."""
    if clip.kind != "video" or not clip.tracking_keyframes:
        return []
    source_per_local = max(0.25, float(clip.speed))
    new_source_per_local = max(0.25, float(speed))
    new_length = max(0.0, (float(end)-float(start))/new_source_per_local)
    result = []
    for point in clip.tracking_keyframes:
        source_time = float(clip.start) + float(point["time"]) * source_per_local
        if source_time < float(start)-1e-7 or source_time > float(end)+1e-7:
            continue
        item = dict(point)
        item["time"] = round(max(0.0, min(new_length, (source_time-float(start))/new_source_per_local)), 6)
        if result and abs(result[-1]["time"]-item["time"]) <= 1e-6:
            result[-1] = item
        else:
            result.append(item)
    return result


def edited_clip(original, mode, delta, track=None):
    """Pure, clamped geometry; collision validation is performed on commit."""
    if mode == "move":
        return replace(original, position=max(0, original.position+delta), track=track or original.track)
    if mode == "left":
        delta = max(-original.start/original.speed, -original.position, min(delta, original.length-MIN_CLIP))
        start = original.start+delta*original.speed
        return replace(original, start=start, position=original.position+delta,
                       keyframes=retime_keyframes(original,start,original.end,original.speed),
                       volume_keyframes=retime_volume_keyframes(original,start,original.end,original.speed),
                       speed_keyframes=retime_speed_keyframes(original,start,original.end),
                       tracking_keyframes=retime_tracking_keyframes(original,start,original.end,original.speed))
    if mode == "right":
        delta = max(MIN_CLIP-original.length, min(delta, (original.duration-original.end)/original.speed))
        end = original.end+delta*original.speed
        return replace(original, end=end,
                       keyframes=retime_keyframes(original,original.start,end,original.speed),
                       volume_keyframes=retime_volume_keyframes(original,original.start,end,original.speed),
                       speed_keyframes=retime_speed_keyframes(original,original.start,end),
                       tracking_keyframes=retime_tracking_keyframes(original,original.start,end,original.speed))
    raise ValueError("Unbekannte Schnittoperation.")


def slip_clip(original, delta):
    """Shift a clip's source window while keeping its timeline geometry."""
    if original.kind not in ("video", "audio") or original.source_type not in ("video", "audio"):
        raise ValueError("Slip-Schnitt ist nur für Video- und Audiomedien verfügbar.")
    if original.freeze_frame:
        raise ValueError("Ein Clip mit Freeze-Frame kann nicht geslippt werden.")
    span = float(original.end) - float(original.start)
    if span < MIN_CLIP - 1e-7:
        raise ValueError("Der Clip ist zu kurz für einen Slip-Schnitt.")
    maximum = max(0.0, float(original.duration) - span)
    start = max(0.0, min(maximum, float(original.start) + float(delta) * float(original.speed)))
    end = start + span
    # A slip changes the source image underneath the clip; previously
    # analysed positions are no longer trustworthy for the new material.
    return replace(original, start=start, end=end, tracking_keyframes=[])


def roll_edit(left, right, cut_time):
    """Move the cut between two adjacent clips without changing duration."""
    if left.uid == right.uid or left.track != right.track or left.kind != right.kind:
        raise ValueError("Ein Roll-Schnitt braucht zwei Medienclips derselben Spur.")
    if abs(left.finish - right.position) > 1e-5:
        raise ValueError("Ein Roll-Schnitt braucht direkt angrenzende Clips.")
    delta = float(cut_time) - float(left.finish)
    first = edited_clip(left, "right", delta)
    second = edited_clip(right, "left", delta)
    if abs(first.finish - second.position) > 1e-5:
        raise ValueError("Der Roll-Schnitt überschreitet den verfügbaren Quellbereich.")
    return first, second


def slide_edit(previous, clip, following, delta):
    """Move a clip while trimming its directly adjacent neighbours."""
    if len({previous.uid, clip.uid, following.uid}) != 3:
        raise ValueError("Ein Slide-Schnitt braucht drei verschiedene Clips.")
    if not (previous.track == clip.track == following.track):
        raise ValueError("Ein Slide-Schnitt braucht Clips derselben Spur.")
    if not (previous.kind == clip.kind == following.kind):
        raise ValueError("Ein Slide-Schnitt braucht Clips desselben Typs.")
    if abs(previous.finish - clip.position) > 1e-5 or abs(clip.finish - following.position) > 1e-5:
        raise ValueError("Ein Slide-Schnitt braucht zwei direkte Nachbarn.")
    delta = float(delta)
    left = edited_clip(previous, "right", delta)
    middle = replace(clip, position=clip.position + delta)
    right = edited_clip(following, "left", delta)
    if abs(left.finish - middle.position) > 1e-5 or abs(middle.finish - right.position) > 1e-5:
        raise ValueError("Der Slide-Schnitt überschreitet den verfügbaren Quellbereich.")
    return left, middle, right


def atomic_json(path, data):
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".framecut-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_project(path, clips, preset, tracks, assets=(), origin=None, track_states=None, track_names=None, markers=None, mixer=None):
    target = Path(path).resolve()
    validate_timeline(clips, tracks)
    track_states = normalize_track_states(track_states, tracks)
    track_names = normalize_track_names(track_names, tracks)
    markers = normalize_markers(markers, length(clips))
    mixer = normalize_master_mixer(mixer)
    source_files = [path for clip in list(clips)+list(assets)
                    for path in ([clip.path] + list(clip.source_paths)
                                 + ([clip.lut_path] if clip.lut_path else [])
                                 + ([clip.background_removed_path] if clip.background_removed_path else []))]
    if any(Path(path).resolve() == target for path in source_files if path):
        raise ValueError("Projekt darf keine Quelldatei überschreiben.")
    def encode(clip):
        item = asdict(clip)
        item["path"] = (os.path.relpath(clip.path, target.parent)
                        if clip.kind != "text" and clip.source_type != "adjustment" else "")
        if clip.source_type == "image_sequence":
            item["source_paths"] = [os.path.relpath(path, target.parent) for path in clip.source_paths]
        if clip.lut_path:
            item["lut_path"] = os.path.relpath(clip.lut_path, target.parent)
        if clip.background_removed_path:
            item["background_removed_path"] = os.path.relpath(clip.background_removed_path, target.parent)
        return item
    # Marker metadata is optional, so keep the established v2 container
    # version. Older Framecut releases can still open the project and simply
    # ignore the new top-level marker field.
    atomic_json(target, {"format": "framecut", "version": 2, "preset": preset, "tracks": tracks,
                        "track_states": {str(track): state for track, state in track_states.items()},
                        "track_names": {str(track): name for track, name in track_names.items()},
                        "markers": markers,
                        "mixer": mixer,
                        "clips": [encode(c) for c in clips], "assets": [encode(c) for c in assets], "origin": origin})


def load_project(path, allow_missing=False):
    """Load a project, optionally keeping clips whose media is offline.

    Normal project loading remains strict so existing callers still get an
    immediate, useful error.  The editor uses ``allow_missing=True`` for its
    relink workflow and receives the missing absolute paths in the result.
    """
    p = Path(path).resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("format") != "framecut" or data.get("version") not in (1, 2, 3):
        raise ValueError("Keine unterstützte Framecut-Projektdatei.")
    v1 = data["version"] == 1
    def decode(item):
        values = dict(item)
        values.setdefault("group_id", "")
        values.setdefault("source_paths", [])
        values.setdefault("source_fps", 24.0)
        values.setdefault("source_type", "text" if values.get("kind") == "text" else "audio" if values.get("kind") == "audio" else "video")
        if values.get("source_type") == "image_sequence":
            values["source_paths"] = [str((p.parent / source).resolve()) for source in values.get("source_paths", [])]
        if values.get("lut_path"):
            values["lut_path"] = str((p.parent / values["lut_path"]).resolve())
        if values.get("background_removed_path"):
            values["background_removed_path"] = str((p.parent / values["background_removed_path"]).resolve())
        if values.get("kind") == "text" or values.get("source_type") == "adjustment":
            values["path"] = ""
            # Text clips created by pre-1.3 builds used their initial visible
            # duration as the source limit. Keep them freely extendable too.
            if values.get("kind") == "text":
                values["duration"] = max(float(values.get("duration", 0)), 864000.0)
        else:
            values["path"] = str((p.parent/values["path"]).resolve())
        return Clip(**values)
    clips = [decode(item) for item in data["clips"]]
    if v1:
        pos = 0
        source_audio = {}
        for c in clips:
            if c.path not in source_audio:
                source_audio[c.path] = probe(c.path)[2] if Path(c.path).is_file() else c.has_audio
            c.has_audio = source_audio[c.path]
            c.position = pos
            pos = c.finish
    tracks = data.get("tracks", [2, 1, -1, -2])
    validate_timeline(clips, tracks, files=not allow_missing)
    track_states = normalize_track_states(data.get("track_states"), tracks)
    track_names = normalize_track_names(data.get("track_names"), tracks)
    mixer = normalize_master_mixer(data.get("mixer"))
    assets = [decode(item) for item in data.get("assets", [])]
    if not assets:
        seen = set()
        for c in clips:
            if c.kind != "text" and c.source_type != "adjustment" and c.path not in seen:
                assets.append(replace(c, start=0, end=c.duration, position=0, volume=1, uid=uuid.uuid4().hex))
                seen.add(c.path)
    for c in assets:
        c.validate(files=not allow_missing)
    markers = normalize_markers(data.get('markers'), length(clips))
    missing_media = missing_project_media(clips, assets) if allow_missing else []
    return {"clips": clips, "tracks": tracks, "track_states": track_states, "track_names": track_names, "assets": assets,
            "markers": markers, "mixer": mixer, "preset": data.get("preset", next(iter(PRESETS))), "origin": data.get("origin"), "migrated": v1,
            "missing_media": missing_media}


class ExportCancelled(Exception):
    pass


def _canonical_path(path):
    return str(Path(path).expanduser().resolve()) if path else ""


def _clip_media_paths(clip):
    """Return every external file referenced by a clip, without duplicates."""
    if clip.kind == "text":
        return []
    values = [clip.path]
    if clip.source_type == "image_sequence":
        values.extend(clip.source_paths)
    if clip.lut_path:
        values.append(clip.lut_path)
    if clip.background_removed_path:
        values.append(clip.background_removed_path)
    result = []
    seen = set()
    for value in values:
        canonical = _canonical_path(value)
        if canonical and canonical not in seen:
            result.append(canonical)
            seen.add(canonical)
    return result


def missing_project_media(clips, assets=()):
    """Return unique, absolute paths that are not available on disk."""
    missing = []
    seen = set()
    for clip in list(clips) + list(assets):
        for path in _clip_media_paths(clip):
            if path not in seen:
                seen.add(path)
                if not Path(path).is_file():
                    missing.append(path)
    return missing


def relink_project_media(clips, assets, replacements):
    """Return clip/asset copies with the supplied source paths replaced."""
    if not isinstance(replacements, dict):
        raise ValueError("Ungültige Medienverknüpfungen.")
    normalized = {}
    for old, new in replacements.items():
        old_path = _canonical_path(old)
        new_path = _canonical_path(new)
        if not old_path or not new_path or not Path(new_path).is_file():
            raise ValueError(f"Neue Quelldatei fehlt:\n{new}")
        normalized[old_path] = new_path

    def mapped(path):
        if not path:
            return path
        return normalized.get(_canonical_path(path), path)

    def relink(clip):
        return replace(clip,
                       path=mapped(clip.path),
                       source_paths=[mapped(path) for path in clip.source_paths],
                       lut_path=mapped(clip.lut_path),
                       background_removed_path=mapped(clip.background_removed_path))

    return [relink(clip) for clip in clips], [relink(asset) for asset in assets]


def find_relink_candidates(missing_paths, directory):
    """Index files in a folder by basename for deterministic auto-relinking."""
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Ordner nicht gefunden:\n{directory}")
    by_name = {}
    for candidate in root.rglob("*"):
        if candidate.is_file():
            by_name.setdefault(candidate.name.casefold(), []).append(str(candidate.resolve()))
    return {str(Path(path).resolve()): sorted(by_name.get(Path(path).name.casefold(), []))
            for path in missing_paths}


def _archive_file_name(project_name):
    if project_name:
        name = Path(str(project_name)).name
        if not name.lower().endswith(".framecut"):
            name += ".framecut"
        if name != ".framecut":
            return name
    return "Mein-Film.framecut"


def archive_project(path, project_name, clips, preset, tracks, assets=(), origin=None,
                    track_states=None, track_names=None, progress=lambda value: None,
                    cancel=None, markers=None, mixer=None):
    """Create a standalone ZIP containing the project and every referenced file."""
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    cancel = cancel or threading.Event()
    validate_timeline(clips, tracks)
    for asset in assets:
        asset.validate()

    source_files = []
    seen = set()
    for clip in list(clips) + list(assets):
        for source in _clip_media_paths(clip):
            if source not in seen:
                source_files.append(source)
                seen.add(source)
    if target in {Path(source).resolve() for source in source_files}:
        raise ValueError("Das Archiv darf keine Quelldatei überschreiben.")
    for source in source_files:
        if not Path(source).is_file():
            raise ValueError(f"Medium fehlt:\n{source}")

    temporary_zip = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with tempfile.TemporaryDirectory(prefix=".framecut-archive-", dir=str(target.parent)) as work_name:
            work = Path(work_name)
            media_dir = work / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            mapping = {}
            used_names = set()
            total = max(1, len(source_files))
            for index, source in enumerate(source_files, 1):
                if cancel.is_set():
                    raise ExportCancelled()
                source_path = Path(source)
                filename = source_path.name or "media"
                if filename in used_names:
                    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
                    filename = f"{source_path.stem}-{digest}{source_path.suffix}"
                counter = 2
                candidate = filename
                while candidate in used_names:
                    candidate = f"{source_path.stem}-{counter}{source_path.suffix}"
                    counter += 1
                filename = candidate
                used_names.add(filename)
                destination = media_dir / filename
                shutil.copy2(source_path, destination)
                mapping[source] = str(destination.resolve())
                progress(int(index / total * 72))

            archived_clips, archived_assets = relink_project_media(clips, assets, mapping)
            project_file = work / _archive_file_name(project_name)
            save_project(project_file, archived_clips, preset, tracks, archived_assets,
                         origin=None, track_states=track_states, track_names=track_names, markers=markers, mixer=mixer)
            progress(82)
            with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                members = sorted(path for path in work.rglob("*") if path.is_file())
                for index, member in enumerate(members, 1):
                    if cancel.is_set():
                        raise ExportCancelled()
                    archive.write(member, member.relative_to(work).as_posix())
                    progress(82 + int(index / max(1, len(members)) * 17))
        os.replace(temporary_zip, target)
    finally:
        if temporary_zip.exists():
            try:
                temporary_zip.unlink()
            except OSError:
                pass
    progress(100)
    return str(target)


def extract_project_archive(path, destination=None):
    """Safely extract a Framecut archive and return its contained project."""
    archive_path = Path(path).expanduser().resolve()
    if not archive_path.is_file():
        raise ValueError(f"Archiv nicht gefunden:\n{path}")
    if destination is None:
        destination = Path(tempfile.mkdtemp(prefix="framecut-archive-"))
    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    root = str(destination)
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            relative = Path(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Archiv enthält einen ungültigen Pfad.")
            target = (destination / relative).resolve()
            if os.path.commonpath((root, str(target))) != root:
                raise ValueError("Archiv enthält einen ungültigen Pfad.")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    projects = sorted(destination.rglob("*.framecut"))
    if not projects:
        raise ValueError("Das Archiv enthält keine Framecut-Projektdatei.")
    return str(projects[0])


def proxy_path_for(source_path, proxy_directory, kind="video", profile="360p"):
    """Return a stable, non-colliding path for a generated preview proxy."""
    if profile not in PROXY_PROFILES:
        raise ValueError("Unbekanntes Proxy-Profil.")
    source = _canonical_path(source_path)
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(source).stem)[:48] or "media"
    suffix = ".m4a" if kind == "audio" else ".mp4"
    return str((Path(proxy_directory).expanduser().resolve() / f"{stem}-{digest}.proxy-{profile}{suffix}"))


def create_proxy(source_path, target_path, kind="video", progress=lambda value: None,
                 cancel=None, profile="360p"):
    """Generate one low-resolution, editor-only proxy without touching the source."""
    if profile not in PROXY_PROFILES:
        raise ValueError("Unbekanntes Proxy-Profil.")
    source = Path(source_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Quelldatei fehlt:\n{source}")
    if target.is_file() and target.stat().st_size > 0:
        progress(100)
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    cancel = cancel or threading.Event()
    duration = max(MIN_CLIP, probe(source)[0])
    with tempfile.TemporaryDirectory(prefix=".framecut-proxy-", dir=str(target.parent)) as work_name:
        work = Path(work_name)
        temporary = work / f"proxy{target.suffix}"
        progress_file = work / "progress.txt"
        log_file = work / "error.txt"
        args = ["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-y", "-i", str(source)]
        if kind == "audio":
            args += ["-vn", "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "2"]
        else:
            proxy_info = PROXY_PROFILES[profile]
            args += ["-map", "0:v:0", "-map", "0:a:0?", "-vf",
                     f"scale={proxy_info['width']}:{proxy_info['height']}:force_original_aspect_ratio=decrease:force_divisible_by=2",
                     "-c:v", "libx264", "-preset", proxy_info['preset'], "-crf", str(proxy_info['crf']), "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "2", "-shortest"]
        args += ["-movflags", "+faststart", "-progress", str(progress_file), str(temporary)]
        with log_file.open("w+") as log:
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=log)
            while process.poll() is None:
                if cancel.wait(.12):
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                    raise ExportCancelled()
                try:
                    lines = progress_file.read_text().splitlines()
                    stamps = [int(line.split("=", 1)[1]) for line in lines
                              if line.startswith("out_time_us=") and line.split("=", 1)[1].lstrip("-").isdigit()]
                    if stamps:
                        progress(min(99, max(0, int(stamps[-1] / 1e6 / duration * 100))))
                except (OSError, ValueError):
                    pass
            if cancel.is_set():
                raise ExportCancelled()
            if process.returncode:
                log.seek(0)
                raise RuntimeError(log.read()[-3500:] or "FFmpeg konnte die Proxy-Datei nicht erzeugen.")
        os.replace(temporary, target)
    progress(100)
    return str(target)


def create_proxy_files(clips, assets, proxy_directory, progress=lambda value: None,
                       cancel=None, profile="360p"):
    """Generate/reuse proxies for all video and audio sources in a project."""
    if profile not in PROXY_PROFILES:
        raise ValueError("Unbekanntes Proxy-Profil.")
    cancel = cancel or threading.Event()
    sources = {}
    for clip in list(clips) + list(assets):
        if (clip.kind not in ("video", "audio") or clip.source_type in ("image", "image_sequence")
                or not clip.path):
            continue
        source = _canonical_path(clip.path)
        sources.setdefault(source, clip.kind)
    mapping = {}
    total = max(1, len(sources))
    for index, (source, kind) in enumerate(sorted(sources.items()), 1):
        if cancel.is_set():
            raise ExportCancelled()
        target = proxy_path_for(source, proxy_directory, kind, profile)
        create_proxy(source, target, kind, lambda value, index=index: progress(
            int(((index - 1) + value / 100) / total * 100)), cancel, profile)
        mapping[source] = target
        progress(int(index / total * 100))
    progress(100)
    return mapping


def normalize_export_settings(settings=None, preview=False):
    """Validate and fill the export profile used by the real FFmpeg render."""
    values = dict(DEFAULT_EXPORT_SETTINGS)
    if settings is not None:
        if not isinstance(settings, dict):
            raise ValueError("Ungültige Export-Einstellungen.")
        values.update(settings)
    if preview:
        values.update(format='mp4', video_codec='h264', fps=24.0, bitrate_kbps=0,
                      encoder='software', hdr=False)
    if values.get('format') not in EXPORT_FORMATS:
        raise ValueError("Unbekanntes Exportformat.")
    if values.get('video_codec') not in EXPORT_CODEC_LABELS:
        raise ValueError("Unbekannter Videocodec.")
    if values['video_codec'] not in EXPORT_FORMATS[values['format']]['codecs']:
        raise ValueError(f"{EXPORT_CODEC_LABELS[values['video_codec']]} ist für {EXPORT_FORMATS[values['format']]['label']} nicht geeignet.")
    if values.get('encoder') not in EXPORT_ENCODER_LABELS:
        raise ValueError("Unbekannter Export-Encoder.")
    try:
        fps = float(values.get('fps'))
        bitrate = int(round(float(values.get('bitrate_kbps'))))
    except (TypeError, ValueError) as exc:
        raise ValueError("FPS und Bitrate müssen Zahlen sein.") from exc
    if not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError("Die Export-FPS müssen zwischen 1 und 120 liegen.")
    if not 256 <= bitrate <= 200000 and not (preview and bitrate == 0):
        raise ValueError("Die Videobitrate muss zwischen 256 und 200000 kbit/s liegen.")
    if type(values.get('hdr')) is not bool:
        raise ValueError("Ungültiger HDR-Status.")
    if values['hdr'] and values['video_codec'] not in ('hevc', 'av1'):
        raise ValueError("HDR benötigt H.265/HEVC oder AV1.")
    if values['encoder'] == 'nvenc' and values['video_codec'] not in ('h264', 'hevc', 'av1'):
        raise ValueError("NVIDIA NVENC unterstützt diesen Videocodec nicht.")
    if values['encoder'] == 'vaapi' and values['video_codec'] not in ('h264', 'hevc'):
        raise ValueError("VAAPI unterstützt H.264 und H.265/HEVC.")
    values['fps'] = fps
    values['bitrate_kbps'] = bitrate
    return values


@lru_cache(maxsize=None)
def ffmpeg_encoder_available(encoder):
    """Return whether the installed FFmpeg exposes an encoder by name."""
    try:
        result = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-h', f'encoder={encoder}'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _vaapi_device():
    configured = os.environ.get('FRAMECUT_VAAPI_DEVICE', '').strip()
    if configured and Path(configured).is_char_device():
        return configured
    dri = Path('/dev/dri')
    if dri.is_dir():
        devices = sorted(path for path in dri.glob('renderD*') if path.is_char_device())
        if devices:
            return str(devices[0])
    return None


def resolve_export_encoder(settings):
    """Resolve a user-facing encoder mode to software or a real hardware path."""
    codec = settings['video_codec']
    software = EXPORT_VIDEO_ENCODERS[codec]
    mode = settings['encoder']
    if mode == 'software':
        return 'software', software, None
    if mode == 'nvenc':
        encoder = {'h264': 'h264_nvenc', 'hevc': 'hevc_nvenc', 'av1': 'av1_nvenc'}[codec]
        if not ffmpeg_encoder_available(encoder):
            raise ValueError(f"FFmpeg unterstützt {encoder} auf diesem System nicht.")
        return 'nvenc', encoder, None
    if mode == 'vaapi':
        device = _vaapi_device()
        encoder = {'h264': 'h264_vaapi', 'hevc': 'hevc_vaapi'}[codec]
        if not device:
            raise ValueError("Kein VAAPI-Gerät gefunden. Prüfe /dev/dri oder wähle Software / CPU.")
        if not ffmpeg_encoder_available(encoder):
            raise ValueError(f"FFmpeg unterstützt {encoder} auf diesem System nicht.")
        return 'vaapi', encoder, device
    # Auto only selects hardware when a device is actually present. Merely
    # listing an NVENC encoder is not enough on systems without a GPU.
    if Path('/dev/nvidia0').exists() and codec in ('h264', 'hevc', 'av1'):
        encoder = {'h264': 'h264_nvenc', 'hevc': 'hevc_nvenc', 'av1': 'av1_nvenc'}[codec]
        if ffmpeg_encoder_available(encoder):
            return 'nvenc', encoder, None
    device = _vaapi_device()
    if device and codec in ('h264', 'hevc'):
        encoder = {'h264': 'h264_vaapi', 'hevc': 'hevc_vaapi'}[codec]
        if ffmpeg_encoder_available(encoder):
            return 'vaapi', encoder, device
    return 'software', software, None


def render(clips, tracks, target, size=(1920,1080), progress=lambda n: None, cancel=None, preview=False,
           track_states=None, export_settings=None, preview_acceleration=False, master_settings=None):
    """Same composition for preview and export: upper video wins, all audio mixes."""
    export_settings = normalize_export_settings(export_settings, preview=preview)
    validate_timeline(clips, tracks)
    track_states = normalize_track_states(track_states, tracks)
    master_settings = normalize_master_mixer(master_settings)
    solo_tracks = {track for track, state in track_states.items() if state["solo"]}
    muted_tracks = {track for track, state in track_states.items()
                    if state["muted"] or (solo_tracks and track not in solo_tracks)}
    transitions = transition_pairs(clips)
    transition_out = {previous_uid: (incoming_uid, duration, kind)
                      for incoming_uid, (previous_uid, duration, kind) in transitions.items()}
    if not clips:
        raise ValueError("Die Timeline ist leer.")
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise ExportCancelled()
    target = Path(target).resolve()
    source_files = [path for clip in clips
                    for path in ([clip.path] + list(clip.source_paths)
                                 + ([clip.lut_path] if clip.lut_path else [])
                                 + ([clip.background_removed_path] if clip.background_removed_path else []))]
    if any(Path(path).resolve() == target for path in source_files if path):
        raise ValueError("Export darf keine Quelldatei überschreiben.")
    target.parent.mkdir(parents=True, exist_ok=True)
    total = length(clips)
    width, height = size
    args = ["ffmpeg", "-hide_banner", "-v", "error", "-nostdin", "-y"]
    if preview and preview_acceleration and preview_acceleration_info()['available']:
        # FFmpeg keeps the composition filters in software while using the
        # detected decoder for source frames. With no suitable device the
        # editor never enables this flag, so software preview remains safe.
        args += ["-hwaccel", "auto"]
    fps = export_settings['fps']
    format_info = EXPORT_FORMATS[export_settings['format']]
    encoder_kind, video_encoder, vaapi_device = resolve_export_encoder(export_settings)
    if vaapi_device:
        args += ["-vaapi_device", vaapi_device]
    graphs = [f"color=c=black:s={width}x{height}:r={fps}:d={total:.6f}[base]",
              f"anullsrc=r=48000:cl=stereo,atrim=duration={total:.6f}[silence]"]
    infos = []
    input_index = {}
    media_index = 0
    sequence_temp = None
    for i, c in enumerate(clips):
        if cancel.is_set():
            raise ExportCancelled()
        if c.kind == "text":
            infos.append((False, False))
            continue
        if c.source_type == "adjustment":
            infos.append((True, False))
            continue
        source_length = c.end-c.start
        source_path = c.path
        if c.background_removal_enabled:
            if c.source_type == "image_sequence":
                raise ValueError("KI-Hintergrundentfernung ist für Bildsequenzen noch nicht verfügbar.")
            source_path = c.background_removed_path
            if not source_path or not Path(source_path).is_file():
                raise ValueError("Die KI-Hintergrunddatei fehlt. Starte die Hintergrundentfernung erneut.")
        if c.kind == "video" and c.source_type == "image":
            video, audio = True, False
            infos.append((video, audio))
            args += ["-loop", "1", "-framerate", f"{fps:.6f}", "-t", f"{source_length:.6f}", "-i", source_path]
            input_index[i] = media_index
            media_index += 1
            continue
        if c.kind == "video" and c.source_type == "image_sequence":
            if sequence_temp is None:
                sequence_temp = tempfile.TemporaryDirectory(prefix="framecut-sequences-")
            manifest = Path(sequence_temp.name) / f"sequence-{i}.ffconcat"
            frame_duration = 1.0 / float(c.source_fps)
            with manifest.open("w", encoding="utf-8") as stream:
                for source_path in c.source_paths:
                    escaped = str(Path(source_path).resolve()).replace("'", "'\\''")
                    stream.write(f"file '{escaped}'\n")
                    stream.write(f"duration {frame_duration:.9f}\n")
                # The concat demuxer uses the last file once more to honour
                # the duration line belonging to the final frame.
                escaped = str(Path(c.source_paths[-1]).resolve()).replace("'", "'\\''")
                stream.write(f"file '{escaped}'\n")
            infos.append((True, False))
            args += ["-ss", f"{c.start:.6f}", "-t", f"{source_length:.6f}",
                     "-f", "concat", "-safe", "0", "-i", str(manifest)]
            input_index[i] = media_index
            media_index += 1
            continue
        _, video, audio = probe(source_path)
        if c.kind == "video" and not video:
            raise ValueError("Videoquelle enthält kein Video: " + source_path)
        if c.kind == "audio" and not audio:
            raise ValueError("Audioquelle enthält keinen Ton: " + source_path)
        infos.append((video, audio))
        args += ["-threads", "1", "-ss", f"{c.start:.6f}", "-t", f"{source_length:.6f}", "-i", source_path]
        input_index[i] = media_index
        media_index += 1
    last = "base"
    for i in sorted(range(len(clips)), key=lambda i: (clips[i].track, clips[i].position)):
        c = clips[i]
        if c.kind != "video":
            continue
        if c.source_type == "adjustment":
            enabled = f"between(t,{c.position:.6f},{c.finish:.6f})"
            adjustment_filters = []
            for filter_text in preset_filters(c):
                adjustment_filters.append(f"{filter_text}:enable='{enabled}'")
            if abs(c.brightness) > 1e-7 or abs(c.contrast-1) > 1e-7 or abs(c.saturation-1) > 1e-7:
                adjustment_filters.append(
                    f"eq=brightness={c.brightness:.6f}:contrast={c.contrast:.6f}:"
                    f"saturation={c.saturation:.6f}:enable='{enabled}'")
            if c.blur > 1e-7:
                adjustment_filters.append(f"gblur=sigma={c.blur:.6f}:enable='{enabled}'")
            if c.sharpen > 1e-7:
                adjustment_filters.append(f"unsharp=5:5:{c.sharpen:.6f}:5:5:0:enable='{enabled}'")
            if adjustment_filters:
                graphs.append(f"[{last}]"+",".join(adjustment_filters)+f"[adjustment{i}]")
                last = f"adjustment{i}"
            continue
        video_filters=[]
        incoming_transition = transitions.get(c.uid)
        transition_duration = incoming_transition[1] if incoming_transition else 0.0
        transition_kind = incoming_transition[2] if incoming_transition else 'none'
        base_length = c.length - (c.freeze_duration if c.freeze_frame else 0.0)
        if c.source_type in ("image", "image_sequence"):
            video_filters.append(f"trim=duration={c.end-c.start:.6f}")
        if c.reverse and c.source_type not in ('image', 'image_sequence'):
            video_filters.append("reverse")
        video_filters.append("setpts=PTS-STARTPTS")
        if c.speed_keyframes:
            # The expression contains if()/lt() commas; keep it as one
            # filter argument instead of letting the graph parser split it.
            video_filters.append(f"setpts='PTS/({speed_keyframe_expression(c)})'")
            video_filters += [f"trim=duration={base_length:.6f}", "setpts=PTS-STARTPTS"]
        else:
            video_filters.append(f"setpts=PTS/{c.speed:.6f}")
        if c.stabilization > 1e-7:
            # FFmpeg's deshake requires rx/ry to be multiples of 16.
            search_radius = max(16, min(64, round(float(c.stabilization)*3)*16))
            video_filters.append(f"deshake=rx={search_radius}:ry={search_radius}:edge=mirror")
        animated = bool(c.keyframes)
        opacity_animated = animated and any("opacity" in frame for frame in c.keyframes)
        blur_animated = animated and any("blur" in frame for frame in c.keyframes)
        crop_w=1-c.crop_left-c.crop_right
        crop_h=1-c.crop_top-c.crop_bottom
        if any(value > 0 for value in (c.crop_left,c.crop_top,c.crop_right,c.crop_bottom)):
            video_filters.append(
                f"crop=w='iw*{crop_w:.6f}':h='ih*{crop_h:.6f}':"
                f"x='iw*{c.crop_left:.6f}':y='ih*{c.crop_top:.6f}'")
        video_filters.extend(preset_filters(c))
        if abs(c.brightness) > 1e-7 or abs(c.contrast-1) > 1e-7 or abs(c.saturation-1) > 1e-7:
            video_filters.append(f"eq=brightness={c.brightness:.6f}:contrast={c.contrast:.6f}:saturation={c.saturation:.6f}")
        if c.lut_path:
            video_filters.append(f"lut3d=file='{_filter_escape(c.lut_path)}'")
        scale_expression = keyframe_expression(c, "scale") if animated else f"{c.video_scale:.6f}"
        video_filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2")
        if c.object_removal_enabled:
            # delogo accepts pixel coordinates, not normalized expressions on
            # all supported FFmpeg versions.  Apply stepped, timeline-enabled
            # fills after the fixed output scale; a tracked rectangle therefore
            # follows the object without relying on a cloud API.
            video_filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
            points = c.tracking_keyframes or [{
                'time': 0.0, 'x': c.mask_x, 'y': c.mask_y,
                'width': c.mask_width, 'height': c.mask_height,
            }]
            for point_index, point in enumerate(points):
                start_time = max(0.0, float(point['time']))
                if point_index + 1 < len(points):
                    end_time = max(start_time + 1e-6, float(points[point_index + 1]['time']))
                    enable = f"between(t,{start_time:.6f},{end_time:.6f})"
                else:
                    enable = f"gte(t,{start_time:.6f})"
                x_pixel = max(0, min(width - 2, round(float(point['x']) * width)))
                y_pixel = max(0, min(height - 2, round(float(point['y']) * height)))
                w_pixel = max(2, min(width - x_pixel, round(float(point['width']) * width)))
                h_pixel = max(2, min(height - y_pixel, round(float(point['height']) * height)))
                video_filters.append(
                    f"delogo=x={x_pixel}:y={y_pixel}:w={w_pixel}:h={h_pixel}:show=0:enable='{enable}'")
        video_filters += ["setsar=1",f"fps={fps}"]

        # gblur exposes a fixed sigma. Animated blur therefore becomes a
        # short chain of timeline-enabled blur filters. This avoids a costly
        # per-pixel blend expression and keeps the live preview responsive.
        if blur_animated:
            video_filters.extend(animated_blur_filters(c))
        video_filters.append(f"scale=w='max(2,iw*({scale_expression}))':h='max(2,ih*({scale_expression}))':eval=frame")
        if transition_kind == 'zoom' and transition_duration > 0:
            zoom_progress = f"clip(t/{transition_duration:.6f},0,1)"
            video_filters.append(f"scale=w='max(2,iw*(.72+.28*{zoom_progress}))':h='max(2,ih*(.72+.28*{zoom_progress}))':eval=frame")
        if c.flip_horizontal:
            video_filters.append("hflip")
        if c.flip_vertical:
            video_filters.append("vflip")
        if not blur_animated and c.blur > 1e-7:
            video_filters.append(f"gblur=sigma={c.blur:.6f}")
        if c.chroma_key_enabled:
            video_filters.append(f"chromakey={_ffmpeg_color(c.chroma_key_color)}:similarity={c.chroma_key_similarity:.6f}:blend={c.chroma_key_blend:.6f}")
        if c.freeze_frame and c.freeze_duration > 0:
            video_filters.append(f"tpad=stop_mode=clone:stop_duration={c.freeze_duration:.6f}")
        graphs.append(f"[{input_index[i]}:v:0]"+','.join(video_filters)+f"[effects{i}]")
        effect_input = f"[effects{i}]"

        post_filters=[]
        if c.sharpen > 1e-7:
            post_filters.append(f"unsharp=5:5:{c.sharpen:.6f}:5:5:0")
        post_filters.append("format=rgba")
        if animated:
            rotation_expression = keyframe_expression(c, "rotation")
            post_filters.append(f"rotate='({rotation_expression})*0.01745329252':ow=rotw(iw):oh=roth(ih):c=none")
        elif abs(c.rotation) > 1e-6:
            post_filters.append(f"rotate={math.radians(c.rotation):.6f}:ow=rotw(iw):oh=roth(ih):c=none")
        if transition_kind in ('wipe_left', 'wipe_right', 'wipe_up', 'wipe_down') and transition_duration > 0:
            # This filter still sees clip-local time; the overlay is shifted
            # to the timeline position only by the following setpts stage.
            wipe_progress = f"clip(T/{transition_duration:.6f},0,1)"
            if transition_kind == 'wipe_left':
                wipe_alpha = f"if(lt(X,W*({wipe_progress})),1,0)"
            elif transition_kind == 'wipe_right':
                wipe_alpha = f"if(gt(X,W*(1-({wipe_progress}))),1,0)"
            elif transition_kind == 'wipe_up':
                wipe_alpha = f"if(lt(Y,H*({wipe_progress})),1,0)"
            else:
                wipe_alpha = f"if(gt(Y,H*(1-({wipe_progress}))),1,0)"
            post_filters.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({wipe_alpha})'")
        if transition_kind in ('blur_in', 'pixelize') and transition_duration > 0:
            transition_progress = f"clip(t/{transition_duration:.6f},0,1)"
            if transition_kind == 'blur_in':
                post_filters.append(f"gblur=sigma=18:enable='lt(t,{transition_duration:.6f})'")
            else:
                # FFmpeg 4.4 (Ubuntu 22.04) has no pixelize filter. Keep the
                # named transition available with a compatible soft fallback.
                post_filters.append(f"gblur=sigma=14:enable='lt(t,{transition_duration:.6f})'")
        if transition_kind in ('circle_open', 'circle_close', 'radial') and transition_duration > 0:
            transition_progress = f"clip(T/{transition_duration:.6f},0,1)"
            distance = "hypot(X-W/2,Y-H/2)"
            if transition_kind == 'circle_close':
                radius = f"max(W,H)*(1-{transition_progress})"
            else:
                radius = f"max(W,H)*({transition_progress})"
            # geq's alpha() helper is not available on every FFmpeg build;
            # set an explicit opaque/transparent alpha mask instead.
            radial_alpha = f"if(lt({distance},{radius}),255,0)"
            post_filters.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{radial_alpha}'")
        if transition_kind == 'fade_white' and transition_duration > 0:
            post_filters.append(f"fade=t=in:st=0:d={transition_duration:.6f}:color=white")
        mask_expression = mask_filter(c)
        if mask_expression:
            post_filters.append(mask_expression)
        if opacity_animated:
            opacity_expression = keyframe_expression(c, "opacity", f"(N/{fps:.6f})")
            post_filters.append(f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({opacity_expression})'")
        elif c.opacity < 1-1e-7:
            post_filters.append(f"colorchannelmixer=aa={c.opacity:.6f}")
        if c.uid in transitions and transition_kind == "dissolve":
            post_filters.append(f"fade=t=in:st=0:d={transition_duration:.6f}:alpha=1")
        if c.fade_in > 0:
            post_filters.append(f"fade=t=in:st=0:d={c.fade_in:.6f}")
        if c.fade_out > 0:
            post_filters.append(f"fade=t=out:st={max(0,c.length-c.fade_out):.6f}:d={c.fade_out:.6f}")
        post_filters.append(f"setpts=PTS+{c.position:.6f}/TB")
        graphs.append(effect_input+','.join(post_filters)+f"[v{i}]")
        local_time = f"(t-{c.position:.6f})"
        x_expression = keyframe_expression(c, "x", local_time) if animated else f"{c.video_x:.6f}"
        y_expression = keyframe_expression(c, "y", local_time) if animated else f"{c.video_y:.6f}"
        overlay_x = f"(W-w)*({x_expression})"
        overlay_y = f"(H-h)*({y_expression})"
        slide_directions = {
            'slide_left': 'left', 'slide_right': 'right', 'slide_up': 'up', 'slide_down': 'down',
            'smooth_left': 'left', 'smooth_right': 'right', 'smooth_up': 'up', 'smooth_down': 'down',
            'cover_left': 'left', 'cover_right': 'right', 'cover_up': 'up', 'cover_down': 'down',
        }
        if transition_kind in slide_directions and transition_duration > 0:
            raw_progress = f"clip((t-{c.position:.6f})/{transition_duration:.6f},0,1)"
            slide_progress = (f"(1-pow(1-({raw_progress}),3))"
                              if transition_kind.startswith('smooth') else raw_progress)
            direction = slide_directions[transition_kind]
            if direction == 'left':
                overlay_x = f"({overlay_x})+(W+w)*(1-{slide_progress})"
            elif direction == 'right':
                overlay_x = f"({overlay_x})-(W+w)*(1-{slide_progress})"
            elif direction == 'up':
                overlay_y = f"({overlay_y})+(H+h)*(1-{slide_progress})"
            else:
                overlay_y = f"({overlay_y})-(H+h)*(1-{slide_progress})"
        graphs.append(f"[{last}][v{i}]overlay=eof_action=pass:repeatlast=0:"
                      f"x='{overlay_x}':y='{overlay_y}':"
                      f"enable='gte(t,{c.position:.6f})*lt(t,{c.finish:.6f})'[mix{i}]")
        last = f"mix{i}"
        if transition_kind == 'dip_to_black' and transition_duration > 0:
            half = transition_duration/2
            dip_label = f"dip{i}"
            graphs.append(f"color=c=black:s={width}x{height}:r={fps}:d={transition_duration:.6f},format=rgba,"
                          f"fade=t=in:st=0:d={half:.6f}:alpha=1,fade=t=out:st={half:.6f}:d={half:.6f}:alpha=1,"
                          f"setpts=PTS+{c.position-half:.6f}/TB[{dip_label}]")
            graphs.append(f"[{last}][{dip_label}]overlay=eof_action=pass:repeatlast=0:x=0:y=0:"
                          f"enable='gte(t,{c.position-half:.6f})*lt(t,{c.position+half:.6f})'[dipmix{i}]")
            last = f"dipmix{i}"
    audio_entries = [i for i, c in enumerate(clips)
                     if infos[i][1] and c.track not in muted_tracks and (c.volume > 0 or c.volume_keyframes)]
    duck_targets = [i for i in audio_entries if clips[i].audio_ducking > 1e-7]
    duck_slots = {index: slot for slot, index in enumerate(duck_targets)}
    audio_labels = ["[silence]"]
    for i in audio_entries:
        c = clips[i]
        if c.speed_keyframes:
            ramp_length = max(1e-6, c.length-(c.freeze_duration if c.freeze_frame else 0.0))
            tempo = (c.end-c.start)/ramp_length
        else:
            tempo=c.speed
        tempo_filters=[]
        while tempo < 0.5:
            tempo_filters.append('atempo=0.5'); tempo/=0.5
        while tempo > 2.0:
            tempo_filters.append('atempo=2.0'); tempo/=2.0
        tempo_filters.append(f'atempo={tempo:.6f}')
        audio_filters=["aresample=48000","aformat=sample_rates=48000:channel_layouts=stereo",
                       "asetpts=PTS-STARTPTS",f"atrim=duration={c.end-c.start:.6f}"]
        if c.reverse:
            audio_filters.append('areverse')
        audio_filters += tempo_filters
        audio_filters += audio_effect_filters(c)
        if c.volume_keyframes:
            audio_filters.append(f"volume='({volume_keyframe_expression(c)})':eval=frame")
        else:
            audio_filters.append(f"volume={c.volume:.6f}")
        audio_filters += track_audio_filters(track_states.get(c.track, {}))
        if c.fade_in > 0:
            audio_filters.append(f"afade=t=in:st=0:d={c.fade_in:.6f}")
        if c.fade_out > 0:
            audio_filters.append(f"afade=t=out:st={max(0,c.length-c.fade_out):.6f}:d={c.fade_out:.6f}")
        if c.uid in transitions:
            _, transition_duration, transition_kind = transitions[c.uid]
            audio_filters.append(f"afade=t=in:st=0:d={transition_duration:.6f}")
        if c.uid in transition_out:
            _, transition_duration, transition_kind = transition_out[c.uid]
            audio_filters.append(f"afade=t=out:st={max(0,c.length-transition_duration):.6f}:d={transition_duration:.6f}")
        audio_filters.append(f"adelay={round(c.position*48000)}S:all=1")
        if duck_targets:
            # A target never needs its own signal as a sidechain. Omitting
            # that branch keeps every asplit output connected in FFmpeg.
            side_slots = [slot for slot, target_index in enumerate(duck_targets) if target_index != i]
            output_count = 1 + len(side_slots)
            output_labels = [f"[main{i}]"] + [f"[side{i}_{slot}]" for slot in side_slots]
            graphs.append(f"[{input_index[i]}:a:0]"+','.join(audio_filters)+
                          f",asplit={output_count}"+''.join(output_labels))
        else:
            graphs.append(f"[{input_index[i]}:a:0]"+','.join(audio_filters)+f"[a{i}]")
        audio_labels.append(f"[a{i}]")
    if duck_targets:
        for i in audio_entries:
            if i not in duck_slots:
                graphs.append(f"[main{i}]anull[a{i}]")
    for i in duck_targets:
        c = clips[i]
        slot = duck_slots[i]
        sidechain_inputs = [f"[side{other}_{slot}]" for other in audio_entries if other != i]
        if not sidechain_inputs:
            graphs.append(f"[main{i}]anull[a{i}]")
            continue
        sidechain_label = f"[duckside{i}]"
        graphs.append(''.join(sidechain_inputs)+
                      f"amix=inputs={len(sidechain_inputs)}:duration=longest:dropout_transition=0:normalize=0"+
                      ",aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"+
                      sidechain_label)
        ratio = 1.0 + 19.0*float(c.audio_ducking)
        main_label = f"[duckmain{i}]"
        graphs.append(f"[main{i}]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"+
                      main_label)
        graphs.append(f"{main_label}{sidechain_label}sidechaincompress=threshold=0.03:ratio={ratio:.6f}:"
                      f"attack=20:release=250:makeup=1:mix=1[a{i}]")
    graphs.append(''.join(audio_labels)+f"amix=inputs={len(audio_labels)}:duration=first:dropout_transition=0:normalize=0,"
                  + ','.join(master_audio_filters(master_settings)) + "[aout]")
    with tempfile.TemporaryDirectory(prefix=".framecut-render-", dir=target.parent) as work:
        work = Path(work)
        for i in sorted((i for i, c in enumerate(clips) if c.kind == "text"),
                        key=lambda i: (clips[i].track, clips[i].position)):
            c = clips[i]
            textfile = work/f'text-{i}.txt'
            textfile.write_text(c.text, encoding='utf-8')
            fontfile = _text_font_file(c)
            font_part = f"fontfile={_filter_escape(fontfile)}:" if fontfile else "font=Sans:"
            x_expression, y_expression, alpha_expression = _text_animation_expressions(c)
            text_options = [
                font_part.rstrip(':'),
                f"textfile={_filter_escape(textfile)}",
                f"fontcolor={_ffmpeg_color(c.color)}",
                f"fontsize={c.font_size}",
                f"x='{x_expression}'",
                f"y='{y_expression}'",
                f"borderw={round(c.outline_width):d}",
                f"bordercolor={_ffmpeg_color(c.outline_color)}",
                f"shadowx={round(c.shadow_size):d}",
                f"shadowy={round(c.shadow_size):d}",
                f"shadowcolor={_ffmpeg_color(c.shadow_color, .85)}",
                f"box={1 if c.background_enabled else 0}",
                f"boxcolor={_ffmpeg_color(c.background_color, c.background_opacity)}",
                f"boxborderw={c.background_padding}",
                f"enable='gte(t,{c.position:.6f})*lt(t,{c.finish:.6f})'",
            ]
            if alpha_expression:
                text_options.append(f"alpha='{alpha_expression}'")
            graphs.append(f"[{last}]drawtext=" + ':'.join(text_options) + f"[text{i}]")
            last=f"text{i}"
        graphfile = work/"graph.txt"
        graphfile.write_text(';\n'.join(graphs))
        finished = work/f"finished{format_info['extension']}"
        args += ["-filter_complex_threads", "1", "-filter_complex_script", str(graphfile),
                 "-map", f"[{last}]", "-map", "[aout]", "-t", f"{total:.6f}"]
        if encoder_kind == 'vaapi':
            # The composition stays in software; only the final frames are
            # uploaded to the VAAPI device for encoding.
            args += ["-vf", f"format={'p010le' if export_settings['hdr'] else 'nv12'},hwupload"]
        if preview:
            video_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p"]
        elif encoder_kind == 'software':
            video_args = ["-c:v", video_encoder, "-b:v", f"{export_settings['bitrate_kbps']}k"]
            if export_settings['video_codec'] in ('h264', 'hevc'):
                video_args += ["-preset", "fast"]
            elif export_settings['video_codec'] == 'vp9':
                video_args += ["-deadline", "good", "-cpu-used", "4", "-row-mt", "1"]
            else:
                video_args += ["-cpu-used", "6", "-row-mt", "1"]
            video_args += ["-pix_fmt", "yuv420p10le" if export_settings['hdr'] else "yuv420p"]
        elif encoder_kind == 'nvenc':
            video_args = ["-c:v", video_encoder, "-preset", "p4", "-rc", "vbr",
                          "-b:v", f"{export_settings['bitrate_kbps']}k",
                          "-pix_fmt", "p010le" if export_settings['hdr'] else "yuv420p"]
        else:
            video_args = ["-c:v", video_encoder, "-b:v", f"{export_settings['bitrate_kbps']}k"]
        if export_settings['hdr'] and export_settings['video_codec'] == 'hevc':
            video_args += ["-profile:v", "main10"]
        args += video_args + ["-threads", "2"]
        if export_settings['hdr']:
            args += ["-color_primaries", "bt2020", "-color_trc", "smpte2084",
                     "-colorspace", "bt2020nc", "-color_range", "tv"]
        audio_codec = "libopus" if export_settings['format'] == 'webm' else "aac"
        audio_bitrate = "160k" if audio_codec == "libopus" else "192k"
        args += ["-c:a", audio_codec, "-b:a", audio_bitrate, "-ar", "48000", "-ac", "2"]
        if export_settings['format'] in ('mp4', 'mov'):
            args += ["-movflags", "+faststart"]
        if export_settings['format'] in ('mp4', 'mov') and export_settings['video_codec'] == 'hevc':
            args += ["-tag:v", "hvc1"]
        args += ["-f", format_info['muxer'], "-progress", str(work/"progress.txt"), str(finished)]
        with (work/"error.txt").open("w+") as log:
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=log)
            while proc.poll() is None:
                if cancel.wait(.12):
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill(); proc.wait()
                    raise ExportCancelled()
                try:
                    lines = (work/"progress.txt").read_text().splitlines()
                    stamps = [int(s.split('=',1)[1]) for s in lines if s.startswith('out_time_us=') and s[12:].lstrip('-').isdigit()]
                    if stamps:
                        progress(min(99, max(0, int(stamps[-1]/1e6/total*100))))
                except (OSError, ValueError):
                    pass
            if cancel.is_set():
                raise ExportCancelled()
            if proc.returncode:
                log.seek(0)
                raise RuntimeError(log.read()[-3500:] or "FFmpeg konnte das Video nicht rendern.")
        os.replace(finished, target)
    if sequence_temp is not None:
        sequence_temp.cleanup()
    progress(100)
