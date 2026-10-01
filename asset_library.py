"""Framecut's built-in, offline starter library.

The library deliberately contains descriptions and deterministic presets instead
of downloaded third-party packs. Sounds are generated as tiny WAV files on
first use, while effects, transitions and animations map directly to the
existing Clip fields and renderer.
"""
from dataclasses import dataclass, field
import math
from pathlib import Path
import struct
import wave

from PySide6.QtCore import Qt, Signal, QMimeData, QSize
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from core import Clip
from ux import line_icon


LIBRARY_MIME = 'application/x-framecut-library'


@dataclass(frozen=True)
class LibraryItem:
    item_id: str
    title: str
    category: str
    kind: str
    description: str
    tags: tuple = ()
    icon: str = 'package-x-generic'
    duration: float = 0.0
    parameters: dict = field(default_factory=dict)


LIBRARY_CATEGORIES = {
    'all': 'Alle',
    'sounds': 'Sounds',
    'effects': 'Videoeffekte',
    'animations': 'Animationen',
    'transitions': 'Übergänge',
}


BUILTIN_LIBRARY = (
    LibraryItem('sound_whoosh', 'Whoosh', 'sounds', 'sound',
                'Heller, kurzer Sweep für Übergänge und Bewegungen.',
                ('sweep', 'transition', 'bewegung'), 'audio-volume-high', 0.72,
                {'profile': 'whoosh'}),
    LibraryItem('sound_pop', 'Pop', 'sounds', 'sound',
                'Kurzer, weicher Pop für Text, Sticker und Einblendungen.',
                ('pop', 'text', 'sticker'), 'audio-volume-high', 0.34,
                {'profile': 'pop'}),
    LibraryItem('sound_click', 'Click', 'sounds', 'sound',
                'Trockener Klick für UI-Elemente, Schnitte und Marker.',
                ('click', 'ui', 'schnitt'), 'audio-volume-high', 0.16,
                {'profile': 'click'}),
    LibraryItem('sound_impact', 'Impact', 'sounds', 'sound',
                'Tiefer kurzer Impact für harte Schnitte und Betonungen.',
                ('impact', 'hit', 'schnitt'), 'audio-volume-high', 0.62,
                {'profile': 'impact'}),
    LibraryItem('sound_riser', 'Riser', 'sounds', 'sound',
                'Ansteigender Sweep für Aufbau, Reveal und Drop.',
                ('riser', 'build', 'reveal'), 'audio-volume-high', 1.35,
                {'profile': 'riser'}),
    LibraryItem('sound_tick', 'Tick', 'sounds', 'sound',
                'Sehr kurzer Tick für Timer, Listen und schnelle Cuts.',
                ('tick', 'timer', 'cut'), 'audio-volume-high', 0.11,
                {'profile': 'tick'}),
    LibraryItem('effect_cinematic', 'Cinematic', 'effects', 'effect',
                'Kontrastreich, leicht entsättigt und mit dezenter Schärfe.',
                ('look', 'film', 'kontrast'), 'package-x-generic',
                parameters={'effect_preset': 'cinematic'}),
    LibraryItem('effect_dream', 'Dream', 'effects', 'effect',
                'Weicher, heller Look für emotionale und ruhige Szenen.',
                ('soft', 'warm', 'look'), 'package-x-generic',
                parameters={'effect_preset': 'dream'}),
    LibraryItem('effect_noir', 'Noir', 'effects', 'effect',
                'Schwarzweiß-Look mit starkem Kontrast und Schärfe.',
                ('black', 'white', 'contrast'), 'package-x-generic',
                parameters={'effect_preset': 'noir'}),
    LibraryItem('effect_vivid', 'Vivid', 'effects', 'effect',
                'Satte Farben und mehr Präsenz für Social-Clips.',
                ('color', 'social', 'saturated'), 'package-x-generic',
                parameters={'effect_preset': 'vivid'}),
    LibraryItem('effect_soft_focus', 'Soft Focus', 'effects', 'effect',
                'Sanfte Unschärfe für Hintergründe und atmosphärische Bilder.',
                ('blur', 'soft', 'atmosphere'), 'package-x-generic',
                parameters={'effect_preset': 'soft_focus'}),
    LibraryItem('effect_stabilize', 'Stabilize', 'effects', 'effect',
                'Stabilisierung als Startwert für verwackelte Videoclips.',
                ('camera', 'smooth', 'stabil'), 'package-x-generic',
                parameters={'effect_preset': 'custom', 'stabilization': 0.65}),
    LibraryItem('animation_zoom_in', 'Zoom In', 'animations', 'animation',
                'Sanfter Push-in vom leicht verkleinerten Startbild.',
                ('zoom', 'push', 'social'), 'media-playback-start',
                parameters={'animation': 'zoom_in'}),
    LibraryItem('animation_zoom_out', 'Zoom Out', 'animations', 'animation',
                'Ruhiger Pull-out für einen weichen Szenenabschluss.',
                ('zoom', 'pull', 'out'), 'media-playback-start',
                parameters={'animation': 'zoom_out'}),
    LibraryItem('animation_slide_left', 'Slide Left', 'animations', 'animation',
                'Clip kommt von rechts in den Bildraum.',
                ('slide', 'left', 'motion'), 'media-playback-start',
                parameters={'animation': 'slide_left'}),
    LibraryItem('animation_slide_up', 'Slide Up', 'animations', 'animation',
                'Clip fährt von unten in den Bildraum.',
                ('slide', 'up', 'motion'), 'media-playback-start',
                parameters={'animation': 'slide_up'}),
    LibraryItem('animation_text_fade', 'Text Fade', 'animations', 'animation',
                'Ein-/Ausblendanimation für Textclips.',
                ('text', 'fade', 'title'), 'format-justify-fill',
                parameters={'animation': 'text_fade'}),
    LibraryItem('animation_text_slide', 'Text Slide', 'animations', 'animation',
                'Text kommt von links in den Bildraum.',
                ('text', 'slide', 'lower third'), 'format-justify-fill',
                parameters={'animation': 'text_slide'}),
    LibraryItem('transition_dissolve', 'Dissolve', 'transitions', 'transition',
                'Klassische weiche Überblendung zwischen zwei Clips.',
                ('fade', 'soft', 'classic'), 'view-refresh',
                parameters={'transition_type': 'dissolve', 'duration': 0.5}),
    LibraryItem('transition_slide', 'Slide', 'transitions', 'transition',
                'Der nächste Clip schiebt sich von rechts in die Szene.',
                ('slide', 'motion', 'cut'), 'view-refresh',
                parameters={'transition_type': 'slide_right', 'duration': 0.5}),
    LibraryItem('transition_zoom', 'Zoom', 'transitions', 'transition',
                'Dynamischer Zoom-Übergang für schnelle Social-Schnitte.',
                ('zoom', 'social', 'dynamic'), 'view-refresh',
                parameters={'transition_type': 'zoom', 'duration': 0.5}),
    LibraryItem('transition_dip', 'Dip to Black', 'transitions', 'transition',
                'Kurzer schwarzer Dip für klare Kapitel- oder Szenenwechsel.',
                ('black', 'chapter', 'cinematic'), 'view-refresh',
                parameters={'transition_type': 'dip_to_black', 'duration': 0.5}),
)

