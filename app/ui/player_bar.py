from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy, QSlider, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from ..config import settings
from ..player import REPEAT_ALL, REPEAT_OFF, REPEAT_ONE
from . import theme
from .effects import ColorFader, Visualizer, bounce, dominantColor, heartBurst


class ClickSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.loopRange = None
        self.setFixedHeight(16)
        self.setCursor(Qt.PointingHandCursor)

    def _valueAt(self, xPosition):
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(xPosition - 6), max(1, self.width() - 12))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setSliderDown(True)
            self.setValue(self._valueAt(event.position().x()))
            self.sliderMoved.emit(self.value())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.setValue(self._valueAt(event.position().x()))
            self.sliderMoved.emit(self.value())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.isSliderDown():
            self.setSliderDown(False)
            self.sliderReleased.emit()
            return
        super().mouseReleaseEvent(event)

    def setLoopRange(self, loopRange):
        self.loopRange = loopRange
        self.update()

    def enterEvent(self, event):
        self.hovered = True
        self.update()

    def leaveEvent(self, event):
        self.hovered = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        margin = 6
        width = self.width() - margin * 2
        middle = self.height() / 2
        span = max(1, self.maximum() - self.minimum())
        ratio = (self.value() - self.minimum()) / span if self.maximum() > self.minimum() else 0
        hovered = getattr(self, "hovered", False) or self.isSliderDown()
        painter.setBrush(QColor("#4D4D4D"))
        painter.drawRoundedRect(QRectF(margin, middle - 2, width, 4), 2, 2)
        painter.setBrush(QColor(theme.ACCENT if hovered else theme.TEXT))
        painter.drawRoundedRect(QRectF(margin, middle - 2, width * ratio, 4), 2, 2)
        if self.loopRange and self.maximum() > 0:
            loopColor = QColor(theme.ACCENT)
            loopColor.setAlpha(150)
            startX = margin + self.loopRange[0] / span * width
            endX = margin + self.loopRange[1] / span * width
            painter.setBrush(loopColor)
            painter.drawRoundedRect(QRectF(startX, middle - 4, max(3, endX - startX), 8), 3, 3)
        if hovered:
            painter.setBrush(QColor(theme.TEXT))
            painter.drawEllipse(QRectF(margin + width * ratio - 6, middle - 6, 12, 12))
        painter.end()


def _toolButton(iconName, tooltip, size=32, iconSize=18):
    button = QToolButton()
    button.setIcon(theme.icon(iconName, theme.SUBTEXT, iconSize))
    button.setIconSize(QSize(iconSize, iconSize))
    button.setFixedSize(size, size)
    button.setToolTip(tooltip)
    button.setCursor(Qt.PointingHandCursor)
    button.iconName = iconName
    return button


