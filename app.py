"""Framecut 3.7 — native Linux multitrack editor."""
import math
import os
import sys
import shutil
import threading
import tempfile
import uuid
import subprocess
from pathlib import Path
from dataclasses import replace

from PySide6.QtCore import Qt, QUrl, QThread, Signal, QTimer, QLockFile
from PySide6.QtGui import QAction, QImage, QColor, QFont, QPainter, QIcon
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,
    QPushButton,QListWidgetItem,QFileDialog,QMessageBox,QSplitter,QDoubleSpinBox,QFormLayout,
    QComboBox,QSlider,QScrollArea,QProgressDialog,QFrame,QCheckBox,QStackedWidget,QSpinBox,QLineEdit,QInputDialog,QSizePolicy,QMenu,QColorDialog,QListWidget,QFontComboBox,QDialog,QDialogButtonBox,QGridLayout)
from PySide6.QtMultimedia import (QMediaPlayer,QAudioOutput,QMediaCaptureSession,QAudioInput,
                                  QMediaRecorder,QMediaFormat)
from preview import VideoView
from core import (Clip,PRESETS,MIN_CLIP,FILTER_PRESETS,MASK_TYPES,AUDIO_CHANNEL_MODES,TEXT_STYLE_PRESETS,EFFECT_PRESETS,KEYFRAME_CURVES,KEYFRAME_CURVE_LABELS,EXPORT_FORMATS,EXPORT_CODEC_LABELS,EXPORT_ENCODER_LABELS,PROXY_PROFILES,
                  normalize_export_settings,import_clip,import_image_sequence,parse_subtitle_file,subtitle_cues_from_clips,write_subtitle_file,save_project,load_project,split_clip,render,
                  archive_project,extract_project_archive,find_relink_candidates,relink_project_media,missing_project_media,create_proxy_files,
                  preview_acceleration_info,cache_size,prune_cache,
                  ExportCancelled,validate_timeline,length,normalize_markers,edited_clip,retime_keyframes,retime_volume_keyframes,retime_speed_keyframes,
                  normalize_track_states,normalize_track_names,normalize_master_mixer)
from timeline import Timeline,MediaList
from style import STYLE
from update_system import (configured_manifest_url,download_verified,fetch_manifest,
                           install_downloaded,preferred_kinds,select_artifact,update_cache_directory,
                           update_checks_disabled)

try:
    APP_VERSION = Path(__file__).with_name('VERSION').read_text(encoding='utf-8').strip() or '3.7'
except OSError:
    APP_VERSION = '3.7'


def label(text,name=None):
    widget=QLabel(text)
    if name: widget.setObjectName(name)
    return widget


def button(text,callback,primary=False):
    widget=QPushButton(text); widget.clicked.connect(callback)
    if primary: widget.setObjectName('primary')
    return widget


def panel():
    widget=QFrame(); widget.setObjectName('panel')
    layout=QVBoxLayout(widget); layout.setContentsMargins(14,14,14,14); layout.setSpacing(10)
    return widget,layout


def state_directory():
    path=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state')))/'framecut'
    path.mkdir(parents=True,exist_ok=True)
    return path


def app_icon_path():
    return Path(__file__).with_name('framecut.svg')


