from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme

HANDLE_GRAB_PX = 8


class WaveformWidget(QWidget):
    selectionChanged = Signal(int, int)
    seekRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peaks = None
        self.durationMs = 0
        self.selection = None
        self.regions = []
        self.playheadMs = 0
        self.viewStart = 0
        self.viewEnd = 0
        self.message = "Caricamento forma d'onda..."
        self.dragMode = None
        self.dragOriginMs = 0
        self.pressPos = None
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)

    # ---------- data ----------
    def setData(self, peaks, durationMs):
        self.peaks = peaks
        self.durationMs = max(1, int(durationMs))
        self.viewStart = 0
        self.viewEnd = self.durationMs
        self.message = ""
        self.update()

    def setMessage(self, text):
        self.message = text
        self.update()

    def clear(self):
        self.peaks = None
        self.selection = None
        self.regions = []
        self.message = "Caricamento forma d'onda..."
        self.update()

    def setSelection(self, startMs, endMs, emit=False):
        if startMs is None:
            self.selection = None
        else:
            startMs, endMs = sorted((int(startMs), int(endMs)))
            if self.durationMs:
                startMs = max(0, min(startMs, self.durationMs))
                endMs = max(0, min(endMs, self.durationMs))
            self.selection = (startMs, endMs)
            if emit:
                self.selectionChanged.emit(startMs, endMs)
        self.update()

    def setRegions(self, regions):
        self.regions = regions
        self.update()

    def setPlayhead(self, positionMs):
        self.playheadMs = positionMs
        self.update()

    def resetZoom(self):
        self.viewStart, self.viewEnd = 0, self.durationMs
        self.update()

    # ---------- geometry ----------
    def _waveRect(self):
        return QRectF(0, 0, self.width(), self.height() - 18)

    def _msToX(self, positionMs):
        span = max(1, self.viewEnd - self.viewStart)
        return (positionMs - self.viewStart) / span * self.width()

    def _xToMs(self, xPosition):
        span = max(1, self.viewEnd - self.viewStart)
        return int(max(0, min(self.durationMs, self.viewStart + xPosition / max(1, self.width()) * span)))

    # ---------- painting ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        waveRect = self._waveRect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1A1A1A"))
        painter.drawRoundedRect(waveRect, 8, 8)
        if self.peaks is None or not self.durationMs:
            painter.setPen(QColor(theme.SUBTEXT))
            painter.drawText(waveRect, Qt.AlignCenter, self.message)
            return

        for region in self.regions:
            startX, endX = self._msToX(region["startMs"]), self._msToX(region["endMs"])
            color = QColor(theme.ACCENT if region.get("active") else "#7B61FF")
            color.setAlpha(70 if region.get("active") else 40)
            painter.fillRect(QRectF(startX, waveRect.top(), endX - startX, waveRect.height()), color)

        if self.selection:
            startX, endX = self._msToX(self.selection[0]), self._msToX(self.selection[1])
            painter.fillRect(QRectF(startX, waveRect.top(), endX - startX, waveRect.height()), QColor(255, 255, 255, 38))

        middle = waveRect.center().y()
        halfHeight = waveRect.height() / 2 - 6
        peakCount = len(self.peaks)
        barStep = 3
        for xPosition in range(0, self.width(), barStep):
            positionMs = self._xToMs(xPosition)
            nextMs = self._xToMs(xPosition + barStep)
            firstIndex = int(positionMs / self.durationMs * (peakCount - 1))
            lastIndex = max(firstIndex + 1, int(nextMs / self.durationMs * (peakCount - 1)))
            value = float(self.peaks[firstIndex:lastIndex].max()) if lastIndex > firstIndex else float(self.peaks[min(firstIndex, peakCount - 1)])
            barHeight = max(1.0, value * halfHeight)
            inSelection = self.selection and self.selection[0] <= positionMs <= self.selection[1]
            played = positionMs <= self.playheadMs
            if inSelection:
                color = QColor(theme.ACCENT)
            elif played:
                color = QColor("#E0E0E0")
            else:
                color = QColor("#5A5A5A")
            painter.fillRect(QRectF(xPosition, middle - barHeight, barStep - 1, barHeight * 2), color)

        if self.selection:
            painter.setPen(QPen(QColor(theme.ACCENT), 2))
            for edgeMs in self.selection:
                edgeX = self._msToX(edgeMs)
                painter.drawLine(QPointF(edgeX, waveRect.top()), QPointF(edgeX, waveRect.bottom()))
                painter.setBrush(QColor(theme.ACCENT))
                painter.drawRoundedRect(QRectF(edgeX - 5, waveRect.top(), 10, 14), 3, 3)

        playheadX = self._msToX(self.playheadMs)
        painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
        painter.drawLine(QPointF(playheadX, waveRect.top()), QPointF(playheadX, waveRect.bottom()))

        painter.setPen(QColor(theme.SUBTEXT))
        smallFont = QFont(self.font())
        smallFont.setPointSizeF(8)
        painter.setFont(smallFont)
        span = self.viewEnd - self.viewStart
        tickCount = max(2, self.width() // 110)
        for tickIndex in range(tickCount + 1):
            tickMs = self.viewStart + span * tickIndex / tickCount
            tickX = self._msToX(tickMs)
            alignment = Qt.AlignLeft if tickIndex == 0 else (Qt.AlignRight if tickIndex == tickCount else Qt.AlignHCenter)
            textRect = QRectF(tickX - 50 if alignment != Qt.AlignLeft else tickX, waveRect.bottom() + 2, 100 if alignment == Qt.AlignHCenter else 50, 16)
            if alignment == Qt.AlignRight:
                textRect = QRectF(tickX - 50, waveRect.bottom() + 2, 50, 16)
            label = theme.formatTimePrecise(tickMs) if span < 20000 else theme.formatTime(tickMs)
            painter.drawText(textRect, alignment | Qt.AlignVCenter, label)

    # ---------- interaction ----------
    def _handleAt(self, xPosition):
        if not self.selection:
            return None
        if abs(self._msToX(self.selection[0]) - xPosition) <= HANDLE_GRAB_PX:
            return "start"
        if abs(self._msToX(self.selection[1]) - xPosition) <= HANDLE_GRAB_PX:
            return "end"
        return None

    def mousePressEvent(self, event):
        if self.peaks is None or event.button() != Qt.LeftButton:
            return
        xPosition = event.position().x()
        self.pressPos = event.position()
        handle = self._handleAt(xPosition)
        if handle:
            self.dragMode = handle
        else:
            self.dragMode = "pending"
            self.dragOriginMs = self._xToMs(xPosition)

    def mouseMoveEvent(self, event):
        xPosition = event.position().x()
        if self.dragMode is None:
            self.setCursor(Qt.SizeHorCursor if self._handleAt(xPosition) else Qt.IBeamCursor)
            return
        positionMs = self._xToMs(xPosition)
        if self.dragMode == "pending" and abs(event.position().x() - self.pressPos.x()) > 4:
            self.dragMode = "new"
        if self.dragMode == "new":
            self.setSelection(self.dragOriginMs, positionMs, emit=True)
        elif self.dragMode == "start" and self.selection:
            self.setSelection(min(positionMs, self.selection[1] - 10), self.selection[1], emit=True)
        elif self.dragMode == "end" and self.selection:
            self.setSelection(self.selection[0], max(positionMs, self.selection[0] + 10), emit=True)

    def mouseReleaseEvent(self, event):
        if self.dragMode == "pending":
            self.seekRequested.emit(self._xToMs(event.position().x()))
        self.dragMode = None

    def wheelEvent(self, event):
        if self.peaks is None:
            return
        delta = event.angleDelta().y() or event.angleDelta().x()
        span = self.viewEnd - self.viewStart
        if event.modifiers() & Qt.ShiftModifier or event.angleDelta().x():
            shift = -delta / 120 * span * 0.1
            newStart = max(0, min(self.durationMs - span, self.viewStart + shift))
            self.viewStart, self.viewEnd = newStart, newStart + span
        else:
            anchorMs = self._xToMs(event.position().x())
            factor = 0.8 if delta > 0 else 1.25
            newSpan = max(500, min(self.durationMs, span * factor))
            ratio = (anchorMs - self.viewStart) / max(1, span)
            newStart = max(0, min(self.durationMs - newSpan, anchorMs - ratio * newSpan))
            self.viewStart, self.viewEnd = newStart, newStart + newSpan
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.resetZoom()
