import math

import numpy
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QInputDialog, QMessageBox, QPushButton, QSizePolicy, QSlider,
    QVBoxLayout, QWidget,
)

from ..audio_engine import EQ_LABELS, EQ_PRESETS, eqResponse
from ..config import settings
from . import theme
from .views import Page, _label

GAIN_RANGE = 12.0
STEPS_PER_DB = 10
CUSTOM_PRESET = "Personalizzato"


class EqSlider(QSlider):
    def __init__(self, orientation=Qt.Vertical, parent=None):
        super().__init__(orientation, parent)
        self.setRange(int(-GAIN_RANGE * STEPS_PER_DB), int(GAIN_RANGE * STEPS_PER_DB))
        self.setCursor(Qt.PointingHandCursor)
        self.hovered = False
        if orientation == Qt.Vertical:
            self.setMinimumHeight(170)
            self.setFixedWidth(34)
        else:
            self.setFixedHeight(22)

    def enterEvent(self, event):
        self.hovered = True
        self.update()

    def leaveEvent(self, event):
        self.hovered = False
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.setValue(0)

    def _ratio(self, value):
        return (value - self.minimum()) / max(1, self.maximum() - self.minimum())

    def _valueFromPosition(self, position):
        margin = 8
        if self.orientation() == Qt.Vertical:
            ratio = 1 - (position.y() - margin) / max(1, self.height() - margin * 2)
        else:
            ratio = (position.x() - margin) / max(1, self.width() - margin * 2)
        ratio = max(0.0, min(1.0, ratio))
        return int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setSliderDown(True)
            self.setValue(self._valueFromPosition(event.position()))
            event.accept()

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.setValue(self._valueFromPosition(event.position()))

    def mouseReleaseEvent(self, event):
        self.setSliderDown(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        margin = 8
        active = self.isEnabled()
        accent = QColor(theme.ACCENT if active else theme.MUTED)
        zeroRatio = self._ratio(getattr(self, "zeroValue", 0))
        valueRatio = self._ratio(self.value())
        if self.orientation() == Qt.Vertical:
            centerX = self.width() / 2
            length = self.height() - margin * 2
            painter.setBrush(QColor("#3A3A3A"))
            painter.drawRoundedRect(QRectF(centerX - 2, margin, 4, length), 2, 2)
            zeroY = margin + (1 - zeroRatio) * length
            valueY = margin + (1 - valueRatio) * length
            painter.setBrush(QColor("#555"))
            painter.drawRect(QRectF(centerX - 7, zeroY - 0.5, 14, 1))
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(centerX - 2, min(zeroY, valueY), 4, abs(valueY - zeroY)), 2, 2)
            painter.setBrush(QColor(theme.TEXT if active else theme.SUBTEXT))
            radius = 8 if (self.hovered or self.isSliderDown()) else 7
            painter.drawEllipse(QPointF(centerX, valueY), radius, radius)
        else:
            centerY = self.height() / 2
            length = self.width() - margin * 2
            painter.setBrush(QColor("#3A3A3A"))
            painter.drawRoundedRect(QRectF(margin, centerY - 2, length, 4), 2, 2)
            zeroX = margin + zeroRatio * length
            valueX = margin + valueRatio * length
            painter.setBrush(QColor("#555"))
            painter.drawRect(QRectF(zeroX - 0.5, centerY - 7, 1, 14))
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(min(zeroX, valueX), centerY - 2, abs(valueX - zeroX), 4), 2, 2)
            painter.setBrush(QColor(theme.TEXT if active else theme.SUBTEXT))
            radius = 8 if (self.hovered or self.isSliderDown()) else 7
            painter.drawEllipse(QPointF(valueX, centerY), radius, radius)
        painter.end()


