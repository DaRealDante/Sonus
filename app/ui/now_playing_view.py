import bisect
import os
import time

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QStackedLayout,
    QVBoxLayout, QWidget,
)

from ..config import APP_NAME, settings
from ..lyrics import parseSynced
from . import theme
from .player_bar import ClickSlider
from .video_controller import FrameView
from .effects import ColorFader, Visualizer
from .views import ElidedLabel, Page, _iconButton, _label


class GradientWidget(QWidget):
    """Background of "In riproduzione": vertical gradient from the cover colour (painted, so it can animate cheaply)."""

    def __init__(self):
        super().__init__()
        self.color = QColor("#3A3A3A")

    def setColor(self, color):
        self.color = QColor(color) if color is not None else QColor("#3A3A3A")
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QLinearGradient, QPainterPath
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, self.color)
        gradient.setColorAt(1, self.color.darker(260))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        painter.fillPath(path, gradient)
        painter.end()

MODE_LYRICS, MODE_VIDEO, MODE_BOTH = "lyrics", "video", "both"


def dominantColor(coverPath, fallback="#3A3A3A"):
    image = QImage(coverPath) if coverPath else QImage()
    if image.isNull():
        return QColor(fallback)
    small = image.scaled(24, 24, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    red = green = blue = count = 0
    for x in range(small.width()):
        for y in range(small.height()):
            color = small.pixelColor(x, y)
            saturation = color.hsvSaturationF()
            weight = 0.3 + saturation
            red += color.red() * weight
            green += color.green() * weight
            blue += color.blue() * weight
            count += weight
    color = QColor(int(red / count), int(green / count), int(blue / count))
    hue, saturation, value, _ = color.getHsvF()
    return QColor.fromHsvF(max(0.0, hue), min(1.0, saturation * 1.1), min(0.55, max(0.28, value)))


class LyricsView(QWidget):
    seekRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lines = []
        self.times = []
        self.synced = False
        self.message = ""
        self.currentIndex = -1
        self.layoutCache = []
        self.totalHeight = 0
        self.scrollOffset = 0.0
        self.targetOffset = 0.0
        self.manualUntil = 0.0
        self.hoverIndex = -1
        self.compact = False
        self.animationTimer = QTimer(self)
        self.animationTimer.setInterval(16)
        self.animationTimer.timeout.connect(self._animate)
        self.searchButton = QPushButton("Cerca il testo", self)
        self.searchButton.setObjectName("accent")
        self.searchButton.setIcon(theme.icon("search", "#000", 16))
        self.searchButton.hide()

    def setCompact(self, compact):
        self.compact = compact
        self._relayout()

    def setLyrics(self, plain, synced):
        parsed = parseSynced(synced) if synced else []
        parsed = [(stamp, text) for stamp, text in parsed]
        if parsed:
            self.synced = True
            self.times = [stamp for stamp, _ in parsed]
            self.lines = [text or "♪" for _, text in parsed]
        elif plain:
            self.synced = False
            self.times = []
            self.lines = plain.splitlines() or [plain]
        else:
            self.synced = False
            self.times = []
            self.lines = []
        self.message = ""
        self.searchButton.hide()
        self.currentIndex = -1
        self.scrollOffset = 0.0
        self.targetOffset = 0.0
        self._relayout()

    def setMessage(self, text, showSearch=False):
        self.lines = []
        self.times = []
        self.message = text
        self.searchButton.setVisible(showSearch)
        self._relayout()

    def _font(self):
        font = QFont(self.font())
        font.setPointSizeF(15 if self.compact else 21)
        font.setWeight(QFont.Bold)
        return font

    def _relayout(self):
        metrics = QFontMetrics(self._font())
        width = max(100, self.width() - 64)
        self.layoutCache = []
        y = self.height() * 0.35 if self.synced else 24
        spacing = 10 if self.compact else 16
        for line in self.lines:
            text = line if line.strip() else " "
            rect = metrics.boundingRect(0, 0, width, 10000, Qt.TextWordWrap | Qt.AlignLeft, text)
            height = max(metrics.height(), rect.height())
            self.layoutCache.append((y, height))
            y += height + spacing
        self.totalHeight = y + (self.height() * 0.5 if self.synced else 24)
        self._updateTarget(immediate=True)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.searchButton.adjustSize()
        self.searchButton.move((self.width() - self.searchButton.width()) // 2, self.height() // 2 + 40)
        self._relayout()

    def setPosition(self, positionMs):
        if not self.synced or not self.times:
            return
        index = bisect.bisect_right(self.times, positionMs + 150) - 1
        if index != self.currentIndex:
            self.currentIndex = index
            self._updateTarget()
            self.update()

    def _updateTarget(self, immediate=False):
        if self.synced and 0 <= self.currentIndex < len(self.layoutCache) and time.time() > self.manualUntil:
            lineY, lineHeight = self.layoutCache[self.currentIndex]
            self.targetOffset = max(0.0, lineY + lineHeight / 2 - self.height() * 0.38)
        elif self.synced and self.currentIndex < 0 and time.time() > self.manualUntil:
            self.targetOffset = 0.0
        if immediate:
            self.scrollOffset = self.targetOffset
        elif not self.animationTimer.isActive():
            self.animationTimer.start()

    def _animate(self):
        difference = self.targetOffset - self.scrollOffset
        if abs(difference) < 0.5:
            self.scrollOffset = self.targetOffset
            self.animationTimer.stop()
        else:
            self.scrollOffset += difference * 0.14
        self.update()

    def wheelEvent(self, event):
        maxOffset = max(0.0, self.totalHeight - self.height())
        self.targetOffset = max(0.0, min(maxOffset, self.targetOffset - event.angleDelta().y() * 0.8))
        self.manualUntil = time.time() + 3.5
        if not self.animationTimer.isActive():
            self.animationTimer.start()

    def _indexAt(self, yPosition):
        contentY = yPosition + self.scrollOffset
        for index, (lineY, lineHeight) in enumerate(self.layoutCache):
            if lineY - 6 <= contentY <= lineY + lineHeight + 6:
                return index
        return -1

    def mouseMoveEvent(self, event):
        index = self._indexAt(event.position().y()) if self.synced else -1
        if index != self.hoverIndex:
            self.hoverIndex = index
            self.setCursor(Qt.PointingHandCursor if index >= 0 else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self.hoverIndex = -1
        self.update()

    def mouseReleaseEvent(self, event):
        if self.synced and event.button() == Qt.LeftButton:
            index = self._indexAt(event.position().y())
            if index >= 0:
                self.manualUntil = 0
                self.seekRequested.emit(self.times[index])

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        if not self.lines:
            painter.setPen(QColor(255, 255, 255, 170))
            font = QFont(self.font())
            font.setPointSizeF(13)
            painter.setFont(font)
            painter.drawText(self.rect().adjusted(24, 0, -24, 0), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            return
        painter.setFont(self._font())
        width = max(100, self.width() - 64)
        for index, (line, (lineY, lineHeight)) in enumerate(zip(self.lines, self.layoutCache)):
            top = lineY - self.scrollOffset
            if top + lineHeight < 0 or top > self.height():
                continue
            if not self.synced:
                color = QColor(255, 255, 255, 235)
            elif index == self.currentIndex:
                color = QColor(255, 255, 255)
            elif index < self.currentIndex:
                color = QColor(255, 255, 255, 150)
            else:
                color = QColor(0, 0, 0, 150) if index != self.hoverIndex else QColor(255, 255, 255, 200)
            if self.synced and index == self.hoverIndex and index != self.currentIndex:
                color = QColor(255, 255, 255, 210)
            painter.setPen(color)
            painter.drawText(QRectF(32, top, width, lineHeight + 4), Qt.TextWordWrap | Qt.AlignLeft, line)


class VideoPane(QWidget):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.controller = view.window.videoController
        self.setObjectName("videoPane")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#videoPane { background: #000; border-radius: 10px; }")
        self.stack = QStackedLayout(self)
        self.frameView = FrameView(self.controller)
        self.stack.addWidget(self.frameView)
        emptyWidget = QWidget()
        emptyLayout = QVBoxLayout(emptyWidget)
        emptyLayout.addStretch()
        self.emptyLabel = _label("Nessun video per questa canzone", "h3")
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        emptyLayout.addWidget(self.emptyLabel)
        buttonsRow = QHBoxLayout()
        buttonsRow.addStretch()
        searchButton = QPushButton("Cerca video su YouTube")
        searchButton.setObjectName("accent")
        searchButton.clicked.connect(lambda: self.view.window.openVideoSearch(self.view.song))
        fileButton = QPushButton("Scegli file video")
        fileButton.clicked.connect(lambda: self.view.window.chooseVideoFile(self.view.song))
        buttonsRow.addWidget(searchButton)
        buttonsRow.addWidget(fileButton)
        buttonsRow.addStretch()
        emptyLayout.addLayout(buttonsRow)
        emptyLayout.addStretch()
        self.stack.addWidget(emptyWidget)
        self.currentPath = None
        self.controller.stateChanged.connect(self._onControllerState)

    def setVideo(self, path):
        if path and (str(path).startswith(("http://", "https://")) or os.path.isfile(path)):
            self.currentPath = path
            self.controller.request("pane", path)
            self.stack.setCurrentIndex(0)
        else:
            self.showEmpty("Nessun video per questa canzone" if not path else "File video non trovato")

    def _onControllerState(self):
        if self.currentPath and self.controller.failed and self.controller.currentPath == self.currentPath:
            self.showEmpty("Video non riproducibile")

    def showEmpty(self, text):
        self.release()
        self.emptyLabel.setText(text)
        self.stack.setCurrentIndex(1)

    def release(self):
        self.currentPath = None
        self.controller.release("pane")

    def hasVideo(self):
        return self.currentPath is not None

    def sync(self, player):
        self.controller.sync()


class FullscreenHost(QWidget):
    def __init__(self, view):
        super().__init__(None, Qt.Window)
        self.view = view
        self.setWindowTitle(APP_NAME)
        self.setObjectName("fullscreenHost")
        self.setStyleSheet("QWidget#fullscreenHost { background: #000; }")
        self.setMouseTracking(True)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.controls = QFrame(self)
        self.controls.setObjectName("fullscreenControls")
        self.controls.setStyleSheet("QFrame#fullscreenControls { background: rgba(20,20,20,215); border-radius: 12px; }")
        controlsLayout = QHBoxLayout(self.controls)
        controlsLayout.setContentsMargins(14, 8, 14, 8)
        player = view.window.player
        previousButton = _iconButton("prev", "Precedente", 36, 18, theme.TEXT)
        previousButton.clicked.connect(player.previous)
        self.playButton = _iconButton("play", "Play / pausa", 40, 22, theme.TEXT)
        self.playButton.clicked.connect(player.togglePlay)
        nextButton = _iconButton("next", "Successiva", 36, 18, theme.TEXT)
        nextButton.clicked.connect(lambda: player.next())
        self.positionLabel = _label("0:00", "small")
        self.slider = ClickSlider()
        self.slider.sliderReleased.connect(lambda: player.seek(self.slider.value()))
        self.durationLabel = _label("0:00", "small")
        self.titleLabel = _label("", "songTitle")
        exitButton = _iconButton("close", "Esci da schermo intero (Esc)", 36, 18, theme.TEXT)
        exitButton.clicked.connect(view.toggleFullscreen)
        for widget in (previousButton, self.playButton, nextButton, self.positionLabel):
            controlsLayout.addWidget(widget)
        controlsLayout.addWidget(self.slider, 1)
        controlsLayout.addWidget(self.durationLabel)
        controlsLayout.addSpacing(10)
        controlsLayout.addWidget(self.titleLabel)
        controlsLayout.addWidget(exitButton)
        self.hideTimer = QTimer(self)
        self.hideTimer.setSingleShot(True)
        self.hideTimer.timeout.connect(self._hideControls)
        player.positionChanged.connect(self._onPosition)
        player.durationChanged.connect(lambda duration: (self.slider.setRange(0, duration), self.durationLabel.setText(theme.formatTime(duration))))
        player.playingChanged.connect(lambda playing: self._updatePlayIcon())
        player.loadingChanged.connect(lambda loading: self._updatePlayIcon())
        player.songChanged.connect(lambda song: self.titleLabel.setText(f"{song.get('title')} · {song.get('artist') or ''}" if song else ""))

    def _updatePlayIcon(self):
        player = self.view.window.player
        willPlay = player.isPlaying() or (player.loading and player.loadAutoplay)
        self.playButton.setIcon(theme.icon("pause" if willPlay else "play", theme.TEXT, 22))

    def _onPosition(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
            self.positionLabel.setText(theme.formatTime(position))

    def prepare(self):
        player = self.view.window.player
        self.slider.setRange(0, player.duration())
        self.durationLabel.setText(theme.formatTime(player.duration()))
        self._updatePlayIcon()
        song = player.currentSong()
        self.titleLabel.setText(f"{song.get('title')} · {song.get('artist') or ''}" if song else "")
        QApplication.instance().installEventFilter(self)
        self._showControls()

    def finish(self):
        QApplication.instance().removeEventFilter(self)
        self.hideTimer.stop()
        self.setCursor(Qt.ArrowCursor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = min(1000, self.width() - 80)
        self.controls.setGeometry((self.width() - width) // 2, self.height() - 86, width, 60)

    def _showControls(self):
        self.controls.show()
        self.controls.raise_()
        self.unsetCursor()
        self.hideTimer.start(2500)

    def _hideControls(self):
        if not self.controls.underMouse():
            self.controls.hide()
            self.setCursor(Qt.BlankCursor)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseMove and self.isVisible():
            self._showControls()
        elif event.type() == QEvent.KeyPress and self.isVisible() and self.isActiveWindow():
            if event.key() in (Qt.Key_Escape, Qt.Key_F11, Qt.Key_F):
                self.view.toggleFullscreen()
                return True
            if event.key() == Qt.Key_Space:
                self.view.window.player.togglePlay()
                return True
            if event.key() == Qt.Key_Right:
                self.view.window.player.seekRelative(5000)
                return True
            if event.key() == Qt.Key_Left:
                self.view.window.player.seekRelative(-5000)
                return True
        elif event.type() == QEvent.MouseButtonDblClick and self.isVisible() and isinstance(obj, QWidget) and QWidget.window(obj) is self:
            self.view.toggleFullscreen()
            return True
        return False

    def closeEvent(self, event):
        event.ignore()
        self.view.toggleFullscreen()


class NowPlayingView(Page):
    def __init__(self, window):
        super().__init__(window)
        self.song = None
        savedMode = settings.get("nowPlayingMode")
        self.mode = savedMode if savedMode in (MODE_LYRICS, MODE_VIDEO, MODE_BOTH) else MODE_LYRICS
        self.fullscreenHost = None
        self.backgroundColor = QColor("#3A3A3A")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content = GradientWidget()
        self.content.setObjectName("nowContent")
        outer.addWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(24, 16, 24, 18)
        layout.setSpacing(12)

        topBar = QHBoxLayout()
        topBar.setSpacing(6)
        self.modeGroup = QButtonGroup(self)
        self.modeButtons = {}
        for key, text in ((MODE_LYRICS, "Testo"), (MODE_VIDEO, "Video"), (MODE_BOTH, "Video + Testo")):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton { background: rgba(0,0,0,0.35); border-radius: 15px; padding: 6px 16px; }"
                "QPushButton:checked { background: #FFFFFF; color: #000; }"
            )
            button.clicked.connect(lambda checked=False, k=key: self.setMode(k))
            button.setMinimumWidth(button.sizeHint().width() + 8)
            self.modeGroup.addButton(button)
            self.modeButtons[key] = button
            topBar.addWidget(button)
        topBar.addStretch()
        self.videoMenuButton = QPushButton("")
        self.videoMenuButton.setIcon(theme.icon("picture", theme.TEXT, 18))
        self.videoMenuButton.setToolTip("Opzioni video: cerca, scegli file, rimuovi")
        self.videoMenuButton.clicked.connect(self._videoMenu)
        self.lyricsMenuButton = QPushButton("")
        self.lyricsMenuButton.setIcon(theme.icon("mic", theme.TEXT, 18))
        self.lyricsMenuButton.setToolTip("Opzioni testo: cerca, scrivi, rimuovi")
        self.lyricsMenuButton.clicked.connect(self._lyricsMenu)
        self.fullscreenButton = QPushButton("")
        self.fullscreenButton.setIcon(theme.icon("panel", theme.TEXT, 18))
        self.fullscreenButton.setToolTip("Schermo intero (F11)")
        self.fullscreenButton.clicked.connect(self.toggleFullscreen)
        for button in (self.videoMenuButton, self.lyricsMenuButton, self.fullscreenButton):
            button.setFixedSize(38, 32)
            button.setStyleSheet("QPushButton { background: rgba(0,0,0,0.35); padding: 0; border-radius: 16px; }"
                                 " QPushButton:hover { background: rgba(0,0,0,0.6); }")
            topBar.addWidget(button)
        layout.addLayout(topBar)

        body = QHBoxLayout()
        body.setSpacing(24)
        self.coverPane = QWidget()
        coverLayout = QVBoxLayout(self.coverPane)
        coverLayout.setContentsMargins(0, 0, 0, 0)
        coverLayout.setSpacing(8)
        coverLayout.addStretch()
        self.coverLabel = QLabel()
        self.coverLabel.setAlignment(Qt.AlignCenter)
        coverLayout.addWidget(self.coverLabel, 0, Qt.AlignHCenter)
        self.titleLabel = ElidedLabel("", "h1")
        self.artistLabel = ElidedLabel("", "sub")
        self.artistLabel.setStyleSheet("color: rgba(255,255,255,0.75); font-size: 12pt;")
        coverLayout.addWidget(self.titleLabel)
        coverLayout.addWidget(self.artistLabel)
        coverLayout.addStretch()
        self.videoPane = VideoPane(self)
        self.lyricsView = LyricsView()
        self.lyricsView.seekRequested.connect(self.window.player.seek)
        self.lyricsView.searchButton.clicked.connect(lambda: self.window.searchLyricsManually(self.song))
        body.addWidget(self.coverPane, 4)
        body.addWidget(self.videoPane, 6)
        body.addWidget(self.lyricsView, 5)
        layout.addLayout(body, 1)
        self.visualizer = Visualizer(self.window.player, bars=32)
        self.visualizer.setFixedHeight(54)
        self.visualizer.setColor(QColor(255, 255, 255, 200))
        self.visualizer.setVisible(bool(settings.get("fxVisualizer")))
        layout.addWidget(self.visualizer)
        self.window.player.playingChanged.connect(lambda playing: self.visualizer.refreshRunning())
        self.backgroundFader = ColorFader(self.content.setColor, self)

        self.syncTimer = QTimer(self)
        self.syncTimer.setInterval(200)
        self.syncTimer.timeout.connect(lambda: self.videoPane.sync(self.window.player))

        player = self.window.player
        player.songChanged.connect(self._onSongChanged)
        player.positionChanged.connect(self.lyricsView.setPosition)
        self._applyMode()

    # ---------- state ----------
    def isActive(self):
        return self.isVisible() or (self.fullscreenHost is not None and self.fullscreenHost.isVisible())

    def refresh(self):
        current = self.window.player.currentSong()
        self.setSong(current, force=True)

    def _onSongChanged(self, song):
        if self.isActive():
            self.setSong(song)
        else:
            self.song = None

    def setSong(self, song, force=False):
        fresh = self.window.database.getSong(song["id"]) if song and song.get("id") else song
        if not force and self.song and fresh and self.song.get("id") == fresh.get("id") and \
                self.song.get("lyrics") == fresh.get("lyrics") and self.song.get("videoPath") == fresh.get("videoPath"):
            return
        self.song = fresh
        if not fresh:
            self.titleLabel.setText("Nessuna canzone")
            self.artistLabel.setText("")
            self.coverLabel.setPixmap(theme.placeholderCover(320))
            self.lyricsView.setMessage("Avvia una canzone")
            self.videoPane.showEmpty("Nessuna canzone")
            self._setBackground(None)
            return
        self.titleLabel.setText(fresh.get("title") or "")
        self.artistLabel.setText(fresh.get("artist") or "Artista sconosciuto")
        self._updateCover()
        self._setBackground(fresh.get("cover"))
        self._loadLyrics()
        self._loadVideo()

    def songDataChanged(self, songId):
        if self.song and self.song.get("id") == songId and self.isActive():
            self.setSong(self.window.player.currentSong() or self.song, force=True)

    def _updateCover(self):
        if not self.song:
            return
        size = max(160, min(420, self.coverPane.width() - 20, self.height() - 260))
        self.coverLabel.setPixmap(theme.coverPixmap(self.song.get("cover"), size, self.song.get("id") or 0, 8))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._updateCover)

    def _setBackground(self, coverPath):
        self.backgroundColor = dominantColor(coverPath)
        if settings.get("fxCoverColors"):
            self.backgroundFader.fadeTo(self.backgroundColor)
        else:
            self.backgroundFader.current = None
            self.content.setColor(self.backgroundColor)

    def applyEffectSettings(self):
        self.visualizer.setVisible(bool(settings.get("fxVisualizer")))
        self.visualizer.refreshRunning()

    def _loadLyrics(self):
        song = self.song
        if song.get("syncedLyrics") or song.get("lyrics"):
            self.lyricsView.setLyrics(song.get("lyrics"), song.get("syncedLyrics"))
            self.lyricsView.setPosition(self.window.player.position())
            return
        if self.window.lyricsPending(song["id"]):
            self.lyricsView.setMessage("Cerco il testo...")
        elif song["id"] in self.window.lyricsRetries:
            self.lyricsView.setMessage("Servizio testi momentaneamente non disponibile, riprovo da solo tra poco.", showSearch=True)
        elif not song.get("lyricsAuto", 1):
            self.lyricsView.setMessage("Testo automatico disattivato per questa canzone.", showSearch=True)
        elif song.get("lyricsChecked"):
            self.lyricsView.setMessage("Testo non trovato in automatico.", showSearch=True)
        else:
            self.lyricsView.setMessage("Cerco il testo...")
            self.window.ensureLyrics(song)

    def _loadVideo(self):
        if self.mode == MODE_LYRICS or not self.isActive():
            self.videoPane.release()
            return
        song = self.song
        if not song:
            return
        if self.window.videoPending(song["id"]):
            self.videoPane.showEmpty("Download del video in corso...")
            return
        source = self.window.videoSourceFor(song)
        if source:
            self.videoPane.setVideo(source)
        elif self.window.videoStreamLoading(song):
            self.videoPane.showEmpty("Carico il video in streaming...")
        else:
            self.videoPane.setVideo(song.get("videoPath"))
        self.videoPane.sync(self.window.player)

    # ---------- modes ----------
    def setMode(self, mode):
        self.mode = mode
        settings.set("nowPlayingMode", mode)
        self._applyMode()
        self._loadVideo()

    def _applyMode(self):
        self.modeButtons[self.mode].setChecked(True)
        self._updateLyricsIndicator()
        self.coverPane.setVisible(self.mode == MODE_LYRICS)
        self.videoPane.setVisible(self.mode in (MODE_VIDEO, MODE_BOTH))
        self.lyricsView.setVisible(self.mode in (MODE_LYRICS, MODE_BOTH))
        self.lyricsView.setCompact(self.mode == MODE_BOTH)
        if self.mode == MODE_LYRICS:
            self.videoPane.release()
            self.syncTimer.stop()
        else:
            self.syncTimer.start()

    def _updateLyricsIndicator(self):
        playerBar = getattr(self.window, "playerBar", None)
        if playerBar is not None:
            playerBar.setLyricsActive(self.isVisible() and self.mode in (MODE_LYRICS, MODE_BOTH))

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.refresh)
        QTimer.singleShot(0, self._updateLyricsIndicator)

    def hideEvent(self, event):
        super().hideEvent(event)
        QTimer.singleShot(0, self._updateLyricsIndicator)
        if self.fullscreenHost is None or not self.fullscreenHost.isVisible():
            self.videoPane.release()
            self.syncTimer.stop()

    # ---------- menus ----------
    def _videoMenu(self):
        song = self.song
        menu = QMenu(self)
        enabled = song is not None
        menu.addAction(theme.icon("search"), "Cerca un video su YouTube...", lambda: self.window.openVideoSearch(song)).setEnabled(enabled)
        menu.addAction(theme.icon("folder"), "Scegli un file video...", lambda: self.window.chooseVideoFile(song)).setEnabled(enabled)
        if song and song.get("url"):
            menu.addAction(theme.icon("refresh"), "Usa il video originale della canzone", lambda: self.window.downloadOriginalVideo(song))
        if song and song.get("videoPath"):
            menu.addAction(theme.icon("folder"), "Mostra il file video", lambda: self.window.revealPath(song["videoPath"]))
            menu.addAction(theme.icon("delete"), "Rimuovi il video", lambda: self.window.removeVideo(song))
        menu.addSeparator()
        autoAction = menu.addAction("Scarica il video in automatico per questa canzone")
        autoAction.setCheckable(True)
        autoAction.setChecked(bool(song.get("videoAuto", 1)) if song else False)
        autoAction.setEnabled(enabled)
        autoAction.toggled.connect(lambda checked: self.window.setSongAuto(song, "videoAuto", checked))
        menu.exec(self.videoMenuButton.mapToGlobal(self.videoMenuButton.rect().bottomLeft()))

    def _lyricsMenu(self):
        song = self.song
        menu = QMenu(self)
        enabled = song is not None
        menu.addAction(theme.icon("refresh"), "Cerca di nuovo il testo", lambda: self.window.ensureLyrics(song, force=True)).setEnabled(enabled)
        menu.addAction(theme.icon("search"), "Cerca il testo...", lambda: self.window.searchLyricsManually(song)).setEnabled(enabled)
        menu.addAction(theme.icon("edit"), "Scrivi / incolla il testo...", lambda: self.window.editLyrics(song)).setEnabled(enabled)
        if song and (song.get("lyrics") or song.get("syncedLyrics")):
            menu.addAction(theme.icon("delete"), "Rimuovi il testo", lambda: self.window.removeLyrics(song))
        menu.addSeparator()
        autoAction = menu.addAction("Testo automatico per questa canzone")
        autoAction.setCheckable(True)
        autoAction.setChecked(bool(song.get("lyricsAuto", 1)) if song else False)
        autoAction.setEnabled(enabled)
        autoAction.toggled.connect(lambda checked: self.window.setSongAuto(song, "lyricsAuto", checked))
        menu.exec(self.lyricsMenuButton.mapToGlobal(self.lyricsMenuButton.rect().bottomLeft()))

    # ---------- fullscreen ----------
    def toggleFullscreen(self):
        layout = self.layout()
        if self.fullscreenHost is None:
            self.fullscreenHost = FullscreenHost(self)
        host = self.fullscreenHost
        if host.isVisible():
            host.finish()
            host.layout_.removeWidget(self.content)
            layout.addWidget(self.content)
            self.content.layout().setContentsMargins(24, 16, 24, 18)
            host.hide()
            self.fullscreenButton.setToolTip("Schermo intero (F11)")
            self.window.activateWindow()
            QTimer.singleShot(0, self._loadVideo)
        else:
            if self.mode == MODE_LYRICS and self.song and (self.song.get("videoPath") or self.window.videoSourceFor(self.song)):
                self.setMode(MODE_VIDEO)
            layout.removeWidget(self.content)
            host.layout_.addWidget(self.content)
            self.content.layout().setContentsMargins(40, 24, 40, 100)
            host.showFullScreen()
            host.prepare()
            self.fullscreenButton.setToolTip("Esci da schermo intero (Esc)")
            QTimer.singleShot(0, self._loadVideo)
        self.content.show()
