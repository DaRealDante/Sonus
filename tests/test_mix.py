import os
import subprocess
import tempfile

import numpy
import pytest
from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest

from app import audio_tools
from app.config import ffmpegExe


@pytest.fixture(scope="module")
def tones():
    folder = tempfile.mkdtemp()
    paths = []
    for name, frequency in (("a.wav", 440), ("b.wav", 880)):
        path = os.path.join(folder, name)
        subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration=4",
                        "-ar", "44100", "-ac", "2", path], check=True)
        paths.append(path)
    return folder, paths


def _clip(path, positionMs, fadeInMs=0, fadeOutMs=0):
    return {"path": path, "startMs": 0, "endMs": 4000, "posMs": positionMs, "fadeInMs": fadeInMs, "fadeOutMs": fadeOutMs, "volume": 100}


def _samples(path):
    raw = audio_tools.runFfmpeg(["-i", path, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], captureOutput=True)
    return numpy.frombuffer(raw, dtype=numpy.int16).astype(numpy.float32) / 32768.0


def _rms(samples, startSeconds, endSeconds):
    part = samples[int(startSeconds * 8000):int(endSeconds * 8000)]
    return float(numpy.sqrt(numpy.mean(part ** 2)))


def test_renderMix(tones):
    folder, (pathA, pathB) = tones
    # Crossfade of 2 s: 4 s + 4 s - 2 s = 6 s, and the loudness stays even (equal power) in the middle of the fade
    crossfade = audio_tools.renderMix([_clip(pathA, 0, 0, 2000), _clip(pathB, 2000, 2000, 0)], os.path.join(folder, "x.wav"))
    samples = _samples(crossfade)
    assert abs(len(samples) / 8000 * 1000 - 6000) < 150
    assert 0.8 < _rms(samples, 2.8, 3.2) / _rms(samples, 0.5, 1.5) < 1.25
    assert float(numpy.abs(samples).max()) <= 1.0
    # Cut (no transition): 8 s
    cut = audio_tools.renderMix([_clip(pathA, 0), _clip(pathB, 4000)], os.path.join(folder, "cut.wav"))
    assert abs(len(_samples(cut)) / 8000 * 1000 - 8000) < 150
    # Only a part of the mix (used by the preview)
    part = audio_tools.renderMix([_clip(pathA, 0, 0, 2000), _clip(pathB, 2000, 2000, 0)], os.path.join(folder, "part.wav"),
                                 "192", 1000, 3000)
    assert abs(len(_samples(part)) / 8000 * 1000 - 2000) < 150


class FakeMediaPlayer(QObject):
    """The test PC has no sound card: the editor only needs the player's states and signals."""
    StoppedState, PlayingState, EndOfMedia = QMediaPlayer.StoppedState, QMediaPlayer.PlayingState, QMediaPlayer.EndOfMedia
    positionChanged = Signal(int)
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)

    def setAudioOutput(self, output):
        pass

    def playbackState(self):
        return self.StoppedState

    def stop(self):
        pass

    def setSource(self, url):
        pass


class FakeAudioOutput(QObject):
    def setVolume(self, volume):
        pass


def test_mixEditor(tones, monkeypatch):
    import app.ui.mix_dialog as mix_dialog
    from app.ui.mix_dialog import MixDialog
    monkeypatch.setattr(mix_dialog, "QMediaPlayer", FakeMediaPlayer)
    monkeypatch.setattr(mix_dialog, "QAudioOutput", FakeAudioOutput)
    _, (pathA, pathB) = tones
    songs = [{"id": 1, "path": pathA, "title": "A", "artist": "X", "duration": 4.0, "cover": None},
             {"id": 2, "path": pathB, "title": "B", "artist": "Y", "duration": 4.0, "cover": None}]
    dialog = MixDialog(None, songs, lambda: [], lambda *arguments: None)
    try:
        first, second = dialog.clips
        # Songs start one after the other with a 3 s crossfade
        assert second.posMs == first.timelineEndMs - 3000 == 1000
        assert first.fadeOutMs == 3000 and second.fadeInMs == 3000
        dialog.timeline.selectClip(second)
        dialog.transitionCombo.setCurrentIndex(2)  # cut
        dialog._applyToSelected()
        assert second.posMs == 4000 and second.fadeInMs == 0 and first.fadeOutMs == 0
        dialog._undo()
        assert second.posMs == 1000 and second.fadeInMs == 3000
        # Split the first song at the cursor, then undo
        dialog.timeline.setPlayhead(500)
        dialog.timeline.selectClip(first)
        dialog._split()
        assert len(dialog.clips) == 3
        dialog._undo()
        assert len(dialog.clips) == 2
        # Drag the second song with the mouse
        timeline = dialog.timeline
        timeline.resize(1200, 300)
        timeline.fitAll()
        lane = timeline.lanes()[0][second]
        rect = timeline._clipRect(second, lane)
        start = QPointF(rect.center().x(), rect.center().y())
        undoBefore = len(dialog.undoStack)
        QTest.mousePress(timeline, Qt.LeftButton, Qt.NoModifier, start.toPoint())
        QTest.mouseMove(timeline, (start + QPointF(50, 0)).toPoint())
        QTest.mouseRelease(timeline, Qt.LeftButton, Qt.NoModifier, (start + QPointF(50, 0)).toPoint())
        assert 1100 < second.posMs < 1500
        assert len(dialog.undoStack) == undoBefore + 1
        dialog._undo()
        assert second.posMs == 1000
    finally:
        dialog.reject()
