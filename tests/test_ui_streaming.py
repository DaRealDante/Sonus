import time

import pytest
from PySide6.QtWidgets import QApplication, QMenu


@pytest.fixture(scope="module")
def window():
    application = QApplication.instance() or QApplication([])
    from app.ui import theme
    application.setStyleSheet(theme.STYLESHEET)
    from app.ui.main_window import MainWindow
    mainWindow = MainWindow()
    yield mainWindow
    mainWindow.player.shutdown()


def pump(seconds=0.3):
    deadline = time.time() + seconds
    while time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_addStreamEntriesCreatesStreamSongs(window, monkeypatch):
    from app import downloader
    monkeypatch.setattr(downloader, "streamSongInfo", lambda entry: {
        "url": entry["url"], "title": entry["title"], "artist": "Artista", "album": "", "duration": 100, "cover": None})
    playlistId = window.database.createPlaylist("Test streaming")
    window.addStreamEntries([{"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "title": "Uno"},
                             {"url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "title": "Due"}], playlistId)
    assert waitFor(lambda: len(window.database.playlistSongs(playlistId)) == 2)
    paths = [song["path"] for song in window.database.playlistSongs(playlistId)]
    assert paths == ["stream:https://www.youtube.com/watch?v=aaaaaaaaaaa", "stream:https://www.youtube.com/watch?v=bbbbbbbbbbb"]


def captureMenu(monkeypatch):
    captured = {}

    class RecordingMenu(QMenu):
        def exec(self, *args):
            captured["actions"] = [action.text() for action in self.actions()]
            return None

    from app.ui import main_window
    monkeypatch.setattr(main_window, "QMenu", RecordingMenu)
    return captured


def test_streamSongMenuHasDownloadAndNoCut(window, monkeypatch):
    song = window.database.findSongByUrl("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    captured = captureMenu(monkeypatch)
    window.showSongMenu([song], None, {})
    assert "Scarica sul PC" in captured["actions"]
    assert "Taglia audio..." in captured["actions"]
    assert "Mostra nella cartella" not in captured["actions"]


def test_cutOnStreamSongFetchesAudioFirst(window, monkeypatch, tmp_path):
    from app import downloader
    from app.ui import main_window
    tempFile = tmp_path / "temp.m4a"
    tempFile.write_bytes(b"x")
    monkeypatch.setattr(downloader, "downloadTempAudio", lambda target: str(tempFile))
    opened = []

    class FakeCutDialog:
        def __init__(self, parent, song, callback, selection):
            opened.append(song)

        def exec(self):
            return 0

    monkeypatch.setattr(main_window, "CutDialog", FakeCutDialog)
    song = window.database.findSongByUrl("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    window.openCutDialog(song)
    assert waitFor(lambda: opened)
    assert opened[0]["path"] == str(tempFile) and opened[0]["streamOrigin"].startswith("stream:")


def test_replaceCutOfStreamSongBecomesFile(window, monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "musicDir", lambda: str(tmp_path))
    song = window.database.findSongByUrl("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    cutFile = tmp_path / "cut_tmp.mp3"
    import shutil, subprocess
    from app.config import ffmpegExe
    subprocess.run([ffmpegExe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=2", str(cutFile)], check=True)
    window._onCutDone(dict(song, path=str(tmp_path / "temp.m4a"), streamOrigin=song["path"]), str(cutFile), song["title"], True,
                      {"mode": "keep", "startMs": 0, "endMs": 2000})
    updated = window.database.getSong(song["id"])
    assert not updated["path"].startswith("stream:") and updated["path"].startswith(str(tmp_path))
    import os
    assert os.path.isfile(updated["path"])


def test_deleteSongMovesFileToTrash(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Yes)
    filePath = tmp_path / "da_eliminare.mp3"
    filePath.write_bytes(b"x")
    songId = window.database.addSong(str(filePath), "Da eliminare", "", "", 1)
    window.deleteSongs([window.database.getSong(songId)])
    assert window.database.getSong(songId) is None
    assert not filePath.exists()


def test_downloadReplacesStreamSong(window, tmp_path):
    song = window.database.findSongByUrl("https://www.youtube.com/watch?v=bbbbbbbbbbb")
    filePath = tmp_path / "Artista - Due.mp3"
    filePath.write_bytes(b"x")
    window._onSongDownloaded({"path": str(filePath), "title": "Due", "artist": "Artista", "album": "", "duration": 100,
                              "cover": None, "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "replaceSongId": song["id"]}, None)
    updated = window.database.getSong(song["id"])
    assert updated["path"] == str(filePath)
    assert len([row for row in window.database.allSongs() if row["url"] == song["url"]]) == 1


def test_hiddenSongSavedWhenAddedToPlaylist(window):
    hiddenId = window.database.addStreamSong("https://youtu.be/ccccccccccc", "Amico", "", "", 1, None, hidden=True)
    playlistId = window.database.createPlaylist("Mia")
    window.addToPlaylist(playlistId, [hiddenId])
    assert window.database.getSong(hiddenId)["hidden"] == 0


def test_streamingIsDefault():
    from app.config import settings
    assert settings.get("streamOnly") is True
    assert settings.get("streamVideo") is True


def test_videoStreamsWithoutDownload(window, monkeypatch, tmp_path):
    from app import downloader
    from app.config import settings
    calls = []
    monkeypatch.setattr(downloader, "resolveVideoStream", lambda target, height: calls.append((target, height)) or "http://127.0.0.1:9/video.mp4")
    monkeypatch.setattr(window, "_activeForVideo", lambda: True)
    songId = window.database.addStreamSong("https://www.youtube.com/watch?v=vvvvvvvvvvv", "Con video", "", "", 100, None)
    song = window.database.getSong(songId)
    assert window.videoSourceFor(song) is None
    assert window.videoStreamLoading(song)
    assert waitFor(lambda: not window.videoStreamLoading(song))
    assert window.videoSourceFor(song) == "http://127.0.0.1:9/video.mp4"
    assert ("https://www.youtube.com/watch?v=vvvvvvvvvvv", int(settings.get("videoQuality"))) in calls
    videoFile = tmp_path / "v.mp4"
    videoFile.write_bytes(b"x")
    window.database.updateSong(songId, videoPath=str(videoFile))
    assert window.videoSourceFor(song) == str(videoFile)
    settings.set("streamVideo", False)
    window.database.updateSong(songId, videoPath=None)
    assert window.videoSourceFor(song) is None
    settings.set("streamVideo", True)


def test_recentShowsFriendsSongsToo(window):
    hiddenId = window.database.addStreamSong("https://youtu.be/rrrrrrrrrrr", "Messa da amico", "", "", 100, None, hidden=True)
    window.database.registerPlay(hiddenId)
    window.navigate("recent")
    titles = [song["title"] for song in window.recentPage.table.visibleSongs()]
    assert titles[0] == "Messa da amico"
    assert "Messa da amico" not in [song["title"] for song in window.database.allSongs()]
    assert len(titles) <= 15
