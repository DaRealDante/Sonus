import datetime
import os
import webbrowser

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import downloader, spotify_import
from ..config import settings
from ..workers import runInBackground
from . import effects, theme
from .song_table import SongTable


def _label(text, objectName=None, wrap=False):
    label = QLabel(text)
    if objectName:
        label.setObjectName(objectName)
    label.setWordWrap(wrap)
    return label


def _bigPlayButton(tooltip="Riproduci"):
    button = QToolButton()
    button.setObjectName("bigPlay")
    button.setFixedSize(56, 56)
    button.setIcon(theme.icon("play", theme.ACCENT_TEXT, 24))
    button.setIconSize(QSize(24, 24))
    button.setToolTip(tooltip)
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(lambda: effects.bounce(button, QSize(24, 24)))
    return button


def _iconButton(iconName, tooltip, size=40, iconSize=20, color=theme.SUBTEXT):
    button = QToolButton()
    button.setIcon(theme.icon(iconName, color, iconSize))
    button.setIconSize(QSize(iconSize, iconSize))
    button.setFixedSize(size, size)
    button.setToolTip(tooltip)
    button.setCursor(Qt.PointingHandCursor)
    return button


class Page(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("page")
        self.setAttribute(Qt.WA_StyledBackground, True)

    def refresh(self):
        pass

    def updateSong(self, song):
        for table in self.findChildren(SongTable):
            table.songModel.updateSong(song)

    def setCurrent(self, songId, isPlaying):
        for table in self.findChildren(SongTable):
            table.songModel.setCurrent(songId, isPlaying)

    def connectTable(self, table, context=None):
        table.playRequested.connect(lambda songs, index: self.window.playSongs(songs, index))
        table.menuRequested.connect(lambda songs, position: self.window.showSongMenu(songs, position, context or {}))
        table.favoriteClicked.connect(self.window.toggleFavorite)
        current = self.window.player.currentSong()
        table.songModel.setCurrent(current.get("id") if current else None, self.window.player.isPlaying())


class ElidedLabel(QLabel):
    def __init__(self, text="", objectName=None):
        super().__init__()
        if objectName:
            self.setObjectName(objectName)
        self.fullText = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):
        self.fullText = text or ""
        self.setToolTip(self.fullText)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self.fullText, Qt.ElideRight, max(20, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def showEvent(self, event):
        super().showEvent(event)
        self._elide()


class HeaderBanner(QFrame):
    def __init__(self, colorTop="#535353"):
        super().__init__()
        self.setObjectName("banner")
        self.setColor(colorTop)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 16)
        layout.setSpacing(22)
        self.setFixedHeight(214)
        self.coverLabel = QLabel()
        self.coverLabel.setFixedSize(170, 170)
        layout.addWidget(self.coverLabel, 0, Qt.AlignBottom)
        textColumn = QVBoxLayout()
        textColumn.setSpacing(6)
        textColumn.addStretch()
        self.kindLabel = _label("Playlist", "small")
        self.titleLabel = ElidedLabel("", "h1")
        self.descriptionLabel = ElidedLabel("", "sub")
        self.statsLabel = _label("", "small")
        textColumn.addWidget(self.kindLabel)
        textColumn.addWidget(self.titleLabel)
        textColumn.addWidget(self.descriptionLabel)
        textColumn.addWidget(self.statsLabel)
        layout.addLayout(textColumn, 1)

    def setColor(self, colorTop):
        self.setStyleSheet(
            f"QFrame#banner {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {colorTop}, stop:1 rgba(0,0,0,0));"
            f" border-top-left-radius: 10px; border-top-right-radius: 10px; }}"
        )


def _songStats(songs):
    totalSeconds = sum(song.get("duration") or 0 for song in songs)
    return f"{len(songs)} brani · {theme.formatTotal(totalSeconds)}"


