"""Local computer-vision helpers used by Framecut's premium toolset.

The module keeps heavyweight imports lazy.  Framecut can still open older
projects on machines that have not installed the optional OpenCV/rembg stack;
the affected action then reports the missing dependency in the editor.
"""
from pathlib import Path
from array import array
import math
import statistics
import shutil
import subprocess


class AIToolError(RuntimeError):
    """User-facing error raised by an optional local AI operation."""


def _cv2():
    try:
        import cv2
    except ImportError as exc:
        raise AIToolError(
            "Für lokale KI-Funktionen fehlt OpenCV. Starte Framecut einmal mit "
            "Internetverbindung, damit die Zusatzpakete installiert werden."
        ) from exc
    return cv2


def _background_session():
    try:
        from rembg import new_session
    except ImportError as exc:
        raise AIToolError(
            "Für KI-Hintergrundentfernung fehlt rembg/onnxruntime. Starte "
            "Framecut einmal mit Internetverbindung, damit die Zusatzpakete "
            "und das Modell installiert werden."
        ) from exc
    try:
        return new_session("u2net")
    except Exception as exc:
        raise AIToolError(
            "Das lokale Hintergrundmodell konnte nicht geladen werden. "
            "Prüfe die Internetverbindung beim ersten Lauf und den freien Speicherplatz."
        ) from exc


def _cancelled(cancel):
    return cancel is not None and cancel.is_set()


def _write_png_bytes(frame, cv2):
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise AIToolError("Ein Videobild konnte nicht für die KI verarbeitet werden.")
    return encoded.tobytes()


def remove_background_media(source, target, progress=lambda value: None, cancel=None):
    """Create a transparent local derivative for an image or complete video.

    Video audio is copied through an intermediate FFmpeg mux.  The derivative
    keeps the original duration, so normal Framecut source trims remain valid.
    """
    source = Path(source).expanduser().resolve()
    target = Path(target).expanduser().resolve()
    if not source.is_file():
        raise AIToolError(f"Quelldatei nicht gefunden: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2 = _cv2()
    session = _background_session()

    image_suffixes = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
    if source.suffix.lower() in image_suffixes:
        from rembg import remove
        try:
            result = remove(source.read_bytes(), session=session, alpha_matting=False,
                            post_process_mask=True)
            target.write_bytes(result)
            progress(100)
            return str(target)
        except Exception as exc:
            raise AIToolError(f"Hintergrund konnte nicht entfernt werden: {exc}") from exc

    from rembg import remove
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise AIToolError(f"Video konnte nicht für die Hintergrundentfernung geöffnet werden: {source.name}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    if not 1.0 <= fps <= 240.0:
        fps = 30.0
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total_frames <= 0:
        capture.release()
        raise AIToolError("Das Video enthält keine verarbeitbaren Frames.")

    process = None
    completed = False
    try:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise AIToolError("FFmpeg fehlt. Installiere es mit: sudo apt install ffmpeg")
        args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "image2pipe", "-vcodec", "png", "-r", f"{fps:.6f}", "-i", "pipe:0",
                "-i", str(source), "-map", "0:v:0", "-map", "1:a?", "-c:v", "qtrle",
                "-pix_fmt", "argb", "-c:a", "aac", "-shortest", str(target)]
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE)
        for index in range(total_frames):
            if _cancelled(cancel):
                raise AIToolError("Hintergrundentfernung abgebrochen.")
            ok, frame = capture.read()
            if not ok:
                break
            try:
                result = remove(_write_png_bytes(frame, cv2), session=session,
                                alpha_matting=False, post_process_mask=True)
                process.stdin.write(result)
            except BrokenPipeError as exc:
                detail = process.stderr.read().decode(errors="replace").strip()
                raise AIToolError("FFmpeg konnte das transparente Video nicht erzeugen. " + detail) from exc
            progress(min(99, int((index + 1) / max(1, total_frames) * 100)))
        process.stdin.close()
        return_code = process.wait(timeout=120)
        detail = process.stderr.read().decode(errors="replace").strip()
        if return_code:
            raise AIToolError("Transparentes Video konnte nicht erzeugt werden." + (f"\n{detail}" if detail else ""))
        progress(100)
        completed = True
        return str(target)
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            process.kill(); process.wait()
        raise AIToolError("Die transparente Videodatei brauchte zu lange.") from exc
    finally:
        capture.release()
        if process is not None and process.poll() is None:
            process.kill(); process.wait()
        if not completed:
            target.unlink(missing_ok=True)


