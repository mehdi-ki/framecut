"""Small, testable interaction primitives for Framecut's Smooth Workflow update."""
import json
import os
import re
from pathlib import Path
from dataclasses import replace

from PySide6.QtCore import (Qt, QObject, QEvent, Signal, QTimer, QProcess,
                            QPropertyAnimation, QEasingCurve, QByteArray)
from PySide6.QtGui import QIcon, QPixmap, QPainter, QImage
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QDoubleSpinBox, QSpinBox, QLineEdit,
    QPlainTextEdit, QTextEdit, QComboBox, QWidget, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QToolTip, QGraphicsOpacityEffect)


# A local vector family is independent of the Linux desktop's icon theme.
ICON_PATHS = {
    'document-new': 'M6 3h8l4 4v14H6z M14 3v5h4 M9 14h6 M12 11v6',
    'document-open': 'M3 7h7l2 2h9l-3 11H3z M3 7V4h7l2 3',
    'document-save': 'M4 3h14l3 3v15H3V3z M7 3v6h10V3 M7 21v-8h10v8',
    'document-save-as': 'M4 3h12v7 M3 3v18h10 M7 3v6h6 M14 19l6-6 2 2-6 6-3 1z',
    'view-refresh': 'M20 10a8 8 0 1 0-1 8 M20 4v6h-6',
    'edit-undo': 'M3 9h11a7 7 0 0 1 0 14 M3 9l5-5 M3 9l5 5',
    'edit-redo': 'M21 9H10a7 7 0 0 0 0 14 M21 9l-5-5 M21 9l-5 5',
    'edit-cut': 'M4 4l16 16 M20 4l-7 7 M9 15l-2 2 M8 18a3 3 0 1 1-6 0a3 3 0 1 1 6 0 M8 6a3 3 0 1 1-6 0a3 3 0 1 1 6 0',
    'edit-copy': 'M8 8h13v13H8z M16 8V3H3v13h5',
    'edit-paste': 'M8 5H4v16h16V5h-4 M8 3h8v5H8z',
    'edit-delete': 'M3 6h18 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7',
    'list-add': 'M12 4v16 M4 12h16',
    'view-list': 'M8 5h13 M8 12h13 M8 19h13 M3 5h1 M3 12h1 M3 19h1',
    'view-more': 'M4 12h1 M11 12h1 M18 12h1',
    'system-search': 'M17 10a7 7 0 1 1-14 0a7 7 0 1 1 14 0 M15 15l6 6',
    'view-fullscreen': 'M9 3H3v6 M15 3h6v6 M3 15v6h6 M21 15v6h-6',
    'insert-link': 'M9 8l3-3a5 5 0 0 1 7 7l-3 3 M15 16l-3 3a5 5 0 0 1-7-7l3-3 M8 16l8-8',
    'insert-object': 'M3 3h8v8H3z M14 14h7v7h-7z M11 7h6v7 M14 11l3 3 3-3',
    'package-x-generic': 'M3 7l9-4 9 4v13H3z M3 7l9 4 9-4 M12 11v9',
    'audio-volume-high': 'M3 9h4l5-5v16l-5-5H3z M15 8q5 4 0 8 M18 5q8 7 0 14',
    'media-playback-start': 'M6 3l15 9-15 9z',
    'media-playback-pause': 'M7 4v16 M17 4v16',
    'format-justify-fill': 'M3 5h18 M3 12h18 M3 19h18',
    'object-select': 'M4 3l7 18 3-7 7-3z',
    'bookmark-new': 'M6 3h12v18l-6-4-6 4z M9 9h6 M12 6v6',
    'document-export': 'M5 3h10v5 M5 3v18h14v-5 M12 12h10 M18 8l4 4-4 4',
    'snap-to-grid': 'M4 4v9a8 8 0 0 0 16 0V4h-5v9a3 3 0 0 1-6 0V4z M4 8h5 M15 8h5',
}


def line_icon(name):
    path = ICON_PATHS.get(name)
    if not path:
        return QIcon()
    result = QIcon()
    for mode, color in ((QIcon.Normal, '#cce5ed'), (QIcon.Disabled, '#788997'),
                        (QIcon.Active, '#8dffdf'), (QIcon.Selected, '#8dffdf')):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
               f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.7" '
               'stroke-linecap="round" stroke-linejoin="round"/></svg>')
        pixmap = QPixmap(48, 48); pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap); QSvgRenderer(QByteArray(svg.encode())).render(painter); painter.end()
        result.addPixmap(pixmap, mode)
    return result


