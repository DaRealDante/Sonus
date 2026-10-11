import pytest

from tests.broker import pump, waitFor
from tests.test_discover import ROUTES, fakeFetch


@pytest.fixture(scope="module")
def window():
    from app.ui.main_window import MainWindow
    mainWindow = MainWindow()
    mainWindow.resize(1400, 860)
    mainWindow.show()
    yield mainWindow
    mainWindow.player.shutdown()


def test_discoverPageLoadsSectionsAndPlaysTrack(window, monkeypatch, tmp_path):
    from app import discover
    from app.discover import DeezerClient
    monkeypatch.setattr(discover, "youtubeMix", lambda videoId, limit: [])
    songId = window.database.addStreamSong("https://youtu.be/uuuuuuuuuuu", "Altrove", "Ultimo", "", 200, None)
    window.database.registerPlay(songId)
    page = window.discoverPage
    page.cache.path = str(tmp_path / "cache.json")
    page.data = None
    page.client = DeezerClient(fakeFetch(ROUTES))
    window.navigate("discover")
    assert waitFor(lambda: not page.loading, 10)
    titles = [section["title"] for section in page.data["sections"]]
    assert "Consigliati per te" in titles and "Artisti che potrebbero piacerti" in titles and "Top Italia" in titles
    pump(0.3)
    window.grab().save(str(tmp_path / "discover.png"))
    forYou = next(section for section in page.data["sections"] if section["id"] == "forYou")
    window.playDiscovered(forYou["items"], 0)
    current = window.player.currentSong()
    assert current["path"].startswith("stream:ytsearch1:") and current["hidden"] == 1
    assert current["title"] not in [song["title"] for song in window.database.allSongs()]
    window.saveDiscovered(forYou["items"][0])
    assert current["title"] in [song["title"] for song in window.database.allSongs()]


def test_artistPageOpens(window):
    page = window.discoverPage
    artist = next(section for section in page.data["sections"] if section["id"] == "similarArtists")["items"][0]
    page.openArtist(artist)
    assert page.stack.currentWidget() is page.artistScroll
    assert waitFor(lambda: page.artistPopularBox.count() > 1, 10)
