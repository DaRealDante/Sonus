import json
import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from .. import audio_tools
from ..config import APP_NAME, TEMP_DIR, settings
from ..workers import runInBackground
from . import theme
from .dialogs import TimeSpin

CLIP_COLORS = ["#1ED760", "#7B61FF", "#FF8A3D", "#2FA8FF", "#F15E6C", "#E5C03A", "#2FD4C4", "#C06BFF"]
RULER_H = 24
LANE_H = 96
LANE_GAP = 6
GRAB_PX = 7
SNAP_PX = 8
MIN_CLIP_MS = 100
PREVIEW_MS = 60000
TRANSITIONS = [
    ("Dissolvenza incrociata (crossfade)", "crossfade"),
    ("Sovrapposizione (volume pieno)", "overlap"),
    ("Taglio netto (nessuna transizione)", "cut"),
    ("Pausa (silenzio)", "gap"),
]


class MixClip:
    """One song in the mix: which part of it plays (startMs-endMs), where it sits in the mix (posMs), fades, volume."""

    FIELDS = ("startMs", "endMs", "posMs", "fadeInMs", "fadeOutMs", "volume")

    def __init__(self, song, colorIndex=0):
        self.song = song
        self.path = song["path"]
        self.durationMs = int((song.get("duration") or 0) * 1000) or 1000
        self.startMs = 0
        self.endMs = self.durationMs
        self.posMs = 0
        self.fadeInMs = 0
        self.fadeOutMs = 0
        self.volume = 100
        self.peaks = None
        self.color = CLIP_COLORS[colorIndex % len(CLIP_COLORS)]

    @property
    def lengthMs(self):
        return self.endMs - self.startMs

    @property
    def timelineEndMs(self):
        return self.posMs + self.lengthMs

    def params(self):
        return {name: getattr(self, name) for name in self.FIELDS}

    def restore(self, params):
        for name, value in params.items():
            setattr(self, name, value)

    def renderDict(self):
        return dict(self.params(), path=self.path)

    def clampFades(self):
        self.fadeInMs = max(0, min(int(self.fadeInMs), self.lengthMs))
        self.fadeOutMs = max(0, min(int(self.fadeOutMs), self.lengthMs))

    def gainAt(self, offsetMs):
        """Loudness (0-1.5) of the clip at offsetMs from its start, with fades and volume: what the waveform shows."""
        gain = self.volume / 100.0
        if self.fadeInMs and offsetMs < self.fadeInMs:
            gain *= math.sin(max(0.0, offsetMs) / self.fadeInMs * math.pi / 2)
        remaining = self.lengthMs - offsetMs
        if self.fadeOutMs and remaining < self.fadeOutMs:
            gain *= math.sin(max(0.0, remaining) / self.fadeOutMs * math.pi / 2)
        return gain


