import pytest

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


def test_effectsInRoomAreNotSavedToSong(window):
    songId = window.database.addStreamSong("https://youtu.be/eeeeeeeeeee", "Effetti", "", "", 100, None)
    song = window.database.getSong(songId)
    window.player.restoreSession([song], 0, 0)
    window.together.createRoom()
    window._onEffectsChanged({"rate": 1.3, "keepPitch": True, "reverbWet": 0.2, "reverbSize": 2.0})
    assert window.database.getSong(songId)["songRate"] == 1.0
    assert window.together.roomEffects["rate"] == 1.3
    window.together.leaveRoom()
    window._onEffectsChanged({"rate": 1.1, "keepPitch": True, "reverbWet": 0.0, "reverbSize": 1.8})
    assert abs(window.database.getSong(songId)["songRate"] - 1.1) < 0.001


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