def track_motion(source, start, end, region, progress=lambda value: None, cancel=None, sample_fps=8.0):
    """Track a normalized rectangle through a local video with template matching."""
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise AIToolError(f"Quelldatei nicht gefunden: {source}")
    cv2 = _cv2()
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise AIToolError(f"Video konnte nicht für Motion-Tracking geöffnet werden: {source.name}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    if not 1.0 <= fps <= 240.0:
        fps = 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if frame_count <= 0 or width < 8 or height < 8:
        capture.release()
        raise AIToolError("Das Video enthält keine nutzbaren Trackingdaten.")
    start_frame = max(0, min(frame_count - 1, round(float(start) * fps)))
    end_frame = max(start_frame, min(frame_count - 1, round(float(end) * fps)))
    x_norm, y_norm, w_norm, h_norm = [float(value) for value in region]
    x = max(0, min(width - 2, round(x_norm * width)))
    y = max(0, min(height - 2, round(y_norm * height)))
    box_w = max(4, min(width - x, round(w_norm * width)))
    box_h = max(4, min(height - y, round(h_norm * height)))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    ok, first = capture.read()
    if not ok:
        capture.release()
        raise AIToolError("Das erste Trackingbild konnte nicht gelesen werden.")
    gray = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
    template = gray[y:y + box_h, x:x + box_w]
    if template.size == 0 or template.shape[0] < 4 or template.shape[1] < 4:
        capture.release()
        raise AIToolError("Der Trackingbereich ist zu klein.")
    stride = max(1, round(fps / max(1.0, float(sample_fps))))
    results = []
    frame_index = start_frame
    try:
        while frame_index <= end_frame:
            if _cancelled(cancel):
                raise AIToolError("Motion-Tracking abgebrochen.")
            if frame_index == start_frame:
                frame = first
            else:
                ok, frame = capture.read()
                if not ok:
                    break
            if (frame_index - start_frame) % stride == 0 or not results:
                current = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if current.shape[0] >= template.shape[0] and current.shape[1] >= template.shape[1]:
                    match = cv2.matchTemplate(current, template, cv2.TM_CCOEFF_NORMED)
                    _, score, _, location = cv2.minMaxLoc(match)
                    x, y = int(location[0]), int(location[1])
                    x = max(0, min(width - box_w, x)); y = max(0, min(height - box_h, y))
                    patch = current[y:y + box_h, x:x + box_w]
                    if patch.shape == template.shape:
                        template = cv2.addWeighted(template, .82, patch, .18, 0)
                else:
                    score = 0.0
                results.append({'time': round((frame_index - start_frame) / fps, 6),
                                'x': round(x / width, 6), 'y': round(y / height, 6),
                                'width': round(box_w / width, 6), 'height': round(box_h / height, 6),
                                'score': round(float(score), 6)})
            progress(min(100, int((frame_index - start_frame) / max(1, end_frame - start_frame) * 100)))
            frame_index += 1
        if not results:
            raise AIToolError("Motion-Tracking hat keine Frames gefunden.")
        progress(100)
        return results
    finally:
        capture.release()


def auto_reframe_video(source, start, end, target_aspect, progress=lambda value: None,
                       cancel=None, sample_fps=6.0):
    """Detect faces locally and return smooth normalized Auto-Reframe focus points.

    The detector intentionally returns a usable center fallback when a frame has
    no face. This keeps the feature deterministic for product shots, gameplay,
    and other footage where face detection is not the right signal.
    """
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise AIToolError(f"Quelldatei nicht gefunden: {source}")
    try:
        target_aspect = float(target_aspect)
    except (TypeError, ValueError) as exc:
        raise AIToolError("Ungültiges Auto-Reframe-Format.") from exc
    if not math.isfinite(target_aspect) or target_aspect <= 0:
        raise AIToolError("Ungültiges Auto-Reframe-Format.")
    cv2 = _cv2()
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    if cascade.empty():
        raise AIToolError("Der lokale Gesichtserkenner konnte nicht geladen werden.")

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise AIToolError(f"Video konnte nicht für Auto-Reframe geöffnet werden: {source.name}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    if not 1.0 <= fps <= 240.0:
        fps = 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if frame_count <= 0 or width < 8 or height < 8:
        capture.release()
        raise AIToolError("Das Video enthält keine nutzbaren Auto-Reframe-Frames.")

    start_frame = max(0, min(frame_count - 1, round(float(start) * fps)))
    end_frame = max(start_frame, min(frame_count - 1, round(float(end) * fps)))
    stride = max(1, round(fps / max(1.0, float(sample_fps))))
    total_frames = max(1, end_frame - start_frame + 1)
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    results = []
    previous_center = None
    previous_size = (0.30, 0.30)
    previous_score = 0.0
    last_sampled_frame = None
    try:
        for frame_index in range(start_frame, end_frame + 1):
            if _cancelled(cancel):
                raise AIToolError("Auto-Reframe abgebrochen.")
            ok, frame = capture.read()
            if not ok:
                break
            should_sample = not results or (frame_index - start_frame) % stride == 0 or frame_index == end_frame
            if should_sample:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                detector_width = min(640, width)
                detector_scale = detector_width / float(width)
                if detector_scale < 0.999:
                    detector_height = max(8, round(height * detector_scale))
                    gray = cv2.resize(gray, (detector_width, detector_height), interpolation=cv2.INTER_AREA)
                else:
                    detector_scale = 1.0
                min_face = max(12, round(min(gray.shape[1], gray.shape[0]) / 30))
                faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4,
                                                 minSize=(min_face, min_face))
                candidates = []
                for x, y, box_width, box_height in faces:
                    x = float(x) / detector_scale
                    y = float(y) / detector_scale
                    box_width = float(box_width) / detector_scale
                    box_height = float(box_height) / detector_scale
                    center = ((x + box_width / 2) / width, (y + box_height / 2) / height)
                    candidates.append((box_width * box_height, center,
                                       (box_width / width, box_height / height)))
                if candidates:
                    if previous_center is None:
                        _, detected_center, detected_size = max(candidates, key=lambda item: item[0])
                    else:
                        _, detected_center, detected_size = min(
                            candidates,
                            key=lambda item: ((item[1][0] - previous_center[0]) ** 2
                                              + (item[1][1] - previous_center[1]) ** 2,
                                              -item[0]))
                    if previous_center is None:
                        center = detected_center
                    else:
                        center = (previous_center[0] * .65 + detected_center[0] * .35,
                                  previous_center[1] * .65 + detected_center[1] * .35)
                    previous_center = (max(0.0, min(1.0, center[0])),
                                       max(0.0, min(1.0, center[1])))
                    previous_size = (max(.01, min(1.0, detected_size[0])),
                                     max(.01, min(1.0, detected_size[1])))
                    previous_score = 1.0
                elif previous_center is None:
                    previous_center = (.5, .5)
                    previous_score = 0.0
                else:
                    previous_score = 0.0
                point = {
                    'time': round((frame_index - start_frame) / fps, 6),
                    'x': round(previous_center[0], 6),
                    'y': round(previous_center[1], 6),
                    'width': round(previous_size[0], 6),
                    'height': round(previous_size[1], 6),
                    'score': round(previous_score, 6),
                    'curve': 'ease_in_out',
                }
                results.append(point)
                last_sampled_frame = frame_index
            progress(min(99, int((frame_index - start_frame + 1) / total_frames * 100)))
        if not results:
            raise AIToolError("Auto-Reframe hat keine Frames gefunden.")
        duration = max(0.0, float(end) - float(start))
        if duration > 0 and last_sampled_frame is not None:
            final_time = round(duration, 6)
            if final_time - float(results[-1]['time']) > 1e-6:
                final_point = dict(results[-1])
                final_point['time'] = final_time
                results.append(final_point)
        progress(100)
        return results
    finally:
        capture.release()


def detect_scene_changes(source, start, end, progress=lambda value: None, cancel=None,
                         sample_fps=6.0, threshold=0.22, min_gap=0.4):
    """Detect hard scene changes with a local grayscale frame-difference pass."""
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise AIToolError(f"Quelldatei nicht gefunden: {source}")
    cv2 = _cv2()
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise AIToolError(f"Video konnte nicht für Szenenerkennung geöffnet werden: {source.name}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    if not 1.0 <= fps <= 240.0:
        fps = 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_count <= 0:
        capture.release()
        raise AIToolError("Das Video enthält keine Szenenerkennungs-Frames.")
    start = max(0.0, float(start)); end = max(start, float(end))
    start_frame = max(0, min(frame_count-1, round(start*fps)))
    end_frame = max(start_frame, min(frame_count-1, round(end*fps)))
    stride = max(1, round(fps/max(1.0, float(sample_fps))))
    total_frames = max(1, end_frame-start_frame+1)
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    previous = None
    changes = []
    last_change = -float(min_gap)
    try:
        for frame_index in range(start_frame, end_frame+1):
            if _cancelled(cancel):
                raise AIToolError("Szenenerkennung abgebrochen.")
            ok, frame = capture.read()
            if not ok:
                break
            if (frame_index-start_frame) % stride == 0 or previous is None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (320, 180), interpolation=cv2.INTER_AREA)
                if previous is not None:
                    score = float(cv2.absdiff(gray, previous).mean())/255.0
                    local_time = (frame_index-start_frame)/fps
                    if score >= float(threshold) and local_time-last_change >= float(min_gap):
                        changes.append(round(local_time, 6)); last_change = local_time
                previous = gray
            progress(min(99, int((frame_index-start_frame+1)/total_frames*100)))
        progress(100)
        return changes
    finally:
        capture.release()


def detect_audio_onset(source, start, end, progress=lambda value: None, cancel=None):
    """Return the first audible local onset for multi-camera synchronization."""
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise AIToolError(f"Quelldatei nicht gefunden: {source}")
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise AIToolError('FFmpeg fehlt. Installiere es mit: sudo apt install ffmpeg')
    start = max(0.0, float(start)); duration = max(0.05, float(end)-start)
    sample_rate = 16000; chunk_samples = 512
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
               '-ss', f'{start:.6f}', '-t', f'{duration:.6f}', '-i', str(source),
               '-vn', '-ac', '1', '-ar', str(sample_rate), '-f', 's16le', 'pipe:1']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    energies = []
    try:
        while True:
            if _cancelled(cancel):
                process.terminate()
                raise AIToolError('Multi-Kamera-Synchronisation abgebrochen.')
            data = process.stdout.read(chunk_samples*2)
            if not data:
                break
            samples = array('h'); samples.frombytes(data)
            if samples:
                rms = math.sqrt(sum(float(value)*float(value) for value in samples)/len(samples))/32768.0
                energies.append(rms)
                progress(min(92, int(len(energies)*chunk_samples/sample_rate/duration*92)))
        detail = process.stderr.read().decode(errors='replace').strip()
        return_code = process.wait(timeout=30)
        if return_code:
            raise AIToolError('Audio konnte für die Multi-Kamera-Synchronisation nicht gelesen werden.'
                              + (f'\n{detail}' if detail else ''))
    except subprocess.TimeoutExpired as exc:
        process.kill(); process.wait()
        raise AIToolError('Multi-Kamera-Synchronisation brauchte zu lange.') from exc
    finally:
        if process.poll() is None:
            process.kill(); process.wait()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
    progress(100)
    if not energies or max(energies) < 1e-4:
        return 0.0
    noise_window = energies[:max(1, min(len(energies), round(sample_rate/chunk_samples*.5)))]
    ordered_noise = sorted(noise_window)
    baseline = ordered_noise[min(len(ordered_noise)-1, round((len(ordered_noise)-1)*.2))]
    threshold = max(.012, baseline*3.0)
    for index, energy in enumerate(energies):
        if energy >= threshold:
            return round(index*chunk_samples/sample_rate, 6)
    fallback = max(.012, max(energies)*.15)
    for index, energy in enumerate(energies):
        if energy >= fallback:
            return round(index*chunk_samples/sample_rate, 6)
    return 0.0


