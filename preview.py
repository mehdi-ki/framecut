"""Qt video sink rendered as a regular widget, including on Wayland/offscreen."""
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QPainter,QColor,QImage
from PySide6.QtWidgets import QWidget
from PySide6.QtMultimedia import QVideoSink


class VideoView(QWidget):
    def __init__(self):
        super().__init__()
        self.sink=QVideoSink(self)
        self.frame=QImage()
        self.sink.videoFrameChanged.connect(self.receive_frame)
        self.setMinimumSize(200,120)

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