class FineDoubleSpinBox(QDoubleSpinBox):
    """No accidental wheel edits; Shift fine step; Esc restores an uncommitted edit."""
    def __init__(self, *args):
        super().__init__(*args)
        self.setKeyboardTracking(False)
        self.reset_value = 0.0
        self.entry_value = self.value()
        self.fine_step = False
        self.lineEdit().installEventFilter(self)

    def eventFilter(self, target, event):
        if target is self.lineEdit() and event.type()==QEvent.MouseButtonDblClick and event.button()==Qt.LeftButton:
            self.setValue(self.reset_value); self.editingFinished.emit(); event.accept(); return True
        return super().eventFilter(target,event)

    def stepBy(self, steps):
        step = self.singleStep()
        if self.fine_step or QApplication.keyboardModifiers() & Qt.ShiftModifier:
            self.setSingleStep(max(10 ** -self.decimals(), step / 10))
        super().stepBy(steps)
        self.setSingleStep(step)

    def focusInEvent(self, event):
        self.entry_value = self.value()
        super().focusInEvent(event)

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore(); return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Shift:
            self.fine_step = True
        if event.key() == Qt.Key_Escape:
            self.setValue(self.entry_value)
            self.lineEdit().setText(self.textFromValue(self.value()) + self.suffix())
            self.clearFocus(); event.accept(); return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Shift:
            self.fine_step = False
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.fine_step = False
        super().focusOutEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setValue(self.reset_value); self.editingFinished.emit(); event.accept(); return
        super().mouseDoubleClickEvent(event)


class InputGuard(QObject):
    """Let text/number editors consume editing shortcuts before application actions."""
    def __init__(self, editor):
        super().__init__(editor); self.editor = editor

    def eventFilter(self, target, event):
        editor = self.editor
        if editor._closing or not isinstance(target, QWidget):
            return False
        if target is not editor and not editor.isAncestorOf(target):
            return False
        kind = event.type()
        if kind == QEvent.ShortcutOverride:
            focus = QApplication.focusWidget()
            typing = isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QDoubleSpinBox, QSpinBox))
            if isinstance(focus, QComboBox):
                typing = focus.isEditable()
            # Save/open remain global. Local clipboard, Undo and Delete stay local.
            global_keys = (Qt.Key_S, Qt.Key_O, Qt.Key_N, Qt.Key_K)
            global_command = bool(event.modifiers() & Qt.ControlModifier) and event.key() in global_keys
            if typing and not global_command:
                event.accept(); return True
        if kind == QEvent.ToolTip and not target.isEnabled():
            reason = target.property('disabledReason') or target.toolTip()
            if reason:
                QToolTip.showText(event.globalPos(), reason, target); return True
        if kind in (QEvent.KeyPress, QEvent.KeyRelease):
            if kind==QEvent.KeyRelease and event.key()==Qt.Key_B and editor.compare_active and not event.isAutoRepeat():
                editor.compare_released(); return True
            focus = QApplication.focusWidget()
            typing = isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QDoubleSpinBox, QSpinBox))
            if event.key() == Qt.Key_B and not event.modifiers() and not typing:
                if not event.isAutoRepeat():
                    editor.compare_pressed() if kind == QEvent.KeyPress else editor.compare_released()
                return True
            if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape and not typing:
                editor.cancel_interaction()
        if kind in (QEvent.WindowDeactivate, QEvent.ApplicationDeactivate):
            editor.compare_released()
        if target is editor.scroll.viewport() and kind == QEvent.Wheel:
            editor.suspend_follow()
        return False


class InlineTask(QWidget):
    canceled = Signal()

    def __init__(self, title, parent):
        super().__init__(parent)
        row = QHBoxLayout(self); row.setContentsMargins(8, 2, 8, 2)
        self.title = QLabel(title); self.title.setWordWrap(True); row.addWidget(self.title, 1)
        self.bar = QProgressBar(); self.bar.setRange(0, 100); self.bar.setMaximumWidth(180); row.addWidget(self.bar)
        self.cancel_button = QPushButton('Abbrechen'); row.addWidget(self.cancel_button)
        self.cancel_button.clicked.connect(self.cancel)

    def cancel(self):
        self.cancel_button.setEnabled(False); self.title.setText('Wird abgebrochen …'); self.canceled.emit()

    def setValue(self, value):
        self.bar.setValue(value)


def load_preferences(path):
    try:
        result = json.loads(Path(path).read_text(encoding='utf-8'))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_preferences(path, data):
    """Replace one preference file atomically; never truncate the previous copy."""
    path = Path(path); temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def scaled_style(style, percent):
    scale = max(1.0, min(1.5, percent / 100))
    return re.sub(r'font-size:\s*(\d+)px',
                  lambda match: f'font-size: {round(int(match[1]) * scale)}px', style)


