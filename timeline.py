"""Painted multitrack timeline with transactional drag/trim and snapping."""
from dataclasses import replace
from pathlib import Path
from time import monotonic
from PySide6.QtCore import Qt, Signal, QRectF, QMimeData, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QDrag, QImage, QPolygonF
from PySide6.QtWidgets import QWidget, QListWidget
from core import edited_clip, snap_time, length

ASSET_MIME = 'application/x-framecut-asset'


class MediaList(QListWidget):
    ASSET_INDEX_ROLE = Qt.UserRole
    ASSET_UID_ROLE = Qt.UserRole + 1

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)

    def asset_index(self):
        """Return the source asset index stored on the visible list item."""
        item = self.currentItem()
        if item is None:
            return -1
        value = item.data(self.ASSET_INDEX_ROLE)
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def startDrag(self, supported):
        index = self.asset_index()
        if index < 0:
            return
        drag = QDrag(self)
        mime = QMimeData()
        # Search and sorting change the visual row, not the source asset index.
        mime.setData(ASSET_MIME, str(index).encode())
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class Timeline(QWidget):
    selected = Signal(str)
    selection_changed = Signal(object)
    context_requested = Signal(str, object)
    track_context_requested = Signal(int, object)
    seek = Signal(float)
    commit = Signal(object)
    add_asset = Signal(int, float, int)
    delete_selected = Signal()
    track_mute_requested = Signal(int)
    track_lock_requested = Signal(int)
    marker_context_requested = Signal(float, object)
    zoom_request = Signal(int)
    pan_request = Signal(int)
    gesture_done = Signal()
    LEFT, TOP, ROW = 150, 36, 70

    def __init__(self):
        super().__init__()
        self.clips = []
        self.tracks = [2, 1, -1, -2]
        self.track_states = {}
        self.track_names = {}
        self.current = None
        self.selection = []
        self.markers = []
        self.playhead = 0.0
        self.scale = 60.0
        self.snap = True
        self.drag = None
        self.playhead_drag = False
        self.pan_drag = None
        self.marquee_start = None
        self.marquee_current = None
        self.marquee_active = False
        self.marquee_append = False
        self.ghost = None
        self.snapline = None
        # Some Linux/Qt combinations deliver both the mouse right-click path
        # and a follow-up context-menu event. Keep one native gesture from
        # opening the editor menu twice while still allowing a new click
        # immediately after a different gesture.
        self._last_context_signature = None
        self._last_context_time = -1.0
        self.thumbnails = {}
        self.waveforms = {}
        # Scaling poster frames and waveform images during every paint event
        # made playhead dragging and clip selection unnecessarily expensive.
        # These caches are keyed by the small set of values that changes the
        # rendered image, so ordinary repainting only reuses already prepared
        # QImages.
        self._scaled_thumbnails = {}
        self._scaled_waveforms = {}
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        # QScrollArea/viewport combinations can swallow the default
        # QWidget context-menu event on Linux. Handle the right button
        # directly in mousePressEvent so the editor always receives it.
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setAcceptDrops(True)
        self.setToolTip('M = Spur stumm · L = Spur sperren · Clipmitte ziehen: verschieben · Ränder ziehen: kürzen · leere Fläche ziehen: Mehrfachauswahl · Strg+Linksklick: Auswahl erweitern · Strg+Linksklick ziehen: Timeline verschieben · Umschalt: ohne Einrasten · Strg+Mausrad: Zoom · weißen Abspielkopf oben ziehen')
        self.refresh([], self.tracks, None)

    def refresh(self, clips, tracks, current, track_states=None, track_names=None, selection=None, markers=None):
        self.clips, self.tracks, self.current = clips, sorted(tracks, reverse=True), current
        if markers is not None:
            self.markers = [dict(marker) for marker in markers]
        self.selection = [uid for uid in (selection or ([current] if current else []))
                          if any(clip.uid == uid for clip in clips)]
        self.track_names = track_names or {}
        states = track_states or {}
        self.track_states = {}
        for track in self.tracks:
            raw = states.get(track, states.get(str(track), {})) if isinstance(states, dict) else {}
            self.track_states[track] = {"muted": bool(raw.get("muted", False)),
                                        "locked": bool(raw.get("locked", False))} if isinstance(raw, dict) else {"muted": False, "locked": False}
        minimum_height = self.TOP + len(self.tracks)*self.ROW + 16
        minimum_width = max(800, int((length(clips)+10)*self.scale)+self.LEFT)
        if self.minimumHeight() != minimum_height:
            self.setMinimumHeight(minimum_height)
        if self.minimumWidth() != minimum_width:
            self.setMinimumWidth(minimum_width)
        self.update()

    def set_thumbnails(self, thumbnails):
        """Set poster frames keyed by absolute source path."""
        self.thumbnails = thumbnails or {}
        self._scaled_thumbnails.clear()
        self.update()

    def set_waveforms(self, waveforms):
        self.waveforms = waveforms or {}
        self._scaled_waveforms.clear()
        self.update()

    def set_visuals(self, thumbnails, waveforms):
        """Update both image collections with one repaint instead of two."""
        thumbnails = thumbnails or {}
        waveforms = waveforms or {}
        if (set(thumbnails) != set(self.thumbnails)
                or set(waveforms) != set(self.waveforms)):
            self._scaled_thumbnails.clear()
            self._scaled_waveforms.clear()
        self.thumbnails = thumbnails
        self.waveforms = waveforms
        self.update()

    def set_selection(self, uids, current=None):
        """Change one or many selected clips while repainting their bounds."""
        old_ids = set(self.selection)
        new_selection = [uid for uid in uids if any(clip.uid == uid for clip in self.clips)]
        if current is None:
            current = new_selection[-1] if new_selection else None
        if new_selection == self.selection and current == self.current:
            return
        dirty = []
        for clip in self.clips:
            if clip.uid in old_ids or clip.uid in new_selection:
                dirty.append(self.rect_for(clip).toRect().adjusted(-4, -4, 4, 4))
        self.selection = new_selection
        self.current = current
        if dirty:
            area = dirty[0]
            for rect in dirty[1:]:
                area = area.united(rect)
            self.update(area)
        else:
            self.update()

    def set_current(self, uid):
        """Compatibility helper for callers that select one clip."""
        self.set_selection([uid], uid)

    def set_playhead(self, time):
        """Move the playhead and invalidate only its old/new narrow columns."""
        old_x = int(self.LEFT + self.playhead*self.scale)
        self.playhead = max(0.0, float(time))
        new_x = int(self.LEFT + self.playhead*self.scale)
        left = max(0, min(old_x, new_x)-8)
        right = min(self.width(), max(old_x, new_x)+9)
        self.update(left, 0, max(1, right-left), self.height())

    def marker_at(self, point):
        """Return the nearest timeline marker when the top ruler was hit."""
        if point.y() > self.TOP or not self.markers:
            return None
        time = self.time_at(point.x())
        marker = min(self.markers, key=lambda value: abs(float(value.get('time', 0.0))-time))
        return marker if abs(float(marker.get('time', 0.0))-time) <= 8 / max(self.scale, 1.0) else None

    def snap_targets(self, excluded=()):
        """Return deduplicated global snap targets for moves, trims and drops."""
        excluded = set(excluded)
        values = [0.0, length(self.clips), self.playhead]
        values.extend(float(marker.get('time', 0.0)) for marker in self.markers)
        values.extend(value for clip in self.clips if clip.uid not in excluded
                      for value in (clip.position, clip.finish))
        return sorted({round(max(0.0, value), 6) for value in values})

    def _thumbnail(self, path, height):
        image = self.thumbnails.get(path)
        if image is None or image.isNull():
            return None
        key = (path, int(height))
        cached = self._scaled_thumbnails.get(key)
        if cached is not None:
            return cached
        target_h = max(8, int(height))
        scaled = image.scaled(max(1, int(target_h*image.width()/max(1, image.height()))),
                              target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._scaled_thumbnails[key] = scaled
        if len(self._scaled_thumbnails) > 256:
            self._scaled_thumbnails.clear()
            self._scaled_thumbnails[key] = scaled
        return scaled

    def _waveform(self, clip, width, height):
        image = self.waveforms.get(clip.path)
        if image is None or image.isNull():
            return None
        key = (clip.uid, round(clip.start, 6), round(clip.end, 6), int(width), int(height))
        cached = self._scaled_waveforms.get(key)
        if cached is not None:
            return cached
        source_width = image.width()
        left = max(0, min(source_width-1, int(source_width*clip.start/max(clip.duration, 1e-9))))
        right = max(left+1, min(source_width, int(source_width*clip.end/max(clip.duration, 1e-9))))
        cropped = image.copy(left, 0, right-left, image.height())
        scaled = cropped.scaled(max(1, int(width)), max(8, int(height)),
                                Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._scaled_waveforms[key] = scaled
        if len(self._scaled_waveforms) > 512:
            self._scaled_waveforms.clear()
            self._scaled_waveforms[key] = scaled
        return scaled

    def rect_for(self, clip):
        row = self.tracks.index(clip.track)
        return QRectF(self.LEFT+clip.position*self.scale, self.TOP+row*self.ROW+7,
                      max(3,clip.length*self.scale), self.ROW-14)

    def time_at(self, x):
        return max(0,(x-self.LEFT)/self.scale)

    def track_at(self, y):
        index = int((y-self.TOP)//self.ROW)
        return self.tracks[index] if 0 <= index < len(self.tracks) else None

    def track_control_at(self, point):
        if point.x() >= self.LEFT or point.y() < self.TOP:
            return None
        track = self.track_at(point.y())
        if track is None:
            return None
        if self.LEFT-52 <= point.x() < self.LEFT-30:
            return track, "mute"
        if self.LEFT-28 <= point.x() < self.LEFT-6:
            return track, "lock"
        return None

    def track_locked(self, track):
        return bool(self.track_states.get(track, {}).get("locked", False))

    def hit(self, point):
        return next((c for c in reversed(self.clips) if self.rect_for(c).contains(point)), None)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#0c131b'))
        ruler = QRectF(0, 0, self.width(), self.TOP)
        p.fillRect(ruler, QColor('#111d28'))
        p.fillRect(QRectF(0, 0, self.LEFT, self.TOP), QColor('#15232e'))
        p.setPen(QColor('#8ea6b5'))
        p.setFont(QFont('Sans', 8, QFont.Bold))
        p.drawText(QRectF(14, 0, self.LEFT-24, self.TOP), Qt.AlignLeft|Qt.AlignVCenter, 'TRACKS')
        p.setFont(QFont('Sans',9))
        viewport = QRectF(event.rect())
        steps = [.1,.25,.5,1,2,5,10,15,30,60,120,300,600]
        step = next((s for s in steps if s*self.scale>=65),600)
        begin = max(0,int((viewport.left()-self.LEFT)/self.scale/step))
        end = int((viewport.right()-self.LEFT)/self.scale/step)+2
        for k in range(begin,end):
            t=k*step; x=self.LEFT+t*self.scale
            p.setPen(QColor('#22323f')); p.drawLine(int(x),self.TOP,int(x),self.height())
            p.setPen(QColor('#9ab0bd'))
            p.drawText(int(x)+5,22,f'{int(t)//60:02}:{t%60:04.1f}' if step<1 else f'{int(t)//60:02}:{int(t)%60:02}')
        p.fillRect(0,self.TOP,self.LEFT,self.height()-self.TOP,QColor('#111b25'))
        p.setPen(QPen(QColor('#304451'),1)); p.drawLine(self.LEFT,0,self.LEFT,self.height())
        p.setFont(QFont('Sans',9))
        for i, track in enumerate(self.tracks):
            y=self.TOP+i*self.ROW
            row_color = QColor('#101a23' if i % 2 == 0 else '#0e1720')
            p.fillRect(QRectF(0,y,self.width(),self.ROW), row_color)
            p.setPen(QColor('#233541')); p.drawLine(0,y,self.width(),y)
            p.setPen(QColor('#8bd9c5' if track < 0 else '#8fc9e1'))
            p.setFont(QFont('Sans',9,QFont.Bold))
            name=self.track_names.get(track, f'VIDEO {track}' if track>0 else f'AUDIO {-track}')
            track_icon='▣' if track > 0 else '♫'
            p.drawText(QRectF(12,y+9,self.LEFT-64,22),Qt.AlignLeft|Qt.AlignVCenter,f'{track_icon}  {name}')
            p.setFont(QFont('Sans',8))
            p.setPen(QColor('#6f8797'))
            p.drawText(QRectF(12,y+32,self.LEFT-24,18),Qt.AlignLeft|Qt.AlignVCenter,'Bild + Ton' if track>0 else 'Musik / Ton')
            state = self.track_states.get(track, {})
            mute_color = QColor('#ff9ca6' if state.get('muted') else '#78909e')
            lock_color = QColor('#f4c86b' if state.get('locked') else '#78909e')
            for box_x, letter, color in ((self.LEFT-53,'M',mute_color),(self.LEFT-29,'L',lock_color)):
                p.setBrush(QColor('#26333d') if ((letter == 'M' and state.get('muted')) or (letter == 'L' and state.get('locked'))) else QColor('#192630'))
                p.setPen(QPen(QColor('#334957'),1)); p.drawRoundedRect(QRectF(box_x,y+16,20,20),5,5)
                p.setPen(color); p.setFont(QFont('Sans',8,QFont.Bold)); p.drawText(QRectF(box_x,y+16,20,20),Qt.AlignCenter,letter)
        for marker in self.markers:
            marker_time = float(marker.get('time', 0.0))
            x = self.LEFT + marker_time * self.scale
            if x < viewport.left()-12 or x > viewport.right()+12:
                continue
            color = QColor(marker.get('color', '#63ead4'))
            p.setPen(QPen(color, 1, Qt.DashLine)); p.drawLine(int(x), 4, int(x), self.height())
            p.setPen(Qt.NoPen); p.setBrush(color)
            p.drawPolygon(QPolygonF([QPointF(x, 4), QPointF(x+6, 4), QPointF(x, 11)]))
            p.setPen(color); p.setFont(QFont('Sans', 8, QFont.Bold if marker.get('kind') == 'chapter' else QFont.Normal))
            text = str(marker.get('label', 'Marker'))[:24]
            p.drawText(int(x)+7, 12, text)
            p.setFont(QFont('Sans', 9))
        ghost_ids={clip.uid for clip in (self.ghost or [])}
        for c in self.clips:
            if c.uid in ghost_ids:
                continue
            self.draw_clip(p,c,False,viewport)
        for ghost in self.ghost or []:
            self.draw_clip(p,ghost,True,viewport)
        if self.marquee_active and self.marquee_start is not None and self.marquee_current is not None:
            rect = QRectF(self.marquee_start, self.marquee_current).normalized()
            p.setPen(QPen(QColor('#63ead4'), 1, Qt.DashLine)); p.setBrush(QColor(99,234,212,35)); p.drawRect(rect)
        if not self.clips:
            p.setPen(QColor('#8794a6')); p.setFont(QFont('Sans',10,QFont.Bold)); p.drawText(self.LEFT+24,self.TOP+40,'Timeline leer · Medien hierher ziehen oder mit + hinzufügen')
        if self.snapline is not None:
            p.setPen(QPen(QColor('#f8c86f'),1,Qt.DashLine))
            x=int(self.LEFT+self.snapline*self.scale); p.drawLine(x,28,x,self.height())
        p.setPen(QPen(QColor('#f2fffc'),2))
        x=int(self.LEFT+self.playhead*self.scale); p.drawLine(x,24,x,self.height())
        p.fillRect(x-4,24,8,10,QColor('#f2fffc'))

    def draw_clip(self,p,c,ghost,viewport=None):
        r=self.rect_for(c)
        if viewport is not None and not r.intersects(viewport):
            return
        selected=c.uid in self.selection
        p.setOpacity(.7 if ghost else 1)
        border = QColor('#8cebdd' if selected else '#4b7381' if c.track>0 else '#3f806e')
        fill = QColor('#4b3d20' if c.source_type=='adjustment' else '#3a2b50' if c.kind=='text' else '#1d3b48' if c.track>0 else '#1b3a32')
        p.setPen(QPen(border,2 if selected else 1))
        p.setBrush(fill)
        p.drawRoundedRect(r,7,7)
        accent = QColor('#e6bf67' if c.source_type=='adjustment' else '#c898ed' if c.kind=='text' else '#70c8e2' if c.track>0 else '#72d0ac')
        p.setPen(Qt.NoPen); p.setBrush(accent); p.drawRoundedRect(QRectF(r.left()+1,r.top()+1,r.width()-2,3),2,2)
        if selected:
            p.setBrush(QColor(116,226,208,36)); p.setPen(Qt.NoPen); p.drawRoundedRect(r.adjusted(3,4,-3,-3),5,5)
        if c.kind == 'text':
            p.setPen(QColor('#f5e8ff')); p.setFont(QFont('Sans',9,QFont.Bold)); p.drawText(int(r.left()+10),int(r.top()+23),'T  '+c.text[:24])
            p.setPen(QColor('#d8b9ef')); p.setFont(QFont('Sans',8)); p.drawText(int(r.left()+10),int(r.top()+43),f'{c.length:.2f} s  ·  Text')
        if c.kind == 'video' and c.path in self.thumbnails and r.width() > 34:
            image = self._thumbnail(c.path, r.height()-4)
            if image is not None:
                p.save(); p.setClipRect(r.adjusted(2,2,-2,-2))
                tile_w = max(28, image.width())
                x = int(r.left()+2)
                while x < r.right():
                    p.setOpacity((.45 if ghost else .72) if not selected else (.55 if ghost else .82))
                    p.drawImage(x, int(r.top()+2), image)
                    x += tile_w
                p.fillRect(r.adjusted(2,2,-2,-2), QColor(8,14,20,105 if not selected else 75))
                p.restore()
        if c.source_type == 'adjustment':
            p.save(); p.setClipRect(r.adjusted(8,2,-7,-2))
            p.setPen(QColor('#f8d27a')); p.setFont(QFont('Sans',9,QFont.Bold)); p.drawText(int(r.left()+10),int(r.top()+23),'FX  Adjustment-Layer')
            p.setPen(QColor('#d6b86a')); p.setFont(QFont('Sans',8)); p.drawText(int(r.left()+10),int(r.top()+43),f'{c.length:.2f} s  ·  Effekte')
            p.restore()
        if c.kind == 'audio' and c.path in self.waveforms and r.width() > 24:
            image = self._waveform(c, r.width()-6, r.height()-6)
            if image is not None:
                p.save(); p.setClipRect(r.adjusted(3,3,-3,-3))
                p.setOpacity(.72 if not ghost else .35)
                p.drawImage(int(r.left()+3), int(r.top()+3), image)
                p.restore()
        p.save(); p.setClipRect(r.adjusted(8,2,-7,-2))
        if c.kind != 'text' and c.source_type != 'adjustment':
            title = c.compound_name or Path(c.path).name
            if c.camera_angle:
                title = f'{title} · {c.camera_angle}'
            if r.width() > 54:
                p.setPen(QColor('#e5f4f8')); p.setFont(QFont('Sans',9,QFont.Bold)); p.drawText(int(r.left()+10),int(r.top()+23),title[:32])
            if r.width() > 82:
                detail = f'{c.length:.2f} s  ·  {c.volume:.0%}'
                if c.multicam_group and not c.multicam_active:
                    detail += '  ·  inaktiver Winkel'
                p.setPen(QColor('#aec7d1')); p.setFont(QFont('Sans',8)); p.drawText(int(r.left()+10),int(r.top()+43),detail)
        p.restore()
        if selected and r.width()>18:
            p.setOpacity(1)
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor('#b7fff4'),2)); p.drawRoundedRect(r,7,7)
            p.fillRect(QRectF(r.left()+3,r.top()+15,3,max(2,r.height()-30)),QColor('#8de7da'))
            p.fillRect(QRectF(r.right()-6,r.top()+15,3,max(2,r.height()-30)),QColor('#8de7da'))
        if c.kind == 'video' and c.keyframes and r.width() > 18:
            p.setOpacity(.95 if not ghost else .45)
            p.setPen(Qt.NoPen); p.setBrush(QColor('#f8c86f'))
            for keyframe in c.keyframes:
                x=r.left()+max(0.0,min(c.length,float(keyframe.get('time',0))))*self.scale
                y=r.top()+6
                p.drawPolygon(QPolygonF([QPointF(x,y-4),QPointF(x+4,y),QPointF(x,y+4),QPointF(x-4,y)]))
        if c.kind in ('video','audio') and c.volume_keyframes and r.width() > 18:
            p.setOpacity(.95 if not ghost else .45)
            p.setPen(Qt.NoPen); p.setBrush(QColor('#8bd9b9'))
            for keyframe in c.volume_keyframes:
                x=r.left()+max(0.0,min(c.length,float(keyframe.get('time',0))))*self.scale
                y=r.bottom()-6
                p.drawPolygon(QPolygonF([QPointF(x,y-4),QPointF(x+4,y),QPointF(x,y+4),QPointF(x-4,y)]))
        # Small state badges make effects and animation discoverable without
        # opening the Inspector. They are intentionally short and stable so
        # the timeline remains readable at compact zoom levels.
        badges=[]
        if c.source_type == 'adjustment' or getattr(c,'effect_preset','clean') != 'clean':
            badges.append(('FX','#e6bf67'))
        if getattr(c,'keyframes',None):
            badges.append(('KF','#f8c86f'))
        if getattr(c,'volume_keyframes',None):
            badges.append(('VOL','#8bd9b9'))
        if getattr(c,'transition_type','none') != 'none':
            badges.append(('TR','#c898ed'))
        if badges and r.width() > 68:
            p.save(); p.setOpacity(.96 if not ghost else .45)
            badge_x=r.right()-5
            for text,color in reversed(badges):
                width=25 if text != 'VOL' else 31
                badge_x-=width
                p.setPen(Qt.NoPen); p.setBrush(QColor(color)); p.drawRoundedRect(QRectF(badge_x,r.top()+8,width,16),4,4)
                p.setPen(QColor('#12202a')); p.setFont(QFont('Sans',7,QFont.Bold)); p.drawText(QRectF(badge_x,r.top()+8,width,16),Qt.AlignCenter,text)
                badge_x-=3
            p.restore()
        if self.track_states.get(c.track, {}).get('muted'):
            p.save(); p.setBrush(QColor(10,14,20,92)); p.setPen(QPen(QColor('#ff8f8f'),1,Qt.DashLine)); p.drawRoundedRect(r.adjusted(2,2,-2,-2),4,4); p.restore()
        p.setOpacity(1)

    def _group_ids(self, clip):
        ids = {clip.uid}
        if clip.group_id:
            ids.update(value.uid for value in self.clips if value.group_id == clip.group_id)
        if clip.compound_id:
            ids.update(value.uid for value in self.clips if value.compound_id == clip.compound_id)
        return [value.uid for value in self.clips if value.uid in ids]

    def _selection_locked(self):
        return any(self.track_locked(clip.track) for clip in self.clips if clip.uid in self.selection)

    def mousePressEvent(self,event):
        if event.button()==Qt.RightButton:
            point=event.position().toPoint()
            self._request_context_menu(point,self.mapToGlobal(point))
            event.accept()
            return
        if event.button()!=Qt.LeftButton:
            return
        self.setFocus()
        point=event.position()
        control = self.track_control_at(point)
        if control and not (event.modifiers() & Qt.ControlModifier):
            track, action = control
            (self.track_mute_requested if action == "mute" else self.track_lock_requested).emit(track)
            return
        playhead_x=self.LEFT+self.playhead*self.scale
        # The small white handle at the top is the dedicated playhead grip.
        # It takes priority over a clip underneath so the clip is not moved.
        if point.y() <= self.TOP and abs(point.x()-playhead_x) <= 10:
            self.playhead_drag=True
            self.seek.emit(self.time_at(point.x()))
            self.setCursor(Qt.SizeHorCursor)
            self.update()
            return
        marker = self.marker_at(point)
        if marker is not None:
            self.seek.emit(float(marker.get('time', 0.0)))
            self.setCursor(Qt.SizeHorCursor)
            self.update()
            return
        c=self.hit(point)
        if event.modifiers() & Qt.ControlModifier:
            if not c:
                self.pan_drag=point.x()
                self.setCursor(Qt.ClosedHandCursor)
                return
            ids=self._group_ids(c)
            selected=set(self.selection)
            if all(uid in selected for uid in ids):
                new_selection=[uid for uid in self.selection if uid not in ids]
                anchor=new_selection[-1] if new_selection else None
            else:
                new_selection=list(self.selection)
                for uid in ids:
                    if uid not in new_selection:
                        new_selection.append(uid)
                anchor=c.uid
            self.set_selection(new_selection,anchor)
            if anchor:
                self.selected.emit(anchor)
            self.selection_changed.emit(new_selection)
            return
        if c:
            # Selecting a clip must not move the playhead. The playhead is
            # moved only by the dedicated grip or by clicking empty timeline.
            ids=self._group_ids(c)
            self.set_selection(ids,c.uid)
            self.selected.emit(c.uid); self.selection_changed.emit(ids)
            if self._selection_locked():
                self.update()
                return
            r=self.rect_for(c); mode='move'
            if len(ids)==1 and abs(point.x()-r.left())<=7:
                mode='left'
            elif len(ids)==1 and abs(point.x()-r.right())<=7:
                mode='right'
            originals=[replace(value) for value in self.clips if value.uid in ids]
            self.drag=(originals,mode,point.x())
        elif point.x()>=self.LEFT:
            self.marquee_start = point
            self.marquee_current = point
            self.marquee_append = bool(event.modifiers() & Qt.ShiftModifier)
            self.marquee_active = False
            self.setCursor(Qt.CrossCursor)
        self.update()

    def mouseMoveEvent(self,event):
        point=event.position()
        if self.pan_drag is not None:
            delta=int(point.x()-self.pan_drag)
            if delta:
                self.pan_request.emit(delta); self.pan_drag=point.x()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self.marquee_start is not None:
            self.marquee_current = point
            self.marquee_active = (point-self.marquee_start).manhattanLength() >= 4
            self.setCursor(Qt.CrossCursor)
            self.update()
            return
        if self.playhead_drag:
            self.seek.emit(self.time_at(point.x()))
            self.setCursor(Qt.SizeHorCursor)
            return
        if not self.drag:
            if self.track_control_at(point):
                self.setCursor(Qt.PointingHandCursor)
                return
            c=self.hit(point)
            edge=c and min(abs(point.x()-self.rect_for(c).left()),abs(point.x()-self.rect_for(c).right()))<=7 and len(self._group_ids(c))==1
            self.setCursor(Qt.ForbiddenCursor if c and (self.track_locked(c.track) or self._selection_locked()) else Qt.SizeHorCursor if edge else Qt.OpenHandCursor if c else Qt.ArrowCursor)
            return
        originals,mode,x=self.drag
        delta=(point.x()-x)/self.scale
        self.snapline=None
        if abs(point.x()-x)<3 and self.ghost is None:
            return
        group=len(originals)>1
        if group:
            candidates=[edited_clip(original,'move',delta,original.track) for original in originals]
        else:
            original=originals[0]
            candidate=edited_clip(original,mode,delta)
            track=self.track_at(point.y())
            if mode=='move' and track is not None and (track>0)==(original.track>0):
                candidate=replace(candidate,track=track)
            candidates=[candidate]
        if self.snap and not(event.modifiers() & Qt.ShiftModifier):
            original_ids={value.uid for value in originals}
            targets=self.snap_targets(original_ids)
            tolerance=8/self.scale
            if group:
                edges=[min(value.position for value in candidates),max(value.finish for value in candidates)]
            else:
                edges=[candidates[0].position,candidates[0].finish] if mode=='move' else [candidates[0].position if mode=='left' else candidates[0].finish]
            matches=[(abs(t-e),t-e,t) for e in edges for t in targets if abs(t-e)<=tolerance]
            if matches:
                _,adjustment,target=min(matches)
                self.snapline=target
                if group:
                    candidates=[edited_clip(original,'move',delta+adjustment,original.track) for original in originals]
                else:
                    candidates=[edited_clip(original,mode,delta+adjustment,candidates[0].track)]
        self.ghost=candidates
        self.setCursor(Qt.ClosedHandCursor if mode=='move' else Qt.SizeHorCursor)
        self.update()

    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.LeftButton:
            return
        if self.pan_drag is not None:
            self.pan_drag=None
            self.setCursor(Qt.ArrowCursor)
            self.gesture_done.emit()
            return
        if self.marquee_start is not None:
            start, end = self.marquee_start, self.marquee_current or self.marquee_start
            active = self.marquee_active
            append = self.marquee_append
            self.marquee_start = None; self.marquee_current = None; self.marquee_active = False; self.marquee_append = False
            self.setCursor(Qt.ArrowCursor)
            if active:
                rect = QRectF(start, end).normalized()
                found = [clip.uid for clip in self.clips if rect.intersects(self.rect_for(clip))]
                selected = list(self.selection) if append else []
                for uid in found:
                    if uid not in selected:
                        selected.append(uid)
                self.set_selection(selected, selected[-1] if selected else None)
                self.selection_changed.emit(selected)
            else:
                self.set_selection([], None); self.selection_changed.emit([])
                self.seek.emit(self.time_at(end.x()))
            self.gesture_done.emit(); self.update(); return
        if self.playhead_drag:
            self.playhead_drag=False
            self.setCursor(Qt.ArrowCursor)
            self.gesture_done.emit()
            self.update()
            return
        changed=self.ghost
        self.drag=None; self.ghost=None; self.snapline=None
        if changed:
            self.commit.emit(changed)
        self.gesture_done.emit()
        self.update()

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Escape and self.pan_drag is not None:
            self.pan_drag=None; self.setCursor(Qt.ArrowCursor); self.update(); self.gesture_done.emit()
        elif event.key()==Qt.Key_Escape and self.playhead_drag:
            self.playhead_drag=False; self.setCursor(Qt.ArrowCursor); self.update(); self.gesture_done.emit()
        elif event.key()==Qt.Key_Escape and self.drag:
            self.drag=None; self.ghost=None; self.snapline=None
            self.update(); self.gesture_done.emit()
        elif event.key()==Qt.Key_Escape and self.marquee_start is not None:
            self.marquee_start=None; self.marquee_current=None; self.marquee_active=False; self.marquee_append=False
            self.setCursor(Qt.ArrowCursor); self.update(); self.gesture_done.emit()
        elif event.key() in (Qt.Key_Delete,Qt.Key_Backspace):
            self.delete_selected.emit()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self,event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_request.emit(1 if event.angleDelta().y()>0 else -1)
            event.accept()
        else:
            event.ignore()

    def _request_context_menu(self, point, global_pos=None):
        """Forward a right-click to the editor's contextual action menus."""
        signature = (int(point.x()), int(point.y()))
        now = monotonic()
        if (signature == self._last_context_signature
                and now-self._last_context_time < 0.35):
            return
        self._last_context_signature = signature
        self._last_context_time = now
        if global_pos is None:
            global_pos = self.mapToGlobal(point)
        if point.x() < self.LEFT and point.y() >= self.TOP:
            track=self.track_at(point.y())
            if track is not None:
                self.track_context_requested.emit(track,global_pos)
                return
        marker = self.marker_at(point)
        if marker is not None:
            self.marker_context_requested.emit(float(marker.get('time', 0.0)), global_pos)
            return
        clip=self.hit(point)
        self.context_requested.emit(clip.uid if clip else '', global_pos)

    def contextMenuEvent(self,event):
        # Keep the native event path working for callers that send a
        # QContextMenuEvent directly (including older Qt test harnesses).
        self._request_context_menu(event.pos(), event.globalPos())
        event.accept()

    def dragEnterEvent(self,event):
        if event.mimeData().hasFormat(ASSET_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self,event):
        track = self.track_at(event.position().y())
        if event.mimeData().hasFormat(ASSET_MIME) and track is not None and not self.track_locked(track):
            event.acceptProposedAction()

    def dropEvent(self,event):
        if event.mimeData().hasFormat(ASSET_MIME):
            track=self.track_at(event.position().y())
            if track is not None and not self.track_locked(track):
                index=int(bytes(event.mimeData().data(ASSET_MIME)).decode())
                position=self.time_at(event.position().x())
                if self.snap and not(event.modifiers() & Qt.ShiftModifier):
                    position=snap_time(position,self.snap_targets(),8/self.scale)
                self.add_asset.emit(index,position,track)
                event.acceptProposedAction()
