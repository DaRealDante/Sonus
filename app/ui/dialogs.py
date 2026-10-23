import os

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QListWidget, QListWidgetItem,
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QTabWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from .. import audio_tools, metadata
from ..config import APP_NAME, DATA_DIR, IMAGE_FILTER, TEMP_DIR, VERSION, settings
from ..workers import runInBackground
from . import theme
from .waveform import WaveformWidget


def storeImage(sourcePath):
    if not sourcePath or not os.path.isfile(sourcePath):
        return None
    extension = os.path.splitext(sourcePath)[1].lower() or ".jpg"
    with open(sourcePath, "rb") as imageFile:
        return metadata.saveCoverBytes(imageFile.read(), extension)


class CoverPicker(QLabel):
    def __init__(self, coverPath=None, size=180, seed=0, glyph="music", parent=None):
        super().__init__(parent)
        self.coverPath = coverPath
        self.coverSize = size
        self.seed = seed
        self.glyph = glyph
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Clicca per scegliere un'immagine")
        self.refresh()

    def refresh(self):
        self.setPixmap(theme.coverPixmap(self.coverPath, self.coverSize, self.seed, 6, self.glyph))

    def mousePressEvent(self, event):
        self.choose()

    def choose(self):
        filePath, _ = QFileDialog.getOpenFileName(self, "Scegli immagine", os.path.expanduser("~"), IMAGE_FILTER)
        if filePath:
            self.coverPath = storeImage(filePath)
            self.refresh()

    def clearCover(self):
        self.coverPath = None
        self.refresh()