class SongListPage(Page):
    """Banner + action row + filterable song table."""

    def __init__(self, window, reorderable=False, bannerColor="#535353"):
        super().__init__(window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.banner = HeaderBanner(bannerColor)
        layout.addWidget(self.banner)
        actionRow = QHBoxLayout()
        actionRow.setContentsMargins(28, 12, 28, 8)
        actionRow.setSpacing(12)
        self.playButton = _bigPlayButton()
        self.playButton.clicked.connect(lambda: self.playAll())
        self.shuffleButton = _iconButton("shuffle", "Riproduci in ordine casuale", 44, 24)
        self.shuffleButton.clicked.connect(lambda: self.playAll(shuffled=True))
        actionRow.addWidget(self.playButton)
        actionRow.addWidget(self.shuffleButton)
        self.actionRow = actionRow
        self.extraActions = QHBoxLayout()
        self.extraActions.setSpacing(6)
        actionRow.addLayout(self.extraActions)
        actionRow.addStretch()
        self.filterEdit = QLineEdit()
        self.filterEdit.setPlaceholderText("Cerca in questa lista")
        self.filterEdit.setClearButtonEnabled(True)
        self.filterEdit.setFixedWidth(240)
        actionRow.addWidget(self.filterEdit)
        layout.addLayout(actionRow)
        self.table = SongTable(reorderable=reorderable)
        self.table.setMinimumHeight(170)
        self.filterEdit.textChanged.connect(self.table.setFilterText)
        tableWrap = QVBoxLayout()
        tableWrap.setContentsMargins(20, 0, 12, 0)
        tableWrap.addWidget(self.table)
        layout.addLayout(tableWrap, 1)
        self.emptyLabel = _label("", "sub")
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        self.emptyLabel.hide()
        layout.addWidget(self.emptyLabel)

    def setSongs(self, songs, emptyText=""):
        self.table.setSongs(songs)
        self.banner.statsLabel.setText(_songStats(songs))
        self.emptyLabel.setText(emptyText)
        self.emptyLabel.setVisible(not songs and bool(emptyText))
        self.playButton.setEnabled(bool(songs))

    def playAll(self, shuffled=False):
        songs = self.table.visibleSongs()
        if songs:
            self.window.playSongs(songs, None if shuffled else 0, shuffled=shuffled)


class LibraryPage(SongListPage):
    def __init__(self, window):
        super().__init__(window, bannerColor="#1E3264")
        self.banner.kindLabel.setText("Libreria")
        self.banner.titleLabel.setText("Tutti i brani")
        self.banner.descriptionLabel.setText("Trascina qui file audio o cartelle per importarli.")
        self.banner.coverLabel.setPixmap(theme.placeholderCover(170, 1, "library"))
        importButton = QPushButton("Importa file")
        importButton.setIcon(theme.icon("file", theme.TEXT, 16))
        importButton.clicked.connect(lambda: self.window.importFiles())
        folderButton = QPushButton("Importa cartella")
        folderButton.setIcon(theme.icon("folder", theme.TEXT, 16))
        folderButton.clicked.connect(self.window.importFolder)
        spotifyButton = QPushButton("Importa da Spotify")
        spotifyButton.setIcon(theme.icon("link", theme.TEXT, 16))
        spotifyButton.clicked.connect(self.window.askSpotifyLink)
        self.extraActions.addWidget(importButton)
        self.extraActions.addWidget(folderButton)
        self.extraActions.addWidget(spotifyButton)
        self.connectTable(self.table, {"library": True})
        self.table.deletePressed.connect(self.window.deleteSongs)

    def refresh(self):
        self.setSongs(self.window.database.allSongs(), "La libreria è vuota: importa file o cerca su YouTube.")


class FavoritesPage(SongListPage):
    def __init__(self, window):
        super().__init__(window, bannerColor="#4527A0")
        self.banner.kindLabel.setText("Playlist")
        self.banner.titleLabel.setText("Brani che ti piacciono")
        self.banner.coverLabel.setPixmap(theme.placeholderCover(170, 0, "heartFill"))
        self.connectTable(self.table, {"favorites": True})

    def refresh(self):
        self.setSongs(self.window.database.favoriteSongs(), "Premi il cuore su una canzone per salvarla qui.")


class RecentPage(SongListPage):
    LIMIT = 15

    def __init__(self, window):
        super().__init__(window, bannerColor="#0D5C63")
        self.banner.kindLabel.setText("Playlist")
        self.banner.titleLabel.setText("Recenti")
        self.banner.descriptionLabel.setText("Le ultime 15 canzoni ascoltate: le tue e quelle messe dagli amici in Ascolta insieme.")
        self.banner.coverLabel.setPixmap(theme.placeholderCover(170, 4, "clock"))
        self.connectTable(self.table, {"recent": True})

    def refresh(self):
        self.setSongs(self.window.database.recentlyPlayed(self.LIMIT, includeHidden=True),
                      "Qui compaiono le ultime canzoni che ascolti.")


class PlaylistPage(SongListPage):
    def __init__(self, window):
        super().__init__(window, reorderable=True, bannerColor="#3A3A3A")
        self.playlistId = None
        addButton = _iconButton("add", "Aggiungi file a questa playlist", 40, 20)
        addButton.clicked.connect(lambda: self.window.importFiles(self.playlistId))
        editButton = _iconButton("edit", "Modifica dettagli", 40, 20)
        editButton.clicked.connect(lambda: self.window.editPlaylist(self.playlistId))
        moreButton = _iconButton("more", "Altre opzioni", 40, 20)
        moreButton.clicked.connect(lambda: self._moreMenu(moreButton))
        self.extraActions.addWidget(addButton)
        self.extraActions.addWidget(editButton)
        self.extraActions.addWidget(moreButton)
        self.banner.coverLabel.setCursor(Qt.PointingHandCursor)
        self.banner.coverLabel.mousePressEvent = lambda event: self.window.editPlaylist(self.playlistId)
        self.table.reorderRequested.connect(self._onReorder)
        self.table.deletePressed.connect(lambda songs: self.window.removeFromPlaylist(self.playlistId, songs))
        self.table.menuRequested.connect(lambda songs, position: self.window.showSongMenu(songs, position, {"playlistId": self.playlistId}))
        self.table.playRequested.connect(lambda songs, index: self.window.playSongs(songs, index))
        self.table.favoriteClicked.connect(self.window.toggleFavorite)

    _palette = ["#5038A0", "#1E3264", "#8C1932", "#056952", "#BA5D07", "#503750", "#283C46", "#7D4B32"]

    def setPlaylist(self, playlistId):
        self.playlistId = playlistId
        self.filterEdit.clear()
        self.refresh()

    def refresh(self):
        playlist = self.window.database.getPlaylist(self.playlistId) if self.playlistId else None
        if not playlist:
            return
        songs = self.window.database.playlistSongs(self.playlistId)
        self.banner.setColor(self._palette[playlist["id"] % len(self._palette)])
        self.banner.titleLabel.setText(playlist["name"])
        self.banner.descriptionLabel.setText(playlist.get("description") or "")
        self.banner.descriptionLabel.setVisible(bool(playlist.get("description")))
        self.banner.coverLabel.setPixmap(self.window.playlistCover(playlist, 170, 6))
        self.setSongs(songs, "Questa playlist è vuota. Aggiungi brani dal menu (tasto destro) o con il pulsante +.")

    def _onReorder(self, entryIds, targetRow):
        songs = self.table.songModel.songs
        moving = [song for song in songs if song.get("entryId") in entryIds]
        if not moving:
            return
        before = [song for song in songs[:targetRow] if song.get("entryId") not in entryIds]
        after = [song for song in songs[targetRow:] if song.get("entryId") not in entryIds]
        newOrder = before + moving + after
        self.window.database.setPlaylistOrder([song["entryId"] for song in newOrder])
        self.refresh()

    def _moreMenu(self, button):
        menu = QMenu(self)
        menu.addAction(theme.icon("play"), "Riproduci", self.playAll)
        menu.addAction(theme.icon("queue"), "Aggiungi tutto alla coda", lambda: self.window.player.addToQueue(self.table.visibleSongs()))
        menu.addAction(theme.icon("edit"), "Modifica dettagli", lambda: self.window.editPlaylist(self.playlistId))
        menu.addAction(theme.icon("add"), "Aggiungi file...", lambda: self.window.importFiles(self.playlistId))
        menu.addSeparator()
        menu.addAction(theme.icon("delete"), "Elimina playlist", lambda: self.window.deletePlaylist(self.playlistId))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))


