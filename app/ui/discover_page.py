import hashlib
import os

from PySide6.QtCore import QEasingCurve, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .. import discover
from ..config import COVERS_DIR, DATA_DIR, settings
from ..workers import runInBackground
from . import effects, theme
from .views import Page, _bigPlayButton, _label

REMOTE_DIR = os.path.join(COVERS_DIR, "remote")
_imagePool = None
CARD_WIDTH = 176
COVER_SIZE = 152


def remoteImagePath(url):
    if not url:
        return None
    return os.path.join(REMOTE_DIR, hashlib.md5(url.encode("utf-8")).hexdigest() + ".jpg")


def cachedRemoteImage(url):
    path = remoteImagePath(url)
    return path if path and os.path.isfile(path) else None


def _downloadImage(url):
    from ..downloader import fetchBytes
    os.makedirs(REMOTE_DIR, exist_ok=True)
    path = remoteImagePath(url)
    if not os.path.isfile(path):
        data = fetchBytes(url, timeout=12)
        temporaryPath = path + ".part"
        with open(temporaryPath, "wb") as imageFile:
            imageFile.write(data)
        os.replace(temporaryPath, path)
    return path


def loadRemoteImage(url, callback):
    """Calls callback(path) with the cached image, downloading it in background the first time."""
    cached = cachedRemoteImage(url)
    if cached:
        callback(cached)
        return
    if not url:
        return

    def safeCallback(path):
        try:
            callback(path)
        except RuntimeError:
            pass

    global _imagePool
    if _imagePool is None:
        from PySide6.QtCore import QThreadPool
        _imagePool = QThreadPool()
        _imagePool.setMaxThreadCount(4)
    runInBackground(_downloadImage, url, onFinished=safeCallback, pool=_imagePool)