class MixTimeline(QWidget):
    """Lanes with the songs of the mix. Drag a song to move it, its edges to trim it, the round handles for fades."""

    selectionChanged = Signal(object)
    edited = Signal()
    editStarted = Signal()
    seekRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clips = []
        self.selected = None
        self.playheadMs = 0
        self.viewStart = 0.0
        self.viewEnd = 10000.0
        self.snapEnabled = True
        self.drag = None
        self.snapGuideMs = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMinimumHeight(RULER_H + LANE_H * 2 + 12)

    # ---------- geometry ----------
    def totalMs(self):
        return max((clip.timelineEndMs for clip in self.clips), default=0)

    def _pxPerMs(self):
        return self.width() / max(1.0, self.viewEnd - self.viewStart)

    def _msToX(self, positionMs):
        return (positionMs - self.viewStart) * self._pxPerMs()

    def _xToMs(self, xPosition):
        return self.viewStart + xPosition / max(0.0001, self._pxPerMs())

    def lanes(self):
        """Lane of every clip: songs that overlap in time go to different lanes."""
        laneEnds, result = [], {}
        for clip in sorted(self.clips, key=lambda item: item.posMs):
            for index, endMs in enumerate(laneEnds):
                if clip.posMs >= endMs:
                    laneEnds[index] = clip.timelineEndMs
                    result[clip] = index
                    break
            else:
                laneEnds.append(clip.timelineEndMs)
                result[clip] = len(laneEnds) - 1
        return result, max(2, len(laneEnds))

    def refreshLayout(self):
        self.setMinimumHeight(RULER_H + self.lanes()[1] * LANE_H + 12)

    def _clipRect(self, clip, lane):
        top = RULER_H + lane * LANE_H + LANE_GAP / 2
        return QRectF(self._msToX(clip.posMs), top, clip.lengthMs * self._pxPerMs(), LANE_H - LANE_GAP)

    def _paintOrder(self):
        return [clip for clip in self.clips if clip is not self.selected] + ([self.selected] if self.selected in self.clips else [])

    def fitAll(self):
        self.viewStart = 0.0
        self.viewEnd = max(5000.0, self.totalMs() * 1.04)
        self.update()

    def _setView(self, start, end):
        span = end - start
        if start < 0:
            start, end = 0.0, span
        self.viewStart, self.viewEnd = start, end
        self.update()

    def setPlayhead(self, positionMs):
        self.playheadMs = max(0, int(positionMs))
        self.update()

    def selectClip(self, clip):
        if clip is not self.selected:
            self.selected = clip
            self.selectionChanged.emit(clip)
        self.update()

    # ---------- snapping ----------
    def _snapPoints(self, exclude):
        points = [0, self.playheadMs]
        for clip in self.clips:
            if clip is not exclude:
                points += [clip.posMs, clip.timelineEndMs]
        return points

    def _snapActive(self):
        return self.snapEnabled and not (QGuiApplication.keyboardModifiers() & Qt.AltModifier)

    def _snapRange(self, positionMs, lengthMs, exclude):
        """A clip being moved: its start or its end snaps to the nearest edge of the other clips."""
        self.snapGuideMs = None
        if not self._snapActive():
            return positionMs
        tolerance = SNAP_PX / max(0.0001, self._pxPerMs())
        best = None
        for point in self._snapPoints(exclude):
            for edge in (positionMs, positionMs + lengthMs):
                difference = point - edge
                if abs(difference) <= tolerance and (best is None or abs(difference) < abs(best[0])):
                    best = (difference, point)
        if best:
            self.snapGuideMs = best[1]
            return positionMs + best[0]
        return positionMs

    def _snapValue(self, valueMs, exclude):
        return self._snapRange(valueMs, 0, exclude)

    # ---------- painting ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#161616"))
        laneMap, laneCount = self.lanes()
        for lane in range(laneCount):
            painter.fillRect(QRectF(0, RULER_H + lane * LANE_H, self.width(), LANE_H), QColor("#1B1B1B" if lane % 2 == 0 else "#171717"))
        self._paintRuler(painter)
        for clip in self._paintOrder():
            self._paintClip(painter, clip, laneMap[clip])
        self._paintOverlaps(painter, laneCount)
        if self.snapGuideMs is not None:
            painter.setPen(QPen(QColor(255, 255, 255, 170), 1, Qt.DashLine))
            guideX = self._msToX(self.snapGuideMs)
            painter.drawLine(QPointF(guideX, 0), QPointF(guideX, self.height()))
        playheadX = self._msToX(self.playheadMs)
        painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
        painter.drawLine(QPointF(playheadX, 0), QPointF(playheadX, self.height()))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPolygon([QPointF(playheadX - 5, 0), QPointF(playheadX + 5, 0), QPointF(playheadX, 8)])
        painter.end()

    def _paintRuler(self, painter):
        painter.fillRect(QRectF(0, 0, self.width(), RULER_H), QColor("#101010"))
        painter.setPen(QColor(theme.SUBTEXT))
        font = QFont(self.font())
        font.setPointSizeF(8)
        painter.setFont(font)
        step = 100
        for candidate in (100, 200, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000, 600000):
            step = candidate
            if candidate * self._pxPerMs() >= 80:
                break
        first = int(self.viewStart // step) * step
        positionMs = first
        while positionMs <= self.viewEnd:
            tickX = self._msToX(positionMs)
            painter.setPen(QColor("#3A3A3A"))
            painter.drawLine(QPointF(tickX, RULER_H - 7), QPointF(tickX, RULER_H))
            painter.setPen(QColor(theme.SUBTEXT))
            label = theme.formatTimePrecise(positionMs) if step < 1000 else theme.formatTime(positionMs)
            painter.drawText(QRectF(tickX + 3, 0, 80, RULER_H - 4), Qt.AlignLeft | Qt.AlignVCenter, label)
            positionMs += step

    def _paintClip(self, painter, clip, lane):
        rect = self._clipRect(clip, lane)
        if rect.right() < 0 or rect.left() > self.width():
            return
        selected = clip is self.selected
        outline = QPainterPath()
        outline.addRoundedRect(rect, 7, 7)
        base = QColor(clip.color)
        fill = QColor(base)
        fill.setAlpha(95 if selected else 60)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawPath(outline)
        painter.save()
        painter.setClipPath(outline)
        self._paintWave(painter, clip, rect, base)
        self._paintFadeShade(painter, clip, rect)
        painter.restore()
        painter.setPen(QPen(base if selected else QColor(base.red(), base.green(), base.blue(), 150), 2 if selected else 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(outline)
        # title
        painter.save()
        painter.setClipRect(rect.adjusted(6, 0, -6, 0))
        font = QFont(self.font())
        font.setPointSizeF(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        textLeft = max(rect.left(), 0) + 10
        painter.drawText(QRectF(textLeft, rect.top() + 14, max(10, rect.right() - textLeft - 6), 16), Qt.AlignLeft | Qt.AlignVCenter,
                         str(clip.song.get("title") or "")[:80])
        painter.restore()
        if rect.width() > 40:
            for handleX, active in ((rect.left() + clip.fadeInMs * self._pxPerMs(), clip.fadeInMs > 0),
                                    (rect.right() - clip.fadeOutMs * self._pxPerMs(), clip.fadeOutMs > 0)):
                painter.setPen(QPen(base, 2))
                painter.setBrush(QColor("#FFFFFF") if active or selected else QColor(255, 255, 255, 120))
                painter.drawEllipse(QPointF(handleX, rect.top() + 9), 4.5, 4.5)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 190))
            painter.drawRoundedRect(QRectF(rect.left() + 1, rect.center().y() - 14, 4, 28), 2, 2)
            painter.drawRoundedRect(QRectF(rect.right() - 5, rect.center().y() - 14, 4, 28), 2, 2)

    def _paintWave(self, painter, clip, rect, base):
        if clip.peaks is None or not len(clip.peaks):
            return
        peaks = clip.peaks
        middle = rect.top() + rect.height() / 2 + 8
        halfHeight = rect.height() / 2 - 14
        color = QColor(base)
        color.setAlpha(210)
        count = len(peaks)
        step = 3
        first = max(0, int(rect.left()))
        last = min(self.width(), int(rect.right()) + 1)
        for xPosition in range(first - first % step, last, step):
            offsetMs = self._xToMs(xPosition) - clip.posMs
            nextOffsetMs = self._xToMs(xPosition + step) - clip.posMs
            if offsetMs < 0 or offsetMs > clip.lengthMs:
                continue
            firstIndex = int((offsetMs + clip.startMs) / clip.durationMs * (count - 1))
            lastIndex = max(firstIndex + 1, int((nextOffsetMs + clip.startMs) / clip.durationMs * (count - 1)))
            firstIndex = max(0, min(firstIndex, count - 1))
            value = float(peaks[firstIndex:lastIndex].max()) if lastIndex > firstIndex else float(peaks[firstIndex])
            barHeight = max(1.0, value * halfHeight * min(1.2, clip.gainAt(offsetMs)))
            painter.fillRect(QRectF(xPosition, middle - barHeight, step - 1, barHeight * 2), color)

    def _paintFadeShade(self, painter, clip, rect):
        """Darkens the part of the song that the fades take away, so a fade is easy to see."""
        shade = QColor(0, 0, 0, 110)
        painter.setPen(Qt.NoPen)
        painter.setBrush(shade)
        for fadeMs, fromLeft in ((clip.fadeInMs, True), (clip.fadeOutMs, False)):
            width = fadeMs * self._pxPerMs()
            if width < 2:
                continue
            path = QPainterPath()
            bottom, top = rect.bottom(), rect.top()
            edgeX = rect.left() if fromLeft else rect.right()
            path.moveTo(edgeX, top)
            path.lineTo(edgeX, bottom)
            for index in range(0, 17):
                ratio = index / 16.0
                x = edgeX + width * ratio if fromLeft else edgeX - width * ratio
                path.lineTo(x, bottom - (bottom - top) * math.sin(ratio * math.pi / 2))
            path.closeSubpath()
            painter.drawPath(path)

    def _paintOverlaps(self, painter, laneCount):
        ordered = sorted(self.clips, key=lambda item: item.posMs)
        for firstIndex, first in enumerate(ordered):
            for second in ordered[firstIndex + 1:]:
                startMs = max(first.posMs, second.posMs)
                endMs = min(first.timelineEndMs, second.timelineEndMs)
                if endMs <= startMs:
                    continue
                left, right = self._msToX(startMs), self._msToX(endMs)
                painter.fillRect(QRectF(left, RULER_H, right - left, laneCount * LANE_H), QColor(255, 255, 255, 26))
                painter.setPen(QPen(QColor(255, 255, 255, 120), 1, Qt.DashLine))
                painter.drawLine(QPointF(left, RULER_H), QPointF(left, self.height()))
                painter.drawLine(QPointF(right, RULER_H), QPointF(right, self.height()))
                overlapMs = endMs - startMs
                matched = abs(first.fadeOutMs - overlapMs) < 60 and abs(second.fadeInMs - overlapMs) < 60
                text = f"{'Crossfade' if matched else 'Sovrapposti'} {overlapMs / 1000:.1f} s"
                font = QFont(self.font())
                font.setPointSizeF(8)
                font.setBold(True)
                painter.setFont(font)
                pill = QRectF((left + right) / 2 - 52, self.height() - 22, 104, 17)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 190))
                painter.drawRoundedRect(pill, 8, 8)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(pill, Qt.AlignCenter, text)

    # ---------- interaction ----------
    def _hit(self, position):
        laneMap, _ = self.lanes()
        for clip in reversed(self._paintOrder()):
            rect = self._clipRect(clip, laneMap[clip])
            if not rect.contains(position):
                continue
            if abs(position.y() - (rect.top() + 9)) <= 9:
                if abs(position.x() - (rect.left() + clip.fadeInMs * self._pxPerMs())) <= 9:
                    return clip, "fadeIn"
                if abs(position.x() - (rect.right() - clip.fadeOutMs * self._pxPerMs())) <= 9:
                    return clip, "fadeOut"
            if position.x() - rect.left() <= GRAB_PX:
                return clip, "trimStart"
            if rect.right() - position.x() <= GRAB_PX:
                return clip, "trimEnd"
            return clip, "move"
        return None, None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        position = event.position()
        if position.y() < RULER_H:
            self.drag = {"mode": "scrub"}
            self.seekRequested.emit(max(0, int(self._xToMs(position.x()))))
            return
        clip, part = self._hit(position)
        if clip is None:
            self.selectClip(None)
            self.drag = {"mode": "scrub"}
            self.seekRequested.emit(max(0, int(self._xToMs(position.x()))))
            return
        self.selectClip(clip)
        self.drag = {
            "mode": part, "clip": clip, "x0": position.x(), "orig": clip.params(), "started": False,
            "ripple": bool(event.modifiers() & Qt.ShiftModifier),
            "others": {other: other.posMs for other in self.clips if other is not clip},
        }

    def mouseMoveEvent(self, event):
        position = event.position()
        if self.drag is None:
            _, part = self._hit(position) if position.y() >= RULER_H else (None, None)
            self.setCursor({"move": Qt.SizeAllCursor, "trimStart": Qt.SizeHorCursor, "trimEnd": Qt.SizeHorCursor,
                            "fadeIn": Qt.PointingHandCursor, "fadeOut": Qt.PointingHandCursor}.get(part, Qt.ArrowCursor))
            return
        if self.drag["mode"] == "scrub":
            self.seekRequested.emit(max(0, int(self._xToMs(position.x()))))
            return
        deltaMs = int((position.x() - self.drag["x0"]) / max(0.0001, self._pxPerMs()))
        if deltaMs == 0 and not self.drag["started"]:
            return
        if not self.drag["started"]:
            self.drag["started"] = True
            self.editStarted.emit()
        self._applyDrag(deltaMs)
        self.refreshLayout()
        self.update()
        self.edited.emit()

    def _applyDrag(self, deltaMs):
        clip, orig, mode = self.drag["clip"], self.drag["orig"], self.drag["mode"]
        length = orig["endMs"] - orig["startMs"]
        if mode == "move":
            newPosition = max(0, orig["posMs"] + deltaMs)
            newPosition = max(0, self._snapRange(newPosition, length, clip))
            clip.posMs = newPosition
            if self.drag["ripple"]:
                shift = newPosition - orig["posMs"]
                for other, originalPosition in self.drag["others"].items():
                    if originalPosition >= orig["posMs"]:
                        other.posMs = max(0, originalPosition + shift)
        elif mode == "trimStart":
            lowest = max(0, orig["startMs"] - orig["posMs"])
            newStart = max(lowest, min(orig["endMs"] - MIN_CLIP_MS, orig["startMs"] + deltaMs))
            timelineStart = self._snapValue(orig["posMs"] + newStart - orig["startMs"], clip)
            newStart = max(lowest, min(orig["endMs"] - MIN_CLIP_MS, orig["startMs"] + (timelineStart - orig["posMs"])))
            clip.startMs = int(newStart)
            clip.posMs = int(orig["posMs"] + newStart - orig["startMs"])
        elif mode == "trimEnd":
            newEnd = max(orig["startMs"] + MIN_CLIP_MS, min(clip.durationMs, orig["endMs"] + deltaMs))
            timelineEnd = self._snapValue(orig["posMs"] + newEnd - orig["startMs"], clip)
            newEnd = max(orig["startMs"] + MIN_CLIP_MS, min(clip.durationMs, orig["startMs"] + (timelineEnd - orig["posMs"])))
            clip.endMs = int(newEnd)
        elif mode == "fadeIn":
            handle = self._snapValue(orig["posMs"] + orig["fadeInMs"] + deltaMs, clip)
            clip.fadeInMs = int(max(0, min(clip.lengthMs, handle - clip.posMs)))
        elif mode == "fadeOut":
            clipEnd = clip.posMs + clip.lengthMs
            handle = self._snapValue(clipEnd - orig["fadeOutMs"] + deltaMs, clip)
            clip.fadeOutMs = int(max(0, min(clip.lengthMs, clipEnd - handle)))
        clip.clampFades()

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.snapGuideMs = None
        self.update()

    def mouseDoubleClickEvent(self, event):
        if event.position().y() >= RULER_H and self._hit(event.position())[0] is None:
            self.fitAll()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
            return
        span = self.viewEnd - self.viewStart
        if event.modifiers() & Qt.ShiftModifier:
            shift = -span * 0.1 * (delta / 120.0)
            self._setView(self.viewStart + shift, self.viewEnd + shift)
            return
        anchorMs = self._xToMs(event.position().x())
        newSpan = max(500.0, min(max(60000.0, self.totalMs() * 2.0), span * (0.8 if delta > 0 else 1.25)))
        ratio = (anchorMs - self.viewStart) / max(1.0, span)
        start = anchorMs - ratio * newSpan
        self._setView(start, start + newSpan)


