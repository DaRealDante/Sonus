import os
import time

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QWidget

from .. import video_proxy

STALL_SECONDS = 4
FIRST_FRAME_SECONDS = 12
SEEK_GAP_SECONDS = 2


def isRemote(path):
    return str(path or "").lower().startswith(("http://", "https://"))


class VideoController(QObject):
    """One muted video player shared by the background and the "In riproduzione" page, synced to the audio."""

    frameReady = Signal()
    stateChanged = Signal()

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.mediaPlayer = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.mediaPlayer.setVideoSink(self.sink)
        self.mediaPlayer.setLoops(QMediaPlayer.Infinite)
        self.sink.videoFrameChanged.connect(self._onFrame)
        self.mediaPlayer.errorOccurred.connect(self._onError)
        self.clients = {}
        self.currentPath = None
        self.currentImage = None
        self.lastFrameTime = 0.0
        self.frameInterval = 1 / 12
        self.failed = False
        self.suspended = False
        self.loadedAt = 0.0
        self.lastSeekAt = 0.0
        self.retried = False
        self.audioWasPlaying = False
        self.syncTimer = QTimer(self)
        self.syncTimer.setInterval(200)
        self.syncTimer.timeout.connect(self.sync)

    # ---------- clients ----------
    def request(self, client, path):
        if path and (isRemote(path) or os.path.isfile(path)):
            self.clients[client] = path
        else:
            self.clients.pop(client, None)
        self._apply()

    def release(self, client):
        self.clients.pop(client, None)
        self._apply()

    def unload(self):
        self.clients.clear()
        self._apply()

    def _apply(self):
        wantedPath = next(iter(self.clients.values()), None)
        if wantedPath == self.currentPath:
            return
        self.currentPath = wantedPath
        self.currentImage = None
        self.failed = False
        self.retried = False
        self.mediaPlayer.stop()
        if wantedPath:
            self._setSource(wantedPath)
            if self.suspended:
                self.mediaPlayer.play()
                QTimer.singleShot(150, lambda: self.suspended and self.mediaPlayer.pause())
            else:
                self.syncTimer.start()
                self.sync()
        else:
            self.mediaPlayer.setSource(QUrl())
            self.syncTimer.stop()
        self.stateChanged.emit()
        self.frameReady.emit()

    def _setSource(self, path):
        self.loadedAt = time.monotonic()
        self.lastSeekAt = 0.0
        if isRemote(path):
            print("[Video] carico il video in streaming")
            self.mediaPlayer.setSource(QUrl(video_proxy.localUrl(path)))
        else:
            self.mediaPlayer.setSource(QUrl.fromLocalFile(os.path.abspath(path)))

    def _checkStall(self):
        """A streaming video that stops sending frames while the music plays: reload it once, then give up
        (the cover is shown instead of a frozen picture)."""
        now = time.monotonic()
        lastProgress = max(self.lastFrameTime, self.loadedAt)
        limit = FIRST_FRAME_SECONDS if self.currentImage is None else STALL_SECONDS
        if now - lastProgress < limit:
            return
        if not self.retried:
            print("[Video] il video si è bloccato: lo ricarico")
            self.retried = True
            self.mediaPlayer.stop()
            self._setSource(self.currentPath)
            self.mediaPlayer.play()
            return
        print("[Video] il video non va: mostro la copertina")
        self.failed = True
        self.mediaPlayer.stop()
        self.stateChanged.emit()
        self.frameReady.emit()

    def setSuspended(self, suspended):
        """Freezes the video (last frame stays) to free the CPU, e.g. while you play a game."""
        if suspended == self.suspended:
            return
        self.suspended = suspended
        if suspended:
            self.syncTimer.stop()
            if self.mediaPlayer.playbackState() == QMediaPlayer.PlayingState:
                self.mediaPlayer.pause()
        elif self.currentPath:
            self.loadedAt = time.monotonic()
            self.syncTimer.start()
            self.sync()

    def hasFrames(self):
        return self.currentPath is not None and self.currentImage is not None and not self.failed

    def setFrameRate(self, framesPerSecond):
        # A little under the frame time, so 30 fps from a 30 fps video does not drop every other frame
        self.frameInterval = 0.9 / max(5, framesPerSecond)

    # ---------- sync with audio ----------
    def sync(self):
        if not self.currentPath or self.suspended or self.failed:
            return
        audioPlaying = self.player.isPlaying()
        now = time.monotonic()
        if audioPlaying and not self.audioWasPlaying:
            self.loadedAt = now
        self.audioWasPlaying = audioPlaying
        videoState = self.mediaPlayer.playbackState()
        duration = self.mediaPlayer.duration()
        target = self.player.position()
        if duration > 0:
            target = target % duration
        if abs(self.mediaPlayer.playbackRate() - self.player.playbackRate()) > 0.01:
            self.mediaPlayer.setPlaybackRate(self.player.playbackRate())
        drift = abs(self.mediaPlayer.position() - target)
        if duration > 0:
            drift = min(drift, duration - drift)
        if drift > 300 and now - self.lastSeekAt > SEEK_GAP_SECONDS:
            # Not more often than this: every jump makes a streaming video load again, and it froze
            self.lastSeekAt = now
            self.loadedAt = max(self.loadedAt, now)
            self.mediaPlayer.setPosition(target)
        if audioPlaying:
            self._checkStall()
            if self.failed:
                return
        if audioPlaying and videoState != QMediaPlayer.PlayingState:
            self.mediaPlayer.play()
        elif not audioPlaying and videoState == QMediaPlayer.PlayingState:
            self.mediaPlayer.pause()
        elif not audioPlaying and videoState == QMediaPlayer.StoppedState and self.currentImage is None:
            self.mediaPlayer.play()
            QTimer.singleShot(120, lambda: not self.player.isPlaying() and self.mediaPlayer.pause())

    # ---------- frames ----------
    def _onFrame(self, frame):
        now = time.monotonic()
        if now - self.lastFrameTime < self.frameInterval and self.currentImage is not None:
            return
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        self.lastFrameTime = now
        hadFrames = self.currentImage is not None
        self.currentImage = image
        self.frameReady.emit()
        if not hadFrames:
            self.stateChanged.emit()

    def _onError(self, error, message):
        if error != QMediaPlayer.NoError:
            print(f"[Video] errore del video: {message}")
            self.failed = True
            self.stateChanged.emit()
            self.frameReady.emit()


