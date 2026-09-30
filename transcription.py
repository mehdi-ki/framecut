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
FILLER_PHRASES = {
    'äh', 'ähm', 'ähh', 'hm', 'hmm', 'uh', 'um', 'er', 'erm',
    'you know', 'basically', 'like', 'so', 'also', 'halt', 'quasi',
}


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
        words = []
        for word in (getattr(segment, 'words', None) or []):
            try:
                word_start = float(getattr(word, 'start'))
                word_end = float(getattr(word, 'end'))
            except (AttributeError, TypeError, ValueError):
                continue
            word_text = ' '.join(str(getattr(word, 'word', '')).strip().split())
            if not word_text or not math.isfinite(word_start) or not math.isfinite(word_end):
                continue
            words.append({'start': round(max(start, word_start), 6),
                          'end': round(max(max(start, word_start), word_end), 6),
                          'text': word_text})
        cue = {'start': round(start, 6), 'end': round(end, 6), 'text': text}
        if words:
            cue['words'] = words
        cues.append(cue)

        if duration:
            _report(progress, 24 + min(74, (end / duration) * 74))
        elif progress is not None:
            _report(progress, 24 + min(74, (index + 1) * 2))

    cues.sort(key=lambda cue: (cue['start'], cue['end'], cue['text']))
    return cues


def _normalized_words(text):
    value = ''.join(char.lower() if char.isalnum() or char in 'äöüß' else ' ' for char in str(text))
    return ' '.join(value.split())


def _merge_ranges(ranges, duration):
    normalized = []
    for start, end in ranges:
        start = max(0.0, min(float(duration), float(start)))
        end = max(0.0, min(float(duration), float(end)))
        if end-start < 0.06:
            continue
        if normalized and start <= normalized[-1][1] + 0.015:
            normalized[-1] = (normalized[-1][0], max(normalized[-1][1], end))
        else:
            normalized.append((start, end))
    return [(round(start, 6), round(end, 6)) for start, end in normalized]


def build_text_edit_plan(cues, duration, filler_words=None, gap_threshold=0.45,
                         keep_padding=0.06):
    """Build a local, transcript-driven cut plan for silence and fillers.

    Word timestamps are used when available. Older or mocked transcription
    segments still work: filler-only cues are removed as complete cues and
    pauses between cues are cut without needing word metadata.
    """
    try:
        duration = max(0.0, float(duration))
        gap_threshold = max(0.1, float(gap_threshold))
        keep_padding = max(0.0, min(.2, float(keep_padding)))
    except (TypeError, ValueError) as exc:
        raise ValueError('Ungültige Textschnitt-Zeitdaten.') from exc
    if duration <= 0:
        return {'keep_ranges': [], 'removed_ranges': [], 'removed_seconds': 0.0,
                'filler_segments': 0}
    raw_cues = cues or []
    cues = []
    for cue in sorted(raw_cues, key=lambda value: (float(value.get('start', 0)), float(value.get('end', 0)))):
        try:
            start = max(0.0, min(duration, float(cue['start'])))
            end = max(start, min(duration, float(cue['end'])))
        except (KeyError, TypeError, ValueError):
            continue
        if end-start >= 0.02 and str(cue.get('text', '')).strip():
            cues.append(dict(cue, start=start, end=end))
    if not cues:
        return {'keep_ranges': [(0.0, round(duration, 6))], 'removed_ranges': [],
                'removed_seconds': 0.0, 'filler_segments': 0}

    filler_set = {_normalized_words(value) for value in (filler_words or FILLER_PHRASES)}
    # Context words such as “so” and “also” can be meaningful in a sentence;
    # only remove them when the complete cue is a filler-only cue.
    word_filler_set = filler_set - {'so', 'also', 'halt', 'quasi', 'you know'}
    removed = []
    filler_segments = 0
    if cues[0]['start'] >= gap_threshold:
        removed.append((0.0, max(0.0, cues[0]['start']-keep_padding)))
    for previous, current in zip(cues, cues[1:]):
        gap_start = float(previous['end']) + keep_padding
        gap_end = float(current['start']) - keep_padding
        if gap_end-gap_start >= gap_threshold:
            removed.append((gap_start, gap_end))
    if duration-cues[-1]['end'] >= gap_threshold:
        removed.append((cues[-1]['end']+keep_padding, duration))

    for cue in cues:
        words = cue.get('words') or []
        if words:
            removed_words = []
            for word in words:
                if _normalized_words(word.get('text', '')) in word_filler_set:
                    try:
                        start, end = float(word['start']), float(word['end'])
                    except (KeyError, TypeError, ValueError):
                        continue
                    removed_words.append((max(cue['start'], start-.015), min(cue['end'], end+.015)))
            if removed_words and len(removed_words) == len(words):
                filler_segments += 1
            removed.extend(removed_words)
        elif _normalized_words(cue.get('text', '')) in filler_set:
            removed.append((cue['start'], cue['end']))
            filler_segments += 1

    removed_ranges = _merge_ranges(removed, duration)
    keep_ranges = []
    cursor = 0.0
    for start, end in removed_ranges:
        if start-cursor >= MIN_CLIP-1e-7:
            keep_ranges.append((round(cursor, 6), round(start, 6)))
        cursor = max(cursor, end)
    if duration-cursor >= MIN_CLIP-1e-7:
        keep_ranges.append((round(cursor, 6), round(duration, 6)))
    removed_seconds = sum(end-start for start, end in removed_ranges)
    return {'keep_ranges': keep_ranges, 'removed_ranges': removed_ranges,
            'removed_seconds': round(removed_seconds, 6),
            'filler_segments': filler_segments}


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
        word_timestamps=True,
    )
    duration = getattr(info, 'duration', None)
    cues = normalize_segments(segments, progress=progress, cancel=cancel,
                              total_duration=duration)
    if not cues:
        raise ValueError('Keine gesprochenen Worte im Medium erkannt.')
    _report(progress, 100)
    detected_language = str(getattr(info, 'language', language or 'auto') or 'auto')
    return {'cues': cues, 'language': detected_language, 'source': str(source)}