def circularPixmap(pixmap, size):
    return theme.roundedPixmap(pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                               .copy(0, 0, size, size), size // 2)


class DiscoverCard(QFrame):
    """Card for a track, an artist (round photo) or an album."""

    def __init__(self, title, subtitle, imageUrl, onClick, onPlay=None, onMenu=None, round_=False, seed=0):
        super().__init__()
        self.onClick = onClick
        self.onMenu = onMenu
        self.round = round_
        self.setObjectName("discoverCard")
        self.setFixedWidth(CARD_WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"QFrame#discoverCard {{ background: {theme.PANEL}; border-radius: 8px; }}"
                           f" QFrame#discoverCard:hover {{ background: {theme.HOVER}; }}")
        self.glow = effects.HoverGlow(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 14)
        layout.setSpacing(6)
        self.coverLabel = QLabel()
        self.coverLabel.setFixedSize(COVER_SIZE, COVER_SIZE)
        placeholder = theme.placeholderCover(COVER_SIZE, seed, "person" if round_ else "music")
        self.coverLabel.setPixmap(circularPixmap(placeholder, COVER_SIZE) if round_ else theme.roundedPixmap(placeholder, 6))
        layout.addWidget(self.coverLabel)
        self.playButton = None
        if onPlay:
            self.playButton = _bigPlayButton()
            self.playButton.setFixedSize(44, 44)
            self.playButton.setParent(self.coverLabel)
            self.playButton.move(COVER_SIZE - 52, COVER_SIZE - 52)
            self.playButton.clicked.connect(onPlay)
            self.playButton.hide()
        titleLabel = _label("", "songTitle")
        titleLabel.setText(titleLabel.fontMetrics().elidedText(title, Qt.ElideRight, 150))
        titleLabel.setToolTip(title)
        subtitleLabel = _label("", "small")
        subtitleLabel.setText(subtitleLabel.fontMetrics().elidedText(subtitle, Qt.ElideRight, 150))
        if round_:
            titleLabel.setAlignment(Qt.AlignHCenter)
            subtitleLabel.setAlignment(Qt.AlignHCenter)
        layout.addWidget(titleLabel)
        layout.addWidget(subtitleLabel)
        loadRemoteImage(imageUrl, self._setImage)

    def _setImage(self, path):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        if self.round:
            self.coverLabel.setPixmap(circularPixmap(pixmap, COVER_SIZE))
        else:
            self.coverLabel.setPixmap(theme.coverPixmap(path, COVER_SIZE, 0, 6))

    def enterEvent(self, event):
        if self.playButton:
            self.playButton.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.playButton:
            self.playButton.hide()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.onClick()
        elif event.button() == Qt.RightButton and self.onMenu:
            self.onMenu(event.globalPosition().toPoint())


class SkeletonCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedSize(CARD_WIDTH, 232)
        self.setObjectName("skeleton")
        self._setShade(QColor(theme.PANEL))
        if settings.get("fxTransitions"):
            self.animation = QVariantAnimation(self)
            self.animation.setStartValue(QColor(theme.PANEL))
            self.animation.setEndValue(QColor(theme.HOVER))
            self.animation.setDuration(800)
            self.animation.setEasingCurve(QEasingCurve.InOutSine)
            self.animation.setLoopCount(-1)
            self.animation.valueChanged.connect(self._setShade)
            self.animation.start()

    def _setShade(self, color):
        self.setStyleSheet(f"QFrame#skeleton {{ background: {color.name()}; border-radius: 8px; }}")


class TrackRow(QFrame):
    def __init__(self, number, track, owned, onPlay, onMenu):
        super().__init__()
        self.onPlay = onPlay
        self.onMenu = onMenu
        self.setObjectName("trackRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"QFrame#trackRow {{ border-radius: 6px; }} QFrame#trackRow:hover {{ background: {theme.HOVER}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(12)
        numberLabel = _label(str(number), "sub")
        numberLabel.setFixedWidth(22)
        layout.addWidget(numberLabel)
        self.coverLabel = QLabel()
        self.coverLabel.setFixedSize(42, 42)
        self.coverLabel.setPixmap(theme.placeholderCover(42, number, "music"))
        layout.addWidget(self.coverLabel)
        column = QVBoxLayout()
        column.setSpacing(0)
        titleLabel = _label(track["title"], "songTitle")
        titleLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        column.addWidget(titleLabel)
        albumLabel = _label(track.get("album") or "", "small")
        albumLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        column.addWidget(albumLabel)
        layout.addLayout(column, 1)
        if owned:
            ownedLabel = QLabel()
            ownedLabel.setPixmap(theme.icon("check", theme.ACCENT, 16).pixmap(16, 16))
            ownedLabel.setToolTip("È già nella tua libreria")
            layout.addWidget(ownedLabel)
        layout.addWidget(_label(theme.formatTime((track.get("duration") or 0) * 1000), "small"))
        loadRemoteImage(track.get("image"), lambda path: self.coverLabel.setPixmap(theme.coverPixmap(path, 42, 0, 4)))

    def mouseDoubleClickEvent(self, event):
        self.onPlay()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.onMenu(event.globalPosition().toPoint())


class DiscoverPage(Page):
    """Scopri: suggestions from what you listen to (Deezer + YouTube), artists, new releases and charts."""

    def __init__(self, window):
        super().__init__(window)
        self.cache = discover.DiscoverCache(os.path.join(DATA_DIR, "discover_cache.json"))
        self.client = discover.DeezerClient()
        self.data = None
        self.loading = False
        self.loadSerial = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.mainScroll = QScrollArea()
        self.mainScroll.setWidgetResizable(True)
        self.mainScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stack.addWidget(self.mainScroll)
        self.artistScroll = QScrollArea()
        self.artistScroll.setWidgetResizable(True)
        self.artistScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stack.addWidget(self.artistScroll)

    # ---------- loading ----------
    def refresh(self):
        self.stack.setCurrentWidget(self.mainScroll)
        if self.data is None:
            self.data = self.cache.load()
        if self.data is not None:
            self._render()
        elif not self.loading:
            self.reload()

    def reload(self):
        self.loadSerial += 1
        serial = self.loadSerial
        self.loading = True
        self._renderSkeleton()
        profile = discover.libraryProfile(self.window.database)
        self.ownedKeys = set(profile["ownedKeys"])
        runInBackground(discover.buildDiscover, profile, self.client,
                        onFinished=lambda result: self._onLoaded(serial, result),
                        onError=lambda message: self._onLoaded(serial, None, message))

    def _onLoaded(self, serial, result, message=None):
        if serial != self.loadSerial:
            return
        self.loading = False
        if result is not None and result.get("sections"):
            self.data = result
            self.cache.save(result)
        elif result is not None:
            self.data = result
        try:
            self._render(message if result is None else None)
        except RuntimeError:
            pass

    # ---------- main view ----------
    def _newContent(self, scroll):
        content = QWidget()
        content.setObjectName("discoverContent")
        content.setStyleSheet("QWidget#discoverContent { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                              f" stop:0 {QColor(theme.ACCENT).darker(420).name()}, stop:0.35 rgba(0,0,0,0)); }}")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(14)
        old = scroll.takeWidget()
        if old is not None:
            old.hide()
            old.deleteLater()
        scroll.setWidget(content)
        return layout

    def _header(self, layout):
        row = QHBoxLayout()
        column = QVBoxLayout()
        column.addWidget(_label("Scopri", "h1"))
        column.addWidget(_label("Consigli in base a cosa ascolti, artisti nuovi, uscite e classifiche.", "sub"))
        row.addLayout(column, 1)
        self.refreshButton = QPushButton("Aggiorna")
        self.refreshButton.setIcon(theme.icon("refresh", theme.TEXT, 16))
        self.refreshButton.setEnabled(not self.loading)
        self.refreshButton.clicked.connect(self.reload)
        row.addWidget(self.refreshButton, 0, Qt.AlignTop)
        layout.addLayout(row)

    def _renderSkeleton(self):
        layout = self._newContent(self.mainScroll)
        self._header(layout)
        for _ in range(3):
            layout.addSpacing(8)
            bar = QFrame()
            bar.setFixedSize(260, 22)
            bar.setStyleSheet(f"background: {theme.PANEL}; border-radius: 6px;")
            layout.addWidget(bar)
            row = QHBoxLayout()
            row.setSpacing(14)
            for _ in range(6):
                row.addWidget(SkeletonCard())
            row.addStretch()
            layout.addLayout(row)
        layout.addStretch()

    def _render(self, errorMessage=None):
        layout = self._newContent(self.mainScroll)
        self._header(layout)
        sections = (self.data or {}).get("sections") or []
        if not sections:
            text = "Non riesco a caricare i consigli: controlla la connessione e premi Aggiorna." if errorMessage or self.data is None \
                else "Ascolta qualche canzone e qui arriveranno i consigli per te."
            emptyLabel = _label(text, "sub", wrap=True)
            layout.addSpacing(30)
            layout.addWidget(emptyLabel, 0, Qt.AlignHCenter)
        for section in sections:
            rowLayout = self._row(layout, section["title"])
            items = section["items"]
            for index, item in enumerate(items):
                rowLayout.addWidget(self._card(section, items, index, item))
            rowLayout.addStretch()
        layout.addStretch()

    def _row(self, layout, title):
        layout.addSpacing(8)
        layout.addWidget(_label(title, "h2"))
        rowScroll = QScrollArea()
        rowScroll.setWidgetResizable(True)
        rowScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rowScroll.setFixedHeight(262)
        rowWidget = QWidget()
        rowLayout = QHBoxLayout(rowWidget)
        rowLayout.setContentsMargins(0, 0, 0, 10)
        rowLayout.setSpacing(14)
        rowScroll.setWidget(rowWidget)
        layout.addWidget(rowScroll)
        return rowLayout

    def _card(self, section, items, index, item):
        if section["kind"] == "artists":
            return DiscoverCard(item["name"], "Artista", item.get("image"), lambda: self.openArtist(item), round_=True, seed=index)
        if section["kind"] == "albums":
            subtitle = f"{item['artist']} · {'Singolo' if item.get('type') == 'single' else 'Album'}"
            return DiscoverCard(item["title"], subtitle, item.get("image"), lambda: self.playAlbum(item),
                                onPlay=lambda: self.playAlbum(item), seed=index)
        return DiscoverCard(item["title"], item.get("artist") or "", item.get("image"),
                            lambda: self.window.playDiscovered(items, index),
                            onPlay=lambda: self.window.playDiscovered(items, index),
                            onMenu=lambda position: self.trackMenu(item, position), seed=index)

    # ---------- actions ----------
    def trackMenu(self, track, position):
        window = self.window
        menu = QMenu(self)
        menu.addAction(theme.icon("play"), "Riproduci", lambda: window.playDiscovered([track], 0))
        menu.addAction(theme.icon("queue"), "Aggiungi alla coda", lambda: window.queueDiscovered([track]))
        menu.addAction(theme.icon("add"), "Salva nella libreria", lambda: window.saveDiscovered(track))
        playlistMenu = menu.addMenu(theme.icon("add"), "Aggiungi a playlist")
        for playlist in window.database.playlists():
            playlistMenu.addAction(playlist["name"], lambda pid=playlist["id"]: window.addToPlaylist(pid, [window.discoveredSong(track)["id"]]))
        menu.addAction(theme.icon("download"), "Scarica sul PC", lambda: window.downloadStreamSongs([window.discoveredSong(track)]))
        menu.exec(position)

    def playAlbum(self, album):
        self.window.showStatus(f"Carico \"{album['title']}\"...", 8000)
        runInBackground(self.client.albumTracks, album["id"], album,
                        onFinished=lambda tracks: tracks and self.window.playDiscovered(tracks, 0),
                        onError=lambda message: self.window.showStatus("Album non disponibile ora", 4000))

    # ---------- artist page ----------
    def openArtist(self, artist):
        layout = self._newContent(self.artistScroll)
        self.stack.setCurrentWidget(self.artistScroll)
        backButton = QToolButton()
        backButton.setIcon(theme.icon("back", theme.TEXT, 18))
        backButton.setIconSize(QSize(18, 18))
        backButton.setToolTip("Torna a Scopri")
        backButton.clicked.connect(lambda: self.stack.setCurrentWidget(self.mainScroll))
        layout.addWidget(backButton, 0, Qt.AlignLeft)
        header = QHBoxLayout()
        header.setSpacing(24)
        photoLabel = QLabel()
        photoLabel.setFixedSize(180, 180)
        photoLabel.setPixmap(circularPixmap(theme.placeholderCover(180, 2, "person"), 180))
        loadRemoteImage(artist.get("image"), lambda path: photoLabel.setPixmap(circularPixmap(QPixmap(path), 180)))
        header.addWidget(photoLabel)
        column = QVBoxLayout()
        column.addStretch()
        column.addWidget(_label("Artista", "small"))
        column.addWidget(_label(artist["name"], "h1"))
        column.addStretch()
        header.addLayout(column, 1)
        layout.addLayout(header)
        self.artistPopularBox = QVBoxLayout()
        self.artistPopularBox.setSpacing(2)
        layout.addWidget(_label("Popolari", "h2"))
        loadingLabel = _label("Caricamento...", "sub")
        self.artistPopularBox.addWidget(loadingLabel)
        layout.addLayout(self.artistPopularBox)
        mine = [song for song in self.window.database.searchSongs(artist["name"])
                if discover.normalizeText(discover.mainArtist(song.get("artist"))) == discover.normalizeText(artist["name"])]
        if mine:
            layout.addWidget(_label("Le tue canzoni", "h2"))
            for number, song in enumerate(mine[:10], 1):
                track = {"title": song["title"], "album": song.get("album") or "", "duration": song.get("duration") or 0, "image": None}
                row = TrackRow(number, track, False, lambda s=mine, i=number - 1: self.window.playSongs(s, i),
                               lambda position, s=song: self.window.showSongMenu([s], position, {}))
                row.coverLabel.setPixmap(theme.coverPixmap(song.get("cover"), 42, song["id"], 4))
                layout.addWidget(row)
        self.artistRelatedLayout = None
        relatedTitle = _label("Artisti simili", "h2")
        relatedTitle.hide()
        layout.addWidget(relatedTitle)
        relatedHolder = QVBoxLayout()
        layout.addLayout(relatedHolder)
        layout.addStretch()
        serial = id(layout)
        self.artistSerial = serial

        def load():
            results = []
            for loader in (self.client.topTracks, self.client.relatedArtists):
                try:
                    results.append(loader(artist["id"], 10))
                except Exception:
                    results.append(None)
            if results[0] is None and results[1] is None:
                raise RuntimeError("offline")
            return results[0] or [], results[1] or []

        def onLoaded(result):
            if self.artistSerial != serial:
                return
            try:
                popular, related = result
                loadingLabel.hide()
                ownedKeys = getattr(self, "ownedKeys", None)
                if ownedKeys is None:
                    ownedKeys = self.ownedKeys = set(discover.libraryProfile(self.window.database)["ownedKeys"])
                for number, track in enumerate(popular, 1):
                    owned = discover.trackKeyOf(track["title"], track["artist"]) in ownedKeys
                    self.artistPopularBox.addWidget(TrackRow(number, track, owned,
                                                             lambda i=number - 1: self.window.playDiscovered(popular, i),
                                                             lambda position, t=track: self.trackMenu(t, position)))
                if related:
                    relatedTitle.show()
                    rowScroll = QScrollArea()
                    rowScroll.setWidgetResizable(True)
                    rowScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    rowScroll.setFixedHeight(262)
                    rowWidget = QWidget()
                    rowLayout = QHBoxLayout(rowWidget)
                    rowLayout.setContentsMargins(0, 0, 0, 10)
                    rowLayout.setSpacing(14)
                    for index, item in enumerate(related):
                        rowLayout.addWidget(DiscoverCard(item["name"], "Artista", item.get("image"),
                                                         lambda a=item: self.openArtist(a), round_=True, seed=index))
                    rowLayout.addStretch()
                    rowScroll.setWidget(rowWidget)
                    relatedHolder.addWidget(rowScroll)
            except RuntimeError:
                pass

        def onError(message):
            try:
                loadingLabel.setText("Non riesco a caricare l'artista ora (connessione?).")
            except RuntimeError:
                pass

        runInBackground(load, onFinished=onLoaded, onError=onError)
