import pytest
from PySide6.QtCore import QUrl

from tests.broker import localBroker, waitFor  # noqa: F401


@pytest.fixture(scope="module")
def window(localBroker):
    from app.ui.main_window import MainWindow
    mainWindow = MainWindow()
    mainWindow.show()
    yield mainWindow
    mainWindow.together.leaveRoom()
    mainWindow.player.shutdown()


def test_createRoomFromPopupShowsBannerAndPeople(window):
    window.showTogether()
    popup = window.togetherPopup
    assert popup.isVisible()
    popup._create()
    assert window.together.code and window.together.code.startswith("SONUS-")
    assert window.togetherBanner.isVisible()
    assert "aspetto" in window.togetherLabel.text()
    assert waitFor(lambda: window.together.link.isConnected() and window.together.myId() in window.together.peers)
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text().startswith("sonus://join/SONUS-")
    window.together.leaveRoom()
    assert not window.togetherBanner.isVisible()


def test_invalidCodeShowsError(window):
    window.showTogether()
    popup = window.togetherPopup
    popup.codeEdit.setText("ciao")
    popup._join()
    assert not popup.errorLabel.isHidden()


def test_roomEffectsDoNotTouchMySavedOnesExceptBass(window):
    from app.config import settings
    songId = window.database.addStreamSong("https://youtu.be/eeeeeeeeeee", "Effetti", "", "", 100, None)
    song = window.database.getSong(songId)
    window.player.restoreSession([song], 0, 0)
    window._onEffectsChanged({"rate": 1.0, "keepPitch": True, "reverbWet": 0.0, "reverbSize": 1.8, "bassBoost": 0.0})
    window.together.createRoom()
    window._onEffectsChanged({"rate": 1.3, "keepPitch": True, "reverbWet": 0.2, "reverbSize": 2.0, "bassBoost": 0.4})
    assert settings.get("effects")["rate"] == 1.0 and settings.get("effects")["bassBoost"] == 0.4
    assert window.together.roomEffects["rate"] == 1.3 and "bassBoost" not in window.together.roomEffects
    assert window.effectsForSong(song)["rate"] == 1.3 and window.effectsForSong(song)["bassBoost"] == 0.4
    window.together.leaveRoom()
    window._onEffectsChanged({"rate": 1.1, "keepPitch": True, "reverbWet": 0.0, "reverbSize": 1.8, "bassBoost": 0.0})
    assert abs(settings.get("effects")["rate"] - 1.1) < 0.001
    settings.set("effects", {})


def test_effectsStayWhenTheSongChanges(window):
    from app.config import settings
    songIds = [window.database.addStreamSong(f"https://youtu.be/{index:011d}", f"Generale {index}", "", "", 100, None) for index in range(2)]
    window.player.streamResolver = lambda target, useCache=True: (_ for _ in ()).throw(RuntimeError("offline"))
    window.player.restoreSession(window.database.getSongs(songIds), 0, 0)
    window._onEffectsChanged({"rate": 1.2, "keepPitch": False, "reverbWet": 0.3, "reverbSize": 2.0, "bassBoost": 0.1})
    assert window.effectsForSong(window.database.getSong(songIds[1]))["rate"] == 1.2
    window.player.currentIndex = 1
    window.player._startSource(window.player.currentSong(), QUrl(), False, 0)
    assert abs(window.player.playbackRate() - 1.2) < 0.001 and abs(window.player.mediaPlayer.reverbWet - 0.3) < 0.001
    settings.set("effects", {})


def test_videoFpsSetting(window):
    from app.config import settings
    settings.set("videoFps", 0)
    window.applyVideoFps()
    assert abs(window.videoController.frameInterval - 0.9 / 12) < 1e-6
    settings.set("videoFps", 30)
    window.applyVideoFps()
    assert abs(window.videoController.frameInterval - 0.9 / 30) < 1e-6
    settings.set("videoFps", 0)


def test_playButtonShowsPauseWhileASongLoadsToPlay(window):
    window.player.loading = True
    window.player.loadAutoplay = True
    window.player.queue = [{"id": 1, "path": "stream:x", "title": "t"}]
    window.player.currentIndex = 0
    window.playerBar._updatePlayIcon()
    assert window.playerBar.playButton.toolTip().startswith("Pausa")
    window.player.togglePlay()
    assert not window.player.loadAutoplay
    assert window.playerBar.playButton.toolTip().startswith("Riproduci")
    window.player.loading = False


def test_sharePlaylistFromMenuAndJoinWithCode(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    songId = window.database.addStreamSong("https://youtu.be/fffffffffff", "Condivisa", "", "", 100, None)
    playlistId = window.database.createPlaylist("Da condividere")
    window.database.addToPlaylist(playlistId, [songId])
    window.sharePlaylist(playlistId)
    code = window.sharedPlaylists.codeOf(playlistId)
    assert code.startswith("SONUSP-")
    items = [window.playlistList.item(index).text() for index in range(window.playlistList.count())]
    assert any("Da condividere\nPlaylist condivisa" in text for text in items)
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == "sonus://join/" + code
    assert window.handleCode("ciao") is False


def test_copyDiagnosticsFromRoom(window):
    from PySide6.QtGui import QGuiApplication
    window.together.createRoom()
    assert waitFor(window.together.link.isConnected)
    print("[Link] riga di prova per la diagnostica")
    window.showTogether()
    window.togetherPopup._copyDiagnostics()
    text = QGuiApplication.clipboard().text()
    assert text.startswith("Synth Music ") and "CONNESSO" in text and "Stanza: sì" in text
    window.together.leaveRoom()
    window.togetherPopup.hide()
