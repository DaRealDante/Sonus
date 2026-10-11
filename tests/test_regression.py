import os
import subprocess
import tempfile

import pytest

from app.config import ffmpegExe
from tests.broker import pump, waitFor
from tests.test_together import FakeOutputStream


@pytest.fixture(scope="module")
def window():
    import sounddevice
    original = sounddevice.OutputStream
    sounddevice.OutputStream = FakeOutputStream
    from app.ui.main_window import MainWindow
    mainWindow = MainWindow()
    mainWindow.show()
    yield mainWindow
    mainWindow.player.shutdown()
    sounddevice.OutputStream = original


@pytest.fixture(scope="module")
def localSong(window):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "Ken - Prova Locale.mp3")
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=20", path], check=True)
    window._onImported([{"path": path, "title": "Prova Locale", "artist": "Ken", "album": "", "duration": 20, "cover": None}], None)
    return window.database.findSong("Prova Locale", "Ken")


def test_localFilePlaysSeeksAndEffectsSave(window, localSong):
    window.playSongs([localSong], 0)
    assert waitFor(window.player.isPlaying, 5)
    window.player.seek(8000)
    pump(0.5)
    assert 8000 <= window.player.position() < 9500
    window._onEffectsChanged({"rate": 0.9, "keepPitch": False, "reverbWet": 0.3, "reverbSize": 2.5})
    saved = window.database.getSong(localSong["id"])
    assert abs(saved["songRate"] - 0.9) < 0.001 and saved["keepPitch"] == 0
    assert abs(window.player.playbackRate() - 0.9) < 0.001
    window._onEffectsChanged({"rate": 1.0, "keepPitch": True, "reverbWet": 0.0, "reverbSize": 1.8})
    window.player.pause()


def test_localSearchLoopsAndPlaylists(window, localSong):
    assert [song["title"] for song in window.database.searchSongs("Prova")] == ["Prova Locale"]
    loopId = window.database.addLoop(localSong["id"], "Ritornello", 2000, 5000)
    assert window.database.loops(localSong["id"])[0]["id"] == loopId
    playlistId = window.database.createPlaylist("Regressione")
    window.addToPlaylist(playlistId, [localSong["id"]])
    assert [song["title"] for song in window.database.playlistSongs(playlistId)] == ["Prova Locale"]
    window.removeFromPlaylist(playlistId, window.database.playlistSongs(playlistId))
    assert window.database.playlistSongs(playlistId) == []


def test_cutDialogStillOpensForFiles(window, localSong, monkeypatch):
    from app.ui import main_window
    opened = []

    class FakeCutDialog:
        def __init__(self, parent, song, callback, selection):
            opened.append(song["title"])

        def exec(self):
            return 0

    monkeypatch.setattr(main_window, "CutDialog", FakeCutDialog)
    window.openCutDialog(localSong)
    assert opened == ["Prova Locale"]


def test_songMenuForFilesKeepsEveryAction(window, localSong, monkeypatch):
    from PySide6.QtWidgets import QMenu
    from app.ui import main_window
    captured = {}

    class RecordingMenu(QMenu):
        def exec(self, *args):
            captured["actions"] = [action.text() for action in self.actions()]

    monkeypatch.setattr(main_window, "QMenu", RecordingMenu)
    window.showSongMenu([window.database.getSong(localSong["id"])], None, {})
    for expected in ("Riproduci", "Riproduci dopo", "Aggiungi alla coda", "Loop A-B...", "Taglia audio...",
                     "Modifica informazioni...", "Mostra nella cartella", "Elimina dalla libreria..."):
        assert expected in captured["actions"]
    assert "Scarica sul PC" not in captured["actions"]


def test_pagesNavigateWithoutErrors(window):
    for key in ("home", "search", "library", "favorites", "downloads", "queue", "equalizer", "nowplaying"):
        window.navigate(key)
        pump(0.05)
    window.navigate("home")