class ResponseCurve(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.frequencies = numpy.geomspace(20, 20000, 240)
        self.response = numpy.zeros(len(self.frequencies))
        self.enabledCurve = True

    def setCurve(self, gains, preampDb, enabled):
        try:
            self.response = eqResponse(gains, preampDb, self.frequencies)
        except Exception:
            self.response = numpy.zeros(len(self.frequencies))
        self.enabledCurve = enabled
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(44, 10, self.width() - 56, self.height() - 34)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1A1A1A"))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)
        smallFont = QFont(self.font())
        smallFont.setPointSizeF(8)
        painter.setFont(smallFont)
        maxDb = GAIN_RANGE * 1.5

        def toX(frequency):
            return rect.left() + (math.log10(frequency) - math.log10(20)) / (math.log10(20000) - math.log10(20)) * rect.width()

        def toY(decibels):
            decibels = max(-maxDb, min(maxDb, decibels))
            return rect.center().y() - decibels / maxDb * rect.height() / 2

        for decibels in (-18, -12, -6, 0, 6, 12, 18):
            yPosition = toY(decibels)
            painter.setPen(QPen(QColor("#3A3A3A" if decibels == 0 else "#262626"), 1))
            painter.drawLine(QPointF(rect.left(), yPosition), QPointF(rect.right(), yPosition))
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(QRectF(0, yPosition - 8, 38, 16), Qt.AlignRight | Qt.AlignVCenter, f"{decibels:+d}" if decibels else "0")
        for frequency, label in ((50, "50"), (100, "100"), (200, "200"), (500, "500"), (1000, "1K"), (2000, "2K"), (5000, "5K"), (10000, "10K")):
            xPosition = toX(frequency)
            painter.setPen(QPen(QColor("#262626"), 1))
            painter.drawLine(QPointF(xPosition, rect.top()), QPointF(xPosition, rect.bottom()))
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(QRectF(xPosition - 20, rect.bottom() + 4, 40, 16), Qt.AlignCenter, label)

        path = QPainterPath()
        fillPath = QPainterPath()
        zeroY = toY(0)
        for index, (frequency, decibels) in enumerate(zip(self.frequencies, self.response)):
            point = QPointF(toX(frequency), toY(float(decibels)))
            if index == 0:
                path.moveTo(point)
                fillPath.moveTo(QPointF(point.x(), zeroY))
            else:
                path.lineTo(point)
            fillPath.lineTo(point)
        fillPath.lineTo(QPointF(toX(self.frequencies[-1]), zeroY))
        fillPath.closeSubpath()
        color = QColor(theme.ACCENT if self.enabledCurve else theme.MUTED)
        gradient = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.bottom()))
        fillColor = QColor(color)
        fillColor.setAlpha(70)
        gradient.setColorAt(0, fillColor)
        fillColor.setAlpha(10)
        gradient.setColorAt(1, fillColor)
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(fillPath)
        painter.setPen(QPen(color, 2.2))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()


class EqualizerPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self.updating = False
        self.macroValues = {"bass": 0, "mid": 0, "treble": 0}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)

        headerRow = QHBoxLayout()
        headerRow.addWidget(_label("Equalizzatore", "h1"))
        headerRow.addStretch()
        self.enabledCheck = QCheckBox("Attivo")
        self.enabledCheck.setStyleSheet("font-weight: 700; font-size: 11pt;")
        self.enabledCheck.toggled.connect(self._apply)
        headerRow.addWidget(self.enabledCheck)
        layout.addLayout(headerRow)

        presetRow = QHBoxLayout()
        presetRow.setSpacing(8)
        presetRow.addWidget(_label("Preset", "sub"))
        self.presetCombo = QComboBox()
        self.presetCombo.setMinimumWidth(220)
        self.presetCombo.activated.connect(self._onPresetChosen)
        presetRow.addWidget(self.presetCombo)
        saveButton = QPushButton("Salva preset")
        saveButton.clicked.connect(self._savePreset)
        self.deleteButton = QPushButton("Elimina")
        self.deleteButton.clicked.connect(self._deletePreset)
        resetButton = QPushButton("Reset")
        resetButton.clicked.connect(lambda: self._loadGains(EQ_PRESETS["Piatto"], "Piatto", resetPreamp=True))
        presetRow.addWidget(saveButton)
        presetRow.addWidget(self.deleteButton)
        presetRow.addWidget(resetButton)
        presetRow.addStretch()
        layout.addLayout(presetRow)

        self.curve = ResponseCurve()
        layout.addWidget(self.curve)

        bandsCard = QFrame()
        bandsCard.setObjectName("eqCard")
        bandsCard.setStyleSheet(f"QFrame#eqCard {{ background: {theme.PANEL}; border-radius: 10px; }}")
        bandsLayout = QHBoxLayout(bandsCard)
        bandsLayout.setContentsMargins(16, 14, 16, 12)
        bandsLayout.setSpacing(4)
        self.preampSlider, preampColumn = self._bandColumn("Preamp")
        self.preampSlider.valueChanged.connect(self._apply)
        bandsLayout.addLayout(preampColumn)
        separator = QFrame()
        separator.setFixedWidth(1)
        separator.setStyleSheet("background: #333;")
        bandsLayout.addSpacing(10)
        bandsLayout.addWidget(separator)
        bandsLayout.addSpacing(10)
        self.bandSliders = []
        for label in EQ_LABELS:
            slider, column = self._bandColumn(label + " Hz" if not label.endswith("K") else label + "Hz")
            slider.valueChanged.connect(self._onBandMoved)
            self.bandSliders.append(slider)
            bandsLayout.addLayout(column, 1)
        layout.addWidget(bandsCard, 1)

        macroCard = QFrame()
        macroCard.setObjectName("macroCard")
        macroCard.setStyleSheet(f"QFrame#macroCard {{ background: {theme.PANEL}; border-radius: 10px; }}")
        macroLayout = QHBoxLayout(macroCard)
        macroLayout.setContentsMargins(16, 12, 16, 12)
        macroLayout.setSpacing(18)
        self.macroSliders = {}
        for key, text in (("bass", "Bassi"), ("mid", "Medi"), ("treble", "Alti")):
            column = QVBoxLayout()
            titleRow = QHBoxLayout()
            titleRow.addWidget(_label(text, "h3"))
            titleRow.addStretch()
            valueLabel = _label("0 dB", "small")
            titleRow.addWidget(valueLabel)
            slider = EqSlider(Qt.Horizontal)
            slider.valueChanged.connect(lambda value, k=key, lbl=valueLabel: self._onMacroMoved(k, value, lbl))
            column.addLayout(titleRow)
            column.addWidget(slider)
            macroLayout.addLayout(column, 1)
            self.macroSliders[key] = slider
        balanceColumn = QVBoxLayout()
        balanceRow = QHBoxLayout()
        balanceRow.addWidget(_label("Bilanciamento", "h3"))
        balanceRow.addStretch()
        self.balanceLabel = _label("Centro", "small")
        balanceRow.addWidget(self.balanceLabel)
        self.balanceSlider = EqSlider(Qt.Horizontal)
        self.balanceSlider.setRange(-100, 100)
        self.balanceSlider.valueChanged.connect(self._onBalance)
        balanceColumn.addLayout(balanceRow)
        balanceColumn.addWidget(self.balanceSlider)
        macroLayout.addLayout(balanceColumn, 1)
        layout.addWidget(macroCard)

        hint = _label("Doppio click su uno slider per azzerarlo. Se l'audio distorce con molti boost, abbassa il Preamp.", "small")
        layout.addWidget(hint)

        self._restore()

    def _bandColumn(self, label):
        column = QVBoxLayout()
        column.setSpacing(6)
        valueLabel = _label("0", "small")
        valueLabel.setAlignment(Qt.AlignCenter)
        slider = EqSlider(Qt.Vertical)
        slider.valueLabel = valueLabel
        slider.valueChanged.connect(lambda value, lbl=valueLabel: lbl.setText(f"{value / STEPS_PER_DB:+.1f}" if value else "0"))
        nameLabel = _label(label, "small")
        nameLabel.setAlignment(Qt.AlignCenter)
        column.addWidget(valueLabel)
        column.addWidget(slider, 1, Qt.AlignHCenter)
        column.addWidget(nameLabel)
        return slider, column

    # ---------- presets ----------
    def _customPresets(self):
        return dict(settings.get("eqCustomPresets") or {})

    def _fillPresets(self, selected):
        self.presetCombo.blockSignals(True)
        self.presetCombo.clear()
        for name in EQ_PRESETS:
            self.presetCombo.addItem(name)
        customPresets = self._customPresets()
        if customPresets:
            self.presetCombo.insertSeparator(self.presetCombo.count())
            for name in customPresets:
                self.presetCombo.addItem(theme.icon("heartFill", theme.ACCENT, 14), name)
        self.presetCombo.insertSeparator(self.presetCombo.count())
        self.presetCombo.addItem(CUSTOM_PRESET)
        index = self.presetCombo.findText(selected)
        self.presetCombo.setCurrentIndex(index if index >= 0 else self.presetCombo.count() - 1)
        self.presetCombo.blockSignals(False)
        self.deleteButton.setEnabled(selected in customPresets)

    def _onPresetChosen(self, index):
        name = self.presetCombo.itemText(index)
        gains = EQ_PRESETS.get(name) or self._customPresets().get(name)
        if gains is not None:
            self._loadGains(gains, name)

    def _loadGains(self, gains, presetName, resetPreamp=False):
        self.updating = True
        for slider, gain in zip(self.bandSliders, gains):
            slider.setValue(int(round(gain * STEPS_PER_DB)))
        if resetPreamp:
            self.preampSlider.setValue(0)
            self.balanceSlider.setValue(0)
        for slider in self.macroSliders.values():
            slider.setValue(0)
        self.macroValues = {key: 0 for key in self.macroValues}
        self.updating = False
        settings.set("eqPreset", presetName)
        self._fillPresets(presetName)
        if presetName != "Piatto" and not self.enabledCheck.isChecked():
            self.enabledCheck.setChecked(True)
        self._apply()

    def _savePreset(self):
        name, accepted = QInputDialog.getText(self, "Salva preset", "Nome del preset:")
        name = name.strip()
        if not accepted or not name:
            return
        if name in EQ_PRESETS or name == CUSTOM_PRESET:
            QMessageBox.warning(self, "Equalizzatore", "Questo nome è già usato da un preset di sistema.")
            return
        customPresets = self._customPresets()
        customPresets[name] = self.gains()
        settings.set("eqCustomPresets", customPresets)
        settings.set("eqPreset", name)
        settings.save()
        self._fillPresets(name)
        self.window.showStatus(f"Preset \"{name}\" salvato")

    def _deletePreset(self):
        name = self.presetCombo.currentText()
        customPresets = self._customPresets()
        if name in customPresets:
            del customPresets[name]
            settings.set("eqCustomPresets", customPresets)
            settings.set("eqPreset", CUSTOM_PRESET)
            settings.save()
            self._fillPresets(CUSTOM_PRESET)

    # ---------- values ----------
    def gains(self):
        return [slider.value() / STEPS_PER_DB for slider in self.bandSliders]

    def _onBandMoved(self):
        if self.updating:
            return
        current = self.presetCombo.currentText()
        expected = EQ_PRESETS.get(current) or self._customPresets().get(current)
        if expected is None or any(abs(a - b) > 0.05 for a, b in zip(expected, self.gains())):
            settings.set("eqPreset", CUSTOM_PRESET)
            self._fillPresets(CUSTOM_PRESET)
        self._apply()

    _MACRO_SHAPES = {
        "bass": [1.0, 1.0, 0.8, 0.4, 0.1, 0, 0, 0, 0, 0],
        "mid": [0, 0, 0, 0.3, 0.8, 1.0, 0.8, 0.3, 0, 0],
        "treble": [0, 0, 0, 0, 0, 0, 0.3, 0.7, 1.0, 1.0],
    }

    def _onMacroMoved(self, key, value, valueLabel):
        valueLabel.setText(f"{value / STEPS_PER_DB:+.1f} dB" if value else "0 dB")
        if self.updating:
            return
        delta = value - self.macroValues[key]
        self.macroValues[key] = value
        self.updating = True
        for slider, weight in zip(self.bandSliders, self._MACRO_SHAPES[key]):
            if weight:
                slider.setValue(int(round(slider.value() + delta * weight)))
        self.updating = False
        if not self.enabledCheck.isChecked() and value:
            self.enabledCheck.setChecked(True)
        self._onBandMoved()

    def _onBalance(self, value):
        self.balanceLabel.setText("Centro" if value == 0 else (f"S {abs(value)}%" if value < 0 else f"D {value}%"))
        self.window.player.mediaPlayer.setBalance(value / 100.0)
        settings.set("eqBalance", value)

    def _apply(self):
        if self.updating:
            return
        enabled = self.enabledCheck.isChecked()
        gains = self.gains()
        preampDb = self.preampSlider.value() / STEPS_PER_DB
        self.window.player.setEqualizer(gains, preampDb, enabled)
        self.curve.setCurve(gains, preampDb, enabled)
        for slider in self.bandSliders + [self.preampSlider]:
            slider.update()
        settings.set("eqEnabled", enabled)
        settings.set("eqGains", gains)
        settings.set("eqPreamp", preampDb)
        if hasattr(self.window, "playerBar"):
            self.window.playerBar.setEqActive(enabled and (any(abs(g) > 0.05 for g in gains) or abs(preampDb) > 0.05))

    def _restore(self):
        self.updating = True
        gains = settings.get("eqGains") or EQ_PRESETS["Piatto"]
        for slider, gain in zip(self.bandSliders, gains):
            slider.setValue(int(round(float(gain) * STEPS_PER_DB)))
        self.preampSlider.setValue(int(round(float(settings.get("eqPreamp") or 0) * STEPS_PER_DB)))
        self.enabledCheck.setChecked(bool(settings.get("eqEnabled")))
        self.updating = False
        self.balanceSlider.setValue(int(settings.get("eqBalance") or 0))
        self._fillPresets(settings.get("eqPreset") or "Piatto")
        self._apply()
