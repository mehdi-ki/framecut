"""Local speech-to-text helpers for Framecut automatic subtitles.

The editor deliberately keeps the speech recognition backend optional at
import time.  ``faster-whisper`` is installed by ``start.sh`` for released
builds, while this module remains importable for the lightweight core tests.
Audio and video are decoded locally; only the model is downloaded the first
time a model size is used.
"""
import math
from pathlib import Path

from core import ExportCancelled, MIN_CLIP


TRANSCRIPTION_MODELS = ('tiny', 'base', 'small')


def _report(progress, value):
    if progress is not None:
        progress(max(0, min(100, int(value))))


def normalize_segments(segments, progress=None, cancel=None, total_duration=None):
    """Convert Whisper segments into editable Framecut subtitle cues.

    This small normalization layer is intentionally independent of the
    Whisper implementation so the timing and cancellation behavior can be
    tested without downloading a model.
    """
    cues = []
    try:
        duration = float(total_duration) if total_duration is not None else 0.0
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        duration = 0.0

    for index, segment in enumerate(segments):
        if cancel is not None and cancel.is_set():
            raise ExportCancelled()
        try:
            start = float(getattr(segment, 'start'))
            end = float(getattr(segment, 'end'))
        except (AttributeError, TypeError, ValueError):
            continue
        text = ' '.join(str(getattr(segment, 'text', '')).strip().split())
        if not math.isfinite(start) or not math.isfinite(end) or not text:
            continue
        start = max(0.0, start)
        end = max(start + MIN_CLIP, end)
        cues.append({'start': round(start, 6), 'end': round(end, 6), 'text': text})

        if duration:
            _report(progress, 24 + min(74, (end / duration) * 74))
        elif progress is not None:
            _report(progress, 24 + min(74, (index + 1) * 2))

    cues.sort(key=lambda cue: (cue['start'], cue['end'], cue['text']))
    return cues


def transcribe_media(path, model_size='base', language='auto', cache_dir=None,
                     progress=None, cancel=None):
    """Transcribe a local audio/video file with faster-whisper.

    Returns a dictionary containing normalized cues and the detected language.
    The backend is imported lazily so opening existing projects never requires
    a model or a speech-to-text import.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f'Medium nicht gefunden:\n{source}')
    model_size = str(model_size or 'base').strip().casefold()
    if model_size not in TRANSCRIPTION_MODELS:
        raise ValueError('Ungültige Whisper-Modellgröße.')
    language = str(language or 'auto').strip().casefold()
    if language != 'auto' and (len(language) != 2 or not language.isalpha()):
        raise ValueError('Ungültige Sprache für die Spracherkennung.')
    if cancel is not None and cancel.is_set():
        raise ExportCancelled()

    _report(progress, 5)
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            'Die lokale Spracherkennung ist noch nicht installiert. '
            'Starte Framecut einmal neu, damit faster-whisper automatisch nachinstalliert wird.'
        ) from exc

    model_cache = Path(cache_dir).expanduser() if cache_dir else None
    if model_cache is not None:
        model_cache.mkdir(parents=True, exist_ok=True)
    _report(progress, 10)
    model_kwargs = {
        'device': 'cpu',
        'compute_type': 'int8',
    }
    if model_cache is not None:
        model_kwargs['download_root'] = str(model_cache)
    model = WhisperModel(model_size, **model_kwargs)
    if cancel is not None and cancel.is_set():
        raise ExportCancelled()
    _report(progress, 22)

    segments, info = model.transcribe(
        str(source),
        language=None if language == 'auto' else language,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    duration = getattr(info, 'duration', None)
    cues = normalize_segments(segments, progress=progress, cancel=cancel,
                              total_duration=duration)
    if not cues:
        raise ValueError('Keine gesprochenen Worte im Medium erkannt.')
    _report(progress, 100)
    detected_language = str(getattr(info, 'language', language or 'auto') or 'auto')
    return {'cues': cues, 'language': detected_language, 'source': str(source)}
