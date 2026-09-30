"""Local computer-vision helpers used by Framecut's premium toolset.

The module keeps heavyweight imports lazy.  Framecut can still open older
projects on machines that have not installed the optional OpenCV/rembg stack;
the affected action then reports the missing dependency in the editor.
"""
from pathlib import Path
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