class Card(QFrame):
    def __init__(self, pixmap, title, subtitle, onClick, onPlay=None, round_=False):
        super().__init__()
        self.onClick = onClick
        self.setObjectName("card")
        self.setFixedWidth(176)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#card {{ background: {theme.PANEL}; border-radius: 8px; }} QFrame#card:hover {{ background: {theme.HOVER}; }}"
        )
        self.glow = effects.HoverGlow(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 14)
        layout.setSpacing(6)
        coverLabel = QLabel()
        coverLabel.setFixedSize(152, 152)
        coverLabel.setPixmap(pixmap)
        layout.addWidget(coverLabel)
        if onPlay:
            playButton = _bigPlayButton()
            playButton.setFixedSize(44, 44)
            playButton.setParent(coverLabel)
            playButton.move(152 - 52, 152 - 52)
            playButton.clicked.connect(onPlay)
            playButton.hide()
            self.playButton = playButton
        else:
            self.playButton = None
        titleLabel = _label(title, "songTitle")
        titleLabel.setMaximumWidth(152)
        titleLabel.setText(titleLabel.fontMetrics().elidedText(title, Qt.ElideRight, 150))
        subtitleLabel = _label("", "small")
        subtitleLabel.setText(subtitleLabel.fontMetrics().elidedText(subtitle, Qt.ElideRight, 150))
        layout.addWidget(titleLabel)
        layout.addWidget(subtitleLabel)

    def enterEvent(self, event):
        if self.playButton:
            self.playButton.show()

    def leaveEvent(self, event):
        if self.playButton:
            self.playButton.hide()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.onClick()


