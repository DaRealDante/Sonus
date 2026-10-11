def test_cardPlayButtonKeepsItsSongs():
    """The round play button on a card used to pass True/False instead of the songs ('bool' object is not iterable)."""
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.ui.views import Card
    received = []
    songs = [{"id": 1}, {"id": 2}]
    card = Card(QPixmap(152, 152), "Titolo", "Artista", lambda s=songs, i=1: received.append(("open", s, i)),
                lambda s=songs, i=1: received.append(("play", s, i)))
    card.playButton.click()
    assert received == [("play", songs, 1)]