def analyze_beats(source, start, end, progress=lambda value: None, cancel=None):
    """Detect musical onsets locally with an FFmpeg PCM energy pass."""
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise AIToolError(f"Quelldatei nicht gefunden: {source}")
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise AIToolError('FFmpeg fehlt. Installiere es mit: sudo apt install ffmpeg')
    start = max(0.0, float(start)); duration = max(0.05, float(end)-start)
    sample_rate = 22050
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
               '-ss', f'{start:.6f}', '-t', f'{duration:.6f}', '-i', str(source),
               '-vn', '-ac', '1', '-ar', str(sample_rate), '-f', 's16le', 'pipe:1']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    energies = []
    chunk_samples = 1024
    try:
        while True:
            if _cancelled(cancel):
                process.terminate()
                raise AIToolError('Beat-Erkennung abgebrochen.')
            data = process.stdout.read(chunk_samples * 2)
            if not data:
                break
            samples = array('h'); samples.frombytes(data)
            if not samples:
                continue
            # Normalize the RMS to a compact, codec-independent energy curve.
            rms = math.sqrt(sum(float(value) * float(value) for value in samples) / len(samples)) / 32768.0
            time = len(energies) * chunk_samples / sample_rate
            energies.append((time, rms))
            progress(min(92, int(time / duration * 92)))
        detail = process.stderr.read().decode(errors='replace').strip()
        return_code = process.wait(timeout=30)
        if return_code:
            raise AIToolError('Audio konnte für die Beat-Erkennung nicht gelesen werden.' + (f'\n{detail}' if detail else ''))
    except subprocess.TimeoutExpired as exc:
        process.kill(); process.wait()
        raise AIToolError('Beat-Erkennung brauchte zu lange.') from exc
    finally:
        if process.poll() is None:
            process.kill(); process.wait()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    if len(energies) < 3 or max(value for _, value in energies) < 1e-4:
        progress(100)
        return {'beats': [], 'bpm': 0.0, 'duration': duration}
    values = [value for _, value in energies]
    baseline_window = max(3, round(sample_rate / chunk_samples * .7))
    beats = []
    minimum_gap = .18
    last_beat = -minimum_gap
    for index in range(1, len(energies)-1):
        time, energy = energies[index]
        left = energies[max(0, index-baseline_window):index]
        baseline = statistics.median(value for _, value in left) if left else statistics.median(values)
        threshold = max(baseline * 1.42, statistics.median(values) * 1.7, .012)
        if energy < threshold or energy < energies[index-1][1] or energy < energies[index+1][1]:
            continue
        if time-last_beat < minimum_gap:
            if beats and energy > beats[-1][1]:
                beats[-1] = (time, energy)
            continue
        beats.append((time, energy)); last_beat = time
    beat_times = [round(time, 6) for time, _ in beats]
    intervals = [beat_times[index]-beat_times[index-1] for index in range(1, len(beat_times))
                 if .25 <= beat_times[index]-beat_times[index-1] <= 1.5]
    bpm = 60.0 / statistics.median(intervals) if intervals else 0.0
    if bpm:
        while bpm < 70:
            bpm *= 2
        while bpm > 180:
            bpm /= 2
    progress(100)
    return {'beats': beat_times, 'bpm': round(bpm, 2), 'duration': duration}