class PlaylistDialog(QDialog):
    def __init__(self, parent=None, playlist=None):
        super().__init__(parent)
        self.setWindowTitle("Modifica playlist" if playlist else "Nuova playlist")
        self.setMinimumWidth(560)
        playlist = playlist or {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        titleLabel = QLabel(self.windowTitle())
        titleLabel.setObjectName("h2")
        layout.addWidget(titleLabel)
        body = QHBoxLayout()
        body.setSpacing(16)
        coverColumn = QVBoxLayout()
        self.coverPicker = CoverPicker(playlist.get("cover"), 180, playlist.get("id") or 0, "queue")
        coverColumn.addWidget(self.coverPicker)
        coverButtons = QHBoxLayout()
        chooseButton = QPushButton("Scegli foto")
        chooseButton.clicked.connect(self.coverPicker.choose)
        removeButton = QPushButton("Rimuovi")
        removeButton.clicked.connect(self.coverPicker.clearCover)
        coverButtons.addWidget(chooseButton)
        coverButtons.addWidget(removeButton)
        coverColumn.addLayout(coverButtons)
        coverColumn.addStretch()
        body.addLayout(coverColumn)
        fieldsColumn = QVBoxLayout()
        self.nameEdit = QLineEdit(playlist.get("name") or "")
        self.nameEdit.setPlaceholderText("Nome della playlist")
        self.descriptionEdit = QPlainTextEdit(playlist.get("description") or "")
        self.descriptionEdit.setPlaceholderText("Aggiungi una descrizione (facoltativa)")
        fieldsColumn.addWidget(self.nameEdit)
        fieldsColumn.addWidget(self.descriptionEdit)
        body.addLayout(fieldsColumn, 1)
        layout.addLayout(body)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancelButton = QPushButton("Annulla")
        cancelButton.clicked.connect(self.reject)
        saveButton = QPushButton("Salva")
        saveButton.setObjectName("accent")
        saveButton.setDefault(True)
        saveButton.clicked.connect(self._accept)
        buttons.addWidget(cancelButton)
        buttons.addWidget(saveButton)
        layout.addLayout(buttons)
        self.nameEdit.setFocus()

    def _accept(self):
        if not self.nameEdit.text().strip():
            self.nameEdit.setFocus()
            return
        self.accept()

    def values(self):
        return self.nameEdit.text().strip(), self.descriptionEdit.toPlainText().strip(), self.coverPicker.coverPath


class SongEditDialog(QDialog):
    def __init__(self, parent, song):
        super().__init__(parent)
        self.song = song
        self.setWindowTitle("Modifica informazioni")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        titleLabel = QLabel("Modifica informazioni")
        titleLabel.setObjectName("h2")
        layout.addWidget(titleLabel)
        body = QHBoxLayout()
        body.setSpacing(16)
        coverColumn = QVBoxLayout()
        self.coverPicker = CoverPicker(song.get("cover"), 170, song.get("id") or 0)
        coverColumn.addWidget(self.coverPicker)
        coverButtons = QHBoxLayout()
        chooseButton = QPushButton("Scegli foto")
        chooseButton.clicked.connect(self.coverPicker.choose)
        removeButton = QPushButton("Rimuovi")
        removeButton.clicked.connect(self.coverPicker.clearCover)
        coverButtons.addWidget(chooseButton)
        coverButtons.addWidget(removeButton)
        coverColumn.addLayout(coverButtons)
        coverColumn.addStretch()
        body.addLayout(coverColumn)
        form = QFormLayout()
        form.setSpacing(10)
        self.titleEdit = QLineEdit(song.get("title") or "")
        self.artistEdit = QLineEdit(song.get("artist") or "")
        self.albumEdit = QLineEdit(song.get("album") or "")
        form.addRow("Titolo", self.titleEdit)
        form.addRow("Artista", self.artistEdit)
        form.addRow("Album", self.albumEdit)
        pathLabel = QLabel(song.get("path") or "")
        pathLabel.setObjectName("small")
        pathLabel.setWordWrap(True)
        pathLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("File", pathLabel)
        self.writeTagsCheck = QCheckBox("Scrivi i dati anche nel file MP3")
        self.writeTagsCheck.setChecked(song.get("path", "").lower().endswith(".mp3"))
        self.writeTagsCheck.setEnabled(song.get("path", "").lower().endswith(".mp3"))
        form.addRow("", self.writeTagsCheck)
        body.addLayout(form, 1)
        layout.addLayout(body)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancelButton = QPushButton("Annulla")
        cancelButton.clicked.connect(self.reject)
        saveButton = QPushButton("Salva")
        saveButton.setObjectName("accent")
        saveButton.setDefault(True)
        saveButton.clicked.connect(self.accept)
        buttons.addWidget(cancelButton)
        buttons.addWidget(saveButton)
        layout.addLayout(buttons)

    def values(self):
        return {
            "title": self.titleEdit.text().strip() or self.song.get("title"),
            "artist": self.artistEdit.text().strip(),
            "album": self.albumEdit.text().strip(),
            "cover": self.coverPicker.coverPath,
        }


class TimeSpin(QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(3)
        self.setSingleStep(0.1)
        self.setSuffix(" s")
        self.setMinimumWidth(110)
        self.setKeyboardTracking(False)


class CutDialog(QDialog):
    def __init__(self, parent, song, onDone, initialSelection=None):
        super().__init__(parent)
        self.song = song
        self.onDone = onDone
        self.durationMs = int((song.get("duration") or 0) * 1000)
        self.setWindowTitle(f"Taglia audio — {song.get('title')}")
        self.resize(980, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        header = QLabel("Taglia audio")
        header.setObjectName("h2")
        subHeader = QLabel(f"{song.get('title')}  ·  {song.get('artist') or 'Artista sconosciuto'}")
        subHeader.setObjectName("sub")
        layout.addWidget(header)
        layout.addWidget(subHeader)
        hint = QLabel("Trascina sulla forma d'onda per selezionare · trascina i bordi per regolare · rotella = zoom · Shift+rotella = scorri · doppio click = reset zoom · click = posiziona")
        hint.setObjectName("small")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.waveform = WaveformWidget()
        self.waveform.setMinimumHeight(170)
        self.waveform.selectionChanged.connect(self._onWaveSelection)
        self.waveform.seekRequested.connect(self._seekPreview)
        layout.addWidget(self.waveform, 1)

        controls = QHBoxLayout()
        self.playButton = QToolButton()
        self.playButton.setObjectName("playButton")
        self.playButton.setIcon(theme.icon("play", "#000", 18))
        self.playButton.setFixedSize(36, 36)
        self.playButton.setToolTip("Riproduci / pausa")
        self.playButton.clicked.connect(self._togglePreview)
        previewSelectionButton = QPushButton("Ascolta selezione")
        previewSelectionButton.setIcon(theme.icon("play", theme.TEXT, 14))
        previewSelectionButton.clicked.connect(self._previewSelection)
        self.positionLabel = QLabel("0:00.000")
        self.positionLabel.setObjectName("sub")
        controls.addWidget(self.playButton)
        controls.addWidget(previewSelectionButton)
        controls.addWidget(self.positionLabel)
        controls.addStretch()
        setStartButton = QPushButton("Inizio = posizione")
        setStartButton.clicked.connect(lambda: self._setEdge("start"))
        setEndButton = QPushButton("Fine = posizione")
        setEndButton.clicked.connect(lambda: self._setEdge("end"))
        controls.addWidget(setStartButton)
        controls.addWidget(setEndButton)
        layout.addLayout(controls)

        optionsGrid = QGridLayout()
        optionsGrid.setHorizontalSpacing(14)
        optionsGrid.setVerticalSpacing(10)
        self.startSpin = TimeSpin()
        self.endSpin = TimeSpin()
        self.startSpin.valueChanged.connect(self._onSpinChanged)
        self.endSpin.valueChanged.connect(self._onSpinChanged)
        self.lengthLabel = QLabel("")
        self.lengthLabel.setObjectName("sub")
        optionsGrid.addWidget(QLabel("Inizio"), 0, 0)
        optionsGrid.addWidget(self.startSpin, 0, 1)
        optionsGrid.addWidget(QLabel("Fine"), 0, 2)
        optionsGrid.addWidget(self.endSpin, 0, 3)
        optionsGrid.addWidget(self.lengthLabel, 0, 4)

        self.keepRadio = QRadioButton("Tieni solo la selezione")
        self.removeRadio = QRadioButton("Elimina la selezione")
        self.keepRadio.setChecked(True)
        modeGroup = QButtonGroup(self)
        modeGroup.addButton(self.keepRadio)
        modeGroup.addButton(self.removeRadio)
        optionsGrid.addWidget(self.keepRadio, 1, 0, 1, 2)
        optionsGrid.addWidget(self.removeRadio, 1, 2, 1, 2)

        self.fadeInSpin = QSpinBox()
        self.fadeInSpin.setRange(0, 20000)
        self.fadeInSpin.setSingleStep(250)
        self.fadeInSpin.setSuffix(" ms")
        self.fadeOutSpin = QSpinBox()
        self.fadeOutSpin.setRange(0, 20000)
        self.fadeOutSpin.setSingleStep(250)
        self.fadeOutSpin.setSuffix(" ms")
        optionsGrid.addWidget(QLabel("Fade in"), 2, 0)
        optionsGrid.addWidget(self.fadeInSpin, 2, 1)
        optionsGrid.addWidget(QLabel("Fade out"), 2, 2)
        optionsGrid.addWidget(self.fadeOutSpin, 2, 3)

        self.nameEdit = QLineEdit(f"{song.get('title')} (taglio)")
        self.formatCombo = QComboBox()
        self.formatCombo.addItems(["mp3", "wav", "flac", "m4a"])
        self.replaceCheck = QCheckBox("Sostituisci il file originale")
        self.replaceCheck.toggled.connect(lambda checked: self.nameEdit.setEnabled(not checked) or self.formatCombo.setEnabled(not checked))
        optionsGrid.addWidget(QLabel("Nome"), 3, 0)
        optionsGrid.addWidget(self.nameEdit, 3, 1, 1, 3)
        optionsGrid.addWidget(self.formatCombo, 3, 4)
        optionsGrid.addWidget(self.replaceCheck, 4, 1, 1, 3)
        optionsGrid.setColumnStretch(5, 1)
        layout.addLayout(optionsGrid)

        buttons = QHBoxLayout()
        self.statusLabel = QLabel("")
        self.statusLabel.setObjectName("sub")
        buttons.addWidget(self.statusLabel)
        buttons.addStretch()
        cancelButton = QPushButton("Chiudi")
        cancelButton.clicked.connect(self.reject)
        self.saveButton = QPushButton("Salva taglio")
        self.saveButton.setObjectName("accent")
        self.saveButton.setIcon(theme.icon("cut", "#000", 16))
        self.saveButton.clicked.connect(self._save)
        buttons.addWidget(cancelButton)
        buttons.addWidget(self.saveButton)
        layout.addLayout(buttons)

        self.previewPlayer = QMediaPlayer(self)
        self.previewOutput = QAudioOutput(self)
        self.previewOutput.setVolume((settings.get("volume") / 100.0) ** 2)
        self.previewPlayer.setAudioOutput(self.previewOutput)
        self.previewPlayer.setSource(QUrl.fromLocalFile(os.path.abspath(song["path"])))
        self.previewPlayer.positionChanged.connect(self._onPreviewPosition)
        self.previewPlayer.playbackStateChanged.connect(self._onPreviewState)
        self.previewPlayer.durationChanged.connect(self._onPreviewDuration)
        self.stopAtMs = None
        self.updatingSpins = False

        self._applyDuration(self.durationMs)
        initial = initialSelection or (0, self.durationMs)
        self._setSelection(*initial)
        runInBackground(audio_tools.loadWaveform, song["path"], onFinished=self._onWaveform,
                        onError=lambda message: self.waveform.setMessage(f"Impossibile leggere l'audio: {message}"))

    def _applyDuration(self, durationMs):
        seconds = max(0.001, durationMs / 1000.0)
        for spin in (self.startSpin, self.endSpin):
            spin.setMaximum(seconds)

    def _onPreviewDuration(self, durationMs):
        if durationMs > 0 and not self.durationMs:
            self.durationMs = durationMs
            self._applyDuration(durationMs)
            self._setSelection(0, durationMs)

    def _onWaveform(self, result):
        peaks, durationMs = result
        if durationMs > 0:
            hadFull = self.waveform.selection is None or self.waveform.selection[1] >= self.durationMs - 5
            self.durationMs = durationMs
            self._applyDuration(durationMs)
            self.waveform.setData(peaks, durationMs)
            if hadFull and self.waveform.selection is not None and self.waveform.selection[0] == 0:
                self._setSelection(0, durationMs)
            else:
                self._setSelection(*self.waveform.selection) if self.waveform.selection else self._setSelection(0, durationMs)

    def _setSelection(self, startMs, endMs):
        self.waveform.setSelection(startMs, endMs)
        self._syncSpins()

    def _syncSpins(self):
        if not self.waveform.selection:
            return
        startMs, endMs = self.waveform.selection
        self.updatingSpins = True
        self.startSpin.setValue(startMs / 1000.0)
        self.endSpin.setValue(endMs / 1000.0)
        self.updatingSpins = False
        self.lengthLabel.setText(f"Durata selezione: {theme.formatTimePrecise(endMs - startMs)}")

    def _onWaveSelection(self, startMs, endMs):
        self._syncSpins()

    def _onSpinChanged(self):
        if self.updatingSpins:
            return
        startMs = int(self.startSpin.value() * 1000)
        endMs = int(self.endSpin.value() * 1000)
        if endMs <= startMs:
            endMs = startMs + 10
        self._setSelection(startMs, endMs)

    def _setEdge(self, edge):
        positionMs = self.previewPlayer.position()
        startMs, endMs = self.waveform.selection or (0, self.durationMs)
        if edge == "start":
            startMs = min(positionMs, endMs - 10)
        else:
            endMs = max(positionMs, startMs + 10)
        self._setSelection(startMs, endMs)

    def _togglePreview(self):
        if self.previewPlayer.playbackState() == QMediaPlayer.PlayingState:
            self.previewPlayer.pause()
        else:
            self.stopAtMs = None
            self.previewPlayer.play()

    def _previewSelection(self):
        if not self.waveform.selection:
            return
        startMs, endMs = self.waveform.selection
        self.stopAtMs = endMs
        self.previewPlayer.setPosition(startMs)
        self.previewPlayer.play()

    def _seekPreview(self, positionMs):
        self.previewPlayer.setPosition(positionMs)
        self.waveform.setPlayhead(positionMs)

    def _onPreviewPosition(self, positionMs):
        self.waveform.setPlayhead(positionMs)
        self.positionLabel.setText(theme.formatTimePrecise(positionMs))
        if self.stopAtMs is not None and positionMs >= self.stopAtMs:
            self.stopAtMs = None
            self.previewPlayer.pause()

    def _onPreviewState(self, state):
        isPlaying = state == QMediaPlayer.PlayingState
        self.playButton.setIcon(theme.icon("pause" if isPlaying else "play", "#000", 18))

    def _save(self):
        if not self.waveform.selection:
            return
        startMs, endMs = self.waveform.selection
        removeSelection = self.removeRadio.isChecked()
        if not removeSelection and endMs - startMs < 100:
            QMessageBox.warning(self, APP_NAME, "La selezione è troppo corta.")
            return
        if removeSelection and startMs <= 5 and endMs >= self.durationMs - 5:
            QMessageBox.warning(self, APP_NAME, "Non puoi eliminare tutta la canzone.")
            return
        replaceOriginal = self.replaceCheck.isChecked()
        if replaceOriginal:
            answer = QMessageBox.question(self, APP_NAME, "Sovrascrivere il file originale? L'operazione non si può annullare.")
            if answer != QMessageBox.Yes:
                return
            extension = os.path.splitext(self.song["path"])[1].lower() or ".mp3"
            outputPath = audio_tools.uniquePath(TEMP_DIR, "cut_tmp", extension)
            newTitle = self.song.get("title")
        else:
            extension = "." + self.formatCombo.currentText()
            newTitle = self.nameEdit.text().strip() or f"{self.song.get('title')} (taglio)"
            baseName = audio_tools.safeFileName(f"{self.song.get('artist')} - {newTitle}" if self.song.get("artist") else newTitle)
            outputPath = audio_tools.uniquePath(settings.musicDir(), baseName, extension)
        self.previewPlayer.stop()
        self.previewPlayer.setSource(QUrl())
        self.saveButton.setEnabled(False)
        self.statusLabel.setText("Elaborazione in corso...")
        runInBackground(
            audio_tools.cutAudio, self.song["path"], outputPath, startMs, endMs, removeSelection,
            self.fadeInSpin.value(), self.fadeOutSpin.value(), settings.get("audioQuality"),
            onFinished=lambda path: self._onCutDone(path, newTitle, replaceOriginal,
                                                    {"mode": "remove" if removeSelection else "keep", "startMs": startMs, "endMs": endMs}),
            onError=self._onCutError,
        )

    def _onCutDone(self, outputPath, newTitle, replaceOriginal, cutOperation=None):
        self.statusLabel.setText("Fatto!")
        self.onDone(self.song, outputPath, newTitle, replaceOriginal, cutOperation)
        self.accept()

    def _onCutError(self, message):
        self.saveButton.setEnabled(True)
        self.statusLabel.setText("")
        self.previewPlayer.setSource(QUrl.fromLocalFile(os.path.abspath(self.song["path"])))
        QMessageBox.critical(self, APP_NAME, f"Errore durante il taglio:\n{message}")

    def done(self, result):
        self.previewPlayer.stop()
        super().done(result)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni")
        self.setMinimumWidth(640)
        self.restartForColors = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        titleLabel = QLabel("Impostazioni")
        titleLabel.setObjectName("h2")
        layout.addWidget(titleLabel)
        form = QFormLayout()
        form.setSpacing(12)
        folderRow = QHBoxLayout()
        self.folderEdit = QLineEdit(settings.musicDir())
        browseButton = QPushButton("Sfoglia")
        browseButton.clicked.connect(self._browse)
        folderRow.addWidget(self.folderEdit, 1)
        folderRow.addWidget(browseButton)
        form.addRow("Cartella musica\n(download e tagli)", folderRow)
        self.qualityCombo = QComboBox()
        self.qualityCombo.addItems(["128", "192", "256", "320"])
        self.qualityCombo.setCurrentText(str(settings.get("audioQuality")))
        form.addRow("Qualità MP3 (kbps)", self.qualityCombo)
        self.resultsSpin = QSpinBox()
        self.resultsSpin.setRange(5, 50)
        self.resultsSpin.setValue(int(settings.get("searchResults")))
        form.addRow("Risultati ricerca web", self.resultsSpin)
        self.copyCheck = QCheckBox("Copia i file importati nella cartella musica")
        self.copyCheck.setChecked(bool(settings.get("copyImported")))
        form.addRow("", self.copyCheck)
        self.streamOnlyCheck = QCheckBox("Solo streaming: le canzoni da YouTube non vengono scaricate (scaricale dal menu → Scarica sul PC)")
        self.streamOnlyCheck.setToolTip("Le canzoni non occupano spazio ma servono internet per ascoltarle.\n"
                                        "Puoi sempre scaricarne una dal menu della canzone → Scarica sul PC.")
        self.streamOnlyCheck.setChecked(bool(settings.get("streamOnly")))
        form.addRow("", self.streamOnlyCheck)
        self.streamVideoCheck = QCheckBox("Mostra il video in streaming quando non è scaricato")
        self.streamVideoCheck.setChecked(bool(settings.get("streamVideo")))
        form.addRow("", self.streamVideoCheck)
        self.autoVideoCheck = QCheckBox("Salva automaticamente il video delle canzoni scaricate")
        self.autoVideoCheck.setChecked(bool(settings.get("autoVideo")))
        form.addRow("", self.autoVideoCheck)
        self.videoQualityCombo = QComboBox()
        self.videoQualityCombo.addItems(["480", "720", "1080"])
        self.videoQualityCombo.setCurrentText(str(settings.get("videoQuality")))
        form.addRow("Qualità video (p)", self.videoQualityCombo)
        self.videoFpsCombo = QComboBox()
        for value, text in self.VIDEO_FPS:
            self.videoFpsCombo.addItem(text, value)
        fpsIndex = self.videoFpsCombo.findData(int(settings.get("videoFps") or 0))
        self.videoFpsCombo.setCurrentIndex(max(0, fpsIndex))
        self.videoFpsCombo.setToolTip("Più FPS = video più fluido ma più lavoro per il PC")
        form.addRow("FPS video", self.videoFpsCombo)
        self.pauseVideoCheck = QCheckBox("Ferma il video quando usi altre app o giochi (consigliato, evita lag)")
        self.pauseVideoCheck.setChecked(bool(settings.get("pauseVideoInBackground")))
        form.addRow("", self.pauseVideoCheck)
        self.autoUpdateCheck = QCheckBox("Controlla da solo se c'è una nuova versione di Sonus")
        self.autoUpdateCheck.setChecked(bool(settings.get("autoCheckUpdates")))
        form.addRow("", self.autoUpdateCheck)
        self.discordCheck = QCheckBox("Mostra su Discord cosa stai ascoltando (con tempo e copertina)")
        self.discordCheck.setChecked(bool(settings.get("discordPresence")))
        form.addRow("", self.discordCheck)
        self.discordIdEdit = QLineEdit(settings.get("discordClientId") or "")
        from ..config import DISCORD_CLIENT_ID
        self.discordIdEdit.setPlaceholderText("Vuoto = quello di Sonus" if DISCORD_CLIENT_ID else "Incolla l'ID della tua app Discord")
        self.discordIdEdit.setToolTip("ID applicazione dal Discord Developer Portal (solo se vuoi usarne uno tuo)")
        form.addRow("ID app Discord", self.discordIdEdit)
        self.autoLyricsCheck = QCheckBox("Salva automaticamente i testi")
        self.autoLyricsCheck.setChecked(bool(settings.get("autoLyrics")))
        form.addRow("", self.autoLyricsCheck)
        self.tabs = QTabWidget()
        generalPage = QWidget()
        generalPage.setLayout(form)
        self.tabs.addTab(generalPage, "Generale")
        self.tabs.addTab(self._buildAppearanceTab(), "Aspetto")
        self.tabs.addTab(self._buildEffectsTab(), "Animazioni")
        layout.addWidget(self.tabs)
        infoRow = QHBoxLayout()
        profileButton = QPushButton("Profilo...")
        profileButton.setToolTip("Nome e foto che vedono gli amici in \"Ascolta insieme\"")
        profileButton.clicked.connect(self._editProfile)
        infoRow.addWidget(profileButton)
        dataButton = QPushButton("Apri cartella dati")
        dataButton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(DATA_DIR)))
        infoRow.addWidget(dataButton)
        engineButton = QPushButton("Aggiorna motore YouTube")
        engineButton.setToolTip("Scarica l'ultima versione di yt-dlp (serve se i download da YouTube smettono di funzionare)")
        engineButton.clicked.connect(lambda: parent.checkEngineUpdate(force=True) if parent else None)
        infoRow.addWidget(engineButton)
        infoRow.addStretch()
        layout.addLayout(infoRow)
        infoRow = QHBoxLayout()
        checkButton = QPushButton("Controlla aggiornamenti")
        checkButton.clicked.connect(lambda: parent.checkAppUpdate(manual=True) if parent else None)
        infoRow.addWidget(checkButton)
        updateButton = QPushButton("Installa da file...")
        updateButton.setToolTip("Scegli il file Sonus_Setup ricevuto: l'app si chiude e si aggiorna da sola")
        updateButton.clicked.connect(self._installUpdate)
        infoRow.addWidget(updateButton)
        infoRow.addStretch()
        versionLabel = QLabel(f"{APP_NAME} v{VERSION}")
        versionLabel.setObjectName("small")
        infoRow.addWidget(versionLabel)
        layout.addLayout(infoRow)
        for button in self.findChildren(QPushButton):
            button.setMinimumWidth(button.sizeHint().width())
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancelButton = QPushButton("Annulla")
        cancelButton.clicked.connect(self.reject)
        saveButton = QPushButton("Salva")
        saveButton.setObjectName("accent")
        saveButton.clicked.connect(self._save)
        buttons.addWidget(cancelButton)
        buttons.addWidget(saveButton)
        layout.addLayout(buttons)

    def _installUpdate(self):
        filePath, _ = QFileDialog.getOpenFileName(self, "Scegli il file di aggiornamento", os.path.expanduser("~/Downloads"),
                                                  "Installer Sonus (Sonus_Setup*.exe);;Programmi (*.exe)")
        if not filePath:
            return
        answer = QMessageBox.question(self, APP_NAME, "Sonus si chiuderà, si aggiornerà e si riaprirà da solo. Continuare?\n"
                                                      "Le tue playlist e canzoni non verranno toccate.")
        if answer != QMessageBox.Yes:
            return
        from .. import app_updater
        problem = app_updater.launchInstaller(filePath)
        if problem:
            QMessageBox.warning(self, APP_NAME, f"Impossibile avviare l'aggiornamento:\n{problem}")
            return
        self.accept()
        if self.parent():
            self.parent().close()

    VIDEO_FPS = ((0, "Automatico (12, 25 a schermo intero)"), (15, "15"), (24, "24"), (30, "30"), (60, "60"))

    COLOR_FIELDS = (("accent", "Accento"), ("background", "Sfondo pagine"), ("panel", "Pannelli"),
                    ("sidebar", "Barra e menu laterale"), ("text", "Testo"))

    def _buildAppearanceTab(self):
        from . import theme
        page = QWidget()
        column = QVBoxLayout(page)
        column.setSpacing(12)
        hint = QLabel("Scegli i colori principali. Si applicano riavviando l'app (lo fa da sola).")
        hint.setObjectName("small")
        hint.setWordWrap(True)
        column.addWidget(hint)
        self.chosenColors = dict(settings.get("themeColors") or {})
        self.colorButtons = {}
        colorForm = QFormLayout()
        colorForm.setSpacing(10)
        for key, label in self.COLOR_FIELDS:
            button = QPushButton()
            button.setFixedSize(120, 30)
            button.clicked.connect(lambda checked=False, colorKey=key: self._pickColor(colorKey))
            self.colorButtons[key] = button
            colorForm.addRow(label, button)
        column.addLayout(colorForm)
        presetLabel = QLabel("Temi pronti")
        presetLabel.setObjectName("sub")
        column.addWidget(presetLabel)
        presetGrid = QGridLayout()
        presetGrid.setSpacing(8)
        for index, (name, colors) in enumerate(theme.COLOR_PRESETS.items()):
            presetButton = QPushButton(name)
            swatch = QColor(colors.get("accent", theme.DEFAULT_COLORS["accent"]))
            presetButton.setStyleSheet(f"QPushButton {{ border-left: 6px solid {swatch.name()}; }}")
            presetButton.clicked.connect(lambda checked=False, preset=colors: self._applyPreset(preset))
            presetGrid.addWidget(presetButton, index // 4, index % 4)
        column.addLayout(presetGrid)
        resetButton = QPushButton("Ripristina colori originali")
        resetButton.clicked.connect(lambda: self._applyPreset({}))
        column.addWidget(resetButton, 0, Qt.AlignLeft)
        column.addStretch()
        self._refreshColorButtons()
        return page

    def _currentColor(self, key):
        from . import theme
        return self.chosenColors.get(key) or theme.DEFAULT_COLORS[key]

    def _refreshColorButtons(self):
        for key, button in self.colorButtons.items():
            color = QColor(self._currentColor(key))
            textColor = "#000000" if color.lightnessF() > 0.55 else "#FFFFFF"
            button.setText(color.name().upper())
            button.setStyleSheet(f"QPushButton {{ background: {color.name()}; color: {textColor}; border: 1px solid #555; border-radius: 6px; }}")

    def _pickColor(self, key):
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(QColor(self._currentColor(key)), self, "Scegli un colore")
        if color.isValid():
            self.chosenColors[key] = color.name().upper()
            self._refreshColorButtons()

    def _applyPreset(self, preset):
        self.chosenColors = dict(preset)
        self._refreshColorButtons()

    def _buildEffectsTab(self):
        page = QWidget()
        column = QVBoxLayout(page)
        column.setSpacing(10)
        self.effectChecks = {}
        for key, text in (("fxTransitions", "Transizioni: pagine che sfumano, popup morbidi, card che si illuminano, bottoni che rimbalzano"),
                          ("fxCoverColors", "Colori della canzone: la barra e \"In riproduzione\" cambiano colore con la canzone"),
                          ("fxVisualizer", "Visualizer: barre che si muovono a ritmo"),
                          ("fxMicro", "Micro-effetti: cuore che esplode al like, copertina che pulsa sui bassi"),
                          ("fxSongFade", "Dissolvenza tra canzoni (fade-in all'inizio, fade-out alla fine)")):
            check = QCheckBox(text)
            check.setChecked(bool(settings.get(key)))
            self.effectChecks[key] = check
            column.addWidget(check)
            if key == "fxCoverColors":
                column.addLayout(self._buildSongColorRow())
        column.addStretch()
        return page

    def _buildSongColorRow(self):
        row = QHBoxLayout()
        row.setContentsMargins(24, 0, 0, 0)
        row.addWidget(QLabel("Prendi i colori da:"))
        self.songColorCombo = QComboBox()
        for value, text in (("cover", "Copertina"), ("custom", "Colore scelto da me"), ("video", "Video")):
            self.songColorCombo.addItem(text, value)
        self.songColorCombo.setCurrentIndex(max(0, self.songColorCombo.findData(settings.get("songColorSource"))))
        self.chosenSongColor = settings.get("songColorCustom") or "#1ED760"
        self.songColorButton = QPushButton()
        self.songColorButton.setFixedSize(120, 30)
        self.songColorButton.clicked.connect(self._pickSongColor)
        self.songColorCombo.currentIndexChanged.connect(self._refreshSongColorButton)
        row.addWidget(self.songColorCombo)
        row.addWidget(self.songColorButton)
        row.addStretch()
        self._refreshSongColorButton()
        return row

    def _refreshSongColorButton(self):
        color = QColor(self.chosenSongColor)
        textColor = "#000000" if color.lightnessF() > 0.55 else "#FFFFFF"
        self.songColorButton.setText(color.name().upper())
        self.songColorButton.setStyleSheet(f"QPushButton {{ background: {color.name()}; color: {textColor}; border: 1px solid #555; border-radius: 6px; }}")
        self.songColorButton.setVisible(self.songColorCombo.currentData() == "custom")

    def _pickSongColor(self):
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(QColor(self.chosenSongColor), self, "Scegli un colore")
        if color.isValid():
            self.chosenSongColor = color.name().upper()
            self._refreshSongColorButton()

    def _editProfile(self):
        from .together_popup import ProfileDialog
        if ProfileDialog(self).exec() == ProfileDialog.Accepted and self.parent() is not None and hasattr(self.parent(), "together"):
            self.parent().together.updateProfile()

    def _browse(self):
        folderPath = QFileDialog.getExistingDirectory(self, "Scegli cartella musica", self.folderEdit.text())
        if folderPath:
            self.folderEdit.setText(folderPath)

    def _save(self):
        settings.set("musicDir", self.folderEdit.text().strip())
        settings.set("audioQuality", self.qualityCombo.currentText())
        settings.set("searchResults", self.resultsSpin.value())
        settings.set("copyImported", self.copyCheck.isChecked())
        settings.set("autoVideo", self.autoVideoCheck.isChecked())
        settings.set("streamOnly", self.streamOnlyCheck.isChecked())
        settings.set("streamVideo", self.streamVideoCheck.isChecked())
        for key, check in self.effectChecks.items():
            settings.set(key, check.isChecked())
        settings.set("songColorSource", self.songColorCombo.currentData())
        settings.set("songColorCustom", self.chosenSongColor)
        colorsChanged = (settings.get("themeColors") or {}) != self.chosenColors
        settings.set("themeColors", dict(self.chosenColors))
        self.restartForColors = colorsChanged
        settings.set("discordPresence", self.discordCheck.isChecked())
        settings.set("discordClientId", "".join(character for character in self.discordIdEdit.text() if character.isdigit()))
        settings.set("videoQuality", self.videoQualityCombo.currentText())
        settings.set("videoFps", int(self.videoFpsCombo.currentData() or 0))
        settings.set("autoLyrics", self.autoLyricsCheck.isChecked())
        settings.set("pauseVideoInBackground", self.pauseVideoCheck.isChecked())
        settings.set("autoCheckUpdates", self.autoUpdateCheck.isChecked())
        settings.musicDir()
        settings.save()
        self.accept()


class VideoSearchDialog(QDialog):
    def __init__(self, parent, song):
        super().__init__(parent)
        self.setWindowTitle("Scegli il video")
        self.resize(760, 560)
        self.selectedEntry = None
        self.serial = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        titleLabel = QLabel("Scegli il video")
        titleLabel.setObjectName("h2")
        layout.addWidget(titleLabel)
        hint = QLabel("Puoi usare qualsiasi video: il video ufficiale, un live, un edit... L'audio resta quello della canzone.")
        hint.setObjectName("small")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        searchRow = QHBoxLayout()
        self.searchEdit = QLineEdit(f"{song.get('artist') or ''} {song.get('title') or ''} official video".strip())
        self.searchEdit.setPlaceholderText("Cerca un video o incolla un link YouTube")
        self.searchEdit.returnPressed.connect(self.search)
        searchButton = QPushButton("Cerca")
        searchButton.setObjectName("accent")
        searchButton.clicked.connect(self.search)
        searchRow.addWidget(self.searchEdit, 1)
        searchRow.addWidget(searchButton)
        layout.addLayout(searchRow)
        self.statusLabel = QLabel("")
        self.statusLabel.setObjectName("sub")
        layout.addWidget(self.statusLabel)
        self.resultList = QListWidget()
        self.resultList.setIconSize(QSize(128, 72))
        self.resultList.setSelectionMode(QAbstractItemView.SingleSelection)
        self.resultList.itemDoubleClicked.connect(lambda item: self._choose())
        layout.addWidget(self.resultList, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancelButton = QPushButton("Annulla")
        cancelButton.clicked.connect(self.reject)
        chooseButton = QPushButton("Usa questo video")
        chooseButton.setObjectName("accent")
        chooseButton.clicked.connect(self._choose)
        buttons.addWidget(cancelButton)
        buttons.addWidget(chooseButton)
        layout.addLayout(buttons)
        self.search()

    def search(self):
        from .. import downloader
        query = self.searchEdit.text().strip()
        if not query:
            return
        self.serial += 1
        serial = self.serial
        self.resultList.clear()
        self.statusLabel.setText("Ricerca in corso...")
        runInBackground(downloader.searchYoutube, query, 15,
                        onFinished=lambda result: self._onResults(serial, result),
                        onError=lambda message: self.statusLabel.setText(f"Errore: {message}"))

    def _onResults(self, serial, result):
        if serial != self.serial:
            return
        from .. import downloader
        entries = result["entries"]
        self.statusLabel.setText("" if entries else "Nessun risultato")
        for entry in entries:
            details = entry["channel"] + (f"  ·  {theme.formatTime(entry['duration'] * 1000)}" if entry.get("duration") else "")
            item = QListWidgetItem(f"{entry['title']}\n{details}")
            item.setData(Qt.UserRole, entry)
            item.setSizeHint(QSize(100, 82))
            self.resultList.addItem(item)
            if entry.get("thumbnail"):
                def onLoaded(data, listItem=item):
                    pixmap = QPixmap()
                    if pixmap.loadFromData(data):
                        try:
                            listItem.setIcon(QIcon(pixmap.scaled(128, 72, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
                        except RuntimeError:
                            pass
                runInBackground(downloader.fetchBytes, entry["thumbnail"], onFinished=onLoaded)
        if entries:
            self.resultList.setCurrentRow(0)

    def _choose(self):
        item = self.resultList.currentItem()
        if item:
            self.selectedEntry = item.data(Qt.UserRole)
            self.accept()


class LyricsEditDialog(QDialog):
    def __init__(self, parent, song):
        super().__init__(parent)
        self.setWindowTitle("Testo della canzone")
        self.resize(560, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)
        titleLabel = QLabel(f"Testo — {song.get('title')}")
        titleLabel.setObjectName("h2")
        layout.addWidget(titleLabel)
        hint = QLabel("Incolla il testo normale, oppure un testo sincronizzato in formato LRC ([00:12.34] riga...).")
        hint.setObjectName("small")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.textEdit = QPlainTextEdit(song.get("syncedLyrics") or song.get("lyrics") or "")
        layout.addWidget(self.textEdit, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancelButton = QPushButton("Annulla")
        cancelButton.clicked.connect(self.reject)
        saveButton = QPushButton("Salva")
        saveButton.setObjectName("accent")
        saveButton.clicked.connect(self.accept)
        buttons.addWidget(cancelButton)
        buttons.addWidget(saveButton)
        layout.addLayout(buttons)

    def values(self):
        from ..lyrics import LRC_LINE, parseSynced
        text = self.textEdit.toPlainText().strip()
        if parseSynced(text):
            plain = "\n".join(LRC_LINE.sub("", line).strip() for line in text.splitlines() if LRC_LINE.search(line))
            return plain, text
        return text, ""


class LyricsSearchDialog(QDialog):
    def __init__(self, parent, song):
        super().__init__(parent)
        from .. import lyrics as lyricsModule
        self.lyricsModule = lyricsModule
        self.song = song
        self.selected = None
        self.serial = 0
        self.setWindowTitle("Cerca il testo")
        self.resize(940, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        titleLabel = QLabel("Cerca il testo")
        titleLabel.setObjectName("h2")
        layout.addWidget(titleLabel)
        hint = QLabel("Scrivi artista e titolo come vuoi, scegli un risultato e controlla l'anteprima. "
                      "\u23f1 = testo sincronizzato (scorre con la musica).")
        hint.setObjectName("small")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        searchRow = QHBoxLayout()
        self.searchEdit = QLineEdit(lyricsModule.defaultQuery(song.get("title") or "", song.get("artist") or ""))
        self.searchEdit.setPlaceholderText("Artista e titolo")
        self.searchEdit.returnPressed.connect(self.search)
        searchButton = QPushButton("Cerca")
        searchButton.setObjectName("accent")
        searchButton.clicked.connect(self.search)
        searchRow.addWidget(self.searchEdit, 1)
        searchRow.addWidget(searchButton)
        layout.addLayout(searchRow)
        self.statusLabel = QLabel("")
        self.statusLabel.setObjectName("sub")
        layout.addWidget(self.statusLabel)
        body = QHBoxLayout()
        body.setSpacing(12)
        self.resultList = QListWidget()
        self.resultList.currentItemChanged.connect(self._onSelected)
        self.resultList.itemDoubleClicked.connect(lambda item: self._choose())
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Anteprima del testo")
        body.addWidget(self.resultList, 5)
        body.addWidget(self.preview, 4)
        layout.addLayout(body, 1)
        buttons = QHBoxLayout()
        pasteButton = QPushButton("Scrivi / incolla a mano...")
        pasteButton.clicked.connect(lambda: self.done(2))
        buttons.addWidget(pasteButton)
        buttons.addStretch()
        cancelButton = QPushButton("Annulla")
        cancelButton.clicked.connect(self.reject)
        self.chooseButton = QPushButton("Usa questo testo")
        self.chooseButton.setObjectName("accent")
        self.chooseButton.setEnabled(False)
        self.chooseButton.clicked.connect(self._choose)
        buttons.addWidget(cancelButton)
        buttons.addWidget(self.chooseButton)
        layout.addLayout(buttons)
        self.search()

    def search(self):
        query = self.searchEdit.text().strip()
        if not query:
            return
        self.serial += 1
        serial = self.serial
        self.resultList.clear()
        self.preview.clear()
        self.chooseButton.setEnabled(False)
        self.statusLabel.setText("Ricerca in corso...")
        runInBackground(self.lyricsModule.searchLyrics, query, self.song.get("duration") or 0,
                        onFinished=lambda results: self._onResults(serial, results),
                        onError=lambda message: serial == self.serial and self.statusLabel.setText(
                            "Servizio testi non raggiungibile, riprova tra poco" if "503" in message or "Down" in message
                            else f"Errore: {message[:120]}"))

    def _onResults(self, serial, results):
        if serial != self.serial:
            return
        self.statusLabel.setText(f"{len(results)} risultati" if results else "Nessun risultato: prova a cambiare le parole")
        for result in results:
            duration = theme.formatTime(result["duration"] * 1000) if result["duration"] else "--:--"
            badge = "\u23f1  " if result["synced"] else ""
            details = "  ·  ".join(part for part in (result["artist"], result["album"], duration) if part)
            item = QListWidgetItem(f"{badge}{result['title']}\n{details}")
            item.setData(Qt.UserRole, result)
            item.setSizeHint(QSize(100, 54))
            self.resultList.addItem(item)
        if results:
            self.resultList.setCurrentRow(0)

    def _onSelected(self, item, previous=None):
        result = item.data(Qt.UserRole) if item else None
        self.chooseButton.setEnabled(result is not None)
        self.preview.setPlainText(result["plain"] if result else "")

    def _choose(self):
        item = self.resultList.currentItem()
        if item:
            self.selected = item.data(Qt.UserRole)
            self.accept()