class QuickTile(QFrame):
    def __init__(self, pixmap, title, onClick, onPlay):
        super().__init__()
        self.onClick = onClick
        self.setObjectName("tile")
        self.setFixedHeight(64)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#tile { background: rgba(255,255,255,0.07); border-radius: 6px; }"
            "QFrame#tile:hover { background: rgba(255,255,255,0.16); }"
        )
        self.glow = effects.HoverGlow(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(12)
        coverLabel = QLabel()
        coverLabel.setFixedSize(64, 64)
        coverLabel.setPixmap(pixmap)
        layout.addWidget(coverLabel)
        titleLabel = _label(title, "songTitle")
        titleLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(titleLabel, 1)
        self.playButton = _bigPlayButton()
        self.playButton.setFixedSize(40, 40)
        self.playButton.clicked.connect(onPlay)
        self.playButton.hide()
        layout.addWidget(self.playButton)

    def enterEvent(self, event):
        self.playButton.show()

    def leaveEvent(self, event):
        self.playButton.hide()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.onClick()


class HomePage(Page):
    def __init__(self, window):
        super().__init__(window)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scrollArea = QScrollArea()
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scrollArea)

    def _newContent(self):
        content = QWidget()
        content.setObjectName("homeContent")
        content.setStyleSheet(
            "QWidget#homeContent { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1F3B2C, stop:0.35 rgba(0,0,0,0)); }"
        )
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(28, 24, 28, 28)
        self.layout_.setSpacing(16)
        oldContent = self.scrollArea.takeWidget()
        if oldContent is not None:
            oldContent.hide()
            oldContent.deleteLater()
        self.scrollArea.setWidget(content)

    def refresh(self):
        self._newContent()
        hour = datetime.datetime.now().hour
        greeting = "Buongiorno" if 5 <= hour < 13 else ("Buon pomeriggio" if hour < 18 else "Buonasera")
        self.layout_.addWidget(_label(greeting, "h1"))
        database = self.window.database
        allSongs = database.allSongs()
        playlists = database.playlists()

        if not allSongs:
            emptyBox = QVBoxLayout()
            emptyBox.setSpacing(12)
            emptyBox.addSpacing(40)
            emptyBox.addWidget(_label("La tua libreria è vuota", "h2"), 0, Qt.AlignHCenter)
            emptyBox.addWidget(_label("Importa i tuoi MP3 oppure cerca canzoni su YouTube e scaricale.", "sub"), 0, Qt.AlignHCenter)
            buttonRow = QHBoxLayout()
            buttonRow.addStretch()
            importButton = QPushButton("Importa file")
            importButton.setObjectName("accent")
            importButton.clicked.connect(lambda: self.window.importFiles())
            searchButton = QPushButton("Cerca online")
            searchButton.clicked.connect(lambda: self.window.navigate("search"))
            buttonRow.addWidget(importButton)
            buttonRow.addWidget(searchButton)
            buttonRow.addStretch()
            emptyBox.addLayout(buttonRow)
            self.layout_.addLayout(emptyBox)
            self.layout_.addStretch()
            return

        tilesGrid = QGridLayout()
        tilesGrid.setSpacing(10)
        tiles = [("fav", None)] + [("playlist", playlist) for playlist in playlists[:7]]
        for index, (kind, playlist) in enumerate(tiles):
            if kind == "fav":
                pixmap = theme.roundedPixmap(theme.placeholderCover(64, 0, "heartFill"), 0)
                tile = QuickTile(pixmap, "Brani che ti piacciono", lambda: self.window.navigate("favorites"),
                                 lambda: self.window.playSongs(database.favoriteSongs(), 0))
            else:
                pixmap = self.window.playlistCover(playlist, 64, 0)
                tile = QuickTile(pixmap, playlist["name"],
                                 lambda pid=playlist["id"]: self.window.openPlaylist(pid),
                                 lambda pid=playlist["id"]: self.window.playSongs(database.playlistSongs(pid), 0))
            tilesGrid.addWidget(tile, index // 2, index % 2)
        self.layout_.addLayout(tilesGrid)

        self._addSongRow("Ascoltati di recente", database.recentlyPlayed(10))
        self._addSongRow("Aggiunti di recente", database.recentSongs(10))
        self._addSongRow("I più ascoltati", database.mostPlayed(10))
        if playlists:
            self._addPlaylistRow("Le tue playlist", playlists)
        self.layout_.addStretch()

    def _row(self, title):
        self.layout_.addSpacing(8)
        self.layout_.addWidget(_label(title, "h2"))
        rowScroll = QScrollArea()
        rowScroll.setWidgetResizable(True)
        rowScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rowScroll.setFixedHeight(262)
        rowWidget = QWidget()
        rowLayout = QHBoxLayout(rowWidget)
        rowLayout.setContentsMargins(0, 0, 0, 10)
        rowLayout.setSpacing(14)
        rowScroll.setWidget(rowWidget)
        self.layout_.addWidget(rowScroll)
        return rowLayout

    def _addSongRow(self, title, songs):
        if not songs:
            return
        rowLayout = self._row(title)
        for index, song in enumerate(songs):
            pixmap = theme.coverPixmap(song.get("cover"), 152, song.get("id") or 0, 6)
            rowLayout.addWidget(Card(
                pixmap, song.get("title") or "", song.get("artist") or "Artista sconosciuto",
                lambda s=songs, i=index: self.window.playSongs(s, i),
                lambda s=songs, i=index: self.window.playSongs(s, i),
            ))
        rowLayout.addStretch()

    def _addPlaylistRow(self, title, playlists):
        rowLayout = self._row(title)
        for playlist in playlists:
            rowLayout.addWidget(Card(
                self.window.playlistCover(playlist, 152, 6), playlist["name"], f"{playlist['songCount']} brani",
                lambda pid=playlist["id"]: self.window.openPlaylist(pid),
                lambda pid=playlist["id"]: self.window.playSongs(self.window.database.playlistSongs(pid), 0),
            ))
        rowLayout.addStretch()


class WebResultWidget(QFrame):
    def __init__(self, page, entry):
        super().__init__()
        self.page = page
        self.entry = entry
        self.setObjectName("webResult")
        self.setStyleSheet(
            "QFrame#webResult { background: transparent; border-radius: 6px; } QFrame#webResult:hover { background: #1F1F1F; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(14)
        self.thumbLabel = QLabel()
        self.thumbLabel.setFixedSize(112, 63)
        self.thumbLabel.setStyleSheet(f"background: {theme.ELEVATED}; border-radius: 4px;")
        layout.addWidget(self.thumbLabel)
        textColumn = QVBoxLayout()
        textColumn.setSpacing(2)
        titleLabel = _label(entry["title"], "songTitle")
        titleLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        titleLabel.setMinimumWidth(140)
        titleLabel.setToolTip(entry["title"])
        details = entry["channel"]
        if entry.get("duration"):
            details += f"  ·  {theme.formatTime(entry['duration'] * 1000)}"
        if entry.get("views"):
            details += f"  ·  {entry['views']:,} visualizzazioni".replace(",", ".")
        detailLabel = _label(details, "small")
        detailLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        textColumn.addStretch()
        textColumn.addWidget(titleLabel)
        textColumn.addWidget(detailLabel)
        self.progressBar = QProgressBar()
        self.progressBar.setFixedHeight(5)
        self.progressBar.hide()
        textColumn.addWidget(self.progressBar)
        textColumn.addStretch()
        layout.addLayout(textColumn, 1)
        self.statusLabel = _label("", "small")
        layout.addWidget(self.statusLabel)
        self.previewButton = _iconButton("play", "Ascolta anteprima (streaming)", 36, 18)
        self.previewButton.clicked.connect(lambda: self.page.togglePreview(self))
        self.openButton = _iconButton("globe", "Apri su YouTube", 36, 18)
        self.openButton.clicked.connect(lambda: webbrowser.open(entry["url"]))
        self.playlistButton = _iconButton("add", "Streaming, coda e playlist", 36, 18)
        self.playlistButton.clicked.connect(self._playlistMenu)
        streamOnly = bool(settings.get("streamOnly"))
        self.downloadButton = QPushButton("Aggiungi" if streamOnly else "Scarica")
        self.downloadButton.setIcon(theme.icon("cloud" if streamOnly else "download", "#000", 16))
        self.downloadButton.setToolTip("Aggiungi alla libreria solo in streaming (non scarica)" if streamOnly else "Scarica la canzone")
        self.downloadButton.setObjectName("accent")
        self.downloadButton.setMinimumWidth(104)
        self.downloadButton.clicked.connect(self._onMainButton)
        for widget in (self.previewButton, self.openButton, self.playlistButton, self.downloadButton):
            layout.addWidget(widget)

    def _onMainButton(self):
        window = self.page.window
        if settings.get("streamOnly"):
            window.addStreamEntries([self.entry])
            self.downloadButton.setText("Aggiunto")
            self.downloadButton.setIcon(theme.icon("check", "#000", 16))
        else:
            window.downloads.enqueue(self.entry)

    def _addTo(self, playlistId):
        window = self.page.window
        if settings.get("streamOnly"):
            window.addStreamEntries([self.entry], playlistId)
        else:
            window.downloads.enqueue(self.entry, playlistId)

    def _playlistMenu(self):
        window = self.page.window
        menu = QMenu(self)
        menu.addAction(theme.icon("play"), "Riproduci in streaming", lambda: window.addStreamEntries([self.entry], play=True))
        menu.addAction(theme.icon("queue"), "Aggiungi alla coda (streaming)", lambda: window.addStreamEntries([self.entry], queue=True))
        menu.addAction(theme.icon("cloud"), "Salva in libreria (solo streaming)", lambda: window.addStreamEntries([self.entry]))
        streamMenu = menu.addMenu(theme.icon("cloud"), "Aggiungi a playlist (solo streaming)")
        for playlist in window.database.playlists():
            streamMenu.addAction(playlist["name"], lambda pid=playlist["id"]: window.addStreamEntries([self.entry], pid))
        if settings.get("streamOnly"):
            menu.addAction(theme.icon("download"), "Scarica sul PC", lambda: window.downloads.enqueue(self.entry))
        menu.addSeparator()
        menu.addAction(theme.icon("add"), "Nuova playlist...", self._toNewPlaylist)
        menu.addSeparator()
        for playlist in window.database.playlists():
            menu.addAction(playlist["name"], lambda pid=playlist["id"]: self._addTo(pid))
        menu.exec(self.playlistButton.mapToGlobal(self.playlistButton.rect().bottomLeft()))

    def _toNewPlaylist(self):
        playlistId = self.page.window.createPlaylist()
        if playlistId:
            self._addTo(playlistId)

    def setThumbnail(self, pixmap):
        scaled = pixmap.scaled(112, 63, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        scaled = scaled.copy((scaled.width() - 112) // 2, (scaled.height() - 63) // 2, 112, 63)
        self.thumbLabel.setPixmap(theme.roundedPixmap(scaled, 4))

    def setPreviewing(self, active):
        self.previewButton.setIcon(theme.icon("pause" if active else "play", theme.ACCENT if active else theme.SUBTEXT, 18))

    def updateJob(self, job):
        status = job["status"]
        if status in ("queued", "search", "download", "convert", "video"):
            self.progressBar.show()
            self.progressBar.setValue(job["percent"])
            self.downloadButton.setEnabled(False)
            self.statusLabel.setText({"queued": "In coda", "search": "Cerco...", "download": f"{job['percent']}%",
                                      "convert": "Conversione...", "video": f"Video {job['percent']}%"}[status])
        elif status == "done":
            self.progressBar.hide()
            self.downloadButton.setEnabled(True)
            self.downloadButton.setText("Scaricato")
            self.downloadButton.setObjectName("")
            self.downloadButton.setStyle(self.downloadButton.style())
            self.downloadButton.setIcon(theme.icon("check", theme.ACCENT, 16))
            self.statusLabel.setText("")
        elif status == "error":
            self.progressBar.hide()
            self.downloadButton.setEnabled(True)
            self.downloadButton.setText("Riprova")
            self.statusLabel.setText("Errore")
            self.statusLabel.setToolTip(job["error"])


class SpotifyRow(QFrame):
    def __init__(self, page, trackInfo):
        super().__init__()
        self.page = page
        self.trackInfo = trackInfo
        self.setObjectName("spotifyRow")
        self.setStyleSheet("QFrame#spotifyRow { border-radius: 6px; } QFrame#spotifyRow:hover { background: #1F1F1F; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)
        indexLabel = _label(str(trackInfo["playlistIndex"] + 1), "small")
        indexLabel.setFixedWidth(28)
        indexLabel.setAlignment(Qt.AlignCenter)
        self.thumbLabel = QLabel()
        self.thumbLabel.setFixedSize(44, 44)
        self.thumbLabel.setPixmap(theme.placeholderCover(44, trackInfo["playlistIndex"]))
        textColumn = QVBoxLayout()
        textColumn.setSpacing(1)
        titleLabel = ElidedLabel(trackInfo["title"], "songTitle")
        detailLabel = ElidedLabel(f"{trackInfo['artist']}  ·  {theme.formatTime(trackInfo['durationMs'])}", "small")
        textColumn.addWidget(titleLabel)
        textColumn.addWidget(detailLabel)
        self.progressBar = QProgressBar()
        self.progressBar.setFixedHeight(4)
        self.progressBar.hide()
        textColumn.addWidget(self.progressBar)
        self.statusLabel = _label("", "small")
        self.downloadButton = _iconButton("download", "Scarica solo questo brano", 34, 18)
        self.downloadButton.clicked.connect(lambda: self.page.window.downloadSpotifyTracks([self.trackInfo], None))
        layout.addWidget(indexLabel)
        layout.addWidget(self.thumbLabel)
        layout.addLayout(textColumn, 1)
        layout.addWidget(self.statusLabel)
        layout.addWidget(self.downloadButton)

    def setThumbnail(self, pixmap):
        self.thumbLabel.setPixmap(theme.roundedPixmap(pixmap.scaled(44, 44, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).copy(0, 0, 44, 44), 4))

    def updateJob(self, job):
        status = job["status"]
        active = status in ("queued", "search", "download", "convert", "video")
        self.progressBar.setVisible(active)
        self.progressBar.setValue(job["percent"])
        self.downloadButton.setEnabled(not active)
        texts = {"queued": "In coda", "search": "Cerco...", "download": f"{job['percent']}%", "convert": "Conversione...",
                 "video": f"Video {job['percent']}%",
                 "done": "Scaricato", "error": "Errore"}
        self.statusLabel.setText(texts.get(status, ""))
        self.statusLabel.setToolTip(job.get("error") or "")
        if status == "done":
            self.downloadButton.setIcon(theme.icon("check", theme.ACCENT, 18))

    def markInLibrary(self):
        self.statusLabel.setText("Già in libreria")
        self.downloadButton.setIcon(theme.icon("check", theme.ACCENT, 18))


class SearchPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self.resultWidgets = {}
        self.thumbCache = {}
        self.currentPlaylistInfo = None
        self.currentSpotifyInfo = None
        self.searchSerial = 0
        self.previewWidget = None
        self.previewPlayer = QMediaPlayer(self)
        self.previewOutput = QAudioOutput(self)
        self.previewPlayer.setAudioOutput(self.previewOutput)
        self.previewPlayer.mediaStatusChanged.connect(self._onPreviewStatus)
        self.previewPlayer.errorOccurred.connect(lambda *args: self._stopPreview(error=True))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 0)
        layout.setSpacing(14)
        searchRow = QHBoxLayout()
        self.searchEdit = QLineEdit()
        self.searchEdit.setObjectName("searchBox")
        self.searchEdit.setPlaceholderText("Cosa vuoi ascoltare? (canzone, artista, link YouTube o link Spotify)")
        self.searchEdit.addAction(theme.icon("search", theme.SUBTEXT, 18), QLineEdit.LeadingPosition)
        self.searchEdit.setClearButtonEnabled(True)
        self.searchEdit.returnPressed.connect(self.searchWeb)
        self.searchEdit.textChanged.connect(self._onTextChanged)
        webButton = QPushButton("Cerca su YouTube")
        webButton.setObjectName("accent")
        webButton.setIcon(theme.icon("globe", "#000", 16))
        webButton.clicked.connect(self.searchWeb)
        searchRow.addWidget(self.searchEdit, 1)
        searchRow.addWidget(webButton)
        layout.addLayout(searchRow)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        localWidget = QWidget()
        localLayout = QVBoxLayout(localWidget)
        localLayout.setContentsMargins(0, 10, 0, 0)
        self.localTable = SongTable()
        self.connectTable(self.localTable, {"library": True})
        self.localEmpty = _label("Scrivi qualcosa per cercare nella tua libreria.", "sub")
        localLayout.addWidget(self.localEmpty)
        localLayout.addWidget(self.localTable, 1)
        self.tabs.addTab(localWidget, "Nella libreria")

        webWidget = QWidget()
        webLayout = QVBoxLayout(webWidget)
        webLayout.setContentsMargins(0, 10, 0, 0)
        webLayout.setSpacing(8)
        self.playlistBanner = QFrame()
        self.playlistBanner.setObjectName("importBanner")
        self.playlistBanner.setStyleSheet(f"QFrame#importBanner {{ background: {theme.ELEVATED}; border-radius: 8px; }}")
        bannerLayout = QHBoxLayout(self.playlistBanner)
        bannerLayout.setContentsMargins(14, 10, 14, 10)
        self.playlistBannerLabel = _label("", "h3")
        self.playlistBannerLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        importAllButton = QPushButton("Importa come playlist")
        importAllButton.setToolTip("Scarica tutti i brani e crea una nuova playlist")
        importAllButton.setMinimumWidth(importAllButton.sizeHint().width() + 20)
        self.importAllButton = importAllButton
        importAllButton.setObjectName("accent")
        importAllButton.setIcon(theme.icon("download", "#000", 16))
        importAllButton.clicked.connect(self._importWholePlaylist)
        bannerLayout.addWidget(self.playlistBannerLabel, 1)
        bannerLayout.addWidget(importAllButton)
        self.playlistBanner.hide()
        webLayout.addWidget(self.playlistBanner)
        self.webStatus = _label("Premi Invio o \"Cerca su YouTube\" per cercare online. Puoi anche incollare il link di un video o di una playlist YouTube, oppure di una playlist / album / brano Spotify.", "sub", wrap=True)
        webLayout.addWidget(self.webStatus)
        self.webList = QListWidget()
        self.webList.setSelectionMode(QAbstractItemView.NoSelection)
        self.webList.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.webList.setStyleSheet("QListWidget::item { padding: 0; } QListWidget::item:hover { background: transparent; }")
        webLayout.addWidget(self.webList, 1)
        self.tabs.addTab(webWidget, "Su YouTube")
        layout.addWidget(self.tabs, 1)

        self.window.downloads.jobUpdated.connect(self._onJobUpdated)
        self.window.downloads.jobAdded.connect(self._onJobUpdated)

    def focusSearch(self):
        self.searchEdit.setFocus()
        self.searchEdit.selectAll()

    def _onTextChanged(self, text):
        text = text.strip()
        if not text or downloader.isUrl(text):
            self.localTable.setSongs([])
            self.localEmpty.setVisible(True)
            self.localEmpty.setText("Scrivi qualcosa per cercare nella tua libreria.")
            return
        songs = self.window.database.searchSongs(text)
        self.localTable.setSongs(songs)
        self.localEmpty.setVisible(not songs)
        self.localEmpty.setText(f"Nessun risultato nella libreria per \"{text}\". Premi Invio per cercare su YouTube.")

    def refresh(self):
        self._onTextChanged(self.searchEdit.text())

    def searchWeb(self):
        query = self.searchEdit.text().strip()
        if not query:
            return
        self.tabs.setCurrentIndex(1)
        self.searchSerial += 1
        serial = self.searchSerial
        self._stopPreview()
        self.webList.clear()
        self.resultWidgets.clear()
        self.playlistBanner.hide()
        self.currentPlaylistInfo = None
        self.currentSpotifyInfo = None
        self.webStatus.show()
        if spotify_import.isSpotifyUrl(query):
            self.webStatus.setText("Leggo il link Spotify...")
            runInBackground(
                spotify_import.fetchSpotify, query,
                onFinished=lambda info: self._onSpotify(serial, info),
                onError=lambda message: serial == self.searchSerial and self.webStatus.setText(
                    f"Impossibile leggere il link Spotify (deve essere pubblico): {message}"),
            )
            return
        self.webStatus.setText("Ricerca in corso...")
        runInBackground(
            downloader.searchYoutube, query, int(settings.get("searchResults")),
            onFinished=lambda result: self._onResults(serial, result),
            onError=lambda message: serial == self.searchSerial and self.webStatus.setText(f"Errore nella ricerca: {message}"),
        )

    def _onResults(self, serial, result):
        if serial != self.searchSerial:
            return
        entries = result["entries"]
        if not entries:
            self.webStatus.setText("Nessun risultato trovato.")
            return
        self.webStatus.hide()
        self.currentPlaylistInfo = result if result.get("playlistTitle") else None
        if self.currentPlaylistInfo:
            self.playlistBannerLabel.setText(f"Playlist: {result['playlistTitle']}  ·  {len(entries)} brani")
            self.importAllButton.setText("Importa come playlist")
            self.playlistBanner.show()
        for entry in entries:
            widget = WebResultWidget(self, entry)
            item = QListWidgetItem(self.webList)
            item.setSizeHint(QSize(100, 76))
            self.webList.setItemWidget(item, widget)
            self.resultWidgets.setdefault(entry["url"], []).append(widget)
            for job in self.window.downloads.jobs:
                if downloader.jobKey(job["entry"]) == entry["url"]:
                    widget.updateJob(job)
            self._loadThumbnail(widget, entry.get("thumbnail"))

    def _onSpotify(self, serial, info):
        if serial != self.searchSerial:
            return
        tracks = info["tracks"]
        if not tracks:
            self.webStatus.setText("La playlist Spotify è vuota o privata.")
            return
        self.webStatus.hide()
        self.currentSpotifyInfo = info
        kindText = {"playlist": "Playlist Spotify", "album": "Album Spotify", "track": "Brano Spotify"}[info["kind"]]
        self.playlistBannerLabel.setText(f"{kindText}: {info['name']}  ·  {len(tracks)} brani")
        self.importAllButton.setText("Scarica il brano" if info["kind"] == "track" else "Importa come playlist")
        self.playlistBanner.show()
        for trackInfo in tracks:
            row = SpotifyRow(self, trackInfo)
            item = QListWidgetItem(self.webList)
            item.setSizeHint(QSize(100, 60))
            self.webList.setItemWidget(item, row)
            key = downloader.jobKey({"spotify": trackInfo})
            self.resultWidgets.setdefault(key, []).append(row)
            for job in self.window.downloads.jobs:
                if downloader.jobKey(job["entry"]) == key:
                    row.updateJob(job)
            if self.window.database.findSong(trackInfo["title"], trackInfo["mainArtist"], fileOnly=not settings.get("streamOnly")):
                row.markInLibrary()
            self._loadThumbnail(row, trackInfo.get("image"))

    def _loadThumbnail(self, widget, url):
        if not url:
            return
        if url in self.thumbCache:
            widget.setThumbnail(self.thumbCache[url])
            return

        def onLoaded(data):
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self.thumbCache[url] = pixmap
                try:
                    widget.setThumbnail(pixmap)
                except RuntimeError:
                    pass

        runInBackground(downloader.fetchBytes, url, onFinished=onLoaded)

    def _onJobUpdated(self, job):
        for widget in self.resultWidgets.get(downloader.jobKey(job["entry"]), []):
            try:
                widget.updateJob(job)
            except RuntimeError:
                pass

    def _importWholePlaylist(self):
        if self.currentSpotifyInfo:
            self.window.importSpotify(self.currentSpotifyInfo)
            self.playlistBanner.hide()
            return
        if not self.currentPlaylistInfo:
            return
        playlistId = self.window.database.createPlaylist(self.currentPlaylistInfo["playlistTitle"], "Importata da YouTube")
        self.window.refreshPlaylists()
        if settings.get("streamOnly"):
            self.window.addStreamEntries(self.currentPlaylistInfo["entries"], playlistId)
        else:
            for entry in self.currentPlaylistInfo["entries"]:
                self.window.downloads.enqueue(entry, playlistId)
            self.window.showStatus(f"Download di {len(self.currentPlaylistInfo['entries'])} brani avviato")
        self.playlistBanner.hide()

    # ---------- streaming preview ----------
    def togglePreview(self, widget):
        if self.previewWidget is widget:
            self._stopPreview()
            return
        self._stopPreview()
        self.previewWidget = widget
        widget.setPreviewing(True)
        widget.statusLabel.setText("Caricamento...")
        if self.window.player.isPlaying():
            self.window.player.pause()
        self.previewOutput.setVolume(self.window.player.audioOutput.volume())
        runInBackground(_streamUrl, widget.entry["url"],
                        onFinished=lambda url, w=widget: self._startPreview(w, url),
                        onError=lambda message, w=widget: self._previewFailed(w, message))

    def _startPreview(self, widget, url):
        if self.previewWidget is not widget:
            return
        try:
            widget.statusLabel.setText("Anteprima")
        except RuntimeError:
            return
        self.previewPlayer.setSource(QUrl(url))
        self.previewPlayer.play()

    def _previewFailed(self, widget, message):
        if self.previewWidget is widget:
            self._stopPreview()
            self.window.showStatus(f"Anteprima non disponibile: {message[:120]}")

    def _onPreviewStatus(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self._stopPreview()

    def _stopPreview(self, error=False):
        self.previewPlayer.stop()
        self.previewPlayer.setSource(QUrl())
        if self.previewWidget is not None:
            try:
                self.previewWidget.setPreviewing(False)
                if self.previewWidget.statusLabel.text() in ("Anteprima", "Caricamento..."):
                    self.previewWidget.statusLabel.setText("Errore" if error else "")
            except RuntimeError:
                pass
        self.previewWidget = None

    def hideEvent(self, event):
        self._stopPreview()
        super().hideEvent(event)


def _streamUrl(url):
    return downloader.resolveStream(url)["url"]


class DownloadsPage(Page):
    def __init__(self, window):
        super().__init__(window)
        self.rows = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(12)
        headerRow = QHBoxLayout()
        headerRow.addWidget(_label("Download", "h1"))
        headerRow.addStretch()
        folderButton = QPushButton("Apri cartella musica")
        folderButton.setIcon(theme.icon("folder", theme.TEXT, 16))
        folderButton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(settings.musicDir())))
        clearButton = QPushButton("Pulisci completati")
        clearButton.clicked.connect(self._clearFinished)
        headerRow.addWidget(folderButton)
        headerRow.addWidget(clearButton)
        layout.addLayout(headerRow)
        self.emptyLabel = _label("Nessun download. Cerca una canzone e premi \"Scarica\".", "sub")
        layout.addWidget(self.emptyLabel)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.list, 1)
        window.downloads.jobAdded.connect(self._addJob)
        window.downloads.jobUpdated.connect(self._updateJob)

    def _addJob(self, job):
        rowWidget = QWidget()
        rowLayout = QHBoxLayout(rowWidget)
        rowLayout.setContentsMargins(6, 6, 6, 6)
        rowLayout.setSpacing(12)
        iconLabel = QLabel()
        iconLabel.setPixmap(theme.icon("download", theme.SUBTEXT, 22).pixmap(22, 22))
        textColumn = QVBoxLayout()
        titleLabel = _label(job["entry"]["title"], "songTitle")
        titleLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        progressBar = QProgressBar()
        progressBar.setFixedHeight(5)
        statusLabel = _label("In coda", "small")
        textColumn.addWidget(titleLabel)
        textColumn.addWidget(progressBar)
        textColumn.addWidget(statusLabel)
        retryButton = QPushButton("Riprova")
        retryButton.hide()
        retryButton.clicked.connect(lambda: self._retry(job))
        rowLayout.addWidget(iconLabel)
        rowLayout.addLayout(textColumn, 1)
        rowLayout.addWidget(retryButton)
        item = QListWidgetItem()
        item.setSizeHint(QSize(100, 68))
        self.list.insertItem(0, item)
        self.list.setItemWidget(item, rowWidget)
        self.rows[job["jobId"]] = (item, iconLabel, progressBar, statusLabel, retryButton)
        self.emptyLabel.hide()
        self._updateJob(job)

    def _updateJob(self, job):
        row = self.rows.get(job["jobId"])
        if not row:
            return
        item, iconLabel, progressBar, statusLabel, retryButton = row
        status = job["status"]
        progressBar.setValue(job["percent"])
        progressBar.setVisible(status not in ("done", "error"))
        if status == "done" and job["result"] and job["result"].get("videoError"):
            statusLabel.setToolTip("Video non scaricato: " + job["result"]["videoError"])
        retryButton.setVisible(status == "error")
        if status == "queued":
            statusLabel.setText("In coda")
        elif status == "search":
            statusLabel.setText("Cerco su YouTube...")
        elif status == "download":
            statusLabel.setText(f"Download {job['percent']}%")
        elif status == "convert":
            statusLabel.setText("Conversione in MP3...")
        elif status == "video":
            statusLabel.setText(f"Download video {job['percent']}%")
        elif status == "done":
            statusLabel.setText("Completato · " + os.path.basename(job["result"]["path"]))
            iconLabel.setPixmap(theme.icon("check", theme.ACCENT, 22).pixmap(22, 22))
        elif status == "error":
            statusLabel.setText("Errore: " + job["error"][:160])
            statusLabel.setToolTip(job["error"])
            iconLabel.setPixmap(theme.icon("close", "#F15E6C", 22).pixmap(22, 22))
        self.window.updateDownloadBadge()

    def _retry(self, job):
        row = self.rows.pop(job["jobId"], None)
        if row:
            self.list.takeItem(self.list.row(row[0]))
        self.window.downloads.retry(job)

    def _clearFinished(self):
        activeIds = {job["jobId"] for job in self.window.downloads.jobs if job["status"] in downloader.ACTIVE_STATES}
        for jobId in list(self.rows):
            if jobId not in activeIds:
                item = self.rows.pop(jobId)[0]
                self.list.takeItem(self.list.row(item))
        self.window.downloads.clearFinished()
        self.emptyLabel.setVisible(not self.rows)


class QueuePage(Page):
    def __init__(self, window):
        super().__init__(window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(12)
        headerRow = QHBoxLayout()
        headerRow.addWidget(_label("Coda", "h1"))
        headerRow.addStretch()
        clearButton = QPushButton("Svuota prossimi")
        clearButton.clicked.connect(self.window.player.clearUpcoming)
        headerRow.addWidget(clearButton)
        layout.addLayout(headerRow)
        layout.addWidget(_label("Trascina per riordinare · doppio click per riprodurre · Canc per rimuovere", "small"))
        self.list = QListWidget()
        self.list.setIconSize(QSize(44, 44))
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(lambda item: self.window.player.jumpTo(self.list.row(item)))
        self.list.model().rowsMoved.connect(self._onRowsMoved)
        self.list.installEventFilter(self)
        layout.addWidget(self.list, 1)
        self.window.player.queueChanged.connect(self.refresh)
        self.window.player.songChanged.connect(lambda song: self.refresh())

    def refresh(self):
        if not self.isVisible():
            self.dirty = True
            return
        self.dirty = False
        player = self.window.player
        scrollValue = self.list.verticalScrollBar().value()
        self.list.blockSignals(True)
        self.list.clear()
        for index, song in enumerate(player.queue):
            isCurrent = index == player.currentIndex
            prefix = "▶  " if isCurrent else ("     " if index > player.currentIndex else "     ")
            item = QListWidgetItem(
                songIcon(song, 44),
                f"{prefix}{song.get('title')}\n       {song.get('artist') or 'Artista sconosciuto'}  ·  {theme.formatTime((song.get('duration') or 0) * 1000)}",
            )
            item.setSizeHint(QSize(100, 58))
            if isCurrent:
                item.setForeground(QColor(theme.ACCENT))
            elif index < player.currentIndex:
                item.setForeground(QColor(theme.MUTED))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.list.verticalScrollBar().setValue(scrollValue)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "dirty", True):
            QTimer.singleShot(0, self.refresh)

    def _onRowsMoved(self, parent, start, end, destination, row):
        toIndex = row if row < start else row - 1
        self.window.player.moveInQueue(start, toIndex)

    def _removeSelected(self):
        rows = [self.list.row(item) for item in self.list.selectedItems()]
        self.window.player.removeFromQueue(rows)

    def _menu(self, position):
        item = self.list.itemAt(position)
        if not item:
            return
        menu = QMenu(self)
        menu.addAction(theme.icon("play"), "Riproduci", lambda: self.window.player.jumpTo(self.list.row(item)))
        menu.addAction(theme.icon("delete"), "Rimuovi dalla coda", self._removeSelected)
        menu.exec(self.list.viewport().mapToGlobal(position))

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.list and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Delete:
            self._removeSelected()
            return True
        return super().eventFilter(obj, event)


def songIcon(song, size):
    from PySide6.QtGui import QIcon
    return QIcon(theme.coverPixmap(song.get("cover"), size, song.get("id") or 0, 4))
