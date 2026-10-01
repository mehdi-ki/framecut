"""Framecut 3.27.0 — native Linux multitrack editor."""
import math
import json
import os
import sys
import shutil
import threading
import tempfile
import uuid
import subprocess
import inspect
import time
from pathlib import Path
from dataclasses import replace

from PySide6.QtCore import Qt, QUrl, QThread, Signal, QTimer, QLockFile, QSize
from PySide6.QtGui import QAction, QImage, QColor, QFont, QPainter, QPen, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,
    QPushButton,QToolButton,QListWidgetItem,QFileDialog,QMessageBox,QSplitter,QDoubleSpinBox,QFormLayout,
    QComboBox,QSlider,QScrollArea,QProgressDialog,QFrame,QCheckBox,QStackedWidget,QSpinBox,QLineEdit,QInputDialog,QSizePolicy,QMenu,QColorDialog,QListWidget,QFontComboBox,QDialog,QDialogButtonBox,QGridLayout,QPlainTextEdit)
from PySide6.QtMultimedia import (QMediaPlayer,QAudioOutput,QMediaCaptureSession,QAudioInput,
                                  QMediaRecorder,QMediaFormat)
from preview import VideoView
from core import (Clip,PRESETS,MIN_CLIP,FILTER_PRESETS,MASK_TYPES,AUDIO_CHANNEL_MODES,TEXT_STYLE_PRESETS,EFFECT_PRESETS,KEYFRAME_CURVES,KEYFRAME_CURVE_LABELS,EXPORT_FORMATS,EXPORT_CODEC_LABELS,EXPORT_ENCODER_LABELS,EXPORT_PRESETS,PROXY_PROFILES,AUTO_REFRAME_FORMATS,AUTO_REFRAME_FORMAT_LABELS,auto_reframe_aspect,curve_progress,
                  normalize_export_settings,import_clip,import_image_sequence,parse_subtitle_file,subtitle_cues_from_clips,write_subtitle_file,save_project,load_project,split_clip,render,
                  archive_project,extract_project_archive,find_relink_candidates,relink_project_media,missing_project_media,create_proxy_files,
                  preview_acceleration_info,cache_size,prune_cache,
                  ExportCancelled,validate_timeline,length,normalize_markers,edited_clip,retime_keyframes,retime_volume_keyframes,retime_speed_keyframes,
                  normalize_track_states,normalize_track_names,normalize_master_mixer,slip_clip,roll_edit,slide_edit,retime_tracking_keyframes,retime_auto_reframe_keyframes,retime_mask_path_keyframes,
                  cut_clip_ranges,split_clip_at_times,build_auto_cut_points,mask_path_keyframes_from_tracking,
                  trim_timeline_range,close_track_gaps,copy_keyframe_bundle,paste_keyframe_bundle,
                  write_chapter_file,capture_frame)
from timeline import Timeline,MediaList
from asset_library import (AssetLibraryPanel, LibraryItem, get_library_item,
                           library_items, library_items_for, library_sound_path)
from style import STYLE
from ux import FineDoubleSpinBox as QDoubleSpinBox, line_icon
from workbench import SmoothWorkbench, HISTORY_NAMES
from update_system import (configured_manifest_url,download_verified,fetch_manifest,
                           install_downloaded,preferred_kinds,select_artifact,update_cache_directory,
                           update_checks_disabled)
from transcription import transcribe_media, build_text_edit_plan
from ai_tools import (AIToolError, remove_background_media, track_motion, auto_reframe_video,
                       analyze_beats, detect_scene_changes, detect_audio_onset)

try:
    APP_VERSION = Path(__file__).with_name('VERSION').read_text(encoding='utf-8').strip() or '3.27.0'
except OSError:
    APP_VERSION = '3.27.0'


def label(text,name=None):
    widget=QLabel(text)
    if name: widget.setObjectName(name)
    return widget


def button(text,callback,primary=False):
    widget=QPushButton(text); widget.clicked.connect(lambda checked=False:callback())
    if primary: widget.setObjectName('primary')
    return widget


def icon_action(symbol, tooltip, callback, theme_name=None):
    """Create a compact header action without adding another text-heavy box."""
    widget=QToolButton()
    icon=line_icon(theme_name) if theme_name else QIcon()
    if not icon.isNull():
        widget.setIcon(icon)
        widget.setToolButtonStyle(Qt.ToolButtonIconOnly)
    else:
        widget.setText(symbol)
        widget.setToolButtonStyle(Qt.ToolButtonTextOnly)
    widget.setObjectName('headerToolButton')
    widget.setToolTip(tooltip)
    widget.setStatusTip(tooltip)
    widget.setAccessibleName(tooltip)
    widget.setIconSize(QSize(17,17))
    widget.setFixedSize(34,30)
    widget.setAutoRaise(True)
    widget.clicked.connect(lambda checked=False:callback())
    return widget


def timeline_tool_button(symbol, tooltip, callback=None, theme_name=None, toggle=False, object_name=None):
    """Create a compact, icon-first timeline action with a descriptive tooltip."""
    widget=QToolButton()
    widget.setText(symbol)
    icon=line_icon(theme_name) if theme_name else QIcon()
    if not icon.isNull():
        widget.setIcon(icon)
        widget.setToolButtonStyle(Qt.ToolButtonIconOnly)
    else:
        widget.setToolButtonStyle(Qt.ToolButtonTextOnly)
    widget.setObjectName(object_name or ('timelineToolToggle' if toggle else 'timelineToolButton'))
    widget.setToolTip(tooltip)
    widget.setStatusTip(tooltip)
    widget.setAccessibleName(tooltip)
    widget.setIconSize(QSize(18,18))
    widget.setFixedSize(32,30)
    widget.setAutoRaise(True)
    if toggle:
        widget.setCheckable(True)
    if callback is not None:
        widget.clicked.connect(lambda checked=False:callback())
    return widget


def timeline_menu_button(symbol, tooltip, menu, theme_name=None):
    """Create an icon-only timeline button that opens a compact action menu."""
    widget=timeline_tool_button(symbol, tooltip, theme_name=theme_name, object_name='timelineMenuButton')
    widget.setPopupMode(QToolButton.InstantPopup)
    widget.setMenu(menu)
    return widget


def timeline_icon_label(symbol, tooltip):
    """Return a tiny symbol label for non-action timeline controls."""
    widget=label(symbol,'timelineIconLabel')
    widget.setToolTip(tooltip)
    widget.setStatusTip(tooltip)
    return widget


def timeline_tool_group(title, widgets):
    """Put related timeline actions into one flat, tooltip-labelled group."""
    group=QFrame(); group.setObjectName('timelineToolGroup')
    group.setToolTip(title); group.setAccessibleName(title)
    layout=QHBoxLayout(group); layout.setContentsMargins(1,1,1,1); layout.setSpacing(1)
    for widget in widgets:
        layout.addWidget(widget)
    return group


def timeline_separator():
    separator=QFrame(); separator.setObjectName('timelineSeparator'); separator.setFrameShape(QFrame.VLine)
    separator.setFixedHeight(30)
    return separator


def timeline_track_group(video_spin, audio_spin):
    """Create the compact video/audio track count control."""
    group=QFrame(); group.setObjectName('timelineControlGroup')
    layout=QVBoxLayout(group); layout.setContentsMargins(7,3,7,3); layout.setSpacing(1)
    caption=label('SPUREN','timelineGroupLabel'); caption.setAlignment(Qt.AlignCenter); layout.addWidget(caption)
    controls=QHBoxLayout(); controls.setContentsMargins(0,0,0,0); controls.setSpacing(4)
    video_icon=timeline_icon_label('▣','Video-Spuren'); controls.addWidget(video_icon)
    video_spin.setFixedWidth(40); controls.addWidget(video_spin)
    audio_icon=timeline_icon_label('♫','Audio-Spuren'); controls.addWidget(audio_icon)
    audio_spin.setFixedWidth(40); controls.addWidget(audio_spin)
    layout.addLayout(controls)
    return group


def panel():
    widget=QFrame(); widget.setObjectName('panel')
    layout=QVBoxLayout(widget); layout.setContentsMargins(12,11,12,11); layout.setSpacing(8)
    return widget,layout


def state_directory():
    path=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'framecut'
    path.mkdir(parents=True,exist_ok=True)
    return path


def app_icon_path():
    return Path(__file__).with_name('framecut.svg')


# Attribute paste deliberately excludes source identity, timing, grouping and
# animation. Keyframes have a dedicated clipboard so a quick effect paste
# cannot unexpectedly overwrite motion data.
VIDEO_ATTRIBUTE_FIELDS = (
    'volume', 'fade_in', 'fade_out', 'video_scale', 'video_x', 'video_y',
    'crop_left', 'crop_top', 'crop_right', 'crop_bottom', 'rotation',
    'flip_horizontal', 'flip_vertical', 'brightness', 'contrast', 'saturation',
    'filter_preset', 'lut_path', 'color_exposure', 'color_temperature',
    'color_tint', 'color_vibrance', 'color_lift_r', 'color_lift_g',
    'color_lift_b', 'color_gamma_r', 'color_gamma_g', 'color_gamma_b',
    'color_gain_r', 'color_gain_g', 'color_gain_b', 'opacity', 'blur',
    'sharpen', 'stabilization', 'effect_preset',
    'chroma_key_enabled', 'chroma_key_color', 'chroma_key_similarity',
    'chroma_key_blend', 'mask_type', 'mask_x', 'mask_y', 'mask_width',
    'mask_height', 'mask_feather', 'mask_points', 'audio_noise_reduction',
    'audio_eq_low', 'audio_eq_mid', 'audio_eq_high', 'audio_compressor_enabled',
    'audio_compressor_threshold', 'audio_compressor_ratio', 'audio_ducking',
    'audio_voice_isolation', 'audio_channel_mode', 'audio_pan',
    'audio_normalize', 'audio_normalize_target', 'freeze_frame',
    'freeze_duration', 'reverse', 'speed', 'transition_type',
    'transition_duration',
)
AUDIO_ATTRIBUTE_FIELDS = (
    'volume', 'fade_in', 'fade_out', 'audio_noise_reduction', 'audio_eq_low',
    'audio_eq_mid', 'audio_eq_high', 'audio_compressor_enabled',
    'audio_compressor_threshold', 'audio_compressor_ratio', 'audio_ducking',
    'audio_voice_isolation', 'audio_channel_mode', 'audio_pan',
    'audio_normalize', 'audio_normalize_target', 'speed', 'reverse',
    'transition_type', 'transition_duration',
)
TEXT_ATTRIBUTE_FIELDS = (
    'volume', 'fade_in', 'fade_out', 'font_size', 'color', 'font_family',
    'font_bold', 'font_italic', 'outline_width', 'outline_color',
    'shadow_size', 'shadow_color', 'background_enabled', 'background_color',
    'background_opacity', 'background_padding', 'text_animation',
    'text_animation_duration', 'x', 'y',
)


class KeyframeGraphWidget(QWidget):
    """Compact draggable curve editor for the clip transform keyframes."""
    point_moved = Signal(int, float, float)
    point_added = Signal(float, float)
    point_selected = Signal(int)
    drag_started = Signal()
    drag_finished = Signal()
    RANGES = {
        'scale': (.1, 4.0, 'Zoom'),
        'x': (0.0, 1.0, 'Bild X'),
        'y': (0.0, 1.0, 'Bild Y'),
        'rotation': (-360.0, 360.0, 'Rotation'),
        'opacity': (0.0, 1.0, 'Deckkraft'),
        'blur': (0.0, 20.0, 'Unschärfe'),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(142)
        self.setMaximumHeight(190)
        self.setMouseTracking(True)
        self.frames = []
        self.duration = 1.0
        self.field = 'scale'
        self.default = 1.0
        self.selected = -1
        self.dragging = False

    def set_data(self, frames, duration, field, default):
        self.frames = [dict(frame) for frame in frames]
        self.duration = max(.01, float(duration))
        self.field = field if field in self.RANGES else 'scale'
        self.default = float(default)
        self.selected = min(self.selected, len(self.frames)-1)
        self.dragging = False
        self.update()

    def _plot(self):
        return self.rect().adjusted(30, 12, -12, -24)

    def _range(self):
        low, high, _ = self.RANGES[self.field]
        return low, high

    def _value(self, frame):
        return float(frame.get(self.field, self.default))

    def _map(self, time, value):
        plot = self._plot(); low, high = self._range()
        x = plot.left() + max(0.0, min(self.duration, float(time))) / self.duration * plot.width()
        ratio = (float(value)-low) / max(1e-9, high-low)
        y = plot.bottom() - max(0.0, min(1.0, ratio)) * plot.height()
        return x, y

    def _unmap(self, point):
        plot = self._plot(); low, high = self._range()
        time = (point.x()-plot.left()) / max(1, plot.width()) * self.duration
        ratio = (plot.bottom()-point.y()) / max(1, plot.height())
        return max(0.0, min(self.duration, time)), max(low, min(high, low+ratio*(high-low)))

    def _value_at(self, time):
        if not self.frames:
            return self.default
        frames = sorted(self.frames, key=lambda value: float(value.get('time', 0.0)))
        if time <= float(frames[0].get('time', 0.0)):
            return self.default if float(frames[0].get('time', 0.0)) > 1e-7 else self._value(frames[0])
        for left, right in zip(frames, frames[1:]):
            left_time, right_time = float(left.get('time', 0.0)), float(right.get('time', 0.0))
            if time <= right_time:
                ratio = (time-left_time) / max(1e-9, right_time-left_time)
                ratio = curve_progress(ratio, left.get('curve', 'linear'))
                return self._value(left) + (self._value(right)-self._value(left))*ratio
        return self._value(frames[-1])

    def _hit(self, point):
        nearest = -1; distance = 9e9
        for index, frame in enumerate(self.frames):
            x, y = self._map(frame.get('time', 0.0), self._value(frame))
            current = (x-point.x())**2 + (y-point.y())**2
            if current < distance and current <= 12**2:
                nearest, distance = index, current
        return nearest

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#101722'))
        plot = self._plot(); low, high = self._range(); title = self.RANGES[self.field][2]
        painter.setPen(QPen(QColor('#667085'), 1))
        painter.drawText(6, 15, title)
        painter.setPen(QPen(QColor('#253246'), 1))
        for step in range(5):
            y = plot.top() + step * plot.height() / 4
            painter.drawLine(plot.left(), int(y), plot.right(), int(y))
        for step in range(5):
            x = plot.left() + step * plot.width() / 4
            painter.drawLine(int(x), plot.top(), int(x), plot.bottom())
        painter.setPen(QPen(QColor('#7d8da6'), 1))
        painter.drawText(plot.left(), self.height()-6, '0 s')
        painter.drawText(plot.right()-34, self.height()-6, f'{self.duration:.1f} s')
        if not self.frames:
            painter.setPen(QPen(QColor('#8b98aa'), 1))
            painter.drawText(plot.left()+8, plot.center().y(), 'Keyframes im Inspector setzen oder doppelt klicken')
            return
        curve_points = []
        for index in range(81):
            time = self.duration * index / 80
            curve_points.append(self._map(time, self._value_at(time)))
        painter.setPen(QPen(QColor('#63ead4'), 2))
        for left, right in zip(curve_points, curve_points[1:]):
            painter.drawLine(int(left[0]), int(left[1]), int(right[0]), int(right[1]))
        for index, frame in enumerate(self.frames):
            x, y = self._map(frame.get('time', 0.0), self._value(frame))
            color = QColor('#f8c86f' if index == self.selected else '#63ead4')
            painter.setPen(QPen(color, 2)); painter.setBrush(color)
            painter.drawEllipse(int(x)-4, int(y)-4, 8, 8)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        point = event.position().toPoint()
        self.selected = self._hit(point)
        if self.selected >= 0:
            self.dragging = True
            self.drag_started.emit()
            self.point_selected.emit(self.selected)
            self.update()

    def mouseMoveEvent(self, event):
        if not self.dragging or self.selected < 0:
            return
        time, value = self._unmap(event.position().toPoint())
        if self.selected > 0:
            time = max(time, float(self.frames[self.selected-1].get('time', 0.0))+.01)
        if self.selected + 1 < len(self.frames):
            time = min(time, float(self.frames[self.selected+1].get('time', self.duration))-.01)
        frame = self.frames[self.selected]
        frame['time'] = round(max(0.0, min(self.duration, time)), 6)
        frame[self.field] = round(value, 6)
        self.point_moved.emit(self.selected, frame['time'], frame[self.field])
        self.update()

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.drag_finished.emit()
        self.dragging = False

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        time, value = self._unmap(event.position().toPoint())
        self.point_added.emit(round(time, 6), round(value, 6))


class ExportDialog(QDialog):
    """Small, explicit export profile dialog backed by core validation."""
    def __init__(self,parent=None,work_area=None):
        super().__init__(parent)
        self.setWindowTitle('Export-Einstellungen')
        self.setMinimumWidth(430)
        self.work_area=work_area
        layout=QVBoxLayout(self); layout.setContentsMargins(18,16,18,16); layout.setSpacing(12)
        layout.addWidget(label('EXPORT · FERTIGEN FILM SPEICHERN','heading'))
        self.summary=label('','projectTitle'); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        form=QFormLayout()
        self.preset_combo=QComboBox()
        for value,info in EXPORT_PRESETS.items():
            self.preset_combo.addItem(info['label'],value)
        form.addRow('Export-Preset',self.preset_combo)
        self.format_combo=QComboBox()
        for value,info in EXPORT_FORMATS.items(): self.format_combo.addItem(info['label'],value)
        self.codec_combo=QComboBox()
        self.fps=QDoubleSpinBox(); self.fps.setRange(1,120); self.fps.setDecimals(2); self.fps.setSingleStep(1); self.fps.setValue(30); self.fps.setSuffix(' FPS')
        self.bitrate=QSpinBox(); self.bitrate.setRange(256,200000); self.bitrate.setSingleStep(500); self.bitrate.setValue(12000); self.bitrate.setSuffix(' kbit/s')
        self.encoder_combo=QComboBox()
        for value,title in EXPORT_ENCODER_LABELS.items(): self.encoder_combo.addItem(title,value)
        self.hdr=QCheckBox('HDR10 · BT.2020 / PQ')
        self.hdr.setToolTip('10-Bit-Video mit HDR-Farbmetadaten; benötigt H.265/HEVC oder AV1.')
        form.addRow('Format',self.format_combo); form.addRow('Bildrate',self.fps)
        layout.addLayout(form)
        self.advanced_toggle=QToolButton(); self.advanced_toggle.setText('Erweitert · Codec und Qualität')
        self.advanced_toggle.setCheckable(True); self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); layout.addWidget(self.advanced_toggle)
        self.advanced_panel=QWidget(); advanced=QFormLayout(self.advanced_panel)
        advanced.addRow('Videocodec',self.codec_combo); advanced.addRow('Videobitrate',self.bitrate)
        advanced.addRow('Encoding',self.encoder_combo); advanced.addRow('Farbraum',self.hdr)
        layout.addWidget(self.advanced_panel); self.advanced_panel.hide()
        self.advanced_toggle.toggled.connect(lambda visible:(self.advanced_panel.setVisible(visible),self.advanced_toggle.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)))
        self.work_area_box=QCheckBox('Nur Arbeitsbereich exportieren')
        self.work_area_box.setEnabled(bool(work_area))
        if work_area:
            self.work_area_box.setToolTip(f'Exportiert nur {work_area[0]:.2f}–{work_area[1]:.2f} s.')
        else:
            self.work_area_box.setToolTip('Setze zuerst Arbeitsbereich-In und Arbeitsbereich-Out in der Vorschau.')
        layout.addWidget(self.work_area_box)
        self.queue_only_box=QCheckBox('Nur in Render-Queue einreihen')
        self.queue_only_box.setToolTip('Der Export startet erst, wenn die Render-Queue gestartet wird.')
        layout.addWidget(self.queue_only_box)
        self.hint=label('Die Auswahl wird direkt im FFmpeg-Export verwendet.','muted'); self.hint.setWordWrap(True); layout.addWidget(self.hint)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.format_combo.currentIndexChanged.connect(self.format_changed)
        self.codec_combo.currentIndexChanged.connect(self.codec_changed)
        self.preset_combo.currentIndexChanged.connect(self.preset_changed)
        self.preset_combo.setCurrentIndex(self.preset_combo.findData('master'))
        self.preset_changed()
        if parent is not None and hasattr(parent,'clips'):
            source=next((c for c in parent.clips if c.kind=='video' and c.source_type not in ('image','adjustment')),None)
            self.fps.setValue(source.source_fps if source else 30)
            saved=getattr(parent,'last_export_settings',{})
            try: saved=normalize_export_settings(saved) if saved else {}
            except (ValueError,TypeError): saved={}
            if saved:
                self.format_combo.setCurrentIndex(self.format_combo.findData(saved['format']))
                self.codec_combo.setCurrentIndex(self.codec_combo.findData(saved['video_codec']))
                self.fps.setValue(saved['fps']); self.bitrate.setValue(saved['bitrate_kbps'])
                self.encoder_combo.setCurrentIndex(self.encoder_combo.findData(saved['encoder'])); self.hdr.setChecked(saved['hdr'])
        self.fps.valueChanged.connect(self.update_summary); self.format_combo.currentIndexChanged.connect(self.update_summary)
        self.preset_combo.currentIndexChanged.connect(self.update_summary); self.work_area_box.toggled.connect(self.update_summary)
        self.update_summary()

    def update_summary(self,*_):
        parent=self.parent(); preset=EXPORT_PRESETS.get(self.preset_combo.currentData(),{})
        size=preset.get('size') or (PRESETS[parent.preset.currentText()] if parent is not None and hasattr(parent,'preset') else (1920,1080))
        area='Arbeitsbereich' if self.work_area_box.isChecked() else 'Gesamte Timeline'
        self.summary.setText(f'{size[0]} × {size[1]} · {self.fps.value():g} FPS · {self.format_combo.currentText()}\n{area} · Originalmedien')

    def preset_changed(self,*_):
        values=EXPORT_PRESETS.get(self.preset_combo.currentData())
        if not values:
            return
        self.format_combo.blockSignals(True); self.codec_combo.blockSignals(True)
        self.format_combo.setCurrentIndex(self.format_combo.findData(values['format']))
        self.format_combo.blockSignals(False)
        self.format_changed()
        self.codec_combo.blockSignals(True)
        self.codec_combo.setCurrentIndex(self.codec_combo.findData(values['video_codec']))
        self.codec_combo.blockSignals(False)
        self.fps.setValue(values['fps']); self.bitrate.setValue(values['bitrate_kbps'])
        encoder_index=self.encoder_combo.findData(values['encoder'])
        if encoder_index >= 0:
            self.encoder_combo.setCurrentIndex(encoder_index)
        self.hdr.setChecked(bool(values['hdr']))
        self.codec_changed()

    def format_changed(self,*_):
        old=self.codec_combo.currentData(); self.codec_combo.blockSignals(True); self.codec_combo.clear()
        info=EXPORT_FORMATS[self.format_combo.currentData()]
        for value in info['codecs']: self.codec_combo.addItem(EXPORT_CODEC_LABELS[value],value)
        index=self.codec_combo.findData(old)
        self.codec_combo.setCurrentIndex(index if index >= 0 else 0); self.codec_combo.blockSignals(False); self.codec_changed()

    def codec_changed(self,*_):
        enabled=self.codec_combo.currentData() in ('hevc','av1')
        self.hdr.setEnabled(enabled)
        if not enabled:self.hdr.setChecked(False)

    def settings(self):
        return {'format':self.format_combo.currentData(),'video_codec':self.codec_combo.currentData(),
                'fps':self.fps.value(),'bitrate_kbps':self.bitrate.value(),
                'encoder':self.encoder_combo.currentData(),'hdr':self.hdr.isChecked(),
                'export_preset':self.preset_combo.currentData(),
                'size':EXPORT_PRESETS.get(self.preset_combo.currentData(),{}).get('size')}

    def accept(self):
        try:
            self.export_settings=normalize_export_settings(self.settings())
        except ValueError as exc:
            QMessageBox.warning(self,'Export-Einstellungen',str(exc)); return
        self.export_work_area=self.work_area_box.isChecked()
        super().accept()


class AutomaticSubtitleDialog(QDialog):
    """Choose a local source and settings for speech-to-text subtitles."""

    def __init__(self, sources, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Automatische Untertitel')
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(11)
        layout.addWidget(label('AUTOMATISCHE UNTERTITEL · LOKALE SPRACHERKENNUNG', 'heading'))
        intro = label(
            'Framecut wandelt die Sprache aus einem Video oder einer Audiodatei in editierbare Textclips um. '
            'Die Quelldatei bleibt auf deinem Rechner; beim ersten Einsatz wird nur das gewählte Sprachmodell geladen.',
            'muted')
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        source_row = QHBoxLayout()
        self.source_combo = QComboBox()
        for title, path in sources:
            self.source_combo.addItem(title, str(path))
        self.source_combo.setToolTip('Bereits importiertes Video oder Audio verwenden')
        source_row.addWidget(self.source_combo, 1)
        browse = QPushButton('Datei auswählen …')
        browse.clicked.connect(self.choose_file)
        source_row.addWidget(browse)
        source_widget = QWidget(); source_widget.setLayout(source_row)
        form.addRow('Quelle', source_widget)

        self.language_combo = QComboBox()
        for value, title in (
            ('auto', 'Automatisch erkennen'),
            ('de', 'Deutsch'),
            ('en', 'English'),
            ('tr', 'Türkçe'),
            ('az', 'Azərbaycanca'),
            ('es', 'Español'),
            ('fr', 'Français'),
        ):
            self.language_combo.addItem(title, value)
        self.language_combo.setToolTip('Eine bekannte Sprache kann die Erkennung beschleunigen')
        form.addRow('Sprache', self.language_combo)

        self.model_combo = QComboBox()
        for value, title in (
            ('tiny', 'Schnell · tiny'),
            ('base', 'Ausgewogen · base'),
            ('small', 'Genauer · small'),
        ):
            self.model_combo.addItem(title, value)
        self.model_combo.setCurrentIndex(self.model_combo.findData('base'))
        self.model_combo.setToolTip('Größere Modelle sind genauer, brauchen aber länger und mehr Speicher')
        form.addRow('Modell', self.model_combo)
        layout.addLayout(form)

        hint = label('Die Verarbeitung läuft als Hintergrundvorgang und kann jederzeit abgebrochen werden. '
                     'Das Modell wird im Framecut-Benutzerordner zwischengespeichert.', 'muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Untertitel erstellen')
        buttons.button(QDialogButtonBox.Cancel).setText('Abbrechen')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Quelle für automatische Untertitel auswählen', '',
            'Video und Audio (*.mp4 *.mkv *.mov *.webm *.avi *.mp3 *.wav *.m4a *.flac *.ogg);;Alle Dateien (*)')
        if not path:
            return
        path = str(Path(path).expanduser().resolve())
        index = self.source_combo.findData(path)
        if index < 0:
            self.source_combo.insertItem(0, f'{Path(path).name} · Datei', path)
            index = 0
        self.source_combo.setCurrentIndex(index)

    def settings(self):
        return {
            'path': self.source_combo.currentData(),
            'language': self.language_combo.currentData(),
            'model_size': self.model_combo.currentData(),
        }

    def accept(self):
        path = self.source_combo.currentData()
        if not path:
            QMessageBox.warning(self, 'Automatische Untertitel', 'Wähle zuerst ein Video oder eine Audiodatei aus.')
            return
        if not Path(path).is_file():
            QMessageBox.warning(self, 'Automatische Untertitel', f'Die Quelldatei wurde nicht gefunden:\n{path}')
            return
        super().accept()


class CommandPaletteDialog(QDialog):
    """Searchable launcher for the editor's most important actions."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setWindowTitle('Framecut · Befehle')
        self.setModal(True)
        self.setMinimumSize(560, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(label('BEFEHLE UND SHORTCUTS', 'heading'))
        hint = label('Suche eine Aktion und bestätige mit Enter. Öffnen jederzeit mit Strg+K.', 'muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.query = QLineEdit()
        self.query.setPlaceholderText('Befehl suchen …')
        self.query.setClearButtonEnabled(True)
        layout.addWidget(self.query)
        self.commands = editor.command_definitions()
        self.results = QListWidget()
        self.results.setViewMode(QListWidget.ListMode)
        self.results.itemDoubleClicked.connect(self.run_selected)
        layout.addWidget(self.results, 1)
        footer = QHBoxLayout()
        footer.addWidget(label('↑ ↓ auswählen · Enter ausführen · Esc schließen', 'muted'))
        footer.addStretch()
        close = QPushButton('Schließen')
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.query.textChanged.connect(self.refresh_results)
        self.query.returnPressed.connect(self.run_selected)
        self.refresh_results()
        self.query.setFocus()

    def refresh_results(self, *_):
        query = self.query.text().strip().casefold()
        self.results.clear()
        for title, shortcut, callback in self.commands:
            searchable = f'{title} {shortcut}'.casefold()
            if query and query not in searchable:
                continue
            item = QListWidgetItem(f'{title}    {shortcut}')
            item.setData(Qt.UserRole, callback)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)
        else:
            empty = QListWidgetItem('Keine passenden Befehle')
            empty.setFlags(Qt.NoItemFlags)
            self.results.addItem(empty)

    def run_selected(self, *_):
        item = self.results.currentItem()
        callback = item.data(Qt.UserRole) if item is not None else None
        if not callable(callback):
            return
        self.accept()
        QTimer.singleShot(0, callback)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


class CinemaPreviewDialog(QDialog):
    """Fullscreen preview that temporarily uses its own video sink."""

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setObjectName('cinemaDialog')
        self.setWindowTitle(f'Framecut {APP_VERSION} · Cinema-Vorschau')
        self.setWindowFlag(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.addWidget(label('FRAMECUT · CINEMA PREVIEW', 'heading'))
        header.addStretch()
        close = QPushButton('Schließen  Esc')
        close.setObjectName('iconButton')
        close.clicked.connect(self.close)
        header.addWidget(close)
        layout.addLayout(header)
        self.canvas = VideoView()
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas.frame = editor.video.frame
        layout.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        self.play_button = QPushButton('▶ Timeline')
        self.play_button.clicked.connect(editor.toggle_play)
        controls.addWidget(self.play_button)
        controls.addWidget(label('F11 oder Esc zum Schließen', 'muted'))
        controls.addStretch()
        self.time = label(editor.time_label.text(), 'muted')
        controls.addWidget(self.time)
        layout.addLayout(controls)
        editor.player.setVideoSink(self.canvas.sink)
        editor.player.playbackStateChanged.connect(self.sync_play_state)
        editor.player.positionChanged.connect(self.sync_time)
        self.sync_play_state(editor.player.playbackState())

    def sync_play_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self.play_button.setText('Ⅱ Pause')
        else:
            self.play_button.setText('▶ Timeline')

    def sync_time(self, *_):
        self.time.setText(self.editor.time_label.text())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F11):
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.editor.player.setVideoSink(self.editor.video.sink)
        self.editor.video.frame = self.canvas.frame
        self.editor.video.update()
        self.editor.cinema_dialog = None
        if hasattr(self.editor, 'cinema_button'):
            self.editor.cinema_button.setText('⛶ Cinema')
        super().closeEvent(event)


class LevelMeter(QWidget):
    """Compact, dependency-free mixer meter driven by the current playhead."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.setMinimumWidth(92)
        self.setMinimumHeight(16)

    def set_level(self, value):
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self.level) > .005:
            self.level = value
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#0b1017'))
        width = max(0, int((self.width()-4) * self.level))
        if width:
            green = max(0, min(width, int(self.width()*.70)))
            yellow = max(0, min(width-green, int(self.width()*.20)))
            painter.fillRect(2, 2, green, max(1, self.height()-4), QColor('#63d9a5'))
            painter.fillRect(2+green, 2, yellow, max(1, self.height()-4), QColor('#f5c86b'))
            painter.fillRect(2+green+yellow, 2, max(0, width-green-yellow), max(1, self.height()-4), QColor('#ff7777'))
        painter.setPen(QColor('#334255'))
        painter.drawRect(1, 1, self.width()-3, self.height()-3)


class MixerDialog(QDialog):
    """Track mixer with live faders, pan, solo/mute and master controls."""
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setWindowTitle('Audio-Mixer')
        self.setMinimumSize(760, 420)
        self._loading = True
        self._checkpointed = False
        self.track_controls = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(label('AUDIO-MIXER · SPUREN, MASTER UND PEGEL','heading'))
        hint = label('Fader und Panorama wirken in Vorschau und Export. Solo schaltet alle anderen Tonspuren für den Abhörmix aus.','muted')
        hint.setWordWrap(True); layout.addWidget(hint)

        grid = QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(6)
        for column, title in enumerate(('Spur','Lautstärke','Panorama','M / S','Pegel')):
            grid.addWidget(label(title,'muted'), 0, column)
        for row, track in enumerate(editor.tracks, 1):
            state = editor.track_states.get(track, {})
            name = editor.track_names.get(track, editor.default_track_name(track))
            grid.addWidget(label(name), row, 0)
            volume_slider = QSlider(Qt.Horizontal); volume_slider.setRange(0, 200); volume_slider.setValue(round(float(state.get('volume',1))*100)); volume_slider.setToolTip('Spurlautstärke 0–200 %')
            volume_spin = QDoubleSpinBox(); volume_spin.setRange(0, 200); volume_spin.setDecimals(0); volume_spin.setSuffix(' %'); volume_spin.setValue(float(state.get('volume',1))*100)
            volume_box = QHBoxLayout(); volume_box.setContentsMargins(0,0,0,0); volume_box.addWidget(volume_slider, 1); volume_box.addWidget(volume_spin)
            volume_widget = QWidget(); volume_widget.setLayout(volume_box); grid.addWidget(volume_widget, row, 1)
            pan_slider = QSlider(Qt.Horizontal); pan_slider.setRange(-100, 100); pan_slider.setValue(round(float(state.get('pan',0))*100)); pan_slider.setToolTip('Panorama links/rechts')
            pan_spin = QDoubleSpinBox(); pan_spin.setRange(-100, 100); pan_spin.setDecimals(0); pan_spin.setSuffix(' %'); pan_spin.setValue(float(state.get('pan',0))*100)
            pan_box = QHBoxLayout(); pan_box.setContentsMargins(0,0,0,0); pan_box.addWidget(pan_slider, 1); pan_box.addWidget(pan_spin)
            pan_widget = QWidget(); pan_widget.setLayout(pan_box); grid.addWidget(pan_widget, row, 2)
            mute = QCheckBox('M'); mute.setChecked(bool(state.get('muted',False))); mute.setToolTip('Spur stummschalten')
            solo = QCheckBox('S'); solo.setChecked(bool(state.get('solo',False))); solo.setToolTip('Spur solo abhören')
            buttons = QHBoxLayout(); buttons.setContentsMargins(0,0,0,0); buttons.addWidget(mute); buttons.addWidget(solo)
            button_widget = QWidget(); button_widget.setLayout(buttons); grid.addWidget(button_widget, row, 3)
            meter = LevelMeter(); grid.addWidget(meter, row, 4)
            self.track_controls[track] = {'volume_slider':volume_slider,'volume_spin':volume_spin,
                                          'pan_slider':pan_slider,'pan_spin':pan_spin,'mute':mute,
                                          'solo':solo,'meter':meter}
            volume_slider.valueChanged.connect(lambda value, s=volume_spin: s.setValue(value))
            volume_spin.valueChanged.connect(lambda value, s=volume_slider: s.setValue(round(value)))
            pan_slider.valueChanged.connect(lambda value, s=pan_spin: s.setValue(value))
            pan_spin.valueChanged.connect(lambda value, s=pan_slider: s.setValue(round(value)))
            for control in (volume_slider,pan_slider):
                control.sliderPressed.connect(lambda:setattr(self,'_checkpointed',False))
                control.sliderReleased.connect(lambda:setattr(self,'_checkpointed',False))
            for control in (volume_spin,pan_spin):
                control.editingFinished.connect(lambda:setattr(self,'_checkpointed',False))
            volume_spin.valueChanged.connect(lambda value, t=track: self.set_track(t, volume=value/100.0))
            pan_spin.valueChanged.connect(lambda value, t=track: self.set_track(t, pan=value/100.0))
            mute.toggled.connect(lambda value, t=track: self.set_track(t, muted=value))
            solo.toggled.connect(lambda value, t=track: self.set_track(t, solo=value))
        scroll_content = QWidget(); scroll_content.setLayout(grid)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(scroll_content); layout.addWidget(scroll, 1)

        master_box = QFrame(); master_box.setObjectName('panel'); master_layout = QGridLayout(master_box)
        master_layout.addWidget(label('MASTER','heading'), 0, 0)
        self.master_volume = QDoubleSpinBox(); self.master_volume.setRange(0,200); self.master_volume.setDecimals(0); self.master_volume.setSuffix(' %')
        self.master_volume.setValue(float(editor.master_mixer.get('volume',1))*100)
        self.master_pan = QDoubleSpinBox(); self.master_pan.setRange(-100,100); self.master_pan.setDecimals(0); self.master_pan.setSuffix(' %')
        self.master_pan.setValue(float(editor.master_mixer.get('pan',0))*100)
        self.loudness_box = QCheckBox('Loudness-Normalisierung'); self.loudness_box.setChecked(bool(editor.master_mixer.get('loudness_normalization',False)))
        self.loudness_target = QDoubleSpinBox(); self.loudness_target.setRange(-30,-5); self.loudness_target.setDecimals(1); self.loudness_target.setSuffix(' LUFS'); self.loudness_target.setValue(float(editor.master_mixer.get('loudness_target',-16)))
        master_layout.addWidget(label('Fader','muted'), 1, 0); master_layout.addWidget(self.master_volume, 1, 1)
        master_layout.addWidget(label('Pan','muted'), 1, 2); master_layout.addWidget(self.master_pan, 1, 3)
        master_layout.addWidget(self.loudness_box, 1, 4); master_layout.addWidget(self.loudness_target, 1, 5)
        self.master_meter = LevelMeter(); master_layout.addWidget(self.master_meter, 1, 6)
        layout.addWidget(master_box)
        actions = QHBoxLayout(); voice = QPushButton('Voice-over aufnehmen…'); voice.clicked.connect(editor.start_voiceover_recording); actions.addWidget(voice)
        actions.addWidget(label('Aufnahme wird als WAV auf eine freie Audiospur gelegt.','muted')); actions.addStretch()
        close = QPushButton('Schließen'); close.clicked.connect(self.accept); actions.addWidget(close); layout.addLayout(actions)
        self.master_volume.valueChanged.connect(lambda value:self.set_master(volume=value/100.0))
        self.master_pan.valueChanged.connect(lambda value:self.set_master(pan=value/100.0))
        self.loudness_box.toggled.connect(lambda value:self.set_master(loudness_normalization=value))
        self.loudness_target.valueChanged.connect(lambda value:self.set_master(loudness_target=value))
        self.meter_timer = QTimer(self); self.meter_timer.setInterval(90); self.meter_timer.timeout.connect(self.update_meters); self.meter_timer.start()
        self._loading = False
        self.update_meters()

    def _checkpoint(self):
        if not self._checkpointed:
            self.editor.checkpoint(); self._checkpointed = True

    def set_track(self, track, **values):
        if self._loading or self.editor.worker:
            return
        self._checkpoint()
        state = self.editor.track_states.setdefault(track, {'muted':False,'locked':False,'solo':False,'volume':1.0,'pan':0.0})
        state.update(values)
        self.editor.track_states = normalize_track_states(self.editor.track_states, self.editor.tracks)
        self.editor.changed()

    def set_master(self, **values):
        if self._loading or self.editor.worker:
            return
        self._checkpoint()
        updated = dict(self.editor.master_mixer); updated.update(values)
        self.editor.master_mixer = normalize_master_mixer(updated)
        self.editor.changed()

    def update_meters(self):
        playhead = float(self.editor.playhead)
        solo_tracks = {track for track, state in self.editor.track_states.items() if state.get('solo',False)}
        levels = []
        for track, controls in self.track_controls.items():
            state = self.editor.track_states.get(track, {})
            allowed = not state.get('muted',False) and (not solo_tracks or track in solo_tracks)
            active = [clip for clip in self.editor.clips if clip.track == track and clip.kind in ('audio','video')
                      and clip.position <= playhead < clip.finish and getattr(clip,'has_audio',False) and clip.volume > 0]
            level = 0.0
            if allowed and active:
                clip = active[-1]
                pulse = .45 + .35 * (0.5 + 0.5 * math.sin(playhead * 8.0 + abs(track)))
                level = min(1.0, pulse * min(1.0, clip.volume * float(state.get('volume',1.0))))
            controls['meter'].set_level(level); levels.append(level)
        master = max(levels, default=0.0) * min(1.0, float(self.editor.master_mixer.get('volume',1.0)))
        self.master_meter.set_level(master)

    def refresh_from_editor(self):
        """Keep an already open mixer aligned after undo, redo or project load."""
        self._loading = True
        for track, controls in self.track_controls.items():
            state = self.editor.track_states.get(track, {})
            for widget, value in ((controls['volume_slider'], round(float(state.get('volume',1))*100)),
                                  (controls['volume_spin'], float(state.get('volume',1))*100),
                                  (controls['pan_slider'], round(float(state.get('pan',0))*100)),
                                  (controls['pan_spin'], float(state.get('pan',0))*100),
                                  (controls['mute'], bool(state.get('muted',False))),
                                  (controls['solo'], bool(state.get('solo',False)))):
                widget.blockSignals(True)
                (widget.setChecked(value) if isinstance(widget,QCheckBox) else widget.setValue(value))
                widget.blockSignals(False)
        for widget, value in ((self.master_volume,float(self.editor.master_mixer.get('volume',1))*100),
                              (self.master_pan,float(self.editor.master_mixer.get('pan',0))*100),
                              (self.loudness_box,bool(self.editor.master_mixer.get('loudness_normalization',False))),
                              (self.loudness_target,float(self.editor.master_mixer.get('loudness_target',-16)))):
            widget.blockSignals(True)
            (widget.setChecked(value) if isinstance(widget,QCheckBox) else widget.setValue(value))
            widget.blockSignals(False)
        self._loading = False
        self.update_meters()

    def closeEvent(self, event):
        self.meter_timer.stop()
        if self.editor.mixer_dialog is self:
            self.editor.mixer_dialog = None
        super().closeEvent(event)


class Job(QThread):
    progress=Signal(int)
    result=Signal(object)

    def __init__(self,operation):
        super().__init__()
        self.operation=operation; self.cancel=threading.Event()

    def run(self):
        try:
            result=self.operation(self.progress.emit,self.cancel)
            self.result.emit({'ok':True,'value':result})
        except ExportCancelled:
            self.result.emit({'ok':False,'cancelled':True,'error':'Vorgang abgebrochen.'})
        except Exception as exc:
            self.result.emit({'ok':False,'cancelled':False,'error':str(exc)})


class UpdateCheckJob(QThread):
    result=Signal(object)

    def __init__(self,manifest_url,current_version):
        super().__init__()
        self.manifest_url=manifest_url; self.current_version=current_version

    def run(self):
        try:
            manifest=fetch_manifest(self.manifest_url)
            artifact=select_artifact(manifest,self.current_version,preferred_kinds())
            self.result.emit({'ok':True,'artifact':artifact})
        except Exception as exc:
            self.result.emit({'ok':False,'error':str(exc)})


class UpdateDownloadJob(QThread):
    result=Signal(object)

    def __init__(self,artifact,install=False,current_path=None):
        super().__init__()
        self.artifact=artifact; self.install=install; self.current_path=current_path

    def run(self):
        try:
            target=update_cache_directory()/self.artifact['filename']
            downloaded=download_verified(self.artifact['url'],self.artifact['sha256'],target)
            message='Update verifiziert heruntergeladen: '+str(downloaded)
            installed=False
            if self.install and self.artifact['kind']=='appimage' and self.current_path:
                message=install_downloaded(downloaded,'appimage',self.current_path)
                installed=True
            self.result.emit({'ok':True,'path':str(downloaded),'message':message,'installed':installed})
        except Exception as exc:
            self.result.emit({'ok':False,'error':str(exc)})


class Editor(SmoothWorkbench,QMainWindow):
    def __init__(self,state_dir=None,recovery=True):
        super().__init__()
        self.state_dir=Path(state_dir) if state_dir else state_directory()
        self.state_dir.mkdir(parents=True,exist_ok=True)
        self.custom_library_root=self.state_dir/'library'/'custom'
        self.custom_library_manifest=self.state_dir/'library'/'custom_library.json'
        self.custom_library_items=self._load_custom_library_items()
        self.init_smooth_state(); self.job_type=Job
        self.recovery_path=self.state_dir/'recovery.framecut'
        self.cache_root=self.state_dir/'cache'; self.cache_root.mkdir(parents=True,exist_ok=True)
        self.cache_limit_bytes=768*1024*1024
        prune_cache(self.cache_root,self.cache_limit_bytes)
        sessions=self.cache_root/'sessions'; sessions.mkdir(parents=True,exist_ok=True)
        self.cache=tempfile.TemporaryDirectory(prefix='framecut-preview-',dir=str(sessions))
        self.thumbnail_cache=self.cache_root/'thumbnails'; self.thumbnail_cache.mkdir(parents=True,exist_ok=True)
        self.thumbnails={}
        self.waveforms={}
        self.clips=[]; self.assets=[]; self.tracks=[2,1,-1,-2]
        self.track_states=normalize_track_states(None,self.tracks); self.track_names=normalize_track_names(None,self.tracks)
        self.master_mixer=normalize_master_mixer(None); self.mixer_dialog=None
        self.current=None; self.selection=[]; self.clipboard=[]; self.attribute_clipboard=None; self.keyframe_clipboard=None; self.markers=[]
        # These are UI preferences, not project media.  They keep the editor
        # calm for beginners while leaving the full professional surface one
        # click away.
        self.edit_mode='simple'
        self.workspace_preset='Schnitt'
        self.focus_mode=False
        self.favorite_assets=set()
        self.inspector_sections=[]
        self.project_path=None; self.suggested_name='Mein-Film.framecut'
        self.history=[]; self.future=[]; self.dirty=False; self.revision=0
        self.preview_revision=-1; self.preview_signature=None; self.preview_path=None
        self.preview_worker=None; self.preview_queued=False; self.preview_play_requested=False
        # A plain, contiguous video timeline does not need an FFmpeg
        # composition render just to cut and play it.  The direct backend
        # keeps the source in QMediaPlayer and switches only when the playhead
        # crosses a cut.  Complex timelines still use the rendered backend.
        self.direct_preview=False; self.direct_preview_revision=-1
        self.direct_preview_signature=None; self.direct_clip_uid=None
        self.missing_media=[]; self.proxy_enabled=False; self.proxy_map={}; self.proxy_directory=None; self.proxy_profile='360p'
        self.auto_proxy_sources=set()
        self.gpu_preview_info=preview_acceleration_info()
        self.render_queue=[]; self.render_current=None; self.render_queue_paused=False
        self.mode='timeline'; self.playhead=0.0
        self.work_in=None; self.work_out=None
        # Source-monitor state is intentionally transient.  It is not part of
        # the project file: In/Out marks describe the current source-editing
        # session and are cleared whenever the timeline changes.
        self.source_clip_uid=None; self.source_in=None; self.source_out=None
        self.transport_rate=0.0; self.transport_rate_pending=None
        self.voiceover_capture=None; self.voiceover_input=None; self.voiceover_recorder=None
        self.voiceover_dialog=None; self.voiceover_target=None
        self.cinema_dialog=None
        self.transport_timer=QTimer(self); self.transport_timer.setInterval(40); self.transport_timer.timeout.connect(self.transport_tick)
        self.pending_seek=None; self.worker=None; self.recovery_enabled=recovery
        self._closing=False
        self.update_job=None; self.update_download_job=None; self.update_artifact=None
        self.setWindowTitle(f'Framecut {APP_VERSION} · Neues Projekt')
        self.resize(1460,980); self.setMinimumSize(1120,740)
        self.player=QMediaPlayer(self); self.audio=QAudioOutput(self); self.player.setAudioOutput(self.audio)
        # Library previews use a separate player so they never disturb the
        # timeline/source monitor state.
        self.library_player=QMediaPlayer(self); self.library_audio=QAudioOutput(self)
        self.library_audio.setVolume(.8); self.library_player.setAudioOutput(self.library_audio)
        self.player.positionChanged.connect(self.position_changed)
        self.player.mediaStatusChanged.connect(self.media_ready)
        self.player.errorOccurred.connect(lambda *_:self.statusBar().showMessage('Vorschau: '+self.player.errorString()))
        self.player.playbackStateChanged.connect(self.play_state)
        self.autosave_timer=QTimer(self); self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(2000); self.autosave_timer.timeout.connect(self.autosave)
        # Debounce edits so a burst of trim/property changes produces one
        # preview render after the user pauses, not one render per keystroke.
        self.live_preview_timer=QTimer(self); self.live_preview_timer.setSingleShot(True); self.live_preview_timer.setInterval(700); self.live_preview_timer.timeout.connect(self.auto_preview)
        self.build_ui(); self.init_smooth_ui(); self.update_project_identity(); self.setAcceptDrops(True); self.update_cache_status()
        shortcuts=[('Ctrl+I',self.import_dialog),('Ctrl+S',self.save),('Ctrl+Shift+S',lambda:self.save(True)),
                   ('Ctrl+O',self.open_project),('Ctrl+N',self.new_project),('Ctrl+Z',self.undo),
                   ('Ctrl+Shift+Z',self.redo),('Ctrl+Y',self.redo),('Ctrl+B',self.split),('S',self.split),
                   ('Ctrl+C',self.copy_selection),('Ctrl+V',self.paste_selection),('Ctrl+Shift+V',self.ripple_insert),
                   ('Ctrl+Alt+C',self.copy_attributes),('Ctrl+Alt+V',self.paste_attributes),
                   ('Ctrl+Alt+K',self.copy_keyframes),('Ctrl+Alt+Shift+K',self.paste_keyframes),
                   ('Ctrl+D',self.duplicate_selection),('Ctrl+G',self.group_selection),('Ctrl+Shift+G',self.ungroup_selection),
                   ('Ctrl+Shift+Delete',self.ripple_delete),('Q',self.ripple_trim_in),('W',self.ripple_trim_out),
                   ('I',self.set_source_in),('O',self.set_source_out),
                   ('Ctrl+Alt+I',self.set_work_in),('Ctrl+Alt+O',self.set_work_out),
                   ('R',self.roll_to_playhead),('Alt+Left',lambda:self.slide_selected(-1)),
                   ('Alt+Right',lambda:self.slide_selected(1)),
                   ('Shift+Alt+Left',lambda:self.slip_selected(-1)),
                   ('Shift+Alt+Right',lambda:self.slip_selected(1)),
                   ('Ctrl+A',self.select_all),('J',self.transport_j),('K',self.transport_stop),('L',self.transport_l),
                   ('Ctrl+K',self.open_command_palette),('Ctrl+Shift+F',self.toggle_focus_mode),('F11',self.toggle_cinema_preview),
                   ('Ctrl+Alt+Z',self.show_history),('Up',lambda:self.jump_cut(-1)),('Down',lambda:self.jump_cut(1)),
                   ('Space',self.toggle_play),('Delete',self.remove),('Backspace',self.remove),
                   ('Left',lambda:self.nudge_playhead(-1)),('Right',lambda:self.nudge_playhead(1)),
                   ('Shift+Left',lambda:self.nudge_playhead(-5)),('Shift+Right',lambda:self.nudge_playhead(5)),
                   ('Home',lambda:self.set_playhead(0)),('End',lambda:self.set_playhead(length(self.clips)))]
        for shortcut,fn in shortcuts:
            action=QAction(self); action.setShortcut(shortcut); action.setShortcutContext(Qt.WindowShortcut); action.triggered.connect(fn); self.addAction(action)
        self.refresh()
        self.statusBar().showMessage('Bereit · Lokal auf deinem Rechner · Quelldateien bleiben unverändert')
        if recovery: QTimer.singleShot(0,self.offer_recovery)
        if configured_manifest_url(): QTimer.singleShot(2500,lambda:self.check_for_updates(True))

    CUSTOM_LIBRARY_CATEGORIES = {
        'sounds': 'sound',
        'effects': 'effect',
        'animations': 'animation',
        'transitions': 'transition',
        'text_styles': 'text_style',
        'stickers': 'sticker',
        'filters': 'filter',
    }

    def _load_custom_library_items(self):
        """Load user assets without making the built-in catalog mutable."""
        try:
            raw=json.loads(self.custom_library_manifest.read_text(encoding='utf-8'))
        except (OSError,ValueError,TypeError):
            return []
        items=[]
        for value in raw if isinstance(raw,list) else []:
            if not isinstance(value,dict):
                continue
            category=str(value.get('category','')).strip()
            kind=str(value.get('kind','')).strip()
            if category not in self.CUSTOM_LIBRARY_CATEGORIES or kind != self.CUSTOM_LIBRARY_CATEGORIES[category]:
                continue
            parameters=value.get('parameters',{})
            if not isinstance(parameters,dict):
                parameters={}
            try:
                items.append(LibraryItem(
                    str(value.get('item_id') or f'custom_{uuid.uuid4().hex}'),
                    str(value.get('title') or 'Eigenes Asset'), category, kind,
                    str(value.get('description') or 'Eigenes Framecut-Asset.'),
                    tuple(str(tag) for tag in value.get('tags',[]) if str(tag).strip()),
                    str(value.get('icon') or 'package-x-generic'),
                    float(value.get('duration') or 0.0), dict(parameters)))
            except (TypeError,ValueError):
                continue
        return items

    def _save_custom_library_items(self):
        self.custom_library_manifest.parent.mkdir(parents=True,exist_ok=True)
        payload=[]
        for item in self.custom_library_items:
            payload.append({'item_id':item.item_id,'title':item.title,'category':item.category,
                            'kind':item.kind,'description':item.description,'tags':list(item.tags),
                            'icon':item.icon,'duration':item.duration,'parameters':dict(item.parameters)})
        temporary=self.custom_library_manifest.with_name(f'.{self.custom_library_manifest.name}.{uuid.uuid4().hex}.tmp')
        temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(self.custom_library_manifest)

    def _library_items_for(self, category):
        category=str(category)
        return tuple(library_items_for(category))+tuple(item for item in self.custom_library_items
                                                        if item.category == category)

    def _library_item(self, item_id):
        return get_library_item(item_id) or next((item for item in self.custom_library_items
                                                   if item.item_id == str(item_id)),None)

    def _refresh_custom_library(self):
        """Refresh every preset panel and the timeline's drag catalog."""
        if hasattr(self,'asset_library_panel'):
            self.asset_library_panel.set_items(self._library_items_for('sounds'))
        category_by_panel={'text':'text_styles','sticker':'stickers','effects':'effects',
                           'animations':'animations','transitions':'transitions','filters':'filters'}
        for key,panel_widget in getattr(self,'library_panels',{}).items():
            panel_widget.set_items(self._library_items_for(category_by_panel.get(key,key)))
        if hasattr(self,'timeline'):
            catalog=list(library_items())+list(self.custom_library_items)
            self.timeline.library_catalog={item.item_id:item for item in catalog}

    def import_custom_library_asset(self, category):
        """Import user sounds or JSON/LUT presets into the local asset catalog."""
        category=str(category or '').strip()
        if category == 'all':
            category,ok=QInputDialog.getItem(self,'Eigenes Asset importieren','Kategorie:',
                                              ['sounds','effects','animations','transitions','text_styles','stickers','filters'],0,False)
            if not ok:
                return
        if category not in self.CUSTOM_LIBRARY_CATEGORIES:
            return self.error('Diese Asset-Kategorie wird nicht unterstützt.')
        if category == 'sounds':
            paths,_=QFileDialog.getOpenFileNames(
                self,'Eigene Sounds importieren','',
                'Audio (*.wav *.mp3 *.flac *.ogg *.m4a *.aac);;Alle Dateien (*)')
            if not paths:
                return
            added=[]; errors=[]
            self.custom_library_root.mkdir(parents=True,exist_ok=True)
            for path in paths:
                try:
                    source=Path(path).expanduser().resolve()
                    audio=import_clip(source)
                    if audio.kind != 'audio':
                        raise ValueError('Die Datei enthält keine reine Audiospur.')
                    target=self.custom_library_root/f'{uuid.uuid4().hex}{source.suffix.lower()}'
                    shutil.copy2(source,target)
                    added.append(LibraryItem(
                        f'custom_sound_{uuid.uuid4().hex}',source.stem,'sounds','sound',
                        'Eigener importierter Sound.',('custom','audio'),'audio-volume-high',
                        float(audio.duration),{'path':str(target)}))
                except Exception as exc:
                    errors.append(f'{Path(path).name}: {exc}')
            if added:
                self.custom_library_items.extend(added); self._save_custom_library_items(); self._refresh_custom_library()
                self.statusBar().showMessage(f'{len(added)} eigene Sounds importiert.',4000)
            if errors:
                self.error('\n'.join(errors))
            return

        preset_filter='Framecut-Preset (*.json);;Alle Dateien (*)'
        if category == 'filters':
            preset_filter='Framecut-Preset oder LUT (*.json *.cube *.3dl);;Alle Dateien (*)'
        path,_=QFileDialog.getOpenFileName(self,'Eigenes Asset importieren','',preset_filter)
        if not path:
            return
        try:
            source=Path(path).expanduser().resolve()
            self.custom_library_root.mkdir(parents=True,exist_ok=True)
            if category == 'filters' and source.suffix.lower() in ('.cube','.3dl'):
                target=self.custom_library_root/f'{uuid.uuid4().hex}{source.suffix.lower()}'
                shutil.copy2(source,target)
                item=LibraryItem(f'custom_filter_{uuid.uuid4().hex}',source.stem,'filters','filter',
                                 'Eigene LUT für Farblooks.',('custom','lut'),'color-management',0.0,
                                 {'filter_preset':'none','lut_path':str(target)})
            else:
                payload=json.loads(source.read_text(encoding='utf-8'))
                if not isinstance(payload,dict):
                    raise ValueError('Das Preset muss ein JSON-Objekt sein.')
                payload_category=str(payload.get('category') or category)
                if payload_category != category:
                    raise ValueError(f'Das Preset gehört zur Kategorie „{payload_category}“, nicht „{category}“.')
                kind=self.CUSTOM_LIBRARY_CATEGORIES[category]
                parameters=payload.get('parameters',{})
                if not isinstance(parameters,dict):
                    raise ValueError('„parameters“ muss ein JSON-Objekt sein.')
                item=LibraryItem(
                    f'custom_{kind}_{uuid.uuid4().hex}',str(payload.get('title') or source.stem),
                    category,kind,str(payload.get('description') or 'Eigenes Framecut-Preset.'),
                    tuple(str(tag) for tag in payload.get('tags',[]) if str(tag).strip()),
                    str(payload.get('icon') or 'package-x-generic'),float(payload.get('duration') or 0.0),
                    dict(parameters))
            self.custom_library_items.append(item); self._save_custom_library_items(); self._refresh_custom_library()
            self.statusBar().showMessage(f'Eigenes Asset „{item.title}“ importiert.',4000)
        except Exception as exc:
            self.error(f'Asset konnte nicht importiert werden: {exc}')

    def build_ui(self):
        root=QWidget(); root.setObjectName('editorRoot')
        outer=QVBoxLayout(root); outer.setContentsMargins(12,10,12,8); outer.setSpacing(8)

        # Header: project identity and the actions that belong to the whole
        # edit. Keeping this separate from the workspace makes the hierarchy
        # readable even when the inspector is scrolled deeply.
        header=QFrame(); header.setObjectName('topbar')
        head=QHBoxLayout(header); head.setContentsMargins(13,7,10,7); head.setSpacing(5)
        head.addWidget(label('FRAMECUT','brand'))
        head.addWidget(label(f'v{APP_VERSION}','versionLabel'))
        divider=QFrame(); divider.setObjectName('headerDivider'); divider.setFrameShape(QFrame.VLine); divider.setFixedHeight(22); head.addWidget(divider)
        project_block=QVBoxLayout(); project_block.setContentsMargins(2,0,0,0); project_block.setSpacing(0)
        self.project_title_label=label('Neues Projekt','projectTitle'); project_block.addWidget(self.project_title_label)
        self.project_meta_label=label('Lokales Projekt','muted'); project_block.addWidget(self.project_meta_label)
        project_widget=QWidget(); project_widget.setLayout(project_block); head.addWidget(project_widget)
        head.addStretch(1)
        self.autosave_pill=label('● Autosave','statusPill'); self.autosave_pill.setToolTip('Automatische Sicherung ist aktiv'); head.addWidget(self.autosave_pill)
        self.new_button=icon_action('+','Neues Projekt · Strg+N',self.new_project,'document-new'); head.addWidget(self.new_button)
        self.open_button=icon_action('↥','Projekt öffnen · Strg+O',self.open_project,'document-open'); head.addWidget(self.open_button)
        self.save_button=icon_action('▣','Projekt speichern · Strg+S',self.save,'document-save'); head.addWidget(self.save_button)
        self.update_button=icon_action('↻','Nach Updates suchen',self.check_for_updates,'view-refresh'); head.addWidget(self.update_button)
        self.relink_button=icon_action('⛓','Medien neu verknüpfen',self.relink_media,'insert-link'); head.addWidget(self.relink_button)
        self.archive_button=icon_action('▤','Projekt archivieren',self.archive_project_dialog,'package-x-generic'); head.addWidget(self.archive_button)
        self.render_queue_button=icon_action('☷','Render-Queue öffnen',self.show_render_queue,'view-list'); head.addWidget(self.render_queue_button)
        self.mixer_button=icon_action('♫','Audio-Mixer öffnen',self.open_mixer,'audio-volume-high'); head.addWidget(self.mixer_button)
        self.command_button=icon_action('⌘','Befehlspalette öffnen · Strg+K',self.open_command_palette,'system-search'); head.addWidget(self.command_button)
        self.preset=QComboBox(); self.preset.setObjectName('projectPreset'); self.preset.addItems(PRESETS); self.preset.currentTextChanged.connect(self.preset_changed); self.preset.setToolTip('Projektformat und Vorschaugröße'); head.addWidget(self.preset)
        export_button=button('Exportieren',self.start_export,True); export_button.setObjectName('exportButton'); export_button.setMinimumWidth(106); head.addWidget(export_button)
        outer.addWidget(header)

        # The reference uses a lightweight mode strip above the three-column
        # workspace. These shortcuts expose existing actions without hiding
        # any of the editor's current controls.
        modebar=QFrame(); self.modebar=modebar; modebar.setObjectName('modebar')
        mode_layout=QHBoxLayout(modebar); mode_layout.setContentsMargins(7,3,7,3); mode_layout.setSpacing(3)
        mode_layout.addWidget(label('ARBEITSBEREICH','eyebrow'))
        mode_layout.addWidget(timeline_separator())
        self.mode_buttons=[]
        def mode_tab(text, callback=None, active=False, tooltip=''):
            tab=QPushButton(text); tab.setObjectName('modeTabActive' if active else 'modeTab')
            if tooltip: tab.setToolTip(tooltip)
            self.mode_buttons.append(tab)
            def activate(checked=False):
                for other in self.mode_buttons:
                    other.setObjectName('modeTab')
                    other.style().unpolish(other); other.style().polish(other); other.update()
                tab.setObjectName('modeTabActive'); tab.style().unpolish(tab); tab.style().polish(tab); tab.update()
                if callback: callback()
            tab.clicked.connect(activate); mode_layout.addWidget(tab)
            return tab
        mode_tab('Medien',self.open_media_panel,True,'Medienablage öffnen')
        mode_tab('Sound',self.open_sound_panel,tooltip='Soundbibliothek öffnen und eigene Sounds importieren')
        mode_tab('Audio',self.open_mixer,tooltip='Audio-Mixer öffnen')
        mode_tab('Text',self.open_text_panel,tooltip='Textdesign auswählen und Textclip anlegen')
        mode_tab('Animation',self.open_animation_panel,tooltip='Animationsbibliothek öffnen')
        mode_tab('Sticker',self.open_sticker_panel,tooltip='Offline-Stickerbibliothek öffnen')
        mode_tab('Effekte',self.open_effects_panel,tooltip='Effektbibliothek öffnen')
        mode_tab('Übergänge',self.open_transitions_panel,tooltip='Übergangsbibliothek öffnen')
        mode_tab('Filter',self.open_filters_panel,tooltip='Filterbibliothek öffnen')
        mode_layout.addStretch()
        mode_layout.addWidget(label('LAYOUT','eyebrow'))
        self.workspace_preset_combo=QComboBox(); self.workspace_preset_combo.setObjectName('workspacePreset')
        self.workspace_preset_combo.addItem('Schnitt','edit')
        self.workspace_preset_combo.addItem('Shorts / Reels','shorts')
        self.workspace_preset_combo.addItem('Audio','audio')
        self.workspace_preset_combo.addItem('Farbe','color')
        self.workspace_preset_combo.addItem('Untertitel','captions')
        self.workspace_preset_combo.setToolTip('Arbeitsbereich für die aktuelle Aufgabe wählen')
        self.workspace_preset_combo.currentIndexChanged.connect(self.apply_workspace_preset)
        mode_layout.addWidget(self.workspace_preset_combo)
        mode_layout.addWidget(label('MODUS','eyebrow'))
        self.edit_mode_combo=QComboBox(); self.edit_mode_combo.setObjectName('editModeCombo')
        self.edit_mode_combo.addItem('Einfach','simple'); self.edit_mode_combo.addItem('Pro','pro')
        self.edit_mode_combo.setToolTip('Einfach zeigt nur die häufigsten Einstellungen · Pro zeigt alle Werkzeuge')
        self.edit_mode_combo.currentIndexChanged.connect(self.set_edit_mode)
        mode_layout.addWidget(self.edit_mode_combo)
        self.edit_mode_badge=label('KERNWERKZEUGE','modeBadge'); mode_layout.addWidget(self.edit_mode_badge)
        self.focus_button=QPushButton('Fokus'); self.focus_button.setObjectName('modeTab'); self.focus_button.setToolTip('Vorschau und Timeline vergrößern · Strg+Shift+F')
        self.focus_button.clicked.connect(self.toggle_focus_mode); mode_layout.addWidget(self.focus_button)
        outer.addWidget(modebar)

        vertical=QSplitter(Qt.Vertical); self.vertical=vertical; top=QSplitter(Qt.Horizontal); self.top=top; top.setChildrenCollapsible(False)
        # Let the vertical splitter decide the height. The default Preferred
        # policy inherits the tall media-panel size hint and blocks the handle.
        top.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Ignored)
        media,ml=panel(); self.media_panel=media; media.setObjectName('mediaPanel'); media.setMinimumWidth(250)
        media_header=QHBoxLayout(); media_header.setContentsMargins(0,0,0,0); media_header.setSpacing(6)
        self.media_heading=label('MEDIEN','heading'); media_header.addWidget(self.media_heading); media_header.addStretch()
        self.media_count=label('0 Medien','muted'); media_header.addWidget(self.media_count); ml.addLayout(media_header)
        import_row=QHBoxLayout(); import_row.setContentsMargins(0,0,0,0); import_row.setSpacing(5)
        import_row.addWidget(button('+ Medien importieren',self.import_dialog,True),1)
        import_more=QToolButton(); import_more.setText('⋯'); import_more.setObjectName('panelMenuButton'); import_more.setToolTip('Weitere Importoptionen'); import_more.setAccessibleName('Weitere Importoptionen')
        import_menu=QMenu(self); import_menu.addAction('Bildsequenz importieren',self.import_sequence_dialog); import_menu.addAction('Untertitel importieren (SRT/VTT)',self.import_subtitle_dialog); import_menu.addAction('Automatische Untertitel',self.automatic_subtitle_dialog)
        import_more.setMenu(import_menu); import_more.setPopupMode(QToolButton.InstantPopup); import_row.addWidget(import_more)
        self.media_import_container=QWidget(); self.media_import_container.setLayout(import_row); ml.addWidget(self.media_import_container)
        self.media_search=QLineEdit(); self.media_search.setPlaceholderText('Medien durchsuchen …'); self.media_search.setClearButtonEnabled(True)
        self.media_search.setToolTip('Suche nach Dateiname, Pfad oder Medientyp')
        ml.addWidget(self.media_search)
        media_filter_row=QHBoxLayout(); media_filter_row.setContentsMargins(0,0,0,0); media_filter_row.setSpacing(6)
        self.media_filter=QComboBox()
        for value,title in (('all','Alle'),('video','Video'),('audio','Audio'),('image','Bilder'),('sequence','Sequenzen'),('offline','Offline')):
            self.media_filter.addItem(title,value)
        self.media_filter.setToolTip('Medien nach Typ oder Offline-Status filtern')
        self.media_sort=QComboBox()
        for value,title in (('order','Import-Reihenfolge'),('name','Name'),('type','Typ'),('duration','Dauer')):
            self.media_sort.addItem(title,value)
        self.media_sort.setToolTip('Reihenfolge der Medienablage')
        media_filter_row.addWidget(self.media_filter,1); media_filter_row.addWidget(self.media_sort,1)
        self.media_filter_container=QWidget(); self.media_filter_container.setLayout(media_filter_row); ml.addWidget(self.media_filter_container)
        library_tools=QHBoxLayout(); library_tools.setContentsMargins(0,0,0,0); library_tools.setSpacing(5)
        self.media_view_combo=QComboBox(); self.media_view_combo.setObjectName('mediaViewCombo')
        self.media_view_combo.addItem('Karten','cards'); self.media_view_combo.addItem('Liste','list')
        self.media_view_combo.setToolTip('Medienablage als Karten oder kompakte Liste anzeigen')
        self.media_view_combo.currentIndexChanged.connect(self.set_media_view)
        self.media_favorites_only=QCheckBox('★ Favoriten'); self.media_favorites_only.setObjectName('mediaFavorites')
        self.media_favorites_only.setToolTip('Nur markierte Medien anzeigen')
        self.media_favorites_only.toggled.connect(lambda *_: self.refresh_media())
        self.media_favorite_button=QToolButton(); self.media_favorite_button.setObjectName('mediaFavoriteButton'); self.media_favorite_button.setText('☆'); self.media_favorite_button.setToolTip('Ausgewähltes Medium als Favorit markieren'); self.media_favorite_button.setAccessibleName('Medium als Favorit markieren'); self.media_favorite_button.clicked.connect(self.toggle_asset_favorite)
        library_tools.addWidget(self.media_view_combo); library_tools.addWidget(self.media_favorites_only); library_tools.addStretch(); library_tools.addWidget(self.media_favorite_button)
        self.media_tools_container=QWidget(); self.media_tools_container.setLayout(library_tools); ml.addWidget(self.media_tools_container)
        self.media_hint=label('Ziehen zum Einfügen · Doppelklick zum Anhängen','subtle'); self.media_hint.setWordWrap(True); ml.addWidget(self.media_hint)
        self.media_empty_hint=label('Noch keine Medien\nImportiere ein Video, Audio oder Bild, um zu starten.','emptyState'); self.media_empty_hint.setAlignment(Qt.AlignCenter); self.media_empty_hint.setWordWrap(True); self.media_empty_hint.setVisible(False); ml.addWidget(self.media_empty_hint)
        self.media_list=MediaList(); self.media_list.setObjectName('mediaList'); self.media_list.setViewMode(QListWidget.IconMode)
        self.media_list.setResizeMode(QListWidget.Adjust); self.media_list.setWrapping(True); self.media_list.setSpacing(4)
        self.media_list.setIconSize(QSize(124,72)); self.media_list.setGridSize(QSize(150,108)); self.media_list.setUniformItemSizes(True)
        self.media_list.itemDoubleClicked.connect(lambda _:self.add_selected_asset())
        self.media_list.currentItemChanged.connect(lambda *_: self.update_media_favorite_button())
        self.media_search.textChanged.connect(self.refresh_media); self.media_filter.currentIndexChanged.connect(self.refresh_media); self.media_sort.currentIndexChanged.connect(self.refresh_media)
        ml.addWidget(self.media_list,1)
        self.add_timeline_button=button('＋ Zur Timeline hinzufügen',self.add_selected_asset); ml.addWidget(self.add_timeline_button)
        self.library_stack=QStackedWidget(); self.library_stack.setObjectName('libraryStack'); self.library_stack.hide()
        self.asset_library_panel=AssetLibraryPanel(
            items=self._library_items_for('sounds'),title='SOUND',
            hint='Eigene und mitgelieferte Sounds direkt anhören oder in die Timeline ziehen.',
            fixed_category='sounds',action_label='Einfügen')
        self.asset_library_panel.use_requested.connect(self.use_library_item)
        self.asset_library_panel.preview_requested.connect(self.preview_library_item)
        self.asset_library_panel.custom_import_requested.connect(self.import_custom_library_asset)
        self.library_stack.addWidget(self.asset_library_panel)
        self.library_panels={}
        dedicated_libraries=(
            ('text', self._library_items_for('text_styles'), 'TEXT-DESIGN',
             'Wähle zuerst ein fertiges Textdesign. Danach gibst du den Text ein; alle Stilwerte sind bereits vorbereitet.',
             'Text anlegen', 'text_styles'),
            ('animations', self._library_items_for('animations'), 'ANIMATIONEN',
             'Bewegungsvorlagen auf den ausgewählten Video- oder Textclip anwenden.',
             'Anwenden', 'animations'),
            ('sticker', self._library_items_for('stickers'), 'STICKER',
             'Offline-Sticker als editierbare Textobjekte einfügen. Position, Größe und Farbe sind sofort anpassbar.',
             'Einfügen', 'stickers'),
            ('effects', self._library_items_for('effects'), 'EFFEKTE',
             'Video-Looks und Adjustment-Startwerte auf den ausgewählten Clip anwenden.',
             'Anwenden', 'effects'),
            ('transitions', self._library_items_for('transitions'), 'ÜBERGÄNGE',
             'Einen Übergang als Startwert auf den ausgewählten Video- oder Audioclip anwenden.',
             'Anwenden', 'transitions'),
            ('filters', self._library_items_for('filters'), 'FILTER',
             'Farblooks auswählen und direkt auf den ausgewählten Videoclip anwenden.',
             'Anwenden', 'filters'),
        )
        for key,items,title,hint,action_label,category in dedicated_libraries:
            panel_widget=AssetLibraryPanel(items=items,title=title,hint=hint,
                                            fixed_category=category,action_label=action_label)
            panel_widget.use_requested.connect(self.use_library_item)
            panel_widget.preview_requested.connect(self.preview_library_item)
            panel_widget.custom_import_requested.connect(self.import_custom_library_asset)
            self.library_panels[key]=panel_widget
            self.library_stack.addWidget(panel_widget)
        ml.addWidget(self.library_stack,1)
        self._media_controls=(self.media_import_container,self.media_search,self.media_filter_container,
                              self.media_tools_container,self.media_hint,self.media_empty_hint,
                              self.media_list,self.add_timeline_button)
        top.addWidget(media)
        preview,pl=panel(); self.preview_panel=preview; preview.setObjectName('previewPanel'); pl.setContentsMargins(8,7,8,7); pl.setSpacing(5)
        preview_header_frame=QFrame(); preview_header_frame.setObjectName('previewHeader')
        preview_header=QHBoxLayout(preview_header_frame); preview_header.setContentsMargins(0,0,0,0); preview_header.setSpacing(6)
        preview_header.addWidget(label('PLAYER','heading')); preview_header.addStretch()
        self.preview_mode_pill=label('TIMELINE','statusPill'); self.preview_mode_pill.setObjectName('previewModePill'); preview_header.addWidget(self.preview_mode_pill)
        pl.addWidget(preview_header_frame)
        self.preview_status=label('Timeline-Vorschau wird beim ersten Abspielen berechnet.','muted'); self.preview_status.setObjectName('previewStatus'); self.preview_status.setWordWrap(False); pl.addWidget(self.preview_status)
        preview_options=QHBoxLayout(); self.live_preview_box=QCheckBox('Live-Vorschau'); self.live_preview_box.setChecked(True); self.live_preview_box.setToolTip('Nach einer Änderung automatisch eine neue Vorschau berechnen')
        self.quick_preview_box=QCheckBox('Schnellvorschau'); self.quick_preview_box.setChecked(True); self.quick_preview_box.setToolTip('Niedrigere Auflösung und schnelleres Rendering für die Vorschau')
        self.gpu_preview_box=QCheckBox('GPU-Decoding'); self.gpu_preview_box.setChecked(self.gpu_preview_info['available']); self.gpu_preview_box.setEnabled(self.gpu_preview_info['available'])
        self.gpu_preview_box.setToolTip(self.gpu_preview_info['label']+' · fällt sonst automatisch auf CPU zurück')
        self.live_preview_box.toggled.connect(self.preview_option_changed); self.quick_preview_box.toggled.connect(self.preview_option_changed); self.gpu_preview_box.toggled.connect(self.preview_option_changed)
        preview_options.addWidget(self.live_preview_box); preview_options.addWidget(self.quick_preview_box); preview_options.addWidget(self.gpu_preview_box); preview_options.addStretch()
        performance_options=QHBoxLayout(); self.proxy_box=QCheckBox('Proxy-Vorschau'); self.proxy_box.setEnabled(False)
        self.proxy_box.setToolTip('Erzeugt lokale, kleinere Vorschau-Dateien. Bei sehr großen Quellen startet Framecut die Schnellvorschau automatisch im Hintergrund; Originale bleiben für den Export aktiv.')
        self.proxy_profile_combo=QComboBox()
        for value,info in PROXY_PROFILES.items(): self.proxy_profile_combo.addItem(info['label'],value)
        self.proxy_profile_combo.setCurrentIndex(self.proxy_profile_combo.findData(self.proxy_profile)); self.proxy_profile_combo.setEnabled(False)
        self.proxy_profile_combo.setToolTip('Qualität der Proxy-Dateien: 360p ist schneller, 720p detailreicher')
        self.cache_status=label('Cache wird automatisch begrenzt','muted'); self.cache_clear_button=button('Cache leeren',self.clear_cache)
        self.proxy_box.toggled.connect(self.proxy_toggled); self.proxy_profile_combo.currentIndexChanged.connect(self.proxy_profile_changed)
        performance_options.addWidget(self.proxy_box); performance_options.addWidget(label('Profil','muted')); performance_options.addWidget(self.proxy_profile_combo); performance_options.addStretch(); performance_options.addWidget(self.cache_status); performance_options.addWidget(self.cache_clear_button)
        self.video_stack=QStackedWidget(); self.video_stack.setObjectName('previewCanvas'); self.video_stack.setMinimumSize(330,190)
        self.placeholder=label('Dein Film beginnt hier.\n\nMedien importieren → in die Timeline ziehen', 'muted')
        self.placeholder.setAlignment(Qt.AlignCenter); self.video_stack.addWidget(self.placeholder)
        self.video=VideoView(); self.player.setVideoSink(self.video.sink); self.video_stack.addWidget(self.video)
        pl.addWidget(self.video_stack,1)
        self.seek=QSlider(Qt.Horizontal); self.seek.setObjectName('previewSeek'); self.seek.setRange(0,10000); self.seek.sliderMoved.connect(self.seek_slider); pl.addWidget(self.seek)
        transport=QFrame(); transport.setObjectName('playerTransport')
        controls=QHBoxLayout(transport); controls.setContentsMargins(0,0,0,0); controls.setSpacing(4)
        self.play_button=button('▶',self.toggle_play); self.play_button.setObjectName('previewPlayButton'); self.play_button.setToolTip('Timeline abspielen / pausieren · Leertaste'); self.play_button.setAccessibleName('Timeline abspielen oder pausieren'); controls.addWidget(self.play_button)
        self.source_preview_button=button('◉',self.source_preview); self.source_preview_button.setObjectName('previewControlButton'); self.source_preview_button.setToolTip('Ausgewählten Clip ansehen'); self.source_preview_button.setAccessibleName('Ausgewählten Clip ansehen'); controls.addWidget(self.source_preview_button)
        controls.addWidget(label('00:00','previewTimecode')); controls.addStretch()
        self.cinema_button=button('⛶',self.toggle_cinema_preview); self.cinema_button.setIcon(line_icon('view-fullscreen')); self.cinema_button.setObjectName('previewControlButton'); self.cinema_button.setToolTip('Vollbildvorschau'); controls.addWidget(self.cinema_button)
        self.time_label=label('00:00.0 / 00:00.0','muted'); self.time_label.setObjectName('previewTimeLabel'); controls.addWidget(self.time_label); pl.addWidget(transport)
        source_controls=QHBoxLayout(); source_controls.setContentsMargins(6,0,6,0); source_controls.setSpacing(3)
        self.source_range_label=label('◉ Clip · In/Out','muted'); self.source_range_label.setObjectName('sourceRangeLabel'); source_controls.addWidget(self.source_range_label,1)
        self.source_in_button=timeline_tool_button('I','Quell-In am aktuellen Quellbild setzen · I',self.set_source_in,object_name='sourceToolButton')
        self.source_out_button=timeline_tool_button('O','Quell-Out am aktuellen Quellbild setzen · O',self.set_source_out,object_name='sourceToolButton')
        self.source_clear_button=timeline_tool_button('×','Quell-In/Out auf den gesamten Clip zurücksetzen',self.clear_source_marks,object_name='sourceToolDanger')
        self.source_insert_button=timeline_tool_button('↳','Markierten Quellbereich am Abspielkopf einfügen und spätere Clips verschieben',self.insert_source_range,'insert-object',object_name='sourceToolButton')
        self.source_overwrite_button=timeline_tool_button('▣','Markierten Quellbereich am Abspielkopf überschreiben',self.overwrite_source_range,'document-save-as',object_name='sourceToolButton')
        for widget in (self.source_in_button,self.source_out_button,self.source_clear_button,self.source_insert_button,self.source_overwrite_button): source_controls.addWidget(widget)
        range_separator=timeline_separator(); range_separator.setFixedHeight(24); source_controls.addWidget(range_separator)
        self.work_range_label=label('⌁ Timeline · gesamt','muted'); self.work_range_label.setObjectName('sourceRangeLabel'); source_controls.addWidget(self.work_range_label,1)
        self.work_in_button=timeline_tool_button('I','Arbeitsbereich-In am Abspielkopf setzen · Strg+Alt+I',self.set_work_in,object_name='sourceToolButton')
        self.work_out_button=timeline_tool_button('O','Arbeitsbereich-Out am Abspielkopf setzen · Strg+Alt+O',self.set_work_out,object_name='sourceToolButton')
        self.work_clear_button=timeline_tool_button('×','Arbeitsbereich löschen',self.clear_work_area,object_name='sourceToolDanger')
        for widget in (self.work_in_button,self.work_out_button,self.work_clear_button): source_controls.addWidget(widget)
        source_bar=QFrame(); source_bar.setObjectName('previewSubbar'); source_bar.setLayout(source_controls); pl.addWidget(source_bar)
        preview_tools=QFrame(); self.preview_tools=preview_tools; preview_tools.setObjectName('previewToolbar')
        preview_tools_layout=QVBoxLayout(preview_tools); preview_tools_layout.setContentsMargins(8,4,8,4); preview_tools_layout.setSpacing(1)
        preview_tools_layout.addLayout(preview_options); preview_tools_layout.addLayout(performance_options); pl.addWidget(preview_tools)
        top.addWidget(preview)
        inspector,inspector_outer=panel(); self.inspector_panel=inspector; inspector.setObjectName('inspectorPanel'); inspector.setMinimumWidth(250); inspector.setMinimumHeight(0)
        inspector_scroll=QScrollArea(); self.inspector_scroll=inspector_scroll; inspector_scroll.setWidgetResizable(True); inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); inspector_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        inspector_content=QWidget(); il=QVBoxLayout(inspector_content); il.setContentsMargins(0,0,0,0); il.setSpacing(8)
        inspector_scroll.setWidget(inspector_content); inspector_outer.addWidget(inspector_scroll)
        inspector_header=QFrame(); inspector_header.setObjectName('inspectorHeader')
        inspector_header_layout=QVBoxLayout(inspector_header); inspector_header_layout.setContentsMargins(10,8,10,8); inspector_header_layout.setSpacing(2)
        inspector_header_layout.addWidget(label('INSPECTOR','eyebrow'))
        self.clip_name=label('Kein Clip ausgewählt','projectTitle'); self.clip_name.setWordWrap(True); inspector_header_layout.addWidget(self.clip_name)
        il.addWidget(inspector_header)

        # Context actions keep the most common clip operations next to the
        # selected object. The permanent timeline toolbar stays compact while
        # this row changes with the current selection.
        self.context_toolbar=QFrame(); self.context_toolbar.setObjectName('contextToolbar')
        context_layout=QHBoxLayout(self.context_toolbar); context_layout.setContentsMargins(5,4,5,4); context_layout.setSpacing(2)
        self.context_split_button=timeline_tool_button('✂','Ausgewählten Clip am Abspielkopf teilen · S',self.split,'edit-cut',object_name='contextAction')
        self.context_duplicate_button=timeline_tool_button('⧉','Auswahl duplizieren · Strg+D',self.duplicate_selection,'edit-copy',object_name='contextAction')
        self.context_reset_button=timeline_tool_button('↺','Bild- und Effekteinstellungen zurücksetzen',self.reset_transform,'view-refresh',object_name='contextAction')
        self.context_delete_button=timeline_tool_button('⌫','Auswahl entfernen · Entf',self.remove,'edit-delete',object_name='contextAction')
        for action in (self.context_split_button,self.context_duplicate_button,self.context_reset_button,self.context_delete_button): context_layout.addWidget(action)
        context_layout.addStretch(); il.addWidget(self.context_toolbar)

        def inspector_section(title, expanded=True, advanced=False):
            section=QFrame(); section.setObjectName('inspectorSection')
            section_layout=QVBoxLayout(section); section_layout.setContentsMargins(0,0,0,0); section_layout.setSpacing(0)
            toggle=QToolButton(); toggle.setObjectName('inspectorSectionHeader'); toggle.setText(title); toggle.setCheckable(True); toggle.setChecked(expanded); toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow); toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); toggle.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
            body=QFrame(); body.setObjectName('inspectorSectionBody'); body.setVisible(expanded)
            body_layout=QVBoxLayout(body); body_layout.setContentsMargins(10,7,10,10); body_layout.setSpacing(7)
            toggle.toggled.connect(lambda checked, body=body, toggle=toggle: (body.setVisible(checked), toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)))
            section_layout.addWidget(toggle); section_layout.addWidget(body); il.addWidget(section)
            self.inspector_sections.append({'section':section,'advanced':advanced,'toggle':toggle,'body':body})
            return body_layout

        self.position=QDoubleSpinBox(); self.start=QDoubleSpinBox(); self.end=QDoubleSpinBox()
        for spin in [self.position,self.start,self.end]: spin.setRange(0,864000); spin.setDecimals(3); spin.setSuffix(' s'); spin.setSingleStep(.1)
        self.track_combo=QComboBox(); self.volume=QDoubleSpinBox(); self.volume.setRange(0,100); self.volume.setDecimals(0); self.volume.setSuffix(' %')
        self.audio_noise_reduction=QDoubleSpinBox(); self.audio_noise_reduction.setRange(0,30); self.audio_noise_reduction.setDecimals(1); self.audio_noise_reduction.setSingleStep(1); self.audio_noise_reduction.setSuffix(' dB')
        self.audio_eq_low=QDoubleSpinBox(); self.audio_eq_mid=QDoubleSpinBox(); self.audio_eq_high=QDoubleSpinBox()
        for spin in (self.audio_eq_low,self.audio_eq_mid,self.audio_eq_high): spin.setRange(-12,12); spin.setDecimals(1); spin.setSingleStep(1); spin.setSuffix(' dB')
        self.audio_compressor_enabled=QCheckBox('Kompressor aktiv')
        self.audio_compressor_threshold=QDoubleSpinBox(); self.audio_compressor_threshold.setRange(-60,0); self.audio_compressor_threshold.setDecimals(1); self.audio_compressor_threshold.setSingleStep(1); self.audio_compressor_threshold.setSuffix(' dB')
        self.audio_compressor_ratio=QDoubleSpinBox(); self.audio_compressor_ratio.setRange(1,20); self.audio_compressor_ratio.setDecimals(1); self.audio_compressor_ratio.setSingleStep(.5); self.audio_compressor_ratio.setSuffix('×')
        self.audio_ducking=QDoubleSpinBox(); self.audio_ducking.setRange(0,100); self.audio_ducking.setDecimals(0); self.audio_ducking.setSuffix(' %')
        self.audio_voice_isolation=QDoubleSpinBox(); self.audio_voice_isolation.setRange(0,100); self.audio_voice_isolation.setDecimals(0); self.audio_voice_isolation.setSuffix(' %')
        self.audio_voice_isolation.setToolTip('Lokale Sprachisolierung: Dialog hervorheben und Hintergrund reduzieren')
        self.audio_normalize=QCheckBox('Loudness normalisieren')
        self.audio_normalize_target=QDoubleSpinBox(); self.audio_normalize_target.setRange(-30,-5); self.audio_normalize_target.setDecimals(1); self.audio_normalize_target.setSingleStep(1); self.audio_normalize_target.setSuffix(' LUFS')
        self.audio_normalize_target.setToolTip('Zielpegel für diesen Clip; -16 LUFS ist ein guter Allround-Wert.')
        self.audio_channel_mode=QComboBox()
        channel_titles={'stereo':'Stereo','mono':'Mono','left':'Linker Kanal auf Stereo','right':'Rechter Kanal auf Stereo'}
        for value in AUDIO_CHANNEL_MODES: self.audio_channel_mode.addItem(channel_titles[value],value)
        self.audio_pan=QDoubleSpinBox(); self.audio_pan.setRange(-100,100); self.audio_pan.setDecimals(0); self.audio_pan.setSuffix(' %')
        self.speed=QDoubleSpinBox(); self.speed.setRange(.25,4); self.speed.setDecimals(2); self.speed.setSingleStep(.25); self.speed.setSuffix('×')
        self.freeze_enabled=QCheckBox('Letztes Bild halten')
        self.freeze_duration=QDoubleSpinBox(); self.freeze_duration.setRange(0,600); self.freeze_duration.setDecimals(2); self.freeze_duration.setSingleStep(.1); self.freeze_duration.setSuffix(' s')
        self.reverse_clip=QCheckBox('Rückwärts abspielen')
        self.fade_in=QDoubleSpinBox(); self.fade_in.setRange(0,60); self.fade_in.setDecimals(2); self.fade_in.setSingleStep(.1); self.fade_in.setSuffix(' s')
        self.fade_out=QDoubleSpinBox(); self.fade_out.setRange(0,60); self.fade_out.setDecimals(2); self.fade_out.setSingleStep(.1); self.fade_out.setSuffix(' s')
        self.text_value=QLineEdit(); self.text_value.setPlaceholderText('Text eingeben')
        self.text_size=QSpinBox(); self.text_size.setRange(8,240); self.text_size.setValue(56); self.text_size.setSuffix(' px')
        self.text_color=QLineEdit('#ffffff'); self.text_color.setMaxLength(7); self.text_color.setPlaceholderText('#ffffff')
        self.text_palette_button=QPushButton('Palette'); self.text_palette_button.clicked.connect(self.choose_text_color)
        self.text_font=QFontComboBox(); self.text_font.setCurrentFont(QFont('DejaVu Sans'))
        self.text_font.setToolTip('Schriftfamilie für den Textclip')
        self.text_bold=QCheckBox('Fett'); self.text_italic=QCheckBox('Kursiv')
        self.text_outline_width=QDoubleSpinBox(); self.text_outline_width.setRange(0,20); self.text_outline_width.setDecimals(0); self.text_outline_width.setSuffix(' px')
        self.text_outline_color=QLineEdit('#000000'); self.text_outline_color.setMaxLength(7); self.text_outline_color.setPlaceholderText('#000000')
        self.text_shadow_size=QDoubleSpinBox(); self.text_shadow_size.setRange(0,40); self.text_shadow_size.setDecimals(0); self.text_shadow_size.setSuffix(' px')
        self.text_shadow_color=QLineEdit('#000000'); self.text_shadow_color.setMaxLength(7); self.text_shadow_color.setPlaceholderText('#000000')
        self.text_background_enabled=QCheckBox('Hintergrund anzeigen'); self.text_background_enabled.setChecked(True)
        self.text_background_color=QLineEdit('#000000'); self.text_background_color.setMaxLength(7); self.text_background_color.setPlaceholderText('#000000')
        self.text_background_opacity=QDoubleSpinBox(); self.text_background_opacity.setRange(0,100); self.text_background_opacity.setDecimals(0); self.text_background_opacity.setValue(35); self.text_background_opacity.setSuffix(' %')
        self.text_background_padding=QSpinBox(); self.text_background_padding.setRange(0,80); self.text_background_padding.setValue(16); self.text_background_padding.setSuffix(' px')
        self.text_animation=QComboBox()
        for title,value in [('Keine','none'),('Ein-/Ausblenden','fade'),('Von links','slide_left'),('Von rechts','slide_right'),('Von oben','slide_up'),('Von unten','slide_down')]: self.text_animation.addItem(title,value)
        self.text_animation_duration=QDoubleSpinBox(); self.text_animation_duration.setRange(.05,10); self.text_animation_duration.setDecimals(2); self.text_animation_duration.setSingleStep(.05); self.text_animation_duration.setSuffix(' s')
        self.text_style_preset=QComboBox()
        for title,value in [('Titel','title'),('Untertitel','subtitle'),('Lower Third','lower_third')]: self.text_style_preset.addItem(title,value)
        self.text_style_apply_button=button('Stil anwenden',self.apply_text_style_preset)
        self.text_x=QDoubleSpinBox(); self.text_x.setRange(0,100); self.text_x.setDecimals(1); self.text_x.setSuffix(' %')
        self.text_y=QDoubleSpinBox(); self.text_y.setRange(0,100); self.text_y.setDecimals(1); self.text_y.setSuffix(' %')
        self.transform_scale=QDoubleSpinBox(); self.transform_scale.setRange(.1,4); self.transform_scale.setDecimals(2); self.transform_scale.setSingleStep(.1); self.transform_scale.setSuffix('×')
        self.transform_x=QDoubleSpinBox(); self.transform_x.setRange(0,100); self.transform_x.setDecimals(1); self.transform_x.setSuffix(' %')
        self.transform_y=QDoubleSpinBox(); self.transform_y.setRange(0,100); self.transform_y.setDecimals(1); self.transform_y.setSuffix(' %')
        self.rotation=QDoubleSpinBox(); self.rotation.setRange(-360,360); self.rotation.setDecimals(1); self.rotation.setSingleStep(5); self.rotation.setSuffix('°')
        self.crop_left=QDoubleSpinBox(); self.crop_top=QDoubleSpinBox(); self.crop_right=QDoubleSpinBox(); self.crop_bottom=QDoubleSpinBox()
        for spin in (self.crop_left,self.crop_top,self.crop_right,self.crop_bottom):
            spin.setRange(0,95); spin.setDecimals(1); spin.setSingleStep(1); spin.setSuffix(' %')
        self.flip_horizontal=QCheckBox('Horizontal'); self.flip_vertical=QCheckBox('Vertikal')
        self.brightness=QDoubleSpinBox(); self.brightness.setRange(-1,1); self.brightness.setDecimals(2); self.brightness.setSingleStep(.05)
        self.contrast=QDoubleSpinBox(); self.contrast.setRange(0,3); self.contrast.setDecimals(2); self.contrast.setSingleStep(.1); self.contrast.setSuffix('×')
        self.saturation=QDoubleSpinBox(); self.saturation.setRange(0,3); self.saturation.setDecimals(2); self.saturation.setSingleStep(.1); self.saturation.setSuffix('×')
        self.color_exposure=QDoubleSpinBox(); self.color_exposure.setRange(-3,3); self.color_exposure.setDecimals(2); self.color_exposure.setSingleStep(.1); self.color_exposure.setSuffix(' EV')
        self.color_temperature=QDoubleSpinBox(); self.color_temperature.setRange(-100,100); self.color_temperature.setDecimals(0); self.color_temperature.setSingleStep(5); self.color_temperature.setSuffix(' %')
        self.color_tint=QDoubleSpinBox(); self.color_tint.setRange(-100,100); self.color_tint.setDecimals(0); self.color_tint.setSingleStep(5); self.color_tint.setSuffix(' %')
        self.color_vibrance=QDoubleSpinBox(); self.color_vibrance.setRange(-100,100); self.color_vibrance.setDecimals(0); self.color_vibrance.setSuffix(' %')
        self.color_wheel_spins={}
        for wheel in ('lift','gamma','gain'):
            for channel in ('r','g','b'):
                spin=QDoubleSpinBox(); spin.setRange(-100,100); spin.setDecimals(0); spin.setSingleStep(5); spin.setSuffix(' %')
                self.color_wheel_spins[f'color_{wheel}_{channel}']=spin
                setattr(self, f'color_{wheel}_{channel}', spin)
        self.filter_preset=QComboBox()
        for title,value in [('Kein Filter','none'),('Vivid','vivid'),('Warm','warm'),('Cool','cool'),('Cinematic','cinematic'),('Vintage','vintage'),('Noir','noir')]: self.filter_preset.addItem(title,value)
        self.lut_path=QLineEdit(); self.lut_path.setPlaceholderText('Optional: .cube / .3dl LUT')
        self.lut_browse_button=QPushButton('LUT …'); self.lut_browse_button.clicked.connect(self.choose_lut)
        self.opacity=QDoubleSpinBox(); self.opacity.setRange(0,100); self.opacity.setDecimals(0); self.opacity.setSuffix(' %')
        self.blur=QDoubleSpinBox(); self.blur.setRange(0,20); self.blur.setDecimals(1); self.blur.setSingleStep(.5); self.blur.setSuffix(' σ')
        self.sharpen=QDoubleSpinBox(); self.sharpen.setRange(0,5); self.sharpen.setDecimals(1); self.sharpen.setSingleStep(.25); self.sharpen.setSuffix('×')
        self.effect_preset=QComboBox()
        for title,value in [('Clean / Manuell','clean'),('Cinematic','cinematic'),('Dream','dream'),('Noir','noir'),('Vivid','vivid'),('Soft Focus','soft_focus')]:
            self.effect_preset.addItem(title,value)
        self.effect_preset_apply_button=button('Preset anwenden',self.apply_effect_preset)
        self.stabilization=QDoubleSpinBox(); self.stabilization.setRange(0,100); self.stabilization.setDecimals(0); self.stabilization.setSuffix(' %')
        self.stabilization.setToolTip('Lokale Deshake-Stabilisierung. Höhere Werte suchen stärker, können aber Bildrand verändern.')
        self.background_removal_enabled=QCheckBox('Freistellung verwenden')
        self.background_remove_button=button('Hintergrund entfernen',self.start_background_removal)
        self.background_clear_button=button('Freistellung zurücksetzen',self.clear_background_removal)
        self.background_remove_status=label('Noch keine Freistellung erzeugt.','muted'); self.background_remove_status.setWordWrap(True)
        self.track_motion_button=button('Motion-Tracking starten',self.start_motion_tracking)
        self.mask_track_button=button('Bezier-Maske verfolgen',self.start_mask_tracking)
        self.clear_tracking_button=button('Tracking löschen',self.clear_motion_tracking)
        self.tracking_status=label('Kein Tracking vorhanden.','muted'); self.tracking_status.setWordWrap(True)
        self.auto_reframe_enabled=QCheckBox('Auto-Reframe verwenden')
        self.auto_reframe_format=QComboBox()
        for value in AUTO_REFRAME_FORMATS:
            self.auto_reframe_format.addItem(AUTO_REFRAME_FORMAT_LABELS[value],value)
        self.auto_reframe_button=button('Auto-Reframe analysieren',self.start_auto_reframe)
        self.auto_reframe_clear_button=button('Reframe löschen',self.clear_auto_reframe)
        self.auto_reframe_status=label('Noch keine Auto-Reframe-Analyse.','muted'); self.auto_reframe_status.setWordWrap(True)
        self.object_removal_enabled=QCheckBox('Objekt im Bereich entfernen')
        self.chroma_key_enabled=QCheckBox('Greenscreen aktiv')
        self.chroma_key_color=QLineEdit('#00ff00'); self.chroma_key_color.setMaxLength(7); self.chroma_key_color.setPlaceholderText('#00ff00')
        self.chroma_key_similarity=QDoubleSpinBox(); self.chroma_key_similarity.setRange(0,100); self.chroma_key_similarity.setDecimals(0); self.chroma_key_similarity.setSuffix(' %')
        self.chroma_key_blend=QDoubleSpinBox(); self.chroma_key_blend.setRange(0,100); self.chroma_key_blend.setDecimals(0); self.chroma_key_blend.setSuffix(' %')
        self.mask_type=QComboBox()
        for title,value in [('Keine Maske','none'),('Rechteck','rectangle'),('Ellipse','ellipse'),('Bezier / Freiform','bezier')]: self.mask_type.addItem(title,value)
        self.mask_type.currentIndexChanged.connect(self.mask_type_changed)
        self.mask_x=QDoubleSpinBox(); self.mask_y=QDoubleSpinBox(); self.mask_width=QDoubleSpinBox(); self.mask_height=QDoubleSpinBox(); self.mask_feather=QDoubleSpinBox()
        for spin in (self.mask_x,self.mask_y,self.mask_width,self.mask_height,self.mask_feather): spin.setRange(0,100); spin.setDecimals(1); spin.setSuffix(' %')
        self.mask_width.setValue(100); self.mask_height.setValue(100)
        self.mask_points=QLineEdit(); self.mask_points.setPlaceholderText('10,10; 90,10; 90,90; 10,90')
        self.mask_points.setToolTip('Bezier-Anker als Prozentwerte eingeben: x,y; x,y; …')
        self.mask_points_apply=button('Punkte übernehmen',self.apply_mask_points)
        self.mask_path_time=QDoubleSpinBox(); self.mask_path_time.setRange(0,864000); self.mask_path_time.setDecimals(2); self.mask_path_time.setSingleStep(.1); self.mask_path_time.setSuffix(' s')
        self.mask_path_list=QListWidget(); self.mask_path_list.setMaximumHeight(74); self.mask_path_list.setMinimumHeight(36)
        self.mask_path_set_button=button('Rotoskopie-Punkt setzen',self.set_mask_path_keyframe)
        self.mask_path_remove_button=button('Rotoskopie-Punkt löschen',self.remove_mask_path_keyframe)
        self.mask_path_list.currentRowChanged.connect(self.mask_path_selected)
        self.transition_type=QComboBox()
        for title,value in [('Kein Übergang','none'),('Überblenden','dissolve'),('Slide links','slide_left'),('Slide rechts','slide_right'),('Slide oben','slide_up'),('Slide unten','slide_down'),('Wipe links','wipe_left'),('Wipe rechts','wipe_right'),('Wipe oben','wipe_up'),('Wipe unten','wipe_down'),('Zoom','zoom'),('Dip to Black','dip_to_black'),('Fade to White','fade_white'),('Blur In','blur_in'),('Circle Open','circle_open'),('Circle Close','circle_close'),('Radial','radial'),('Pixelize','pixelize'),('Smooth links','smooth_left'),('Smooth rechts','smooth_right'),('Smooth oben','smooth_up'),('Smooth unten','smooth_down'),('Cover links','cover_left'),('Cover rechts','cover_right'),('Cover oben','cover_up'),('Cover unten','cover_down')]: self.transition_type.addItem(title,value)
        self.transition_duration=QDoubleSpinBox(); self.transition_duration.setRange(0,30); self.transition_duration.setDecimals(2); self.transition_duration.setSingleStep(.1); self.transition_duration.setSuffix(' s')
        self.keyframe_time=QDoubleSpinBox(); self.keyframe_time.setRange(0,864000); self.keyframe_time.setDecimals(2); self.keyframe_time.setSingleStep(.1); self.keyframe_time.setSuffix(' s')
        self.keyframe_curve=QComboBox()
        for value in KEYFRAME_CURVES: self.keyframe_curve.addItem(KEYFRAME_CURVE_LABELS[value],value)
        self.keyframe_list=QListWidget(); self.keyframe_list.setObjectName('keyframeList'); self.keyframe_list.setMaximumHeight(96); self.keyframe_list.setMinimumHeight(42)
        self.keyframe_set_button=button('Keyframe setzen / aktualisieren',self.set_keyframe)
        self.keyframe_remove_button=button('Keyframe löschen',self.remove_keyframe)
        self.keyframe_list.currentRowChanged.connect(self.keyframe_selected)
        self.keyframe_graph_property=QComboBox()
        for title,value in [('Zoom','scale'),('Bild X','x'),('Bild Y','y'),('Rotation','rotation'),('Deckkraft','opacity'),('Unschärfe','blur')]:
            self.keyframe_graph_property.addItem(title,value)
        self.keyframe_graph=KeyframeGraphWidget()
        self.keyframe_graph_property.currentIndexChanged.connect(lambda *_: self.refresh_keyframe_graph(self.current_clip()))
        self.keyframe_graph.point_moved.connect(self.graph_keyframe_moved)
        self.keyframe_graph.point_added.connect(self.graph_keyframe_added)
        self.keyframe_graph.point_selected.connect(self.graph_keyframe_selected)
        self.keyframe_graph.drag_started.connect(self.graph_keyframe_drag_started)
        self.keyframe_graph.drag_finished.connect(self.graph_keyframe_drag_finished)
        self.volume_keyframe_time=QDoubleSpinBox(); self.volume_keyframe_time.setRange(0,864000); self.volume_keyframe_time.setDecimals(2); self.volume_keyframe_time.setSingleStep(.1); self.volume_keyframe_time.setSuffix(' s')
        self.volume_keyframe_curve=QComboBox()
        for value in KEYFRAME_CURVES: self.volume_keyframe_curve.addItem(KEYFRAME_CURVE_LABELS[value],value)
        self.volume_keyframe_list=QListWidget(); self.volume_keyframe_list.setMaximumHeight(96); self.volume_keyframe_list.setMinimumHeight(42)
        self.volume_keyframe_set_button=button('Lautstärke setzen / aktualisieren',self.set_volume_keyframe)
        self.volume_keyframe_remove_button=button('Lautstärke-Keyframe löschen',self.remove_volume_keyframe)
        self.volume_keyframe_list.currentRowChanged.connect(self.volume_keyframe_selected)
        self.speed_ramp_time=QDoubleSpinBox(); self.speed_ramp_time.setRange(0,864000); self.speed_ramp_time.setDecimals(2); self.speed_ramp_time.setSingleStep(.1); self.speed_ramp_time.setSuffix(' s')
        self.speed_ramp_value=QDoubleSpinBox(); self.speed_ramp_value.setRange(.25,4); self.speed_ramp_value.setDecimals(2); self.speed_ramp_value.setSingleStep(.25); self.speed_ramp_value.setSuffix('×')
        self.speed_ramp_list=QListWidget(); self.speed_ramp_list.setMaximumHeight(96); self.speed_ramp_list.setMinimumHeight(42)
        self.speed_ramp_set_button=button('Speed-Punkt setzen / aktualisieren',self.set_speed_ramp)
        self.speed_ramp_remove_button=button('Speed-Punkt löschen',self.remove_speed_ramp)
        self.speed_ramp_list.currentRowChanged.connect(self.speed_ramp_selected)
        self.beat_analyze_button=button('Beats analysieren',self.start_beat_analysis)
        self.beat_clear_button=button('Beats löschen',self.clear_beat_markers)
        self.beat_status=label('Keine Beat-Marker vorhanden.','muted'); self.beat_status.setWordWrap(True)
        self.text_cut_button=button('Textschnitt starten',self.start_text_based_cut)
        self.text_cut_status=label('Pausen und Füllwörter werden lokal entfernt.','muted'); self.text_cut_status.setWordWrap(True)
        self.auto_cut_button=button('Beat-/Szenen-Auto-Cut',self.start_auto_cut)
        self.auto_cut_status=label('Noch kein automatischer Schnitt.','muted'); self.auto_cut_status.setWordWrap(True)
        self.multicam_sync_button=button('Multi-Kamera synchronisieren',self.sync_multicam)
        self.multicam_switch_button=button('Als aktive Kamera verwenden',self.switch_multicam_angle)
        self.multicam_status=label('Keine Multi-Kamera-Gruppe.','muted'); self.multicam_status.setWordWrap(True)
        def configure_form(layout):
            layout.setVerticalSpacing(5); layout.setHorizontalSpacing(9)
            layout.setLabelAlignment(Qt.AlignLeft|Qt.AlignVCenter)
            layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
            return layout

        clip_form=configure_form(QFormLayout())
        for name,widget in [('Spur',self.track_combo),('Position',self.position),('Quellstart',self.start),('Quellende',self.end)]: clip_form.addRow(name,widget)
        timing_form=configure_form(QFormLayout())
        for name,widget in [('Geschwindigkeit',self.speed),('Freeze-Frame',self.freeze_enabled),('Freeze-Dauer',self.freeze_duration),('Reverse',self.reverse_clip),('Einblenden',self.fade_in),('Ausblenden',self.fade_out),('Lautstärke',self.volume)]: timing_form.addRow(name,widget)
        text_form=configure_form(QFormLayout())
        color_row=QHBoxLayout(); color_row.setContentsMargins(0,0,0,0); color_row.setSpacing(5); color_row.addWidget(self.text_color,1); color_row.addWidget(self.text_palette_button)
        for name,widget in [('Text',self.text_value),('Textgröße',self.text_size),('Schrift',self.text_font)]: text_form.addRow(name,widget)
        text_form.addRow('Textfarbe',color_row)
        for name,widget in [('Text X',self.text_x),('Text Y',self.text_y)]: text_form.addRow(name,widget)
        text_style_form=configure_form(QFormLayout())
        style_row=QHBoxLayout(); style_row.setContentsMargins(0,0,0,0); style_row.addWidget(self.text_bold); style_row.addWidget(self.text_italic); style_row.addStretch(); text_style_form.addRow('Schnitt',style_row)
        text_style_form.addRow('Kontur',self.text_outline_width); text_style_form.addRow('Konturfarbe',self.text_outline_color)
        text_style_form.addRow('Schatten',self.text_shadow_size); text_style_form.addRow('Schattenfarbe',self.text_shadow_color)
        text_style_form.addRow('Hintergrund',self.text_background_enabled); text_style_form.addRow('Hintergrundfarbe',self.text_background_color)
        text_style_form.addRow('Hintergrunddeckkraft',self.text_background_opacity); text_style_form.addRow('Hintergrundrand',self.text_background_padding)
        preset_row=QHBoxLayout(); preset_row.setContentsMargins(0,0,0,0); preset_row.addWidget(self.text_style_preset,1); preset_row.addWidget(self.text_style_apply_button)
        text_style_form.addRow('Stilvorlage',preset_row)
        text_style_form.addRow('Animation',self.text_animation); text_style_form.addRow('Anim.-Dauer',self.text_animation_duration)
        clip_section=inspector_section('CLIP · POSITION',True); clip_section.addLayout(clip_form)
        timing_section=inspector_section('TIMING · AUDIO-BASIS',True); timing_section.addLayout(timing_form)
        text_section=inspector_section('TEXT · INHALT UND POSITION',True); text_section.addLayout(text_form)
        text_style_section=inspector_section('TEXT · STIL UND ANIMATION',False,True); text_style_section.addLayout(text_style_form)
        transform_form=configure_form(QFormLayout())
        transform_form.addRow('Zoom',self.transform_scale)
        transform_form.addRow('Bild X',self.transform_x); transform_form.addRow('Bild Y',self.transform_y)
        transform_form.addRow('Rotation',self.rotation)
        transform_form.addRow('Crop links',self.crop_left); transform_form.addRow('Crop oben',self.crop_top)
        transform_form.addRow('Crop rechts',self.crop_right); transform_form.addRow('Crop unten',self.crop_bottom)
        flip_row=QHBoxLayout(); flip_row.setContentsMargins(0,0,0,0); flip_row.addWidget(self.flip_horizontal); flip_row.addWidget(self.flip_vertical); flip_row.addStretch()
        transform_form.addRow('Spiegeln',flip_row)
        transform_section=inspector_section('BILD · TRANSFORMATION',True); transform_section.addLayout(transform_form)
        audio_form=configure_form(QFormLayout()); audio_form.addRow('Rauschunterdrückung',self.audio_noise_reduction)
        audio_form.addRow('EQ Tiefen',self.audio_eq_low); audio_form.addRow('EQ Mitten',self.audio_eq_mid); audio_form.addRow('EQ Höhen',self.audio_eq_high)
        audio_form.addRow('Kompressor',self.audio_compressor_enabled); audio_form.addRow('Kompressor-Schwelle',self.audio_compressor_threshold); audio_form.addRow('Kompressor-Ratio',self.audio_compressor_ratio)
        audio_form.addRow('Audio-Ducking',self.audio_ducking); audio_form.addRow('Sprachisolierung',self.audio_voice_isolation); audio_form.addRow('Kanäle',self.audio_channel_mode); audio_form.addRow('Panorama',self.audio_pan)
        audio_form.addRow('Clip-Loudness',self.audio_normalize); audio_form.addRow('Zielpegel',self.audio_normalize_target)
        beat_buttons=QHBoxLayout(); beat_buttons.setContentsMargins(0,0,0,0); beat_buttons.addWidget(self.beat_analyze_button,1); beat_buttons.addWidget(self.beat_clear_button,1)
        audio_form.addRow('Beat-Sync',beat_buttons); audio_form.addRow('',self.beat_status)
        audio_form.addRow('Textschnitt',self.text_cut_button); audio_form.addRow('',self.text_cut_status)
        auto_cut_row=QHBoxLayout(); auto_cut_row.setContentsMargins(0,0,0,0); auto_cut_row.addWidget(self.auto_cut_button,1)
        audio_form.addRow('Auto-Cut',auto_cut_row); audio_form.addRow('',self.auto_cut_status)
        multicam_row=QHBoxLayout(); multicam_row.setContentsMargins(0,0,0,0); multicam_row.addWidget(self.multicam_sync_button,1); multicam_row.addWidget(self.multicam_switch_button,1)
        audio_form.addRow('Multi-Kamera',multicam_row); audio_form.addRow('',self.multicam_status)
        audio_section=inspector_section('AUDIO · MIX UND SMART TOOLS',False,True); audio_section.addLayout(audio_form)
        color_form=configure_form(QFormLayout()); color_form.addRow('Helligkeit',self.brightness); color_form.addRow('Kontrast',self.contrast); color_form.addRow('Sättigung',self.saturation); color_form.addRow('Filter',self.filter_preset)
        effect_preset_row=QHBoxLayout(); effect_preset_row.setContentsMargins(0,0,0,0); effect_preset_row.addWidget(self.effect_preset,1); effect_preset_row.addWidget(self.effect_preset_apply_button); color_form.addRow('Effekt-Preset',effect_preset_row)
        lut_row=QHBoxLayout(); lut_row.setContentsMargins(0,0,0,0); lut_row.addWidget(self.lut_path,1); lut_row.addWidget(self.lut_browse_button); color_form.addRow('LUT',lut_row)
        color_section=inspector_section('FARBE · KORREKTUR',True); color_section.addLayout(color_form)
        grading_form=configure_form(QFormLayout()); grading_form.addRow('Belichtung',self.color_exposure); grading_form.addRow('Temperatur',self.color_temperature); grading_form.addRow('Tönung',self.color_tint); grading_form.addRow('Vibrance',self.color_vibrance)
        for title,wheel in (('Lift / Schatten','lift'),('Gamma / Mitten','gamma'),('Gain / Lichter','gain')):
            row=QHBoxLayout(); row.setContentsMargins(0,0,0,0)
            for channel,title_channel in (('r','R'),('g','G'),('b','B')):
                spin=self.color_wheel_spins[f'color_{wheel}_{channel}']; spin.setToolTip(f'{title} · {title_channel}')
                row.addWidget(spin,1)
            grading_form.addRow(title,row)
        grading_section=inspector_section('FARBE · 3-WEGE-GRADING',False,True); grading_section.addLayout(grading_form)
        effects_form=configure_form(QFormLayout()); effects_form.addRow('Deckkraft',self.opacity); effects_form.addRow('Unschärfe',self.blur); effects_form.addRow('Schärfe',self.sharpen); effects_form.addRow('Stabilisierung',self.stabilization); effects_form.addRow('Greenscreen',self.chroma_key_enabled); effects_form.addRow('Key-Farbe',self.chroma_key_color); effects_form.addRow('Ähnlichkeit',self.chroma_key_similarity); effects_form.addRow('Weichheit',self.chroma_key_blend)
        effects_section=inspector_section('EFFEKTE · VIDEO',True); effects_section.addLayout(effects_form)
        mask_form=configure_form(QFormLayout()); mask_form.addRow('Maskentyp',self.mask_type); mask_form.addRow('Maske X',self.mask_x); mask_form.addRow('Maske Y',self.mask_y); mask_form.addRow('Maskenbreite',self.mask_width); mask_form.addRow('Maskenhöhe',self.mask_height); mask_form.addRow('Maskenweichheit',self.mask_feather)
        mask_points_row=QHBoxLayout(); mask_points_row.setContentsMargins(0,0,0,0); mask_points_row.addWidget(self.mask_points,1); mask_points_row.addWidget(self.mask_points_apply); mask_form.addRow('Bezier-Punkte',mask_points_row)
        mask_section=inspector_section('MASKEN · ROTOSKOPIE',False,True); mask_section.addLayout(mask_form)
        mask_path_form=configure_form(QFormLayout()); mask_path_form.addRow('Rotoskopie-Zeit',self.mask_path_time)
        mask_path_buttons=QHBoxLayout(); mask_path_buttons.setContentsMargins(0,0,0,0); mask_path_buttons.addWidget(self.mask_path_set_button,1); mask_path_buttons.addWidget(self.mask_path_remove_button,1)
        mask_section.addLayout(mask_path_form); mask_section.addLayout(mask_path_buttons); mask_section.addWidget(self.mask_path_list)
        ai_form=configure_form(QFormLayout())
        background_buttons=QHBoxLayout(); background_buttons.setContentsMargins(0,0,0,0); background_buttons.addWidget(self.background_remove_button,1); background_buttons.addWidget(self.background_clear_button,1)
        tracking_buttons=QHBoxLayout(); tracking_buttons.setContentsMargins(0,0,0,0); tracking_buttons.addWidget(self.track_motion_button,1); tracking_buttons.addWidget(self.clear_tracking_button,1)
        tracking_buttons.addWidget(self.mask_track_button,1)
        auto_reframe_buttons=QHBoxLayout(); auto_reframe_buttons.setContentsMargins(0,0,0,0); auto_reframe_buttons.addWidget(self.auto_reframe_button,1); auto_reframe_buttons.addWidget(self.auto_reframe_clear_button,1)
        ai_form.addRow('Hintergrund',background_buttons); ai_form.addRow('',self.background_removal_enabled); ai_form.addRow('',self.background_remove_status)
        ai_form.addRow('Tracking',tracking_buttons); ai_form.addRow('',self.tracking_status); ai_form.addRow('Objekt entfernen',self.object_removal_enabled)
        ai_form.addRow('Auto-Reframe',self.auto_reframe_format); ai_form.addRow('',self.auto_reframe_enabled)
        ai_form.addRow('',auto_reframe_buttons); ai_form.addRow('',self.auto_reframe_status)
        ai_section=inspector_section('KI-WERKZEUGE · LOKAL',False,True); ai_section.addLayout(ai_form)
        transition_form=configure_form(QFormLayout()); transition_form.addRow('Übergang',self.transition_type); transition_form.addRow('Dauer',self.transition_duration)
        transition_section=inspector_section('ÜBERGÄNGE',False,True); transition_section.addLayout(transition_form)
        keyframe_section=inspector_section('ANIMATION · KEYFRAMES UND SPEED-RAMPING',False,True)
        keyframe_form=configure_form(QFormLayout()); keyframe_form.addRow('Zeit im Clip',self.keyframe_time); keyframe_form.addRow('Kurve',self.keyframe_curve); keyframe_section.addLayout(keyframe_form)
        keyframe_buttons=QHBoxLayout(); keyframe_buttons.setContentsMargins(0,0,0,0); keyframe_buttons.addWidget(self.keyframe_set_button,1); keyframe_buttons.addWidget(self.keyframe_remove_button,1)
        keyframe_section.addLayout(keyframe_buttons)
        keyframe_section.addWidget(self.keyframe_list)
        graph_form=configure_form(QFormLayout()); graph_form.addRow('Kurve anzeigen',self.keyframe_graph_property); keyframe_section.addLayout(graph_form); keyframe_section.addWidget(self.keyframe_graph)
        volume_keyframe_form=configure_form(QFormLayout()); volume_keyframe_form.addRow('Zeit im Clip',self.volume_keyframe_time); volume_keyframe_form.addRow('Kurve',self.volume_keyframe_curve); keyframe_section.addLayout(volume_keyframe_form)
        volume_keyframe_buttons=QHBoxLayout(); volume_keyframe_buttons.setContentsMargins(0,0,0,0); volume_keyframe_buttons.addWidget(self.volume_keyframe_set_button,1); volume_keyframe_buttons.addWidget(self.volume_keyframe_remove_button,1)
        keyframe_section.addLayout(volume_keyframe_buttons)
        keyframe_section.addWidget(self.volume_keyframe_list)
        speed_ramp_form=configure_form(QFormLayout()); speed_ramp_form.addRow('Quellzeit',self.speed_ramp_time); speed_ramp_form.addRow('Geschwindigkeit',self.speed_ramp_value); keyframe_section.addLayout(speed_ramp_form)
        speed_ramp_buttons=QHBoxLayout(); speed_ramp_buttons.setContentsMargins(0,0,0,0); speed_ramp_buttons.addWidget(self.speed_ramp_set_button,1); speed_ramp_buttons.addWidget(self.speed_ramp_remove_button,1)
        keyframe_section.addLayout(speed_ramp_buttons)
        keyframe_section.addWidget(self.speed_ramp_list)
        actions_section=inspector_section('AKTIONEN',True)
        actions_section.addWidget(button('Bild zurücksetzen',self.reset_transform)); actions_section.addWidget(button('Übernehmen',self.apply_properties,True)); actions_section.addWidget(button('Audio aus Video extrahieren',self.extract_audio))
        hint=label('Rechtsklick = Aktionen · Mitte ziehen = verschieben · Ränder = kürzen\nShift = ohne Einrasten · Strg-Klick = Mehrfachauswahl · Leertaste = Play/Pause','subtle'); hint.setWordWrap(True); il.addWidget(hint); il.addStretch()
        top.addWidget(inspector); top.setSizes([310,760,360]); top.setStretchFactor(0,0); top.setStretchFactor(1,1); top.setStretchFactor(2,0); vertical.addWidget(top)
        bottom,bl=panel(); self.timeline_panel=bottom; bottom.setObjectName('timelinePanel'); bottom.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Ignored); bl.setContentsMargins(7,7,7,7); bl.setSpacing(4)
        timeline_toolbar=QFrame(); self.timeline_toolbar=timeline_toolbar; timeline_toolbar.setObjectName('timelineToolbar')
        bar=QHBoxLayout(timeline_toolbar); bar.setContentsMargins(6,3,6,3); bar.setSpacing(3)
        bar.addWidget(label('TIMELINE','heading')); bar.addSpacing(2); bar.addWidget(timeline_separator())

        # Keep the primary editing actions visible, but give them enough
        # hierarchy that the toolbar reads as a toolset instead of a glyph
        # soup. Less frequent actions live in the two popup groups below.
        undo_button=timeline_tool_button('↶','Rückgängig · Strg+Z',self.undo,'edit-undo')
        redo_button=timeline_tool_button('↷','Wiederholen · Strg+Shift+Z',self.redo,'edit-redo')
        split_button=timeline_tool_button('✂','Am Abspielkopf teilen · Strg+B',self.split,'edit-cut')
        remove_button=timeline_tool_button('⌫','Auswahl entfernen · Entf',self.remove,'edit-delete',object_name='timelineToolDanger')
        copy_button=timeline_tool_button('⧉','Auswahl kopieren · Strg+C',self.copy_selection,'edit-copy')
        paste_button=timeline_tool_button('⎘','Einfügen · Strg+V',self.paste_selection,'edit-paste')
        insert_button=timeline_tool_button('↳','Insert einfügen · Strg+Shift+V',self.insert_selection,'insert-object')
        overwrite_button=timeline_tool_button('▣','Overwrite einfügen',self.overwrite_selection,'document-save-as')

        trim_menu=QMenu(self); trim_menu.setTitle('Professionelle Trim-Werkzeuge')
        trim_menu.addAction('Ripple-In zum Abspielkopf · Q',self.ripple_trim_in)
        trim_menu.addAction('Ripple-Out zum Abspielkopf · W',self.ripple_trim_out)
        trim_menu.addSeparator()
        trim_menu.addAction('Roll-Schnitt zum Abspielkopf · R',self.roll_to_playhead)
        trim_menu.addSeparator()
        trim_menu.addAction('Slide links · Alt+←',lambda:self.slide_selected(-1))
        trim_menu.addAction('Slide rechts · Alt+→',lambda:self.slide_selected(1))
        trim_menu.addAction('Slip links · Umschalt+Alt+←',lambda:self.slip_selected(-1))
        trim_menu.addAction('Slip rechts · Umschalt+Alt+→',lambda:self.slip_selected(1))
        trim_button=timeline_menu_button('⟷','Professionelle Trim-Werkzeuge',trim_menu,'edit-cut')

        marker_menu=QMenu(self); marker_menu.setTitle('Marker')
        marker_menu.addAction('Marker hinzufügen',lambda:self.add_marker('marker'))
        marker_menu.addAction('Kapitel hinzufügen',lambda:self.add_marker('chapter'))
        marker_menu.addSeparator(); marker_menu.addAction('Kapitel exportieren …',self.export_chapters)
        marker_button=timeline_menu_button('⚑','Marker oder Kapitel hinzufügen',marker_menu,'bookmark-new')

        add_menu=QMenu(self); add_menu.setTitle('Timeline-Element hinzufügen')
        add_menu.addAction('Text hinzufügen',self.add_text)
        add_menu.addAction('Adjustment-Layer hinzufügen',self.add_adjustment_layer)
        add_menu.addSeparator()
        add_menu.addAction('Untertitel importieren (SRT/VTT)',self.import_subtitle_dialog)
        add_menu.addAction('Automatische Untertitel …',self.automatic_subtitle_dialog)
        add_button=timeline_menu_button('+','Element hinzufügen',add_menu,'list-add')

        more_menu=QMenu(self); more_menu.setTitle('Weitere Timeline-Aktionen')
        more_menu.addAction('Duplizieren · Strg+D',self.duplicate_selection)
        more_menu.addAction('Ripple löschen · Strg+Shift+Entf',self.ripple_delete)
        more_menu.addSeparator()
        more_menu.addAction('Gruppieren · Strg+G',self.group_selection)
        more_menu.addAction('Gruppe lösen · Strg+Shift+G',self.ungroup_selection)
        more_menu.addAction('Compound-Clip erstellen',self.create_compound)
        more_menu.addAction('Compound-Clip auflösen',self.dissolve_compound)
        more_menu.addSeparator()
        more_menu.addAction('Multi-Kamera synchronisieren',self.sync_multicam)
        more_menu.addAction('Audio-Sync für Auswahl',self.sync_audio_selection)
        more_menu.addAction('Aktive Kamera wechseln',self.switch_multicam_angle)
        more_menu.addAction('Attribute kopieren · Ctrl+Alt+C',self.copy_attributes)
        more_menu.addAction('Attribute einfügen · Ctrl+Alt+V',self.paste_attributes)
        more_menu.addAction('Keyframes kopieren · Ctrl+Alt+K',self.copy_keyframes)
        more_menu.addAction('Keyframes einfügen · Ctrl+Alt+Shift+K',self.paste_keyframes)
        more_menu.addSeparator()
        more_menu.addAction('Lücken auf aktueller Spur schließen',self.close_selected_track_gaps)
        more_menu.addAction('Standbild am Abspielkopf einfügen',self.add_freeze_frame)
        more_menu.addAction('Aktuelles Bild als PNG speichern',self.start_frame_capture)
        more_menu.addAction('Textschnitt · Pausen/Füllwörter',self.start_text_based_cut)
        more_menu.addAction('Beat-/Szenen-Auto-Cut',self.start_auto_cut)
        more_button=timeline_menu_button('⋯','Weitere Timeline-Aktionen',more_menu,'view-more')

        bar.addWidget(timeline_tool_group('VERLAUF',[undo_button,redo_button]))
        bar.addWidget(timeline_tool_group('TRIMMEN',[trim_button]))
        bar.addWidget(timeline_tool_group('BEARBEITEN',[split_button,remove_button,copy_button,paste_button]))
        bar.addWidget(timeline_tool_group('EINFÜGEN',[insert_button,overwrite_button]))
        bar.addWidget(timeline_tool_group('MARKER',[marker_button]))
        bar.addWidget(timeline_tool_group('ADD',[add_button]))
        self.subtitle_export_button=timeline_tool_button('⇩','Untertitel exportieren',theme_name='document-export')
        self.subtitle_export_button.clicked.connect(self.export_subtitles)
        bar.addWidget(timeline_tool_group('EXPORT',[self.subtitle_export_button]))
        bar.addWidget(timeline_tool_group('MEHR',[more_button]))
        bar.addStretch()
        self.snap_box=timeline_tool_button('⌁','Einrasten ein/aus',toggle=True,theme_name='snap-to-grid')
        self.snap_box.setChecked(True); self.snap_box.toggled.connect(lambda b:setattr(self.timeline,'snap',b))
        bar.addWidget(timeline_tool_group('AUSRICHTEN',[self.snap_box]))
        self.total=label('','muted'); self.total.setObjectName('timelineTotal'); bar.addWidget(self.total); bl.addWidget(timeline_toolbar)

        timeline_meta=QFrame(); timeline_meta.setObjectName('timelineMeta')
        row=QHBoxLayout(timeline_meta); row.setContentsMargins(6,0,6,4); row.setSpacing(6)
        self.autosave_label=label('Autosave bereit','muted'); row.addWidget(self.autosave_label); row.addStretch()
        self.video_tracks=QSpinBox(); self.video_tracks.setRange(1,10); self.video_tracks.setValue(2); self.video_tracks.setToolTip('Anzahl der Video-Spuren'); self.video_tracks.valueChanged.connect(self.track_counts_changed)
        self.audio_tracks=QSpinBox(); self.audio_tracks.setRange(1,10); self.audio_tracks.setValue(2); self.audio_tracks.setToolTip('Anzahl der Audio-Spuren'); self.audio_tracks.valueChanged.connect(self.track_counts_changed)
        row.addWidget(timeline_track_group(self.video_tracks,self.audio_tracks))
        fit_button=timeline_tool_button('⛶','Timeline einpassen',self.fit_timeline,'view-fullscreen')
        zoom_icon=timeline_icon_label('⌕','Timeline-Zoom')
        self.zoom_slider=QSlider(Qt.Horizontal); self.zoom_slider.setToolTip('Timeline-Zoom'); self.zoom_slider.setRange(2,200); self.zoom_slider.setValue(60); self.zoom_slider.setFixedWidth(120); self.zoom_slider.valueChanged.connect(self.zoom)
        row.addWidget(timeline_tool_group('ANSICHT',[fit_button,zoom_icon,self.zoom_slider])); bl.addWidget(timeline_meta)
        self.timeline=Timeline(); self.timeline.library_catalog={item.item_id:item for item in list(library_items())+list(self.custom_library_items)}
        self.timeline.selection_changed.connect(self.timeline_selection_changed); self.timeline.seek.connect(self.set_playhead)
        self.timeline.context_requested.connect(self.show_context_menu)
        self.timeline.track_context_requested.connect(self.show_track_context_menu)
        self.timeline.marker_context_requested.connect(self.show_marker_context_menu)
        self.timeline.commit.connect(self.commit_drag); self.timeline.add_asset.connect(self.drop_asset); self.timeline.library_action.connect(self.handle_library_drop); self.timeline.delete_selected.connect(self.remove)
        self.timeline.track_mute_requested.connect(self.toggle_track_mute); self.timeline.track_lock_requested.connect(self.toggle_track_lock)
        self.timeline.zoom_request.connect(lambda n:self.zoom_slider.setValue(self.zoom_slider.value()+n*5))
        self.timeline.gesture_done.connect(self.resume_autosave)
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setWidget(self.timeline); bl.addWidget(self.scroll)
        self.timeline.pan_request.connect(self.pan_timeline)
        self.text_value.editingFinished.connect(self.apply_properties)
        self.text_color.editingFinished.connect(self.apply_properties)
        for field in (self.position,self.start,self.end,self.speed,self.freeze_duration,self.fade_in,self.fade_out,self.volume,
                      self.audio_noise_reduction,self.audio_eq_low,self.audio_eq_mid,self.audio_eq_high,self.audio_compressor_threshold,
                      self.audio_compressor_ratio,self.audio_ducking,self.audio_pan,self.audio_normalize_target,self.text_size,self.text_x,self.text_y,
                      self.text_outline_width,self.text_outline_color,self.text_shadow_size,self.text_shadow_color,self.text_background_color,
                      self.text_background_opacity,self.text_background_padding,self.text_animation_duration,
                      self.transform_scale,self.transform_x,self.transform_y,self.rotation,self.crop_left,self.crop_top,self.crop_right,self.crop_bottom,
                      self.brightness,self.contrast,self.saturation,self.lut_path,self.opacity,self.blur,self.sharpen,self.stabilization,
                      self.audio_voice_isolation,
                      self.chroma_key_color,self.chroma_key_similarity,self.chroma_key_blend,
                      self.mask_x,self.mask_y,self.mask_width,self.mask_height,self.mask_feather):
            field.editingFinished.connect(self.apply_properties)
        self.flip_horizontal.clicked.connect(self.apply_properties); self.flip_vertical.clicked.connect(self.apply_properties)
        self.freeze_enabled.clicked.connect(self.apply_properties); self.reverse_clip.clicked.connect(self.apply_properties)
        self.audio_compressor_enabled.clicked.connect(self.apply_properties)
        self.audio_normalize.clicked.connect(self.apply_properties)
        self.audio_voice_isolation.editingFinished.connect(self.apply_properties)
        self.background_removal_enabled.clicked.connect(self.apply_properties)
        self.object_removal_enabled.clicked.connect(self.apply_properties)
        self.audio_channel_mode.activated.connect(lambda *_: self.apply_properties())
        self.text_bold.clicked.connect(self.apply_properties); self.text_italic.clicked.connect(self.apply_properties)
        self.text_background_enabled.clicked.connect(self.apply_properties)
        self.text_font.activated.connect(lambda *_: self.apply_properties())
        self.text_animation.activated.connect(lambda *_: self.apply_properties())
        self.filter_preset.activated.connect(lambda *_: self.apply_properties()); self.chroma_key_enabled.clicked.connect(self.apply_properties)
        self.mask_type.activated.connect(lambda *_: self.apply_properties())
        self.transition_type.activated.connect(lambda *_: self.apply_properties()); self.transition_duration.editingFinished.connect(self.apply_properties)
        vertical.addWidget(bottom); vertical.setStretchFactor(0,5); vertical.setStretchFactor(1,3); vertical.setChildrenCollapsible(False); vertical.setSizes([560,340]); outer.addWidget(vertical,1); self.setCentralWidget(root)
        self.refresh_media()
        self.update_source_monitor_controls()
        self.set_edit_mode()
        self.apply_workspace_preset()

    def error(self,message): self.present_error(message)

    def update_project_identity(self):
        """Keep the compact header in sync with the active project."""
        if not hasattr(self,'project_title_label'):
            return
        name=Path(self.project_path).stem if self.project_path else 'Neues Projekt'
        self.project_title_label.setText(name)
        self.project_meta_label.setText('Gespeichert' if self.project_path else 'Lokales Projekt')
        saved=self.autosave_revision==self.revision and self.last_autosave is not None
        self.autosave_pill.setText('● Wiederherstellbar' if self.dirty and saved else '● Sicherung folgt' if self.dirty else '● Gespeichert' if self.project_path else '● Bereit')
        self.autosave_pill.setToolTip('Autosave ist eine Wiederherstellungskopie. Strg+S speichert deine Projektdatei.')
        self.autosave_pill.setProperty('dirty',bool(self.dirty))
        self.autosave_pill.style().unpolish(self.autosave_pill); self.autosave_pill.style().polish(self.autosave_pill); self.autosave_pill.update()

    def set_edit_mode(self, *_):
        """Switch between a calm beginner inspector and the full toolset."""
        if not hasattr(self, 'edit_mode_combo'):
            return
        mode=self.edit_mode_combo.currentData() or 'simple'
        self.edit_mode=str(mode)
        for entry in getattr(self, 'inspector_sections', []):
            entry['section'].setVisible(self.edit_mode == 'pro' or not entry['advanced'])
        is_pro=self.edit_mode == 'pro'
        if hasattr(self,'edit_mode_badge'):
            self.edit_mode_badge.setText('ALLE WERKZEUGE' if is_pro else 'KERNWERKZEUGE')
            self.edit_mode_badge.setProperty('pro',is_pro)
            self.edit_mode_badge.style().unpolish(self.edit_mode_badge); self.edit_mode_badge.style().polish(self.edit_mode_badge)
        self.edit_mode_combo.setProperty('pro',is_pro)
        self.edit_mode_combo.style().unpolish(self.edit_mode_combo); self.edit_mode_combo.style().polish(self.edit_mode_combo)
        if hasattr(self, 'statusBar'):
            self.statusBar().showMessage(
                'Einfach-Modus · Kernwerkzeuge sichtbar, Profi-Bereiche ausgeblendet' if self.edit_mode == 'simple'
                else 'Pro-Modus · vollständiger Inspector mit Audio, KI, Masken und Keyframes', 3000)

    def apply_workspace_preset(self, *_):
        """Apply a task-oriented layout without creating another editor mode."""
        if not hasattr(self, 'workspace_preset_combo') or not hasattr(self, 'top'):
            return
        preset=self.workspace_preset_combo.currentData() or 'edit'
        self.workspace_preset=str(preset)
        if self.focus_mode:
            return
        sizes={
            'edit':[300, 820, 350],
            'shorts':[230, 930, 290],
            'audio':[250, 650, 470],
            'color':[190, 820, 480],
            'captions':[280, 720, 430],
        }.get(preset,[300,820,350])
        self.top.setSizes(sizes)
        if hasattr(self, 'vertical'):
            self.vertical.setSizes([560,340] if preset != 'audio' else [500,400])
        labels={'edit':'Schnitt-Layout','shorts':'Shorts-Layout','audio':'Audio-Layout','color':'Farb-Layout','captions':'Untertitel-Layout'}
        if hasattr(self, 'statusBar'):
            self.statusBar().showMessage(f'{labels.get(preset,"Arbeitsbereich")} aktiviert.',2500)

    def toggle_focus_mode(self):
        """Give the preview and timeline the full width with one safe toggle."""
        if not hasattr(self, 'top'):
            return
        self.focus_mode=not self.focus_mode
        if self.focus_mode: self._normal_sizes=self.top.sizes()
        self.media_panel.setVisible(not self.focus_mode)
        self.inspector_panel.setVisible(not self.focus_mode)
        self.focus_button.setText('Fokus schließen' if self.focus_mode else 'Fokus')
        self.focus_button.setToolTip('Seitenbereiche wieder einblenden · Strg+Shift+F' if self.focus_mode else 'Vorschau und Timeline vergrößern · Strg+Shift+F')
        if self.focus_mode:
            self.top.setSizes([0, 1200, 0])
            self.statusBar().showMessage('Fokusmodus · Vorschau und Timeline maximiert',3000)
        else:
            if self._normal_sizes: self.top.setSizes(self._normal_sizes)
            else: self.apply_workspace_preset()
            self.statusBar().showMessage('Fokusmodus beendet · Arbeitsbereich wiederhergestellt',3000)

    def update_context_toolbar(self):
        if not hasattr(self, 'context_toolbar'):
            return
        clip=self.current_clip()
        available=clip is not None and not self.worker and not self.selection_locked()
        self.context_toolbar.setVisible(bool(clip))
        for action in (self.context_split_button,self.context_duplicate_button,self.context_reset_button,self.context_delete_button):
            action.setEnabled(available)
        self.context_reset_button.setEnabled(bool(available and len(self.selection)==1 and clip.kind=='video'))
        self.context_reset_button.setProperty('disabledReason','Wähle genau einen entsperrten Videoclip aus.')

    def set_media_view(self, *_):
        """Switch the media browser between visual cards and a compact list."""
        if not hasattr(self, 'media_view_combo') or not hasattr(self, 'media_list'):
            return
        list_view=self.media_view_combo.currentData() == 'list'
        self.media_list.setViewMode(QListWidget.ListMode if list_view else QListWidget.IconMode)
        self.media_list.setWrapping(not list_view)
        self.media_list.setSpacing(1 if list_view else 4)
        self.media_list.setUniformItemSizes(list_view)
        self.media_list.setIconSize(QSize(44,36) if list_view else QSize(124,72))
        self.media_list.setGridSize(QSize(0,0) if list_view else QSize(150,108))
        self.refresh_media()

    def toggle_asset_favorite(self):
        item=self.media_list.currentItem() if hasattr(self, 'media_list') else None
        if item is None:
            return self.statusBar().showMessage('Wähle zuerst ein Medium aus.',2500)
        index=item.data(MediaList.ASSET_INDEX_ROLE)
        uid=str(Path(self.assets[index].path).resolve())
        if uid in self.favorite_assets:
            self.favorite_assets.remove(uid); message='Favorit entfernt.'
        else:
            self.favorite_assets.add(uid); message='Medium als Favorit markiert.'
        self.refresh_media()
        self.statusBar().showMessage(message,2500)

    def update_media_favorite_button(self):
        if not hasattr(self, 'media_favorite_button'):
            return
        item=self.media_list.currentItem()
        uid=str(Path(self.assets[item.data(MediaList.ASSET_INDEX_ROLE)].path).resolve()) if item is not None else None
        favorite=uid in self.favorite_assets if uid is not None else False
        self.media_favorite_button.setEnabled(item is not None)
        self.media_favorite_button.setText('★' if favorite else '☆')
        self.media_favorite_button.setToolTip('Favorit entfernen' if favorite else 'Ausgewähltes Medium als Favorit markieren')
        self.media_favorite_button.setAccessibleName(self.media_favorite_button.toolTip())

    def update_color_button(self,color):
        self.text_palette_button.setStyleSheet(f'QPushButton {{ background: {color}; color: #101216; border: 1px solid #e9edf2; }} QPushButton:hover {{ background: {color}; }}')

    def choose_text_color(self):
        initial=QColor(self.text_color.text().strip())
        if not initial.isValid(): initial=QColor('#ffffff')
        color=QColorDialog.getColor(initial,self,'Textfarbe auswählen')
        if color.isValid():
            self.text_color.setText(color.name())
            self.update_color_button(color.name())
            if self.current_clip() and self.current_clip().kind=='text': self.apply_properties()

    def choose_lut(self):
        """Select a portable .cube/.3dl LUT for the current video clip."""
        path,_=QFileDialog.getOpenFileName(self,'LUT auswählen','',
                                           'LUT (*.cube *.3dl);;Alle Dateien (*)')
        if not path:
            return
        self.lut_path.setText(str(Path(path).resolve()))
        if self.current_clip() and self.current_clip().kind=='video':
            self.apply_properties()

    def pan_timeline(self,delta):
        bar=self.scroll.horizontalScrollBar()
        bar.setValue(bar.value()-int(delta))

    def work_area_bounds(self):
        """Return the effective export range or the complete timeline."""
        total=length(self.clips)
        start=0.0 if self.work_in is None else max(0.0,min(total,float(self.work_in)))
        end=total if self.work_out is None else max(0.0,min(total,float(self.work_out)))
        if end-start < MIN_CLIP:
            return 0.0,total
        return start,end

    def update_work_area_controls(self):
        if not hasattr(self,'work_range_label'):
            return
        total=length(self.clips)
        if self.work_in is None and self.work_out is None:
            self.work_range_label.setText('⌁ Timeline · gesamt')
            self.work_range_label.setToolTip('Strg+Alt+I/O setzen den Exportbereich.')
            return
        start,end=self.work_area_bounds()
        self.work_range_label.setText(f'⌁ Bereich · {start:.2f}–{end:.2f} s')
        self.work_range_label.setToolTip(f'{end-start:.2f} s von {total:.2f} s · Exportdialog kann diesen Bereich verwenden.')

    def set_work_in(self):
        if self.worker:
            return
        self.work_in=max(0.0,min(length(self.clips),float(self.playhead)))
        if self.work_out is not None and self.work_out <= self.work_in+MIN_CLIP:
            self.work_out=None
        self.update_work_area_controls()
        self.statusBar().showMessage(f'Arbeitsbereich-In: {self.work_in:.2f} s',2500)

    def set_work_out(self):
        if self.worker:
            return
        self.work_out=max(0.0,min(length(self.clips),float(self.playhead)))
        if self.work_in is not None and self.work_out <= self.work_in+MIN_CLIP:
            self.work_in=None
        self.update_work_area_controls()
        self.statusBar().showMessage(f'Arbeitsbereich-Out: {self.work_out:.2f} s',2500)

    def clear_work_area(self):
        self.work_in=None; self.work_out=None; self.update_work_area_controls()
        self.statusBar().showMessage('Arbeitsbereich gelöscht · gesamte Timeline aktiv',2500)

    def preview_size(self):
        """Return the actual preview size used for the current UI settings."""
        w,h=PRESETS[self.preset.currentText()]
        max_w,max_h=(640,360) if self.quick_preview_box.isChecked() else (854,480)
        ratio=min(max_w/w,max_h/h)
        return (max(2,int(w*ratio)//2*2),max(2,int(h*ratio)//2*2))

    def update_cache_status(self):
        if not hasattr(self,'cache_status'):
            return
        used=cache_size(self.cache_root)
        self.cache_status.setText(f'Cache {used/1024/1024:.0f} / {self.cache_limit_bytes/1024/1024:.0f} MB')
        self.cache_status.setToolTip(str(self.cache_root))

    def trim_cache(self, keep=()):
        result=prune_cache(self.cache_root,self.cache_limit_bytes,keep)
        self.update_cache_status()
        return result

    def clear_cache(self):
        if self.worker:
            return
        answer=QMessageBox.question(self,'Cache leeren',
            'Nur erzeugte Vorschauen, Poster und Wellenformen werden gelöscht. Projektdateien und Originalmedien bleiben erhalten.',
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if answer!=QMessageBox.Yes:
            return
        self.cancel_preview(wait=True); self.player.stop(); self.player.setSource(QUrl())
        self.preview_path=None; self.preview_signature=None; self.preview_revision=-1
        self.thumbnails.clear(); self.waveforms.clear()
        prune_cache(self.cache_root,0)
        self.prepare_visuals(self.assets); self.refresh(); self.update_cache_status()
        self.statusBar().showMessage('Cache geleert · Projekt und Originalmedien bleiben unverändert',5000)

    def proxy_profile_changed(self,*_):
        profile=self.proxy_profile_combo.currentData() or '360p'
        if profile not in PROXY_PROFILES:
            profile='360p'
        self.proxy_profile=profile
        if self.proxy_enabled and not self.worker:
            self.proxy_map={}; self.preview_queued=True
            if self._direct_preview_clips():
                self.activate_direct_preview(play=self.player.playbackState()==QMediaPlayer.PlayingState)
            self.start_proxy_generation()

    def preview_signature_for_current(self):
        return (self.revision, self.preview_size(), bool(self.proxy_enabled), self.proxy_profile,
                bool(self.gpu_preview_box.isChecked()),
                tuple(sorted(self.proxy_map.items())),
                tuple(sorted((track, tuple(sorted(state.items()))) for track,state in self.track_states.items())),
                tuple(sorted(self.master_mixer.items())))

    @staticmethod
    def _direct_value(value, expected, tolerance=1e-7):
        try:
            return abs(float(value)-float(expected)) <= tolerance
        except (TypeError, ValueError):
            return value == expected

    def _direct_clip_is_plain(self, clip):
        """Whether a clip can be decoded directly without a composition render."""
        if (not clip.enabled or clip.kind != 'video' or clip.source_type != 'video'
                or not clip.path or not Path(clip.path).is_file()):
            return False
        if not all((self._direct_value(getattr(clip, name), expected)
                    for name, expected in (
                        ('speed', 1.0), ('fade_in', 0.0), ('fade_out', 0.0),
                        ('video_scale', 1.0), ('video_x', .5), ('video_y', .5),
                        ('crop_left', 0.0), ('crop_top', 0.0), ('crop_right', 0.0), ('crop_bottom', 0.0),
                        ('rotation', 0.0), ('brightness', 0.0), ('contrast', 1.0), ('saturation', 1.0),
                        ('color_exposure', 0.0), ('color_temperature', 0.0), ('color_tint', 0.0),
                        ('color_vibrance', 0.0), ('color_lift_r', 0.0), ('color_lift_g', 0.0),
                        ('color_lift_b', 0.0), ('color_gamma_r', 0.0), ('color_gamma_g', 0.0),
                        ('color_gamma_b', 0.0), ('color_gain_r', 0.0), ('color_gain_g', 0.0),
                        ('color_gain_b', 0.0), ('opacity', 1.0), ('blur', 0.0), ('sharpen', 0.0),
                        ('stabilization', 0.0), ('chroma_key_similarity', .1),
                        ('chroma_key_blend', .1), ('mask_x', 0.0), ('mask_y', 0.0),
                        ('mask_width', 1.0), ('mask_height', 1.0), ('mask_feather', 0.0),
                        ('audio_noise_reduction', 0.0), ('audio_eq_low', 0.0),
                        ('audio_eq_mid', 0.0), ('audio_eq_high', 0.0),
                        ('audio_compressor_threshold', -18.0), ('audio_compressor_ratio', 4.0),
                        ('audio_ducking', 0.0), ('audio_voice_isolation', 0.0),
                        ('audio_pan', 0.0), ('audio_normalize_target', -16.0))
                    )):
            return False
        if (clip.freeze_frame or clip.reverse or clip.flip_horizontal or clip.flip_vertical
                or clip.chroma_key_enabled or clip.background_removal_enabled
                or clip.object_removal_enabled or clip.auto_reframe_enabled
                or clip.mask_type != 'none' or clip.effect_preset != 'clean'
                or clip.filter_preset != 'none' or clip.lut_path
                or clip.transition_type != 'none' or clip.transition_duration > 1e-7
                or clip.audio_compressor_enabled or clip.audio_normalize
                or clip.audio_channel_mode != 'stereo'
                or clip.speed_keyframes or clip.keyframes or clip.volume_keyframes
                or clip.tracking_keyframes or clip.auto_reframe_keyframes
                or clip.mask_points or clip.mask_path_keyframes):
            return False
        return True

    def _direct_audio_is_plain(self, clip):
        """Whether a detached audio clip can be represented by its source AV stream."""
        if (not clip.enabled or clip.kind != 'audio' or clip.source_type != 'audio'
                or not clip.path or not Path(clip.path).is_file()):
            return False
        if not all((self._direct_value(getattr(clip, name), expected)
                    for name, expected in (
                        ('speed', 1.0), ('volume', 1.0), ('fade_in', 0.0), ('fade_out', 0.0),
                        ('audio_noise_reduction', 0.0), ('audio_eq_low', 0.0),
                        ('audio_eq_mid', 0.0), ('audio_eq_high', 0.0),
                        ('audio_compressor_threshold', -18.0), ('audio_compressor_ratio', 4.0),
                        ('audio_ducking', 0.0), ('audio_voice_isolation', 0.0),
                        ('audio_pan', 0.0), ('audio_normalize_target', -16.0))
                    )):
            return False
        return not (clip.freeze_frame or clip.reverse or clip.audio_compressor_enabled
                    or clip.audio_normalize or clip.audio_channel_mode != 'stereo'
                    or clip.transition_type != 'none' or clip.transition_duration > 1e-7
                    or clip.speed_keyframes or clip.volume_keyframes)

    def _direct_extracted_audio_for_video(self, video):
        """Return unchanged extracted tracks that can be represented by source AV playback."""
        link_id=getattr(video,'linked_source_uid','') or video.uid
        candidates=[clip for clip in self.clips
                    if clip.kind == 'audio' and getattr(clip,'linked_source_uid','') == link_id]
        if not candidates:
            return None
        video_group=sorted((clip for clip in self.clips if clip.kind == 'video'
                            and (getattr(clip,'linked_source_uid','') or clip.uid) == link_id),
                           key=lambda clip:(clip.position,clip.uid))
        if not video_group or any(not self._direct_clip_is_plain(clip)
                                  or not self._direct_value(clip.volume,0.0)
                                  for clip in video_group):
            return None
        expected_position=video_group[0].position
        expected_source=video_group[0].start
        for clip in video_group:
            if (not self._direct_value(clip.position,expected_position)
                    or not self._direct_value(clip.start,expected_source)):
                return None
            expected_position=clip.finish; expected_source=clip.end
        if len({clip.track for clip in candidates}) != 1:
            return None
        state=self.track_states.get(candidates[0].track,{})
        if (state.get('muted') or not self._direct_value(state.get('volume',1.0),1.0)
                or not self._direct_value(state.get('pan',0.0),0.0)):
            return None
        ordered=tuple(sorted(candidates,key=lambda clip:(clip.position,clip.uid)))
        for audio in ordered:
            if not self._direct_audio_is_plain(audio):
                return None
        audio_position=video_group[0].position
        audio_source=video_group[0].start
        for audio in ordered:
            if (not self._direct_value(audio.position,audio_position)
                    or not self._direct_value(audio.start,audio_source)):
                return None
            audio_position=audio.finish; audio_source=audio.end
        if (not self._direct_value(audio_position,video_group[-1].finish)
                or not self._direct_value(audio_source,video_group[-1].end)):
            return None
        return ordered

    def _direct_preview_clips(self):
        """Return a contiguous, single-track timeline suitable for direct play."""
        if not self.clips:
            return ()
        video_clips=[clip for clip in self.clips if clip.kind == 'video']
        audio_clips=[clip for clip in self.clips if clip.kind == 'audio']
        if len(video_clips) != len([clip for clip in self.clips if clip.kind in ('video','audio')]):
            return ()
        tracks={clip.track for clip in video_clips}
        if len(tracks) != 1:
            return ()
        track=next(iter(tracks))
        if track <= 0:
            return ()
        state=self.track_states.get(track, {})
        if (state.get('muted') or state.get('solo')
                or not self._direct_value(state.get('volume',1.0),1.0)
                or not self._direct_value(state.get('pan',0.0),0.0)):
            return ()
        if (not self._direct_value(self.master_mixer.get('volume',1.0),1.0)
                or not self._direct_value(self.master_mixer.get('pan',0.0),0.0)
                or self.master_mixer.get('loudness_normalization',False)):
            return ()
        ordered=tuple(sorted(video_clips,key=lambda clip:(clip.position,clip.uid)))
        linked_audio=[]
        linked_groups=set()
        for clip in ordered:
            link_id=getattr(clip,'linked_source_uid','') or clip.uid
            candidates=[audio for audio in audio_clips
                        if getattr(audio,'linked_source_uid','') == link_id]
            if candidates:
                if link_id not in linked_groups:
                    linked=self._direct_extracted_audio_for_video(clip)
                    if linked is None:
                        return ()
                    linked_audio.extend(linked); linked_groups.add(link_id)
            elif clip.has_audio and not self._direct_value(clip.volume,1.0):
                return ()
        if {audio.uid for audio in audio_clips} != {audio.uid for audio in linked_audio}:
            return ()
        expected=0.0
        for clip in ordered:
            if abs(float(clip.position)-expected) > 1e-5 or not self._direct_clip_is_plain(clip):
                return ()
            expected=clip.finish
        return ordered

    def direct_preview_signature_for_current(self):
        return (self.revision, bool(self.proxy_enabled), self.proxy_profile,
                tuple(sorted(self.proxy_map.items())))

    def direct_preview_is_current(self):
        return bool(self.direct_preview and self.direct_preview_revision == self.revision
                    and self.direct_preview_signature == self.direct_preview_signature_for_current())

    def _direct_clip_at(self, position, clips=None):
        clips=clips or self._direct_preview_clips()
        if not clips:
            return None
        position=float(position)
        for index, clip in enumerate(clips):
            if clip.position-1e-6 <= position < clip.finish-1e-6:
                return index,clip
            if index == len(clips)-1 and clip.position-1e-6 <= position <= clip.finish+1e-6:
                return index,clip
        return None

    def _direct_source_path(self, clip):
        if self.proxy_enabled and clip.path:
            return self.proxy_map.get(str(Path(clip.path).resolve()),clip.path)
        return clip.path

    def _load_direct_clip_at_playhead(self, play=False):
        clips=self._direct_preview_clips()
        selected=self._direct_clip_at(self.playhead,clips)
        if selected is None:
            self.direct_clip_uid=None
            self.player.pause()
            return
        _,clip=selected
        self.direct_clip_uid=clip.uid
        source=self._direct_source_path(clip)
        source_time=clip.start+max(0.0,min(clip.length,self.playhead-clip.position))
        self.mode='timeline'; self.video_stack.setCurrentIndex(1)
        self.pending_seek=(round(source_time*1000),bool(play))
        url=QUrl.fromLocalFile(str(source))
        if self.player.source()==url:
            self.pending_seek=None
            self.player.setPosition(round(source_time*1000))
            if play:
                self.player.play()
        else:
            self.player.stop(); self.player.setSource(url)

    def activate_direct_preview(self, play=None):
        """Switch to instant source playback when the timeline needs no render."""
        clips=self._direct_preview_clips()
        if not clips:
            self.direct_preview=False; self.direct_preview_revision=-1
            self.direct_preview_signature=None; self.direct_clip_uid=None
            return False
        if play is None:
            play=self.player.playbackState()==QMediaPlayer.PlayingState
        self.direct_preview=True; self.direct_preview_revision=self.revision
        self.direct_preview_signature=self.direct_preview_signature_for_current()
        self.mode='timeline'; self.audio.setVolume(1); self.player.setPlaybackRate(1.0)
        linked=any(getattr(clip,'linked_source_uid','') for clip in self.clips)
        self.preview_status.setText(
            'DIRECT-SCHNITT · extrahierte Audiospur synchron · sofort abspielbar'
            if linked else 'DIRECT-SCHNITT · sofort abspielbar · keine Neu-Berechnung nötig')
        self._load_direct_clip_at_playhead(bool(play))
        return True

    def preview_is_current(self):
        if self.direct_preview_is_current():
            return True
        return bool(self.preview_path and self.preview_signature == self.preview_signature_for_current()
                    and Path(self.preview_path).is_file())

    def cancel_preview(self, wait=False):
        worker=self.preview_worker
        if not worker:
            return
        worker.cancel.set()
        if wait:
            worker.wait()
            if self.preview_worker is worker:
                self.preview_worker=None
            worker.deleteLater()

    def show_context_menu(self,uid,global_pos):
        if uid:
            self.select_clip(uid)
        clip=self.current_clip() if uid else None
        menu=QMenu(self)
        if clip:
            inspect=menu.addAction('Clip ausgewählt · Einstellungen rechts')
            inspect.setEnabled(False)
            menu.addSeparator()
            menu.addAction('Kopieren',self.copy_selection)
            menu.addAction('Attribute kopieren · Ctrl+Alt+C',self.copy_attributes)
            menu.addAction('Attribute einfügen · Ctrl+Alt+V',self.paste_attributes)
            if clip.kind == 'video' and clip.source_type != 'adjustment':
                menu.addAction('Keyframes kopieren · Ctrl+Alt+K',self.copy_keyframes)
                menu.addAction('Keyframes einfügen · Ctrl+Alt+Shift+K',self.paste_keyframes)
            menu.addAction('Duplizieren',self.duplicate_selection)
            menu.addAction('Insert einfügen',self.insert_selection)
            menu.addAction('Overwrite einfügen',self.overwrite_selection)
            menu.addAction('Ripple löschen',self.ripple_delete)
            if len(self.selected_clips()) >= 2:
                menu.addAction('Gruppieren',self.group_selection)
            if any(value.group_id for value in self.selected_clips()):
                menu.addAction('Gruppe lösen',self.ungroup_selection)
            if len(self.selected_clips()) >= 2:
                menu.addAction('Compound-Clip erstellen',self.create_compound)
            if any(value.compound_id for value in self.selected_clips()):
                menu.addAction('Compound-Clip auflösen',self.dissolve_compound)
            menu.addSeparator()
            if clip.kind!='text' and clip.source_type!='adjustment':
                menu.addAction('▶ Clip ansehen',self.source_preview)
            if clip.kind in ('video','audio') and clip.source_type in ('video','audio'):
                source_menu=menu.addMenu('Quellmonitor')
                source_menu.addAction('Quell-In setzen · I',self.set_source_in)
                source_menu.addAction('Quell-Out setzen · O',self.set_source_out)
                source_menu.addAction('Quellmarken löschen',self.clear_source_marks)
                source_menu.addSeparator()
                source_menu.addAction('Markierten Bereich als Insert einfügen',self.insert_source_range)
                source_menu.addAction('Markierten Bereich als Overwrite einfügen',self.overwrite_source_range)
            if clip.kind=='text':
                menu.addAction('Text im Inspector bearbeiten',self.focus_text_editor)
            menu.addAction('Am Abspielkopf teilen',self.split)
            if clip.kind in ('video','audio') and clip.source_type in ('video','audio'):
                trim_menu=menu.addMenu('Professionelle Trim-Werkzeuge')
                trim_menu.addAction('Ripple-In zum Abspielkopf · Q',self.ripple_trim_in)
                trim_menu.addAction('Ripple-Out zum Abspielkopf · W',self.ripple_trim_out)
                trim_menu.addAction('Roll-Schnitt zum Abspielkopf · R',self.roll_to_playhead)
                trim_menu.addSeparator()
                trim_menu.addAction('Slide links · Alt+←',lambda:self.slide_selected(-1))
                trim_menu.addAction('Slide rechts · Alt+→',lambda:self.slide_selected(1))
                trim_menu.addAction('Slip links · Umschalt+Alt+←',lambda:self.slip_selected(-1))
                trim_menu.addAction('Slip rechts · Umschalt+Alt+→',lambda:self.slip_selected(1))
            if clip.kind=='video' and clip.source_type in ('video','image'):
                ai_menu=menu.addMenu('KI-Werkzeuge')
                ai_menu.addAction('Hintergrund entfernen',self.start_background_removal)
                if clip.background_removed_path:
                    ai_menu.addAction('Freistellung deaktivieren',self.clear_background_removal)
                ai_menu.addSeparator()
                ai_menu.addAction('Motion-Tracking starten',self.start_motion_tracking).setEnabled(clip.source_type=='video')
                ai_menu.addAction('Bezier-Maske automatisch verfolgen',self.start_mask_tracking).setEnabled(
                    clip.source_type=='video' and clip.mask_type=='bezier' and len(clip.mask_points)>=3)
                if clip.tracking_keyframes:
                    ai_menu.addAction('Tracking löschen',self.clear_motion_tracking)
                ai_menu.addAction('Auto-Reframe analysieren',self.start_auto_reframe).setEnabled(clip.source_type=='video')
                if clip.auto_reframe_keyframes:
                    ai_menu.addAction('Auto-Reframe löschen',self.clear_auto_reframe)
                ai_menu.addAction('Objekt entfernen aktivieren',lambda:self.set_object_removal_enabled(True))
            if clip.kind in ('video','audio') and clip.has_audio and clip.source_type != 'adjustment':
                beat_menu=menu.addMenu('Beat-Sync')
                beat_menu.addAction('Beats analysieren',self.start_beat_analysis)
                beat_menu.addAction('Textbasierter Schnitt · Pausen/Füllwörter',self.start_text_based_cut)
                if clip.kind == 'video' and clip.source_type == 'video':
                    beat_menu.addAction('Beat-/Szenen-Auto-Cut',self.start_auto_cut)
                if any(marker.get('kind') == 'beat' for marker in self.markers):
                    beat_menu.addAction('Beat-Marker löschen',self.clear_beat_markers)
            if clip.multicam_group:
                menu.addAction('Als aktive Kamera verwenden',self.switch_multicam_angle)
            speed_menu=None
            if clip.kind in ('video','audio') and clip.source_type!='adjustment':
                speed_menu=menu.addMenu('Geschwindigkeit')
                for value in (.25,.5,1,2,4):
                    speed_menu.addAction(f'{value:g}×',lambda checked=False,v=value:self.set_speed(v))
            if clip.kind in ('video','audio') and clip.source_type!='adjustment':
                volume_menu=menu.addMenu('Lautstärke')
                volume_menu.addAction('100 %',lambda:self.set_volume(1.0))
                volume_menu.addAction('50 %',lambda:self.set_volume(.5))
                volume_menu.addAction('Stumm',lambda:self.set_volume(0.0))
            if clip.kind=='video' and clip.has_audio:
                menu.addAction('Audio aus Video extrahieren',self.extract_audio)
            if clip.kind=='video':
                menu.addAction('Bildtransformation zurücksetzen',self.reset_transform)
                menu.addAction('Standbild am Abspielkopf einfügen',self.add_freeze_frame)
                menu.addAction('Aktuelles Bild als PNG speichern',self.start_frame_capture)
            if clip.kind in ('video','audio') and clip.source_type!='adjustment':
                transition_menu=menu.addMenu('Übergang')
                transition_menu.addAction('Überblenden · 0,5 s',lambda:self.set_transition('dissolve',.5))
                transition_menu.addAction('Überblenden · 1,0 s',lambda:self.set_transition('dissolve',1.0))
                transition_menu.addSeparator()
                for title,kind in (('Slide links','slide_left'),('Slide rechts','slide_right'),
                                   ('Slide oben','slide_up'),('Slide unten','slide_down'),
                                   ('Wipe links','wipe_left'),('Wipe rechts','wipe_right'),
                                   ('Wipe oben','wipe_up'),('Wipe unten','wipe_down'),
                                   ('Zoom','zoom'),('Dip to Black','dip_to_black'),
                                   ('Fade to White','fade_white'),('Blur In','blur_in'),
                                   ('Circle Open','circle_open'),('Circle Close','circle_close'),
                                   ('Radial','radial'),('Pixelize','pixelize'),
                                   ('Smooth links','smooth_left'),('Smooth rechts','smooth_right'),
                                   ('Smooth oben','smooth_up'),('Smooth unten','smooth_down'),
                                   ('Cover links','cover_left'),('Cover rechts','cover_right'),
                                   ('Cover oben','cover_up'),('Cover unten','cover_down')):
                    transition_menu.addAction(f'{title} · 0,5 s',lambda checked=False,k=kind:self.set_transition(k,.5))
                transition_menu.addAction('Übergang entfernen',lambda:self.set_transition('none',0.0))
            menu.addSeparator()
            menu.addAction('Clip entfernen',self.remove)
        else:
            menu.addAction('Arbeitsbereich-In setzen · Ctrl+Alt+I',self.set_work_in)
            menu.addAction('Arbeitsbereich-Out setzen · Ctrl+Alt+O',self.set_work_out)
            menu.addAction('Arbeitsbereich löschen',self.clear_work_area)
            menu.addAction('Lücken auf aktueller Spur schließen',self.close_selected_track_gaps)
            menu.addSeparator()
            menu.addAction('+ Text',self.add_text)
            menu.addAction('+ Adjustment-Layer',self.add_adjustment_layer)
            menu.addAction('+ Untertitel importieren (SRT/VTT)',self.import_subtitle_dialog)
            menu.addAction('+ Automatische Untertitel',self.automatic_subtitle_dialog)
            menu.addAction('Medien importieren',self.import_dialog)
            menu.addAction('Bildsequenz importieren',self.import_sequence_dialog)
            menu.addAction('Ausgewähltes Medium am Spurende hinzufügen',self.add_selected_asset)
            menu.addAction('Einfügen',self.paste_selection)
            menu.addAction('Insert einfügen',self.insert_selection)
            menu.addAction('Overwrite einfügen',self.overwrite_selection)
        menu.exec(global_pos)

    def _marker_at_time(self, time):
        return min(self.markers, key=lambda value: abs(float(value['time'])-float(time)), default=None)

    def add_marker(self, kind='marker'):
        if self.worker or not self.clips:
            return self.statusBar().showMessage('Füge zuerst Medien zur Timeline hinzu.',3000)
        default = f"{'Kapitel' if kind == 'chapter' else 'Marker'} {sum(value['kind'] == kind for value in self.markers) + 1}"
        title = 'Kapitel hinzufügen' if kind == 'chapter' else 'Marker hinzufügen'
        text, ok = QInputDialog.getText(self, title, 'Name:', text=default)
        if not ok or not text.strip():
            return
        marker = {'time': round(self.playhead, 6), 'label': text.strip(), 'kind': kind}
        self.checkpoint()
        self.markers = normalize_markers([value for value in self.markers
                                          if not (value['kind'] == kind and abs(value['time']-self.playhead) <= .01)] + [marker],
                                         length(self.clips))
        self.changed()
        self.statusBar().showMessage(f"{('Kapitel' if kind == 'chapter' else 'Marker')} bei {self.playhead:.2f} s gesetzt.",3000)

    def edit_marker(self, time):
        marker = self._marker_at_time(time)
        if not marker or self.worker:
            return
        text, ok = QInputDialog.getText(self, 'Marker bearbeiten', 'Name:', text=marker['label'])
        if not ok or not text.strip():
            return
        self.checkpoint()
        self.markers = normalize_markers([dict(value, label=text.strip()) if value is marker else value for value in self.markers],
                                         length(self.clips))
        self.changed()

    def remove_marker(self, time):
        marker = self._marker_at_time(time)
        if not marker or self.worker:
            return
        self.checkpoint()
        self.markers = [value for value in self.markers if value is not marker]
        self.changed()
        self.statusBar().showMessage('Marker entfernt.',3000)

    def show_marker_context_menu(self, time, global_pos):
        marker = self._marker_at_time(time)
        if not marker:
            return
        menu = QMenu(self)
        menu.addAction(f"{marker['label']} · {marker['time']:.2f} s").setEnabled(False)
        menu.addAction('Zum Marker',lambda:self.set_playhead(marker['time']))
        menu.addAction('Bearbeiten …',lambda:self.edit_marker(marker['time']))
        menu.addAction('Löschen',lambda:self.remove_marker(marker['time']))
        menu.exec(global_pos)

    def focus_text_editor(self):
        self.text_value.setFocus()
        self.text_value.selectAll()

    def set_speed(self,value):
        clip=self.current_clip()
        if len(self.selection)>1:
            return self.statusBar().showMessage('Inspector-Änderungen sind bei Mehrfachauswahl deaktiviert.',3000)
        if not clip or clip.kind not in ('video','audio') or self.worker or not self.require_unlocked(clip):return
        candidate=replace(clip,speed=float(value))
        try:
            proposed=[candidate if c.uid==clip.uid else c for c in self.clips]
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed()
        except Exception as exc:
            self.error(exc)

    def set_volume(self,value):
        clip=self.current_clip()
        if len(self.selection)>1:
            return self.statusBar().showMessage('Inspector-Änderungen sind bei Mehrfachauswahl deaktiviert.',3000)
        if not clip or clip.kind not in ('video','audio') or self.worker or not self.require_unlocked(clip):return
        candidate=replace(clip,volume=float(value))
        self.checkpoint(); self.clips=[candidate if c.uid==clip.uid else c for c in self.clips]; self.changed()

    def set_transition(self,kind,duration):
        clip=self.current_clip()
        if len(self.selection)>1:
            return self.statusBar().showMessage('Inspector-Änderungen sind bei Mehrfachauswahl deaktiviert.',3000)
        if not clip or clip.kind not in ('video','audio') or self.worker or not self.require_unlocked(clip):return
        candidate=replace(clip,transition_type=kind,transition_duration=float(duration) if kind!='none' else 0.0)
        try:
            proposed=[candidate if item.uid==clip.uid else item for item in self.clips]
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed()
        except Exception as exc:
            self.error(exc)

    def current_clip(self): return next((c for c in self.clips if c.uid==self.current),None)

    def selected_clips(self):
        selected = set(self.selection or ([self.current] if self.current else []))
        return [clip for clip in self.clips if clip.uid in selected]

    def _clone_clip(self, clip, uid=None, group_id=None):
        return replace(clip, uid=uid or uuid.uuid4().hex,
                       group_id=clip.group_id if group_id is None else group_id,
                       keyframes=[dict(frame) for frame in clip.keyframes],
                       volume_keyframes=[dict(frame) for frame in clip.volume_keyframes],
                       speed_keyframes=[dict(frame) for frame in clip.speed_keyframes],
                       tracking_keyframes=[dict(point) for point in clip.tracking_keyframes],
                       auto_reframe_keyframes=[dict(point) for point in clip.auto_reframe_keyframes],
                       mask_points=[dict(point) for point in clip.mask_points],
                       mask_path_keyframes=[dict(frame, points=[dict(point) for point in frame.get('points', [])])
                                            for frame in clip.mask_path_keyframes],
                       source_paths=list(clip.source_paths))

    def set_selection(self, uids, anchor=None, expand_groups=False):
        previous_current=self.current
        available = {clip.uid: clip for clip in self.clips}
        result = []
        for uid in uids:
            if uid in available and uid not in result:
                result.append(uid)
        if expand_groups:
            groups = {available[uid].group_id for uid in result if available[uid].group_id}
            compounds = {available[uid].compound_id for uid in result if available[uid].compound_id}
            for clip in self.clips:
                if ((clip.group_id in groups and clip.group_id)
                        or (clip.compound_id in compounds and clip.compound_id)) and clip.uid not in result:
                    result.append(clip.uid)
        self.selection = result
        self.current = anchor if anchor in result else (result[-1] if result else None)
        if self.mode=='source' and self.current!=previous_current:
            self.player.pause(); self.pending_seek=None; self.player.setSource(QUrl()); self.mode='timeline'
            self.source_clip_uid=None; self.source_in=None; self.source_out=None
            self.video_stack.setCurrentIndex(0); self.placeholder.setText('Clip ausgewählt · „Clip ansehen“ startet die Quellvorschau.')
        self.fill_inspector()
        self.timeline.set_selection(self.selection, self.current)
        self.update_source_monitor_controls()

    def timeline_selection_changed(self, payload):
        if not isinstance(payload, (list, tuple)):
            return
        self.set_selection(list(payload), self.timeline.current, expand_groups=False)

    def select_all(self):
        if self.worker:
            return
        ids=[clip.uid for clip in self.clips]
        self.set_selection(ids, ids[-1] if ids else None)
        self.statusBar().showMessage(f'{len(ids)} Clips ausgewählt.',3000)

    def selection_locked(self):
        return any(self.track_locked(clip.track) for clip in self.selected_clips())

    def _inspector_controls(self):
        return (self.track_combo,self.position,self.start,self.end,self.speed,self.freeze_enabled,self.freeze_duration,self.reverse_clip,self.fade_in,self.fade_out,self.volume,
                self.text_value,self.text_size,self.text_color,self.text_palette_button,self.text_font,self.text_bold,self.text_italic,
                self.text_outline_width,self.text_outline_color,self.text_shadow_size,self.text_shadow_color,
                self.text_background_enabled,self.text_background_color,self.text_background_opacity,self.text_background_padding,
                self.text_animation,self.text_animation_duration,self.text_x,self.text_y,
                self.audio_noise_reduction,self.audio_eq_low,self.audio_eq_mid,self.audio_eq_high,self.audio_compressor_enabled,
                self.audio_compressor_threshold,self.audio_compressor_ratio,self.audio_ducking,self.audio_voice_isolation,self.audio_channel_mode,self.audio_pan,
                self.audio_normalize,self.audio_normalize_target,
                self.transform_scale,self.transform_x,self.transform_y,self.rotation,self.crop_left,self.crop_top,
                self.crop_right,self.crop_bottom,self.flip_horizontal,self.flip_vertical,self.brightness,self.contrast,
                self.saturation,self.filter_preset,self.effect_preset,self.effect_preset_apply_button,self.lut_path,self.lut_browse_button,self.opacity,self.blur,self.sharpen,self.stabilization,
                self.chroma_key_enabled,self.chroma_key_color,self.chroma_key_similarity,self.chroma_key_blend,
                self.background_removal_enabled,self.background_remove_button,self.background_clear_button,
                self.track_motion_button,self.mask_track_button,self.clear_tracking_button,self.object_removal_enabled,
                self.auto_reframe_enabled,self.auto_reframe_format,self.auto_reframe_button,self.auto_reframe_clear_button,
                self.mask_type,self.mask_x,self.mask_y,self.mask_width,self.mask_height,self.mask_feather,self.mask_points,
                self.mask_points_apply,self.mask_path_time,self.mask_path_list,self.mask_path_set_button,self.mask_path_remove_button,
                self.color_exposure,self.color_temperature,self.color_tint,self.color_vibrance,
                *self.color_wheel_spins.values(),
                self.keyframe_graph_property,self.keyframe_graph,
                self.beat_analyze_button,self.beat_clear_button,
                self.text_cut_button,self.auto_cut_button,self.multicam_sync_button,self.multicam_switch_button,
                self.transition_type,self.transition_duration,
                self.keyframe_time,self.keyframe_curve,self.keyframe_list,self.keyframe_set_button,self.keyframe_remove_button,
                self.volume_keyframe_time,self.volume_keyframe_curve,self.volume_keyframe_list,self.volume_keyframe_set_button,
                self.volume_keyframe_remove_button,self.speed_ramp_time,self.speed_ramp_value,self.speed_ramp_list,
                self.speed_ramp_set_button,self.speed_ramp_remove_button)

    def copy_selection(self):
        clips = self.selected_clips()
        if not clips:
            return self.statusBar().showMessage('Kein Clip ausgewählt.',3000)
        self.clipboard = [self._clone_clip(clip, uid=clip.uid) for clip in clips]
        self.statusBar().showMessage(f"{len(clips)} Clip{'s' if len(clips) != 1 else ''} kopiert.",3000)

    def copy_attributes(self):
        """Copy only editable look/audio attributes from the active clip."""
        clip=self.current_clip()
        if not clip:
            return self.statusBar().showMessage('Wähle zuerst einen Clip aus.',3000)
        if clip.kind == 'video':
            fields=VIDEO_ATTRIBUTE_FIELDS
        elif clip.kind == 'audio':
            fields=AUDIO_ATTRIBUTE_FIELDS
        elif clip.kind == 'text':
            fields=TEXT_ATTRIBUTE_FIELDS
        else:
            return self.statusBar().showMessage('Für diesen Clip gibt es keine Attribute.',3000)
        self.attribute_clipboard={
            'kind':clip.kind,
            'fields':{field:([dict(item) for item in getattr(clip,field)]
                             if isinstance(getattr(clip,field),list)
                             else getattr(clip,field)) for field in fields},
        }
        self.statusBar().showMessage('Clip-Attribute kopiert · Zielclip(s) auswählen und Einfügen ausführen.',4000)

    def paste_attributes(self):
        """Paste copied look/audio attributes onto the current selection."""
        if self.worker or not self.attribute_clipboard:
            return self.statusBar().showMessage('Keine Clip-Attribute kopiert.',3000)
        source_kind=self.attribute_clipboard.get('kind')
        targets=[clip for clip in self.selected_clips() if clip.kind == source_kind]
        if not targets:
            return self.statusBar().showMessage('Wähle mindestens einen Clip desselben Typs aus.',4000)
        if any(not self.require_unlocked(clip) for clip in targets):
            return
        fields=self.attribute_clipboard.get('fields',{})
        proposed=list(self.clips)
        for target in targets:
            values={field:([dict(item) for item in value] if isinstance(value,list) else value)
                    for field,value in fields.items() if hasattr(target,field)}
            candidate=replace(target,**values)
            proposed=[candidate if item.uid==target.uid else item for item in proposed]
        try:
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed(); self.fill_inspector()
            self.statusBar().showMessage(f'Attribute auf {len(targets)} Clip(s) angewendet.',3500)
        except Exception as exc:
            self.error(exc)

    def copy_keyframes(self):
        clip=self.current_clip()
        if not clip or clip.kind != 'video' or clip.source_type == 'adjustment':
            return self.statusBar().showMessage('Wähle einen normalen Videoclip für Keyframes aus.',3500)
        try:
            self.keyframe_clipboard=copy_keyframe_bundle(clip)
            self.statusBar().showMessage('Keyframes kopiert · Zielclip(s) auswählen und Keyframes einfügen.',4000)
        except Exception as exc:
            self.error(exc)

    def paste_keyframes(self):
        if self.worker or not self.keyframe_clipboard:
            return self.statusBar().showMessage('Keine Keyframes kopiert.',3000)
        targets=[clip for clip in self.selected_clips()
                 if clip.kind == 'video' and clip.source_type != 'adjustment']
        if not targets:
            return self.statusBar().showMessage('Wähle mindestens einen normalen Videoclip aus.',3500)
        if any(not self.require_unlocked(clip) for clip in targets):
            return
        try:
            proposed=list(self.clips)
            for target in targets:
                candidate=paste_keyframe_bundle(target,self.keyframe_clipboard)
                proposed=[candidate if item.uid==target.uid else item for item in proposed]
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed(); self.fill_inspector()
            self.statusBar().showMessage(f'Keyframes auf {len(targets)} Clip(s) angewendet.',3500)
        except Exception as exc:
            self.error(exc)

    def _clipboard_candidates(self, anchor):
        if not self.clipboard:
            return []
        minimum = min(clip.position for clip in self.clipboard)
        group_map = {}
        compound_map = {}
        multicam_map = {}
        candidates = []
        for clip in self.clipboard:
            track = clip.track
            if track not in self.tracks:
                compatible = [value for value in self.tracks if (value > 0) == (clip.kind in ('video','text'))]
                if not compatible:
                    raise ValueError('Für einen eingefügten Clip fehlt eine passende Spur.')
                track = min(compatible, key=abs)
            if self.track_locked(track):
                raise ValueError('Eine Zielspur ist gesperrt.')
            group_id = ''
            if clip.group_id:
                group_id = group_map.setdefault(clip.group_id, uuid.uuid4().hex)
            value = self._clone_clip(clip, group_id=group_id)
            compound_id = ''
            if clip.compound_id:
                compound_id = compound_map.setdefault(clip.compound_id, uuid.uuid4().hex)
            multicam_group = ''
            if clip.multicam_group:
                multicam_group = multicam_map.setdefault(clip.multicam_group, uuid.uuid4().hex)
            candidates.append(replace(value,compound_id=compound_id,multicam_group=multicam_group))
            candidates[-1] = replace(candidates[-1], position=max(0.0, anchor + clip.position - minimum), track=track)
        return candidates

    def _free_paste_candidates(self, candidates):
        """Shift a pasted group right until every target track is collision-free."""
        if not candidates:
            return []
        shift = 0.0
        for _ in range(200):
            proposed = [replace(clip, position=clip.position + shift) for clip in candidates]
            try:
                validate_timeline(self.clips + proposed, self.tracks)
                return proposed
            except ValueError:
                conflicts = []
                proposed_ids = {clip.uid for clip in proposed}
                for candidate in proposed:
                    for existing in self.clips:
                        if existing.track == candidate.track and existing.uid not in proposed_ids and candidate.position < existing.finish - 1e-7 and candidate.finish > existing.position + 1e-7:
                            conflicts.append(existing.finish - candidate.position)
                if not conflicts:
                    raise
                shift += max(conflicts)
        raise ValueError('Kein freier Platz für die eingefügten Clips gefunden.')

    def paste_selection(self, ripple=False, anchor=None):
        if self.worker:
            return
        if not self.clipboard:
            return self.statusBar().showMessage('Nichts kopiert.',3000)
        if anchor is None:
            anchor = self.playhead
        try:
            candidates = self._clipboard_candidates(max(0.0, float(anchor)))
            if ripple:
                return self._insert_candidates_ripple(candidates)
            candidates = self._free_paste_candidates(candidates)
            self.checkpoint(); self.clips.extend(candidates); self.selection=[clip.uid for clip in candidates]
            self.current=candidates[-1].uid if candidates else None; self.changed()
            self.statusBar().showMessage(f"{len(candidates)} Clip{'s' if len(candidates) != 1 else ''} eingefügt.",3000)
        except Exception as exc:
            self.error(exc)

    def insert_selection(self):
        """Insert the clipboard at the playhead and ripple later clips right."""
        if not self.clipboard:
            self.copy_selection()
        if self.clipboard:
            self.paste_selection(ripple=True)

    def overwrite_selection(self):
        """Overwrite the timeline at the playhead without shifting later clips."""
        if self.worker:
            return
        if not self.clipboard:
            self.copy_selection()
        if not self.clipboard:
            return
        try:
            candidates = self._clipboard_candidates(max(0.0, float(self.playhead)))
            self._overwrite_candidates(candidates)
        except Exception as exc:
            self.error(exc)

    def duplicate_selection(self):
        clips = self.selected_clips()
        if not clips:
            return self.statusBar().showMessage('Kein Clip ausgewählt.',3000)
        self.clipboard = [self._clone_clip(clip, uid=clip.uid) for clip in clips]
        anchor = max(clip.finish for clip in clips) + 0.05
        self.paste_selection(anchor=anchor)

    def group_selection(self):
        clips = self.selected_clips()
        if len(clips) < 2:
            return self.statusBar().showMessage('Wähle mindestens zwei Clips zum Gruppieren.',3000)
        if self.selection_locked():
            return self.statusBar().showMessage('Eine ausgewählte Spur ist gesperrt.',3000)
        group_id = uuid.uuid4().hex
        self.checkpoint(); selected = {clip.uid for clip in clips}
        self.clips = [replace(clip, group_id=group_id) if clip.uid in selected else clip for clip in self.clips]
        self.changed(); self.statusBar().showMessage(f'{len(clips)} Clips gruppiert.',3000)

    def ungroup_selection(self):
        clips = self.selected_clips()
        grouped = [clip for clip in clips if clip.group_id]
        if not grouped:
            return self.statusBar().showMessage('Die Auswahl enthält keine Gruppe.',3000)
        if self.selection_locked():
            return self.statusBar().showMessage('Eine ausgewählte Spur ist gesperrt.',3000)
        selected = {clip.uid for clip in grouped}
        self.checkpoint(); self.clips = [replace(clip, group_id='') if clip.uid in selected else clip for clip in self.clips]
        self.changed(); self.statusBar().showMessage('Gruppe gelöst.',3000)

    def create_compound(self):
        clips=self.selected_clips()
        if len(clips)<2:
            return self.statusBar().showMessage('Wähle mindestens zwei Clips für einen Compound-Clip.',3000)
        if self.selection_locked():
            return self.statusBar().showMessage('Eine ausgewählte Spur ist gesperrt.',3000)
        name,ok=QInputDialog.getText(self,'Compound-Clip erstellen','Name:',text='Compound Clip')
        if not ok or not name.strip():
            return
        compound_id=uuid.uuid4().hex; selected={clip.uid for clip in clips}; name=name.strip()[:48]
        self.checkpoint()
        self.clips=[replace(clip,compound_id=compound_id,compound_name=name) if clip.uid in selected else clip for clip in self.clips]
        self.changed(); self.statusBar().showMessage(f'Compound-Clip „{name}“ · {len(clips)} Clips gebündelt.',4000)

    def dissolve_compound(self):
        clips=self.selected_clips()
        compounds={clip.compound_id for clip in clips if clip.compound_id}
        if not compounds:
            return self.statusBar().showMessage('Die Auswahl enthält keinen Compound-Clip.',3000)
        if self.selection_locked():
            return self.statusBar().showMessage('Eine ausgewählte Spur ist gesperrt.',3000)
        self.checkpoint()
        self.clips=[replace(clip,compound_id='',compound_name='') if clip.compound_id in compounds else clip for clip in self.clips]
        self.changed(); self.statusBar().showMessage('Compound-Clip gelöst · Einzelclips bleiben erhalten.',4000)

    def sync_multicam(self):
        clips=self.selected_clips()
        if len(clips)<2 or any(clip.kind!='video' or clip.source_type!='video' for clip in clips):
            return self.error('Wähle mindestens zwei normale Videoclips für Multi-Kamera.')
        if any(not clip.has_audio for clip in clips):
            return self.error('Für die Multi-Kamera-Synchronisation braucht jeder Winkel eine Audiospur.')
        if len({clip.track for clip in clips}) != len(clips):
            return self.error('Lege jeden Kamera-Winkel auf eine eigene Videospur.')
        if any(self.track_locked(clip.track) for clip in clips):
            return self.error('Eine ausgewählte Kamera-Spur ist gesperrt.')
        selected=[replace(clip) for clip in clips]; group_id=uuid.uuid4().hex
        def operation(progress,cancel):
            offsets={}
            for index,clip in enumerate(selected):
                if cancel.is_set():
                    raise ExportCancelled()
                value=detect_audio_onset(clip.path,clip.start,clip.end,
                                         lambda item,base=index:progress(int((base+item/100)/len(selected)*100)),cancel)
                offsets[clip.uid]=float(value)
            target=max(clip.position+offsets[clip.uid] for clip in selected)
            return {'offsets':offsets,'target':target}
        self.start_job('Multi-Kamera wird per Audio synchronisiert …',operation,
                       lambda result:self.multicam_sync_done(result,selected,group_id))

    def multicam_sync_done(self,result,selected,group_id):
        if not result['ok']:
            return self.job_error(result)
        current={clip.uid:clip for clip in self.clips}
        if any(clip.uid not in current for clip in selected):
            return self.statusBar().showMessage('Eine Kamera wurde während der Analyse entfernt.',5000)
        offsets=result['value']['offsets']; target=float(result['value']['target'])
        try:
            proposed=[]
            for value in self.clips:
                match=next((clip for clip in selected if clip.uid==value.uid),None)
                if match is None:
                    proposed.append(value); continue
                position=max(0.0,round(target-float(offsets.get(value.uid,0.0)),6))
                angle=f'Angle {selected.index(match)+1}'
                proposed.append(replace(value,position=position,multicam_group=group_id,
                                        camera_angle=angle,multicam_active=selected.index(match)==0))
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.selection=[clip.uid for clip in selected]; self.current=selected[0].uid; self.changed()
            self.statusBar().showMessage(f'Multi-Kamera synchronisiert · {len(selected)} Winkel · {target:.2f} s Referenz.',6000)
        except Exception as exc:
            self.error(exc)

    def switch_multicam_angle(self):
        c=self.current_clip()
        if not c or not c.multicam_group:
            return self.error('Wähle einen Clip aus einer Multi-Kamera-Gruppe.')
        members=[value for value in self.clips if value.multicam_group==c.multicam_group]
        if any(self.track_locked(value.track) for value in members):
            return self.error('Eine Kamera-Spur ist gesperrt.')
        proposed=[replace(value,multicam_active=(value.uid==c.uid)) if value.multicam_group==c.multicam_group else value for value in self.clips]
        try:
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed(); self.fill_inspector()
            self.statusBar().showMessage(f'{c.camera_angle or "Kamera"} ist jetzt aktiv.',4000)
        except Exception as exc:
            self.error(exc)

    def sync_audio_selection(self):
        """Align any selected video/audio sources by their first audio onset."""
        clips=self.selected_clips()
        if len(clips)<2 or any(clip.kind not in ('video','audio') or clip.source_type not in ('video','audio')
                               for clip in clips):
            return self.error('Wähle mindestens zwei normale Video- oder Audioclips für Audio-Sync.')
        if any(not clip.has_audio for clip in clips):
            return self.error('Jeder ausgewählte Clip braucht eine Audiospur.')
        if any(self.track_locked(clip.track) for clip in clips):
            return self.error('Eine ausgewählte Spur ist gesperrt.')
        selected=[replace(clip) for clip in clips]
        def operation(progress,cancel):
            offsets={}
            for index,clip in enumerate(selected):
                if cancel.is_set():
                    raise ExportCancelled()
                offsets[clip.uid]=float(detect_audio_onset(
                    clip.path,clip.start,clip.end,
                    lambda value,base=index: progress(int((base+value/100)/len(selected)*100)),cancel))
            target=max(clip.position+offsets[clip.uid] for clip in selected)
            return {'offsets':offsets,'target':target}
        self.start_job('Audio-Sync wird analysiert …',operation,
                       lambda result:self.audio_sync_done(result,selected))

    def audio_sync_done(self,result,selected):
        if not result['ok']:
            return self.job_error(result)
        offsets=result['value']['offsets']; target=float(result['value']['target'])
        selected_ids={clip.uid for clip in selected}
        try:
            proposed=[replace(value,position=max(0.0,round(target-float(offsets.get(value.uid,0.0)),6)))
                      if value.uid in selected_ids else value for value in self.clips]
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed()
            self.statusBar().showMessage(f'Audio-Sync abgeschlossen · {len(selected)} Clips ausgerichtet.',5000)
        except Exception as exc:
            self.error(exc)

    def close_selected_track_gaps(self):
        clip=self.current_clip()
        if not clip or self.worker:
            return self.statusBar().showMessage('Wähle einen Clip auf der zu bereinigenden Spur aus.',3500)
        track=clip.track
        if self.track_locked(track):
            return self.statusBar().showMessage('Die Spur ist gesperrt.',3000)
        try:
            proposed,removed=close_track_gaps(self.clips,track)
            if removed < MIN_CLIP:
                return self.statusBar().showMessage('Auf dieser Spur gibt es keine schließbare Lücke.',3500)
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed()
            self.statusBar().showMessage(f'Lücken auf Spur geschlossen · {removed:.2f} s eingespart.',4000)
        except Exception as exc:
            self.error(exc)

    def add_freeze_frame(self):
        """Create a short still overlay from the current source frame."""
        clip=self.current_clip()
        if (not clip or clip.kind != 'video' or clip.source_type not in ('video','image')
                or self.worker):
            return self.statusBar().showMessage('Wähle einen normalen Videoclip für ein Standbild aus.',3500)
        if self.track_locked(clip.track):
            return self.statusBar().showMessage('Die ausgewählte Spur ist gesperrt.',3000)
        local=max(0.0,min(clip.length,self.playhead-clip.position))
        source_time=min(clip.duration-0.001,max(0.0,clip.start+local*clip.speed))
        frame_step=max(1.0/120.0,min(0.2,self._frame_step(clip)))
        source_end=min(clip.duration,source_time+frame_step)
        if source_end-source_time < MIN_CLIP:
            source_time=max(0.0,clip.duration-MIN_CLIP); source_end=clip.duration
        track=max((value for value in self.tracks if value>0),default=0)+1
        candidate=replace(clip,uid=uuid.uuid4().hex,start=source_time,end=source_end,
                          position=self.playhead,track=track,freeze_frame=True,
                          freeze_duration=2.0,transition_type='none',transition_duration=0.0,
                          keyframes=[],volume_keyframes=[],speed_keyframes=[],
                          tracking_keyframes=[],auto_reframe_keyframes=[],mask_path_keyframes=[])
        candidate=replace(candidate,compound_id='',compound_name='',multicam_group='',camera_angle='',multicam_active=True)
        try:
            proposed_tracks=list(self.tracks)+[track]
            validate_timeline(self.clips+[candidate],proposed_tracks)
            self.checkpoint(); self.tracks=proposed_tracks; self.track_states=normalize_track_states(self.track_states,self.tracks); self.track_names=normalize_track_names(self.track_names,self.tracks)
            self.track_names[track]='Standbild'
            self.clips.append(candidate); self.selection=[candidate.uid]; self.current=candidate.uid; self.changed()
            self.statusBar().showMessage('Standbild eingefügt · 2 Sekunden Freeze-Frame',4000)
        except Exception as exc:
            self.error(exc)

    def start_frame_capture(self):
        clip=self.current_clip()
        if not clip or clip.kind != 'video' or clip.source_type not in ('video','image') or self.worker:
            return self.statusBar().showMessage('Wähle einen normalen Videoclip für den Frame-Export aus.',3500)
        default_name='Frame-'+self._source_clock(self.playhead-clip.position).replace(':','-')+'.png'
        path,_=QFileDialog.getSaveFileName(self,'Aktuelles Bild speichern',default_name,'PNG (*.png)',options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        target=Path(path).resolve()
        if target.exists() and QMessageBox.question(self,'Bild ersetzen?',f'{target}\nüberschreiben?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            return
        local=max(0.0,min(clip.length,self.playhead-clip.position))
        source_time=min(clip.duration-0.001,max(0.0,clip.start+local*clip.speed))
        def operation(progress,cancel):
            if cancel.is_set():
                raise ExportCancelled()
            progress(15)
            value=capture_frame(clip.path,source_time,target)
            progress(100)
            return value
        self.start_job('Frame wird gespeichert …',operation,
                       lambda result:self.statusBar().showMessage(
                           f'Frame gespeichert: {result["value"]}',5000) if result['ok'] else self.job_error(result))

    def export_chapters(self):
        chapters=[marker for marker in self.markers if marker.get('kind') == 'chapter']
        if not chapters:
            return self.error('Setze zuerst mindestens einen Kapitelmarker.')
        default='Kapitel.ffmeta'
        if self.project_path:
            default=str(Path(self.project_path).with_suffix('.ffmeta'))
        path,_=QFileDialog.getSaveFileName(self,'Kapitel exportieren',default,'FFmpeg-Metadaten (*.ffmeta);;Alle Dateien (*)',options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        if not path.lower().endswith('.ffmeta'):
            path+='.ffmeta'
        target=Path(path).resolve()
        if target.exists() and QMessageBox.question(self,'Kapitel ersetzen?',f'{target}\nüberschreiben?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            return
        try:
            write_chapter_file(target,self.markers,length(self.clips))
            self.statusBar().showMessage(f'{len(chapters)} Kapitel exportiert · {target.name}',5000)
        except Exception as exc:
            self.error(exc)

    def _insert_candidates_ripple(self, candidates):
        if not candidates:
            return
        for track in {clip.track for clip in candidates}:
            if self.track_locked(track):
                raise ValueError('Eine Zielspur ist gesperrt.')
        insert_at=min(clip.position for clip in candidates)
        global_span=max(clip.finish for clip in candidates)-insert_at
        if any(self.track_locked(clip.track) for clip in self.clips if clip.finish > insert_at-1e-7):
            raise ValueError('Eine betroffene Spur ist gesperrt.')
        moved = []
        inserted_ids = {clip.uid for clip in candidates}
        for clip in self.clips:
            if clip.uid not in inserted_ids and clip.finish > insert_at-1e-7:
                moved.append(replace(clip, position=clip.position + global_span))
            else:
                moved.append(clip)
        proposed = moved + candidates
        validate_timeline(proposed, self.tracks)
        markers=[]
        for marker in self.markers:
            value=dict(marker)
            if value['time'] >= insert_at-1e-7:
                value['time'] += global_span
            markers.append(value)
        self.checkpoint(); self.clips=proposed; self.markers=normalize_markers(markers,length(proposed)); self.selection=[clip.uid for clip in candidates]; self.current=candidates[-1].uid; self.changed()
        self.statusBar().showMessage(f"{len(candidates)} Clip{'s' if len(candidates) != 1 else ''} mit Ripple eingefügt.",3000)

    def _overwrite_candidates(self, candidates):
        """Trim or remove covered clips, then place candidates at fixed time."""
        if not candidates:
            return
        for candidate in candidates:
            if self.track_locked(candidate.track):
                raise ValueError('Eine Zielspur ist gesperrt.')
        working=list(self.clips)
        candidates=sorted(candidates,key=lambda value:(value.track,value.position))
        candidate_ids={value.uid for value in candidates}

        def clear_transition(value):
            return replace(value, transition_type='none', transition_duration=0.0)

        for candidate in candidates:
            updated=[]
            for existing in working:
                if (existing.uid in candidate_ids or existing.track != candidate.track
                        or existing.finish <= candidate.position+1e-7
                        or existing.position >= candidate.finish-1e-7):
                    updated.append(existing)
                    continue
                if self.track_locked(existing.track):
                    raise ValueError('Eine betroffene Spur ist gesperrt.')
                left_span=candidate.position-existing.position
                right_span=existing.finish-candidate.finish
                if left_span >= MIN_CLIP-1e-7 and right_span >= MIN_CLIP-1e-7:
                    left,right=split_clip(existing,candidate.position)
                    right=edited_clip(right,'left',candidate.finish-right.position)
                    updated.extend([clear_transition(left),clear_transition(right)])
                elif left_span >= MIN_CLIP-1e-7:
                    updated.append(clear_transition(edited_clip(existing,'right',candidate.position-existing.finish)))
                elif right_span >= MIN_CLIP-1e-7:
                    updated.append(clear_transition(edited_clip(existing,'left',candidate.finish-existing.position)))
                # If neither side is long enough, the old clip is fully covered.
            working=updated
        proposed=working+candidates
        validate_timeline(proposed,self.tracks)
        self.checkpoint(); self.clips=proposed; self.selection=[clip.uid for clip in candidates]; self.current=candidates[-1].uid; self.changed()
        self.statusBar().showMessage(f"{len(candidates)} Clip{'s' if len(candidates) != 1 else ''} überschrieben.",3000)

    def ripple_insert(self):
        self.paste_selection(ripple=True)

    def ripple_delete(self):
        clips = self.selected_clips()
        if not clips:
            return self.statusBar().showMessage('Kein Clip ausgewählt.',3000)
        if self.selection_locked():
            return self.statusBar().showMessage('Eine ausgewählte Spur ist gesperrt.',3000)
        removed = {clip.uid for clip in clips}
        for clip in self.clips:
            if clip.uid in removed:
                continue
            shift = sum(value.length for value in clips if value.track == clip.track and value.finish <= clip.position + 1e-7)
            if shift and self.track_locked(clip.track):
                return self.statusBar().showMessage('Eine betroffene Spur ist gesperrt.',3000)
        proposed = []
        for clip in self.clips:
            if clip.uid in removed:
                continue
            shift = sum(value.length for value in clips if value.track == clip.track and value.finish <= clip.position + 1e-7)
            proposed.append(replace(clip, position=max(0.0, clip.position-shift)) if shift else clip)
        try:
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.selection=[]; self.current=None; self.changed()
            self.statusBar().showMessage(f'{len(clips)} Clips gelöscht und die Spur geschlossen.',3000)
        except Exception as exc:
            self.error(exc)

    def track_locked(self, track):
        return bool(self.track_states.get(track, {}).get('locked', False))

    def require_unlocked(self, clip):
        if clip is not None and self.track_locked(clip.track):
            self.statusBar().showMessage('Diese Spur ist gesperrt.',3000)
            return False
        return True

    def toggle_track_mute(self, track):
        if self.worker or track not in self.tracks:
            return
        self.checkpoint()
        state=self.track_states.setdefault(track, {'muted':False,'locked':False,'solo':False,'volume':1.0,'pan':0.0})
        state['muted']=not state.get('muted',False)
        self.track_states=normalize_track_states(self.track_states,self.tracks)
        self.changed()
        self.statusBar().showMessage(f"Spur {'stummgeschaltet' if state['muted'] else 'wieder hörbar'}: {('Video ' + str(track)) if track > 0 else ('Audio ' + str(-track))}",3000)

    def toggle_track_lock(self, track):
        if self.worker or track not in self.tracks:
            return
        self.checkpoint()
        state=self.track_states.setdefault(track, {'muted':False,'locked':False,'solo':False,'volume':1.0,'pan':0.0})
        state['locked']=not state.get('locked',False)
        self.track_states=normalize_track_states(self.track_states,self.tracks)
        self.changed()
        self.statusBar().showMessage(f"Spur {'gesperrt' if state['locked'] else 'entsperrt'}: {('Video ' + str(track)) if track > 0 else ('Audio ' + str(-track))}",3000)

    def open_mixer(self):
        if self.worker:
            return
        if self.mixer_dialog is not None:
            self.mixer_dialog.raise_(); self.mixer_dialog.activateWindow(); return
        self.mixer_dialog=MixerDialog(self)
        self.mixer_dialog.show()

    def command_definitions(self):
        """Return the high-value actions exposed by Ctrl+K."""
        return [
            ('Neues Projekt', 'Ctrl+N', self.new_project),
            ('Projekt öffnen', 'Ctrl+O', self.open_project),
            ('Projekt speichern', 'Ctrl+S', self.save),
            ('Medien importieren', 'Ctrl+I', self.import_dialog),
            ('Fokusmodus umschalten', 'Ctrl+Shift+F', self.toggle_focus_mode),
            ('Bearbeitungsverlauf öffnen', 'Ctrl+Alt+Z', self.show_history),
            ('Projekt-Statuszentrale öffnen', '—', self.show_project_status),
            ('Zum vorherigen Schnitt', '↑', lambda:self.jump_cut(-1)),
            ('Zum nächsten Schnitt', '↓', lambda:self.jump_cut(1)),
            ('Einfach-Modus aktivieren', '—', lambda: self.edit_mode_combo.setCurrentIndex(self.edit_mode_combo.findData('simple'))),
            ('Pro-Modus aktivieren', '—', lambda: self.edit_mode_combo.setCurrentIndex(self.edit_mode_combo.findData('pro'))),
            ('Schnitt-Layout aktivieren', '—', lambda: self.workspace_preset_combo.setCurrentIndex(self.workspace_preset_combo.findData('edit'))),
            ('Shorts-Layout aktivieren', '—', lambda: self.workspace_preset_combo.setCurrentIndex(self.workspace_preset_combo.findData('shorts'))),
            ('Audio-Layout aktivieren', '—', lambda: self.workspace_preset_combo.setCurrentIndex(self.workspace_preset_combo.findData('audio'))),
            ('Medien-Favorit umschalten', '—', self.toggle_asset_favorite),
            ('Timeline abspielen / pausieren', 'Leertaste', self.toggle_play),
            ('Vollbildvorschau öffnen / schließen', 'F11', self.toggle_cinema_preview),
            ('Clip teilen', 'S / Ctrl+B', self.split),
            ('Ripple-In zum Abspielkopf', 'Q', self.ripple_trim_in),
            ('Ripple-Out zum Abspielkopf', 'W', self.ripple_trim_out),
            ('Roll-Schnitt zum Abspielkopf', 'R', self.roll_to_playhead),
            ('Quell-In setzen', 'I', self.set_source_in),
            ('Quell-Out setzen', 'O', self.set_source_out),
            ('Quellmarken löschen', '—', self.clear_source_marks),
            ('Quellbereich als Insert einfügen', '—', self.insert_source_range),
            ('Quellbereich als Overwrite einfügen', '—', self.overwrite_source_range),
            ('Arbeitsbereich-In setzen', 'Ctrl+Alt+I', self.set_work_in),
            ('Arbeitsbereich-Out setzen', 'Ctrl+Alt+O', self.set_work_out),
            ('Arbeitsbereich löschen', '—', self.clear_work_area),
            ('Attribute kopieren', 'Ctrl+Alt+C', self.copy_attributes),
            ('Attribute einfügen', 'Ctrl+Alt+V', self.paste_attributes),
            ('Keyframes kopieren', 'Ctrl+Alt+K', self.copy_keyframes),
            ('Keyframes einfügen', 'Ctrl+Alt+Shift+K', self.paste_keyframes),
            ('Audio-Sync für Auswahl', '—', self.sync_audio_selection),
            ('Lücken auf aktueller Spur schließen', '—', self.close_selected_track_gaps),
            ('Standbild am Abspielkopf einfügen', '—', self.add_freeze_frame),
            ('Aktuelles Bild als PNG speichern', '—', self.start_frame_capture),
            ('Kapitel exportieren', '—', self.export_chapters),
            ('Slide-Schnitt links', 'Alt+←', lambda: self.slide_selected(-1)),
            ('Slide-Schnitt rechts', 'Alt+→', lambda: self.slide_selected(1)),
            ('Slip-Schnitt links', 'Umschalt+Alt+←', lambda: self.slip_selected(-1)),
            ('Slip-Schnitt rechts', 'Umschalt+Alt+→', lambda: self.slip_selected(1)),
            ('Auswahl entfernen', 'Entf', self.remove),
            ('Rückgängig', 'Ctrl+Z', self.undo),
            ('Wiederholen', 'Ctrl+Shift+Z', self.redo),
            ('Textclip hinzufügen', '+ Text', self.add_text),
            ('Adjustment-Layer hinzufügen', '+ Adjustment-Layer', self.add_adjustment_layer),
            ('Automatische Untertitel erstellen', '—', self.automatic_subtitle_dialog),
            ('Textbasierter Schnitt · Pausen und Füllwörter entfernen', '—', self.start_text_based_cut),
            ('KI-Hintergrund entfernen', '—', self.start_background_removal),
            ('Motion-Tracking starten', '—', self.start_motion_tracking),
            ('Bezier-Maske automatisch verfolgen', '—', self.start_mask_tracking),
            ('Tracking löschen', '—', self.clear_motion_tracking),
            ('KI-Auto-Reframe analysieren', '—', self.start_auto_reframe),
            ('Auto-Reframe löschen', '—', self.clear_auto_reframe),
            ('Beat-Sync analysieren', '—', self.start_beat_analysis),
            ('Beat-/Szenen-Auto-Cut', '—', self.start_auto_cut),
            ('Beat-Marker löschen', '—', self.clear_beat_markers),
            ('Objektentfernung aktivieren', '—', lambda: self.set_object_removal_enabled(True)),
            ('Compound-Clip erstellen', '—', self.create_compound),
            ('Compound-Clip auflösen', '—', self.dissolve_compound),
            ('Multi-Kamera synchronisieren', '—', self.sync_multicam),
            ('Als aktive Kamera verwenden', '—', self.switch_multicam_angle),
            ('Audio-Mixer öffnen', '—', self.open_mixer),
            ('Render-Queue öffnen', '—', self.show_render_queue),
            ('Timeline einpassen', '—', self.fit_timeline),
            ('Nach Updates suchen', '—', self.check_for_updates),
        ]

    def open_command_palette(self):
        if self.worker:
            return
        dialog=CommandPaletteDialog(self)
        dialog.exec()

    def toggle_cinema_preview(self):
        if self.worker:
            return
        if self.cinema_dialog is not None:
            self.cinema_dialog.close()
            return
        self.cinema_dialog=CinemaPreviewDialog(self)
        self.cinema_button.setText('× Cinema schließen')
        self.cinema_dialog.showFullScreen()

    def start_voiceover_recording(self):
        """Record a WAV through Qt Multimedia and place it at the playhead."""
        if self.worker or self.voiceover_recorder is not None:
            return
        path,_=QFileDialog.getSaveFileName(self,'Voice-over aufnehmen','voice-over.wav','WAV-Audio (*.wav)')
        if not path:
            return
        if not path.lower().endswith('.wav'):
            path += '.wav'
        target=Path(path).resolve()
        if target.exists() and QMessageBox.question(self,'Aufnahme ersetzen?',f'{target}\nüberschreiben?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            return
        dialog=QDialog(self); dialog.setWindowTitle('Voice-over aufnehmen'); dialog.setMinimumWidth(420)
        layout=QVBoxLayout(dialog); layout.setContentsMargins(18,16,18,16); layout.setSpacing(10)
        layout.addWidget(label('VOICE-OVER · AUFNAHME','heading'))
        status=label('Mikrofon wird gestartet …','muted'); status.setWordWrap(True); layout.addWidget(status)
        destination=label(str(target),'muted'); destination.setWordWrap(True); layout.addWidget(destination)
        timer_label=label('00:00','heading'); layout.addWidget(timer_label)
        actions=QHBoxLayout(); stop=QPushButton('Aufnahme stoppen'); close=QPushButton('Abbrechen'); actions.addStretch(); actions.addWidget(stop); actions.addWidget(close); layout.addLayout(actions)
        self.voiceover_dialog=dialog; self.voiceover_target=target; self.voiceover_started_at=0.0
        self.voiceover_capture=QMediaCaptureSession(self); self.voiceover_input=QAudioInput(self); self.voiceover_recorder=QMediaRecorder(self)
        self.voiceover_capture.setAudioInput(self.voiceover_input); self.voiceover_capture.setRecorder(self.voiceover_recorder)
        media_format=QMediaFormat(); media_format.setFileFormat(QMediaFormat.FileFormat.Wave); media_format.setAudioCodec(QMediaFormat.AudioCodec.Wave)
        self.voiceover_recorder.setMediaFormat(media_format); self.voiceover_recorder.setOutputLocation(QUrl.fromLocalFile(str(target)))
        self.voiceover_stopping=False
        clock=QTimer(dialog); clock.setInterval(100); clock.timeout.connect(lambda: timer_label.setText(f'{max(0,self.voiceover_recorder.duration()/1000):.1f} s')); clock.start()
        def recorder_error(*_):
            status.setText('Aufnahmefehler: '+self.voiceover_recorder.errorString())
            stop.setEnabled(False)
        def recorder_state(state):
            if state == QMediaRecorder.RecorderState.RecordingState:
                status.setText('Aufnahme läuft … sprich jetzt.'); stop.setEnabled(True)
            elif state == QMediaRecorder.RecorderState.StoppedState and self.voiceover_stopping:
                QTimer.singleShot(150,lambda:self.finish_voiceover_recording(dialog))
        self.voiceover_recorder.errorOccurred.connect(recorder_error)
        self.voiceover_recorder.recorderStateChanged.connect(recorder_state)
        stop.clicked.connect(lambda:(setattr(self,'voiceover_stopping',True),self.voiceover_recorder.stop()))
        close.clicked.connect(lambda:(setattr(self,'voiceover_stopping',True),self.voiceover_recorder.stop()))
        dialog.finished.connect(lambda *_: clock.stop())
        self.voiceover_stopping=True
        self.voiceover_recorder.record()
        dialog.show()

    def finish_voiceover_recording(self, dialog):
        target=self.voiceover_target
        recorder=self.voiceover_recorder
        actual=recorder.actualLocation().toLocalFile() if recorder is not None else ''
        if actual:
            target=Path(actual).resolve()
        self.voiceover_capture=None; self.voiceover_input=None; self.voiceover_recorder=None; self.voiceover_target=None; self.voiceover_stopping=False
        if dialog is not None:
            dialog.close(); dialog.deleteLater(); self.voiceover_dialog=None
        if not target or not target.is_file() or target.stat().st_size <= 44:
            return self.error('Die Voice-over-Aufnahme enthält keine Audiodaten.')
        self.import_voiceover_file(target)

    def import_voiceover_file(self, path):
        try:
            audio=import_clip(path)
            track_candidates=[track for track in sorted((value for value in self.tracks if value < 0), reverse=True)
                              if not self.track_locked(track)]
            position=max(0.0,min(self.playhead,length(self.clips)))
            candidate=None; chosen_tracks=list(self.tracks)
            for track in track_candidates:
                value=replace(audio,uid=uuid.uuid4().hex,position=position,track=track)
                try:
                    validate_timeline(self.clips+[value],self.tracks); candidate=value; break
                except ValueError:
                    continue
            if candidate is None:
                track=min(self.tracks+[0])-1; chosen_tracks.append(track)
                candidate=replace(audio,uid=uuid.uuid4().hex,position=position,track=track)
                validate_timeline(self.clips+[candidate],chosen_tracks)
            self.checkpoint(); self.tracks=chosen_tracks
            self.track_states=normalize_track_states(self.track_states,self.tracks); self.track_names=normalize_track_names(self.track_names,self.tracks)
            self.assets.append(audio); self.clips.append(candidate); self.selection=[candidate.uid]; self.current=candidate.uid
            self.prepare_visuals([audio]); self.changed()
            self.statusBar().showMessage(f'Voice-over aufgenommen · auf {self.default_track_name(candidate.track)} gelegt.',5000)
        except Exception as exc:
            self.error(exc)

    def snapshot(self):
        clone=lambda c: replace(c, keyframes=[dict(frame) for frame in c.keyframes],
                                volume_keyframes=[dict(frame) for frame in c.volume_keyframes],
                                speed_keyframes=[dict(frame) for frame in c.speed_keyframes],
                                tracking_keyframes=[dict(point) for point in c.tracking_keyframes],
                                auto_reframe_keyframes=[dict(point) for point in c.auto_reframe_keyframes],
                                mask_points=[dict(point) for point in c.mask_points],
                                mask_path_keyframes=[dict(frame, points=[dict(point) for point in frame.get('points', [])])
                                                     for frame in c.mask_path_keyframes],
                                source_paths=list(c.source_paths))
        return ([clone(c) for c in self.clips],
                list(self.tracks),self.current,
                {track:dict(state) for track,state in self.track_states.items()},
                dict(self.track_names),list(self.selection),[clone(c) for c in self.assets],
                [dict(marker) for marker in self.markers],dict(self.master_mixer))

    def checkpoint(self,title=None):
        caller=inspect.currentframe().f_back.f_code.co_name
        self.history.append(self.snapshot()); self.history=self.history[-80:]; self.future.clear()
        self.history_labels.append(title or HISTORY_NAMES.get(caller,'Bearbeitung'))
        self.history_labels=self.history_labels[-80:]; self.future_labels.clear()

    def changed(self):
        self.compare_released()
        direct_was_playing=self.direct_preview_is_current() and self.player.playbackState()==QMediaPlayer.PlayingState
        previous_preview_path=self.preview_path if self.preview_path and Path(self.preview_path).is_file() else None
        rendered_was_playing=bool(previous_preview_path and self.mode=='timeline'
                                  and self.player.playbackState()==QMediaPlayer.PlayingState)
        self.dirty=True; self.revision+=1; self.preview_revision=-1; self.preview_signature=None
        # Keep the last completed composition playable while the new revision
        # renders. An edit invalidates the render metadata, not the visible player.
        self.preview_queued=True; self.preview_play_requested=rendered_was_playing
        if self.preview_worker:
            # Cancel an obsolete render. The current frame stays visible while
            # the newer render is prepared in the background.
            self.preview_worker.cancel.set()
        self.transport_timer.stop(); self.transport_rate=0.0; self.transport_rate_pending=None
        self.direct_preview=False; self.direct_preview_revision=-1; self.direct_preview_signature=None
        self.player.setPlaybackRate(1.0); self.mode='timeline'; self.pending_seek=None
        self.source_clip_uid=None; self.source_in=None; self.source_out=None
        if previous_preview_path:
            self.video_stack.setCurrentIndex(1)
            self.preview_status.setText('Vorschau wird im Hintergrund aktualisiert …')
        else:
            self.player.pause()
            self.video_stack.setCurrentIndex(0)
            self.placeholder.setText('Timeline geändert\n\n▶ Timeline berechnet eine neue Vorschau.\n„Clip ansehen“ zeigt sofort die einzelne Quelle.')
            self.preview_status.setText('Vorschau wird nach kurzer Pause im Hintergrund berechnet …')
        self.setWindowTitle(f'Framecut {APP_VERSION} · '+(Path(self.project_path).stem if self.project_path else 'Neues Projekt')+' *')
        self.autosave_label.setText('Änderungen · Autosave folgt …'); self.autosave_timer.start()
        self.update_project_identity()
        self.update_source_monitor_controls()
        direct_ready=self.activate_direct_preview(play=direct_was_playing or rendered_was_playing)
        if direct_ready:
            self.preview_play_requested=False
            self.preview_queued=False
            self.live_preview_timer.stop()
        elif hasattr(self,'live_preview_box') and self.live_preview_box.isChecked() and self.clips:
            self.live_preview_timer.start()
        self.refresh()
        self.refresh_history()
        QTimer.singleShot(0,self.ensure_missing_proxies)

    def preset_changed(self,*_): self.changed()

    def undo(self):
        if self.history and not self.worker:
            self.future_labels.append(self.history_labels.pop() if self.history_labels else 'Bearbeitung')
            self.future.append(self.snapshot()); self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection,self.assets,self.markers,self.master_mixer=self.history.pop(); self.refresh_media(); self.prepare_visuals(self.assets); self.changed()

    def redo(self):
        if self.future and not self.worker:
            self.history_labels.append(self.future_labels.pop() if self.future_labels else 'Bearbeitung')
            self.history.append(self.snapshot()); self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection,self.assets,self.markers,self.master_mixer=self.future.pop(); self.refresh_media(); self.prepare_visuals(self.assets); self.changed()

    def refresh(self):
        self.timeline.refresh(self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection,self.markers)
        self.timeline.set_visuals(self.thumbnails,self.waveforms)
        self.video_tracks.blockSignals(True); self.video_tracks.setValue(len([t for t in self.tracks if t>0])); self.video_tracks.blockSignals(False)
        self.audio_tracks.blockSignals(True); self.audio_tracks.setValue(len([t for t in self.tracks if t<0])); self.audio_tracks.blockSignals(False)
        self.total.setText(f'{len(self.clips)} Clips · {length(self.clips):.1f} s')
        self.update_work_area_controls()
        self.playhead=max(0,self.playhead); self.timeline.set_playhead(self.playhead)
        self.update_time(); self.fill_inspector()
        if self.mixer_dialog is not None:
            self.mixer_dialog.refresh_from_editor()

    def refresh_keyframe_list(self, clip):
        self.keyframe_list.blockSignals(True)
        self.keyframe_list.clear()
        for keyframe in clip.keyframes:
            opacity=float(keyframe.get('opacity',clip.opacity))*100
            blur=float(keyframe.get('blur',clip.blur))
            curve=KEYFRAME_CURVE_LABELS.get(keyframe.get('curve','linear'),'Linear')
            item=QListWidgetItem(f"{float(keyframe['time']):.2f} s   ·   Zoom {float(keyframe['scale']):.2f}×   ·   X {float(keyframe['x'])*100:.0f}%   ·   Y {float(keyframe['y'])*100:.0f}%   ·   {float(keyframe['rotation']):.0f}°   ·   Deckkraft {opacity:.0f}%   ·   Unschärfe {blur:.1f}   ·   {curve}")
            item.setData(Qt.UserRole,float(keyframe['time']))
            self.keyframe_list.addItem(item)
        self.keyframe_list.clearSelection()
        self.keyframe_list.setCurrentRow(-1)
        self.keyframe_list.blockSignals(False)

    def refresh_keyframe_graph(self, clip):
        if not clip or clip.kind != 'video':
            self.keyframe_graph.set_data([], 1.0, 'scale', 1.0)
            return
        field=self.keyframe_graph_property.currentData() or 'scale'
        defaults={'scale':clip.video_scale,'x':clip.video_x,'y':clip.video_y,
                  'rotation':clip.rotation,'opacity':clip.opacity,'blur':clip.blur}
        self.keyframe_graph.set_data(clip.keyframes,clip.length,field,defaults[field])

    def graph_keyframe_drag_started(self):
        c=self.current_clip()
        if c and c.kind=='video' and not self.worker and self.require_unlocked(c):
            self.checkpoint()

    def graph_keyframe_moved(self,index,time,value):
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker or index < 0 or index >= len(c.keyframes) or not self.require_unlocked(c):
            return
        field=self.keyframe_graph_property.currentData() or 'scale'
        frames=[dict(frame) for frame in c.keyframes]
        frames[index]['time']=round(max(0.0,min(c.length,float(time))),6)
        frames[index][field]=round(float(value),6)
        frames.sort(key=lambda frame:float(frame.get('time',0.0)))
        candidate=replace(c,keyframes=frames)
        try:
            validate_timeline([candidate if item.uid==c.uid else item for item in self.clips],self.tracks)
            self.clips=[candidate if item.uid==c.uid else item for item in self.clips]
            self.dirty=True; self.revision+=1; self.preview_revision=-1; self.preview_signature=None; self.preview_queued=True
            self.timeline.refresh(self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection,self.markers)
        except Exception:
            self.keyframe_graph.set_data(c.keyframes,c.length,field,getattr(c,{'scale':'video_scale','x':'video_x','y':'video_y','rotation':'rotation','opacity':'opacity','blur':'blur'}[field]))

    def graph_keyframe_drag_finished(self):
        if self.current_clip() and not self.worker:
            self.changed()

    def graph_keyframe_selected(self,index):
        if 0 <= index < self.keyframe_list.count():
            self.keyframe_list.setCurrentRow(index)

    def graph_keyframe_added(self,time,value):
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker or not self.require_unlocked(c):
            return
        field=self.keyframe_graph_property.currentData() or 'scale'
        self.keyframe_time.setValue(time)
        controls={'scale':self.transform_scale,'x':self.transform_x,'y':self.transform_y,
                  'rotation':self.rotation,'opacity':self.opacity,'blur':self.blur}
        control=controls[field]
        control.setValue(value*100 if field in ('x','y','opacity') else value)
        self.set_keyframe()

    def parse_mask_points(self, text):
        points=[]
        for token in str(text).replace('\n',';').split(';'):
            token=token.strip()
            if not token:
                continue
            values=[value.strip() for value in token.split(',')]
            if len(values) != 2:
                raise ValueError('Bezier-Punkte müssen als x,y; x,y eingegeben werden.')
            try:
                x,y=(float(values[0])/100,float(values[1])/100)
            except ValueError as exc:
                raise ValueError('Bezier-Punkte enthalten keine gültigen Zahlen.') from exc
            if not 0 <= x <= 1 or not 0 <= y <= 1:
                raise ValueError('Bezier-Punkte müssen zwischen 0 und 100 % liegen.')
            points.append({'x':round(x,6),'y':round(y,6)})
        if len(points) < 3:
            raise ValueError('Eine Bezier-Maske braucht mindestens drei Punkte.')
        return points

    def mask_type_changed(self, *_):
        enabled=self.mask_type.currentData() == 'bezier' and bool(self.current_clip() and self.current_clip().kind == 'video')
        clip=self.current_clip()
        self.mask_track_button.setEnabled(enabled and bool(clip and clip.source_type == 'video') and not self.worker)
        for field in (self.mask_points,self.mask_points_apply,self.mask_path_time,self.mask_path_list,
                      self.mask_path_set_button,self.mask_path_remove_button):
            field.setEnabled(enabled and not self.worker)

    def apply_mask_points(self):
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker or not self.require_unlocked(c):
            return
        try:
            points=self.parse_mask_points(self.mask_points.text())
            candidate=replace(c,mask_type='bezier',mask_points=points)
            validate_timeline([candidate if item.uid==c.uid else item for item in self.clips],self.tracks)
            self.checkpoint(); self.clips=[candidate if item.uid==c.uid else item for item in self.clips]; self.changed()
        except Exception as exc:
            self.error(exc)

    def refresh_mask_path_list(self, clip):
        self.mask_path_list.blockSignals(True); self.mask_path_list.clear()
        if clip:
            self.mask_path_time.setMaximum(max(.01,clip.length))
            for frame in clip.mask_path_keyframes:
                item=QListWidgetItem(f"{float(frame['time']):.2f} s · {len(frame.get('points',[]))} Punkte")
                item.setData(Qt.UserRole,float(frame['time'])); self.mask_path_list.addItem(item)
        self.mask_path_list.setCurrentRow(-1); self.mask_path_list.blockSignals(False)

    def mask_path_selected(self,row):
        c=self.current_clip()
        if not c or row<0 or row>=len(c.mask_path_keyframes):
            return
        frame=c.mask_path_keyframes[row]; self.mask_path_time.setValue(float(frame['time']))
        self.mask_points.setText('; '.join(f"{float(point['x'])*100:.1f},{float(point['y'])*100:.1f}" for point in frame.get('points',[])))

    def set_mask_path_keyframe(self):
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker or not self.require_unlocked(c):
            return
        try:
            points=self.parse_mask_points(self.mask_points.text())
            time=round(max(0.0,min(c.length,self.mask_path_time.value())),6)
            frame={'time':time,'points':points}
            frames=[dict(item,points=[dict(point) for point in item.get('points',[])]) for item in c.mask_path_keyframes]
            replaced=False
            for index,item in enumerate(frames):
                if abs(float(item['time'])-time) <= .01:
                    frames[index]=frame; replaced=True; break
            if not replaced: frames.append(frame)
            frames.sort(key=lambda item:float(item['time']))
            candidate=replace(c,mask_type='bezier',mask_points=points,mask_path_keyframes=frames)
            validate_timeline([candidate if item.uid==c.uid else item for item in self.clips],self.tracks)
            self.checkpoint(); self.clips=[candidate if item.uid==c.uid else item for item in self.clips]; self.changed()
        except Exception as exc:
            self.error(exc)

    def remove_mask_path_keyframe(self):
        c=self.current_clip(); row=self.mask_path_list.currentRow()
        if not c or c.kind!='video' or self.worker or row<0 or row>=len(c.mask_path_keyframes) or not self.require_unlocked(c):
            return
        frames=[dict(item,points=[dict(point) for point in item.get('points',[])]) for index,item in enumerate(c.mask_path_keyframes) if index != row]
        candidate=replace(c,mask_path_keyframes=frames)
        self.checkpoint(); self.clips=[candidate if item.uid==c.uid else item for item in self.clips]; self.changed()

    def keyframe_selected(self,row):
        c=self.current_clip()
        if not c or c.kind!='video' or row<0:return
        item=self.keyframe_list.item(row)
        if item is None:return
        time=float(item.data(Qt.UserRole))
        frame=min(c.keyframes,key=lambda value:abs(float(value['time'])-time))
        self.keyframe_time.setValue(time)
        self.transform_scale.setValue(float(frame['scale']))
        self.transform_x.setValue(float(frame['x'])*100)
        self.transform_y.setValue(float(frame['y'])*100)
        self.rotation.setValue(float(frame['rotation']))
        self.opacity.setValue(float(frame.get('opacity',c.opacity))*100)
        self.blur.setValue(float(frame.get('blur',c.blur)))
        curve_index=self.keyframe_curve.findData(frame.get('curve','linear'))
        self.keyframe_curve.setCurrentIndex(curve_index if curve_index >= 0 else 0)

    def set_keyframe(self):
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker or not self.require_unlocked(c):return
        time=round(max(0.0,min(c.length,self.keyframe_time.value())),6)
        frame={'time':time,'scale':round(self.transform_scale.value(),6),
               'x':round(self.transform_x.value()/100,6),'y':round(self.transform_y.value()/100,6),
               'rotation':round(self.rotation.value(),6),
               'opacity':round(self.opacity.value()/100,6),
               'blur':round(self.blur.value(),6),
               'curve':self.keyframe_curve.currentData() or 'linear'}
        frames=[dict(value) for value in c.keyframes]
        replaced=False
        for index,value in enumerate(frames):
            if abs(float(value['time'])-time)<=0.01:
                frames[index]=frame; replaced=True; break
        if not replaced:frames.append(frame)
        frames.sort(key=lambda value:float(value['time']))
        candidate=replace(c,keyframes=frames)
        try:
            proposed=[candidate if value.uid==c.uid else value for value in self.clips]
            validate_timeline(proposed,self.tracks)
            if candidate==c:return
            self.checkpoint(); self.clips=proposed; self.changed()
            self.statusBar().showMessage(f'Keyframe bei {time:.2f} s gesetzt.',3000)
        except Exception as exc:self.error(exc)

    def remove_keyframe(self):
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker or not self.require_unlocked(c):return
        row=self.keyframe_list.currentRow()
        if row<0 or row>=len(c.keyframes):return
        frames=[dict(value) for index,value in enumerate(c.keyframes) if index!=row]
        candidate=replace(c,keyframes=frames)
        self.checkpoint(); self.clips=[candidate if value.uid==c.uid else value for value in self.clips]; self.changed()

    def refresh_volume_keyframe_list(self, clip):
        self.volume_keyframe_list.blockSignals(True)
        self.volume_keyframe_list.clear()
        for keyframe in clip.volume_keyframes:
            curve=KEYFRAME_CURVE_LABELS.get(keyframe.get('curve','linear'),'Linear')
            item=QListWidgetItem(f"{float(keyframe['time']):.2f} s   ·   Lautstärke {float(keyframe['volume'])*100:.0f}%   ·   {curve}")
            item.setData(Qt.UserRole,float(keyframe['time']))
            self.volume_keyframe_list.addItem(item)
        self.volume_keyframe_list.clearSelection()
        self.volume_keyframe_list.setCurrentRow(-1)
        self.volume_keyframe_list.blockSignals(False)

    def volume_keyframe_selected(self,row):
        c=self.current_clip()
        if not c or c.kind not in ('video','audio') or not c.has_audio or row<0:return
        item=self.volume_keyframe_list.item(row)
        if item is None:return
        time=float(item.data(Qt.UserRole))
        frame=min(c.volume_keyframes,key=lambda value:abs(float(value['time'])-time))
        self.volume_keyframe_time.setValue(time)
        self.volume.setValue(float(frame['volume'])*100)
        curve_index=self.volume_keyframe_curve.findData(frame.get('curve','linear'))
        self.volume_keyframe_curve.setCurrentIndex(curve_index if curve_index >= 0 else 0)

    def set_volume_keyframe(self):
        c=self.current_clip()
        if not c or c.kind not in ('video','audio') or not c.has_audio or self.worker or not self.require_unlocked(c):return
        time=round(max(0.0,min(c.length,self.volume_keyframe_time.value())),6)
        frame={'time':time,'volume':round(self.volume.value()/100,6),
               'curve':self.volume_keyframe_curve.currentData() or 'linear'}
        frames=[dict(value) for value in c.volume_keyframes]
        replaced=False
        for index,value in enumerate(frames):
            if abs(float(value['time'])-time)<=0.01:
                frames[index]=frame; replaced=True; break
        if not replaced:frames.append(frame)
        frames.sort(key=lambda value:float(value['time']))
        candidate=replace(c,volume_keyframes=frames)
        try:
            proposed=[candidate if value.uid==c.uid else value for value in self.clips]
            validate_timeline(proposed,self.tracks)
            if candidate==c:return
            self.checkpoint(); self.clips=proposed; self.changed()
            self.statusBar().showMessage(f'Lautstärke-Keyframe bei {time:.2f} s gesetzt.',3000)
        except Exception as exc:self.error(exc)

    def remove_volume_keyframe(self):
        c=self.current_clip()
        if not c or c.kind not in ('video','audio') or not c.has_audio or self.worker or not self.require_unlocked(c):return
        row=self.volume_keyframe_list.currentRow()
        if row<0 or row>=len(c.volume_keyframes):return
        frames=[dict(value) for index,value in enumerate(c.volume_keyframes) if index!=row]
        candidate=replace(c,volume_keyframes=frames)
        self.checkpoint(); self.clips=[candidate if value.uid==c.uid else value for value in self.clips]; self.changed()

    def refresh_speed_ramp_list(self, clip):
        self.speed_ramp_list.blockSignals(True); self.speed_ramp_list.clear()
        for keyframe in clip.speed_keyframes:
            item=QListWidgetItem(f"{float(keyframe['time']):.2f} s   ·   {float(keyframe['speed']):.2f}×")
            item.setData(Qt.UserRole,float(keyframe['time'])); self.speed_ramp_list.addItem(item)
        self.speed_ramp_list.clearSelection(); self.speed_ramp_list.setCurrentRow(-1); self.speed_ramp_list.blockSignals(False)

    def speed_ramp_selected(self,row):
        c=self.current_clip()
        if not c or c.kind!='video' or row<0:return
        item=self.speed_ramp_list.item(row)
        if item is None:return
        time=float(item.data(Qt.UserRole)); frame=min(c.speed_keyframes,key=lambda value:abs(float(value['time'])-time))
        self.speed_ramp_time.setMaximum(max(.01,c.end-c.start)); self.speed_ramp_time.setValue(time); self.speed_ramp_value.setValue(float(frame['speed']))

    def set_speed_ramp(self):
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker or not self.require_unlocked(c):return
        # Preserve the point while committing any other pending inspector
        # edits (freeze/reverse/filter/mask) before the list refreshes.
        requested_time=self.speed_ramp_time.value(); requested_speed=self.speed_ramp_value.value()
        self.apply_properties()
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker or not self.require_unlocked(c):return
        time=round(max(0.0,min(c.end-c.start,requested_time)),6)
        frame={'time':time,'speed':round(requested_speed,6)}
        frames=[dict(value) for value in c.speed_keyframes]; replaced=False
        for index,value in enumerate(frames):
            if abs(float(value['time'])-time)<=.01: frames[index]=frame; replaced=True; break
        if not replaced:frames.append(frame)
        frames.sort(key=lambda value:float(value['time']))
        candidate=replace(c,speed_keyframes=frames)
        try:
            proposed=[candidate if value.uid==c.uid else value for value in self.clips]; validate_timeline(proposed,self.tracks)
            if candidate==c:return
            self.checkpoint(); self.clips=proposed; self.changed(); self.statusBar().showMessage(f'Speed-Punkt bei {time:.2f} s gesetzt.',3000)
        except Exception as exc:self.error(exc)

    def remove_speed_ramp(self):
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker or not self.require_unlocked(c):return
        row=self.speed_ramp_list.currentRow()
        if row<0 or row>=len(c.speed_keyframes):return
        frames=[dict(value) for index,value in enumerate(c.speed_keyframes) if index!=row]
        candidate=replace(c,speed_keyframes=frames)
        self.checkpoint(); self.clips=[candidate if value.uid==c.uid else value for value in self.clips]; self.changed()

    def fill_inspector(self):
        if self._inspector_filling: return
        self._inspector_filling=True
        scroll=self.inspector_scroll.verticalScrollBar(); old_scroll=scroll.value()
        try:
            self._fill_inspector_values(); self.refresh_inline()
            clip=self.current_clip()
            for control in self._inspector_controls():
                if self.worker or self.selection_locked(): control.setEnabled(False)
                reason=('Wähle zuerst einen Clip aus.' if not clip else
                        'Wähle für diese Einstellung genau einen Clip aus.' if len(self.selection)>1 else
                        'Entsperre die Spur, um diesen Clip zu bearbeiten.' if self.selection_locked() else
                        'Die laufende Analyse muss zuerst abgeschlossen oder abgebrochen werden.' if self.worker else
                        'Für diesen Cliptyp oder Zustand nicht verfügbar; prüfe die Auswahl und zugehörigen Optionen.')
                control.setProperty('disabledReason',reason if not control.isEnabled() else '')
        finally:
            self._inspector_filling=False
            scroll.setValue(old_scroll)

    def _fill_inspector_values(self):
        self.update_context_toolbar()
        c=self.current_clip(); self.track_combo.clear()
        if len(self.selection)>1:
            self.clip_name.setText(f'{len(self.selection)} Clips ausgewählt')
            for field in self._inspector_controls():
                field.setEnabled(False)
            self.auto_reframe_status.setText('Auto-Reframe ist bei Mehrfachauswahl deaktiviert.')
            self.keyframe_list.clear(); self.volume_keyframe_list.clear(); self.speed_ramp_list.clear()
            return
        if not c:
            self.clip_name.setText('Kein Clip ausgewählt')
            for field in self._inspector_controls(): field.setEnabled(False)
            self.auto_reframe_status.setText('Kein Clip ausgewählt.')
            self.keyframe_list.clear()
            self.volume_keyframe_list.clear(); self.speed_ramp_list.clear()
            return
        self.clip_name.setText('Adjustment-Layer' if c.source_type=='adjustment' else c.text if c.kind=='text' else Path(c.path).name)
        for t in sorted(self.tracks,reverse=True):
            if (t>0)==(c.kind in ('video','text')): self.track_combo.addItem(f'Video {t}' if t>0 else f'Audio {-t}',t)
        self.track_combo.setCurrentIndex(self.track_combo.findData(c.track))
        self.position.setValue(c.position); self.start.setValue(c.start); self.end.setValue(c.end); self.speed.setValue(c.speed); self.fade_in.setValue(c.fade_in); self.fade_out.setValue(c.fade_out); self.volume.setValue(c.volume*100)
        is_text=c.kind=='text'
        is_video=c.kind=='video'
        is_adjustment=c.source_type=='adjustment'
        is_transitionable=c.kind in ('video','audio') and not is_adjustment
        is_audioable=c.kind in ('video','audio') and c.has_audio
        self.speed.setEnabled(not is_text and not is_adjustment)
        self.freeze_enabled.setEnabled(is_video and not is_adjustment); self.freeze_duration.setEnabled(is_video and not is_adjustment and c.freeze_frame); self.reverse_clip.setEnabled(is_video and not is_adjustment)
        self.fade_in.setEnabled(not is_text and not is_adjustment); self.fade_out.setEnabled(not is_text and not is_adjustment)
        for field in (self.text_value,self.text_size,self.text_color,self.text_palette_button,self.text_font,self.text_bold,self.text_italic,
                      self.text_outline_width,self.text_outline_color,self.text_shadow_size,self.text_shadow_color,
                      self.text_background_enabled,self.text_background_color,self.text_background_opacity,self.text_background_padding,
                      self.text_animation,self.text_animation_duration,self.text_style_preset,self.text_style_apply_button,self.text_x,self.text_y): field.setEnabled(is_text)
        for field in (self.transform_scale,self.transform_x,self.transform_y,self.rotation,self.crop_left,self.crop_top,self.crop_right,self.crop_bottom,self.flip_horizontal,self.flip_vertical): field.setEnabled(is_video and not is_adjustment)
        for field in (self.brightness,self.contrast,self.saturation,self.filter_preset,self.effect_preset,self.effect_preset_apply_button,
                      self.opacity,self.blur,self.sharpen): field.setEnabled(is_video)
        for field in (self.color_exposure,self.color_temperature,self.color_tint,self.color_vibrance,*self.color_wheel_spins.values()):
            field.setEnabled(is_video and not is_adjustment)
        for field in (self.lut_path,self.lut_browse_button,
                      self.opacity,self.blur,self.sharpen,self.chroma_key_enabled,self.chroma_key_color,self.chroma_key_similarity,
                      self.chroma_key_blend,self.mask_type,self.mask_x,self.mask_y,self.mask_width,self.mask_height,self.mask_feather): field.setEnabled(is_video and not is_adjustment)
        self.opacity.setEnabled(is_video); self.blur.setEnabled(is_video); self.sharpen.setEnabled(is_video)
        self.stabilization.setEnabled(is_video and not is_adjustment)
        for field in (self.mask_points,self.mask_points_apply,self.mask_path_time,self.mask_path_list,
                      self.mask_path_set_button,self.mask_path_remove_button):
            field.setEnabled(is_video and not is_adjustment and c.mask_type == 'bezier')
        self.mask_type.setEnabled(is_video and not is_adjustment)
        background_source = is_video and not is_adjustment and c.source_type in ('video','image')
        tracking_source = is_video and not is_adjustment and c.source_type == 'video'
        self.background_remove_button.setEnabled(background_source)
        self.background_clear_button.setEnabled(background_source and bool(c.background_removed_path))
        self.background_removal_enabled.setEnabled(background_source and bool(c.background_removed_path))
        self.track_motion_button.setEnabled(tracking_source)
        self.mask_track_button.setEnabled(tracking_source and c.mask_type == 'bezier' and len(c.mask_points) >= 3)
        self.clear_tracking_button.setEnabled(tracking_source and bool(c.tracking_keyframes))
        auto_reframe_source = tracking_source
        self.auto_reframe_enabled.setEnabled(auto_reframe_source)
        self.auto_reframe_format.setEnabled(auto_reframe_source)
        self.auto_reframe_button.setEnabled(auto_reframe_source)
        self.auto_reframe_clear_button.setEnabled(auto_reframe_source and bool(c.auto_reframe_keyframes))
        self.object_removal_enabled.setEnabled(is_video and not is_adjustment)
        self.text_cut_button.setEnabled(is_audioable and c.source_type in ('video','audio') and not self.worker)
        self.auto_cut_button.setEnabled(is_video and c.source_type == 'video' and not self.worker)
        self.multicam_sync_button.setEnabled(False)
        self.multicam_switch_button.setEnabled(is_video and bool(c.multicam_group) and not self.worker)
        for field in (self.keyframe_time,self.keyframe_curve,self.keyframe_list,self.keyframe_set_button,self.keyframe_remove_button,
                      self.keyframe_graph_property,self.keyframe_graph): field.setEnabled(is_video and not is_adjustment)
        for field in (self.volume_keyframe_time,self.volume_keyframe_curve,self.volume_keyframe_list,self.volume_keyframe_set_button,self.volume_keyframe_remove_button): field.setEnabled(is_audioable)
        for field in (self.audio_noise_reduction,self.audio_eq_low,self.audio_eq_mid,self.audio_eq_high,self.audio_compressor_enabled,
                      self.audio_compressor_threshold,self.audio_compressor_ratio,self.audio_ducking,self.audio_voice_isolation,self.audio_channel_mode,self.audio_pan,
                      self.audio_normalize,self.audio_normalize_target): field.setEnabled(is_audioable)
        for field in (self.speed_ramp_time,self.speed_ramp_value,self.speed_ramp_list,self.speed_ramp_set_button,self.speed_ramp_remove_button): field.setEnabled(is_video and not is_adjustment)
        self.transition_type.setEnabled(is_transitionable); self.transition_duration.setEnabled(is_transitionable)
        self.text_value.setText(c.text if is_text else '')
        self.text_size.setValue(c.font_size if is_text else 56)
        self.text_color.setText(c.color if is_text else '#ffffff')
        self.update_color_button(c.color if is_text else '#ffffff')
        self.text_font.setCurrentText(c.font_family if is_text else 'DejaVu Sans')
        self.text_bold.setChecked(c.font_bold if is_text else False); self.text_italic.setChecked(c.font_italic if is_text else False)
        self.text_outline_width.setValue(c.outline_width if is_text else 0); self.text_outline_color.setText(c.outline_color if is_text else '#000000')
        self.text_shadow_size.setValue(c.shadow_size if is_text else 0); self.text_shadow_color.setText(c.shadow_color if is_text else '#000000')
        self.text_background_enabled.setChecked(c.background_enabled if is_text else True); self.text_background_color.setText(c.background_color if is_text else '#000000')
        self.text_background_opacity.setValue(c.background_opacity*100 if is_text else 35); self.text_background_padding.setValue(c.background_padding if is_text else 16)
        animation_index=self.text_animation.findData(c.text_animation if is_text else 'none')
        self.text_animation.setCurrentIndex(animation_index if animation_index >= 0 else 0)
        self.text_animation_duration.setValue(c.text_animation_duration if is_text else .35)
        self.text_x.setValue(c.x*100 if is_text else 50); self.text_y.setValue(c.y*100 if is_text else 50)
        self.transform_scale.setValue(c.video_scale if is_video else 1.0)
        self.transform_x.setValue(c.video_x*100 if is_video else 50); self.transform_y.setValue(c.video_y*100 if is_video else 50)
        self.rotation.setValue(c.rotation if is_video else 0)
        self.crop_left.setValue(c.crop_left*100 if is_video else 0); self.crop_top.setValue(c.crop_top*100 if is_video else 0)
        self.crop_right.setValue(c.crop_right*100 if is_video else 0); self.crop_bottom.setValue(c.crop_bottom*100 if is_video else 0)
        self.flip_horizontal.setChecked(c.flip_horizontal if is_video else False); self.flip_vertical.setChecked(c.flip_vertical if is_video else False)
        self.brightness.setValue(c.brightness if is_video else 0); self.contrast.setValue(c.contrast if is_video else 1); self.saturation.setValue(c.saturation if is_video else 1)
        self.opacity.setValue(c.opacity*100 if is_video else 100); self.blur.setValue(c.blur if is_video else 0); self.sharpen.setValue(c.sharpen if is_video else 0)
        effect_index=self.effect_preset.findData(c.effect_preset if is_video else 'clean')
        self.effect_preset.setCurrentIndex(effect_index if effect_index >= 0 else 0)
        self.stabilization.setValue(c.stabilization*100 if is_video else 0)
        self.background_removal_enabled.setChecked(c.background_removal_enabled if is_video else False)
        self.background_remove_status.setText(
            'Freistellung aktiv · transparente lokale Datei wird verwendet.'
            if c.background_removal_enabled and c.background_removed_path
            else 'Freistellung erzeugt noch keine lokale Datei.')
        self.tracking_status.setText(
            f'{len(c.tracking_keyframes)} Tracking-Punkte vorhanden.' if c.tracking_keyframes
            else 'Kein Tracking vorhanden.')
        auto_format_index=self.auto_reframe_format.findData(c.auto_reframe_format if auto_reframe_source else 'project')
        self.auto_reframe_format.setCurrentIndex(auto_format_index if auto_format_index >= 0 else 0)
        if c.auto_reframe_keyframes:
            detected=sum(1 for point in c.auto_reframe_keyframes if float(point.get('score', 0.0)) > 0)
            self.auto_reframe_status.setText(
                f'{len(c.auto_reframe_keyframes)} Fokus-Punkte vorhanden · '
                f'{detected} mit Gesichtserkennung.')
        else:
            self.auto_reframe_status.setText('Noch keine Auto-Reframe-Analyse.')
        self.auto_reframe_enabled.setChecked(c.auto_reframe_enabled if auto_reframe_source else False)
        self.object_removal_enabled.setChecked(c.object_removal_enabled if is_video else False)
        self.color_exposure.setValue(c.color_exposure if is_video else 0)
        self.color_temperature.setValue(c.color_temperature*100 if is_video else 0)
        self.color_tint.setValue(c.color_tint*100 if is_video else 0)
        self.color_vibrance.setValue(c.color_vibrance*100 if is_video else 0)
        for key, spin in self.color_wheel_spins.items():
            spin.setValue(getattr(c,key)*100 if is_video else 0)
        mask_title_points='; '.join(f"{float(point['x'])*100:.1f},{float(point['y'])*100:.1f}" for point in c.mask_points)
        self.mask_points.setText(mask_title_points if is_video else '')
        self.refresh_mask_path_list(c if is_video else None)
        self.audio_noise_reduction.setValue(c.audio_noise_reduction if is_audioable else 0)
        self.audio_eq_low.setValue(c.audio_eq_low if is_audioable else 0); self.audio_eq_mid.setValue(c.audio_eq_mid if is_audioable else 0); self.audio_eq_high.setValue(c.audio_eq_high if is_audioable else 0)
        self.audio_compressor_enabled.setChecked(c.audio_compressor_enabled if is_audioable else False)
        self.audio_compressor_threshold.setValue(c.audio_compressor_threshold if is_audioable else -18); self.audio_compressor_ratio.setValue(c.audio_compressor_ratio if is_audioable else 4)
        self.audio_ducking.setValue(c.audio_ducking*100 if is_audioable else 0)
        self.audio_voice_isolation.setValue(c.audio_voice_isolation*100 if is_audioable else 0)
        self.audio_normalize.setChecked(c.audio_normalize if is_audioable else False)
        self.audio_normalize_target.setValue(c.audio_normalize_target if is_audioable else -16)
        channel_index=self.audio_channel_mode.findData(c.audio_channel_mode if is_audioable else 'stereo')
        self.audio_channel_mode.setCurrentIndex(channel_index if channel_index >= 0 else 0); self.audio_pan.setValue(c.audio_pan*100 if is_audioable else 0)
        self.freeze_enabled.setChecked(c.freeze_frame if is_video else False); self.freeze_duration.setValue(c.freeze_duration if is_video else 0)
        self.reverse_clip.setChecked(c.reverse if is_video else False)
        filter_index=self.filter_preset.findData(c.filter_preset if is_video else 'none')
        self.filter_preset.setCurrentIndex(filter_index if filter_index >= 0 else 0)
        self.lut_path.setText(c.lut_path if is_video else '')
        self.chroma_key_enabled.setChecked(c.chroma_key_enabled if is_video else False)
        self.chroma_key_color.setText(c.chroma_key_color if is_video else '#00ff00')
        self.chroma_key_similarity.setValue(c.chroma_key_similarity*100 if is_video else 10)
        self.chroma_key_blend.setValue(c.chroma_key_blend*100 if is_video else 10)
        mask_index=self.mask_type.findData(c.mask_type if is_video else 'none')
        self.mask_type.setCurrentIndex(mask_index if mask_index >= 0 else 0)
        self.mask_x.setValue(c.mask_x*100 if is_video else 0); self.mask_y.setValue(c.mask_y*100 if is_video else 0)
        self.mask_width.setValue(c.mask_width*100 if is_video else 100); self.mask_height.setValue(c.mask_height*100 if is_video else 100)
        self.mask_feather.setValue(c.mask_feather*100 if is_video else 0)
        transition_index=self.transition_type.findData(c.transition_type)
        self.transition_type.setCurrentIndex(transition_index if transition_index >= 0 else 0)
        self.transition_duration.setValue(c.transition_duration if is_transitionable else 0)
        if is_video:
            self.keyframe_time.setMaximum(max(0.01,c.length))
            local_time=max(0.0,min(c.length,self.playhead-c.position))
            self.keyframe_time.setValue(local_time)
            self.keyframe_curve.setCurrentIndex(self.keyframe_curve.findData('linear'))
            self.refresh_keyframe_list(c)
            self.refresh_keyframe_graph(c)
            self.speed_ramp_time.setMaximum(max(0.01,c.end-c.start))
            self.speed_ramp_time.setValue(max(0.0,min(c.end-c.start,local_time)))
            self.refresh_speed_ramp_list(c)
        else:
            self.keyframe_list.clear()
            self.keyframe_graph.set_data([],1.0,'scale',1.0)
            self.speed_ramp_list.clear()
        if is_audioable:
            self.volume_keyframe_time.setMaximum(max(0.01,c.length))
            local_time=max(0.0,min(c.length,self.playhead-c.position))
            self.volume_keyframe_time.setValue(local_time)
            self.refresh_volume_keyframe_list(c)
        else:
            self.volume_keyframe_list.clear()
        if not is_audioable:
            self.volume_keyframe_curve.setCurrentIndex(self.volume_keyframe_curve.findData('linear'))
        beat_count=sum(1 for marker in self.markers if marker.get('kind') == 'beat')
        self.beat_analyze_button.setEnabled(is_audioable and not self.worker)
        self.beat_clear_button.setEnabled(beat_count > 0 and not self.worker)
        self.beat_status.setText(f'{beat_count} Beat-Marker vorhanden.' if beat_count else 'Keine Beat-Marker vorhanden.')
        self.text_cut_status.setText('Pausen und Füllwörter werden lokal entfernt.' if is_audioable else 'Wähle ein Video oder Audio mit Ton.')
        self.auto_cut_status.setText('Beat- und Szenenpunkte werden lokal erkannt.' if is_video else 'Wähle einen normalen Videoclip.')
        if c.multicam_group:
            members=[value for value in self.clips if value.multicam_group == c.multicam_group]
            active=next((value for value in members if value.multicam_active), None)
            self.multicam_status.setText(
                f'{len(members)} Winkel · aktiv: {active.camera_angle or "unbenannt"}' if active
                else f'{len(members)} Winkel · kein aktiver Winkel')
        else:
            self.multicam_status.setText('Keine Multi-Kamera-Gruppe.')

    def select_clip(self,uid):
        self.compare_released(); self.video.cancel_transform()
        if uid!=self.current and self.mode=='source':
            self.player.pause();self.pending_seek=None;self.player.setSource(QUrl());self.mode='timeline'
            self.source_clip_uid=None;self.source_in=None;self.source_out=None
            self.video_stack.setCurrentIndex(0);self.placeholder.setText('Clip ausgewählt · „Clip ansehen“ startet die Quellvorschau.')
        self.set_selection([uid], uid, expand_groups=True)

    def commit_drag(self,candidate):
        if self.worker: self.refresh(); return
        candidates = list(candidate) if isinstance(candidate, (list, tuple)) else [candidate]
        originals = {value.uid: value for value in self.clips}
        if any(value.uid not in originals for value in candidates):
            return
        if any(self.track_locked(originals[value.uid].track) or self.track_locked(value.track) for value in candidates):
            self.statusBar().showMessage('Die Quell- oder Zielspur ist gesperrt.',4000)
            self.refresh()
            return
        by_uid = {value.uid: value for value in candidates}
        proposed=[by_uid.get(c.uid,c) for c in self.clips]
        try:
            validate_timeline(proposed,self.tracks)
            if proposed==self.clips:return
            self.checkpoint(); self.clips=proposed; self.selection=[value.uid for value in candidates]; self.current=candidates[-1].uid; self.changed()
        except Exception as exc:
            self.statusBar().showMessage(str(exc).replace('\n',' '),7000)
            self.timeline.update()

    def apply_text_style_preset(self):
        c=self.current_clip()
        if not c or c.kind!='text' or self.worker:
            return self.statusBar().showMessage('Wähle zuerst einen Text- oder Untertitelclip.',3000)
        preset=TEXT_STYLE_PRESETS.get(self.text_style_preset.currentData())
        if not preset:
            return
        if not self.require_unlocked(c):
            return
        candidate=replace(c,**dict(preset))
        try:
            validate_timeline([candidate if item.uid==c.uid else item for item in self.clips],self.tracks)
            self.checkpoint(); self.clips=[candidate if item.uid==c.uid else item for item in self.clips]; self.changed()
            self.statusBar().showMessage('Textstil angewendet.',2500)
        except Exception as exc:
            self.error(exc)

    def apply_effect_preset(self):
        c=self.current_clip()
        if not c or c.kind!='video' or self.worker:
            return self.statusBar().showMessage('Wähle zuerst einen Video- oder Adjustment-Layer.',3000)
        if not self.require_unlocked(c):
            return
        name=self.effect_preset.currentData() or 'clean'
        preset=EFFECT_PRESETS.get(name)
        if not preset:
            return
        candidate=replace(c,effect_preset=name,**dict(preset))
        try:
            proposed=[candidate if item.uid==c.uid else item for item in self.clips]
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed()
            self.statusBar().showMessage(f'Effekt-Preset „{self.effect_preset.currentText()}“ angewendet.',3000)
        except Exception as exc:
            self.error(exc)

    def export_subtitles(self):
        if self.worker:
            return
        cues=subtitle_cues_from_clips(self.clips,self.track_names)
        if not cues:
            return self.error('Keine exportierbaren Text- oder Untertitelclips gefunden.')
        path,_=QFileDialog.getSaveFileName(self,'Untertitel exportieren','Untertitel.srt',
                                           'SubRip (*.srt);;WebVTT (*.vtt)',options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        suffix=Path(path).suffix.casefold()
        if suffix not in ('.srt','.vtt'):
            path += '.vtt' if 'WebVTT' in path else '.srt'
        target=Path(path).resolve()
        if target.exists() and QMessageBox.question(self,'Untertitel ersetzen?',f'{target}\nüberschreiben?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            return
        try:
            write_subtitle_file(target,self.clips,self.track_names)
            self.statusBar().showMessage(f'{len(cues)} Untertitel exportiert · {target.name}',5000)
        except Exception as exc:
            self.error(exc)

    def apply_properties(self):
        if self._inspector_filling or self.worker: return
        c=self.current_clip()
        if len(self.selection)>1:
            self.statusBar().showMessage('Inspector-Änderungen sind bei Mehrfachauswahl deaktiviert.',3000)
            return
        if c:
            if not self.require_unlocked(c):
                self.fill_inspector()
                return
            values=dict(position=self.position.value(),start=self.start.value(),end=self.end.value(),speed=self.speed.value(),fade_in=self.fade_in.value(),fade_out=self.fade_out.value(),volume=self.volume.value()/100,track=self.track_combo.currentData())
            if c.kind=='text':
                values.update(text=self.text_value.text(),font_size=self.text_size.value(),color=self.text_color.text().strip(),
                              font_family=self.text_font.currentText().strip(),font_bold=self.text_bold.isChecked(),font_italic=self.text_italic.isChecked(),
                              outline_width=self.text_outline_width.value(),outline_color=self.text_outline_color.text().strip(),
                              shadow_size=self.text_shadow_size.value(),shadow_color=self.text_shadow_color.text().strip(),
                              background_enabled=self.text_background_enabled.isChecked(),background_color=self.text_background_color.text().strip(),
                              background_opacity=self.text_background_opacity.value()/100,background_padding=self.text_background_padding.value(),
                              text_animation=self.text_animation.currentData(),text_animation_duration=self.text_animation_duration.value(),
                              x=self.text_x.value()/100,y=self.text_y.value()/100)
            if c.kind=='video':
                values.update(video_scale=self.transform_scale.value(),video_x=self.transform_x.value()/100,video_y=self.transform_y.value()/100,
                             crop_left=self.crop_left.value()/100,crop_top=self.crop_top.value()/100,
                             crop_right=self.crop_right.value()/100,crop_bottom=self.crop_bottom.value()/100,
                             rotation=self.rotation.value(),flip_horizontal=self.flip_horizontal.isChecked(),
                             flip_vertical=self.flip_vertical.isChecked(),brightness=self.brightness.value(),
                             contrast=self.contrast.value(),saturation=self.saturation.value(),
                             color_exposure=self.color_exposure.value(),color_temperature=self.color_temperature.value()/100,
                             color_tint=self.color_tint.value()/100,color_vibrance=self.color_vibrance.value()/100,
                             **{key:spin.value()/100 for key,spin in self.color_wheel_spins.items()},
                             opacity=self.opacity.value()/100,
                             blur=self.blur.value(),sharpen=self.sharpen.value(),stabilization=self.stabilization.value()/100,
                             background_removal_enabled=self.background_removal_enabled.isChecked(),
                             background_removed_path=c.background_removed_path,
                             tracking_keyframes=[dict(point) for point in c.tracking_keyframes],
                             auto_reframe_enabled=self.auto_reframe_enabled.isChecked() if c.source_type == 'video' else False,
                             auto_reframe_format=self.auto_reframe_format.currentData() or 'project',
                             auto_reframe_keyframes=[dict(point) for point in c.auto_reframe_keyframes] if c.source_type == 'video' else [],
                             object_removal_enabled=self.object_removal_enabled.isChecked(),
                             effect_preset=c.effect_preset,
                             freeze_frame=self.freeze_enabled.isChecked(),
                             freeze_duration=self.freeze_duration.value() if self.freeze_enabled.isChecked() else 0.0,
                             reverse=self.reverse_clip.isChecked(),filter_preset=self.filter_preset.currentData(),
                             lut_path=str(Path(self.lut_path.text().strip()).expanduser().resolve()) if self.lut_path.text().strip() else '',
                             chroma_key_enabled=self.chroma_key_enabled.isChecked(),chroma_key_color=self.chroma_key_color.text().strip(),
                             chroma_key_similarity=self.chroma_key_similarity.value()/100,chroma_key_blend=self.chroma_key_blend.value()/100,
                             mask_type=self.mask_type.currentData(),mask_x=self.mask_x.value()/100,mask_y=self.mask_y.value()/100,
                             mask_width=self.mask_width.value()/100,mask_height=self.mask_height.value()/100,mask_feather=self.mask_feather.value()/100,
                             mask_points=self.parse_mask_points(self.mask_points.text()) if self.mask_type.currentData() == 'bezier' else [],
                             mask_path_keyframes=[dict(frame, points=[dict(point) for point in frame.get('points', [])])
                                                  for frame in c.mask_path_keyframes] if self.mask_type.currentData() == 'bezier' else [])
                preset_values=EFFECT_PRESETS.get(c.effect_preset)
                def differs_from_preset(key, value):
                    current=values.get(key, getattr(c,key))
                    if isinstance(current, (int,float)) and isinstance(value, (int,float)):
                        return abs(float(current)-float(value)) > 1e-7
                    return current != value
                if preset_values and any(differs_from_preset(key,value) for key,value in preset_values.items() if key in values):
                    values['effect_preset']='custom'
                if c.keyframes and (abs(values['start']-c.start)>1e-7 or abs(values['end']-c.end)>1e-7
                                    or abs(values['speed']-c.speed)>1e-7):
                    values['keyframes']=retime_keyframes(c,values['start'],values['end'],values['speed'])
                if c.speed_keyframes and (abs(values['start']-c.start)>1e-7 or abs(values['end']-c.end)>1e-7):
                    values['speed_keyframes']=retime_speed_keyframes(c,values['start'],values['end'])
                if c.tracking_keyframes and (abs(values['start']-c.start)>1e-7 or abs(values['end']-c.end)>1e-7
                                             or abs(values['speed']-c.speed)>1e-7):
                    values['tracking_keyframes']=retime_tracking_keyframes(c,values['start'],values['end'],values['speed'])
                if c.auto_reframe_keyframes and (abs(values['start']-c.start)>1e-7 or abs(values['end']-c.end)>1e-7
                                                 or abs(values['speed']-c.speed)>1e-7):
                    values['auto_reframe_keyframes']=retime_auto_reframe_keyframes(c,values['start'],values['end'],values['speed'])
                if c.mask_path_keyframes and (abs(values['start']-c.start)>1e-7 or abs(values['end']-c.end)>1e-7
                                              or abs(values['speed']-c.speed)>1e-7):
                    values['mask_path_keyframes']=retime_mask_path_keyframes(c,values['start'],values['end'],values['speed'])
            if c.kind in ('video','audio') and c.volume_keyframes and (
                    abs(values['start']-c.start)>1e-7 or abs(values['end']-c.end)>1e-7
                    or abs(values['speed']-c.speed)>1e-7):
                values['volume_keyframes']=retime_volume_keyframes(c,values['start'],values['end'],values['speed'])
            if c.kind in ('video','audio'):
                values.update(audio_noise_reduction=self.audio_noise_reduction.value(),
                              audio_eq_low=self.audio_eq_low.value(),audio_eq_mid=self.audio_eq_mid.value(),audio_eq_high=self.audio_eq_high.value(),
                              audio_compressor_enabled=self.audio_compressor_enabled.isChecked(),
                              audio_compressor_threshold=self.audio_compressor_threshold.value(),audio_compressor_ratio=self.audio_compressor_ratio.value(),
                              audio_ducking=self.audio_ducking.value()/100,
                              audio_voice_isolation=self.audio_voice_isolation.value()/100,
                              audio_channel_mode=self.audio_channel_mode.currentData(),audio_pan=self.audio_pan.value()/100,
                              audio_normalize=self.audio_normalize.isChecked(),
                              audio_normalize_target=self.audio_normalize_target.value())
                transition_type='none' if c.source_type=='adjustment' else self.transition_type.currentData()
                values.update(transition_type=transition_type,
                              transition_duration=self.transition_duration.value() if transition_type!='none' else 0.0)
            candidate=replace(c,**values)
            if candidate==c: return
            try:
                proposed=[candidate if v.uid==c.uid else v for v in self.clips]; validate_timeline(proposed,self.tracks)
                self.checkpoint(); self.clips=proposed; self.changed()
            except Exception as exc:self.error(exc)

    def reset_transform(self):
        c=self.current_clip()
        if len(self.selection)>1:
            return self.statusBar().showMessage('Bild zurücksetzen ist bei Mehrfachauswahl deaktiviert.',3000)
        if not c or c.kind!='video' or self.worker or not self.require_unlocked(c):return
        defaults=dict(video_scale=1.0,video_x=.5,video_y=.5,crop_left=0.0,crop_top=0.0,
                      crop_right=0.0,crop_bottom=0.0,rotation=0.0,flip_horizontal=False,flip_vertical=False,
                      keyframes=[],speed_keyframes=[],brightness=0.0,contrast=1.0,saturation=1.0,
                      filter_preset='none',lut_path='',opacity=1.0,blur=0.0,sharpen=0.0,stabilization=0.0,effect_preset='clean',
                      background_removal_enabled=False,background_removed_path='',tracking_keyframes=[],object_removal_enabled=False,
                      auto_reframe_enabled=False,auto_reframe_format='project',auto_reframe_keyframes=[],
                      color_exposure=0.0,color_temperature=0.0,color_tint=0.0,color_vibrance=0.0,
                      color_lift_r=0.0,color_lift_g=0.0,color_lift_b=0.0,
                      color_gamma_r=0.0,color_gamma_g=0.0,color_gamma_b=0.0,
                      color_gain_r=0.0,color_gain_g=0.0,color_gain_b=0.0,
                      freeze_frame=False,freeze_duration=0.0,reverse=False,chroma_key_enabled=False,
                      chroma_key_color='#00ff00',chroma_key_similarity=.1,chroma_key_blend=.1,
                      mask_type='none',mask_x=0.0,mask_y=0.0,mask_width=1.0,mask_height=1.0,mask_feather=0.0,
                      mask_points=[],mask_path_keyframes=[])
        if all(getattr(c,key)==value for key,value in defaults.items()):
            return
        self.checkpoint(); candidate=replace(c,**defaults)
        self.clips=[candidate if item.uid==c.uid else item for item in self.clips]; self.changed()

    def add_text(self, style=None):
        """Ask for text after a style was chosen and create a styled clip."""
        if self.worker:return
        if not any(c.kind=='video' and c.source_type != 'adjustment' for c in self.clips):
            return self.error('Füge zuerst ein Video zur Timeline hinzu.')
        custom_style=isinstance(style,dict)
        style_key=str((style.get('style') if custom_style else style)
                      or self.text_style_preset.currentData() or 'title')
        preset=dict(TEXT_STYLE_PRESETS.get(style_key,TEXT_STYLE_PRESETS['title']))
        if custom_style:
            allowed={'font_size','color','font_family','font_bold','font_italic','outline_width',
                     'outline_color','shadow_size','shadow_color','background_enabled',
                     'background_color','background_opacity','background_padding','text_animation',
                     'text_animation_duration','x','y'}
            preset.update({key:value for key,value in style.items() if key in allowed})
        preset_index=self.text_style_preset.findData(style_key) if not custom_style else -1
        if not custom_style and preset_index >= 0:
            self.text_style_preset.blockSignals(True)
            self.text_style_preset.setCurrentIndex(preset_index)
            self.text_style_preset.blockSignals(False)
        title=('Eigenes Textdesign' if custom_style else
               {'title':'Titel','subtitle':'Untertitel','lower_third':'Lower Third'}.get(style_key,'Text'))
        text,ok=QInputDialog.getText(self,f'{title} hinzufügen','Text eingeben:')
        if not ok or not text.strip():return
        position=max(0,min(self.playhead,length(self.clips)))
        duration=min(3.0,max(0.5,length(self.clips)-position)) if length(self.clips)>position else 3.0
        track=max((t for t in self.tracks if t>0),default=0)+1
        # Text has no source media limit; its visible duration is controlled by
        # the clip end/trim fields and can be extended beyond the initial 3 s.
        candidate=Clip('',864000.0,start=0,end=duration,position=position,track=track,
                       kind='text',has_audio=False,text=text.strip(),source_type='text',**preset)
        self.checkpoint(f'Text hinzufügen · {title}')
        self.tracks.append(track)
        self.track_states=normalize_track_states(self.track_states,self.tracks)
        self.track_names=normalize_track_names(self.track_names,self.tracks)
        self.track_names[track]='Text'
        self.clips.append(candidate); self.selection=[candidate.uid]; self.current=candidate.uid; self.changed()

    def add_adjustment_layer(self):
        if self.worker:
            return
        if not any(c.kind=='video' and c.source_type!='adjustment' for c in self.clips):
            return self.error('Füge zuerst mindestens ein Video zur Timeline hinzu.')
        duration=max((c.finish for c in self.clips if c.source_type!='adjustment'),default=0.0)
        if duration < MIN_CLIP:
            return self.error('Die Timeline ist noch zu kurz für eine Adjustment-Layer.')
        track=max((t for t in self.tracks if t>0),default=0)+1
        candidate=Clip('',max(864000.0,duration),start=0,end=duration,position=0,track=track,
                       kind='video',has_audio=False,source_type='adjustment',effect_preset='clean')
        try:
            validate_timeline(self.clips+[candidate],self.tracks+[track])
            self.checkpoint()
            video_slot=next((index for index,value in enumerate(self.tracks) if value<0),len(self.tracks))
            self.tracks.insert(video_slot,track)
            self.track_states=normalize_track_states(self.track_states,self.tracks)
            self.track_names=normalize_track_names(self.track_names,self.tracks)
            self.track_names[track]=f'Adjustment {sum(value.source_type=="adjustment" for value in self.clips)+1}'
            self.clips.append(candidate)
            self.selection=[candidate.uid]; self.current=candidate.uid; self.changed()
            self.statusBar().showMessage('Adjustment-Layer angelegt · Effekte wirken auf die darunterliegende Komposition.',3500)
        except Exception as exc:
            self.error(exc)

    def split(self):
        selected=self.selected_clips()
        if not selected or self.worker:
            return
        if self.selection_locked():
            return self.statusBar().showMessage('Eine ausgewählte Spur ist gesperrt.',3000)
        eligible=[clip for clip in selected if clip.position+MIN_CLIP < self.playhead < clip.finish-MIN_CLIP]
        if not eligible:
            return self.error('Setze den Abspielkopf in mindestens einen ausgewählten Clip.')
        try:
            replacement={}
            new_selection=[]
            for clip in eligible:
                first,second=split_clip(clip,self.playhead)
                replacement[clip.uid]=(first,second)
                new_selection.extend([first.uid,second.uid])
            proposed=[]
            for clip in self.clips:
                proposed.extend(replacement.get(clip.uid,(clip,)))
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.selection=new_selection; self.current=new_selection[-1]; self.changed()
        except Exception as exc:self.error(exc)

    def _single_trim_clip(self):
        """Return the one selected source clip used by professional trim tools."""
        if self.worker:
            return None
        selected = self.selected_clips()
        if len(selected) != 1:
            self.statusBar().showMessage('Wähle genau einen Video- oder Audioclip für diesen Trim-Schnitt.', 3500)
            return None
        clip = selected[0]
        if clip.kind not in ('video', 'audio') or clip.source_type not in ('video', 'audio'):
            self.statusBar().showMessage('Dieser Trim-Schnitt ist nur für Video- und Audiomedien verfügbar.', 3500)
            return None
        if not self.require_unlocked(clip):
            return None
        return clip

    def _frame_step(self, clip):
        """Return one source frame in timeline seconds for trim nudges."""
        try:
            fps = float(clip.source_fps or 24.0)
        except (TypeError, ValueError):
            fps = 24.0
        return max(MIN_CLIP, 1.0 / max(1.0, fps))

    def _commit_trim_replacements(self, replacements, message, selection=None, markers=None):
        """Validate and commit a trim edit as one undoable transaction."""
        proposed = [replacements.get(clip.uid, clip) for clip in self.clips]
        validate_timeline(proposed, self.tracks)
        self.checkpoint()
        self.clips = proposed
        if markers is not None:
            self.markers = normalize_markers(markers, length(proposed))
        chosen = selection or list(replacements)
        self.selection = [uid for uid in chosen if any(clip.uid == uid for clip in proposed)]
        self.current = self.selection[-1] if self.selection else None
        self.changed()
        self.statusBar().showMessage(message, 3500)

    def _ripple_trim(self, edge):
        clip = self._single_trim_clip()
        if clip is None:
            return
        if not clip.position + MIN_CLIP <= self.playhead <= clip.finish - MIN_CLIP:
            return self.statusBar().showMessage('Setze den Abspielkopf innerhalb des ausgewählten Clips.', 3500)
        old_finish = clip.finish
        if edge == 'in':
            delta = self.playhead - clip.position
            trimmed = edited_clip(clip, 'left', delta)
            # Ripple-In removes the leading source range but keeps the clip at
            # the same timeline position, so later clips can close the gap.
            candidate = replace(trimmed, position=clip.position)
            label_text = 'Ripple-In'
        else:
            delta = self.playhead - clip.finish
            candidate = edited_clip(clip, 'right', delta)
            label_text = 'Ripple-Out'
        removed = clip.length - candidate.length
        if removed < MIN_CLIP - 1e-7:
            return self.statusBar().showMessage('Der Trim-Bereich ist zu klein.', 3000)
        replacements = {clip.uid: candidate}
        for other in self.clips:
            if other.uid == clip.uid:
                continue
            if other.track == clip.track and other.position >= old_finish - 1e-7:
                if self.track_locked(other.track):
                    return self.statusBar().showMessage('Eine betroffene Spur ist gesperrt.', 3500)
                replacements[other.uid] = replace(other, position=max(0.0, other.position - removed))
        markers = []
        for marker in self.markers:
            value = dict(marker)
            if float(value.get('time', 0.0)) >= old_finish - 1e-7:
                value['time'] = max(0.0, float(value['time']) - removed)
            markers.append(value)
        try:
            self._commit_trim_replacements(
                replacements, f'{label_text} ausgeführt · {removed:.3f} s entfernt',
                selection=[clip.uid], markers=markers)
        except Exception as exc:
            self.error(exc)

    def ripple_trim_in(self):
        self._ripple_trim('in')

    def ripple_trim_out(self):
        self._ripple_trim('out')

    def _adjacent_pair_for_roll(self, clip):
        same = sorted((value for value in self.clips
                       if value.uid != clip.uid and value.track == clip.track
                       and value.kind == clip.kind), key=lambda value: value.position)
        previous = max((value for value in same if value.finish <= clip.position + 1e-6),
                       key=lambda value: value.finish, default=None)
        following = min((value for value in same if value.position >= clip.finish - 1e-6),
                         key=lambda value: value.position, default=None)
        pairs = []
        if previous is not None and abs(previous.finish - clip.position) <= 1e-5:
            pairs.append((previous, clip))
        if following is not None and abs(clip.finish - following.position) <= 1e-5:
            pairs.append((clip, following))
        valid = [pair for pair in pairs
                 if pair[0].position + MIN_CLIP <= self.playhead <= pair[1].finish - MIN_CLIP]
        return min(valid, key=lambda pair: abs(pair[0].finish - self.playhead), default=None)

    def roll_to_playhead(self):
        clip = self._single_trim_clip()
        if clip is None:
            return
        pair = self._adjacent_pair_for_roll(clip)
        if pair is None:
            return self.statusBar().showMessage('Setze den Abspielkopf zwischen zwei angrenzende Clips.', 3500)
        left, right = pair
        if self.track_locked(left.track) or self.track_locked(right.track):
            return self.statusBar().showMessage('Eine betroffene Spur ist gesperrt.', 3500)
        try:
            first, second = roll_edit(left, right, self.playhead)
            self._commit_trim_replacements(
                {left.uid: first, right.uid: second},
                f'Roll-Schnitt auf {self.playhead:.3f} s gesetzt',
                selection=[first.uid, second.uid])
        except Exception as exc:
            self.error(exc)

    def _adjacent_triplet(self, clip):
        same = sorted((value for value in self.clips
                       if value.uid != clip.uid and value.track == clip.track
                       and value.kind == clip.kind), key=lambda value: value.position)
        previous = max((value for value in same if value.finish <= clip.position + 1e-6),
                       key=lambda value: value.finish, default=None)
        following = min((value for value in same if value.position >= clip.finish - 1e-6),
                         key=lambda value: value.position, default=None)
        if (previous is None or following is None
                or abs(previous.finish - clip.position) > 1e-5
                or abs(clip.finish - following.position) > 1e-5):
            return None
        return previous, clip, following

    def slide_selected(self, direction):
        clip = self._single_trim_clip()
        if clip is None:
            return
        triplet = self._adjacent_triplet(clip)
        if triplet is None:
            return self.statusBar().showMessage('Slide braucht einen Clip mit direkten Nachbarn links und rechts.', 3500)
        if self.track_locked(clip.track):
            return self.statusBar().showMessage('Die betroffene Spur ist gesperrt.', 3500)
        previous, middle, following = triplet
        delta = self._frame_step(clip) * (1 if direction >= 0 else -1)
        try:
            left, moved, right = slide_edit(previous, middle, following, delta)
            self._commit_trim_replacements(
                {left.uid: left, moved.uid: moved, right.uid: right},
                f'Slide-Schnitt {"rechts" if delta > 0 else "links"} · {abs(delta):.3f} s',
                selection=[moved.uid])
        except Exception as exc:
            self.error(exc)

    def slip_selected(self, direction):
        clip = self._single_trim_clip()
        if clip is None:
            return
        delta = self._frame_step(clip) * (1 if direction >= 0 else -1)
        try:
            candidate = slip_clip(clip, delta)
            if abs(candidate.start - clip.start) <= 1e-7:
                return self.statusBar().showMessage('Der Quellbereich kann nicht weiter in diese Richtung verschoben werden.', 3000)
            self._commit_trim_replacements(
                {clip.uid: candidate},
                f'Slip-Schnitt {"rechts" if delta > 0 else "links"} · {abs(candidate.start-clip.start):.3f} s',
                selection=[candidate.uid])
        except Exception as exc:
            self.error(exc)

    def remove(self):
        selected=self.selected_clips()
        if selected and not self.worker and not self.selection_locked():
            removed={clip.uid for clip in selected}
            anchor=selected[0]
            self.checkpoint(); self.clips=[clip for clip in self.clips if clip.uid not in removed]
            adjacent=min(self.clips,key=lambda c:((c.track!=anchor.track),abs(c.position-anchor.position)),default=None)
            self.current=adjacent.uid if adjacent else None; self.selection=[self.current] if self.current else []; self.changed()

    def add_track(self,video):
        if self.worker:return
        self.checkpoint()
        new=max([t for t in self.tracks if t>0],default=0)+1 if video else min([t for t in self.tracks if t<0],default=0)-1
        self.tracks.append(new); self.track_states=normalize_track_states(self.track_states,self.tracks); self.track_names=normalize_track_names(self.track_names,self.tracks); self.changed()

    def track_counts_changed(self):
        if self.worker:return
        videos, audios = self.video_tracks.value(), self.audio_tracks.value()
        wanted=list(range(videos,0,-1))+list(range(-1,-audios-1,-1))
        if any(c.track not in wanted for c in self.clips):
            self.statusBar().showMessage('Diese Spur enthält noch Clips. Verschiebe oder lösche sie zuerst.',6000)
            self.refresh(); return
        if wanted != self.tracks:
            self.checkpoint(); self.tracks=wanted; self.track_states=normalize_track_states(self.track_states,self.tracks); self.track_names=normalize_track_names(self.track_names,self.tracks); self.changed()

    def default_track_name(self, track):
        return f'VIDEO {track}' if track > 0 else f'AUDIO {-track}'

    def show_track_context_menu(self, track, global_pos):
        if track not in self.tracks:
            return
        menu=QMenu(self)
        menu.addAction('Spur umbenennen …',lambda:self.rename_track(track))
        delete=menu.addAction('Leere Spur löschen',lambda:self.delete_track(track))
        delete.setEnabled(not any(clip.track == track for clip in self.clips))
        menu.exec(global_pos)

    def rename_track(self, track):
        if self.worker or track not in self.tracks or self.track_locked(track):
            return self.statusBar().showMessage('Diese Spur ist gesperrt.',3000) if track in self.tracks else None
        current=self.track_names.get(track,self.default_track_name(track))
        name,ok=QInputDialog.getText(self,'Spur umbenennen','Neuer Spurname:',text=current)
        if not ok:
            return
        name=name.strip()
        self.checkpoint()
        if name and name != self.default_track_name(track):
            self.track_names[track]=name[:48]
        else:
            self.track_names.pop(track,None)
        self.changed()

    def delete_track(self, track):
        if self.worker or track not in self.tracks:
            return
        if self.track_locked(track):
            return self.statusBar().showMessage('Diese Spur ist gesperrt.',3000)
        if any(clip.track == track for clip in self.clips):
            return self.statusBar().showMessage('Die Spur enthält noch Clips. Verschiebe oder lösche sie zuerst.',5000)
        same_type=[value for value in self.tracks if (value > 0) == (track > 0)]
        if len(same_type) <= 1:
            return self.statusBar().showMessage('Mindestens eine Video- und eine Audiospur muss bleiben.',4000)
        self.checkpoint(); self.tracks=[value for value in self.tracks if value != track]
        self.track_states=normalize_track_states(self.track_states,self.tracks); self.track_names=normalize_track_names(self.track_names,self.tracks); self.changed()

    def extract_audio(self):
        c=self.current_clip()
        if not c or c.kind!='video' or not c.has_audio:return self.error('Wähle einen Videoclip mit Originalton.')
        if not self.require_unlocked(c):return
        source=Path(c.path)
        target_dir=self.state_dir/'extracted-audio'; target_dir.mkdir(parents=True,exist_ok=True)
        target=target_dir/(source.stem+'-'+uuid.uuid4().hex[:8]+'.wav')
        clip_snapshot=replace(c)
        tracks_snapshot=list(self.tracks)
        def operation(progress,cancel):
            args=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-i',str(source),
                  '-map','0:a:0','-vn','-c:a','pcm_s16le','-ar','48000','-ac','2',str(target)]
            proc=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
            while proc.poll() is None:
                if cancel.wait(.1):
                    proc.terminate()
                    try: proc.wait(timeout=3)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                    raise ExportCancelled()
            if proc.returncode:
                detail=(proc.stderr.read() if proc.stderr else '').strip()
                raise ValueError('Audio konnte nicht extrahiert werden.'+(('\n'+detail) if detail else ''))
            return str(target)
        self.start_job('Audiospur wird aus dem Video extrahiert …',operation,
                       lambda result:self.extracted_audio_done(result,clip_snapshot,tracks_snapshot))

    def start_background_removal(self):
        """Generate a local transparent derivative for the selected clip."""
        c=self.current_clip()
        if not c or c.kind!='video' or c.source_type not in ('video','image'):
            return self.error('Wähle einen Video- oder Bildclip für die Hintergrundfreistellung.')
        if self.worker or not self.require_unlocked(c):
            return
        source=Path(c.path)
        target_dir=self.state_dir/'ai-media'; target_dir.mkdir(parents=True,exist_ok=True)
        suffix='.png' if c.source_type=='image' else '.mov'
        target=target_dir/(source.stem+'-'+c.uid[:10]+'-background'+suffix)
        uid=c.uid
        def operation(progress,cancel):
            try:
                return remove_background_media(source,target,progress,cancel)
            except AIToolError:
                if cancel.is_set():
                    raise ExportCancelled()
                raise
        self.start_job('Lokale KI entfernt den Hintergrund …',operation,
                       lambda result:self.background_removal_done(result,uid))

    def background_removal_done(self,result,uid):
        if not result['ok']:
            return self.job_error(result)
        c=next((value for value in self.clips if value.uid==uid),None)
        if not c:
            return self.statusBar().showMessage('Clip wurde während der Verarbeitung entfernt.',5000)
        try:
            candidate=replace(c,background_removal_enabled=True,background_removed_path=str(result['value']))
            proposed=[candidate if value.uid==uid else value for value in self.clips]
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed(); self.fill_inspector()
            self.statusBar().showMessage('Hintergrund entfernt · transparente lokale Datei ist aktiv.',6000)
        except Exception as exc:
            self.error(exc)

    def clear_background_removal(self):
        c=self.current_clip()
        if not c or c.kind!='video' or not c.background_removed_path:
            return
        if self.worker or not self.require_unlocked(c):
            return
        candidate=replace(c,background_removal_enabled=False,background_removed_path='')
        self.checkpoint(); self.clips=[candidate if value.uid==c.uid else value for value in self.clips]; self.changed()

    def start_motion_tracking(self):
        """Track the inspector rectangle through one local video clip."""
        c=self.current_clip()
        if not c or c.kind!='video' or c.source_type!='video':
            return self.error('Wähle einen normalen Videoclip für Motion-Tracking.')
        if self.worker or not self.require_unlocked(c):
            return
        region=(self.mask_x.value()/100,self.mask_y.value()/100,
                self.mask_width.value()/100,self.mask_height.value()/100)
        if region[0]+region[2] > 1.000001 or region[1]+region[3] > 1.000001:
            return self.error('Der Trackingbereich muss vollständig im Bild liegen.')
        uid=c.uid
        def operation(progress,cancel):
            try:
                return track_motion(c.path,c.start,c.end,region,progress,cancel)
            except AIToolError:
                if cancel.is_set():
                    raise ExportCancelled()
                raise
        self.start_job('Lokales Motion-Tracking wird berechnet …',operation,
                       lambda result:self.motion_tracking_done(result,uid))

    def start_mask_tracking(self):
        """Track a Bezier mask through the same local object tracker."""
        c=self.current_clip()
        if not c or c.kind!='video' or c.source_type!='video' or c.mask_type!='bezier' or len(c.mask_points)<3:
            return self.error('Wähle eine Bezier-Maske mit mindestens drei Punkten.')
        self.start_motion_tracking()

    def motion_tracking_done(self,result,uid):
        if not result['ok']:
            return self.job_error(result)
        c=next((value for value in self.clips if value.uid==uid),None)
        if not c:
            return self.statusBar().showMessage('Clip wurde während des Trackings entfernt.',5000)
        # Tracking operates on source seconds; render filters see clip-local
        # seconds after speed processing.  Fixed-speed clips therefore map
        # source time by 1/speed.  Speed-ramp clips use the base speed as a
        # stable approximation and remain fully editable afterwards.
        divisor=max(.25,float(c.speed))
        points=[]
        for point in result['value']:
            value=dict(point); value['time']=round(min(c.length,max(0.0,float(point['time'])/divisor)),6)
            points.append(value)
        points.sort(key=lambda value:float(value['time']))
        unique=[]
        for point in points:
            if unique and abs(float(unique[-1]['time'])-float(point['time'])) <= 1e-7:
                unique[-1]=point
            else:
                unique.append(point)
        try:
            candidate=replace(c,tracking_keyframes=unique)
            if c.mask_type == 'bezier' and len(c.mask_points) >= 3:
                candidate=replace(candidate,mask_path_keyframes=mask_path_keyframes_from_tracking(candidate))
            proposed=[candidate if value.uid==uid else value for value in self.clips]
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed(); self.fill_inspector()
            extra=' · Bezier-Maske animiert' if candidate.mask_path_keyframes else ''
            self.statusBar().showMessage(f'Motion-Tracking fertig · {len(unique)} Punkte gespeichert.{extra}',6000)
        except Exception as exc:
            self.error(exc)

    def start_auto_reframe(self):
        """Detect a local face focus path for the selected video clip."""
        c=self.current_clip()
        if not c or c.kind!='video' or c.source_type!='video':
            return self.error('Wähle einen normalen Videoclip für Auto-Reframe.')
        if self.worker or not self.require_unlocked(c):
            return
        format_name=self.auto_reframe_format.currentData() or 'project'
        try:
            target_aspect=auto_reframe_aspect(format_name,PRESETS[self.preset.currentText()])
        except (KeyError,ValueError) as exc:
            return self.error(exc)
        uid=c.uid
        def operation(progress,cancel):
            try:
                return auto_reframe_video(c.path,c.start,c.end,target_aspect,progress,cancel)
            except AIToolError:
                if cancel.is_set():
                    raise ExportCancelled()
                raise
        self.start_job('Lokales Auto-Reframe wird analysiert …',operation,
                       lambda result:self.auto_reframe_done(result,uid,format_name))

    def auto_reframe_done(self,result,uid,format_name):
        if not result['ok']:
            return self.job_error(result)
        c=next((value for value in self.clips if value.uid==uid),None)
        if not c:
            return self.statusBar().showMessage('Clip wurde während des Auto-Reframes entfernt.',5000)
        divisor=max(.25,float(c.speed))
        points=[]
        for point in result['value']:
            value=dict(point)
            value['time']=round(min(c.length,max(0.0,float(point['time'])/divisor)),6)
            points.append(value)
        points.sort(key=lambda value:float(value['time']))
        unique=[]
        for point in points:
            if unique and abs(float(unique[-1]['time'])-float(point['time'])) <= 1e-7:
                unique[-1]=point
            else:
                unique.append(point)
        try:
            candidate=replace(c,auto_reframe_enabled=True,auto_reframe_format=format_name,
                              auto_reframe_keyframes=unique)
            proposed=[candidate if value.uid==uid else value for value in self.clips]
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.changed(); self.fill_inspector()
            detected=sum(1 for point in unique if float(point.get('score',0.0)) > 0)
            self.statusBar().showMessage(
                f'Auto-Reframe fertig · {len(unique)} Fokus-Punkte · {detected} mit Gesichtserkennung.',6000)
        except Exception as exc:
            self.error(exc)

    def clear_auto_reframe(self):
        c=self.current_clip()
        if not c or c.kind!='video' or not c.auto_reframe_keyframes:
            return
        if self.worker or not self.require_unlocked(c):
            return
        candidate=replace(c,auto_reframe_enabled=False,auto_reframe_keyframes=[])
        self.checkpoint(); self.clips=[candidate if value.uid==c.uid else value for value in self.clips]; self.changed()

    def start_beat_analysis(self):
        c=self.current_clip()
        if not c or c.kind not in ('video','audio') or not c.has_audio or c.source_type=='adjustment':
            return self.error('Wähle einen Video- oder Audioclip mit Ton für Beat-Sync.')
        if self.worker or not self.require_unlocked(c):
            return
        uid=c.uid
        def operation(progress,cancel):
            try:
                return analyze_beats(c.path,c.start,c.end,progress,cancel)
            except AIToolError:
                if cancel.is_set():
                    raise ExportCancelled()
                raise
        self.start_job('Lokale Beat-Erkennung wird berechnet …',operation,
                       lambda result:self.beat_analysis_done(result,uid))

    def beat_analysis_done(self,result,uid):
        if not result['ok']:
            return self.job_error(result)
        c=next((value for value in self.clips if value.uid==uid),None)
        if not c:
            return self.statusBar().showMessage('Clip wurde während der Beat-Erkennung entfernt.',5000)
        divisor=max(.25,float(c.speed))
        beat_markers=[marker for marker in self.markers
                      if not (marker.get('kind') == 'beat' and c.position-1e-6 <= float(marker.get('time',0)) <= c.finish+1e-6)]
        for index, beat in enumerate(result['value'].get('beats', []), 1):
            time=c.position+min(c.length,max(0.0,float(beat)/divisor))
            beat_markers.append({'time':round(time,6),'label':f'Beat {index}','kind':'beat','color':'#ff7edb'})
        try:
            normalized=normalize_markers(beat_markers,length(self.clips))
            self.checkpoint(); self.markers=normalized; self.changed()
            bpm=result['value'].get('bpm',0.0)
            self.statusBar().showMessage(
                f"Beat-Sync fertig · {len(result['value'].get('beats',[]))} Beats"
                + (f" · ca. {bpm:.0f} BPM" if bpm else ''),6000)
        except Exception as exc:
            self.error(exc)

    def start_text_based_cut(self):
        """Transcribe one clip locally and remove pauses/filler words."""
        c=self.current_clip()
        if not c or c.kind not in ('video','audio') or c.source_type not in ('video','audio') or not c.has_audio:
            return self.error('Wähle ein Video oder Audio mit Ton für den Textschnitt.')
        if self.worker or not self.require_unlocked(c):
            return
        source=Path(c.path).expanduser().resolve(); uid=c.uid
        if not source.is_file():
            return self.error(f'Die Quelldatei wurde nicht gefunden:\n{source}')
        divisor=max(.25,float(c.speed))

        def operation(progress,cancel):
            payload=transcribe_media(source,model_size='base',language='auto',
                                     cache_dir=self.state_dir/'whisper-models',
                                     progress=progress,cancel=cancel)
            mapped=[]
            for cue in payload.get('cues',[]):
                try:
                    source_start=float(cue['start']); source_end=float(cue['end'])
                except (KeyError,TypeError,ValueError):
                    continue
                if source_end <= c.start+1e-7 or source_start >= c.end-1e-7:
                    continue
                local_start=max(c.start,source_start)-c.start
                local_end=min(c.end,source_end)-c.start
                item=dict(cue,start=round(local_start/divisor,6),end=round(local_end/divisor,6))
                words=[]
                for word in cue.get('words',[]):
                    try:
                        word_start=max(c.start,float(word['start']))-c.start
                        word_end=min(c.end,float(word['end']))-c.start
                    except (KeyError,TypeError,ValueError):
                        continue
                    if word_end > 0 and word_start < c.end-c.start:
                        words.append(dict(word,start=round(max(0,word_start)/divisor,6),
                                          end=round(max(0,word_end)/divisor,6)))
                if words: item['words']=words
                mapped.append(item)
            plan=build_text_edit_plan(mapped,c.length)
            plan['language']=payload.get('language','auto')
            plan['cue_count']=len(mapped)
            return plan
        self.start_job('Textbasierter Schnitt wird lokal analysiert …',operation,
                       lambda result:self.text_based_cut_done(result,uid))

    def text_based_cut_done(self,result,uid):
        if not result['ok']:
            return self.job_error(result)
        c=next((value for value in self.clips if value.uid==uid),None)
        if not c:
            return self.statusBar().showMessage('Clip wurde während der Textanalyse entfernt.',5000)
        plan=result['value']
        removed=float(plan.get('removed_seconds',0.0))
        if removed < .06:
            return self.error('Keine längeren Pausen oder Füllwörter erkannt.')
        try:
            segments=cut_clip_ranges(c,plan.get('keep_ranges',[]))
            old_finish=c.finish
            actual_removed=max(0.0,c.length-sum(value.length for value in segments))
            if actual_removed < .01:
                return self.error('Der Textschnitt hat keine verwertbare Änderung gefunden.')
            removed_ranges=[(float(start),float(end)) for start,end in plan.get('removed_ranges',[])]

            def compact_marker_time(time):
                time=float(time)
                if time < c.position-1e-7:
                    return time
                if time > old_finish+1e-7:
                    return max(0.0,time-actual_removed)
                local=max(0.0,min(c.length,time-c.position)); shift=0.0
                for start,end in removed_ranges:
                    if local >= end:
                        shift += end-start
                    elif local > start:
                        local=start; break
                return c.position+max(0.0,local-shift)

            proposed=[]
            for value in self.clips:
                if value.uid==uid:
                    continue
                if value.track==c.track and value.position >= old_finish-1e-6:
                    proposed.append(replace(value,position=max(0.0,value.position-actual_removed)))
                else:
                    proposed.append(value)
            proposed.extend(segments)
            markers=[dict(marker,time=round(compact_marker_time(marker['time']),6)) for marker in self.markers]
            normalized_markers=normalize_markers(markers,length(proposed))
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.markers=normalized_markers
            self.selection=[value.uid for value in segments]; self.current=segments[-1].uid; self.changed()
            self.statusBar().showMessage(
                f'Textschnitt fertig · {actual_removed:.2f} s entfernt · '
                f'{plan.get("filler_segments",0)} Füllwort-Segmente · {len(segments)} Teile',7000)
        except Exception as exc:
            self.error(exc)

    def clear_beat_markers(self):
        if self.worker:
            return
        markers=[marker for marker in self.markers if marker.get('kind') != 'beat']
        if len(markers) == len(self.markers):
            return
        self.checkpoint(); self.markers=normalize_markers(markers,length(self.clips)); self.changed()

    def start_auto_cut(self):
        """Find beats and hard scene changes, then split at useful points."""
        c=self.current_clip()
        if not c or c.kind!='video' or c.source_type!='video':
            return self.error('Wähle einen normalen Videoclip für Beat-/Szenen-Auto-Cut.')
        if self.worker or not self.require_unlocked(c):
            return
        uid=c.uid; divisor=max(.25,float(c.speed))
        def operation(progress,cancel):
            try:
                if c.has_audio:
                    beat_data=analyze_beats(c.path,c.start,c.end,
                                            lambda value:progress(int(value*.45)),cancel)
                else:
                    beat_data={'beats':[],'bpm':0.0}
                    progress(45)
                scenes=detect_scene_changes(c.path,c.start,c.end,
                                            lambda value:progress(45+int(value*.55)),cancel)
                points=build_auto_cut_points(beat_data,scenes,c.length)
                return {'points':[round(float(value)/divisor,6) for value in points],
                        'beats':len(beat_data.get('beats',[])), 'scenes':len(scenes),
                        'bpm':beat_data.get('bpm',0.0)}
            except AIToolError:
                if cancel.is_set():
                    raise ExportCancelled()
                raise
        self.start_job('Beats und Szenen werden lokal analysiert …',operation,
                       lambda result:self.auto_cut_done(result,uid))

    def auto_cut_done(self,result,uid):
        if not result['ok']:
            return self.job_error(result)
        c=next((value for value in self.clips if value.uid==uid),None)
        if not c:
            return self.statusBar().showMessage('Clip wurde während des Auto-Cuts entfernt.',5000)
        payload=result['value']; points=payload.get('points',[])
        if not points:
            return self.error('Keine stabilen Beat- oder Szenen-Schnittpunkte erkannt.')
        try:
            segments=split_clip_at_times(c,points)
            if len(segments)<2:
                return self.error('Die erkannten Punkte liegen zu dicht für einen sichtbaren Schnitt.')
            proposed=[value for value in self.clips if value.uid!=uid]+segments
            validate_timeline(proposed,self.tracks)
            self.checkpoint(); self.clips=proposed; self.selection=[value.uid for value in segments]; self.current=segments[-1].uid; self.changed()
            self.statusBar().showMessage(
                f'Beat-/Szenen-Auto-Cut fertig · {len(segments)-1} Schnitte · '
                f'{payload.get("beats",0)} Beats · {payload.get("scenes",0)} Szenen',7000)
        except Exception as exc:
            self.error(exc)

    def clear_motion_tracking(self):
        c=self.current_clip()
        if not c or c.kind!='video' or not c.tracking_keyframes:
            return
        if self.worker or not self.require_unlocked(c):
            return
        candidate=replace(c,tracking_keyframes=[])
        self.checkpoint(); self.clips=[candidate if value.uid==c.uid else value for value in self.clips]; self.changed()

    def set_object_removal_enabled(self, enabled=True):
        c=self.current_clip()
        if not c or c.kind!='video' or c.source_type=='adjustment' or self.worker:
            return
        if not self.require_unlocked(c):
            return
        self.object_removal_enabled.setChecked(bool(enabled))
        self.apply_properties()

    # Compatibility helper for the old in-memory action used by older projects/tests.
    # The visible button intentionally uses extract_audio(), which creates a real WAV.
    def detach_audio(self):
        c=self.current_clip()
        if not c or c.kind!='video' or not c.has_audio:
            return self.error('Wähle einen Videoclip mit Originalton.')
        if not self.require_unlocked(c):return
        proposed=None
        for track in sorted((t for t in self.tracks if t<0),reverse=True):
            candidate=replace(c,uid=uuid.uuid4().hex,track=track,kind='audio')
            try:
                validate_timeline(self.clips+[candidate],self.tracks); proposed=candidate; break
            except ValueError:
                continue
        self.checkpoint()
        if proposed is None:
            track=min(self.tracks+[0])-1; self.tracks.append(track)
            self.track_states=normalize_track_states(self.track_states,self.tracks); self.track_names=normalize_track_names(self.track_names,self.tracks)
            proposed=replace(c,uid=uuid.uuid4().hex,track=track,kind='audio')
        self.clips=[replace(v,volume=0) if v.uid==c.uid else v for v in self.clips]+[proposed]
        self.selection=[proposed.uid]; self.current=proposed.uid; self.changed()

    def extracted_audio_done(self,result,source_clip,tracks_snapshot):
        if not result['ok']:
            return self.job_error(result)
        try:
            audio=import_clip(result['value'])
            end=min(source_clip.end,audio.duration)
            start=min(source_clip.start,max(0,end-MIN_CLIP))
            if end-start < MIN_CLIP:
                raise ValueError('Die extrahierte Audiospur ist zu kurz für diesen Clip.')
            proposed=None; chosen_tracks=list(self.tracks)
            for track in sorted((t for t in self.tracks if t<0),reverse=True):
                candidate=replace(audio,uid=uuid.uuid4().hex,track=track,position=source_clip.position,
                                  start=start,end=end,volume=source_clip.volume,
                                  linked_source_uid=source_clip.uid)
                try:
                    validate_timeline(self.clips+[candidate],self.tracks); proposed=candidate; break
                except ValueError:
                    continue
            if proposed is None:
                track=min(self.tracks+[0])-1
                chosen_tracks.append(track)
                proposed=replace(audio,uid=uuid.uuid4().hex,track=track,position=source_clip.position,
                                 start=start,end=end,volume=source_clip.volume,
                                 linked_source_uid=source_clip.uid)
            validate_timeline(self.clips+[proposed],chosen_tracks)
            self.checkpoint(); self.tracks=chosen_tracks; self.track_states=normalize_track_states(self.track_states,self.tracks); self.track_names=normalize_track_names(self.track_names,self.tracks)
            self.clips=[replace(v,volume=0,linked_source_uid=source_clip.uid)
                        if v.uid==source_clip.uid else v for v in self.clips]+[proposed]
            self.assets.append(proposed); self.selection=[proposed.uid]; self.current=proposed.uid; self.prepare_visuals([proposed]); self.changed()
            self.statusBar().showMessage('Audio extrahiert und auf eine eigene Audiospur gelegt.',6000)
        except Exception as exc:
            self.error(exc)

    def import_dialog(self):
        if self.worker:return
        paths,_=QFileDialog.getOpenFileNames(self,'Video / Audio importieren','',
          'Medien (*.mp4 *.mov *.mkv *.webm *.avi *.m4v *.mp3 *.wav *.flac *.ogg *.m4a *.aac *.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;Alle Dateien (*)')
        self.import_paths(paths)

    def import_sequence_dialog(self):
        if self.worker:
            return
        paths,_=QFileDialog.getOpenFileNames(self,'Bildsequenz importieren','',
          'Bilder (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;Alle Dateien (*)')
        if not paths:
            return
        fps,ok=QInputDialog.getDouble(self,'Bildsequenz','Bildrate der Sequenz:',24.0,1.0,120.0,2)
        if ok:
            self.import_paths(paths,sequence_fps=fps)

    def automatic_subtitle_dialog(self):
        if self.worker:
            return
        sources=[]; seen=set()
        candidates=[]
        current=self.current_clip()
        if current is not None:
            candidates.append(current)
        candidates.extend(self.assets)
        candidates.extend(self.clips)
        for candidate in candidates:
            if candidate.kind not in ('video','audio') or candidate.source_type in ('image','image_sequence','adjustment'):
                continue
            path=str(candidate.path or '').strip()
            if not path or path in seen:
                continue
            seen.add(path)
            title=f'{Path(path).name} · {"Video" if candidate.kind == "video" else "Audio"}'
            sources.append((title,path))
        dialog=AutomaticSubtitleDialog(sources,self)
        if dialog.exec()!=QDialog.Accepted:
            return
        settings=dialog.settings()
        self.start_transcription(settings['path'],settings['language'],settings['model_size'])

    def start_transcription(self,path,language='auto',model_size='base'):
        if self.worker:
            return
        if not path:
            return self.error('Wähle zuerst ein Video oder eine Audiodatei für die Spracherkennung aus.')
        source=Path(path).expanduser().resolve()
        if not source.is_file():
            return self.error(f'Die Quelldatei wurde nicht gefunden:\n{source}')

        def operation(progress,cancel):
            return transcribe_media(source,model_size=model_size,language=language,
                                    cache_dir=self.state_dir/'whisper-models',
                                    progress=progress,cancel=cancel)
        self.start_job('Automatische Untertitel werden erstellt …',operation,
                       lambda result:self.transcription_done(result,source))

    def transcription_done(self,result,source):
        if not result['ok']:
            return self.job_error(result)
        payload=result['value']
        cues=payload.get('cues',[]) if isinstance(payload,dict) else payload
        if not cues:
            return self.error('Keine gesprochenen Worte im Medium erkannt.')
        try:
            count=self.add_subtitle_cues(cues,Path(source).name,'automatisch erstellt')
            detected=str(payload.get('language','auto')).upper() if isinstance(payload,dict) else 'AUTO'
            self.statusBar().showMessage(f'{count} Untertitel automatisch erstellt · Sprache {detected}',6000)
        except Exception as exc:
            self.error(exc)

    def import_subtitle_dialog(self):
        if self.worker:
            return
        path,_=QFileDialog.getOpenFileName(self,'Untertitel importieren','','Untertitel (*.srt *.vtt);;Alle Dateien (*)')
        if path:
            self.import_subtitles(path)

    def import_subtitles(self,path):
        if self.worker:
            return
        def operation(progress,cancel):
            if cancel.is_set():
                raise ExportCancelled()
            cues=parse_subtitle_file(path)
            progress(100)
            return cues
        self.start_job('Untertitel werden gelesen …',operation,
                       lambda result:self.subtitle_import_done(result,path))

    def subtitle_import_done(self,result,path):
        if not result['ok']:
            return self.job_error(result)
        try:
            self.add_subtitle_cues(result['value'],Path(path).name,'importiert')
        except Exception as exc:
            self.error(exc)

    def add_subtitle_cues(self,cues,source_label,action='importiert'):
        if not cues:
            raise ValueError('Keine gültigen Untertitel gefunden.')
        existing=list(self.clips)
        tracks=list(self.tracks)
        video_tracks=[track for track in tracks if track > 0]
        next_track=max(video_tracks,default=0)+1
        subtitle_tracks=[]
        new_clips=[]

        def overlaps(track,start,end):
            return any(item.track == track and item.position < end - 1e-7 and item.finish > start + 1e-7
                       for item in existing + new_clips)

        for cue in cues:
            start=float(cue['start']); end=float(cue['end'])
            track=next((candidate for candidate in subtitle_tracks if not overlaps(candidate,start,end)),None)
            if track is None:
                track=next_track; next_track+=1; subtitle_tracks.append(track); tracks.append(track)
            duration=end-start
            candidate=Clip('',864000.0,start=0,end=duration,position=start,track=track,kind='text',
                           has_audio=False,text=cue['text'],source_type='text')
            new_clips.append(candidate)
        proposed=existing+new_clips
        validate_timeline(proposed,tracks)
        self.checkpoint(); self.tracks=tracks
        self.track_states=normalize_track_states(self.track_states,self.tracks)
        self.track_names=normalize_track_names(self.track_names,self.tracks)
        for index,track in enumerate(subtitle_tracks,1):
            self.track_names[track]='Untertitel' if index == 1 else f'Untertitel {index}'
        self.clips=proposed; self.selection=[clip.uid for clip in new_clips]
        self.current=new_clips[-1].uid if new_clips else None; self.changed()
        self.statusBar().showMessage(f'{len(new_clips)} Untertitel aus {source_label} {action}.',5000)
        return len(new_clips)

    def import_paths(self,paths,sequence_fps=None):
        if not paths or self.worker:return
        def operation(progress,cancel):
            assets=[]; errors=[]
            if sequence_fps is not None:
                try:
                    assets.append(import_image_sequence(paths,sequence_fps))
                    progress(100)
                except Exception as exc:
                    errors.append(str(exc))
                return assets,errors
            for i,path in enumerate(paths):
                if cancel.is_set():raise ExportCancelled()
                try:assets.append(import_clip(path))
                except Exception as exc:errors.append(str(exc))
                progress(int((i+1)/len(paths)*100))
            if cancel.is_set():raise ExportCancelled()
            return assets,errors
        self.start_independent_job('import','Medien werden geprüft …',operation,self.import_done)

    def import_done(self,result):
        if not result['ok']:return self.job_error(result)
        assets,errors=result['value']
        asset_key=lambda asset:(asset.source_type,tuple(asset.source_paths) if asset.source_paths else asset.path)
        known={asset_key(asset) for asset in self.assets}
        added=[asset for asset in assets if asset_key(asset) not in known]
        if added: self.checkpoint('Medien importieren')
        self.assets.extend(added); self.prepare_visuals(added); self.refresh_media()
        if added:self.changed()
        if added and self.performance_combo.currentData()=='smooth': QTimer.singleShot(0,self.performance_changed)
        if errors:self.error('\n'.join(errors))

    def open_media_panel(self):
        """Show the project media bin and keep the library panel out of the way."""
        if not hasattr(self, 'asset_library_panel'):
            return
        self.media_heading.setText('MEDIEN')
        for widget in self._media_controls:
            if widget is self.media_empty_hint:
                continue
            widget.show()
        self.library_stack.hide()
        self.media_empty_hint.setVisible(self.media_list.count() == 0)
        self.refresh_media()

    def open_library_panel(self):
        """Keep the old all-assets API available for projects and test helpers."""
        if not hasattr(self,'asset_library_panel'):
            return
        for widget in self._media_controls:
            widget.hide()
        self.media_heading.setText('ASSETS')
        catalog=list(library_items())+list(self.custom_library_items)
        self.media_count.setText(f'{len(catalog)} Assets')
        self.library_stack.setCurrentWidget(self.asset_library_panel)
        self.library_stack.show()
        self.asset_library_panel.set_scope(catalog,None)

    def open_sound_panel(self):
        """Show sounds without duplicating the feature-specific panels."""
        if not hasattr(self, 'asset_library_panel'):
            return
        for widget in self._media_controls:
            widget.hide()
        self.media_heading.setText('SOUND')
        self.media_count.setText(f'{len(self._library_items_for("sounds"))} Sounds')
        self.library_stack.setCurrentWidget(self.asset_library_panel)
        self.library_stack.show()
        self.asset_library_panel.set_scope(self._library_items_for('sounds'),'sounds')

    def open_preset_library(self, key):
        """Show one dedicated offline library in the media column."""
        panel_widget=self.library_panels.get(str(key)) if hasattr(self,'library_panels') else None
        if panel_widget is None:
            return
        for widget in self._media_controls:
            widget.hide()
        labels={
            'text':'TEXT', 'animations':'ANIMATIONEN', 'sticker':'STICKER', 'effects':'EFFEKTE',
            'transitions':'ÜBERGÄNGE', 'filters':'FILTER',
        }
        self.media_heading.setText(labels.get(str(key),str(key).upper()))
        self.media_count.setText(f'{panel_widget.list.count()} Presets')
        self.library_stack.setCurrentWidget(panel_widget)
        self.library_stack.show()
        panel_widget.refresh()

    def open_text_panel(self):
        self.open_preset_library('text')

    def open_animation_panel(self):
        self.open_preset_library('animations')

    def open_sticker_panel(self):
        self.open_preset_library('sticker')

    def open_effects_panel(self):
        self.open_preset_library('effects')

    def open_transitions_panel(self):
        self.open_preset_library('transitions')

    def open_filters_panel(self):
        self.open_preset_library('filters')

    def preview_library_item(self, item_id):
        item=self._library_item(item_id)
        if item is None:
            return
        if item.kind != 'sound':
            self.statusBar().showMessage('Dieses Preset wird direkt auf den ausgewählten Clip angewendet.',3000)
            return
        try:
            custom_path=item.parameters.get('path') if isinstance(item.parameters,dict) else None
            path=Path(custom_path).expanduser().resolve() if custom_path else library_sound_path(item.item_id,self.state_dir)
            if not path.is_file():
                raise ValueError(f'Die Sounddatei fehlt:\n{path}')
            self.library_player.stop()
            self.library_player.setSource(QUrl.fromLocalFile(str(path)))
            self.library_player.play()
            self.statusBar().showMessage(f'Vorschau: {item.title}',2000)
        except Exception as exc:
            self.error(exc)

    def _library_audio_track(self, preferred=None):
        """Choose an unlocked audio track, creating one only when necessary."""
        audio_tracks=[track for track in self.tracks if track < 0]
        if preferred in audio_tracks and not self.track_locked(preferred):
            return preferred
        available=[track for track in audio_tracks if not self.track_locked(track)]
        if available:
            return min(available, key=abs)
        # The caller adds this track together with the rest of the edit so a
        # single undo step can remove it again if all existing audio tracks
        # were locked.
        return min(audio_tracks or [0])-1

    def _library_insert_position(self, track, duration, preferred=None):
        """Find the first free slot on a target track from the playhead onward."""
        position=max(0.0,float(self.playhead if preferred is None else preferred))
        for clip in sorted((value for value in self.clips if value.track == track), key=lambda value:value.position):
            if clip.finish <= position + 1e-7:
                continue
            if clip.position >= position + duration - 1e-7:
                break
            position=clip.finish
        return position

    def _commit_library_clip(self, candidate, title):
        proposed=[candidate if item.uid==candidate.uid else item for item in self.clips]
        validate_timeline(proposed,self.tracks)
        self.checkpoint(title)
        self.clips=proposed; self.selection=[candidate.uid]; self.current=candidate.uid; self.changed()

    def _apply_library_effect(self, item):
        clip=self.current_clip()
        if not clip or clip.kind != 'video' or self.worker:
            return self.statusBar().showMessage('Wähle zuerst einen Video- oder Adjustment-Clip aus.',3000)
        if not self.require_unlocked(clip):
            return
        parameters=dict(item.parameters)
        preset_name=parameters.pop('effect_preset', 'clean')
        values=dict(EFFECT_PRESETS.get(preset_name, {}))
        values.update(parameters)
        candidate=replace(clip,effect_preset=preset_name,**values)
        try:
            self._commit_library_clip(candidate,f'Asset: {item.title}')
            self.statusBar().showMessage(f'Effekt „{item.title}“ angewendet.',3000)
        except Exception as exc:
            self.error(exc)

    def _apply_library_animation(self, item):
        clip=self.current_clip()
        if not clip or self.worker:
            return self.statusBar().showMessage('Wähle zuerst einen Clip für die Animation aus.',3000)
        if not self.require_unlocked(clip):
            return
        animation=item.parameters.get('animation')
        if clip.kind == 'text':
            text_animation={'text_fade':'fade','text_slide':'slide_left'}.get(animation)
            if text_animation is None:
                return self.statusBar().showMessage('Diese Animation ist für Textclips vorgesehen.',3000)
            candidate=replace(clip,text_animation=text_animation,
                              text_animation_duration=min(.8,max(.05,clip.length)))
        elif clip.kind == 'video' and clip.source_type != 'adjustment':
            duration=max(.1,float(clip.length))
            edge=min(.65,max(.05,duration*.35))
            start_scale=clip.video_scale; end_scale=clip.video_scale
            start_x=clip.video_x; end_x=clip.video_x
            start_y=clip.video_y; end_y=clip.video_y
            if animation == 'zoom_in':
                start_scale=max(.1,clip.video_scale*.84)
            elif animation == 'zoom_out':
                end_scale=max(.1,clip.video_scale*.84)
            elif animation == 'slide_left':
                start_x=.08
            elif animation == 'slide_up':
                start_y=.08
            else:
                return self.statusBar().showMessage('Diese Animation ist für Textclips vorgesehen.',3000)
            frames=[dict(time=0.0,scale=start_scale,x=start_x,y=start_y,
                         rotation=clip.rotation,opacity=clip.opacity,blur=clip.blur,curve='ease_out'),
                    dict(time=duration,scale=end_scale,x=end_x,y=end_y,
                         rotation=clip.rotation,opacity=clip.opacity,blur=clip.blur,curve='ease_in_out')]
            candidate=replace(clip,keyframes=frames)
        else:
            return self.statusBar().showMessage('Wähle einen normalen Video- oder Textclip aus.',3000)
        try:
            self._commit_library_clip(candidate,f'Asset: {item.title}')
            self.statusBar().showMessage(f'Animation „{item.title}“ angewendet.',3000)
        except Exception as exc:
            self.error(exc)

    def _apply_library_transition(self, item):
        clip=self.current_clip()
        if not clip or clip.kind not in ('video','audio') or clip.source_type == 'adjustment' or self.worker:
            return self.statusBar().showMessage('Wähle einen Video- oder Audioclip für den Übergang aus.',3000)
        if not self.require_unlocked(clip):
            return
        transition=item.parameters.get('transition_type','dissolve')
        duration=min(float(item.parameters.get('duration',.5)),max(0.0,clip.length))
        candidate=replace(clip,transition_type=transition,transition_duration=duration)
        try:
            self._commit_library_clip(candidate,f'Asset: {item.title}')
            self.statusBar().showMessage(f'Übergang „{item.title}“ angewendet.',3000)
        except Exception as exc:
            self.error(exc)

    def _apply_library_filter(self, item):
        clip=self.current_clip()
        if not clip or clip.kind != 'video' or clip.source_type == 'adjustment' or self.worker:
            return self.statusBar().showMessage('Wähle zuerst einen normalen Videoclip für den Filter aus.',3000)
        if not self.require_unlocked(clip):
            return
        preset=str(item.parameters.get('filter_preset','none'))
        if preset not in FILTER_PRESETS:
            return self.statusBar().showMessage('Dieses Filter-Preset ist nicht verfügbar.',3000)
        lut_path=str(item.parameters.get('lut_path') or '')
        candidate=replace(clip,filter_preset=preset,lut_path=lut_path)
        try:
            self._commit_library_clip(candidate,f'Asset: {item.title}')
            self.statusBar().showMessage(f'Filter „{item.title}“ angewendet.',3000)
        except Exception as exc:
            self.error(exc)

    def _insert_library_sticker(self, item):
        if self.worker:
            return
        if not any(c.kind == 'video' and c.source_type != 'adjustment' for c in self.clips):
            return self.error('Füge zuerst ein Video zur Timeline hinzu.')
        parameters=dict(item.parameters)
        position=max(0.0,min(self.playhead,length(self.clips)))
        duration=min(3.0,max(.5,length(self.clips)-position)) if length(self.clips)>position else 3.0
        track=max((track for track in self.tracks if track > 0),default=0)+1
        candidate=Clip('',864000.0,start=0.0,end=duration,position=position,track=track,
                       kind='text',has_audio=False,text=str(parameters.get('glyph','★')),
                       source_type='text',font_size=int(parameters.get('font_size',96)),
                       color=str(parameters.get('color','#ffffff')),font_family='DejaVu Sans',
                       font_bold=True,outline_width=2.0,outline_color='#101820',
                       shadow_size=2.0,shadow_color='#000000',background_enabled=False,
                       background_opacity=0.0,text_animation='fade',
                       text_animation_duration=.25,x=float(parameters.get('x',.5)),
                       y=float(parameters.get('y',.5)),display_name=item.title)
        try:
            proposed=self.clips+[candidate]
            validate_timeline(proposed,self.tracks+[track])
            self.checkpoint(f'Asset: {item.title} einfügen')
            self.tracks.append(track)
            self.track_states=normalize_track_states(self.track_states,self.tracks)
            self.track_names=normalize_track_names(self.track_names,self.tracks)
            self.track_names[track]=f'Sticker {sum(value.kind == "text" for value in self.clips)+1}'
            self.clips.append(candidate); self.selection=[candidate.uid]; self.current=candidate.uid
            self.changed()
            self.statusBar().showMessage(f'Sticker „{item.title}“ eingefügt.',3000)
        except Exception as exc:
            self.error(exc)

    def _insert_library_sound(self, item, position=None, track=None):
        if self.worker:
            return
        try:
            custom_path=item.parameters.get('path') if isinstance(item.parameters,dict) else None
            path=Path(custom_path).expanduser().resolve() if custom_path else library_sound_path(item.item_id,self.state_dir)
            if not path.is_file():
                raise ValueError(f'Die Sounddatei fehlt:\n{path}')
            existing=next((asset for asset in self.assets
                           if asset.path and Path(asset.path).resolve()==path.resolve()),None)
            if existing is None:
                asset=replace(import_clip(str(path)),display_name=item.title)
            else:
                asset=existing
                if not asset.display_name:
                    asset=replace(asset,display_name=item.title)
            target_track=self._library_audio_track(track)
            target_tracks=list(self.tracks)
            if target_track not in target_tracks:
                target_tracks.append(target_track)
            target_position=self._library_insert_position(target_track,asset.length,position)
            candidate=replace(asset,uid=uuid.uuid4().hex,position=target_position,track=target_track)
            validate_timeline(self.clips+[candidate],target_tracks)
            self.checkpoint('Asset: Sound einfügen')
            if target_tracks != self.tracks:
                self.tracks=target_tracks
                self.track_states=normalize_track_states(self.track_states,self.tracks)
                self.track_names=normalize_track_names(self.track_names,self.tracks)
            if existing is not None and asset.uid != existing.uid:
                self.assets=[asset if value.uid==existing.uid else value for value in self.assets]
            if existing is None:
                self.assets.append(asset)
            self.clips.append(candidate); self.selection=[candidate.uid]; self.current=candidate.uid
            self.prepare_visuals([asset]); self.changed()
            self.statusBar().showMessage(f'Sound „{item.title}“ eingefügt.',3000)
        except Exception as exc:
            self.error(exc)

    def use_library_item(self, item_id):
        """Apply a preset or insert a generated sound using existing editor data."""
        item=self._library_item(item_id)
        if item is None:
            return
        if item.kind == 'sound':
            self._insert_library_sound(item)
        elif item.kind == 'effect':
            self._apply_library_effect(item)
        elif item.kind == 'animation':
            self._apply_library_animation(item)
        elif item.kind == 'transition':
            self._apply_library_transition(item)
        elif item.kind == 'filter':
            self._apply_library_filter(item)
        elif item.kind == 'text_style':
            self.add_text(item.parameters if item.item_id.startswith('custom_') else item.parameters.get('style'))
        elif item.kind == 'sticker':
            self._insert_library_sticker(item)

    def handle_library_drop(self, item_id, position, track):
        item=self._library_item(item_id)
        if item is None or item.kind != 'sound':
            return
        self._insert_library_sound(item,position=float(position),track=int(track))

    def refresh_media(self):
        self.missing_media=missing_project_media(self.clips,self.assets)
        selected_item=self.media_list.currentItem() if hasattr(self,'media_list') else None
        selected_uid=selected_item.data(MediaList.ASSET_UID_ROLE) if selected_item is not None else None
        query=self.media_search.text().strip().casefold() if hasattr(self,'media_search') else ''
        filter_value=self.media_filter.currentData() if hasattr(self,'media_filter') else 'all'
        sort_value=self.media_sort.currentData() if hasattr(self,'media_sort') else 'order'
        favorites_only=self.media_favorites_only.isChecked() if hasattr(self,'media_favorites_only') else False
        rows=[]
        for index,c in enumerate(self.assets):
            icon='▦' if c.source_type=='image_sequence' else '▧' if c.source_type=='image' else '▸' if c.kind=='video' else '♫'
            label_kind='BILDSEQUENZ' if c.source_type=='image_sequence' else 'BILD' if c.source_type=='image' else c.kind.upper()
            referenced=[c.path]+list(c.source_paths)+([c.lut_path] if c.lut_path else [])
            offline=any(path and not Path(path).is_file() for path in referenced)
            category='sequence' if c.source_type=='image_sequence' else 'image' if c.source_type=='image' else 'video' if c.kind=='video' else 'audio'
            searchable=' '.join((Path(c.path).name,str(c.path),label_kind,category)).casefold()
            if query and query not in searchable:
                continue
            if filter_value not in ('all',category) and not (filter_value=='offline' and offline):
                continue
            if favorites_only and str(Path(c.path).resolve()) not in self.favorite_assets:
                continue
            rows.append((index,c,category,offline,icon,label_kind))
        if sort_value == 'name':
            rows.sort(key=lambda row:(Path(row[1].path).name.casefold(),row[0]))
        elif sort_value == 'type':
            rows.sort(key=lambda row:(row[5],Path(row[1].path).name.casefold(),row[0]))
        elif sort_value == 'duration':
            rows.sort(key=lambda row:(-float(row[1].duration),Path(row[1].path).name.casefold(),row[0]))
        self.media_list.setUpdatesEnabled(False); self.media_list.clear()
        for index,c,category,offline,icon,label_kind in rows:
            marker=('⚠  ' if offline else '')+('★  ' if str(Path(c.path).resolve()) in self.favorite_assets else '')
            item=QListWidgetItem(f'{marker}{icon}  {Path(c.path).name}\n{c.duration:.1f} s  ·  {label_kind}')
            poster=self.thumbnails.get(self.visual_key(c.path)) if hasattr(self,'thumbnails') else None
            if poster is not None and not poster.isNull():
                target=QSize(42,34) if getattr(self.media_list,'viewMode',lambda:QListWidget.IconMode)() == QListWidget.ListMode else QSize(116,66)
                item.setIcon(QIcon(QPixmap.fromImage(poster).scaled(target,Qt.KeepAspectRatio,Qt.SmoothTransformation)))
            item.setSizeHint(QSize(0,48) if getattr(self.media_list,'viewMode',lambda:QListWidget.IconMode)() == QListWidget.ListMode else QSize(132,96))
            item.setToolTip(c.path); item.setData(MediaList.ASSET_INDEX_ROLE,index); item.setData(MediaList.ASSET_UID_ROLE,c.uid); self.media_list.addItem(item)
        self.media_list.setUpdatesEnabled(True)
        if selected_uid:
            selected_row=next((row for row in range(self.media_list.count())
                               if self.media_list.item(row).data(MediaList.ASSET_UID_ROLE)==selected_uid),-1)
        else:
            selected_row=-1
        if selected_row >= 0:
            self.media_list.setCurrentRow(selected_row)
        elif self.media_list.count():
            self.media_list.setCurrentRow(0)
        if hasattr(self,'media_count'):
            total=len(self.assets); visible=len(rows)
            self.media_count.setText(f'{visible} / {total} Medien' if visible != total else f'{total} Medien')
        if hasattr(self,'media_empty_hint'):
            self.media_empty_hint.setVisible(not rows)
            if not self.assets:
                self.media_empty_hint.setText('Noch keine Medien\nImportiere ein Video, Audio oder Bild, um zu starten.')
            elif favorites_only:
                self.media_empty_hint.setText('Keine Favoriten sichtbar\nMarkiere ein Medium mit ☆, um es hier zu sammeln.')
            else:
                self.media_empty_hint.setText('Keine Medien passen zu diesem Filter\nSuche oder Filter zurücksetzen.')
        self.update_media_favorite_button()
        self.timeline.assets=self.assets if hasattr(self,'timeline') else []
        if hasattr(self,'proxy_box'):
            available=any(c.kind in ('video','audio') and c.source_type not in ('image','image_sequence')
                          and c.path and Path(c.path).is_file() for c in self.assets+self.clips)
            self.proxy_box.setEnabled(available)
            self.proxy_profile_combo.setEnabled(available)
            if not available and self.proxy_box.isChecked():
                self.proxy_box.setChecked(False)

    def prepare_visuals(self, assets):
        """Posters and waveforms are decoded off the GUI thread."""
        self.queue_visuals(assets)

    def jump_cut(self,direction):
        targets=sorted({v for c in self.clips for v in (c.position,c.finish)})
        choices=[v for v in targets if (v-self.playhead)*direction>1e-6]
        if choices: self.set_playhead(min(choices) if direction>0 else max(choices))

    def nudge_playhead(self, seconds):
        if self.worker:return
        self.set_playhead(max(0,min(length(self.clips),self.playhead+seconds)))

    def transport_stop(self):
        self.transport_rate_pending=None
        self.transport_timer.stop()
        self.transport_rate=0.0
        self.player.pause(); self.player.setPlaybackRate(1.0)
        self.play_button.setText('▶')

    def _start_transport(self, rate):
        if self.worker or not self.clips:
            return
        rate=float(rate)
        if not self.preview_is_current():
            self.transport_rate_pending=rate
            self.preview_play_requested=bool(self.preview_path and Path(self.preview_path).is_file())
            if self.preview_play_requested and rate > 0:
                self.mode='timeline'; self.audio.setVolume(1); self.player.setPlaybackRate(rate)
                self.load_player(self.preview_path,min(self.playhead,length(self.clips)),True)
                self.preview_status.setText('LETZTER GÜLTIGER STAND · Shuttle startet, neue Vorschau läuft im Hintergrund …')
            self.render_preview()
            return
        self.mode='timeline'; self.audio.setVolume(1); self.transport_rate=rate; self.update_source_monitor_controls()
        if rate < 0:
            if self.playhead <= .01:
                self.playhead=length(self.clips)
            self.player.pause(); self.transport_timer.start()
            self.statusBar().showMessage(f'J · rückwärts {abs(rate):g}×',2000)
            return
        self.transport_timer.stop()
        if self.playhead >= length(self.clips)-.02:
            self.playhead=0.0
        self.player.setPlaybackRate(rate)
        self.load_player(self.preview_path,self.playhead,True)
        self.statusBar().showMessage(f'L · vorwärts {rate:g}×',2000)

    def transport_j(self):
        if self.transport_rate < 0:
            self._start_transport(max(-4.0,self.transport_rate*2.0))
        else:
            self._start_transport(-1.0)

    def transport_k(self):
        self.transport_stop()
        self.statusBar().showMessage('K · Pause',2000)

    def transport_l(self):
        if self.transport_rate > 0:
            self._start_transport(min(4.0,self.transport_rate*2.0))
        else:
            self._start_transport(1.0)

    def transport_tick(self):
        if self.transport_rate >= 0 or not self.clips:
            self.transport_stop()
            return
        next_time=self.playhead + self.transport_rate*0.04
        if next_time <= 0:
            self.set_playhead(0)
            self.transport_stop()
            return
        self.set_playhead(next_time)

    def add_selected_asset(self):
        row=self.media_list.asset_index()
        if row<0 or self.worker:return
        a=self.assets[row]; selected=self.current_clip()
        compatible=[t for t in self.tracks if (t>0)==(a.kind=='video')]
        track=selected.track if selected and selected.track in compatible else min(compatible,key=abs)
        position=max((c.finish for c in self.clips if c.track==track),default=0)
        self.drop_asset(row,position,track)

    def drop_asset(self,index,position,track):
        if self.worker or not 0<=index<len(self.assets):return
        if self.track_locked(track):
            self.statusBar().showMessage('Diese Zielspur ist gesperrt.',3000)
            return
        a=self.assets[index]
        candidate=replace(a,position=position,track=track,uid=uuid.uuid4().hex)
        try:
            validate_timeline(self.clips+[candidate],self.tracks)
            self.checkpoint(); self.clips.append(candidate); self.selection=[candidate.uid]; self.current=candidate.uid; self.changed()
        except Exception as exc:self.error(exc)

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and not self.worker:event.acceptProposedAction()

    def dropEvent(self,event):
        paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        subtitle_paths=[path for path in paths if Path(path).suffix.lower() in ('.srt','.vtt')]
        media_paths=[path for path in paths if path not in subtitle_paths]
        if subtitle_paths:
            self.import_subtitles(subtitle_paths[0])
        if media_paths:
            self.import_paths(media_paths)
        event.acceptProposedAction()

    def zoom(self,value):
        old=self.timeline.scale; scroll=self.scroll.horizontalScrollBar()
        center,offset=self._zoom_anchor or ((scroll.value()+self.scroll.viewport().width()/2-self.timeline.LEFT)/old,self.scroll.viewport().width()/2)
        self.timeline.scale=float(value); self.timeline.refresh(self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection)
        self.timeline.resize(max(self.timeline.minimumWidth(),self.scroll.viewport().width()),self.timeline.height())
        scroll.setValue(int(center*value+self.timeline.LEFT-offset))

    def fit_timeline(self):
        width=self.scroll.viewport().width()-self.timeline.LEFT-35
        self.zoom_slider.setValue(max(2,min(200,int(width/max(5,length(self.clips))))))

    @staticmethod
    def _source_clock(seconds):
        seconds=max(0.0,float(seconds))
        return f'{int(seconds)//60:02}:{seconds%60:05.2f}'

    def _source_media_clip(self):
        """Return the active video/audio source shown in the source monitor."""
        clip=self.current_clip()
        if (self.mode!='source' or clip is None or clip.kind not in ('video','audio')
                or clip.source_type not in ('video','audio')):
            return None
        return clip

    def _activate_source_clip(self, clip):
        """Start a fresh transient In/Out session for a newly selected source."""
        if self.source_clip_uid!=clip.uid:
            self.source_clip_uid=clip.uid; self.source_in=None; self.source_out=None

    def _source_bounds(self, clip):
        """Return the effective source In/Out, clamped to the current clip."""
        start=clip.start if self.source_clip_uid!=clip.uid or self.source_in is None else self.source_in
        end=clip.end if self.source_clip_uid!=clip.uid or self.source_out is None else self.source_out
        start=max(clip.start,min(clip.end,start)); end=max(clip.start,min(clip.end,end))
        if end-start<MIN_CLIP:
            return clip.start,clip.end
        return start,end

    def _source_position(self, clip):
        """Return the current source time, using the player when available."""
        fallback=clip.start+max(0.0,min(clip.length,max(0.0,self.playhead-clip.position)))
        try:
            url=QUrl.fromLocalFile(str(clip.path))
            player_position=self.player.position()/1000.0
            if self.player.source()==url and clip.start-.1<=player_position<=clip.end+.1:
                return max(clip.start,min(clip.end,player_position))
        except (AttributeError,TypeError,ValueError):
            pass
        return max(clip.start,min(clip.end,fallback))

    def update_source_monitor_controls(self):
        """Refresh source-monitor labels and action availability."""
        if not hasattr(self,'source_in_button'):
            return
        clip=self.current_clip()
        active=self._source_media_clip() is not None
        for widget in (self.source_in_button,self.source_out_button,self.source_clear_button,
                       self.source_insert_button,self.source_overwrite_button):
            widget.setEnabled(active)
        if active:
            source_in,source_out=self._source_bounds(clip)
            marks=[]
            if self.source_in is not None: marks.append(f'I {self._source_clock(source_in)}')
            if self.source_out is not None: marks.append(f'O {self._source_clock(source_out)}')
            text='◉ Clip · '+(' · '.join(marks) if marks else 'gesamt')
            self.source_range_label.setText(text)
        elif clip is not None and clip.kind in ('video','audio') and clip.source_type in ('video','audio'):
            self.source_range_label.setText('◉ Clip · „Clip ansehen“ für In/Out')
        elif clip is not None and clip.source_type in ('image','image_sequence'):
            self.source_range_label.setText('◉ Standbild · keine In/Out-Marken')
        else:
            self.source_range_label.setText('◉ Kein Clip ausgewählt')

    def set_source_in(self):
        clip=self._source_media_clip()
        if clip is None:
            return self.statusBar().showMessage('Öffne zuerst einen Video- oder Audioclip mit „Clip ansehen“.',3500)
        source_time=self._source_position(clip); _,source_out=self._source_bounds(clip)
        if source_time>=source_out-MIN_CLIP:
            return self.statusBar().showMessage('Der Quell-In muss vor dem Quell-Out liegen.',3000)
        self.source_in=round(source_time,6); self.update_source_monitor_controls()
        self.statusBar().showMessage(f'Quell-In bei {self._source_clock(source_time)} gesetzt.',2500)

    def set_source_out(self):
        clip=self._source_media_clip()
        if clip is None:
            return self.statusBar().showMessage('Öffne zuerst einen Video- oder Audioclip mit „Clip ansehen“.',3500)
        source_time=self._source_position(clip); source_in,_=self._source_bounds(clip)
        if source_time<=source_in+MIN_CLIP:
            return self.statusBar().showMessage('Der Quell-Out muss nach dem Quell-In liegen.',3000)
        self.source_out=round(source_time,6); self.update_source_monitor_controls()
        self.statusBar().showMessage(f'Quell-Out bei {self._source_clock(source_time)} gesetzt.',2500)

    def clear_source_marks(self):
        if self._source_media_clip() is None:
            return self.statusBar().showMessage('Öffne zuerst einen Video- oder Audioclip mit „Clip ansehen“.',3500)
        self.source_in=None; self.source_out=None; self.update_source_monitor_controls()
        self.statusBar().showMessage('Quell-In/Out zurückgesetzt · gesamter Clip aktiv.',2500)

    def _source_candidate(self):
        """Build a clean timeline candidate from the marked source range."""
        clip=self._source_media_clip()
        if clip is None:
            self.statusBar().showMessage('Öffne zuerst einen Video- oder Audioclip mit „Clip ansehen“.',3500)
            return None
        source_in,source_out=self._source_bounds(clip)
        if source_out-source_in<MIN_CLIP:
            self.statusBar().showMessage('Der Quellbereich ist zu kurz.',3000)
            return None
        if self.track_locked(clip.track):
            self.statusBar().showMessage('Die Zielspur ist gesperrt.',3000)
            return None
        return replace(clip,uid=uuid.uuid4().hex,position=max(0.0,self.playhead),
                       start=source_in,end=source_out,group_id='',
                       transition_type='none',transition_duration=0.0,
                       fade_in=0.0,fade_out=0.0,freeze_frame=False,freeze_duration=0.0,
                       keyframes=[],volume_keyframes=[],speed_keyframes=[],
                       source_paths=list(clip.source_paths))

    def insert_source_range(self):
        candidate=self._source_candidate()
        if candidate is None:return
        try:
            self._insert_candidates_ripple([candidate])
        except Exception as exc:
            self.error(exc)

    def overwrite_source_range(self):
        candidate=self._source_candidate()
        if candidate is None:return
        try:
            self._overwrite_candidates([candidate])
        except Exception as exc:
            self.error(exc)

    def set_playhead(self,time):
        self.playhead=max(0,min(length(self.clips),float(time))); self.timeline.set_playhead(self.playhead); self.update_time()
        self.refresh_view_geometry()
        if self.mode=='timeline' and self.direct_preview_is_current():
            self._load_direct_clip_at_playhead(self.player.playbackState()==QMediaPlayer.PlayingState)
        elif self.mode=='timeline' and self.preview_is_current():
            self.player.setPosition(int(min(self.playhead,length(self.clips))*1000))
        elif (self.mode=='timeline' and self.preview_path and Path(self.preview_path).is_file()
              and self.player.source().isLocalFile()):
            # Seek the last valid composition immediately; a newer render can
            # still replace it later without blocking the transport.
            self.player.setPosition(int(self.playhead*1000))
        elif self.mode=='source' and self.current_clip():
            c=self.current_clip()
            if c.position<=time<=c.finish:
                source_time=c.start+time-c.position
                source_in,source_out=self._source_bounds(c)
                self.player.setPosition(int(max(source_in,min(source_out,source_time))*1000))
        self.update_source_monitor_controls()

    def seek_slider(self,value):
        self.set_playhead(value/10000*length(self.clips))

    def update_time(self):
        def clock(t):return f'{int(t)//60:02}:{t%60:04.1f}'
        total=length(self.clips); self.time_label.setText(f'{clock(self.playhead)} / {clock(total)}')
        if not self.seek.isSliderDown():self.seek.setValue(int(min(1,self.playhead/total)*10000) if total else 0)

    def play_state(self,state):
        if state==QMediaPlayer.PlayingState:
            self.follow_suspended=False
            self.play_button.setText(f'Ⅱ {self.transport_rate:g}×' if self.transport_rate else 'Ⅱ')
        else:
            self.play_button.setText('▶')

    def position_changed(self,ms):
        if self.pending_seek or self.compare_active:return
        if self.mode=='timeline':
            if self.direct_preview_is_current():
                clips=self._direct_preview_clips()
                clip=next((value for value in clips if value.uid==self.direct_clip_uid),None)
                if clip is None:
                    selected=self._direct_clip_at(self.playhead,clips)
                    clip=selected[1] if selected else None
                if clip is None:
                    return
                local=max(0.0,min(clip.length,ms/1000.0-clip.start))
                self.playhead=clip.position+local
                if self.playhead>=clip.finish-.04:
                    index=next((index for index,value in enumerate(clips) if value.uid==clip.uid),-1)
                    if index+1<len(clips):
                        self.playhead=clips[index+1].position
                        self._load_direct_clip_at_playhead(True)
                    else:
                        self.playhead=length(self.clips); self.player.pause()
                self.timeline.set_playhead(self.playhead); self.update_time()
                self.follow_playhead(); self.refresh_view_geometry(); self.update_source_monitor_controls()
                return
            if self.preview_is_current():
                self.playhead=ms/1000
            elif self.preview_path and Path(self.preview_path).is_file():
                # The player may still be showing the previous valid mix while
                # the edited multitrack revision renders in the background.
                self.playhead=max(0.0,min(length(self.clips),ms/1000.0))
            else:
                return
        else:
            c=self.current_clip()
            if not c:return
            local=max(0,min(c.length,ms/1000-c.start)); self.playhead=c.position+local
            _,source_out=self._source_bounds(c)
            if ms/1000>=source_out-.015 and self.player.playbackState()==QMediaPlayer.PlayingState:
                self.player.setPosition(round(source_out*1000)); self.player.pause()
        self.timeline.set_playhead(self.playhead); self.update_time()
        self.follow_playhead(); self.refresh_view_geometry()
        self.update_source_monitor_controls()

    def media_ready(self,status):
        if status in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia) and self.pending_seek:
            position,play=self.pending_seek; self.pending_seek=None; self.player.setPosition(position)
            if play:self.player.play()

    def load_player(self,path,position,play,video=True):
        self.player.stop(); self.pending_seek=(round(position*1000),play)
        self.video_stack.setCurrentIndex(1 if video else 0)
        if not video:self.placeholder.setText('♫\nAudiovorschau')
        url=QUrl.fromLocalFile(str(path))
        if self.player.source()==url:
            self.pending_seek=None;self.player.setPosition(round(position*1000))
            if play:self.player.play()
        else:self.player.setSource(url)

    def source_preview(self):
        c=self.current_clip()
        if not c or c.kind=='text' or c.source_type=='adjustment' or self.worker:return
        self.transport_stop()
        self._activate_source_clip(c)
        if c.source_type in ('image','image_sequence'):
            image=QImage(c.source_paths[0] if c.source_paths else c.path)
            if image.isNull():
                return self.error('Das Bild konnte nicht angezeigt werden.')
            self.mode='source'; self.video_stack.setCurrentIndex(1); self.video.frame=image; self.video.update()
            self.preview_status.setText('BILDVORSCHAU · Timeline-Vorschau zeigt die vollständige Komposition')
            self.update_source_monitor_controls()
            return
        if self.preview_worker:
            self.cancel_preview(wait=True); self.preview_queued=False
        self.mode='source';self.preview_status.setText('CLIPVORSCHAU · nur die ausgewählte Quelle, nicht der Mix')
        self.audio.setVolume(c.volume); self.player.setPlaybackRate(c.speed)
        source_in,source_out=self._source_bounds(c)
        source_time=max(source_in,min(source_out-.01,self._source_position(c)))
        self.update_source_monitor_controls()
        source=self.proxy_map.get(str(Path(c.path).resolve()),c.path) if self.proxy_enabled else c.path
        self.load_player(source,source_time,True,c.kind=='video')

    def toggle_play(self):
        if self.worker:return
        if self.transport_timer.isActive() or self.transport_rate != 0:
            self.transport_stop(); return
        if self.player.playbackState()==QMediaPlayer.PlayingState:
            self.player.pause();return
        if not self.clips:return self.error('Füge zuerst Medien zur Timeline hinzu.')
        if self.direct_preview_is_current():
            if self.playhead>=length(self.clips)-.02:
                self.playhead=0.0
            self._load_direct_clip_at_playhead(True)
            return
        if self.preview_worker:
            # A render may already be running because of live preview. Reuse
            # that render instead of starting a second FFmpeg process. If an
            # older composition exists, start it immediately and let the new
            # one replace it when ready.
            self.preview_play_requested=True
            if self.preview_path and Path(self.preview_path).is_file():
                self.mode='timeline'; self.player.setPlaybackRate(1.0); self.audio.setVolume(1)
                self.update_source_monitor_controls()
                self.preview_status.setText('LETZTER GÜLTIGER STAND · neue Vorschau wird im Hintergrund aktualisiert …')
                self.load_player(self.preview_path,min(self.playhead,length(self.clips)),True)
                return
            if getattr(self.preview_worker,'preview_signature',None) != self.preview_signature_for_current():
                self.preview_queued=True; self.preview_worker.cancel.set()
                self.preview_status.setText('Vorschau wird für die Wiedergabe aktualisiert …')
            else:
                self.preview_status.setText('Vorschau fertigstellen · Wiedergabe startet gleich …')
            return
        if self.preview_is_current():
            self.mode='timeline';self.player.setPlaybackRate(1.0);self.audio.setVolume(1);self.update_source_monitor_controls()
            self.preview_status.setText('TIMELINE · alle Video- und Audiospuren · Vorschau 480p / Export in gewählter Auflösung')
            if self.playhead>=length(self.clips)-.02:self.playhead=0
            self.load_player(self.preview_path,self.playhead,True);return
        if self.preview_path and Path(self.preview_path).is_file():
            # Playback must never be gated on a fresh composition render.
            # The old mix is useful for immediate navigation and is replaced
            # automatically once the current revision finishes.
            self.preview_play_requested=True
            self.mode='timeline'; self.player.setPlaybackRate(1.0); self.audio.setVolume(1)
            self.update_source_monitor_controls()
            self.preview_status.setText('LETZTER GÜLTIGER STAND · aktuelle Vorschau wird im Hintergrund berechnet …')
            if self.playhead>=length(self.clips)-.02:self.playhead=0
            self.load_player(self.preview_path,self.playhead,True)
            self.render_preview()
            return
        self.preview_play_requested=True
        self.render_preview()

    def auto_preview(self):
        if self.worker or not self.clips or self.compare_active: return
        if not self.live_preview_box.isChecked() and not self.preview_play_requested:return
        self.preview_queued=False
        self.render_preview(auto=True)

    def preview_option_changed(self,*_):
        if self.clips and self.live_preview_box.isChecked():
            if self.direct_preview_is_current():
                return
            self.preview_queued=True
            if self.preview_worker:self.preview_worker.cancel.set()
            self.live_preview_timer.start()

    def render_preview(self,auto=False):
        if self.compare_active: return
        if self.preview_is_current():
            return
        if self._direct_preview_clips():
            if self.preview_worker:
                self.preview_worker.cancel.set()
            requested=self.preview_play_requested
            self.activate_direct_preview(play=requested or self.player.playbackState()==QMediaPlayer.PlayingState)
            self.preview_play_requested=False
            self.preview_queued=False
            return
        if self.preview_worker:
            if getattr(self.preview_worker,'preview_signature',None) != self.preview_signature_for_current():
                self.preview_queued=True; self.preview_worker.cancel.set()
            return
        revision=self.revision; size=self.preview_size(); signature=self.preview_signature_for_current()
        proxy_tag='proxy' if self.proxy_enabled else 'original'
        target=Path(self.cache.name)/f'preview-{revision}-{size[0]}x{size[1]}-{proxy_tag}.mp4'
        clips=[]
        for clip in self.clips:
            source=clip.path
            if self.proxy_enabled and source:
                source=self.proxy_map.get(str(Path(source).resolve()),source)
            clips.append(replace(clip,path=source,source_paths=list(clip.source_paths)))
        tracks=list(self.tracks); track_states={track:dict(state) for track,state in self.track_states.items()}; master_settings=dict(self.master_mixer)
        use_gpu=self.gpu_preview_box.isChecked()
        def operation(progress,cancel):
            try:
                render(clips,tracks,target,size,progress,cancel,True,track_states,
                       preview_acceleration=use_gpu,master_settings=master_settings)
            except Exception:
                if not use_gpu:
                    raise
                # Hardware decode is an acceleration hint, not a requirement.
                # Drivers can disappear between detection and rendering, so a
                # preview always gets one automatic software fallback.
                render(clips,tracks,target,size,progress,cancel,True,track_states,
                       preview_acceleration=False,master_settings=master_settings)
            return str(target),revision
        self.preview_status.setText('Mehrspur-Vorschau wird im Hintergrund aktualisiert …')
        job=Job(operation); job.preview_signature=signature; self.preview_worker=job
        job.progress.connect(lambda value:None if self.compare_active else self.preview_status.setText(f'Mehrspur-Vorschau wird aktualisiert … {value}%'))
        job.result.connect(lambda result,j=job:self.finish_preview_job(j,result,auto,revision,signature))
        job.start()

    def finish_preview_job(self,job,result,auto,revision,signature):
        if self.preview_worker is not job:
            return
        job.wait(); self.preview_worker=None; job.deleteLater()
        stale=revision!=self.revision or signature!=self.preview_signature_for_current()
        if not result['ok']:
            if self.compare_active:
                self.preview_queued=True
                return
            if result.get('cancelled') and (stale or self.preview_queued or self.preview_play_requested):
                self.live_preview_timer.start()
                return
            if auto:
                self.preview_status.setText('Vorschau konnte nicht aktualisiert werden · Export bleibt verfügbar')
                self.statusBar().showMessage(result.get('error','Vorschau fehlgeschlagen'),6000)
            else:
                self.job_error(result)
            return
        path,rev=result['value']
        if stale:
            try:Path(path).unlink(missing_ok=True)
            except OSError:pass
            if self.preview_queued or self.preview_play_requested:
                self.live_preview_timer.start()
            return
        old=self.preview_path; self.preview_path=path; self.preview_revision=rev; self.preview_signature=signature
        if self.compare_active:
            self.preview_queued=False
            return
        self.mode='timeline'; self.audio.setVolume(1); self.update_source_monitor_controls()
        should_play=self.preview_play_requested
        pending_rate=self.transport_rate_pending
        self.transport_rate_pending=None
        self.preview_play_requested=False
        if (should_play or pending_rate is not None) and self.playhead>=length(self.clips)-.02 and pending_rate is not None and pending_rate > 0:
            self.playhead=0
        self.preview_status.setText('TIMELINE · alle Video- und Audiospuren · Schnellvorschau' if self.quick_preview_box.isChecked() else 'TIMELINE · alle Video- und Audiospuren')
        self.load_player(path,min(self.playhead,length(self.clips)),should_play and pending_rate is None)
        if old and old!=path:
            try:Path(old).unlink(missing_ok=True)
            except OSError:pass
        self.trim_cache(keep={path})
        queued=self.preview_queued; self.preview_queued=False
        if queued and self.live_preview_box.isChecked():
            self.live_preview_timer.start()
        if pending_rate is not None:
            QTimer.singleShot(0,lambda rate=pending_rate:self._start_transport(rate))

    def relink_media(self, missing=None, mapping=None, directory=None):
        """Relink offline sources, auto-matching unique filenames in a folder."""
        if self.worker:
            return False
        missing=list(missing if missing is not None else self.missing_media)
        if not missing:
            missing=missing_project_media(self.clips,self.assets)
        if not missing:
            self.statusBar().showMessage('Alle Medien sind bereits verknüpft.',3000)
            return False
        if mapping is None:
            directory=directory or QFileDialog.getExistingDirectory(self,'Ordner mit den fehlenden Medien auswählen','')
            if not directory:
                return False
            candidates=find_relink_candidates(missing,directory)
            mapping={}
            unresolved=[]
            for old in missing:
                choices=candidates.get(str(Path(old).resolve()),[])
                if len(choices)==1:
                    mapping[old]=choices[0]
                    continue
                suffix=Path(old).suffix
                selected,_=QFileDialog.getOpenFileName(
                    self,f'Medium neu verknüpfen: {Path(old).name}',directory,
                    f'Passende Dateien (*{suffix})' if suffix else 'Alle Dateien (*)')
                if selected:
                    mapping[old]=selected
                else:
                    unresolved.append(old)
            if unresolved:
                self.statusBar().showMessage(f'{len(unresolved)} Medien bleiben offline.',5000)
                return False
        try:
            clips,assets=relink_project_media(self.clips,self.assets,mapping)
            validate_timeline(clips,self.tracks)
            for asset in assets:
                asset.validate()
            self.checkpoint(); self.clips=clips; self.assets=assets
            self.missing_media=missing_project_media(self.clips,self.assets)
            self.proxy_map={}; self.proxy_directory=None; self.proxy_enabled=False
            self.auto_proxy_sources=set()
            self.proxy_box.blockSignals(True); self.proxy_box.setChecked(False); self.proxy_box.blockSignals(False)
            self.prepare_visuals(self.assets); self.refresh_media(); self.changed()
            if self.missing_media:
                self.statusBar().showMessage(f'{len(self.missing_media)} Medien bleiben offline.',5000)
            else:
                self.statusBar().showMessage(f'{len(mapping)} Medien neu verknüpft.',5000)
            return True
        except Exception as exc:
            self.error(exc)
            return False

    def archive_project_dialog(self):
        if self.worker:
            return
        if not self.clips:
            return self.error('Die Timeline ist leer.')
        name=Path(self.project_path).stem if self.project_path else Path(self.suggested_name).stem
        path,_=QFileDialog.getSaveFileName(
            self,'Projekt mit Medien archivieren',name+'.zip',
            'Framecut-Archiv (*.zip);;Alle Dateien (*)',options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        if not path.lower().endswith('.zip'):
            path+='.zip'
        target=Path(path).resolve()
        if target.exists() and QMessageBox.question(self,'Archiv ersetzen?',f'{target}\nüberschreiben?',
                                                     QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            return
        clips=[replace(c,source_paths=list(c.source_paths)) for c in self.clips]
        assets=[replace(c,source_paths=list(c.source_paths)) for c in self.assets]
        tracks=list(self.tracks); states={track:dict(state) for track,state in self.track_states.items()}
        names=dict(self.track_names); preset=self.preset.currentText(); project_name=name
        def operation(progress,cancel):
            return archive_project(target,project_name,clips,preset,tracks,assets,
                                   track_states=states,track_names=names,progress=progress,cancel=cancel,
                                   markers=[dict(marker) for marker in self.markers],mixer=dict(self.master_mixer))
        def complete(result):
            if result['ok']:
                self.statusBar().showMessage('Archiv erstellt · Originalmedien blieben unverändert',6000)
                QMessageBox.information(self,'Archiv fertig','Projekt und Medien archiviert:\n'+result['value'])
            else:
                self.job_error(result)
        self.start_job('Projekt und Medien werden archiviert …',operation,complete)

    def proxy_toggled(self, enabled):
        self.proxy_enabled=bool(enabled)
        if not enabled:
            self.proxy_map={}
            if self._direct_preview_clips():
                self.activate_direct_preview(play=self.player.playbackState()==QMediaPlayer.PlayingState)
            self.preview_queued=True
            if self.clips and self.live_preview_box.isChecked():
                self.live_preview_timer.start()
            return
        if self.worker:
            return
        if self._direct_preview_clips():
            self.activate_direct_preview(play=self.player.playbackState()==QMediaPlayer.PlayingState)
        self.start_proxy_generation()

    def maybe_start_auto_proxy(self):
        """Prepare a 360p proxy in the background for very large sources."""
        if self._closing or self.worker or self.proxy_enabled or 'proxy' in self.independent_jobs:
            return False
        threshold=256*1024*1024
        heavy=[]
        # Scan imported assets as well as timeline clips. This starts the
        # proxy while the user is still arranging the edit, so inserting the
        # source later never has to wait for proxy preparation.
        seen=set()
        for clip in self.assets+self.clips:
            if (clip.kind == 'video' and clip.source_type == 'video' and clip.path
                    and Path(clip.path).is_file()):
                try:
                    source=str(Path(clip.path).resolve())
                    if source in seen:
                        continue
                    seen.add(source)
                    if Path(source).stat().st_size >= threshold:
                        heavy.append(source)
                except OSError:
                    continue
        new_sources=set(heavy)-self.auto_proxy_sources
        if not new_sources:
            return False
        self.auto_proxy_sources.update(new_sources)
        self.proxy_enabled=True
        self.proxy_box.blockSignals(True); self.proxy_box.setChecked(True); self.proxy_box.blockSignals(False)
        self.activate_direct_preview(play=self.player.playbackState()==QMediaPlayer.PlayingState)
        self.statusBar().showMessage('Große Quelle erkannt · Schnellvorschau wird im Hintergrund vorbereitet. Schneiden und Abspielen bleiben sofort möglich.',6000)
        self.start_proxy_generation()
        return True

    def ensure_missing_proxies(self):
        """Start automatic large-file proxies, then repair missing manual ones."""
        if self._closing or self.worker:
            return
        if not self.proxy_enabled:
            self.maybe_start_auto_proxy()
            return
        if 'proxy' in self.independent_jobs:
            return
        sources={str(Path(c.path).resolve()) for c in self.assets+self.clips
                 if c.path and c.kind in ('video','audio') and c.source_type not in ('image','image_sequence')}
        if sources-set(self.proxy_map):
            self.start_proxy_generation()

    def start_proxy_generation(self):
        if self.worker or not self.proxy_enabled:
            return
        if not any(c.kind in ('video','audio') and c.source_type not in ('image','image_sequence')
                   and c.path for c in self.assets+self.clips):
            self.statusBar().showMessage('Für diese Medien werden keine Proxy-Dateien benötigt.',4000)
            return
        if self.project_path:
            directory=Path(self.project_path).with_suffix('.proxies')
        else:
            directory=self.proxy_directory or self.state_dir/'proxies'/uuid.uuid4().hex
        self.proxy_directory=directory
        clips=[replace(c,source_paths=list(c.source_paths)) for c in self.clips]
        assets=[replace(c,source_paths=list(c.source_paths)) for c in self.assets]
        profile=self.proxy_profile
        def operation(progress,cancel):
            return create_proxy_files(clips,assets,directory,profile=profile,
                                      progress=progress,cancel=cancel)
        def complete(result):
            if profile!=self.proxy_profile:
                QTimer.singleShot(0,self.start_proxy_generation); return
            if not result['ok']:
                self.proxy_enabled=False
                self.proxy_box.blockSignals(True); self.proxy_box.setChecked(False); self.proxy_box.blockSignals(False)
                return self.job_error(result)
            if not self.proxy_enabled:
                self.proxy_map={}
                return
            self.proxy_map=result['value']; self.statusBar().showMessage(
                f'{len(self.proxy_map)} Proxy-Dateien ({PROXY_PROFILES[self.proxy_profile]["label"]}) bereit · Originale bleiben für den Export aktiv',5000)
            self.preview_queued=True
            if self.clips:
                self.render_preview()
            # A new import can finish while this job is running. Re-scan once
            # so that the first proxy batch never silently misses that source.
            QTimer.singleShot(0,self.ensure_missing_proxies)
        self.start_independent_job('proxy','Proxy-Dateien werden erzeugt …',operation,complete)

    def update_render_queue_button(self):
        if not hasattr(self,'render_queue_button'):
            return
        count=len(self.render_queue)+(1 if self.render_current else 0)
        suffix=' · pausiert' if self.render_queue_paused and self.render_queue else ''
        self.render_queue_button.setText(f'Render-Queue ({count}){suffix}')

    def show_render_queue(self):
        if not self.render_queue and not self.render_current:
            self.statusBar().showMessage('Render-Queue ist leer.',3000)
            return
        dialog=QDialog(self); dialog.setWindowTitle('Render-Queue'); dialog.setMinimumWidth(520)
        layout=QVBoxLayout(dialog); layout.setContentsMargins(18,16,18,16); layout.setSpacing(10)
        layout.addWidget(label('RENDER-QUEUE · EXPORTS NACHEINANDER','heading'))
        queue_list=QListWidget(); layout.addWidget(queue_list)
        actions=QHBoxLayout(); start=button('Queue starten',lambda:None,True); clear=button('Warteschlange leeren',lambda:None); close=button('Schließen',dialog.reject)
        actions.addWidget(start); actions.addWidget(clear); actions.addStretch(); actions.addWidget(close); layout.addLayout(actions)

        def refresh_list():
            queue_list.clear()
            if self.render_current:
                queue_list.addItem('▶  Läuft: '+self.render_current['label'])
            for index,item in enumerate(self.render_queue,1):
                queue_list.addItem(f'{index}.  '+item['label'])
            start.setEnabled(bool(self.render_queue) and not self.worker)
            clear.setEnabled(bool(self.render_queue) and not self.worker)
        def start_queue():
            self.render_queue_paused=False; self.update_render_queue_button(); self.process_render_queue(); dialog.accept()
        def clear_queue():
            self.render_queue.clear(); self.update_render_queue_button(); refresh_list()
        start.clicked.connect(start_queue); clear.clicked.connect(clear_queue); refresh_list(); dialog.exec()

    def process_render_queue(self):
        if self.worker or self.render_current or self.render_queue_paused or not self.render_queue:
            self.update_render_queue_button(); return
        item=self.render_queue.pop(0); self.render_current=item; self.update_render_queue_button()
        def operation(progress,cancel):
            render(item['clips'],item['tracks'],item['target'],item['size'],progress,cancel,False,
                   item['track_states'],item['settings'],master_settings=item.get('master_settings',self.master_mixer),
                   duration_override=item.get('duration'))
            return str(item['target'])
        def complete(result):
            self.render_current=None; self.update_render_queue_button()
            if result['ok']:
                self.statusBar().showMessage('Export fertig: '+result['value'],6000)
            elif result.get('cancelled'):
                self.render_queue_paused=True; self.statusBar().showMessage(
                    'Aktueller Export abgebrochen · Render-Queue pausiert',6000)
            else:
                self.job_error(result)
            self.update_render_queue_button()
            if self.render_queue and not self.render_queue_paused:
                QTimer.singleShot(0,self.process_render_queue)
        self.start_independent_job('export',item['label']+' wird gerendert …',operation,complete)

    def start_export(self):
        if self.worker:return
        if not self.clips:return self.error('Die Timeline ist leer.')
        work_area=self.work_area_bounds() if (self.work_in is not None or self.work_out is not None) else None
        dialog=ExportDialog(self,work_area)
        if dialog.exec()!=QDialog.Accepted:return
        export_settings=dialog.export_settings
        format_info=EXPORT_FORMATS[export_settings['format']]
        extension=format_info['extension']
        path,_=QFileDialog.getSaveFileName(self,'Video exportieren','Mein-Film'+extension,
                                            f"{format_info['label']} (*{extension});;Alle Dateien (*)",
                                            options=QFileDialog.DontConfirmOverwrite)
        if not path:return
        if not path.lower().endswith(extension):path+=extension
        target=Path(path).resolve()
        source_files=[path for clip in self.clips+self.assets
                      for path in ([clip.path]+list(clip.source_paths)
                                   +([clip.background_removed_path] if clip.background_removed_path else []))]
        if any(Path(path).resolve()==target for path in source_files if path):return self.error('Der Export darf keine Quelldatei überschreiben.')
        if not target.parent.is_dir() or not os.access(target.parent,os.W_OK):
            return self.error('Zielordner nicht beschreibbar: '+str(target.parent))
        if target.exists() and QMessageBox.question(self,'Datei ersetzen?',f'{target}\nüberschreiben?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        clips=self.snapshot()[0]
        self.last_export_settings=dict(export_settings)
        export_duration=None
        if dialog.export_work_area and work_area:
            try:
                clips=trim_timeline_range(clips,*work_area)
                export_duration=work_area[1]-work_area[0]
            except Exception as exc:
                return self.error(exc)
        tracks=list(self.tracks);track_states={track:dict(state) for track,state in self.track_states.items()}
        profile_size=export_settings.get('size')
        size=tuple(profile_size) if profile_size else PRESETS[self.preset.currentText()]
        pending_targets=[item['target'] for item in self.render_queue]
        if self.render_current: pending_targets.append(self.render_current['target'])
        if target in pending_targets:
            return self.error('Dieses Ziel liegt bereits in der Render-Queue.')
        self.render_queue.append({'target':target,'clips':clips,'tracks':tracks,'track_states':track_states,
                                  'size':size,'settings':export_settings,'master_settings':dict(self.master_mixer),
                                  'duration':export_duration,
                                  'label':f"{format_info['label']} · {target.name}"})
        self.update_render_queue_button()
        if dialog.queue_only_box.isChecked():
            self.statusBar().showMessage(f'Export eingereiht · {target.name}',5000)
            return
        self.render_queue_paused=False; self.process_render_queue()

    def start_job(self,title,operation,callback):
        if self.worker: return
        self.cancel_preview(wait=True)
        self.transport_stop()
        self.player.pause()
        self.progress=self.new_task(title)
        self.statusBar().showMessage('Analyse läuft · Navigation bleibt verfügbar; Clip-Änderungen nach Abschluss.')
        self.worker=Job(operation);self.progress.canceled.connect(self.worker.cancel.set)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.result.connect(lambda result:self.finish_job(result,callback))
        self.worker.start();self.progress.show()

    def finish_job(self,result,callback):
        self.worker.wait();self.worker.deleteLater();self.worker=None
        self.progress.close();self.progress.deleteLater()
        if not self.independent_jobs: self.tasks_host.hide()
        callback(result)

    def job_error(self,result):
        if result.get('cancelled'):self.statusBar().showMessage('Abgebrochen · keine Zieldatei ersetzt',6000)
        else:self.error(result.get('error','Unbekannter Fehler'))

    def check_for_updates(self,silent=False):
        if self._closing or self.update_job or self.update_download_job:
            return
        manifest_url=configured_manifest_url()
        if not manifest_url:
            if not silent:
                if update_checks_disabled():
                    QMessageBox.information(self,'Updates','Die Update-Prüfung ist deaktiviert.\n\nEntferne FRAMECUT_DISABLE_UPDATE_CHECK oder setze die Variable auf 0, um sie wieder einzuschalten.')
                else:
                    QMessageBox.information(self,'Updates','Es ist keine Update-Quelle verfügbar.\n\nSetze FRAMECUT_UPDATE_MANIFEST_URL auf deine veröffentlichte updates.json.')
            return
        self.update_button.setEnabled(False); self.update_button.setText('Updates werden geprüft …')
        self.update_job=UpdateCheckJob(manifest_url,APP_VERSION)
        self.update_job.result.connect(lambda result:self.finish_update_check(result,silent))
        self.update_job.finished.connect(self.update_job.deleteLater)
        self.update_job.start()

    def finish_update_check(self,result,silent=False):
        self.update_job=None
        self.update_button.setEnabled(True); self.update_button.setText('Nach Updates suchen')
        if not result.get('ok'):
            self.statusBar().showMessage('Update-Prüfung nicht möglich: '+result.get('error','Unbekannter Fehler'),7000)
            if not silent:
                QMessageBox.warning(self,'Update-Prüfung',result.get('error','Unbekannter Fehler'))
            return
        artifact=result.get('artifact')
        if not artifact:
            self.statusBar().showMessage('Framecut ist auf dem aktuellen Stand.',5000)
            if not silent:
                QMessageBox.information(self,'Updates','Framecut ist bereits aktuell.')
            return
        self.update_artifact=artifact
        self.update_button.setText(f"Update {artifact['version']} verfügbar")
        self.statusBar().showMessage(f"Update verfügbar: Framecut {artifact['version']} · {artifact['kind']}",10000)
        if not silent:
            self.offer_update(artifact)

    def offer_update(self,artifact):
        notes='\n'.join(f'• {note}' for note in artifact.get('release_notes',[])) or 'Keine Release-Notizen.'
        if artifact['kind']=='appimage' and os.environ.get('APPIMAGE'):
            message=f"Framecut {artifact['version']} ist verfügbar.\n\n{notes}\n\nDas verifizierte AppImage wird heruntergeladen und ersetzt die aktuelle Datei. Framecut muss danach neu gestartet werden."
        elif artifact['kind']=='deb':
            message=f"Framecut {artifact['version']} ist verfügbar.\n\n{notes}\n\nDas Paket wird verifiziert heruntergeladen. Die Installation des .deb erfolgt anschließend mit dem angezeigten sudo-Befehl."
        else:
            message=f"Framecut {artifact['version']} ist verfügbar.\n\n{notes}\n\nDas AppImage wird verifiziert heruntergeladen und kann danach direkt gestartet werden."
        if QMessageBox.question(self,'Framecut-Update',message,QMessageBox.Yes|QMessageBox.No,QMessageBox.Yes)!=QMessageBox.Yes:
            return
        current_path=os.environ.get('APPIMAGE') if artifact['kind']=='appimage' else None
        install=bool(current_path and artifact['kind']=='appimage')
        self.update_download_job=UpdateDownloadJob(artifact,install,current_path)
        self.update_button.setEnabled(False); self.update_button.setText('Update wird geladen …')
        self.update_download_job.result.connect(self.finish_update_download)
        self.update_download_job.finished.connect(self.update_download_job.deleteLater)
        self.update_download_job.start()

    def finish_update_download(self,result):
        self.update_download_job=None
        self.update_button.setEnabled(True); self.update_button.setText('Nach Updates suchen')
        if not result.get('ok'):
            self.statusBar().showMessage('Update fehlgeschlagen: '+result.get('error','Unbekannter Fehler'),8000)
            QMessageBox.warning(self,'Update fehlgeschlagen',result.get('error','Unbekannter Fehler'))
            return
        message=result.get('message','Update verifiziert heruntergeladen.')
        self.statusBar().showMessage(message,10000)
        if result.get('installed'):
            QMessageBox.information(self,'Update bereit','Das neue AppImage ist installiert. Bitte Framecut neu starten.')
        elif self.update_artifact and self.update_artifact.get('kind')=='deb':
            path=result.get('path','')
            QMessageBox.information(self,'Update heruntergeladen',message+f"\n\nInstallation im Terminal:\nsudo dpkg -i '{path}'")
        else:
            path=result.get('path','')
            QMessageBox.information(self,'Update heruntergeladen',message+f"\n\nStarten mit:\nchmod +x '{path}'\n'{path}'")

    def resume_autosave(self):
        if self.dirty:self.autosave_timer.start()

    def autosave(self):
        if not self.recovery_enabled or not self.dirty:return
        if self.autosave_revision==self.revision:return
        if self.timeline.drag:
            self.autosave_timer.start();return
        try:
            backup=self.state_dir/'recovery-previous.framecut'
            if self.recovery_path.is_file():
                try:
                    load_project(self.recovery_path,allow_missing=True)
                    staged=backup.with_suffix('.tmp'); shutil.copy2(self.recovery_path,staged); os.replace(staged,backup)
                except (OSError,ValueError): pass
            save_project(self.recovery_path,self.clips,self.preset.currentText(),self.tracks,self.assets,self.project_path,self.track_states,self.track_names,self.markers,self.master_mixer)
            self.last_autosave=time.time(); self.autosave_revision=self.revision
            self.autosave_label.setText('Autosave ✓');self.autosave_label.setToolTip(str(self.recovery_path)); self.update_project_identity()
        except Exception as exc:
            self.autosave_label.setText('Autosave fehlgeschlagen');self.statusBar().showMessage(str(exc)); self.update_project_identity()

    def clear_recovery(self):
        self.autosave_timer.stop()
        if self.recovery_enabled:
            try:self.recovery_path.unlink(missing_ok=True)
            except OSError:pass
            try:(self.state_dir/'recovery-previous.framecut').unlink(missing_ok=True)
            except OSError:pass

    def offer_recovery(self):
        previous=self.state_dir/'recovery-previous.framecut'
        if not self.recovery_path.exists() and not previous.exists():return
        answer=QMessageBox.question(self,'Ungespeicherten Schnitt wiederherstellen?',
            'Es gibt eine automatische Sicherung der letzten Sitzung. Wiederherstellen?',QMessageBox.Yes|QMessageBox.No,QMessageBox.Yes)
        if answer!=QMessageBox.Yes:self.clear_recovery();return
        try:
            try: data=load_project(self.recovery_path,allow_missing=True)
            except (OSError,ValueError):
                if not previous.is_file(): raise
                if self.recovery_path.is_file(): shutil.copy2(self.recovery_path,self.state_dir/f'recovery-unreadable-{uuid.uuid4().hex[:8]}.framecut')
                data=load_project(previous,allow_missing=True)
            self.apply_project(data,data.get('origin'));self.changed()
            self.statusBar().showMessage('Autosave wiederhergestellt. Bitte als Projekt speichern.')
        except Exception as exc:
            # Keep unreadable recovery data even if a new session is subsequently saved.
            backup=self.state_dir/f'recovery-unreadable-{uuid.uuid4().hex[:8]}.framecut'
            try:
                shutil.copy2(self.recovery_path,backup)
                self.error(f'Sicherung konnte nicht geladen werden. Eine Kopie liegt unter:\n{backup}\n\n{exc}')
            except OSError:
                self.recovery_enabled=False
                self.error('Sicherung konnte nicht geladen werden; Autosave bleibt zum Schutz dieser Datei deaktiviert.\n'+str(exc))

    def save(self,save_as=False):
        if self.worker:return False
        path=None if save_as else self.project_path
        if not path:
            path,_=QFileDialog.getSaveFileName(self,'Projekt speichern',self.project_path or self.suggested_name,'Framecut (*.framecut)',options=QFileDialog.DontConfirmOverwrite)
            if not path:return False
            if not path.lower().endswith('.framecut'):path+='.framecut'
            if Path(path).exists() and QMessageBox.question(self,'Projekt ersetzen?',f'{path}\nüberschreiben?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return False
        try:
            save_project(path,self.clips,self.preset.currentText(),self.tracks,self.assets,None,self.track_states,self.track_names,self.markers,self.master_mixer)
            self.project_path=str(Path(path).resolve());self.dirty=False;self.clear_recovery()
            self.setWindowTitle(f'Framecut {APP_VERSION} · '+Path(path).stem);self.autosave_label.setText('Projekt gespeichert ✓');self.update_project_identity();return True
        except Exception as exc:self.error(exc);return False

    def can_discard(self):
        if not self.dirty:return True
        answer=QMessageBox.question(self,'Projekt speichern?','Es gibt ungespeicherte Änderungen.',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
        return self.save() if answer==QMessageBox.Save else answer==QMessageBox.Discard

    def apply_project(self,data,path):
        self.project_session=getattr(self,'project_session',0)+1
        self.cancel_interaction()
        for key,(job,_) in self.independent_jobs.items():
            if key!='export': job.cancel.set()
        self.cancel_preview(wait=True); self.preview_queued=False; self.preview_play_requested=False
        self.transport_stop()
        self.player.stop();self.pending_seek=None;self.player.setSource(QUrl());self.video_stack.setCurrentIndex(0)
        self.clips=data['clips'];self.tracks=data['tracks'];self.track_states=normalize_track_states(data.get('track_states'),self.tracks);self.track_names=normalize_track_names(data.get('track_names'),self.tracks);self.master_mixer=normalize_master_mixer(data.get('mixer'));self.assets=data['assets'];self.markers=normalize_markers(data.get('markers'),length(self.clips));self.project_path=path
        self.missing_media=list(data.get('missing_media',[]));self.proxy_enabled=False;self.proxy_map={};self.proxy_directory=None;self.auto_proxy_sources=set()
        self.proxy_box.blockSignals(True);self.proxy_box.setChecked(False);self.proxy_box.blockSignals(False)
        self.current=self.clips[0].uid if self.clips else None;self.selection=[self.current] if self.current else [];self.playhead=0
        self.source_clip_uid=None;self.source_in=None;self.source_out=None
        self.work_in=None;self.work_out=None
        self.history.clear();self.future.clear();self.revision+=1;self.preview_revision=-1;self.preview_signature=None;self.preview_path=None
        self.direct_preview=False;self.direct_preview_revision=-1;self.direct_preview_signature=None;self.direct_clip_uid=None
        self.history_labels.clear();self.future_labels.clear();self.refresh_history()
        self.last_autosave=None;self.autosave_revision=-1
        self.preset.blockSignals(True);self.preset.setCurrentText(data['preset'] if data['preset'] in PRESETS else next(iter(PRESETS)));self.preset.blockSignals(False)
        self.mode='timeline';self.dirty=False;self.prepare_visuals(self.assets);self.refresh_media();self.refresh()
        self.placeholder.setText('▶ Timeline berechnet die Mehrspur-Vorschau.\n„Clip ansehen“ zeigt sofort die Quelle.')
        self.preview_status.setText('Timeline geladen · Vorschau noch nicht berechnet')
        self.setWindowTitle(f'Framecut {APP_VERSION} · '+(Path(path).stem if path else 'Neues Projekt')); self.update_project_identity()
        # Re-opened projects should get the same instant-playback and large-file
        # proxy treatment as newly edited timelines, without waiting for the
        # first play button press.
        QTimer.singleShot(0,self.ensure_missing_proxies)

    def open_project_path(self,path):
        if self.worker or not self.can_discard():return
        try:
            selected=Path(path).resolve()
            project_path=selected
            if selected.suffix.lower()=='.zip':
                extracted=self.state_dir/'archives'/uuid.uuid4().hex
                project_path=Path(extract_project_archive(selected,extracted))
            data=load_project(project_path,allow_missing=True)
            self.clear_recovery();self.apply_project(data,None if data['migrated'] else str(project_path))
            if data['migrated']:
                self.suggested_name=str(Path(path).with_name(Path(path).stem+'-v02.framecut'));self.changed()
                self.statusBar().showMessage('0.1-Projekt übernommen. Speichern legt eine neue v02-Datei an.')
            elif data.get('missing_media'):
                missing=list(data['missing_media'])
                self.statusBar().showMessage(f'{len(missing)} Medien fehlen · „Medien neu verknüpfen…“ wählen',6000)
                QTimer.singleShot(0,lambda missing=missing:self.relink_media(missing))
            return True
        except Exception as exc:self.error(exc);return False

    def open_project(self):
        if self.worker or not self.can_discard():return
        path,_=QFileDialog.getOpenFileName(self,'Projekt öffnen','','Framecut (*.framecut *.zip);;Framecut-Projekt (*.framecut);;Framecut-Archiv (*.zip)')
        if path:self.open_project_path(path)

    def new_project(self):
        if self.worker or not self.can_discard():return
        self.clear_recovery();self.apply_project({'clips':[],'assets':[],'tracks':[2,1,-1,-2],'track_states':{},'track_names':{},'markers':[],'mixer':normalize_master_mixer(None),'preset':next(iter(PRESETS))},None)
        self.suggested_name='Mein-Film.framecut';self.autosave_label.setText('Autosave bereit'); self.update_project_identity()

    def closeEvent(self,event):
        if self.worker:
            self.error('Bitte den laufenden Vorgang zuerst abschließen oder abbrechen.');event.ignore();return
        if self.independent_jobs:
            answer=QMessageBox.question(self,'Hintergrundaufgaben abbrechen?',
                'Import, Proxy-Erzeugung oder Export laufen noch. Sicher abbrechen und schließen?',
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer!=QMessageBox.Yes: event.ignore(); return
        if self.render_queue:
            answer=QMessageBox.question(self,'Render-Queue schließen?',
                f'{len(self.render_queue)} Exporte sind noch eingereiht und werden beim Schließen verworfen.',
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer!=QMessageBox.Yes:
                event.ignore();return
            self.render_queue.clear(); self.update_render_queue_button()
        if self.can_discard():
            self.compare_released()
            self._closing=True
            self.close_smooth()
            if self.cinema_dialog is not None:
                self.cinema_dialog.close()
            self.autosave_timer.stop(); self.live_preview_timer.stop(); self.transport_timer.stop()
            self.preview_queued=False; self.preview_play_requested=False
            self.transport_stop()
            self.cancel_preview(wait=True)
            for attribute in ('update_job','update_download_job'):
                job=getattr(self,attribute,None)
                if job is not None:
                    job.requestInterruption(); job.wait(); setattr(self,attribute,None); job.deleteLater()
            self.clear_recovery();self.player.stop();self.player.setSource(QUrl());self.cache.cleanup();event.accept()
        else:event.ignore()


def main():
    app=QApplication(sys.argv);app.setApplicationName('Framecut');app.setStyle('Fusion');app.setStyleSheet(STYLE)
    icon=app_icon_path()
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    if hasattr(app,'setDesktopFileName'):
        app.setDesktopFileName('framecut')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        QMessageBox.critical(None,'FFmpeg fehlt','Bitte installieren: sudo apt install ffmpeg');return 1
    state=state_directory();lock=QLockFile(str(state/'editor.lock'));lock.setStaleLockTime(0)
    if not lock.tryLock(100):
                QMessageBox.warning(None,'Framecut läuft bereits',f'Bitte nutze das bereits geöffnete Framecut-{APP_VERSION}-Fenster.');return 1
    window=Editor(state);window.show()
    project_argument=next((argument for argument in sys.argv[1:] if Path(argument).suffix.lower() in ('.framecut','.zip')),None)
    if project_argument:
        QTimer.singleShot(0,lambda path=project_argument:window.open_project_path(path))
    result=app.exec();lock.unlock();return result


if __name__=='__main__':sys.exit(main())
