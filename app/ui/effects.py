import math
import random

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation)
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QLabel, QWidget

from ..config import settings
from . import theme


def enabled(key):
    return bool(settings.get(key))


# ---------- transitions ----------
def switchPage(stacked, widget):
    """Cross-fade + small slide between pages (a snapshot of the old page fades out over the new one)."""
    current = stacked.currentWidget()
    if current is widget or not enabled("fxTransitions") or not stacked.isVisible() or current is None:
        stacked.setCurrentWidget(widget)
        return
    snapshot = current.grab()
    overlay = QLabel(stacked)
    overlay.setPixmap(snapshot)
    overlay.setGeometry(stacked.rect())
    overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
    stacked.setCurrentWidget(widget)
    overlay.show()
    overlay.raise_()
    opacity = QGraphicsOpacityEffect(overlay)
    overlay.setGraphicsEffect(opacity)
    fade = QPropertyAnimation(opacity, b"opacity", overlay)
    fade.setDuration(220)
    fade.setStartValue(1.0)
    fade.setEndValue(0.0)
    fade.setEasingCurve(QEasingCurve.OutCubic)
    slide = QPropertyAnimation(overlay, b"pos", overlay)
    slide.setDuration(220)
    slide.setStartValue(QPoint(0, 0))
    slide.setEndValue(QPoint(0, -14))
    slide.setEasingCurve(QEasingCurve.OutCubic)
    fade.finished.connect(overlay.deleteLater)
    fade.start()
    slide.start()


def popIn(window):
    """Popups open with a quick fade instead of appearing at once."""
    if not enabled("fxTransitions"):
        window.setWindowOpacity(1.0)
        return
    window.setWindowOpacity(0.0)
    animation = QPropertyAnimation(window, b"windowOpacity", window)
    animation.setDuration(150)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.start(QPropertyAnimation.DeleteWhenStopped)


def bounce(button, baseSize=None):
    """Play button "squish": the icon shrinks and springs back."""
    if not enabled("fxTransitions"):
        return
    size = baseSize or button.iconSize()
    animation = QVariantAnimation(button)
    animation.setDuration(260)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutBack)

    def apply(progress):
        scale = 0.72 + 0.28 * progress
        button.setIconSize(QSize(max(1, int(size.width() * scale)), max(1, int(size.height() * scale))))

    animation.valueChanged.connect(apply)
    animation.finished.connect(lambda: button.setIconSize(size))
    animation.start(QVariantAnimation.DeleteWhenStopped)


class HoverGlow(QObject):
    """Cards light up with a soft accent glow under the mouse."""

    def __init__(self, widget, color=None):
        super().__init__(widget)
        self.widget = widget
        self.color = QColor(color or theme.ACCENT)
        self.effect = None
        self.animation = None
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter and enabled("fxTransitions"):
            self._animateTo(26)
        elif event.type() == QEvent.Leave and self.effect is not None:
            self._animateTo(0)
        return False

    def _animateTo(self, radius):
        if self.effect is None:
            self.effect = QGraphicsDropShadowEffect(self.widget)
            glow = QColor(self.color)
            glow.setAlpha(110)
            self.effect.setColor(glow)
            self.effect.setOffset(0, 4)
            self.effect.setBlurRadius(0)
            self.widget.setGraphicsEffect(self.effect)
        if self.animation is None or self.animation.targetObject() is not self.effect:
            self.animation = QPropertyAnimation(self.effect, b"blurRadius", self.effect)
            self.animation.setDuration(180)
            self.animation.setEasingCurve(QEasingCurve.OutCubic)
            self.animation.finished.connect(self._removeEffect)
        self.animation.stop()
        self.animation.setStartValue(self.effect.blurRadius())
        self.animation.setEndValue(radius)
        self.animation.start()

    def _removeEffect(self):
        QTimer.singleShot(0, self._dropEffect)

    def _dropEffect(self):
        if self.effect is not None and self.effect.blurRadius() < 1 and \
                (self.animation is None or self.animation.state() != QPropertyAnimation.Running):
            self.animation = None
            self.widget.setGraphicsEffect(None)
            self.effect = None


# ---------- cover colors ----------
def dominantColor(coverPath):
    """The most vivid average colour of a cover (falls back to the plain average for grey covers)."""
    image = QImage(coverPath) if coverPath else QImage()
    if image.isNull():
        return None
    image = image.scaled(32, 32, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB32)
    weightedRed = weightedGreen = weightedBlue = totalWeight = 0.0
    plainRed = plainGreen = plainBlue = 0.0
    count = image.width() * image.height()
    for y in range(image.height()):
        for x in range(image.width()):
            color = QColor(image.pixel(x, y))
            hue, saturation, value, _ = color.getHsvF()
            plainRed += color.redF()
            plainGreen += color.greenF()
            plainBlue += color.blueF()
            weight = saturation * saturation * value
            if weight > 0.02:
                weightedRed += color.redF() * weight
                weightedGreen += color.greenF() * weight
                weightedBlue += color.blueF() * weight
                totalWeight += weight
    if totalWeight > 0.5:
        result = QColor.fromRgbF(weightedRed / totalWeight, weightedGreen / totalWeight, weightedBlue / totalWeight)
    else:
        result = QColor.fromRgbF(plainRed / count, plainGreen / count, plainBlue / count)
    hue, saturation, value, _ = result.getHsvF()
    return QColor.fromHsvF(max(0.0, hue), min(1.0, saturation * 1.1), min(0.62, max(0.32, value)))