LIBRARY_BY_ID = {item.item_id: item for item in BUILTIN_LIBRARY}


def library_items():
    """Return an immutable-friendly snapshot for UI and tests."""
    return tuple(BUILTIN_LIBRARY)


def get_library_item(item_id):
    return LIBRARY_BY_ID.get(str(item_id))


def library_preview_clip(item, position, track):
    """Create a render-free ghost clip for a sound drag preview."""
    if item is None or item.kind != 'sound':
        return None
    return Clip('', max(0.1, float(item.duration)), start=0.0,
                end=max(0.1, float(item.duration)), position=float(position),
                track=int(track), kind='audio', has_audio=True,
                source_type='audio', display_name=item.title)


def library_sound_path(item_id, state_dir):
    item = get_library_item(item_id)
    if item is None or item.kind != 'sound':
        raise ValueError('Unbekannter Bibliotheks-Sound.')
    root = Path(state_dir).expanduser().resolve() / 'library' / 'sounds'
    root.mkdir(parents=True, exist_ok=True)
    target = root / f'{item.item_id}.wav'
    if not target.is_file() or target.stat().st_size < 44:
        _write_starter_wav(target, item.parameters.get('profile', item.item_id), item.duration)
    return target


def _wave_value(profile, time, duration):
    progress = max(0.0, min(1.0, time/max(duration, 1e-6)))
    if profile == 'whoosh':
        frequency = 240 + 1300*progress*progress
        envelope = min(1.0, progress*10) * min(1.0, (1-progress)*5)
        return math.sin(2*math.pi*frequency*time) * envelope * 0.42
    if profile == 'riser':
        frequency = 100 + 1500*progress
        envelope = min(1.0, progress*4) * .34
        return math.sin(2*math.pi*frequency*time) * envelope
    if profile == 'pop':
        envelope = math.exp(-progress*8)
        return (math.sin(2*math.pi*220*time) * .55 +
                math.sin(2*math.pi*880*time) * .18) * envelope
    if profile == 'impact':
        envelope = math.exp(-progress*10)
        return (math.sin(2*math.pi*(75+40*progress)*time) * .7 +
                math.sin(2*math.pi*1700*time) * .12) * envelope
    if profile == 'click':
        envelope = math.exp(-progress*32)
        return (math.sin(2*math.pi*1800*time) + .35*math.sin(2*math.pi*3400*time)) * envelope * .45
    if profile == 'tick':
        envelope = math.exp(-progress*45)
        return math.sin(2*math.pi*1200*time) * envelope * .32
    return math.sin(2*math.pi*440*time) * .2