class ExportDialog(QDialog):
    """Small, explicit export profile dialog backed by core validation."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Export-Einstellungen')
        self.setMinimumWidth(430)
        layout=QVBoxLayout(self); layout.setContentsMargins(18,16,18,16); layout.setSpacing(12)
        layout.addWidget(label('EXPORT · FORMAT, QUALITÄT UND HARDWARE','heading'))
        form=QFormLayout()
        self.format_combo=QComboBox()
        for value,info in EXPORT_FORMATS.items(): self.format_combo.addItem(info['label'],value)
        self.codec_combo=QComboBox()
        self.fps=QDoubleSpinBox(); self.fps.setRange(1,120); self.fps.setDecimals(2); self.fps.setSingleStep(1); self.fps.setValue(30); self.fps.setSuffix(' FPS')
        self.bitrate=QSpinBox(); self.bitrate.setRange(256,200000); self.bitrate.setSingleStep(500); self.bitrate.setValue(12000); self.bitrate.setSuffix(' kbit/s')
        self.encoder_combo=QComboBox()
        for value,title in EXPORT_ENCODER_LABELS.items(): self.encoder_combo.addItem(title,value)
        self.hdr=QCheckBox('HDR10 · BT.2020 / PQ')
        self.hdr.setToolTip('10-Bit-Video mit HDR-Farbmetadaten; benötigt H.265/HEVC oder AV1.')
        form.addRow('Format',self.format_combo); form.addRow('Videocodec',self.codec_combo)
        form.addRow('Bildrate',self.fps); form.addRow('Videobitrate',self.bitrate)
        form.addRow('Encoding',self.encoder_combo); form.addRow('Farbraum',self.hdr)
        layout.addLayout(form)
        self.queue_only_box=QCheckBox('Nur in Render-Queue einreihen')
        self.queue_only_box.setToolTip('Der Export startet erst, wenn die Render-Queue gestartet wird.')
        layout.addWidget(self.queue_only_box)
        self.hint=label('Die Auswahl wird direkt im FFmpeg-Export verwendet.','muted'); self.hint.setWordWrap(True); layout.addWidget(self.hint)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.format_combo.currentIndexChanged.connect(self.format_changed)
        self.codec_combo.currentIndexChanged.connect(self.codec_changed)
        self.format_combo.setCurrentIndex(self.format_combo.findData('mp4')); self.format_changed()

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
                'encoder':self.encoder_combo.currentData(),'hdr':self.hdr.isChecked()}

    def accept(self):
        try:
            self.export_settings=normalize_export_settings(self.settings())
        except ValueError as exc:
            QMessageBox.warning(self,'Export-Einstellungen',str(exc)); return
        super().accept()


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
            volume_slider.valueChanged.connect(lambda value, t=track: volume_spin.setValue(value))
            volume_spin.valueChanged.connect(lambda value, t=track: volume_slider.setValue(round(value)))
            pan_slider.valueChanged.connect(lambda value, t=track: pan_spin.setValue(value))
            pan_spin.valueChanged.connect(lambda value, t=track: pan_slider.setValue(round(value)))
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


class Editor(QMainWindow):
    def __init__(self,state_dir=None,recovery=True):
        super().__init__()
        self.state_dir=Path(state_dir) if state_dir else state_directory()
        self.state_dir.mkdir(parents=True,exist_ok=True)
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
        self.current=None; self.selection=[]; self.clipboard=[]; self.markers=[]
        self.project_path=None; self.suggested_name='Mein-Film.framecut'
        self.history=[]; self.future=[]; self.dirty=False; self.revision=0
        self.preview_revision=-1; self.preview_signature=None; self.preview_path=None
        self.preview_worker=None; self.preview_queued=False; self.preview_play_requested=False
        self.missing_media=[]; self.proxy_enabled=False; self.proxy_map={}; self.proxy_directory=None; self.proxy_profile='360p'
        self.gpu_preview_info=preview_acceleration_info()
        self.render_queue=[]; self.render_current=None; self.render_queue_paused=False
        self.mode='timeline'; self.playhead=0.0
        self.transport_rate=0.0; self.transport_rate_pending=None
        self.voiceover_capture=None; self.voiceover_input=None; self.voiceover_recorder=None
        self.voiceover_dialog=None; self.voiceover_target=None
        self.transport_timer=QTimer(self); self.transport_timer.setInterval(40); self.transport_timer.timeout.connect(self.transport_tick)
        self.pending_seek=None; self.worker=None; self.recovery_enabled=recovery
        self.update_job=None; self.update_download_job=None; self.update_artifact=None
        self.setWindowTitle(f'Framecut {APP_VERSION} · Neues Projekt')
        self.resize(1460,980); self.setMinimumSize(1120,740)
        self.player=QMediaPlayer(self); self.audio=QAudioOutput(self); self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self.position_changed)
        self.player.mediaStatusChanged.connect(self.media_ready)
        self.player.errorOccurred.connect(lambda *_:self.statusBar().showMessage('Vorschau: '+self.player.errorString()))
        self.player.playbackStateChanged.connect(self.play_state)
        self.autosave_timer=QTimer(self); self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(2000); self.autosave_timer.timeout.connect(self.autosave)
        # Debounce edits so a burst of trim/property changes produces one
        # preview render after the user pauses, not one render per keystroke.
        self.live_preview_timer=QTimer(self); self.live_preview_timer.setSingleShot(True); self.live_preview_timer.setInterval(700); self.live_preview_timer.timeout.connect(self.auto_preview)
        self.build_ui(); self.setAcceptDrops(True); self.update_cache_status()
        shortcuts=[('Ctrl+I',self.import_dialog),('Ctrl+S',self.save),('Ctrl+Shift+S',lambda:self.save(True)),
                   ('Ctrl+O',self.open_project),('Ctrl+N',self.new_project),('Ctrl+Z',self.undo),
                   ('Ctrl+Shift+Z',self.redo),('Ctrl+Y',self.redo),('Ctrl+B',self.split),('S',self.split),
                   ('Ctrl+C',self.copy_selection),('Ctrl+V',self.paste_selection),('Ctrl+Shift+V',self.ripple_insert),
                   ('Ctrl+D',self.duplicate_selection),('Ctrl+G',self.group_selection),('Ctrl+Shift+G',self.ungroup_selection),
                   ('Ctrl+Shift+Delete',self.ripple_delete),
                   ('Ctrl+A',self.select_all),('J',self.transport_j),('K',self.transport_stop),('L',self.transport_l),
                   ('Space',self.toggle_play),('Delete',self.remove),('Backspace',self.remove),
                   ('Left',lambda:self.nudge_playhead(-1)),('Right',lambda:self.nudge_playhead(1)),
                   ('Shift+Left',lambda:self.nudge_playhead(-5)),('Shift+Right',lambda:self.nudge_playhead(5)),
                   ('Home',lambda:self.set_playhead(0)),('End',lambda:self.set_playhead(length(self.clips)))]
        for shortcut,fn in shortcuts:
            action=QAction(self); action.setShortcut(shortcut); action.setShortcutContext(Qt.ApplicationShortcut); action.triggered.connect(fn); self.addAction(action)
        self.refresh()
        self.statusBar().showMessage('Bereit · Lokal auf deinem Rechner · Quelldateien bleiben unverändert')
        if recovery: QTimer.singleShot(0,self.offer_recovery)
        if configured_manifest_url(): QTimer.singleShot(2500,lambda:self.check_for_updates(True))

    def build_ui(self):
        root=QWidget(); outer=QVBoxLayout(root); outer.setContentsMargins(16,14,16,8); outer.setSpacing(12)
        head=QHBoxLayout(); head.addWidget(label('FRAMECUT','brand')); head.addWidget(label(f'{APP_VERSION} / MULTITRACK','muted')); head.addStretch()
        for text,fn in [('Neu',self.new_project),('Öffnen',self.open_project),('Speichern',self.save)]: head.addWidget(button(text,fn))
        self.update_button=button('Nach Updates suchen',self.check_for_updates); head.addWidget(self.update_button)
        self.relink_button=button('Medien neu verknüpfen…',self.relink_media); head.addWidget(self.relink_button)
        self.archive_button=button('Archivieren…',self.archive_project_dialog); head.addWidget(self.archive_button)
        self.render_queue_button=button('Render-Queue (0)',self.show_render_queue); head.addWidget(self.render_queue_button)
        self.mixer_button=button('Audio-Mixer',self.open_mixer); head.addWidget(self.mixer_button)
        self.preset=QComboBox(); self.preset.addItems(PRESETS); self.preset.currentTextChanged.connect(self.preset_changed)
        head.addWidget(self.preset); head.addWidget(button('Exportieren ↗',self.start_export,True)); outer.addLayout(head)
        vertical=QSplitter(Qt.Vertical); top=QSplitter(Qt.Horizontal)
        # Let the vertical splitter decide the height. The default Preferred
        # policy inherits the tall media-panel size hint and blocks the handle.
        top.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Ignored)
        media,ml=panel(); media.setMinimumWidth(220)
        ml.addWidget(label('MEDIEN','heading')); ml.addWidget(button('+ Video / Audio / Bild importieren',self.import_dialog,True))
        ml.addWidget(button('+ Bildsequenz importieren',self.import_sequence_dialog))
        ml.addWidget(button('+ Untertitel importieren (SRT/VTT)',self.import_subtitle_dialog))
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
        media_filter_row.addWidget(self.media_filter,1); media_filter_row.addWidget(self.media_sort,1); ml.addLayout(media_filter_row)
        self.media_count=label('0 Medien','muted'); ml.addWidget(self.media_count)
        ml.addWidget(label('In eine Timeline-Spur ziehen','muted'))
        self.media_list=MediaList(); self.media_list.itemDoubleClicked.connect(lambda _:self.add_selected_asset())
        self.media_search.textChanged.connect(self.refresh_media); self.media_filter.currentIndexChanged.connect(self.refresh_media); self.media_sort.currentIndexChanged.connect(self.refresh_media)
        ml.addWidget(self.media_list,1)
        ml.addWidget(button('Am Spurende hinzufügen +',self.add_selected_asset))
        top.addWidget(media)
        preview,pl=panel(); pl.addWidget(label('VORSCHAU','heading'))
        self.preview_status=label('Timeline-Vorschau wird beim ersten Abspielen berechnet.','muted'); self.preview_status.setWordWrap(True); pl.addWidget(self.preview_status)
        preview_options=QHBoxLayout(); self.live_preview_box=QCheckBox('Live-Vorschau'); self.live_preview_box.setChecked(True); self.live_preview_box.setToolTip('Nach einer Änderung automatisch eine neue Vorschau berechnen')
        self.quick_preview_box=QCheckBox('Schnellvorschau'); self.quick_preview_box.setChecked(True); self.quick_preview_box.setToolTip('Niedrigere Auflösung und schnelleres Rendering für die Vorschau')
        self.gpu_preview_box=QCheckBox('GPU-Decoding'); self.gpu_preview_box.setChecked(self.gpu_preview_info['available']); self.gpu_preview_box.setEnabled(self.gpu_preview_info['available'])
        self.gpu_preview_box.setToolTip(self.gpu_preview_info['label']+' · fällt sonst automatisch auf CPU zurück')
        self.live_preview_box.toggled.connect(self.preview_option_changed); self.quick_preview_box.toggled.connect(self.preview_option_changed); self.gpu_preview_box.toggled.connect(self.preview_option_changed)
        preview_options.addWidget(self.live_preview_box); preview_options.addWidget(self.quick_preview_box); preview_options.addWidget(self.gpu_preview_box); preview_options.addStretch(); pl.addLayout(preview_options)
        performance_options=QHBoxLayout(); self.proxy_box=QCheckBox('Proxy-Vorschau'); self.proxy_box.setEnabled(False)
        self.proxy_box.setToolTip('Erzeugt lokale, kleinere Vorschau-Dateien und lässt die Originale für den Export unverändert')
        self.proxy_profile_combo=QComboBox()
        for value,info in PROXY_PROFILES.items(): self.proxy_profile_combo.addItem(info['label'],value)
        self.proxy_profile_combo.setCurrentIndex(self.proxy_profile_combo.findData(self.proxy_profile)); self.proxy_profile_combo.setEnabled(False)
        self.proxy_profile_combo.setToolTip('Qualität der Proxy-Dateien: 360p ist schneller, 720p detailreicher')
        self.cache_status=label('Cache wird automatisch begrenzt','muted'); self.cache_clear_button=button('Cache leeren',self.clear_cache)
        self.proxy_box.toggled.connect(self.proxy_toggled); self.proxy_profile_combo.currentIndexChanged.connect(self.proxy_profile_changed)
        performance_options.addWidget(self.proxy_box); performance_options.addWidget(label('Profil','muted')); performance_options.addWidget(self.proxy_profile_combo); performance_options.addStretch(); performance_options.addWidget(self.cache_status); performance_options.addWidget(self.cache_clear_button); pl.addLayout(performance_options)
        self.video_stack=QStackedWidget(); self.video_stack.setMinimumSize(330,190)
        self.placeholder=label('Dein Film beginnt hier.\n\nMedien importieren → in die Timeline ziehen', 'muted')
        self.placeholder.setAlignment(Qt.AlignCenter); self.video_stack.addWidget(self.placeholder)
        self.video=VideoView(); self.player.setVideoSink(self.video.sink); self.video_stack.addWidget(self.video)
        pl.addWidget(self.video_stack,1)
        self.seek=QSlider(Qt.Horizontal); self.seek.setRange(0,10000); self.seek.sliderMoved.connect(self.seek_slider); pl.addWidget(self.seek)
        controls=QHBoxLayout(); self.play_button=button('▶ Timeline',self.toggle_play); controls.addWidget(self.play_button)
        controls.addWidget(button('Clip ansehen',self.source_preview)); controls.addStretch()
        self.time_label=label('00:00.0 / 00:00.0','muted'); controls.addWidget(self.time_label); pl.addLayout(controls)
        top.addWidget(preview)
        inspector,inspector_outer=panel(); inspector.setMinimumWidth(250); inspector.setMinimumHeight(0)
        inspector_scroll=QScrollArea(); inspector_scroll.setWidgetResizable(True); inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); inspector_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        inspector_content=QWidget(); il=QVBoxLayout(inspector_content); il.setContentsMargins(0,0,0,0); il.setSpacing(8)
        inspector_scroll.setWidget(inspector_content); inspector_outer.addWidget(inspector_scroll)
        il.addWidget(label('CLIP-EINSTELLUNGEN','heading')); self.clip_name=label('Kein Clip ausgewählt','muted'); self.clip_name.setWordWrap(True); il.addWidget(self.clip_name)
        form=QFormLayout(); self.position=QDoubleSpinBox(); self.start=QDoubleSpinBox(); self.end=QDoubleSpinBox()
        for spin in [self.position,self.start,self.end]: spin.setRange(0,864000); spin.setDecimals(3); spin.setSuffix(' s'); spin.setSingleStep(.1)
        self.track_combo=QComboBox(); self.volume=QDoubleSpinBox(); self.volume.setRange(0,100); self.volume.setDecimals(0); self.volume.setSuffix(' %')
        self.audio_noise_reduction=QDoubleSpinBox(); self.audio_noise_reduction.setRange(0,30); self.audio_noise_reduction.setDecimals(1); self.audio_noise_reduction.setSingleStep(1); self.audio_noise_reduction.setSuffix(' dB')
        self.audio_eq_low=QDoubleSpinBox(); self.audio_eq_mid=QDoubleSpinBox(); self.audio_eq_high=QDoubleSpinBox()
        for spin in (self.audio_eq_low,self.audio_eq_mid,self.audio_eq_high): spin.setRange(-12,12); spin.setDecimals(1); spin.setSingleStep(1); spin.setSuffix(' dB')
        self.audio_compressor_enabled=QCheckBox('Kompressor aktiv')
        self.audio_compressor_threshold=QDoubleSpinBox(); self.audio_compressor_threshold.setRange(-60,0); self.audio_compressor_threshold.setDecimals(1); self.audio_compressor_threshold.setSingleStep(1); self.audio_compressor_threshold.setSuffix(' dB')
        self.audio_compressor_ratio=QDoubleSpinBox(); self.audio_compressor_ratio.setRange(1,20); self.audio_compressor_ratio.setDecimals(1); self.audio_compressor_ratio.setSingleStep(.5); self.audio_compressor_ratio.setSuffix('×')
        self.audio_ducking=QDoubleSpinBox(); self.audio_ducking.setRange(0,100); self.audio_ducking.setDecimals(0); self.audio_ducking.setSuffix(' %')
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
        self.chroma_key_enabled=QCheckBox('Greenscreen aktiv')
        self.chroma_key_color=QLineEdit('#00ff00'); self.chroma_key_color.setMaxLength(7); self.chroma_key_color.setPlaceholderText('#00ff00')
        self.chroma_key_similarity=QDoubleSpinBox(); self.chroma_key_similarity.setRange(0,100); self.chroma_key_similarity.setDecimals(0); self.chroma_key_similarity.setSuffix(' %')
        self.chroma_key_blend=QDoubleSpinBox(); self.chroma_key_blend.setRange(0,100); self.chroma_key_blend.setDecimals(0); self.chroma_key_blend.setSuffix(' %')
        self.mask_type=QComboBox()
        for title,value in [('Keine Maske','none'),('Rechteck','rectangle'),('Ellipse','ellipse')]: self.mask_type.addItem(title,value)
        self.mask_x=QDoubleSpinBox(); self.mask_y=QDoubleSpinBox(); self.mask_width=QDoubleSpinBox(); self.mask_height=QDoubleSpinBox(); self.mask_feather=QDoubleSpinBox()
        for spin in (self.mask_x,self.mask_y,self.mask_width,self.mask_height,self.mask_feather): spin.setRange(0,100); spin.setDecimals(1); spin.setSuffix(' %')
        self.mask_width.setValue(100); self.mask_height.setValue(100)
        self.transition_type=QComboBox()
        for title,value in [('Kein Übergang','none'),('Überblenden','dissolve'),('Slide links','slide_left'),('Slide rechts','slide_right'),('Slide oben','slide_up'),('Slide unten','slide_down'),('Wipe links','wipe_left'),('Wipe rechts','wipe_right'),('Wipe oben','wipe_up'),('Wipe unten','wipe_down'),('Zoom','zoom'),('Dip to Black','dip_to_black'),('Fade to White','fade_white'),('Blur In','blur_in'),('Circle Open','circle_open'),('Circle Close','circle_close'),('Radial','radial'),('Pixelize','pixelize'),('Smooth links','smooth_left'),('Smooth rechts','smooth_right'),('Smooth oben','smooth_up'),('Smooth unten','smooth_down'),('Cover links','cover_left'),('Cover rechts','cover_right'),('Cover oben','cover_up'),('Cover unten','cover_down')]: self.transition_type.addItem(title,value)
        self.transition_duration=QDoubleSpinBox(); self.transition_duration.setRange(0,30); self.transition_duration.setDecimals(2); self.transition_duration.setSingleStep(.1); self.transition_duration.setSuffix(' s')
        self.keyframe_time=QDoubleSpinBox(); self.keyframe_time.setRange(0,864000); self.keyframe_time.setDecimals(2); self.keyframe_time.setSingleStep(.1); self.keyframe_time.setSuffix(' s')
        self.keyframe_curve=QComboBox()
        for value in KEYFRAME_CURVES: self.keyframe_curve.addItem(KEYFRAME_CURVE_LABELS[value],value)
        self.keyframe_list=QListWidget(); self.keyframe_list.setMaximumHeight(96); self.keyframe_list.setMinimumHeight(42)
        self.keyframe_set_button=button('Keyframe setzen / aktualisieren',self.set_keyframe)
        self.keyframe_remove_button=button('Keyframe löschen',self.remove_keyframe)
        self.keyframe_list.currentRowChanged.connect(self.keyframe_selected)
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
        form.setVerticalSpacing(4)
        color_row=QHBoxLayout(); color_row.setContentsMargins(0,0,0,0); color_row.addWidget(self.text_color,1); color_row.addWidget(self.text_palette_button)
        for name,widget in [('Spur',self.track_combo),('Position',self.position),('Quellstart',self.start),('Quellende',self.end),('Geschwindigkeit',self.speed),('Freeze-Frame',self.freeze_enabled),('Freeze-Dauer',self.freeze_duration),('Reverse',self.reverse_clip),('Einblenden',self.fade_in),('Ausblenden',self.fade_out),('Lautstärke',self.volume),('Text',self.text_value),('Textgröße',self.text_size),('Schrift',self.text_font)]:form.addRow(name,widget)
        form.addRow('Textfarbe',color_row)
        for name,widget in [('Text X',self.text_x),('Text Y',self.text_y)]:form.addRow(name,widget)
        text_style_form=QFormLayout()
        style_row=QHBoxLayout(); style_row.setContentsMargins(0,0,0,0); style_row.addWidget(self.text_bold); style_row.addWidget(self.text_italic); style_row.addStretch(); text_style_form.addRow('Schnitt',style_row)
        text_style_form.addRow('Kontur',self.text_outline_width); text_style_form.addRow('Konturfarbe',self.text_outline_color)
        text_style_form.addRow('Schatten',self.text_shadow_size); text_style_form.addRow('Schattenfarbe',self.text_shadow_color)
        text_style_form.addRow('Hintergrund',self.text_background_enabled); text_style_form.addRow('Hintergrundfarbe',self.text_background_color)
        text_style_form.addRow('Hintergrunddeckkraft',self.text_background_opacity); text_style_form.addRow('Hintergrundrand',self.text_background_padding)
        preset_row=QHBoxLayout(); preset_row.setContentsMargins(0,0,0,0); preset_row.addWidget(self.text_style_preset,1); preset_row.addWidget(self.text_style_apply_button)
        text_style_form.addRow('Stilvorlage',preset_row)
        text_style_form.addRow('Animation',self.text_animation); text_style_form.addRow('Anim.-Dauer',self.text_animation_duration)
        il.addWidget(label('TEXTSTIL UND ANIMATION','heading')); il.addLayout(text_style_form)
        transform_form=QFormLayout()
        transform_form.addRow('Zoom',self.transform_scale)
        transform_form.addRow('Bild X',self.transform_x); transform_form.addRow('Bild Y',self.transform_y)
        transform_form.addRow('Rotation',self.rotation)
        transform_form.addRow('Crop links',self.crop_left); transform_form.addRow('Crop oben',self.crop_top)
        transform_form.addRow('Crop rechts',self.crop_right); transform_form.addRow('Crop unten',self.crop_bottom)
        flip_row=QHBoxLayout(); flip_row.setContentsMargins(0,0,0,0); flip_row.addWidget(self.flip_horizontal); flip_row.addWidget(self.flip_vertical); flip_row.addStretch()
        transform_form.addRow('Spiegeln',flip_row)
        il.addLayout(form)
        audio_form=QFormLayout(); audio_form.addRow('Rauschunterdrückung',self.audio_noise_reduction)
        audio_form.addRow('EQ Tiefen',self.audio_eq_low); audio_form.addRow('EQ Mitten',self.audio_eq_mid); audio_form.addRow('EQ Höhen',self.audio_eq_high)
        audio_form.addRow('Kompressor',self.audio_compressor_enabled); audio_form.addRow('Kompressor-Schwelle',self.audio_compressor_threshold); audio_form.addRow('Kompressor-Ratio',self.audio_compressor_ratio)
        audio_form.addRow('Audio-Ducking',self.audio_ducking); audio_form.addRow('Kanäle',self.audio_channel_mode); audio_form.addRow('Panorama',self.audio_pan)
        il.addWidget(label('AUDIO · MIX UND KANÄLE','heading')); il.addLayout(audio_form)
        il.addWidget(label('BILDTRANSFORMATION','heading')); il.addLayout(transform_form)
        color_form=QFormLayout(); color_form.addRow('Helligkeit',self.brightness); color_form.addRow('Kontrast',self.contrast); color_form.addRow('Sättigung',self.saturation); color_form.addRow('Filter',self.filter_preset)
        effect_preset_row=QHBoxLayout(); effect_preset_row.setContentsMargins(0,0,0,0); effect_preset_row.addWidget(self.effect_preset,1); effect_preset_row.addWidget(self.effect_preset_apply_button); color_form.addRow('Effekt-Preset',effect_preset_row)
        lut_row=QHBoxLayout(); lut_row.setContentsMargins(0,0,0,0); lut_row.addWidget(self.lut_path,1); lut_row.addWidget(self.lut_browse_button); color_form.addRow('LUT',lut_row)
        il.addWidget(label('FARBKORREKTUR','heading')); il.addLayout(color_form)
        effects_form=QFormLayout(); effects_form.addRow('Deckkraft',self.opacity); effects_form.addRow('Unschärfe',self.blur); effects_form.addRow('Schärfe',self.sharpen); effects_form.addRow('Stabilisierung',self.stabilization); effects_form.addRow('Greenscreen',self.chroma_key_enabled); effects_form.addRow('Key-Farbe',self.chroma_key_color); effects_form.addRow('Ähnlichkeit',self.chroma_key_similarity); effects_form.addRow('Weichheit',self.chroma_key_blend)
        il.addWidget(label('VIDEO-EFFEKTE','heading')); il.addLayout(effects_form)
        mask_form=QFormLayout(); mask_form.addRow('Maskentyp',self.mask_type); mask_form.addRow('Maske X',self.mask_x); mask_form.addRow('Maske Y',self.mask_y); mask_form.addRow('Maskenbreite',self.mask_width); mask_form.addRow('Maskenhöhe',self.mask_height); mask_form.addRow('Maskenweichheit',self.mask_feather)
        il.addWidget(label('MASKEN','heading')); il.addLayout(mask_form)
        transition_form=QFormLayout(); transition_form.addRow('Übergang',self.transition_type); transition_form.addRow('Dauer',self.transition_duration)
        il.addWidget(label('ÜBERGANG','heading')); il.addLayout(transition_form)
        il.addWidget(label('KEYFRAMES · TRANSFORM + VIDEOEFFEKTE','heading'))
        keyframe_form=QFormLayout(); keyframe_form.addRow('Zeit im Clip',self.keyframe_time); keyframe_form.addRow('Kurve',self.keyframe_curve); il.addLayout(keyframe_form)
        keyframe_buttons=QHBoxLayout(); keyframe_buttons.setContentsMargins(0,0,0,0); keyframe_buttons.addWidget(self.keyframe_set_button,1); keyframe_buttons.addWidget(self.keyframe_remove_button,1); il.addLayout(keyframe_buttons)
        il.addWidget(self.keyframe_list)
        il.addWidget(label('LAUTSTÄRKE-KURVE','heading'))
        volume_keyframe_form=QFormLayout(); volume_keyframe_form.addRow('Zeit im Clip',self.volume_keyframe_time); volume_keyframe_form.addRow('Kurve',self.volume_keyframe_curve); il.addLayout(volume_keyframe_form)
        volume_keyframe_buttons=QHBoxLayout(); volume_keyframe_buttons.setContentsMargins(0,0,0,0); volume_keyframe_buttons.addWidget(self.volume_keyframe_set_button,1); volume_keyframe_buttons.addWidget(self.volume_keyframe_remove_button,1); il.addLayout(volume_keyframe_buttons)
        il.addWidget(self.volume_keyframe_list)
        il.addWidget(label('SPEED-RAMPING · VIDEO','heading'))
        speed_ramp_form=QFormLayout(); speed_ramp_form.addRow('Quellzeit',self.speed_ramp_time); speed_ramp_form.addRow('Geschwindigkeit',self.speed_ramp_value); il.addLayout(speed_ramp_form)
        speed_ramp_buttons=QHBoxLayout(); speed_ramp_buttons.setContentsMargins(0,0,0,0); speed_ramp_buttons.addWidget(self.speed_ramp_set_button,1); speed_ramp_buttons.addWidget(self.speed_ramp_remove_button,1); il.addLayout(speed_ramp_buttons)
        il.addWidget(self.speed_ramp_list)
        il.addWidget(button('Bild zurücksetzen',self.reset_transform)); il.addWidget(button('Übernehmen',self.apply_properties,True)); il.addWidget(button('Audio aus Video extrahieren',self.extract_audio))
        hint=label('Höhere Videospuren liegen vorne.\nTon aller Spuren wird gemischt.\n\nGleiche Spur: keine Überlappung.\nShift beim Ziehen: ohne Einrasten.\n\nSpurkopf: M = stumm schalten · L = Spur sperren.\nAudio: Rauschunterdrückung, 3-Band-EQ, Kompressor, Ducking, Kanalmodus und Panorama.\nDucking auf einem Musikclip senkt ihn automatisch, sobald andere Audiospuren aktiv sind.\nBildtransformation: Zoom, Position, Crop, Rotation und Spiegeln.\nFarbkorrektur: Helligkeit, Kontrast, Sättigung, Presets und .cube/.3dl-LUTs.\nEffekt-Presets: Clean, Cinematic, Dream, Noir, Vivid und Soft Focus.\nAdjustment-Layer legt Effekte über die darunterliegende Komposition.\nVideoeffekte: Deckkraft, Unschärfe, Schärfe, Stabilisierung, Greenscreen und Masken.\nKeyframes animieren Zoom, Bildposition, Rotation, Deckkraft und Unschärfe; Kurven: Linear, Ease in, Ease out und Ease in/out.\nSpeed-Ramping: mehrere Geschwindigkeits-Punkte zwischen 0,25× und 4× setzen.\nFreeze-Frame hält das letzte Bild; Reverse spielt Bild und Ton rückwärts.\nÜbergänge: Überblenden, Slide, Smooth, Cover, Wipe, Zoom, Blur, Pixelize, Circle, Radial sowie Fade to White.\nEinblenden / Ausblenden sind weiche Übergänge für Bild und Ton.\nTextclips liegen automatisch über dem Video.\nTextstil: Schrift, Fett/Kursiv, Kontur, Schatten und Hintergrund.\nTextanimation: Ein-/Ausblenden oder Hereinschieben.\nSRT/VTT importiert Cue-Zeiten als Textclips auf eigenen Spuren.\nAudio extrahieren erstellt eine eigene Audiodatei.\n\nShortcuts: Leertaste = Play/Pause · J = rückwärts · K = Pause · L = vorwärts\nPfeile = 1 s bewegen · Entf = Clip löschen','muted'); hint.setWordWrap(True); il.addWidget(hint); il.addStretch()
        top.addWidget(inspector); top.setSizes([250,780,280]); vertical.addWidget(top)
        bottom,bl=panel(); bottom.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Ignored)
        bar=QHBoxLayout(); bar.addWidget(label('TIMELINE','heading'))
        for title,fn in [('↶',self.undo),('↷',self.redo),('Teilen',self.split),('Entfernen',self.remove),
                         ('Kopieren',self.copy_selection),('Einfügen',self.paste_selection),('Insert',self.insert_selection),('Overwrite',self.overwrite_selection),
                         ('Duplizieren',self.duplicate_selection),('Ripple löschen',self.ripple_delete),
                         ('Gruppieren',self.group_selection),('Marker +',lambda:self.add_marker('marker')),('Kapitel +',lambda:self.add_marker('chapter')),
                         ('+ Text',self.add_text),('+ Adjustment-Layer',self.add_adjustment_layer),('+ Untertitel',self.import_subtitle_dialog)]:bar.addWidget(button(title,fn))
        self.subtitle_export_button=button('Untertitel exportieren…',self.export_subtitles); bar.addWidget(self.subtitle_export_button)
        bar.addWidget(label('Video','muted')); self.video_tracks=QSpinBox(); self.video_tracks.setRange(1,10); self.video_tracks.setValue(2); self.video_tracks.valueChanged.connect(self.track_counts_changed); bar.addWidget(self.video_tracks)
        bar.addWidget(label('Audio','muted')); self.audio_tracks=QSpinBox(); self.audio_tracks.setRange(1,10); self.audio_tracks.setValue(2); self.audio_tracks.valueChanged.connect(self.track_counts_changed); bar.addWidget(self.audio_tracks)
        self.snap_box=QCheckBox('Einrasten'); self.snap_box.setChecked(True); self.snap_box.toggled.connect(lambda b:setattr(self.timeline,'snap',b)); bar.addWidget(self.snap_box); bar.addStretch()
        self.total=label('','muted'); bar.addWidget(self.total); bl.addLayout(bar)
        row=QHBoxLayout(); self.autosave_label=label('Autosave bereit','muted'); row.addWidget(self.autosave_label); row.addStretch(); row.addWidget(button('Einpassen',self.fit_timeline))
        row.addWidget(label('Zoom','muted')); self.zoom_slider=QSlider(Qt.Horizontal); self.zoom_slider.setRange(2,200); self.zoom_slider.setValue(60); self.zoom_slider.setFixedWidth(120); self.zoom_slider.valueChanged.connect(self.zoom); row.addWidget(self.zoom_slider); bl.addLayout(row)
        self.timeline=Timeline(); self.timeline.selection_changed.connect(self.timeline_selection_changed); self.timeline.seek.connect(self.set_playhead)
        self.timeline.context_requested.connect(self.show_context_menu)
        self.timeline.track_context_requested.connect(self.show_track_context_menu)
        self.timeline.marker_context_requested.connect(self.show_marker_context_menu)
        self.timeline.commit.connect(self.commit_drag); self.timeline.add_asset.connect(self.drop_asset); self.timeline.delete_selected.connect(self.remove)
        self.timeline.track_mute_requested.connect(self.toggle_track_mute); self.timeline.track_lock_requested.connect(self.toggle_track_lock)
        self.timeline.zoom_request.connect(lambda n:self.zoom_slider.setValue(self.zoom_slider.value()+n*5))
        self.timeline.gesture_done.connect(self.resume_autosave)
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setWidget(self.timeline); bl.addWidget(self.scroll)
        self.timeline.pan_request.connect(self.pan_timeline)
        self.text_value.editingFinished.connect(self.apply_properties)
        self.text_color.editingFinished.connect(self.apply_properties)
        for field in (self.position,self.start,self.end,self.speed,self.freeze_duration,self.fade_in,self.fade_out,self.volume,
                      self.audio_noise_reduction,self.audio_eq_low,self.audio_eq_mid,self.audio_eq_high,self.audio_compressor_threshold,
                      self.audio_compressor_ratio,self.audio_ducking,self.audio_pan,self.text_size,self.text_x,self.text_y,
                      self.text_outline_width,self.text_outline_color,self.text_shadow_size,self.text_shadow_color,self.text_background_color,
                      self.text_background_opacity,self.text_background_padding,self.text_animation_duration,
                      self.transform_scale,self.transform_x,self.transform_y,self.rotation,self.crop_left,self.crop_top,self.crop_right,self.crop_bottom,
                      self.brightness,self.contrast,self.saturation,self.lut_path,self.opacity,self.blur,self.sharpen,self.stabilization,
                      self.chroma_key_color,self.chroma_key_similarity,self.chroma_key_blend,
                      self.mask_x,self.mask_y,self.mask_width,self.mask_height,self.mask_feather):
            field.editingFinished.connect(self.apply_properties)
        self.flip_horizontal.clicked.connect(self.apply_properties); self.flip_vertical.clicked.connect(self.apply_properties)
        self.freeze_enabled.clicked.connect(self.apply_properties); self.reverse_clip.clicked.connect(self.apply_properties)
        self.audio_compressor_enabled.clicked.connect(self.apply_properties)
        self.audio_channel_mode.activated.connect(lambda *_: self.apply_properties())
        self.text_bold.clicked.connect(self.apply_properties); self.text_italic.clicked.connect(self.apply_properties)
        self.text_background_enabled.clicked.connect(self.apply_properties)
        self.text_font.activated.connect(lambda *_: self.apply_properties())
        self.text_animation.activated.connect(lambda *_: self.apply_properties())
        self.filter_preset.activated.connect(lambda *_: self.apply_properties()); self.chroma_key_enabled.clicked.connect(self.apply_properties)
        self.mask_type.activated.connect(lambda *_: self.apply_properties())
        self.transition_type.activated.connect(lambda *_: self.apply_properties()); self.transition_duration.editingFinished.connect(self.apply_properties)
        vertical.addWidget(bottom); vertical.setStretchFactor(0,4); vertical.setStretchFactor(1,3); vertical.setChildrenCollapsible(False); vertical.setSizes([480,420]); outer.addWidget(vertical,1); self.setCentralWidget(root)

    def error(self,message): QMessageBox.warning(self,'Framecut',str(message))

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
            self.start_proxy_generation()

    def preview_signature_for_current(self):
        return (self.revision, self.preview_size(), bool(self.proxy_enabled), self.proxy_profile,
                bool(self.gpu_preview_box.isChecked()),
                tuple(sorted(self.proxy_map.items())),
                tuple(sorted((track, tuple(sorted(state.items()))) for track,state in self.track_states.items())),
                tuple(sorted(self.master_mixer.items())))

    def preview_is_current(self):
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
            menu.addAction('Duplizieren',self.duplicate_selection)
            menu.addAction('Insert einfügen',self.insert_selection)
            menu.addAction('Overwrite einfügen',self.overwrite_selection)
            menu.addAction('Ripple löschen',self.ripple_delete)
            if len(self.selected_clips()) >= 2:
                menu.addAction('Gruppieren',self.group_selection)
            if any(value.group_id for value in self.selected_clips()):
                menu.addAction('Gruppe lösen',self.ungroup_selection)
            menu.addSeparator()
            if clip.kind!='text' and clip.source_type!='adjustment':
                menu.addAction('▶ Clip ansehen',self.source_preview)
            if clip.kind=='text':
                menu.addAction('Text im Inspector bearbeiten',self.focus_text_editor)
            menu.addAction('Am Abspielkopf teilen',self.split)
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
            menu.addAction('+ Text',self.add_text)
            menu.addAction('+ Adjustment-Layer',self.add_adjustment_layer)
            menu.addAction('+ Untertitel importieren (SRT/VTT)',self.import_subtitle_dialog)
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
                       source_paths=list(clip.source_paths))

    def set_selection(self, uids, anchor=None, expand_groups=False):
        available = {clip.uid: clip for clip in self.clips}
        result = []
        for uid in uids:
            if uid in available and uid not in result:
                result.append(uid)
        if expand_groups:
            groups = {available[uid].group_id for uid in result if available[uid].group_id}
            for clip in self.clips:
                if clip.group_id in groups and clip.uid not in result:
                    result.append(clip.uid)
        self.selection = result
        self.current = anchor if anchor in result else (result[-1] if result else None)
        self.fill_inspector()
        self.timeline.set_selection(self.selection, self.current)

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
                self.audio_compressor_threshold,self.audio_compressor_ratio,self.audio_ducking,self.audio_channel_mode,self.audio_pan,
                self.transform_scale,self.transform_x,self.transform_y,self.rotation,self.crop_left,self.crop_top,
                self.crop_right,self.crop_bottom,self.flip_horizontal,self.flip_vertical,self.brightness,self.contrast,
                self.saturation,self.filter_preset,self.effect_preset,self.effect_preset_apply_button,self.lut_path,self.lut_browse_button,self.opacity,self.blur,self.sharpen,self.stabilization,
                self.chroma_key_enabled,self.chroma_key_color,self.chroma_key_similarity,self.chroma_key_blend,
                self.mask_type,self.mask_x,self.mask_y,self.mask_width,self.mask_height,self.mask_feather,
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

    def _clipboard_candidates(self, anchor):
        if not self.clipboard:
            return []
        minimum = min(clip.position for clip in self.clipboard)
        group_map = {}
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
            candidates.append(self._clone_clip(clip, group_id=group_id))
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
                                source_paths=list(c.source_paths))
        return ([clone(c) for c in self.clips],
                list(self.tracks),self.current,
                {track:dict(state) for track,state in self.track_states.items()},
                dict(self.track_names),list(self.selection),[clone(c) for c in self.assets],
                [dict(marker) for marker in self.markers],dict(self.master_mixer))

    def checkpoint(self):
        self.history.append(self.snapshot()); self.history=self.history[-80:]; self.future.clear()

    def changed(self):
        self.dirty=True; self.revision+=1; self.preview_revision=-1; self.preview_signature=None
        self.preview_queued=True; self.preview_play_requested=False
        if self.preview_worker:
            # Cancel an obsolete render. The current frame stays visible while
            # the newer render is prepared in the background.
            self.preview_worker.cancel.set()
        self.transport_timer.stop(); self.transport_rate=0.0; self.transport_rate_pending=None
        self.player.pause(); self.player.setPlaybackRate(1.0); self.mode='timeline'; self.pending_seek=None
        if self.preview_path and Path(self.preview_path).is_file():
            self.preview_status.setText('Vorschau wird im Hintergrund aktualisiert …')
        else:
            self.video_stack.setCurrentIndex(0)
            self.placeholder.setText('Timeline geändert\n\n▶ Timeline berechnet eine neue Vorschau.\n„Clip ansehen“ zeigt sofort die einzelne Quelle.')
            self.preview_status.setText('Vorschau wird nach kurzer Pause im Hintergrund berechnet …')
        self.setWindowTitle(f'Framecut {APP_VERSION} · '+(Path(self.project_path).stem if self.project_path else 'Neues Projekt')+' *')
        self.autosave_label.setText('Änderungen · Autosave folgt …'); self.autosave_timer.start()
        if hasattr(self,'live_preview_box') and self.live_preview_box.isChecked() and self.clips:
            self.live_preview_timer.start()
        self.refresh()

    def preset_changed(self,*_): self.changed()

    def undo(self):
        if self.history and not self.worker:
            self.future.append(self.snapshot()); self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection,self.assets,self.markers,self.master_mixer=self.history.pop(); self.refresh_media(); self.prepare_visuals(self.assets); self.changed()

    def redo(self):
        if self.future and not self.worker:
            self.history.append(self.snapshot()); self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection,self.assets,self.markers,self.master_mixer=self.future.pop(); self.refresh_media(); self.prepare_visuals(self.assets); self.changed()

    def refresh(self):
        self.timeline.refresh(self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection,self.markers)
        self.timeline.set_visuals(self.thumbnails,self.waveforms)
        self.video_tracks.blockSignals(True); self.video_tracks.setValue(len([t for t in self.tracks if t>0])); self.video_tracks.blockSignals(False)
        self.audio_tracks.blockSignals(True); self.audio_tracks.setValue(len([t for t in self.tracks if t<0])); self.audio_tracks.blockSignals(False)
        self.total.setText(f'{len(self.clips)} Clips · {length(self.clips):.1f} s')
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
        c=self.current_clip(); self.track_combo.clear()
        if len(self.selection)>1:
            self.clip_name.setText(f'{len(self.selection)} Clips ausgewählt')
            for field in self._inspector_controls():
                field.setEnabled(False)
            self.keyframe_list.clear(); self.volume_keyframe_list.clear(); self.speed_ramp_list.clear()
            return
        if not c:
            self.clip_name.setText('Kein Clip ausgewählt')
            for field in self._inspector_controls(): field.setEnabled(False)
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
        for field in (self.lut_path,self.lut_browse_button,
                      self.opacity,self.blur,self.sharpen,self.chroma_key_enabled,self.chroma_key_color,self.chroma_key_similarity,
                      self.chroma_key_blend,self.mask_type,self.mask_x,self.mask_y,self.mask_width,self.mask_height,self.mask_feather): field.setEnabled(is_video and not is_adjustment)
        self.opacity.setEnabled(is_video); self.blur.setEnabled(is_video); self.sharpen.setEnabled(is_video)
        self.stabilization.setEnabled(is_video and not is_adjustment)
        for field in (self.keyframe_time,self.keyframe_curve,self.keyframe_list,self.keyframe_set_button,self.keyframe_remove_button): field.setEnabled(is_video and not is_adjustment)
        for field in (self.volume_keyframe_time,self.volume_keyframe_curve,self.volume_keyframe_list,self.volume_keyframe_set_button,self.volume_keyframe_remove_button): field.setEnabled(is_audioable)
        for field in (self.audio_noise_reduction,self.audio_eq_low,self.audio_eq_mid,self.audio_eq_high,self.audio_compressor_enabled,
                      self.audio_compressor_threshold,self.audio_compressor_ratio,self.audio_ducking,self.audio_channel_mode,self.audio_pan): field.setEnabled(is_audioable)
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
        self.audio_noise_reduction.setValue(c.audio_noise_reduction if is_audioable else 0)
        self.audio_eq_low.setValue(c.audio_eq_low if is_audioable else 0); self.audio_eq_mid.setValue(c.audio_eq_mid if is_audioable else 0); self.audio_eq_high.setValue(c.audio_eq_high if is_audioable else 0)
        self.audio_compressor_enabled.setChecked(c.audio_compressor_enabled if is_audioable else False)
        self.audio_compressor_threshold.setValue(c.audio_compressor_threshold if is_audioable else -18); self.audio_compressor_ratio.setValue(c.audio_compressor_ratio if is_audioable else 4)
        self.audio_ducking.setValue(c.audio_ducking*100 if is_audioable else 0)
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
            self.speed_ramp_time.setMaximum(max(0.01,c.end-c.start))
            self.speed_ramp_time.setValue(max(0.0,min(c.end-c.start,local_time)))
            self.refresh_speed_ramp_list(c)
        else:
            self.keyframe_list.clear()
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

    def select_clip(self,uid):
        if uid!=self.current and self.mode=='source':
            self.player.pause();self.pending_seek=None;self.player.setSource(QUrl());self.mode='timeline'
            self.video_stack.setCurrentIndex(0);self.placeholder.setText('Clip ausgewählt · „Clip ansehen“ startet die Quellvorschau.')
        self.set_selection([uid], uid, expand_groups=True)

    def commit_drag(self,candidate):
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
                             contrast=self.contrast.value(),saturation=self.saturation.value(),opacity=self.opacity.value()/100,
                             blur=self.blur.value(),sharpen=self.sharpen.value(),stabilization=self.stabilization.value()/100,
                             effect_preset=c.effect_preset,
                             freeze_frame=self.freeze_enabled.isChecked(),
                             freeze_duration=self.freeze_duration.value() if self.freeze_enabled.isChecked() else 0.0,
                             reverse=self.reverse_clip.isChecked(),filter_preset=self.filter_preset.currentData(),
                             lut_path=str(Path(self.lut_path.text().strip()).expanduser().resolve()) if self.lut_path.text().strip() else '',
                             chroma_key_enabled=self.chroma_key_enabled.isChecked(),chroma_key_color=self.chroma_key_color.text().strip(),
                             chroma_key_similarity=self.chroma_key_similarity.value()/100,chroma_key_blend=self.chroma_key_blend.value()/100,
                             mask_type=self.mask_type.currentData(),mask_x=self.mask_x.value()/100,mask_y=self.mask_y.value()/100,
                             mask_width=self.mask_width.value()/100,mask_height=self.mask_height.value()/100,mask_feather=self.mask_feather.value()/100)
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
                              audio_channel_mode=self.audio_channel_mode.currentData(),audio_pan=self.audio_pan.value()/100)
                transition_type='none' if c.source_type=='adjustment' else self.transition_type.currentData()
                values.update(transition_type=transition_type,
                              transition_duration=self.transition_duration.value() if transition_type!='none' else 0.0)
            candidate=replace(c,**values)
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
                      freeze_frame=False,freeze_duration=0.0,reverse=False,chroma_key_enabled=False,
                      chroma_key_color='#00ff00',chroma_key_similarity=.1,chroma_key_blend=.1,
                      mask_type='none',mask_x=0.0,mask_y=0.0,mask_width=1.0,mask_height=1.0,mask_feather=0.0)
        if all(getattr(c,key)==value for key,value in defaults.items()):
            return
        self.checkpoint(); candidate=replace(c,**defaults)
        self.clips=[candidate if item.uid==c.uid else item for item in self.clips]; self.changed()

    def add_text(self):
        if self.worker:return
        text,ok=QInputDialog.getText(self,'Text hinzufügen','Text für den Titel oder Untertitel:')
        if not ok or not text.strip():return
        if not any(c.kind=='video' for c in self.clips):
            return self.error('Füge zuerst ein Video zur Timeline hinzu.')
        position=max(0,min(self.playhead,length(self.clips)))
        duration=min(3.0,max(0.5,length(self.clips)-position)) if length(self.clips)>position else 3.0
        track=max((t for t in self.tracks if t>0),default=0)+1
        # Text has no source media limit; its visible duration is controlled by
        # the clip end/trim fields and can be extended beyond the initial 3 s.
        candidate=Clip('',864000.0,start=0,end=duration,position=position,track=track,kind='text',has_audio=False,text=text.strip(),source_type='text')
        self.checkpoint(); self.tracks.append(track); self.track_states=normalize_track_states(self.track_states,self.tracks); self.track_names=normalize_track_names(self.track_names,self.tracks); self.clips.append(candidate); self.selection=[candidate.uid]; self.current=candidate.uid; self.changed()

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

    def remove(self):
        selected=self.selected_clips()
        if selected and not self.worker and not self.selection_locked():
            removed={clip.uid for clip in selected}
            self.checkpoint(); self.clips=[clip for clip in self.clips if clip.uid not in removed]; self.selection=[]; self.current=None; self.changed()

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
                                  start=start,end=end,volume=source_clip.volume)
                try:
                    validate_timeline(self.clips+[candidate],self.tracks); proposed=candidate; break
                except ValueError:
                    continue
            if proposed is None:
                track=min(self.tracks+[0])-1
                chosen_tracks.append(track)
                proposed=replace(audio,uid=uuid.uuid4().hex,track=track,position=source_clip.position,
                                 start=start,end=end,volume=source_clip.volume)
            validate_timeline(self.clips+[proposed],chosen_tracks)
            self.checkpoint(); self.tracks=chosen_tracks; self.track_states=normalize_track_states(self.track_states,self.tracks); self.track_names=normalize_track_names(self.track_names,self.tracks)
            self.clips=[replace(v,volume=0) if v.uid==source_clip.uid else v for v in self.clips]+[proposed]
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
        cues=result['value']
        try:
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
            self.statusBar().showMessage(f'{len(new_clips)} Untertitel aus {Path(path).name} importiert.',5000)
        except Exception as exc:
            self.error(exc)

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
        self.start_job('Medien werden geprüft …',operation,self.import_done)

    def import_done(self,result):
        if not result['ok']:return self.job_error(result)
        assets,errors=result['value']
        asset_key=lambda asset:(asset.source_type,tuple(asset.source_paths) if asset.source_paths else asset.path)
        known={asset_key(asset) for asset in self.assets}
        added=[asset for asset in assets if asset_key(asset) not in known]
        self.assets.extend(added); self.prepare_visuals(added); self.refresh_media()
        if added:self.changed()
        if errors:self.error('\n'.join(errors))

    def refresh_media(self):
        self.missing_media=missing_project_media(self.clips,self.assets)
        selected_item=self.media_list.currentItem() if hasattr(self,'media_list') else None
        selected_uid=selected_item.data(MediaList.ASSET_UID_ROLE) if selected_item is not None else None
        query=self.media_search.text().strip().casefold() if hasattr(self,'media_search') else ''
        filter_value=self.media_filter.currentData() if hasattr(self,'media_filter') else 'all'
        sort_value=self.media_sort.currentData() if hasattr(self,'media_sort') else 'order'
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
            rows.append((index,c,category,offline,icon,label_kind))
        if sort_value == 'name':
            rows.sort(key=lambda row:(Path(row[1].path).name.casefold(),row[0]))
        elif sort_value == 'type':
            rows.sort(key=lambda row:(row[5],Path(row[1].path).name.casefold(),row[0]))
        elif sort_value == 'duration':
            rows.sort(key=lambda row:(-float(row[1].duration),Path(row[1].path).name.casefold(),row[0]))
        self.media_list.setUpdatesEnabled(False); self.media_list.clear()
        for index,c,category,offline,icon,label_kind in rows:
            marker='⚠  ' if offline else ''
            item=QListWidgetItem(f'{marker}{icon}  {Path(c.path).name}\n{c.duration:.1f} s  ·  {label_kind}')
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
        if hasattr(self,'proxy_box'):
            available=any(c.kind in ('video','audio') and c.source_type not in ('image','image_sequence')
                          and c.path and Path(c.path).is_file() for c in self.assets+self.clips)
            self.proxy_box.setEnabled(available)
            self.proxy_profile_combo.setEnabled(available)
            if not available and self.proxy_box.isChecked():
                self.proxy_box.setChecked(False)

    def prepare_visuals(self, assets):
        """Create a lightweight poster frame for each imported video.

        The frame is only editor metadata; source files are never modified.
        """
        for asset in assets:
            try:
                if asset.kind == 'video' and asset.path not in self.thumbnails:
                    target=self.thumbnail_cache/(uuid.uuid5(uuid.NAMESPACE_URL, asset.path).hex+'.jpg')
                    if asset.source_type in ('image','image_sequence'):
                        image=QImage(asset.source_paths[0] if asset.source_paths else asset.path)
                        if not image.isNull():
                            image=image.scaled(320,180,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                    else:
                        if not target.exists():
                            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(min(.5,max(0,asset.duration*.08))),'-i',asset.path,'-frames:v','1','-vf','scale=320:-2',str(target)],check=True,timeout=20)
                        image=QImage(str(target))
                    if not image.isNull(): self.thumbnails[asset.path]=image
                if (asset.kind == 'audio' or asset.has_audio) and asset.path not in self.waveforms:
                    target=self.thumbnail_cache/(uuid.uuid5(uuid.NAMESPACE_URL, asset.path+'-wave-v2').hex+'.png')
                    if not target.exists():
                        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',asset.path,
                                        '-filter_complex','showwavespic=s=1200x180:colors=63ead4:scale=sqrt:draw=full:filter=peak',
                                        '-frames:v','1',str(target)],check=True,timeout=30)
                    image=QImage(str(target))
                    if not image.isNull(): self.waveforms[asset.path]=image
            except (OSError, subprocess.SubprocessError):
                continue
        self.timeline.set_visuals(self.thumbnails,self.waveforms)
        self.trim_cache()

    def nudge_playhead(self, seconds):
        if self.worker:return
        self.set_playhead(max(0,min(length(self.clips),self.playhead+seconds)))

    def transport_stop(self):
        self.transport_rate_pending=None
        self.transport_timer.stop()
        self.transport_rate=0.0
        self.player.pause(); self.player.setPlaybackRate(1.0)
        self.play_button.setText('▶ Timeline')

    def _start_transport(self, rate):
        if self.worker or not self.clips:
            return
        rate=float(rate)
        if not self.preview_is_current():
            self.transport_rate_pending=rate
            self.preview_play_requested=False
            self.render_preview()
            return
        self.mode='timeline'; self.audio.setVolume(1); self.transport_rate=rate
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
        old=self.timeline.scale; scroll=self.scroll.horizontalScrollBar(); center=(scroll.value()+self.scroll.viewport().width()/2-self.timeline.LEFT)/old
        self.timeline.scale=float(value); self.timeline.refresh(self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection)
        scroll.setValue(int(center*value+self.timeline.LEFT-self.scroll.viewport().width()/2))

    def fit_timeline(self):
        width=self.scroll.viewport().width()-self.timeline.LEFT-35
        self.zoom_slider.setValue(max(2,min(200,int(width/max(5,length(self.clips))))))

    def set_playhead(self,time):
        self.playhead=max(0,min(length(self.clips),float(time))); self.timeline.set_playhead(self.playhead); self.update_time()
        if self.mode=='timeline' and self.preview_is_current():
            self.player.setPosition(int(min(self.playhead,length(self.clips))*1000))
        elif self.mode=='source' and self.current_clip():
            c=self.current_clip()
            if c.position<=time<=c.finish:self.player.setPosition(int((c.start+time-c.position)*1000))

    def seek_slider(self,value):
        self.set_playhead(value/10000*length(self.clips))

    def update_time(self):
        def clock(t):return f'{int(t)//60:02}:{t%60:04.1f}'
        total=length(self.clips); self.time_label.setText(f'{clock(self.playhead)} / {clock(total)}')
        if not self.seek.isSliderDown():self.seek.setValue(int(min(1,self.playhead/total)*10000) if total else 0)

    def play_state(self,state):
        if state==QMediaPlayer.PlayingState:
            self.play_button.setText(f'Ⅱ {self.transport_rate:g}×' if self.transport_rate else 'Ⅱ Pause')
        else:
            self.play_button.setText('▶ Timeline')

    def position_changed(self,ms):
        if self.pending_seek:return
        if self.mode=='timeline':
            if not self.preview_is_current():return
            self.playhead=ms/1000
        else:
            c=self.current_clip()
            if not c:return
            local=max(0,min(c.length,ms/1000-c.start)); self.playhead=c.position+local
            if ms/1000>=c.end-.015 and self.player.playbackState()==QMediaPlayer.PlayingState:self.player.pause()
        self.timeline.set_playhead(self.playhead); self.update_time()

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
        if not c or c.kind=='text' or self.worker:return
        self.transport_stop()
        if c.source_type in ('image','image_sequence'):
            image=QImage(c.source_paths[0] if c.source_paths else c.path)
            if image.isNull():
                return self.error('Das Bild konnte nicht angezeigt werden.')
            self.mode='source'; self.video_stack.setCurrentIndex(1); self.video.frame=image; self.video.update()
            self.preview_status.setText('BILDVORSCHAU · Timeline-Vorschau zeigt die vollständige Komposition')
            return
        if self.preview_worker:
            self.cancel_preview(wait=True); self.preview_queued=False
        self.mode='source';self.preview_status.setText('CLIPVORSCHAU · nur die ausgewählte Quelle, nicht der Mix')
        self.audio.setVolume(c.volume); self.player.setPlaybackRate(c.speed)
        source_time=c.start+max(0,min(c.length-.01,self.playhead-c.position))
        self.load_player(c.path,source_time,True,c.kind=='video')

    def toggle_play(self):
        if self.worker:return
        if self.transport_timer.isActive() or self.transport_rate != 0:
            self.transport_stop(); return
        if self.player.playbackState()==QMediaPlayer.PlayingState:
            self.player.pause();return
        if not self.clips:return self.error('Füge zuerst Medien zur Timeline hinzu.')
        if self.preview_worker:
            # A render may already be running because of live preview. Reuse
            # that render instead of starting a second FFmpeg process.
            self.preview_play_requested=True
            if getattr(self.preview_worker,'preview_signature',None) != self.preview_signature_for_current():
                self.preview_queued=True; self.preview_worker.cancel.set()
                self.preview_status.setText('Vorschau wird für die Wiedergabe aktualisiert …')
            else:
                self.preview_status.setText('Vorschau fertigstellen · Wiedergabe startet gleich …')
            return
        if self.preview_is_current():
            self.mode='timeline';self.player.setPlaybackRate(1.0);self.audio.setVolume(1)
            self.preview_status.setText('TIMELINE · alle Video- und Audiospuren · Vorschau 480p / Export in gewählter Auflösung')
            if self.playhead>=length(self.clips)-.02:self.playhead=0
            self.load_player(self.preview_path,self.playhead,True);return
        self.preview_play_requested=True
        self.render_preview()

    def auto_preview(self):
        if self.worker or not self.clips: return
        if not self.live_preview_box.isChecked() and not self.preview_play_requested:return
        self.preview_queued=False
        self.render_preview(auto=True)

    def preview_option_changed(self,*_):
        if self.clips and self.live_preview_box.isChecked():
            self.preview_queued=True
            if self.preview_worker:self.preview_worker.cancel.set()
            self.live_preview_timer.start()

    def render_preview(self,auto=False):
        if self.preview_is_current():
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
        def operation(progress,cancel):
            use_gpu=self.gpu_preview_box.isChecked()
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
        job.progress.connect(lambda value:self.preview_status.setText(f'Mehrspur-Vorschau wird aktualisiert … {value}%'))
        job.result.connect(lambda result,j=job:self.finish_preview_job(j,result,auto,revision,signature))
        job.start()

    def finish_preview_job(self,job,result,auto,revision,signature):
        if self.preview_worker is not job:
            return
        job.wait(); self.preview_worker=None; job.deleteLater()
        stale=revision!=self.revision or signature!=self.preview_signature_for_current()
        if not result['ok']:
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
        self.mode='timeline'; self.audio.setVolume(1)
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
            self.preview_queued=True
            if self.clips and self.live_preview_box.isChecked():
                self.live_preview_timer.start()
            return
        if self.worker:
            return
        self.start_proxy_generation()

    def start_proxy_generation(self):
        if self.worker or not self.proxy_enabled:
            return
        if not any(c.kind in ('video','audio') and c.source_type not in ('image','image_sequence')
                   and c.path for c in self.clips):
            self.statusBar().showMessage('Für diese Timeline werden keine Proxy-Dateien benötigt.',4000)
            return
        if self.project_path:
            directory=Path(self.project_path).with_suffix('.proxies')
        else:
            directory=self.state_dir/'proxies'/uuid.uuid4().hex
        self.proxy_directory=directory
        clips=[replace(c,source_paths=list(c.source_paths)) for c in self.clips]
        assets=[replace(c,source_paths=list(c.source_paths)) for c in self.assets]
        def operation(progress,cancel):
            return create_proxy_files(clips,assets,directory,profile=self.proxy_profile,
                                      progress=progress,cancel=cancel)
        def complete(result):
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
        self.start_job('Proxy-Dateien werden erzeugt …',operation,complete)

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
                   item['track_states'],item['settings'],master_settings=item.get('master_settings',self.master_mixer))
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
        self.start_job(item['label']+' wird gerendert …',operation,complete)

    def start_export(self):
        if self.worker:return
        if not self.clips:return self.error('Die Timeline ist leer.')
        dialog=ExportDialog(self)
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
        source_files=[path for clip in self.clips+self.assets for path in ([clip.path]+list(clip.source_paths))]
        if any(Path(path).resolve()==target for path in source_files if path):return self.error('Der Export darf keine Quelldatei überschreiben.')
        if target.exists() and QMessageBox.question(self,'Datei ersetzen?',f'{target}\nüberschreiben?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        clips=[replace(c,source_paths=list(c.source_paths)) for c in self.clips]
        tracks=list(self.tracks);track_states={track:dict(state) for track,state in self.track_states.items()};size=PRESETS[self.preset.currentText()]
        pending_targets=[item['target'] for item in self.render_queue]
        if self.render_current: pending_targets.append(self.render_current['target'])
        if target in pending_targets:
            return self.error('Dieses Ziel liegt bereits in der Render-Queue.')
        self.render_queue.append({'target':target,'clips':clips,'tracks':tracks,'track_states':track_states,
                                  'size':size,'settings':export_settings,'master_settings':dict(self.master_mixer),
                                  'label':f"{format_info['label']} · {target.name}"})
        self.update_render_queue_button()
        if dialog.queue_only_box.isChecked():
            self.statusBar().showMessage(f'Export eingereiht · {target.name}',5000)
            return
        self.render_queue_paused=False; self.process_render_queue()

    def start_job(self,title,operation,callback):
        self.cancel_preview(wait=True)
        self.transport_stop()
        self.player.pause(); self.centralWidget().setEnabled(False)
        self.progress=QProgressDialog(title,'Abbrechen',0,100,self)
        self.progress.setWindowModality(Qt.ApplicationModal);self.progress.setMinimumDuration(0)
        self.progress.setAutoClose(False);self.progress.setAutoReset(False)
        self.worker=Job(operation);self.progress.canceled.connect(self.worker.cancel.set)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.result.connect(lambda result:self.finish_job(result,callback))
        self.worker.start();self.progress.show()

    def finish_job(self,result,callback):
        self.worker.wait();self.worker.deleteLater();self.worker=None
        self.progress.close();self.progress.deleteLater();self.centralWidget().setEnabled(True)
        callback(result)

    def job_error(self,result):
        if result.get('cancelled'):self.statusBar().showMessage('Abgebrochen · keine Zieldatei ersetzt',6000)
        else:self.error(result.get('error','Unbekannter Fehler'))

    def check_for_updates(self,silent=False):
        if self.update_job or self.update_download_job:
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
        if self.timeline.drag:
            self.autosave_timer.start();return
        try:
            save_project(self.recovery_path,self.clips,self.preset.currentText(),self.tracks,self.assets,self.project_path,self.track_states,self.track_names,self.markers,self.master_mixer)
            self.autosave_label.setText('Autosave ✓');self.autosave_label.setToolTip(str(self.recovery_path))
        except Exception as exc:
            self.autosave_label.setText('Autosave fehlgeschlagen');self.statusBar().showMessage(str(exc))

    def clear_recovery(self):
        self.autosave_timer.stop()
        if self.recovery_enabled:
            try:self.recovery_path.unlink(missing_ok=True)
            except OSError:pass

    def offer_recovery(self):
        if not self.recovery_path.exists():return
        answer=QMessageBox.question(self,'Ungespeicherten Schnitt wiederherstellen?',
            'Es gibt eine automatische Sicherung der letzten Sitzung. Wiederherstellen?',QMessageBox.Yes|QMessageBox.No,QMessageBox.Yes)
        if answer!=QMessageBox.Yes:self.clear_recovery();return
        try:
            data=load_project(self.recovery_path);self.apply_project(data,data.get('origin'));self.changed()
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
            self.setWindowTitle(f'Framecut {APP_VERSION} · '+Path(path).stem);self.autosave_label.setText('Projekt gespeichert ✓');return True
        except Exception as exc:self.error(exc);return False

    def can_discard(self):
        if not self.dirty:return True
        answer=QMessageBox.question(self,'Projekt speichern?','Es gibt ungespeicherte Änderungen.',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
        return self.save() if answer==QMessageBox.Save else answer==QMessageBox.Discard

    def apply_project(self,data,path):
        self.cancel_preview(wait=True); self.preview_queued=False; self.preview_play_requested=False
        self.transport_stop()
        self.player.stop();self.pending_seek=None;self.player.setSource(QUrl());self.video_stack.setCurrentIndex(0)
        self.clips=data['clips'];self.tracks=data['tracks'];self.track_states=normalize_track_states(data.get('track_states'),self.tracks);self.track_names=normalize_track_names(data.get('track_names'),self.tracks);self.master_mixer=normalize_master_mixer(data.get('mixer'));self.assets=data['assets'];self.markers=normalize_markers(data.get('markers'),length(self.clips));self.project_path=path
        self.missing_media=list(data.get('missing_media',[]));self.proxy_enabled=False;self.proxy_map={};self.proxy_directory=None
        self.proxy_box.blockSignals(True);self.proxy_box.setChecked(False);self.proxy_box.blockSignals(False)
        self.current=self.clips[0].uid if self.clips else None;self.selection=[self.current] if self.current else [];self.playhead=0
        self.history.clear();self.future.clear();self.revision+=1;self.preview_revision=-1;self.preview_signature=None;self.preview_path=None
        self.preset.blockSignals(True);self.preset.setCurrentText(data['preset'] if data['preset'] in PRESETS else next(iter(PRESETS)));self.preset.blockSignals(False)
        self.mode='timeline';self.dirty=False;self.prepare_visuals(self.assets);self.refresh_media();self.refresh()
        self.placeholder.setText('▶ Timeline berechnet die Mehrspur-Vorschau.\n„Clip ansehen“ zeigt sofort die Quelle.')
        self.preview_status.setText('Timeline geladen · Vorschau noch nicht berechnet')
        self.setWindowTitle(f'Framecut {APP_VERSION} · '+(Path(path).stem if path else 'Neues Projekt'))

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
        self.suggested_name='Mein-Film.framecut';self.autosave_label.setText('Autosave bereit')

    def closeEvent(self,event):
        if self.worker:
            self.error('Bitte den laufenden Vorgang zuerst abschließen oder abbrechen.');event.ignore();return
        if self.render_queue:
            answer=QMessageBox.question(self,'Render-Queue schließen?',
                f'{len(self.render_queue)} Exporte sind noch eingereiht und werden beim Schließen verworfen.',
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer!=QMessageBox.Yes:
                event.ignore();return
            self.render_queue.clear(); self.update_render_queue_button()
        if self.can_discard():
            self.transport_stop()
            self.cancel_preview(wait=True)
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
        QMessageBox.warning(None,'Framecut läuft bereits','Bitte nutze das bereits geöffnete Framecut-3.7-Fenster.');return 1
    window=Editor(state);window.show()
    project_argument=next((argument for argument in sys.argv[1:] if Path(argument).suffix.lower() in ('.framecut','.zip')),None)
    if project_argument:
        QTimer.singleShot(0,lambda path=project_argument:window.open_project_path(path))
    result=app.exec();lock.unlock();return result


if __name__=='__main__':sys.exit(main())