class ColorFader(QObject):
    """Smoothly moves a colour towards a target and calls back on every frame."""

    def __init__(self, onColor, parent=None, duration=600):
        super().__init__(parent)
        self.onColor = onColor
        self.current = None
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(duration)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation.valueChanged.connect(self._apply)

    def fadeTo(self, color):
        if color is None:
            self.animation.stop()
            self.current = None
            self.onColor(None)
            return
        if self.current is None or not enabled("fxTransitions"):
            self.current = QColor(color)
            self.onColor(self.current)
            return
        self.animation.stop()
        self.animation.setStartValue(QColor(self.current))
        self.animation.setEndValue(QColor(color))
        self.animation.start()

    def _apply(self, color):
        self.current = QColor(color)
        self.onColor(self.current)


# ---------- visualizer ----------
class Visualizer(QWidget):
    """Bars that move with the music (spectrum computed by the audio engine)."""

    def __init__(self, player, bars=16, mirrored=False, parent=None):
        super().__init__(parent)
        self.player = player
        self.barCount = bars
        self.mirrored = mirrored
        self.levels = [0.0] * bars
        self.color = QColor(theme.ACCENT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.listeners = []
        QApplication.instance().applicationStateChanged.connect(lambda state: self.refreshRunning())

    def setColor(self, color):
        self.color = QColor(color or theme.ACCENT)
        self.update()

    def refreshRunning(self):
        active = enabled("fxVisualizer") and self.isVisible() and self.player.isPlaying() \
            and QApplication.instance().applicationState() == Qt.ApplicationActive
        if active and not self.timer.isActive():
            self.timer.start()
        elif not active and self.timer.isActive():
            self.timer.stop()
            self.levels = [0.0] * self.barCount
            self.update()
            for listener in self.listeners:
                listener(0.0)

    def showEvent(self, event):
        super().showEvent(event)
        self.refreshRunning()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.refreshRunning()

    def _tick(self):
        spectrum = self.player.mediaPlayer.spectrum()
        if len(spectrum) != self.barCount:
            step = len(spectrum) / max(1, self.barCount)
            spectrum = [spectrum[min(len(spectrum) - 1, int(index * step))] for index in range(self.barCount)] if spectrum else []
        for index in range(self.barCount):
            target = spectrum[index] if index < len(spectrum) else 0.0
            current = self.levels[index]
            self.levels[index] = current + (target - current) * (0.55 if target > current else 0.18)
        bass = sum(self.levels[:3]) / 3 if self.barCount >= 3 else 0.0
        for listener in self.listeners:
            listener(bass)
        self.update()

    def paintEvent(self, event):
        if not any(level > 0.01 for level in self.levels):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        gap = max(1.0, width / self.barCount * 0.28)
        barWidth = (width - gap * (self.barCount - 1)) / self.barCount
        radius = min(barWidth / 2, 3.0)
        for index, level in enumerate(self.levels):
            if level < 0.03:
                continue
            barHeight = max(3.0, level * height * (0.5 if self.mirrored else 1.0))
            x = index * (barWidth + gap)
            color = QColor(self.color)
            color.setAlphaF(0.55 + 0.45 * level)
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            if self.mirrored:
                rect = QRectF(x, height / 2 - barHeight, barWidth, barHeight * 2)
            else:
                rect = QRectF(x, height - barHeight, barWidth, barHeight)
            painter.drawRoundedRect(rect, radius, radius)
        painter.end()


# ---------- micro effects ----------
class HeartBurst(QWidget):
    """Little hearts that pop out of the like button."""

    def __init__(self, parent, center, color=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.color = QColor(color or theme.ACCENT)
        size = 90
        self.setGeometry(int(center.x() - size / 2), int(center.y() - size / 2), size, size)
        self.particles = [(random.uniform(0, 2 * math.pi), random.uniform(22, 40), random.uniform(5, 9)) for _ in range(9)]
        self.progress = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(560)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._onProgress)
        self.animation.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self.animation.start()

    def _onProgress(self, value):
        self.progress = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        for angle, distance, size in self.particles:
            position = center + QPointF(math.cos(angle), math.sin(angle)) * distance * self.progress
            color = QColor(self.color)
            color.setAlphaF(max(0.0, 1.0 - self.progress))
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            scale = size * (1.0 - 0.4 * self.progress)
            painter.drawPath(_heartPath(position, scale))
        ring = QColor(self.color)
        ring.setAlphaF(max(0.0, 0.6 - self.progress))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(ring)
        radius = 8 + 30 * self.progress
        painter.drawEllipse(center, radius, radius)
        painter.end()


def _heartPath(center, size):
    path = QPainterPath()
    x, y = center.x(), center.y()
    path.moveTo(x, y + size * 0.35)
    path.cubicTo(x - size, y - size * 0.3, x - size * 0.4, y - size, x, y - size * 0.4)
    path.cubicTo(x + size * 0.4, y - size, x + size, y - size * 0.3, x, y + size * 0.35)
    return path


def heartBurst(button):
    if not enabled("fxMicro") or not button.isVisible():
        return
    window = button.window()
    center = button.mapTo(window, button.rect().center())
    HeartBurst(window, center)
