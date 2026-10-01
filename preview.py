"""Qt video sink rendered as a regular widget, including on Wayland/offscreen."""
from PySide6.QtCore import Qt,QRectF,Signal,QPointF
from PySide6.QtGui import QPainter,QColor,QImage,QPen
from PySide6.QtWidgets import QWidget
from PySide6.QtMultimedia import QVideoSink


class VideoView(QWidget):
    transform_committed=Signal(float,float)
    transform_started=Signal()
    def __init__(self):
        super().__init__()
        self.sink=QVideoSink(self)
        self.frame=QImage()
        self.sink.videoFrameChanged.connect(self.receive_frame)
        self.setMinimumSize(200,120)
        self.setFocusPolicy(Qt.StrongFocus); self.setMouseTracking(True)
        self.edit_geometry=None; self.transform_drag=None; self.drag_geometry=None

    def frame_rect(self):
        if self.frame.isNull(): return QRectF(self.rect())
        size=self.frame.size().scaled(self.size(),Qt.KeepAspectRatio)
        return QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())

    def set_edit_geometry(self,geometry):
        self.edit_geometry=geometry; self.update()

    def object_rect(self,geometry=None):
        g=geometry or self.drag_geometry or self.edit_geometry
        canvas=self.frame_rect()
        if not g: return QRectF()
        width=canvas.width()*g['width']; height=canvas.height()*g['height']
        return QRectF(canvas.left()+(canvas.width()-width)*g['x'],
                      canvas.top()+(canvas.height()-height)*g['y'],width,height)

    def cancel_transform(self):
        self.transform_drag=None; self.drag_geometry=None; self.setCursor(Qt.ArrowCursor); self.update()

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.edit_geometry and self.object_rect().contains(event.position()):
            self.setFocus(); self.transform_started.emit()
            self.transform_drag=(event.position(),dict(self.edit_geometry)); self.drag_geometry=dict(self.edit_geometry)
            self.setCursor(Qt.ClosedHandCursor); event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if not self.transform_drag:
            self.setCursor(Qt.OpenHandCursor if self.edit_geometry and self.object_rect().contains(event.position()) else Qt.ArrowCursor)
            return
        origin,g=self.transform_drag; canvas=self.frame_rect(); delta=event.position()-origin
        candidate=dict(g)
        for field,extent,movement,ratio in (('x',canvas.width(),delta.x(),g['width']),('y',canvas.height(),delta.y(),g['height'])):
            available=extent*(1-ratio)
            value=g[field] if abs(available)<1 else max(0,min(1,g[field]+movement/available))
            if not event.modifiers() & Qt.ShiftModifier and abs(available)>=1:
                margin=.05*extent/available
                targets=[0,.5,1,margin,1-margin]
                matches=[v for v in targets if 0<=v<=1 and abs(v-value)*abs(available)<=7]
                if matches: value=min(matches,key=lambda v:abs(v-value))
            candidate[field]=value
        self.drag_geometry=candidate; self.update()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.transform_drag:
            original=self.transform_drag[1]; result=self.drag_geometry
            self.cancel_transform()
            if result and (abs(result['x']-original['x'])>1e-7 or abs(result['y']-original['y'])>1e-7):
                self.transform_committed.emit(result['x'],result['y'])
            event.accept(); return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Escape: self.cancel_transform(); event.accept(); return
        super().keyPressEvent(event)

    def videoSink(self):
        return self.sink

    def receive_frame(self,frame):
        if frame.isValid():
            self.frame=frame.toImage()
            self.update()

    def paintEvent(self,event):
        p=QPainter(self)
        p.fillRect(self.rect(),QColor('#090b10'))
        if not self.frame.isNull():
            size=self.frame.size().scaled(self.size(),Qt.KeepAspectRatio)
            target=QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(target,self.frame)
        if self.edit_geometry and not self.frame.isNull():
            canvas=self.frame_rect(); rect=self.object_rect()
            p.setPen(QPen(QColor('#83f3d4'),1.5)); p.setBrush(Qt.NoBrush); p.drawRect(rect)
            for corner in (rect.topLeft(),rect.topRight(),rect.bottomLeft(),rect.bottomRight()):
                p.fillRect(QRectF(corner.x()-3,corner.y()-3,6,6),QColor('#83f3d4'))
            if self.transform_drag:
                p.setPen(QPen(QColor('#e8ca8a'),1,Qt.DashLine))
                p.drawLine(QPointF(canvas.center().x(),canvas.top()),QPointF(canvas.center().x(),canvas.bottom()))
                p.drawLine(QPointF(canvas.left(),canvas.center().y()),QPointF(canvas.right(),canvas.center().y()))
                p.drawRect(canvas.adjusted(canvas.width()*.05,canvas.height()*.05,-canvas.width()*.05,-canvas.height()*.05))
                p.setPen(QColor('#e9f0f5')); p.drawText(12,22,'Ausrichten · Shift ohne Einrasten · Esc abbrechen')