class PlayerBar(QFrame):
    openQueue = Signal()
    toggleRightPanel = Signal()
    openLoops = Signal()
    cutRequested = Signal()
    favoriteToggled = Signal()
    openEqualizer = Signal()
    openNowPlaying = Signal()
    ambientModeChosen = Signal(str)
    effectsRequested = Signal()
    togetherRequested = Signal()
    openLyrics = Signal()
    artistClicked = Signal()

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.setObjectName("playerBar")
        self.setFixedHeight(88)
        self.seeking = False
        self.sleepTimer = QTimer(self)
        self.sleepTimer.setSingleShot(True)
        self.sleepTimer.timeout.connect(self.player.pause)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        leftWidget = QWidget()
        leftWidget.setMinimumWidth(240)
        leftLayout = QHBoxLayout(leftWidget)
        leftLayout.setContentsMargins(0, 0, 0, 0)
        leftLayout.setSpacing(12)
        self.coverLabel = QLabel()
        self.coverLabel.setFixedSize(56, 56)
        self.coverLabel.setCursor(Qt.PointingHandCursor)
        self.coverLabel.setToolTip("Apri testo e video")
        self.coverLabel.mousePressEvent = lambda event: self.openNowPlaying.emit()
        self.coverLabel.setPixmap(theme.placeholderCover(56))
        textColumn = QVBoxLayout()
        textColumn.setSpacing(2)
        textColumn.addStretch()
        self.titleLabel = QLabel("Nessuna canzone")
        self.titleLabel.setObjectName("songTitle")
        self.artistLabel = QLabel("")
        self.artistLabel.setObjectName("small")
        for label in (self.titleLabel, self.artistLabel):
            label.setMaximumWidth(260)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        textColumn.addWidget(self.titleLabel)
        textColumn.addWidget(self.artistLabel)
        textColumn.addStretch()
        self.miniVisualizer = Visualizer(self.player, bars=12)
        self.miniVisualizer.setFixedSize(46, 22)
        self.miniVisualizer.setVisible(bool(settings.get("fxVisualizer")))
        self.miniVisualizer.listeners.append(self._onBass)
        self.player.playingChanged.connect(lambda playing: self.miniVisualizer.refreshRunning())
        self.favoriteButton = _toolButton("heart", "Salva nei preferiti", 30, 16)
        self.favoriteButton.clicked.connect(self.favoriteToggled)
        leftLayout.addWidget(self.coverLabel)
        leftLayout.addLayout(textColumn, 1)
        leftLayout.addWidget(self.miniVisualizer)
        leftLayout.addWidget(self.favoriteButton)
        self.tintColor = None
        self.coverGlow = 0.0
        self.tintFader = ColorFader(self._setTint, self)
        self.favoriteState = False
        layout.addWidget(leftWidget, 3)

        centerWidget = QWidget()
        centerLayout = QVBoxLayout(centerWidget)
        centerLayout.setContentsMargins(0, 0, 0, 0)
        centerLayout.setSpacing(4)
        buttonsRow = QHBoxLayout()
        buttonsRow.setSpacing(10)
        buttonsRow.addStretch()
        self.shuffleButton = _toolButton("shuffle", "Riproduzione casuale (S)")
        self.shuffleButton.clicked.connect(lambda: self.player.setShuffle(not self.player.shuffle))
        self.previousButton = _toolButton("prev", "Precedente (Ctrl+←)")
        self.previousButton.clicked.connect(self.player.previous)
        self.playButton = QToolButton()
        self.playButton.setObjectName("playButton")
        self.playButton.setFixedSize(36, 36)
        self.playButton.setIcon(theme.icon("play", "#000000", 18))
        self.playButton.setToolTip("Riproduci (Spazio)")
        self.playButton.setCursor(Qt.PointingHandCursor)
        self.playButton.clicked.connect(self.player.togglePlay)
        self.playButton.clicked.connect(lambda: bounce(self.playButton, QSize(18, 18)))
        self.nextButton = _toolButton("next", "Successiva (Ctrl+→)")
        self.nextButton.clicked.connect(lambda: self.player.next())
        self.repeatButton = _toolButton("repeat", "Ripeti (R)")
        self.repeatButton.clicked.connect(self.player.cycleRepeat)
        for button in (self.shuffleButton, self.previousButton, self.playButton, self.nextButton, self.repeatButton):
            buttonsRow.addWidget(button)
        buttonsRow.addStretch()
        centerLayout.addLayout(buttonsRow)
        seekRow = QHBoxLayout()
        seekRow.setSpacing(8)
        self.positionLabel = QLabel("0:00")
        self.positionLabel.setObjectName("small")
        self.positionLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.positionLabel.setFixedWidth(46)
        self.seekSlider = ClickSlider()
        self.seekSlider.setRange(0, 0)
        self.seekSlider.sliderMoved.connect(self._onSeekMoved)
        self.seekSlider.sliderReleased.connect(self._onSeekReleased)
        self.durationLabel = QLabel("0:00")
        self.durationLabel.setObjectName("small")
        self.durationLabel.setFixedWidth(46)
        seekRow.addWidget(self.positionLabel)
        seekRow.addWidget(self.seekSlider, 1)
        seekRow.addWidget(self.durationLabel)
        centerLayout.addLayout(seekRow)
        layout.addWidget(centerWidget, 4)

        rightWidget = QWidget()
        rightLayout = QHBoxLayout(rightWidget)
        rightLayout.setContentsMargins(0, 0, 0, 0)
        rightLayout.setSpacing(4)
        rightLayout.addStretch()
        self.loopButton = _toolButton("loop", "Loop A-B (L)")
        self.loopButton.clicked.connect(self.openLoops)
        self.cutButton = _toolButton("cut", "Taglia audio")
        self.cutButton.clicked.connect(self.cutRequested)
        self.speedButton = _toolButton("speed", "Velocità, pitch e reverb (per canzone)")
        self.speedButton.clicked.connect(self.effectsRequested)
        self.timerButton = _toolButton("timer", "Timer spegnimento")
        self.timerMenu = self._buildTimerMenu()
        self.nowPlayingButton = _toolButton("mic", "Testo (T) — freccia per le opzioni")
        self.nowPlayingButton.setFixedSize(46, 32)
        self.nowPlayingButton.clicked.connect(self.openLyrics)
        self.lyricsMenu = QMenu(self)
        self.nowPlayingButton.setMenu(self.lyricsMenu)
        self.nowPlayingButton.setPopupMode(QToolButton.MenuButtonPopup)
        self.nowPlayingButton.setStyleSheet(
            "QToolButton { padding-right: 12px; } QToolButton::menu-button { border: none; width: 14px; }"
            f" QToolButton::menu-arrow {{ image: url({theme.arrowDownPath()}); width: 10px; height: 10px; }}")
        self.togetherButton = _toolButton("people", "Ascolta insieme")
        self.togetherButton.clicked.connect(self.togetherRequested)
        self.eqButton = _toolButton("eq", "Equalizzatore (E)")
        self.eqButton.clicked.connect(self.openEqualizer)
        self.queueButton = _toolButton("queue", "Coda (Q)")
        self.queueButton.clicked.connect(self.openQueue)
        self.panelButton = _toolButton("panel", "Pannello loop e info")
        self.panelButton.clicked.connect(self.toggleRightPanel)
        self.ambientButton = _toolButton("picture", "Video di sfondo (V)")
        self.ambientButton.setPopupMode(QToolButton.InstantPopup)
        self.ambientButton.setMenu(self._buildAmbientMenu())
        self.moreButton = _toolButton("more", "Altro: taglia, velocità, timer, pannello")
        self.moreButton.setPopupMode(QToolButton.InstantPopup)
        self.moreButton.setMenu(self._buildMoreMenu())
        self.volumeButton = _toolButton("volume", "Muto (M)")
        self.volumeButton.clicked.connect(lambda: self.player.setMuted(not self.player.muted))
        self.volumeSlider = ClickSlider()
        self.volumeSlider.setRange(0, 100)
        self.volumeSlider.setFixedWidth(92)
        self.volumeSlider.valueChanged.connect(self.player.setVolume)
        for widget in (self.togetherButton, self.nowPlayingButton, self.ambientButton, self.speedButton, self.queueButton, self.eqButton, self.loopButton,
                       self.moreButton, self.volumeButton, self.volumeSlider):
            rightLayout.addWidget(widget)
        rightWidget.setMinimumWidth(rightWidget.sizeHint().width())
        layout.addWidget(rightWidget, 3)

        player.songChanged.connect(self.onSongChanged)
        player.loadingChanged.connect(self.onLoadingChanged)
        player.playingChanged.connect(self.onPlayingChanged)
        player.positionChanged.connect(self.onPosition)
        player.durationChanged.connect(self.onDuration)
        player.modesChanged.connect(self.onModesChanged)
        player.volumeChanged.connect(self.onVolumeChanged)
        player.loopChanged.connect(self.onLoopChanged)
        self.onModesChanged()

    def setEffectsIndicator(self, effects):
        bass = effects.get("bassBoost", 0.0)
        active = abs(effects["rate"] - 1.0) > 0.005 or effects["reverbWet"] > 0.005 or bass > 0.005
        self.speedButton.setIcon(theme.icon("speed", theme.ACCENT if active else theme.SUBTEXT, 18))
        details = f"{effects['rate']:.2f}x" + ("" if effects["keepPitch"] else ", pitch libero") + \
            (f", reverb {int(effects['reverbWet'] * 100)}%" if effects["reverbWet"] > 0.005 else "") + \
            (f", bassi +{bass * 12:.0f} dB" if bass > 0.005 else "")
        self.speedButton.setToolTip(f"Velocità ed effetti: {details}")

    def setTogetherActive(self, active, peopleCount=0):
        self.togetherButton.setIcon(theme.icon("people", theme.ACCENT if active else theme.SUBTEXT, 18))
        self.togetherButton.setToolTip(f"Ascolta insieme: {peopleCount} nella stanza" if active else "Ascolta insieme")

    def _buildAmbientMenu(self):
        menu = QMenu(self)
        group = QActionGroup(menu)
        self.ambientActions = {}
        for mode, text in (("off", "Disattivato"), ("background", "Solo sfondo (la UI resta sempre visibile)"),
                           ("fullscreen", "Schermo intero quando non muovi il mouse")):
            action = QAction(text, menu, checkable=True)
            action.triggered.connect(lambda checked=False, value=mode: self.ambientModeChosen.emit(value))
            group.addAction(action)
            menu.addAction(action)
            self.ambientActions[mode] = action
        return menu

    def setAmbientMode(self, mode):
        for key, action in self.ambientActions.items():
            action.setChecked(key == mode)
        self.ambientButton.setIcon(theme.icon("picture", theme.SUBTEXT if mode == "off" else theme.ACCENT, 18))
        texts = {"off": "disattivato", "background": "sfondo", "fullscreen": "schermo intero"}
        self.ambientButton.setToolTip(f"Video di sfondo: {texts.get(mode, mode)} (V)")

    def _buildMoreMenu(self):
        menu = QMenu(self)
        menu.addAction(theme.icon("cut"), "Taglia audio...", self.cutRequested.emit)
        menu.addAction(theme.icon("speed"), "Velocità ed effetti...", self.effectsRequested.emit)
        timerAction = menu.addMenu(self.timerMenu)
        timerAction.setIcon(theme.icon("timer"))
        timerAction.setText("Timer spegnimento")
        menu.addSeparator()
        menu.addAction(theme.icon("panel"), "Pannello loop e info", self.toggleRightPanel.emit)
        return menu

    def _updateMoreIndicator(self):
        if not hasattr(self, "moreButton"):
            return
        active = self.sleepTimer.isActive() or self.player.stopAfterCurrent
        self.moreButton.setIcon(theme.icon("more", theme.ACCENT if active else theme.SUBTEXT, 18))

    def _buildTimerMenu(self):
        menu = QMenu(self)
        for minutes in (5, 15, 30, 45, 60, 90):
            action = menu.addAction(f"Tra {minutes} minuti")
            action.triggered.connect(lambda checked=False, value=minutes: self._startSleep(value))
        endAction = menu.addAction("Alla fine della canzone")
        endAction.triggered.connect(self._sleepAtEnd)
        menu.addSeparator()
        cancelAction = menu.addAction("Disattiva timer")
        cancelAction.triggered.connect(self._cancelSleep)
        return menu

    def _startSleep(self, minutes):
        self.player.stopAfterCurrent = False
        self.sleepTimer.start(minutes * 60 * 1000)
        self.timerButton.setIcon(theme.icon("timer", theme.ACCENT, 18))
        self.timerButton.setToolTip(f"La musica si fermerà tra {minutes} minuti")
        self._updateMoreIndicator()

    def _sleepAtEnd(self):
        self.sleepTimer.stop()
        self.player.stopAfterCurrent = True
        self.timerButton.setIcon(theme.icon("timer", theme.ACCENT, 18))
        self.timerButton.setToolTip("La musica si fermerà alla fine della canzone")
        self._updateMoreIndicator()

    def _cancelSleep(self):
        self.sleepTimer.stop()
        self.player.stopAfterCurrent = False
        self.timerButton.setIcon(theme.icon("timer", theme.SUBTEXT, 18))
        self.timerButton.setToolTip("Timer spegnimento")
        self._updateMoreIndicator()

    def onSongChanged(self, song):
        if not song:
            self.titleLabel.setText("Nessuna canzone")
            self.artistLabel.setText("")
            self.coverLabel.setPixmap(theme.placeholderCover(56))
            self.favoriteButton.setIcon(theme.icon("heart", theme.SUBTEXT, 16))
            self.setCoverTint(None)
            self.favoriteState = False
            return
        self.titleLabel.setText(song.get("title") or "")
        self.titleLabel.setToolTip(song.get("title") or "")
        self.artistLabel.setText("Caricamento in streaming..." if self.player.loading else (song.get("artist") or "Artista sconosciuto"))
        self.coverLabel.setPixmap(theme.coverPixmap(song.get("cover"), 56, song.get("id") or 0, 4))
        self.setCoverTint(song.get("cover"))
        self.setFavorite(bool(song.get("favorite")), animate=False)

    def _setTint(self, color):
        self.tintColor = color
        self.update()

    def _onBass(self, bass):
        glow = bass if settings.get("fxMicro") else 0.0
        if abs(glow - self.coverGlow) > 0.02 or (glow == 0 and self.coverGlow):
            self.coverGlow = glow
            self.update(self.coverLabel.geometry().translated(self.coverLabel.parentWidget().pos()).adjusted(-14, -14, 14, 14))

    def setCoverTint(self, coverPath):
        if not settings.get("fxCoverColors"):
            self.tintFader.fadeTo(None)
            return
        self.tintFader.fadeTo(dominantColor(coverPath))

    def applyEffectSettings(self):
        self.miniVisualizer.setVisible(bool(settings.get("fxVisualizer")))
        self.miniVisualizer.refreshRunning()
        song = self.player.currentSong()
        self.setCoverTint(song.get("cover") if song else None)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.tintColor is None and self.coverGlow <= 0.01:
            return
        from PySide6.QtGui import QLinearGradient
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.tintColor is not None:
            gradient = QLinearGradient(0, 0, self.width() * 0.6, 0)
            start = QColor(self.tintColor)
            start.setAlpha(150)
            end = QColor(self.tintColor)
            end.setAlpha(0)
            gradient.setColorAt(0, start)
            gradient.setColorAt(1, end)
            painter.fillRect(self.rect(), gradient)
        if self.coverGlow > 0.01:
            rect = self.coverLabel.geometry().translated(self.coverLabel.parentWidget().pos())
            glow = QColor(self.tintColor or theme.ACCENT)
            for step in range(4):
                glow.setAlphaF(min(1.0, self.coverGlow) * 0.22 * (4 - step) / 4)
                painter.setPen(Qt.NoPen)
                painter.setBrush(glow)
                spread = 3 + step * 3
                painter.drawRoundedRect(rect.adjusted(-spread, -spread, spread, spread), 6 + spread, 6 + spread)
        painter.end()

    def onLoadingChanged(self, loading):
        song = self.player.currentSong()
        if loading:
            self.artistLabel.setText("Caricamento in streaming...")
        elif song:
            self.artistLabel.setText(song.get("artist") or "Artista sconosciuto")

    def setFavorite(self, isFavorite, animate=True):
        if animate and isFavorite and not self.favoriteState:
            heartBurst(self.favoriteButton)
        self.favoriteState = isFavorite
        self.favoriteButton.setIcon(theme.icon("heartFill" if isFavorite else "heart", theme.ACCENT if isFavorite else theme.SUBTEXT, 16))
        self.favoriteButton.setToolTip("Rimuovi dai preferiti" if isFavorite else "Salva nei preferiti")

    def onPlayingChanged(self, isPlaying):
        self.playButton.setIcon(theme.icon("pause" if isPlaying else "play", "#000000", 18))
        self.playButton.setToolTip("Pausa (Spazio)" if isPlaying else "Riproduci (Spazio)")
        if not isPlaying and not self.player.stopAfterCurrent and self.timerButton.toolTip().startswith("La musica si fermerà alla"):
            self._cancelSleep()
        if not isPlaying and not self.sleepTimer.isActive() and self.timerButton.toolTip().startswith("La musica si fermerà tra"):
            self._cancelSleep()

    def onPosition(self, position):
        if not self.seeking:
            self.seekSlider.setValue(position)
            self.positionLabel.setText(theme.formatTime(position))

    def onDuration(self, duration):
        self.seekSlider.setRange(0, max(0, duration))
        self.durationLabel.setText(theme.formatTime(duration))

    def _onSeekMoved(self, value):
        self.seeking = True
        self.positionLabel.setText(theme.formatTime(value))

    def _onSeekReleased(self):
        self.player.seek(self.seekSlider.value())
        self.seeking = False

    def onModesChanged(self):
        self.shuffleButton.setIcon(theme.icon("shuffle", theme.ACCENT if self.player.shuffle else theme.SUBTEXT, 18))
        repeatMode = self.player.repeatMode
        iconName = "repeatOne" if repeatMode == REPEAT_ONE else "repeat"
        self.repeatButton.setIcon(theme.icon(iconName, theme.SUBTEXT if repeatMode == REPEAT_OFF else theme.ACCENT, 18))
        self.repeatButton.setToolTip({REPEAT_OFF: "Ripeti: disattivato", REPEAT_ALL: "Ripeti: tutto", REPEAT_ONE: "Ripeti: brano"}[repeatMode])

    def onVolumeChanged(self, volume, muted):
        self.volumeSlider.blockSignals(True)
        self.volumeSlider.setValue(volume)
        self.volumeSlider.blockSignals(False)
        iconName = "mute" if muted or volume == 0 else ("volumeLow" if volume < 50 else "volume")
        self.volumeButton.setIcon(theme.icon(iconName, theme.SUBTEXT, 18))

    def onLoopChanged(self, loopData):
        self.seekSlider.setLoopRange((loopData["startMs"], loopData["endMs"]) if loopData else None)
        self.loopButton.setIcon(theme.icon("loop", theme.ACCENT if loopData else theme.SUBTEXT, 18))

    def setPanelActive(self, active):
        self.panelButton.setIcon(theme.icon("panel", theme.ACCENT if active else theme.SUBTEXT, 18))

    def setEqActive(self, active):
        self.eqButton.setIcon(theme.icon("eq", theme.ACCENT if active else theme.SUBTEXT, 18))

    def setLyricsActive(self, active):
        self.nowPlayingButton.setIcon(theme.icon("mic", theme.ACCENT if active else theme.SUBTEXT, 18))