def drawCover(painter, rect, image, fit=False):
    """Draws image filling rect (crop) or fitting inside it (letterbox)."""
    if image is None or image.isNull():
        return
    imageRatio = image.width() / max(1, image.height())
    rectRatio = rect.width() / max(1, rect.height())
    if fit:
        if imageRatio > rectRatio:
            width = rect.width()
            height = width / imageRatio
        else:
            height = rect.height()
            width = height * imageRatio
        target = QRectF(rect.x() + (rect.width() - width) / 2, rect.y() + (rect.height() - height) / 2, width, height)
        painter.drawImage(target, image)
        return
    if imageRatio > rectRatio:
        sourceWidth = image.height() * rectRatio
        source = QRectF((image.width() - sourceWidth) / 2, 0, sourceWidth, image.height())
    else:
        sourceHeight = image.width() / rectRatio
        source = QRectF(0, (image.height() - sourceHeight) / 2, image.width(), sourceHeight)
    painter.drawImage(QRectF(rect), image, source)


_coverCache = {}


def coverImage(path, blurred=False):
    """The song's cover as an image (blurred = made soft, for a full-window background)."""
    if not path or not os.path.isfile(path):
        return None
    key = (path, blurred)
    if key not in _coverCache:
        image = QImage(path)
        if image.isNull():
            return None
        if blurred:
            image = image.scaled(48, 48, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        if len(_coverCache) > 20:
            _coverCache.clear()
        _coverCache[key] = image
    return _coverCache[key]


def videoImage(controller):
    """The current video frame, or None when there is no (working) video."""
    if controller.failed or controller.currentPath is None:
        return None
    return controller.currentImage


class FrameView(QWidget):
    """Shows the controller's current frame, letterboxed on black; the song's cover while there is no video."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.coverPath = None
        controller.frameReady.connect(self._onFrame)

    def setCover(self, coverPath):
        self.coverPath = coverPath
        self.update()

    def _onFrame(self):
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000"))
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        image = videoImage(self.controller)
        if image is None:
            margin = min(self.width(), self.height()) // 10
            drawCover(painter, self.rect().adjusted(margin, margin, -margin, -margin), coverImage(self.coverPath), fit=True)
        else:
            drawCover(painter, self.rect(), image, fit=True)
        painter.end()


class BackdropWidget(QWidget):
    """Central widget of the main window: paints the video behind the (transparent) UI."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.active = False
        self.uiVisible = True
        self.coverPath = None
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        controller.frameReady.connect(self._onFrame)

    def setCover(self, coverPath):
        if coverPath != self.coverPath:
            self.coverPath = coverPath
            self.update()

    def setActive(self, active, uiVisible):
        changed = active != self.active or uiVisible != self.uiVisible
        self.active = active
        self.uiVisible = uiVisible
        if changed:
            self.update()

    def _onFrame(self):
        if self.active:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000"))
        image = videoImage(self.controller) if self.active else None
        if self.active and image is None:
            # No video: the song's cover, soft and darker, instead
            image = coverImage(self.coverPath, blurred=True)
            if image is not None:
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                drawCover(painter, self.rect(), image)
                painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
                image = None
        if image is not None:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, not self.uiVisible)
            drawCover(painter, self.rect(), image)
            if self.uiVisible:
                painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        painter.end()
