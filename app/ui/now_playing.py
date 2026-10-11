from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from .. import audio_tools
from ..workers import runInBackground
from . import theme
from .dialogs import TimeSpin
from .waveform import WaveformWidget

_waveformCache = {}


class NowPlayingPanel(QFrame):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.player = window.player
        self.database = window.database
        self.setObjectName("rightPanel")
        self.setMinimumWidth(340)
        self.setMaximumWidth(420)
        self.currentSong = None
        self.loadingPath = None
        self.updatingSpins = False

        outerLayout = QVBoxLayout(self)
        outerLayout.setContentsMargins(0, 0, 0, 0)
        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outerLayout.addWidget(scrollArea)
        content = QWidget()
        scrollArea.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        headerRow = QHBoxLayout()
        headerLabel = QLabel("In riproduzione")
        headerLabel.setObjectName("h3")
        closeButton = QToolButton()
        closeButton.setIcon(theme.icon("close", theme.SUBTEXT, 14))
        closeButton.clicked.connect(self.window.toggleRightPanel)
        headerRow.addWidget(headerLabel)
        headerRow.addStretch()
        headerRow.addWidget(closeButton)
        layout.addLayout(headerRow)

        self.coverLabel = QLabel()
        self.coverLabel.setAlignment(Qt.AlignCenter)
        self.coverLabel.setMinimumHeight(200)
        layout.addWidget(self.coverLabel)
        self.titleLabel = QLabel("Nessuna canzone")
        self.titleLabel.setObjectName("h2")
        self.titleLabel.setWordWrap(True)
        self.artistLabel = QLabel("")
        self.artistLabel.setObjectName("sub")
        layout.addWidget(self.titleLabel)
        layout.addWidget(self.artistLabel)

        loopCard = QFrame()
        loopCard.setStyleSheet(f"QFrame#loopCard {{ background: {theme.ELEVATED}; border-radius: 8px; }}")
        loopCard.setObjectName("loopCard")
        loopLayout = QVBoxLayout(loopCard)
        loopLayout.setContentsMargins(12, 12, 12, 12)
        loopLayout.setSpacing(8)
        loopHeader = QLabel("Loop A-B")
        loopHeader.setObjectName("h3")
        loopHint = QLabel("Trascina sulla forma d'onda o usa A / B durante l'ascolto. I loop salvati restano per sempre.")
        loopHint.setObjectName("small")
        loopHint.setWordWrap(True)
        loopLayout.addWidget(loopHeader)
        loopLayout.addWidget(loopHint)
        self.waveform = WaveformWidget()
        self.waveform.setMinimumHeight(120)
        self.waveform.setMaximumHeight(140)
        self.waveform.setMessage("Nessuna canzone")
        self.waveform.selectionChanged.connect(self._onSelection)
        self.waveform.seekRequested.connect(self.player.seek)
        loopLayout.addWidget(self.waveform)

        spinRow = QHBoxLayout()
        self.setAButton = QPushButton("A")
        self.setAButton.setToolTip("Imposta inizio alla posizione attuale ([)")
        self.setAButton.setFixedWidth(34)
        self.setAButton.setStyleSheet("padding: 0; font-weight: 800;")
        self.setAButton.clicked.connect(self.setPointA)
        self.startSpin = TimeSpin()
        self.setBButton = QPushButton("B")
        self.setBButton.setToolTip("Imposta fine alla posizione attuale (])")
        self.setBButton.setFixedWidth(34)
        self.setBButton.setStyleSheet("padding: 0; font-weight: 800;")
        self.setBButton.clicked.connect(self.setPointB)
        self.endSpin = TimeSpin()
        for spin in (self.startSpin, self.endSpin):
            spin.setMinimumWidth(70)
        self.startSpin.valueChanged.connect(self._onSpinChanged)
        self.endSpin.valueChanged.connect(self._onSpinChanged)
        spinRow.addWidget(self.setAButton)
        spinRow.addWidget(self.startSpin, 1)
        spinRow.addWidget(self.setBButton)
        spinRow.addWidget(self.endSpin, 1)
        loopLayout.addLayout(spinRow)

        actionRow = QHBoxLayout()
        self.activateButton = QPushButton("Attiva loop")
        self.activateButton.setObjectName("accent")
        self.activateButton.clicked.connect(self.toggleDraftLoop)
        self.saveButton = QPushButton("Salva")
        self.saveButton.clicked.connect(self.saveDraft)
        self.cutButton = QPushButton("")
        self.cutButton.setIcon(theme.icon("cut", theme.TEXT, 16))
        self.cutButton.setToolTip("Taglia / esporta questa parte")
        self.cutButton.setFixedWidth(44)
        self.cutButton.setStyleSheet("padding: 0;")
        self.cutButton.clicked.connect(self._cutSelection)
        actionRow.addWidget(self.activateButton, 1)
        actionRow.addWidget(self.saveButton)
        actionRow.addWidget(self.cutButton)
        loopLayout.addLayout(actionRow)

        savedLabel = QLabel("Loop salvati")
        savedLabel.setObjectName("small")
        loopLayout.addWidget(savedLabel)
        self.loopList = QListWidget()
        self.loopList.setMinimumHeight(140)
        self.loopList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.loopList.customContextMenuRequested.connect(self._loopMenu)
        self.loopList.itemClicked.connect(self._onLoopClicked)
        self.loopList.itemDoubleClicked.connect(self._renameLoop)
        loopLayout.addWidget(self.loopList)
        layout.addWidget(loopCard)
        layout.addStretch()

        self.player.songChanged.connect(self.setSong)
        self.player.positionChanged.connect(self.waveform.setPlayhead)
        self.player.loopChanged.connect(self._onLoopChanged)
        self._setEnabled(False)

    def _setEnabled(self, enabled):
        for widget in (self.setAButton, self.setBButton, self.startSpin, self.endSpin, self.activateButton,
                       self.saveButton, self.cutButton, self.loopList):
            widget.setEnabled(enabled)

    def setSong(self, song):
        previousId = self.currentSong.get("id") if self.currentSong else None
        self.currentSong = song
        if not song:
            self.titleLabel.setText("Nessuna canzone")
            self.artistLabel.setText("")
            self.coverLabel.setPixmap(theme.placeholderCover(260))
            self.waveform.clear()
            self.waveform.setMessage("Nessuna canzone")
            self.loopList.clear()
            self._setEnabled(False)
            return
        self.titleLabel.setText(song.get("title") or "")
        self.artistLabel.setText(song.get("artist") or "Artista sconosciuto")
        self.coverLabel.setPixmap(theme.coverPixmap(song.get("cover"), 260, song.get("id") or 0, 8))
        self._setEnabled(True)
        if previousId == song.get("id") and self.waveform.peaks is not None:
            return
        self.waveform.clear()
        self.waveform.setSelection(None, None)
        self.refreshLoops()
        path = song["path"]
        if str(path).startswith("stream:"):
            self.waveform.setMessage("Canzone in streaming: scaricala per vedere la forma d'onda")
            return
        cached = _waveformCache.get(path)
        if cached:
            self._applyWaveform(path, cached)
            return
        self.loadingPath = path
        runInBackground(audio_tools.loadWaveform, path, 1200,
                        onFinished=lambda result, p=path: self._applyWaveform(p, result),
                        onError=lambda message: self.waveform.setMessage("Forma d'onda non disponibile"))

    def invalidate(self, path):
        _waveformCache.pop(path, None)

    def _applyWaveform(self, path, result):
        if len(_waveformCache) > 30:
            _waveformCache.pop(next(iter(_waveformCache)))
        _waveformCache[path] = result
        if not self.currentSong or self.currentSong["path"] != path:
            return
        peaks, durationMs = result
        self.waveform.setData(peaks, durationMs)
        for spin in (self.startSpin, self.endSpin):
            spin.setMaximum(durationMs / 1000.0)
        self.refreshLoops()
        if self.player.activeLoop:
            self._onLoopChanged(self.player.activeLoop)

    def refreshLoops(self):
        self.loopList.clear()
        if not self.currentSong:
            return
        activeId = self.player.activeLoop.get("id") if self.player.activeLoop else None
        regions = []
        for loopData in self.database.loops(self.currentSong["id"]):
            item = QListWidgetItem(theme.icon("loop", theme.ACCENT if loopData["id"] == activeId else theme.SUBTEXT, 16),
                                   f"{loopData['name']}   {theme.formatTime(loopData['startMs'])} – {theme.formatTime(loopData['endMs'])}")
            item.setData(Qt.UserRole, loopData)
            self.loopList.addItem(item)
            regions.append({"startMs": loopData["startMs"], "endMs": loopData["endMs"], "active": loopData["id"] == activeId})
        self.waveform.setRegions(regions)

    def _draft(self):
        if self.waveform.selection:
            return self.waveform.selection
        return None

    def _syncSpins(self):
        selection = self._draft()
        if not selection:
            return
        self.updatingSpins = True
        self.startSpin.setValue(selection[0] / 1000.0)
        self.endSpin.setValue(selection[1] / 1000.0)
        self.updatingSpins = False

    def _onSelection(self, startMs, endMs):
        self._syncSpins()
        active = self.player.activeLoop
        if active and active.get("id") is None:
            self.player.setLoop({"id": None, "startMs": startMs, "endMs": endMs, "name": "Loop"})

    def _onSpinChanged(self):
        if self.updatingSpins:
            return
        startMs = int(self.startSpin.value() * 1000)
        endMs = max(startMs + 50, int(self.endSpin.value() * 1000))
        self.waveform.setSelection(startMs, endMs)
        self._onSelection(startMs, endMs)

    def setPointA(self):
        if not self.currentSong:
            return
        positionMs = self.player.position()
        _, endMs = self._draft() or (0, self.player.duration())
        if endMs <= positionMs:
            endMs = self.player.duration()
        self.waveform.setSelection(positionMs, endMs)
        self._onSelection(*self.waveform.selection)

    def setPointB(self):
        if not self.currentSong:
            return
        positionMs = self.player.position()
        startMs, _ = self._draft() or (0, 0)
        if startMs >= positionMs:
            startMs = 0
        self.waveform.setSelection(startMs, positionMs)
        self._onSelection(*self.waveform.selection)
        if not self.player.activeLoop:
            self.toggleDraftLoop()

    def toggleDraftLoop(self):
        if self.player.activeLoop:
            self.player.setLoop(None)
            return
        selection = self._draft()
        if not selection:
            self.window.showStatus("Seleziona prima una parte della canzone")
            return
        self.player.setLoop({"id": None, "startMs": selection[0], "endMs": selection[1], "name": "Loop"})

    def saveDraft(self):
        selection = self._draft()
        if not selection or not self.currentSong:
            self.window.showStatus("Seleziona prima una parte della canzone")
            return
        defaultName = f"Loop {self.loopList.count() + 1}"
        name, accepted = QInputDialog.getText(self, "Salva loop", "Nome del loop:", text=defaultName)
        if not accepted:
            return
        loopId = self.database.addLoop(self.currentSong["id"], name.strip() or defaultName, selection[0], selection[1])
        self.player.setLoop({"id": loopId, "startMs": selection[0], "endMs": selection[1], "name": name})
        self.refreshLoops()
        self.window.showStatus("Loop salvato")

    def _onLoopClicked(self, item):
        loopData = item.data(Qt.UserRole)
        if self.player.activeLoop and self.player.activeLoop.get("id") == loopData["id"]:
            self.player.setLoop(None)
            return
        self.waveform.setSelection(loopData["startMs"], loopData["endMs"])
        self._syncSpins()
        self.player.setLoop(loopData)
        self.player.play()

    def _renameLoop(self, item):
        loopData = item.data(Qt.UserRole)
        name, accepted = QInputDialog.getText(self, "Rinomina loop", "Nome del loop:", text=loopData["name"])
        if accepted and name.strip():
            self.database.updateLoop(loopData["id"], name=name.strip())
            self.refreshLoops()

    def _loopMenu(self, position):
        item = self.loopList.itemAt(position)
        if not item:
            return
        loopData = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction(theme.icon("play"), "Attiva", lambda: self._onLoopClicked(item))
        menu.addAction(theme.icon("edit"), "Rinomina", lambda: self._renameLoop(item))
        menu.addAction(theme.icon("check"), "Aggiorna con la selezione attuale", lambda: self._overwriteLoop(loopData))
        menu.addAction(theme.icon("cut"), "Esporta come nuova canzone", lambda: self.window.openCutDialog(
            self.currentSong, (loopData["startMs"], loopData["endMs"])))
        menu.addSeparator()
        menu.addAction(theme.icon("delete"), "Elimina", lambda: self._deleteLoop(loopData))
        menu.exec(self.loopList.viewport().mapToGlobal(position))

    def _overwriteLoop(self, loopData):
        selection = self._draft()
        if not selection:
            return
        self.database.updateLoop(loopData["id"], startMs=selection[0], endMs=selection[1])
        if self.player.activeLoop and self.player.activeLoop.get("id") == loopData["id"]:
            self.player.setLoop({**loopData, "startMs": selection[0], "endMs": selection[1]})
        self.refreshLoops()

    def _deleteLoop(self, loopData):
        if self.player.activeLoop and self.player.activeLoop.get("id") == loopData["id"]:
            self.player.setLoop(None)
        self.database.deleteLoop(loopData["id"])
        self.refreshLoops()

    def _cutSelection(self):
        if self.currentSong:
            self.window.openCutDialog(self.currentSong, self._draft())

    def _onLoopChanged(self, loopData):
        self.activateButton.setText("Disattiva loop" if loopData else "Attiva loop")
        if loopData and self.waveform.peaks is not None:
            if self.waveform.selection != (loopData["startMs"], loopData["endMs"]):
                self.waveform.setSelection(loopData["startMs"], loopData["endMs"])
                self._syncSpins()
        self.refreshLoops()