def _write_starter_wav(target, profile, duration, sample_rate=44100):
    """Write a small mono PCM starter sound without external media."""
    frames = bytearray()
    count = max(1, int(float(duration)*sample_rate))
    for index in range(count):
        time = index/sample_rate
        sample = max(-1.0, min(1.0, _wave_value(profile, time, float(duration))))
        frames.extend(struct.pack('<h', int(sample*32767)))
    temporary = target.with_suffix('.tmp.wav')
    with wave.open(str(temporary), 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(sample_rate)
        stream.writeframes(frames)
    temporary.replace(target)


class LibraryList(QListWidget):
    """List that exposes sound items as safe internal drag data."""
    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None:
            return
        drag = QDrag(self)
        mime = QMimeData()
        item_id = str(item.data(Qt.UserRole))
        mime.setData(LIBRARY_MIME, item_id.encode('utf-8'))
        mime.setText(item_id)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class AssetLibraryPanel(QWidget):
    """Compact left-panel browser for built-in sounds and editing presets."""
    use_requested = Signal(str)
    preview_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('assetLibraryPanel')
        self._items = library_items()
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(7)
        intro = QLabel('STARTER-BIBLIOTHEK'); intro.setObjectName('heading'); layout.addWidget(intro)
        hint = QLabel('Sounds, Looks und Animationen direkt verwenden. Sounds lassen sich in die Timeline ziehen.');
        hint.setObjectName('subtle'); hint.setWordWrap(True); layout.addWidget(hint)
        self.search = QLineEdit(); self.search.setPlaceholderText('Bibliothek durchsuchen …')
        self.search.setClearButtonEnabled(True); self.search.setToolTip('Nach Name, Kategorie oder Schlagwort suchen'); layout.addWidget(self.search)
        self.category = QComboBox()
        for value, title in LIBRARY_CATEGORIES.items(): self.category.addItem(title, value)
        self.category.setToolTip('Bibliothekskategorie wählen'); layout.addWidget(self.category)
        self.list = LibraryList(); self.list.setObjectName('assetLibraryList'); self.list.setIconSize(self.list.iconSize())
        self.list.setSpacing(2); self.list.setAlternatingRowColors(False); self.list.setDragEnabled(True)
        self.list.itemDoubleClicked.connect(lambda *_: self.use_current())
        self.list.currentItemChanged.connect(lambda *_: self.update_details())
        self.search.textChanged.connect(self.refresh); self.category.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.list, 1)
        self.details = QLabel('Wähle ein Bibliothekselement aus.'); self.details.setObjectName('subtle'); self.details.setWordWrap(True); layout.addWidget(self.details)
        actions = QHBoxLayout(); actions.setContentsMargins(0,0,0,0); actions.setSpacing(5)
        self.preview = QPushButton('Vorschau'); self.preview.setIcon(line_icon('media-playback-start')); self.preview.clicked.connect(self.preview_current); actions.addWidget(self.preview)
        self.use = QPushButton('Verwenden'); self.use.setObjectName('primary'); self.use.clicked.connect(self.use_current); actions.addWidget(self.use)
        layout.addLayout(actions)
        self.refresh()

    def current_item_id(self):
        current = self.list.currentItem()
        return str(current.data(Qt.UserRole)) if current is not None else None

    def refresh(self):
        category = self.category.currentData() or 'all'
        query = self.search.text().strip().casefold()
        self.list.setUpdatesEnabled(False); self.list.clear()
        visible=[]
        for item in self._items:
            haystack=' '.join((item.title,item.description,item.category,*item.tags)).casefold()
            if category != 'all' and item.category != category:
                continue
            if query and query not in haystack:
                continue
            visible.append(item)
            row=QListWidgetItem()
            row.setData(Qt.UserRole,item.item_id); row.setIcon(line_icon(item.icon))
            row.setText(f'{item.title}\n{LIBRARY_CATEGORIES[item.category]} · {item.description}')
            row.setToolTip(f'{item.title}\n{item.description}\nSchlagworte: {", ".join(item.tags)}')
            # Keep rows compact and predictable when the left panel is narrow.
            # The full description remains available through the tooltip.
            row.setSizeHint(QSize(0,56))
            self.list.addItem(row)
        self.list.setUpdatesEnabled(True)
        if self.list.count(): self.list.setCurrentRow(0)
        self.update_details()

    def update_details(self):
        item=get_library_item(self.current_item_id())
        enabled=item is not None
        self.preview.setEnabled(enabled and item.kind == 'sound')
        self.use.setEnabled(enabled)
        if not item:
            self.details.setText('Keine Elemente für diese Suche.'); return
        action = 'Doppelklick oder Verwenden: in die Timeline einfügen.' if item.kind == 'sound' else 'Doppelklick oder Verwenden: auf den ausgewählten Clip anwenden.'
        self.details.setText(f'<b>{item.title}</b> · {item.description}<br>{action}')

    def preview_current(self):
        item_id=self.current_item_id()
        if item_id: self.preview_requested.emit(item_id)

    def use_current(self):
        item_id=self.current_item_id()
        if item_id: self.use_requested.emit(item_id)
