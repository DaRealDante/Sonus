from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import theme
from .equalizer_page import EqSlider

DEFAULT_EFFECTS = {"rate": 1.0, "keepPitch": True, "reverbWet": 0.0, "reverbSize": 1.8, "bassBoost": 0.0}
BASS_BOOST_MAX_DB = 12

PRESETS = [
    ("Normale", {"rate": 1.0, "keepPitch": True, "reverbWet": 0.0}),
    ("Slowed + Reverb", {"rate": 0.85, "keepPitch": False, "reverbWet": 0.45, "reverbSize": 3.0}),
    ("Sped up", {"rate": 1.25, "keepPitch": False, "reverbWet": 0.0}),
    ("Nightcore", {"rate": 1.35, "keepPitch": False, "reverbWet": 0.1, "reverbSize": 1.2}),
]


class EffectsPopup(QFrame):
    """Speed / pitch / reverb for the current song. Every change is applied live and saved for that song."""

    effectsChanged = Signal(dict)
    exportRequested = Signal()
    resetRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("effectsPopup")
        self.setStyleSheet(f"QFrame#effectsPopup {{ background: {theme.ELEVATED}; border: 1px solid #3A3A3A; border-radius: 10px; }}")
        self.setFixedWidth(380)
        self.updating = False
        self.emitTimer = QTimer(self)
        self.emitTimer.setSingleShot(True)
        self.emitTimer.setInterval(250)
        self.emitTimer.timeout.connect(lambda: self.effectsChanged.emit(self.values()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        self.titleLabel = QLabel("Velocità ed effetti")
        self.titleLabel.setObjectName("h3")
        layout.addWidget(self.titleLabel)
        self.songLabel = QLabel("")
        self.songLabel.setObjectName("small")
        layout.addWidget(self.songLabel)

        presetGrid = QGridLayout()
        presetGrid.setSpacing(6)
        for index, (name, values) in enumerate(PRESETS):
            button = QPushButton(name)
            button.setStyleSheet("padding: 5px 8px; font-size: 9pt;")
            button.clicked.connect(lambda checked=False, preset=values: self.applyPreset(preset))
            presetGrid.addWidget(button, index // 2, index % 2)
        layout.addLayout(presetGrid)

        speedRow = QHBoxLayout()
        speedRow.addWidget(QLabel("Velocità"))
        speedRow.addStretch()
        self.speedLabel = QLabel("1.00x")
        self.speedLabel.setObjectName("h3")
        speedRow.addWidget(self.speedLabel)
        layout.addLayout(speedRow)
        self.speedSlider = EqSlider(Qt.Horizontal)
        self.speedSlider.setRange(50, 200)
        self.speedSlider.setValue(100)
        self.speedSlider.setToolTip("Doppio click = 1.00x")
        self.speedSlider.mouseDoubleClickEvent = lambda event: self.speedSlider.setValue(100)
        self.speedSlider.zeroValue = 100
        self.speedSlider.valueChanged.connect(self._onChanged)
        layout.addWidget(self.speedSlider)
        self.pitchCheck = QCheckBox("Mantieni il pitch (voce naturale)")
        self.pitchCheck.setChecked(True)
        self.pitchCheck.toggled.connect(self._onChanged)
        layout.addWidget(self.pitchCheck)

        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background: #3A3A3A;")
        layout.addWidget(separator)

        bassRow = QHBoxLayout()
        bassRow.addWidget(QLabel("Bass boost"))
        bassRow.addStretch()
        self.bassLabel = QLabel("Spento")
        self.bassLabel.setObjectName("h3")
        bassRow.addWidget(self.bassLabel)
        layout.addLayout(bassRow)
        self.bassSlider = EqSlider(Qt.Horizontal)
        self.bassSlider.setRange(0, 100)
        self.bassSlider.setValue(0)
        self.bassSlider.setToolTip("Doppio click = spento")
        self.bassSlider.mouseDoubleClickEvent = lambda event: self.bassSlider.setValue(0)
        self.bassSlider.valueChanged.connect(self._onChanged)
        layout.addWidget(self.bassSlider)

        reverbRow = QHBoxLayout()
        reverbRow.addWidget(QLabel("Reverb"))
        reverbRow.addStretch()
        self.reverbLabel = QLabel("Spento")
        self.reverbLabel.setObjectName("h3")
        reverbRow.addWidget(self.reverbLabel)
        layout.addLayout(reverbRow)
        self.reverbSlider = EqSlider(Qt.Horizontal)
        self.reverbSlider.setRange(0, 100)
        self.reverbSlider.setValue(0)
        self.reverbSlider.mouseDoubleClickEvent = lambda event: self.reverbSlider.setValue(0)
        self.reverbSlider.valueChanged.connect(self._onChanged)
        layout.addWidget(self.reverbSlider)
        sizeRow = QHBoxLayout()
        sizeRow.addWidget(QLabel("Grandezza stanza"))
        sizeRow.addStretch()
        self.sizeLabel = QLabel("")
        self.sizeLabel.setObjectName("small")
        sizeRow.addWidget(self.sizeLabel)
        layout.addLayout(sizeRow)
        self.sizeSlider = EqSlider(Qt.Horizontal)
        self.sizeSlider.setRange(3, 50)
        self.sizeSlider.setValue(18)
        self.sizeSlider.zeroValue = 3
        self.sizeSlider.valueChanged.connect(self._onChanged)
        layout.addWidget(self.sizeSlider)

        hint = QLabel("Le impostazioni si salvano da sole per questa canzone.")
        hint.setObjectName("small")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttonsRow = QHBoxLayout()
        resetButton = QPushButton("Ripristina")
        resetButton.clicked.connect(lambda: self.applyPreset(PRESETS[0][1] | {"reverbSize": 1.8, "bassBoost": 0.0}))
        exportButton = QPushButton("Salva come nuova canzone")
        exportButton.setObjectName("accent")
        exportButton.setToolTip("Crea un file con velocità ed effetti applicati")
        exportButton.clicked.connect(self.exportRequested)
        buttonsRow.addWidget(resetButton)
        buttonsRow.addStretch()
        buttonsRow.addWidget(exportButton)
        layout.addLayout(buttonsRow)
        self._refreshLabels()

    def setSong(self, song, effects):
        self.updating = True
        self.songLabel.setText((song.get("title") or "") if song else "Nessuna canzone")
        self.speedSlider.setValue(int(round(effects["rate"] * 100)))
        self.pitchCheck.setChecked(bool(effects["keepPitch"]))
        self.reverbSlider.setValue(int(round(effects["reverbWet"] * 100)))
        self.sizeSlider.setValue(int(round(effects["reverbSize"] * 10)))
        self.bassSlider.setValue(int(round(effects.get("bassBoost", 0.0) * 100)))
        self.updating = False
        self._refreshLabels()

    def values(self):
        return {
            "rate": self.speedSlider.value() / 100,
            "keepPitch": self.pitchCheck.isChecked(),
            "reverbWet": self.reverbSlider.value() / 100,
            "reverbSize": self.sizeSlider.value() / 10,
            "bassBoost": self.bassSlider.value() / 100,
        }

    def applyPreset(self, preset):
        values = dict(DEFAULT_EFFECTS) | self.values() | preset
        self.updating = True
        self.speedSlider.setValue(int(round(values["rate"] * 100)))
        self.pitchCheck.setChecked(bool(values["keepPitch"]))
        self.reverbSlider.setValue(int(round(values["reverbWet"] * 100)))
        self.sizeSlider.setValue(int(round(values["reverbSize"] * 10)))
        self.bassSlider.setValue(int(round(values.get("bassBoost", 0.0) * 100)))
        self.updating = False
        self._refreshLabels()
        self.emitTimer.stop()
        self.effectsChanged.emit(self.values())

    def _refreshLabels(self):
        values = self.values()
        self.speedLabel.setText(f"{values['rate']:.2f}x")
        self.reverbLabel.setText("Spento" if values["reverbWet"] <= 0 else f"{int(values['reverbWet'] * 100)}%")
        self.sizeLabel.setText(f"{values['reverbSize']:.1f} s")
        self.bassLabel.setText("Spento" if values["bassBoost"] <= 0 else f"+{values['bassBoost'] * BASS_BOOST_MAX_DB:.1f} dB")
        for slider in (self.speedSlider, self.reverbSlider, self.sizeSlider, self.bassSlider):
            slider.update()

    def _onChanged(self, *args):
        self._refreshLabels()
        if not self.updating:
            self.emitTimer.start()

    def showBelow(self, anchor):
        self.adjustSize()
        position = anchor.mapToGlobal(anchor.rect().topLeft())
        self.move(position.x() + anchor.width() - self.width(), position.y() - self.height() - 8)
        from .effects import popIn
        popIn(self)
        self.show()