class SongPickerDialog(QDialog):
    """Choose songs of the library to add to the mix."""

    def __init__(self, parent, songs):
        super().__init__(parent)
        self.setWindowTitle("Aggiungi canzoni al mix")
        self.resize(520, 560)
        self.songs = songs
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        note = QLabel("Sono mostrate le canzoni che hai sul PC. Per una canzone in streaming usa il menu → Crea mix.")
        note.setObjectName("small")
        note.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca...")
        self.search.textChanged.connect(self._filter)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda item: self.accept())
        for song in songs:
            artist = song.get("artist") or ""
            item = QListWidgetItem(f"{song.get('title')}  ·  {artist}" if artist else str(song.get("title")))
            item.setData(Qt.UserRole, song)
            self.list.addItem(item)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        add = QPushButton("Aggiungi")
        add.setObjectName("accent")
        add.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(add)
        layout.addWidget(note)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)

    def _filter(self, text):
        text = text.strip().lower()
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(bool(text) and text not in item.text().lower())

    def chosen(self):
        return [item.data(Qt.UserRole) for item in self.list.selectedItems()]


class MixDialog(QDialog):
    def __init__(self, parent, songs, library, onDone):
        super().__init__(parent)
        self.onDone = onDone
        self.library = library
        self.clips = []
        self.undoStack = []
        self.redoStack = []
        self.colorCounter = 0
        self.closed = False
        self.updatingInspector = False
        self.nameEdited = False
        self.renderSerial = 0
        self.windowStartMs = 0
        self.windowEndMs = 0
        self.previewCache = {}
        self.tempFiles = []
        self.seekTimer = QTimer(self)
        self.seekTimer.setSingleShot(True)
        self.seekTimer.setInterval(250)
        self.seekTimer.timeout.connect(lambda: self._startPreview(self.timeline.playheadMs))
        self.setWindowTitle("Crea mix")
        self.resize(1180, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        header = QLabel("Crea mix")
        header.setObjectName("h2")
        hint = QLabel("Trascina un brano per spostarlo (Shift = sposta anche i successivi) · trascina i bordi per tagliarlo · "
                      "i cerchietti in alto sono i fade · rotella = zoom · Shift+rotella = scorri · Alt = senza magnete · "
                      "click sul righello = posiziona · Spazio = ascolta")
        hint.setObjectName("small")
        hint.setWordWrap(True)
        layout.addWidget(header)
        layout.addWidget(hint)

        toolbar = QHBoxLayout()
        self.addButton = QPushButton("+ Aggiungi canzoni...")
        self.addButton.clicked.connect(self._addFromLibrary)
        self.splitButton = QPushButton("Dividi al cursore")
        self.splitButton.setToolTip("Divide il brano selezionato in due pezzi nel punto del cursore")
        self.splitButton.clicked.connect(self._split)
        self.removeButton = QPushButton("Rimuovi brano")
        self.removeButton.clicked.connect(self._remove)
        self.undoButton = QPushButton("Annulla")
        self.undoButton.clicked.connect(self._undo)
        self.redoButton = QPushButton("Ripristina")
        self.redoButton.clicked.connect(self._redo)
        self.snapCheck = QCheckBox("Magnete")
        self.snapCheck.setChecked(True)
        self.snapCheck.setToolTip("I bordi dei brani si attaccano tra loro e al cursore (tieni Alt per escluderlo)")
        fitButton = QPushButton("Adatta alla finestra")
        fitButton.clicked.connect(lambda: self.timeline.fitAll())
        for widget in (self.addButton, self.splitButton, self.removeButton, self.undoButton, self.redoButton):
            toolbar.addWidget(widget)
        toolbar.addSpacing(10)
        toolbar.addWidget(self.snapCheck)
        toolbar.addStretch()
        toolbar.addWidget(fitButton)
        layout.addLayout(toolbar)

        self.timeline = MixTimeline()
        self.timeline.clips = self.clips
        self.timeline.selectionChanged.connect(lambda clip: self._syncInspector())
        self.timeline.edited.connect(self._onTimelineEdited)
        self.timeline.editStarted.connect(self._pushUndo)
        self.timeline.seekRequested.connect(self._onSeek)
        self.snapCheck.toggled.connect(lambda checked: setattr(self.timeline, "snapEnabled", checked))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.timeline)
        layout.addWidget(scroll, 1)

        transport = QHBoxLayout()
        self.playButton = QToolButton()
        self.playButton.setObjectName("playButton")
        self.playButton.setIcon(theme.icon("play", "#000", 18))
        self.playButton.setFixedSize(36, 36)
        self.playButton.setToolTip("Ascolta dal cursore (Spazio)")
        self.playButton.clicked.connect(self._togglePlay)
        startButton = QPushButton("Dall'inizio")
        startButton.clicked.connect(lambda: self._onSeek(0))
        self.timeLabel = QLabel("0:00.000 / 0:00")
        self.timeLabel.setObjectName("sub")
        transport.addWidget(self.playButton)
        transport.addWidget(startButton)
        transport.addWidget(self.timeLabel)
        transport.addStretch()
        layout.addLayout(transport)

        layout.addWidget(self._buildInspector())
        layout.addWidget(self._buildTransitions())

        saveRow = QHBoxLayout()
        self.nameEdit = QLineEdit()
        self.nameEdit.textEdited.connect(lambda text: setattr(self, "nameEdited", True))
        self.formatCombo = QComboBox()
        self.formatCombo.addItems(["mp3", "wav", "flac", "m4a"])
        self.statusLabel = QLabel("")
        self.statusLabel.setObjectName("sub")
        cancelButton = QPushButton("Chiudi")
        cancelButton.clicked.connect(self.reject)
        self.saveButton = QPushButton("Crea mix")
        self.saveButton.setObjectName("accent")
        self.saveButton.clicked.connect(self._save)
        saveRow.addWidget(QLabel("Nome"))
        saveRow.addWidget(self.nameEdit, 1)
        saveRow.addWidget(self.formatCombo)
        saveRow.addSpacing(10)
        saveRow.addWidget(self.statusLabel)
        saveRow.addWidget(cancelButton)
        saveRow.addWidget(self.saveButton)
        layout.addLayout(saveRow)

        self.previewPlayer = QMediaPlayer(self)
        self.previewOutput = QAudioOutput(self)
        self.previewOutput.setVolume((settings.get("volume") / 100.0) ** 2)
        self.previewPlayer.setAudioOutput(self.previewOutput)
        self.previewPlayer.positionChanged.connect(self._onPreviewPosition)
        self.previewPlayer.playbackStateChanged.connect(self._onPreviewState)
        self.previewPlayer.mediaStatusChanged.connect(self._onMediaStatus)

        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._togglePlay)
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self._remove)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self._redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self._redo)

        self._addClips(songs, undo=False)
        self.timeline.fitAll()
        if self.clips:
            self.timeline.selectClip(self.clips[0])
        self._syncInspector()
        self._refreshInfo()

    # ---------- panels ----------
    def _buildInspector(self):
        frame = QFrame()
        frame.setObjectName("card")
        grid = QGridLayout(frame)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.inspector = frame
        self.clipTitle = QLabel("Nessun brano selezionato")
        self.clipTitle.setObjectName("h3")
        self.startSpin = TimeSpin()
        self.endSpin = TimeSpin()
        self.posSpin = TimeSpin()
        for spin in (self.startSpin, self.endSpin, self.posSpin):
            spin.setRange(0, 36000)
        self.fadeInSpin = QSpinBox()
        self.fadeOutSpin = QSpinBox()
        for spin in (self.fadeInSpin, self.fadeOutSpin):
            spin.setRange(0, 60000)
            spin.setSingleStep(250)
            spin.setSuffix(" ms")
            spin.setKeyboardTracking(False)
        self.volumeSpin = QSpinBox()
        self.volumeSpin.setRange(0, 200)
        self.volumeSpin.setSuffix(" %")
        self.volumeSpin.setKeyboardTracking(False)
        for spin in (self.startSpin, self.endSpin, self.posSpin, self.fadeInSpin, self.fadeOutSpin, self.volumeSpin):
            spin.valueChanged.connect(self._onInspector)
        grid.addWidget(self.clipTitle, 0, 0, 1, 8)
        labels = (("Parte da", self.startSpin), ("Finisce a", self.endSpin), ("Posizione nel mix", self.posSpin),
                  ("Fade in", self.fadeInSpin), ("Fade out", self.fadeOutSpin), ("Volume", self.volumeSpin))
        for index, (text, widget) in enumerate(labels):
            row, column = 1 + index // 3, (index % 3) * 2
            grid.addWidget(QLabel(text), row, column)
            grid.addWidget(widget, row, column + 1)
        grid.setColumnStretch(6, 1)
        return frame

    def _buildTransitions(self):
        frame = QFrame()
        frame.setObjectName("card")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)
        self.transitionCombo = QComboBox()
        for text, kind in TRANSITIONS:
            self.transitionCombo.addItem(text, kind)
        self.transitionSpin = TimeSpin()
        self.transitionSpin.setRange(0.1, 60)
        self.transitionSpin.setValue(3.0)
        self.transitionCombo.currentIndexChanged.connect(
            lambda index: self.transitionSpin.setEnabled(self.transitionCombo.currentData() != "cut"))
        applyOne = QPushButton("Applica prima del brano selezionato")
        applyOne.clicked.connect(self._applyToSelected)
        applyAll = QPushButton("Applica a tutte le unioni")
        applyAll.clicked.connect(self._applyToAll)
        row.addWidget(QLabel("Transizione"))
        row.addWidget(self.transitionCombo)
        row.addWidget(QLabel("Durata"))
        row.addWidget(self.transitionSpin)
        row.addWidget(applyOne)
        row.addWidget(applyAll)
        row.addStretch()
        return frame

    # ---------- clips ----------
    def _transitionChoice(self):
        return self.transitionCombo.currentData(), int(self.transitionSpin.value() * 1000)

    def _ordered(self):
        return sorted(self.clips, key=lambda clip: clip.posMs)

    def _previous(self, clip):
        order = self._ordered()
        index = order.index(clip)
        return order[index - 1] if index > 0 else None

    def _applyTransition(self, clip, kind, durationMs):
        """Puts clip after the song before it with this transition; the songs after clip move with it."""
        previous = self._previous(clip)
        if previous is None:
            return False
        order = self._ordered()
        later = order[order.index(clip) + 1:]
        overlap = max(0, min(durationMs, int(min(previous.lengthMs, clip.lengthMs) * 0.9)))
        if kind == "crossfade":
            newPosition = previous.timelineEndMs - overlap
            previous.fadeOutMs, clip.fadeInMs = overlap, overlap
        elif kind == "overlap":
            newPosition = previous.timelineEndMs - overlap
            previous.fadeOutMs, clip.fadeInMs = 0, 0
        elif kind == "cut":
            newPosition = previous.timelineEndMs
            previous.fadeOutMs, clip.fadeInMs = 0, 0
        else:
            newPosition = previous.timelineEndMs + durationMs
        shift = newPosition - clip.posMs
        clip.posMs = newPosition
        for other in later:
            other.posMs = max(0, other.posMs + shift)
        previous.clampFades()
        clip.clampFades()
        return True

    def _applyToSelected(self):
        clip = self.timeline.selected
        if clip is None or self._previous(clip) is None:
            self.statusLabel.setText("Scegli un brano che ha un altro brano prima")
            return
        self._pushUndo()
        self._applyTransition(clip, *self._transitionChoice())
        self._afterEdit()

    def _applyToAll(self):
        order = self._ordered()
        if len(order) < 2:
            return
        self._pushUndo()
        for clip in order[1:]:
            self._applyTransition(clip, *self._transitionChoice())
        self._afterEdit()
        self.timeline.fitAll()

    def _addClips(self, songs, undo=True):
        songs = [song for song in songs if song and song.get("path") and os.path.isfile(song["path"])]
        if not songs:
            return
        if undo:
            self._pushUndo()
        kind, durationMs = self._transitionChoice()
        for song in songs:
            clip = MixClip(song, self.colorCounter)
            self.colorCounter += 1
            clip.posMs = self.timeline.totalMs()
            self.clips.append(clip)
            self._applyTransition(clip, kind, durationMs)
            runInBackground(audio_tools.loadWaveform, clip.path, 4000,
                            onFinished=lambda result, clip=clip: self._onWaveform(clip, result),
                            onError=lambda message: None)
        self._afterEdit()
        self.timeline.fitAll()

    def _addFromLibrary(self):
        songs = [song for song in self.library() if song.get("path") and not str(song["path"]).startswith("stream:")
                 and os.path.isfile(song["path"])]
        dialog = SongPickerDialog(self, songs)
        if dialog.exec():
            chosen = dialog.chosen()
            self._addClips(chosen)
            if not chosen:
                self.statusLabel.setText("Nessuna canzone scelta")

    def _onWaveform(self, clip, result):
        if self.closed:
            return
        peaks, durationMs = result
        clip.peaks = peaks
        if durationMs > 0 and abs(durationMs - clip.durationMs) > 50:
            if clip.endMs >= clip.durationMs - 50:
                clip.endMs = durationMs
            clip.durationMs = durationMs
            clip.startMs = min(clip.startMs, clip.endMs - MIN_CLIP_MS)
            self._afterEdit()
        self.timeline.update()

    def _remove(self):
        clip = self.timeline.selected
        if clip is None or clip not in self.clips:
            return
        self._pushUndo()
        order = self._ordered()
        following = order[order.index(clip) + 1] if order.index(clip) + 1 < len(order) else None
        self.clips.remove(clip)
        self.timeline.selected = None
        if following is not None and self._previous(following) is not None:
            self._applyTransition(following, *self._transitionChoice())
        self._afterEdit()
        self.timeline.selectionChanged.emit(None)

    def _split(self):
        clip = self.timeline.selected
        cutMs = self.timeline.playheadMs
        if clip is None or not (clip.posMs + MIN_CLIP_MS < cutMs < clip.timelineEndMs - MIN_CLIP_MS):
            self.statusLabel.setText("Metti il cursore dentro il brano selezionato")
            return
        self._pushUndo()
        second = MixClip(clip.song)
        second.color = clip.color
        second.peaks = clip.peaks
        second.durationMs = clip.durationMs
        second.startMs = clip.startMs + (cutMs - clip.posMs)
        second.endMs = clip.endMs
        second.posMs = cutMs
        second.fadeOutMs = clip.fadeOutMs
        second.volume = clip.volume
        clip.endMs = second.startMs
        clip.fadeOutMs = 0
        clip.clampFades()
        second.clampFades()
        self.clips.append(second)
        self.timeline.selected = second
        self._afterEdit()
        self.timeline.selectionChanged.emit(second)

    # ---------- undo ----------
    def _snapshot(self):
        return [(clip, clip.params()) for clip in self.clips]

    def _restore(self, snapshot):
        self.clips[:] = [clip for clip, _ in snapshot]
        for clip, params in snapshot:
            clip.restore(params)
        if self.timeline.selected not in self.clips:
            self.timeline.selected = None
        self._afterEdit()
        self.timeline.selectionChanged.emit(self.timeline.selected)

    def _pushUndo(self):
        self.undoStack.append(self._snapshot())
        del self.undoStack[:-60]
        self.redoStack.clear()
        self._updateUndoButtons()

    def _undo(self):
        if not self.undoStack:
            return
        self.redoStack.append(self._snapshot())
        self._restore(self.undoStack.pop())
        self._updateUndoButtons()

    def _redo(self):
        if not self.redoStack:
            return
        self.undoStack.append(self._snapshot())
        self._restore(self.redoStack.pop())
        self._updateUndoButtons()

    def _updateUndoButtons(self):
        self.undoButton.setEnabled(bool(self.undoStack))
        self.redoButton.setEnabled(bool(self.redoStack))

    # ---------- inspector ----------
    def _syncInspector(self):
        clip = self.timeline.selected
        self.inspector.setEnabled(clip is not None)
        self.updatingInspector = True
        if clip is None:
            self.clipTitle.setText("Nessun brano selezionato")
        else:
            artist = clip.song.get("artist")
            self.clipTitle.setText(f"{clip.song.get('title')}  ·  {artist}" if artist else str(clip.song.get("title")))
            for spin in (self.startSpin, self.endSpin):
                spin.setMaximum(clip.durationMs / 1000.0)
            self.startSpin.setValue(clip.startMs / 1000.0)
            self.endSpin.setValue(clip.endMs / 1000.0)
            self.posSpin.setValue(clip.posMs / 1000.0)
            self.fadeInSpin.setValue(clip.fadeInMs)
            self.fadeOutSpin.setValue(clip.fadeOutMs)
            self.volumeSpin.setValue(int(clip.volume))
        self.updatingInspector = False
        self._updateUndoButtons()
        self.timeline.update()

    def _onInspector(self):
        clip = self.timeline.selected
        if self.updatingInspector or clip is None:
            return
        self._pushUndo()
        clip.endMs = max(MIN_CLIP_MS, min(clip.durationMs, int(round(self.endSpin.value() * 1000))))
        clip.startMs = max(0, min(int(round(self.startSpin.value() * 1000)), clip.endMs - MIN_CLIP_MS))
        clip.posMs = max(0, int(round(self.posSpin.value() * 1000)))
        clip.fadeInMs = self.fadeInSpin.value()
        clip.fadeOutMs = self.fadeOutSpin.value()
        clip.volume = self.volumeSpin.value()
        clip.clampFades()
        self._afterEdit()

    def _onTimelineEdited(self):
        self._syncInspector()
        self._invalidatePreview()
        self._refreshInfo()

    def _afterEdit(self):
        self.timeline.refreshLayout()
        self._syncInspector()
        self._invalidatePreview()
        self._refreshInfo()

    def _defaultName(self):
        titles = [str(clip.song.get("title") or "") for clip in self._ordered()]
        unique = list(dict.fromkeys(titles))
        if not unique:
            return "Mix"
        name = " + ".join(unique[:3])
        return f"{name} +{len(unique) - 3}" if len(unique) > 3 else name

    def _refreshInfo(self):
        total = self.timeline.totalMs()
        self.timeLabel.setText(f"{theme.formatTimePrecise(self.timeline.playheadMs)} / {theme.formatTime(total)}")
        self.saveButton.setEnabled(bool(self.clips))
        if not self.nameEdited:
            self.nameEdit.setText(self._defaultName())

    # ---------- preview ----------
    def _stateKey(self):
        return json.dumps([clip.renderDict() for clip in self.clips], sort_keys=True)

    def _invalidatePreview(self):
        self.renderSerial += 1
        if self.previewPlayer.playbackState() != QMediaPlayer.StoppedState:
            self.previewPlayer.stop()

    def _onSeek(self, positionMs):
        wasPlaying = self.previewPlayer.playbackState() == QMediaPlayer.PlayingState
        self.timeline.setPlayhead(positionMs)
        self._refreshInfo()
        if wasPlaying:
            # While you drag the cursor the preview waits, then it restarts from the new place
            self.previewPlayer.stop()
            self.seekTimer.start()

    def _togglePlay(self):
        if self.previewPlayer.playbackState() == QMediaPlayer.PlayingState:
            self.previewPlayer.stop()
            return
        self._startPreview(self.timeline.playheadMs)

    def _startPreview(self, startMs):
        total = self.timeline.totalMs()
        if not self.clips or total <= 0:
            return
        if startMs >= total - 100:
            startMs = 0
        endMs = min(total, startMs + PREVIEW_MS)
        self.renderSerial += 1
        serial = self.renderSerial
        self.previewPlayer.stop()
        self.windowStartMs, self.windowEndMs = startMs, endMs
        key = (self._stateKey(), startMs)
        cached = self.previewCache.get(key)
        if cached and os.path.isfile(cached):
            self._onPreviewReady(serial, cached)
            return
        self.statusLabel.setText("Preparo l'anteprima...")
        folder = os.path.join(TEMP_DIR, "mix_preview")
        os.makedirs(folder, exist_ok=True)
        outputPath = audio_tools.uniquePath(folder, "preview", ".wav")
        self.tempFiles.append(outputPath)

        def onReady(path):
            self.previewCache[key] = path
            self._onPreviewReady(serial, path)

        runInBackground(audio_tools.renderMix, [clip.renderDict() for clip in self.clips], outputPath, "192", startMs, endMs,
                        onFinished=onReady, onError=lambda message: self._onPreviewError(serial, message))

    def _onPreviewReady(self, serial, path):
        if self.closed or serial != self.renderSerial:
            return
        self.statusLabel.setText("")
        self.previewPlayer.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self.previewPlayer.play()

    def _onPreviewError(self, serial, message):
        if self.closed or serial != self.renderSerial:
            return
        self.statusLabel.setText("")
        QMessageBox.critical(self, APP_NAME, f"Impossibile preparare l'anteprima:\n{message}")

    def _onPreviewPosition(self, positionMs):
        self.timeline.setPlayhead(self.windowStartMs + positionMs)
        self._refreshInfo()

    def _onPreviewState(self, state):
        playing = state == QMediaPlayer.PlayingState
        self.playButton.setIcon(theme.icon("pause" if playing else "play", "#000", 18))

    def _onMediaStatus(self, status):
        # The preview plays 60 s at a time: at the end of a part the next one starts by itself
        if status == QMediaPlayer.EndOfMedia and not self.closed and self.windowEndMs < self.timeline.totalMs() - 50:
            self._startPreview(self.windowEndMs)

    # ---------- save ----------
    def _save(self):
        if not self.clips:
            return
        name = self.nameEdit.text().strip() or self._defaultName()
        extension = "." + self.formatCombo.currentText()
        outputPath = audio_tools.uniquePath(settings.musicDir(), audio_tools.safeFileName(name, "Mix"), extension)
        self.previewPlayer.stop()
        self.previewPlayer.setSource(QUrl())
        self.renderSerial += 1
        self.saveButton.setEnabled(False)
        self.statusLabel.setText("Creo il mix...")
        ordered = self._ordered()
        runInBackground(audio_tools.renderMix, [clip.renderDict() for clip in self.clips], outputPath, settings.get("audioQuality"),
                        onFinished=lambda path: self._onSaved(ordered, path, name),
                        onError=lambda message: self._onSaveError(outputPath, message))

    def _onSaved(self, ordered, path, name):
        if self.closed:
            return
        self.statusLabel.setText("Fatto!")
        self.onDone([clip.song for clip in ordered], path, name)
        self.accept()

    def _onSaveError(self, outputPath, message):
        if self.closed:
            return
        self.saveButton.setEnabled(True)
        self.statusLabel.setText("")
        try:
            os.remove(outputPath)
        except OSError:
            pass
        QMessageBox.critical(self, APP_NAME, f"Errore durante la creazione del mix:\n{message}")

    def done(self, result):
        self.closed = True
        self.previewPlayer.stop()
        self.previewPlayer.setSource(QUrl())
        for path in self.tempFiles:
            try:
                os.remove(path)
            except OSError:
                pass
        super().done(result)