def fade_in(widget, reduced=False):
    if reduced or not widget.isVisible():
        return
    effect = QGraphicsOpacityEffect(widget); widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b'opacity', widget)
    animation.setDuration(120); animation.setStartValue(.45); animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    widget._fade_animation = animation
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    animation.start()


def error_guidance(message):
    text = str(message); lower = text.casefold()
    if any(token in lower for token in ('permission', 'berechtigung', 'writable', 'beschreibbar')):
        return 'Der Zielordner ist nicht beschreibbar.', 'Wähle beim nächsten Export einen Ordner mit Schreibrechten.', 'export'
    if any(token in lower for token in ('no space', 'speicherplatz', 'disk full')):
        return 'Nicht genügend Speicherplatz.', 'Prüfe freien Speicher und den Vorschau-Cache in der Projekt-Statuszentrale.', 'status'
    if any(token in lower for token in ('not found', 'no such file', 'fehlt', 'fehlen', 'nicht gefunden')):
        return 'Eine Datei oder benötigte Komponente fehlt.', 'Prüfe die Details. Fehlende Projektmedien kannst du neu verknüpfen.', 'relink'
    if any(token in lower for token in ('overlap', 'überlapp', 'überlappung')):
        return 'Clips überlappen auf derselben Spur.', 'Verschiebe den Clip auf eine freie Stelle oder eine andere Spur.', None
    return text.splitlines()[0][:200], 'Die Änderung wurde nicht abgeschlossen. Details lassen sich unten aufklappen.', None


class FrameProbe(QObject):
    """Coalesced, non-blocking FFmpeg frame decoding for trim-edge feedback."""
    ready = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self); self.process.finished.connect(self.finished)
        self.pending = None; self.active = None; self.cache = {}
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(75)
        self.timer.timeout.connect(self.start_next)
        self.timeout = QTimer(self); self.timeout.setSingleShot(True); self.timeout.setInterval(5000)
        self.timeout.timeout.connect(self.process.kill)

    def request(self, path, time, token):
        self.pending = (str(path), max(0.0, float(time)), token)
        self.timer.start()

    def start_next(self):
        if self.pending is None or self.process.state() != QProcess.NotRunning:
            return
        self.active = self.pending; self.pending = None
        path, time, token = self.active; key = (path, round(time, 3))
        if key in self.cache:
            self.ready.emit(token, self.cache[key]); return
        self.process.start('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-nostdin',
            '-ss', f'{time:.6f}', '-i', path, '-frames:v', '1', '-vf', 'scale=240:-2',
            '-threads', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'])
        self.timeout.start()

    def finished(self, *_):
        self.timeout.stop()
        image = QImage.fromData(bytes(self.process.readAllStandardOutput()))
        self.process.readAllStandardError()
        if self.active and not image.isNull():
            path, time, token = self.active
            if len(self.cache) >= 32:
                self.cache.pop(next(iter(self.cache)))
            self.cache[(path, round(time, 3))] = image
            self.ready.emit(token, image)
        self.active = None
        if self.pending:
            self.start_next()

    def stop(self):
        self.pending = None; self.active = None; self.timer.stop(); self.timeout.stop()
        if self.process.state() != QProcess.NotRunning:
            self.process.kill(); self.process.waitForFinished(1500)


def without_visual_effects(clip):
    """Bypass looks/masks only: keep timing, geometry, audio and source identity."""
    if clip.source_type == 'adjustment':
        return replace(clip, enabled=False)
    if clip.kind != 'video':
        return replace(clip)
    defaults = type(clip)(path=clip.path, duration=clip.duration, end=clip.end)
    names = ['brightness', 'contrast', 'saturation', 'filter_preset', 'lut_path',
             'color_exposure', 'color_temperature', 'color_tint', 'color_vibrance',
             'opacity', 'blur', 'sharpen', 'stabilization', 'effect_preset',
             'chroma_key_enabled', 'mask_type', 'background_removal_enabled', 'object_removal_enabled']
    names += [f'color_{wheel}_{color}' for wheel in ('lift', 'gamma', 'gain') for color in ('r', 'g', 'b')]
    values = {name: getattr(defaults, name) for name in names}
    effect_keys = {'opacity', 'blur', 'brightness', 'contrast', 'saturation'}
    values['keyframes'] = [{k: v for k, v in frame.items() if k not in effect_keys} for frame in clip.keyframes]
    return replace(clip, **values)
