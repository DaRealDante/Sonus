import json
import os
import shutil
import subprocess
import sys
import time

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QCursor, QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QInputDialog, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout,
    QWidget,
)

from .. import audio_tools, downloader, lyrics, metadata
from ..config import APP_NAME, AUDIO_EXTENSIONS, TEMP_DIR, VERSION, resourceDir, settings
from ..database import STREAM_PREFIX, Database, isStreamPath
from ..downloader import DownloadManager
from ..media_keys import MediaSession
from ..session_link import parseCode
from ..playlist_sync import SharedPlaylists
from . import effects
from ..session_link import linkFor
from ..together import TogetherController
from ..player import Player
from ..workers import runInBackground
from . import theme
from .equalizer_page import EqualizerPage
from .dialogs import CutDialog, LyricsEditDialog, LyricsSearchDialog, PlaylistDialog, SettingsDialog, SongEditDialog, VideoSearchDialog
from .now_playing_view import NowPlayingView
from .effects_popup import DEFAULT_EFFECTS, EffectsPopup
from .video_controller import BackdropWidget, VideoController
from .now_playing import NowPlayingPanel
from .player_bar import PlayerBar
from .song_table import SONG_MIME
from .views import DownloadsPage, FavoritesPage, HomePage, LibraryPage, PlaylistPage, QueuePage, RecentPage, SearchPage


def collectAudioFiles(paths):
    found = []
    for path in paths:
        if os.path.isdir(path):
            for rootPath, _, fileNames in os.walk(path):
                for fileName in sorted(fileNames):
                    if os.path.splitext(fileName)[1].lower() in AUDIO_EXTENSIONS:
                        found.append(os.path.join(rootPath, fileName))
        elif os.path.isfile(path) and os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS:
            found.append(path)
    return found


def readFilesForImport(paths, copyFiles, musicDir, progressCallback=None):
    results = []
    files = collectAudioFiles(paths)
    for index, path in enumerate(files):
        finalPath = os.path.abspath(path)
        if copyFiles and not finalPath.startswith(os.path.abspath(musicDir)):
            baseName, extension = os.path.splitext(os.path.basename(path))
            target = audio_tools.uniquePath(musicDir, baseName, extension)
            shutil.copy2(path, target)
            finalPath = target
        info = metadata.readTags(finalPath)
        info["path"] = os.path.normpath(finalPath)
        results.append(info)
        if progressCallback:
            progressCallback((index + 1, len(files)))
    return results


class PlaylistList(QListWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setIconSize(QSize(46, 46))
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAcceptDrops(True)
        self.setSpacing(1)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.highlightRow = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(SONG_MIME) or event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(SONG_MIME) and event.source() is not self:
            item = self.itemAt(event.position().toPoint())
            if item:
                self.setCurrentItem(item)
                event.setDropAction(Qt.CopyAction)
                event.accept()
            else:
                event.ignore()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(SONG_MIME) and event.source() is not self:
            item = self.itemAt(event.position().toPoint())
            if item:
                payload = json.loads(bytes(event.mimeData().data(SONG_MIME)).decode("utf-8"))
                self.window.addToPlaylist(item.data(Qt.UserRole), payload["songIds"])
                event.setDropAction(Qt.CopyAction)
                event.accept()
            return
        super().dropEvent(event)
        ids = [self.item(row).data(Qt.UserRole) for row in range(self.count())]
        self.window.database.setPlaylistsOrder(ids)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(appIcon())
        self.resize(1400, 860)
        self.setMinimumSize(1000, 640)
        self.setAcceptDrops(True)

        self.database = Database()
        self.player = Player(self)
        self.downloads = DownloadManager(self)
        self.downloads.songDownloaded.connect(self._onSongDownloaded)
        self.downloads.videoDownloaded.connect(self._onVideoDownloaded)
        self.pendingOrder = {}
        self.videoStreams = {}
        self.videoRetried = {}
        self.videoResolving = set()
        self.lyricsJobs = set()
        self.lyricsRetries = {}
        self.lyricsPool = QThreadPool(self)
        self.lyricsPool.setMaxThreadCount(2)

        self.videoController = VideoController(self.player, self)
        self.videoController.stateChanged.connect(self.updateAmbient)
        self.videoController.streamFailed.connect(self._onVideoStreamFailed)
        self.ambientActive = False
        self.uiVisible = True
        self.enteredFullscreen = False
        self.wasMaximized = False
        self.hideCursorPos = None
        self.ignoreActivityUntil = 0.0
        self.idleTimer = QTimer(self)
        self.idleTimer.setSingleShot(True)
        self.idleTimer.setInterval(3000)
        self.idleTimer.timeout.connect(self._onIdle)
        self.lastCursorPos = QCursor.pos()
        self.cursorTimer = QTimer(self)
        self.cursorTimer.setInterval(200)
        self.cursorTimer.timeout.connect(self._checkCursorActivity)

        central = BackdropWidget(self.videoController)
        central.setObjectName("backdrop")
        self.backdrop = central
        self.setCentralWidget(central)
        rootLayout = QVBoxLayout(central)
        rootLayout.setContentsMargins(8, 8, 8, 0)
        rootLayout.setSpacing(8)

        self.togetherBanner = QFrame()
        self.togetherBanner.setObjectName("togetherBanner")
        self.togetherBanner.setStyleSheet(f"QFrame#togetherBanner {{ background: {theme.ACCENT_DIM}; border-radius: 8px; }}")
        bannerLayout = QHBoxLayout(self.togetherBanner)
        bannerLayout.setContentsMargins(12, 6, 8, 6)
        bannerLayout.setSpacing(8)
        self.togetherAvatars = QHBoxLayout()
        self.togetherAvatars.setSpacing(4)
        bannerLayout.addLayout(self.togetherAvatars)
        self.togetherLabel = QLabel("")
        self.togetherLabel.setStyleSheet("font-weight: 600;")
        bannerLayout.addWidget(self.togetherLabel, 1)
        manageButton = QPushButton("Gestisci")
        manageButton.clicked.connect(self.showTogether)
        leaveButton = QPushButton("Esci")
        leaveButton.clicked.connect(lambda: self.together.leaveRoom())
        bannerLayout.addWidget(manageButton)
        bannerLayout.addWidget(leaveButton)
        self.togetherBanner.hide()
        rootLayout.addWidget(self.togetherBanner)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(8)
        self.splitter.setChildrenCollapsible(False)
        rootLayout.addWidget(self.splitter, 1)

        self.splitter.addWidget(self._buildSidebar())

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        self.homePage = HomePage(self)
        self.searchPage = SearchPage(self)
        from .discover_page import DiscoverPage
        self.discoverPage = DiscoverPage(self)
        self.libraryPage = LibraryPage(self)
        self.favoritesPage = FavoritesPage(self)
        self.recentPage = RecentPage(self)
        self.playlistPage = PlaylistPage(self)
        self.downloadsPage = DownloadsPage(self)
        self.queuePage = QueuePage(self)
        self.equalizerPage = EqualizerPage(self)
        self.nowPlayingPage = NowPlayingView(self)
        self.pageMap = {
            "equalizer": self.equalizerPage,
            "nowplaying": self.nowPlayingPage,
            "home": self.homePage, "search": self.searchPage, "discover": self.discoverPage, "library": self.libraryPage,
            "favorites": self.favoritesPage, "recent": self.recentPage, "playlist": self.playlistPage, "downloads": self.downloadsPage,
            "queue": self.queuePage,
        }
        for page in self.pageMap.values():
            self.pages.addWidget(page)
        self.splitter.addWidget(self.pages)

        self.rightPanel = NowPlayingPanel(self)
        self.splitter.addWidget(self.rightPanel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([300, 900, 340])

        self.playerBar = PlayerBar(self.player)
        rootLayout.addWidget(self.playerBar)
        self.playerBar.openQueue.connect(lambda: self.navigate("queue"))
        self.playerBar.openEqualizer.connect(lambda: self.navigate("equalizer"))
        self.playerBar.openNowPlaying.connect(lambda: self.navigate("nowplaying"))
        self.playerBar.ambientModeChosen.connect(self.setAmbientMode)
        self.videoController.tintChanged.connect(self.playerBar.setVideoTint)
        self.videoController.tintChanged.connect(self.nowPlayingPage.setVideoTint)
        self.effectsPopup = EffectsPopup(self)
        self.effectsPopup.effectsChanged.connect(self._onEffectsChanged)
        self.effectsPopup.exportRequested.connect(self.exportWithEffects)
        self.playerBar.effectsRequested.connect(self.showEffects)
        self.together = TogetherController(self.player, self.database, self.songEffects,
                                           lambda text: self.showStatus(text, 3500), parent=self)
        self.together.effectsChanged.connect(self.playerBar.setEffectsIndicator)
        self.together.roomChanged.connect(self._updateTogetherUi)
        self.together.peersChanged.connect(self._updateTogetherUi)
        self.togetherPopup = None
        self.sharedPlaylists = SharedPlaylists(self.database, lambda text: self.showStatus(text, 4000), self)
        self.sharedPlaylists.playlistsChanged.connect(self._onSharedPlaylistChanged)
        self.playerBar.togetherRequested.connect(self.showTogether)
        self.player.effectsProvider = self.effectsForSong
        self.player.effectsApplied.connect(self.playerBar.setEffectsIndicator)
        self.playerBar.openLyrics.connect(self.toggleLyricsView)
        self.playerBar.lyricsMenu.aboutToShow.connect(self._fillLyricsMenu)
        if settings.get("ambientMode") not in ("off", "background", "fullscreen"):
            settings.set("ambientMode", "background" if settings.get("ambientVideo") else "off")
        self.playerBar.setAmbientMode(settings.get("ambientMode"))
        self.equalizerPage._apply()
        self.playerBar.toggleRightPanel.connect(self.toggleRightPanel)
        self.playerBar.openLoops.connect(self.openLoops)
        self.playerBar.cutRequested.connect(lambda: self.openCutDialog(self.player.currentSong()))
        self.playerBar.favoriteToggled.connect(lambda: self.player.currentSong() and self.toggleFavorite(self.player.currentSong()))

        self.toast = QLabel(self)
        self.toast.setStyleSheet(
            f"background: {theme.TEXT}; color: #000; border-radius: 8px; padding: 8px 16px; font-weight: 600;"
        )
        self.toast.hide()
        self.toastTimer = QTimer(self)
        self.toastTimer.setSingleShot(True)
        self.toastTimer.timeout.connect(self.toast.hide)

        self.player.songChanged.connect(self._onSongChanged)
        self.player.playingChanged.connect(self._onPlayingChanged)
        self.player.songStarted.connect(self.database.registerPlay)
        self.player.songStarted.connect(self._autoLyricsOnPlay)
        self.player.songStarted.connect(lambda songId: self.pages.currentWidget() is self.recentPage and self.recentPage.refresh())
        self.player.playbackError.connect(lambda message: self.showStatus(message, 5000))

        self.history = []
        self.historyIndex = -1
        self._setupShortcuts()
        self._setupTray()
        self._restoreState()
        self.refreshPlaylists()
        self.navigate("home")
        self._registerMediaKeys()
        QTimer.singleShot(1500, self.sharedPlaylists.start)
        self.discordPresence = None
        self.discordTimer = QTimer(self)
        self.discordTimer.setSingleShot(True)
        self.discordTimer.setInterval(800)
        self.discordTimer.timeout.connect(self._pushDiscordPresence)
        for signal in (self.player.songChanged, self.player.playingChanged, self.player.seeked, self.player.effectsApplied):
            signal.connect(lambda *args: self.discordTimer.start())
        self.together.effectsChanged.connect(lambda *args: self.discordTimer.start())
        self.applyDiscordSetting()
        self.applyEffectSettings()
        self.applyVideoFps()
        QTimer.singleShot(8000, self.checkEngineUpdate)
        QTimer.singleShot(12000, lambda: self.checkAppUpdate(manual=False))
        moreMenu = self.playerBar.moreButton.menu()
        moreMenu.addSeparator()
        moreMenu.addAction(theme.icon("refresh"), "Controlla aggiornamenti", lambda: self.checkAppUpdate(manual=True))
        QApplication.instance().installEventFilter(self)
        QApplication.instance().applicationStateChanged.connect(lambda state: self._updateVideoSuspend())
        QApplication.instance().applicationStateChanged.connect(
            lambda state: state == Qt.ApplicationActive and QTimer.singleShot(300, self._refreshVideo))
        self.updateAmbient()

    # ---------- layout ----------
    def _buildSidebar(self):
        sidebar = QWidget()
        sidebar.setMinimumWidth(230)
        sidebar.setMaximumWidth(420)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        topBox = QFrame()
        topBox.setObjectName("sidebarBox")
        topLayout = QVBoxLayout(topBox)
        topLayout.setContentsMargins(10, 12, 10, 12)
        topLayout.setSpacing(2)
        logoRow = QHBoxLayout()
        logoLabel = QLabel()
        logoLabel.setPixmap(appIcon().pixmap(28, 28))
        nameLabel = QLabel(APP_NAME)
        nameLabel.setObjectName("h3")
        logoRow.addWidget(logoLabel)
        logoRow.addWidget(nameLabel)
        logoRow.addStretch()
        backButton = QToolButton()
        backButton.setIcon(theme.icon("back", theme.SUBTEXT, 16))
        backButton.setToolTip("Indietro (Alt+←)")
        backButton.clicked.connect(self.goBack)
        settingsButton = QToolButton()
        settingsButton.setIcon(theme.icon("settings", theme.SUBTEXT, 16))
        settingsButton.setToolTip("Impostazioni")
        settingsButton.clicked.connect(self.openSettings)
        logoRow.addWidget(backButton)
        logoRow.addWidget(settingsButton)
        topLayout.addLayout(logoRow)
        topLayout.addSpacing(6)
        self.navButtons = {}
        for key, text, iconName in (("home", "Home", "home"), ("search", "Cerca", "search"), ("discover", "Scopri", "star"),
                                    ("nowplaying", "In riproduzione", "mic"), ("equalizer", "Equalizzatore", "eq")):
            topLayout.addWidget(self._navButton(key, text, iconName))
        layout.addWidget(topBox)

        libraryBox = QFrame()
        libraryBox.setObjectName("sidebarBox")
        libraryLayout = QVBoxLayout(libraryBox)
        libraryLayout.setContentsMargins(10, 10, 10, 10)
        libraryLayout.setSpacing(2)
        for key, text, iconName in (("library", "La tua libreria", "library"), ("favorites", "Brani che ti piacciono", "heartFill"),
                                    ("recent", "Recenti", "clock"),
                                    ("downloads", "Download", "download"), ("queue", "Coda", "queue")):
            libraryLayout.addWidget(self._navButton(key, text, iconName))
        playlistHeader = QHBoxLayout()
        playlistHeader.setContentsMargins(12, 10, 4, 4)
        playlistLabel = QLabel("Playlist")
        playlistLabel.setObjectName("sub")
        addPlaylistButton = QToolButton()
        addPlaylistButton.setIcon(theme.icon("add", theme.SUBTEXT, 16))
        addPlaylistButton.setToolTip("Crea playlist (Ctrl+N)")
        addPlaylistButton.clicked.connect(self.createPlaylist)
        addSharedButton = QToolButton()
        addSharedButton.setIcon(theme.icon("link", theme.SUBTEXT, 16))
        addSharedButton.setToolTip("Aggiungi una playlist condivisa (codice o link)")
        addSharedButton.clicked.connect(self.askSharedPlaylist)
        playlistHeader.addWidget(playlistLabel)
        playlistHeader.addStretch()
        playlistHeader.addWidget(addSharedButton)
        playlistHeader.addWidget(addPlaylistButton)
        libraryLayout.addLayout(playlistHeader)
        self.playlistList = PlaylistList(self)
        self.playlistList.itemClicked.connect(lambda item: self.openPlaylist(item.data(Qt.UserRole)))
        self.playlistList.customContextMenuRequested.connect(self._playlistMenu)
        libraryLayout.addWidget(self.playlistList, 1)
        layout.addWidget(libraryBox, 1)
        return sidebar

    def _navButton(self, key, text, iconName):
        button = QPushButton(f"  {text}")
        button.setObjectName("nav")
        button.setCheckable(True)
        button.setIcon(theme.icon(iconName, theme.SUBTEXT if iconName != "heartFill" else theme.ACCENT, 20))
        button.setIconSize(QSize(20, 20))
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda: self.navigate(key))
        self.navButtons[key] = button
        return button

    def updateDownloadBadge(self):
        activeCount = self.downloads.activeCount()
        self.navButtons["downloads"].setText(f"  Download ({activeCount})" if activeCount else "  Download")

    # ---------- navigation ----------
    def navigate(self, key, playlistId=None, addHistory=True):
        page = self.pageMap[key]
        if key == "playlist":
            self.playlistPage.setPlaylist(playlistId)
        else:
            page.refresh()
        current = self.player.currentSong()
        page.setCurrent(current.get("id") if current else None, self.player.isPlaying())
        effects.switchPage(self.pages, page)
        for navKey, button in self.navButtons.items():
            button.setChecked(navKey == key)
        if key != "playlist":
            self.playlistList.clearSelection()
        else:
            for row in range(self.playlistList.count()):
                if self.playlistList.item(row).data(Qt.UserRole) == playlistId:
                    self.playlistList.setCurrentRow(row)
        if key == "search":
            self.searchPage.focusSearch()
        if addHistory:
            entry = (key, playlistId)
            if self.historyIndex < 0 or self.history[self.historyIndex] != entry:
                self.history = self.history[: self.historyIndex + 1] + [entry]
                self.historyIndex = len(self.history) - 1

    def goBack(self):
        if self.historyIndex > 0:
            self.historyIndex -= 1
            key, playlistId = self.history[self.historyIndex]
            if key == "playlist" and not self.database.getPlaylist(playlistId):
                key, playlistId = "home", None
            self.navigate(key, playlistId, addHistory=False)

    def openPlaylist(self, playlistId):
        self.navigate("playlist", playlistId)

    def currentPageKey(self):
        current = self.pages.currentWidget()
        return next((key for key, page in self.pageMap.items() if page is current), "home")

    def refreshCurrentPage(self):
        page = self.pages.currentWidget()
        page.refresh()
        current = self.player.currentSong()
        page.setCurrent(current.get("id") if current else None, self.player.isPlaying())

    def toggleRightPanel(self):
        visible = not self.rightPanel.isVisible()
        self.rightPanel.setVisible(visible)
        self.playerBar.setPanelActive(visible)
        settings.set("rightPanelVisible", visible)

    def openLoops(self):
        if not self.rightPanel.isVisible():
            self.toggleRightPanel()
        elif self.player.activeLoop:
            self.player.setLoop(None)

    # ---------- playlists ----------
    def playlistCover(self, playlist, size, radius):
        if playlist.get("cover") and os.path.isfile(playlist["cover"]):
            return theme.coverPixmap(playlist["cover"], size, playlist["id"], radius)
        covers = [row["cover"] for row in self.database.playlistCoverSongs(playlist["id"])]
        return theme.mosaicPixmap(covers, size, playlist["id"], radius)

    def refreshPlaylists(self):
        selectedId = self.playlistPage.playlistId if self.pages.currentWidget() is self.playlistPage else None
        self.playlistList.clear()
        for playlist in self.database.playlists():
            kind = "Playlist condivisa" if self.sharedPlaylists.isShared(playlist["id"]) else "Playlist"
            item = QListWidgetItem(QIcon(self.playlistCover(playlist, 46, 4)), f"{playlist['name']}\n{kind} · {playlist['songCount']} brani")
            item.setData(Qt.UserRole, playlist["id"])
            item.setSizeHint(QSize(100, 56))
            self.playlistList.addItem(item)
            if playlist["id"] == selectedId:
                item.setSelected(True)

    def createPlaylist(self, songIds=None):
        dialog = PlaylistDialog(self)
        if dialog.exec() != PlaylistDialog.Accepted:
            return None
        name, description, cover = dialog.values()
        playlistId = self.database.createPlaylist(name, description, cover)
        if songIds:
            self.database.addToPlaylist(playlistId, songIds)
        self.refreshPlaylists()
        if not songIds:
            self.openPlaylist(playlistId)
        else:
            self.showStatus(f"Aggiunto a {name}")
        return playlistId

    def editPlaylist(self, playlistId):
        playlist = self.database.getPlaylist(playlistId)
        if not playlist:
            return
        dialog = PlaylistDialog(self, playlist)
        if dialog.exec() != PlaylistDialog.Accepted:
            return
        name, description, cover = dialog.values()
        self.database.updatePlaylist(playlistId, name, description, cover)
        theme.clearCoverCache()
        self.refreshPlaylists()
        if self.pages.currentWidget() is self.playlistPage:
            self.playlistPage.refresh()

    def deletePlaylist(self, playlistId):
        playlist = self.database.getPlaylist(playlistId)
        if not playlist:
            return
        sharedNote = "\nÈ condivisa: verrà eliminata solo da te." if self.sharedPlaylists.isShared(playlistId) else ""
        answer = QMessageBox.question(self, APP_NAME, f"Eliminare la playlist \"{playlist['name']}\"?\nI brani resteranno nella libreria.{sharedNote}")
        if answer != QMessageBox.Yes:
            return
        self.sharedPlaylists.stopSharing(playlistId)
        self.database.deletePlaylist(playlistId)
        self.refreshPlaylists()
        if self.pages.currentWidget() is self.playlistPage and self.playlistPage.playlistId == playlistId:
            self.navigate("library")

    def addToPlaylist(self, playlistId, songIds):
        if not songIds:
            return
        existing = {song["id"] for song in self.database.playlistSongs(playlistId)}
        newIds = [songId for songId in songIds if songId not in existing]
        duplicates = len(songIds) - len(newIds)
        if duplicates and newIds:
            answer = QMessageBox.question(self, APP_NAME, f"{duplicates} brani sono già nella playlist. Aggiungerli comunque?",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                newIds = songIds
        elif duplicates and not newIds:
            answer = QMessageBox.question(self, APP_NAME, "Già presente nella playlist. Aggiungere di nuovo?",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            newIds = songIds
        for songId in set(newIds):
            self.database.updateSong(songId, hidden=0)
        self.database.addToPlaylist(playlistId, newIds)
        playlist = self.database.getPlaylist(playlistId)
        self.refreshPlaylists()
        if self.pages.currentWidget() is self.playlistPage and self.playlistPage.playlistId == playlistId:
            self.playlistPage.refresh()
        self.showStatus(f"Aggiunto a {playlist['name']}")

    def removeFromPlaylist(self, playlistId, songs):
        entryIds = [song["entryId"] for song in songs if song.get("entryId")]
        self.database.removeEntries(entryIds)
        self.refreshPlaylists()
        self.playlistPage.refresh()
        self.showStatus(f"Rimossi {len(entryIds)} brani dalla playlist")

    def _playlistMenu(self, position):
        item = self.playlistList.itemAt(position)
        if not item:
            return
        playlistId = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction(theme.icon("play"), "Riproduci", lambda: self.playSongs(self.database.playlistSongs(playlistId), 0))
        menu.addAction(theme.icon("shuffle"), "Riproduci in casuale",
                       lambda: self.playSongs(self.database.playlistSongs(playlistId), None, shuffled=True))
        menu.addAction(theme.icon("queue"), "Aggiungi alla coda", lambda: self.player.addToQueue(self.database.playlistSongs(playlistId)))
        menu.addSeparator()
        menu.addAction(theme.icon("edit"), "Modifica dettagli", lambda: self.editPlaylist(playlistId))
        if self.sharedPlaylists.isShared(playlistId):
            menu.addAction(theme.icon("link"), "Copia link di condivisione", lambda: self._copySharedLink(playlistId))
            menu.addAction(theme.icon("close"), "Smetti di condividere", lambda: self.stopSharingPlaylist(playlistId))
        else:
            menu.addAction(theme.icon("share"), "Condividi playlist...", lambda: self.sharePlaylist(playlistId))
        menu.addAction(theme.icon("delete"), "Elimina", lambda: self.deletePlaylist(playlistId))
        menu.exec(self.playlistList.viewport().mapToGlobal(position))

    # ---------- songs ----------
    def playSongs(self, songs, index, shuffled=None):
        songs = [song for song in songs if song]
        if not songs:
            return
        self.player.playSongs(songs, index, shuffled=shuffled)

    def toggleFavorite(self, song):
        isFavorite = self.database.toggleFavorite(song["id"])
        if isFavorite and song.get("hidden"):
            self.database.updateSong(song["id"], hidden=0)
        updated = self.database.getSong(song["id"])
        self.broadcastSong(updated)
        if self.pages.currentWidget() is self.favoritesPage:
            self.favoritesPage.refresh()
        self.showStatus("Aggiunto ai preferiti" if isFavorite else "Rimosso dai preferiti")

    def broadcastSong(self, song):
        for page in self.pageMap.values():
            page.updateSong(song)
        self.player.updateSongData(song)
        current = self.player.currentSong()
        if current and current.get("id") == song.get("id"):
            self.playerBar.setFavorite(bool(song.get("favorite")))

    def showSongMenu(self, songs, globalPosition, context):
        if not songs:
            return
        single = songs[0] if len(songs) == 1 else None
        songIds = [song["id"] for song in songs]
        menu = QMenu(self)
        menu.addAction(theme.icon("play"), "Riproduci", lambda: self.playSongs(songs, 0))
        menu.addAction(theme.icon("next"), "Riproduci dopo", lambda: (self.player.playNext(songs), self.showStatus("Riprodotto dopo")))
        menu.addAction(theme.icon("queue"), "Aggiungi alla coda", lambda: (self.player.addToQueue(songs), self.showStatus("Aggiunto alla coda")))
        playlistMenu = menu.addMenu(theme.icon("add"), "Aggiungi a playlist")
        playlistMenu.addAction(theme.icon("add"), "Nuova playlist...", lambda: self.createPlaylist(songIds))
        playlistMenu.addSeparator()
        for playlist in self.database.playlists():
            if playlist["id"] == context.get("playlistId"):
                continue
            playlistMenu.addAction(playlist["name"], lambda pid=playlist["id"]: self.addToPlaylist(pid, songIds))
        allFavorite = all(song.get("favorite") for song in songs)
        menu.addAction(theme.icon("heart" if allFavorite else "heartFill", theme.ACCENT),
                       "Rimuovi dai preferiti" if allFavorite else "Salva nei preferiti",
                       lambda: self._setFavorites(songs, not allFavorite))
        menu.addSeparator()
        streamSongs = [song for song in songs if isStreamPath(song.get("path"))]
        hiddenSongs = [song for song in songs if song.get("hidden")]
        if hiddenSongs:
            menu.addAction(theme.icon("add"), "Salva nella libreria", lambda: self.unhideSongs(hiddenSongs))
        if streamSongs:
            menu.addAction(theme.icon("download"), "Scarica sul PC", lambda: self.downloadStreamSongs(streamSongs))
        if single:
            menu.addAction(theme.icon("loop"), "Loop A-B...", lambda: self._openLoopFor(single))
            menu.addAction(theme.icon("cut"), "Taglia audio...", lambda: self.openCutDialog(single))
            menu.addAction(theme.icon("edit"), "Modifica informazioni...", lambda: self.editSong(single))
            if not streamSongs:
                menu.addAction(theme.icon("folder"), "Mostra nella cartella", lambda: showInFolder(single["path"]))
                if single.get("url"):
                    menu.addAction(theme.icon("cloud"), "Solo streaming (elimina il file)", lambda: self.makeStreamOnly(single))
            if single.get("url"):
                menu.addAction(theme.icon("globe"), "Apri su YouTube", lambda: QDesktopServices.openUrl(QUrl(single["url"])))
            menu.addSeparator()
        if context.get("playlistId"):
            menu.addAction(theme.icon("close"), "Rimuovi da questa playlist",
                           lambda: self.removeFromPlaylist(context["playlistId"], songs))
        menu.addAction(theme.icon("delete", "#F15E6C"), "Elimina dalla libreria...", lambda: self.deleteSongs(songs))
        menu.exec(globalPosition)

    def _setFavorites(self, songs, favorite):
        for song in songs:
            self.database.updateSong(song["id"], favorite=1 if favorite else 0, **({"hidden": 0} if favorite else {}))
            self.broadcastSong(self.database.getSong(song["id"]))
        if self.pages.currentWidget() is self.favoritesPage:
            self.favoritesPage.refresh()

    def _openLoopFor(self, song):
        current = self.player.currentSong()
        if not current or current.get("id") != song["id"]:
            self.playSongs([song], 0)
        if not self.rightPanel.isVisible():
            self.toggleRightPanel()

    def editSong(self, song):
        dialog = SongEditDialog(self, song)
        if dialog.exec() != SongEditDialog.Accepted:
            return
        values = dialog.values()
        self.database.updateSong(song["id"], **values)
        if dialog.writeTagsCheck.isChecked() and not isStreamPath(song.get("path")):
            isCurrent = self.player.currentSong() and self.player.currentSong().get("id") == song["id"]
            if not metadata.writeMp3Tags(song["path"], values["title"], values["artist"], values["album"], values["cover"]):
                self.showStatus("Dati salvati nell'app (il file è in uso o non scrivibile)" if isCurrent else "Impossibile scrivere nel file")
        theme.clearCoverCache(song.get("cover"))
        self.broadcastSong(self.database.getSong(song["id"]))
        self.refreshPlaylists()

    def deleteSongs(self, songs):
        if not songs:
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText(f"Eliminare {len(songs)} brani dalla libreria?" if len(songs) > 1 else f"Eliminare \"{songs[0].get('title')}\" dalla libreria?")
        box.setInformativeText("Verranno rimossi anche da tutte le playlist e i loop salvati. I file audio vanno nel Cestino.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        if box.exec() != QMessageBox.Yes:
            return
        songIds = [song["id"] for song in songs]
        self.player.removeSongIds(songIds)
        self.database.deleteSongs(songIds)
        failed = 0
        self.videoController.unload()
        for song in songs:
            if not isStreamPath(song.get("path")) and os.path.exists(song["path"]) and not _removeToTrash(song["path"]):
                failed += 1
            if song.get("videoPath") and os.path.normpath(song["videoPath"]).startswith(os.path.normpath(settings.musicDir())):
                _removeToTrash(song["videoPath"])
        self.refreshPlaylists()
        self.refreshCurrentPage()
        self.showStatus(f"Eliminati {len(songs)} brani" + (f" ({failed} file non spostati nel Cestino: sono rimasti dove erano)" if failed else ""))

    # ---------- cut ----------
    def openCutDialog(self, song, initialSelection=None):
        if not song:
            self.showStatus("Nessuna canzone selezionata")
            return
        if isStreamPath(song.get("path")):
            self.withLocalAudio(song, self.openCutDialog)
            return
        if not os.path.isfile(song["path"]):
            self.showStatus("File non trovato")
            return
        if self.player.isPlaying():
            self.player.pause()
        dialog = CutDialog(self, song, self._onCutDone, initialSelection)
        dialog.exec()

    def _cutLyricsFields(self, source, cutOperation):
        """cutInfo + lyrics for a file cut from `source`, so the lyrics keep matching the audio."""
        if not cutOperation:
            return {}
        cutInfo = self._cutInfo(source) or {
            "sourceTitle": source.get("title"), "sourceArtist": source.get("artist"), "sourceAlbum": source.get("album"),
            "sourceDuration": source.get("duration") or 0, "operations": [],
        }
        cutInfo["operations"] = list(cutInfo.get("operations") or []) + [cutOperation]
        fields = {"cutInfo": json.dumps(cutInfo)}
        if source.get("syncedLyrics"):
            synced = lyrics.applyCutsToSynced(source["syncedLyrics"], [cutOperation])
            fields.update(syncedLyrics=synced, lyrics=lyrics.plainFromSynced(synced), lyricsChecked=1)
        else:
            fields.update(syncedLyrics=None, lyrics=None, lyricsChecked=0)
        return fields

    def _onCutDone(self, song, outputPath, newTitle, replaceOriginal, cutOperation=None):
        source = self.database.getSong(song["id"]) or song
        lyricsFields = self._cutLyricsFields(source, cutOperation)
        if replaceOriginal:
            current = self.player.currentSong()
            isCurrent = current and current.get("id") == song["id"]
            if isCurrent:
                self.player.mediaPlayer.stop()
                self.player.mediaPlayer.setSource(QUrl())
            targetPath = song["path"]
            if song.get("streamOrigin"):
                baseName = audio_tools.safeFileName(f"{song.get('artist')} - {song.get('title')}" if song.get("artist") else song.get("title"))
                targetPath = audio_tools.uniquePath(settings.musicDir(), baseName, os.path.splitext(outputPath)[1] or ".mp3")
            try:
                os.replace(outputPath, targetPath)
            except OSError as error:
                QMessageBox.critical(self, APP_NAME, f"Impossibile sostituire il file:\n{error}")
                return
            song = dict(song, path=targetPath)
            metadata.writeMp3Tags(song["path"], song.get("title"), song.get("artist"), song.get("album"), song.get("cover"))
            duration = metadata.readTags(song["path"])["duration"]
            pathFields = {"path": targetPath, "source": "cut", "hidden": 0} if song.get("streamOrigin") else {}
            self.database.updateSong(song["id"], duration=duration, **pathFields, **lyricsFields)
            for loopData in self.database.loops(song["id"]):
                if loopData["startMs"] >= duration * 1000:
                    self.database.deleteLoop(loopData["id"])
            self.rightPanel.invalidate(song["path"])
            updated = self.database.getSong(song["id"])
            self.broadcastSong(updated)
            if isCurrent:
                self.player._loadCurrent(autoplay=False)
            self.showStatus("File originale aggiornato")
        else:
            metadata.writeMp3Tags(outputPath, newTitle, song.get("artist") or "", song.get("album") or "", song.get("cover"))
            duration = metadata.readTags(outputPath)["duration"]
            newId = self.database.addSong(outputPath, newTitle, song.get("artist") or "", song.get("album") or "",
                                          duration, song.get("cover"), "cut", song.get("url"))
            if lyricsFields:
                self.database.updateSong(newId, **lyricsFields)
            self.showStatus(f"Creato \"{newTitle}\" nella libreria")
            if self.pages.currentWidget() is self.playlistPage and self.playlistPage.playlistId:
                answer = QMessageBox.question(self, APP_NAME, "Aggiungere il nuovo brano anche a questa playlist?")
                if answer == QMessageBox.Yes:
                    self.database.addToPlaylist(self.playlistPage.playlistId, [newId])
                    self.refreshPlaylists()
        self.refreshCurrentPage()

    # ---------- import ----------
    def importFiles(self, playlistId=None):
        extensions = " ".join(f"*{extension}" for extension in sorted(AUDIO_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Importa file audio", os.path.expanduser("~"), f"Audio ({extensions})")
        if paths:
            self.importPaths(paths, playlistId)

    def importFolder(self):
        folderPath = QFileDialog.getExistingDirectory(self, "Importa cartella", os.path.expanduser("~"))
        if folderPath:
            self.importPaths([folderPath])

    def importPaths(self, paths, playlistId=None):
        self.showStatus("Importazione in corso...", 60000)
        runInBackground(
            readFilesForImport, paths, bool(settings.get("copyImported")), settings.musicDir(),
            withProgress=True,
            onProgress=lambda value: self.showStatus(f"Importazione {value[0]}/{value[1]}...", 60000),
            onFinished=lambda results: self._onImported(results, playlistId),
            onError=lambda message: self.showStatus(f"Errore di importazione: {message}", 5000),
        )

    def _onImported(self, results, playlistId):
        songIds = []
        for info in results:
            songIds.append(self.database.addSong(info["path"], info["title"], info["artist"], info["album"], info["duration"], info["cover"]))
        if settings.get("autoLyrics"):
            for song in self.database.getSongs(songIds):
                if not song.get("lyricsChecked"):
                    self.ensureLyrics(song)
        if playlistId and songIds:
            self.database.addToPlaylist(playlistId, songIds)
            self.refreshPlaylists()
        self.refreshCurrentPage()
        self.showStatus(f"Importati {len(results)} brani" if results else "Nessun file audio trovato")

    def _onSongDownloaded(self, result, playlistId):
        streamSong = self.database.getSong(result["replaceSongId"]) if result.get("replaceSongId") else None
        if streamSong is None or not isStreamPath(streamSong.get("path")):
            streamSong = self.database.songByPath(STREAM_PREFIX + result["url"]) if result.get("url") else None
        if streamSong is not None:
            songId = streamSong["id"]
            duplicate = self.database.songByPath(result["path"])
            if duplicate and duplicate["id"] != songId:
                self.database.mergeSongInto(duplicate["id"], songId)
            metadataFields = {"title": result["title"], "artist": result["artist"], "album": result["album"]} \
                if streamSong.get("hidden") else {}
            self.database.updateSong(songId, path=result["path"], source="youtube", url=result["url"] or streamSong.get("url"),
                                     duration=result["duration"] or streamSong.get("duration") or 0,
                                     cover=streamSong.get("cover") or result["cover"], hidden=0, **metadataFields)
            self.broadcastSong(self.database.getSong(songId))
        else:
            songId = self.database.addSong(result["path"], result["title"], result["artist"], result["album"],
                                           result["duration"], result["cover"], "youtube", result["url"])
        if result.get("videoPath"):
            self.database.updateSong(songId, videoPath=result["videoPath"], videoUrl=result.get("videoUrl"), videoChecked=1)
        if settings.get("autoLyrics"):
            self.ensureLyrics(self.database.getSong(songId))
        if playlistId and self.database.getPlaylist(playlistId):
            self.database.addToPlaylist(playlistId, [songId])
            if playlistId in self.pendingOrder and result.get("playlistIndex") is not None:
                self.pendingOrder[playlistId][songId] = result["playlistIndex"]
                self._applyPendingOrder(playlistId)
            self.refreshPlaylists()
            if self.pages.currentWidget() is self.playlistPage and self.playlistPage.playlistId == playlistId:
                self.playlistPage.refresh()
        if self.pages.currentWidget() is not self.searchPage:
            self.refreshCurrentPage()
        self.showStatus(f"Scaricato: {result['title']}")

    # ---------- playlist condivise ----------
    def sharePlaylist(self, playlistId):
        playlist = self.database.getPlaylist(playlistId)
        if not playlist:
            return
        code = self.sharedPlaylists.share(playlistId)
        QApplication.clipboard().setText(linkFor(code))
        self.refreshPlaylists()
        QMessageBox.information(self, "Playlist condivisa",
                                f"\"{playlist['name']}\" ora è condivisa.\n\nCodice: {code}\n\n"
                                "Il link è già copiato: mandalo ai tuoi amici. Chi lo apre (o incolla il codice) "
                                "riceve la playlist, e tutte le modifiche di tutti si sincronizzano da sole.")

    def _copySharedLink(self, playlistId):
        code = self.sharedPlaylists.codeOf(playlistId)
        if code:
            QApplication.clipboard().setText(linkFor(code))
            self.showStatus(f"Link copiato ({code})")

    def stopSharingPlaylist(self, playlistId):
        answer = QMessageBox.question(self, APP_NAME, "Smettere di sincronizzare questa playlist?\n"
                                                      "Resta da te così com'è; le modifiche degli altri non arriveranno più.")
        if answer == QMessageBox.Yes:
            self.sharedPlaylists.stopSharing(playlistId)
            self.refreshPlaylists()

    def askSharedPlaylist(self):
        text, accepted = QInputDialog.getText(self, "Playlist condivisa", "Incolla il codice o il link della playlist:")
        if accepted and text.strip():
            self.handleCode(text)

    def _onSharedPlaylistChanged(self, playlistId):
        theme.clearCoverCache()
        self.refreshPlaylists()
        if self.pages.currentWidget() is self.playlistPage and self.playlistPage.playlistId == playlistId:
            self.playlistPage.refresh()

    # ---------- ascolta insieme ----------
    def showTogether(self):
        if self.togetherPopup is None:
            from .together_popup import TogetherPopup
            self.togetherPopup = TogetherPopup(self)
        self.togetherPopup.showAbove(self.playerBar.togetherButton)

    def handleCode(self, text):
        """A room or shared-playlist code/link pasted anywhere (popup, link opened from the browser)."""
        parsed = parseCode(text)
        if not parsed:
            self.showStatus("Codice non valido")
            return False
        kind, code = parsed
        if self.togetherPopup is not None:
            self.togetherPopup.hide()
        if kind == "room":
            if self.together.code == code:
                self.showStatus("Sei già in questa stanza")
                return True
            self.together.joinRoom(code)
            self.showStatus("Entro nella stanza...", 3000)
        else:
            self.sharedPlaylists.addShared(code)
        return True

    def handleExternalMessage(self, message):
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()
        if message != "show":
            self.handleCode(message)

    def _updateTogetherUi(self):
        inRoom = self.together.inRoom()
        others = self.together.otherPeers()
        self.playerBar.setTogetherActive(inRoom, len(self.together.peers))
        self.togetherBanner.setVisible(inRoom)
        while self.togetherAvatars.count():
            item = self.togetherAvatars.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not inRoom:
            return
        from .together_popup import avatarPixmap
        for peer in list(others.values())[:6]:
            avatar = QLabel()
            avatar.setFixedSize(24, 24)
            avatar.setPixmap(avatarPixmap(peer.get("photo"), peer.get("name"), 24))
            avatar.setToolTip(peer.get("name"))
            self.togetherAvatars.addWidget(avatar)
        names = [peer.get("name") for peer in others.values()]
        if names:
            shown = ", ".join(names[:3]) + (f" e altri {len(names) - 3}" if len(names) > 3 else "")
            self.togetherLabel.setText(f"In ascolto insieme con {shown}")
        else:
            self.togetherLabel.setText(f"Stanza {self.together.code} · aspetto i tuoi amici (Gestisci → Copia link)")

    # ---------- effetti ----------
    def applyEffectSettings(self):
        engine = self.player.mediaPlayer
        engine.fadeEnabled = bool(settings.get("fxSongFade"))
        engine.spectrumEnabled = bool(settings.get("fxVisualizer") or settings.get("fxMicro"))
        self.playerBar.applyEffectSettings()
        self.nowPlayingPage.applyEffectSettings()

    # ---------- discord ----------
    def applyDiscordSetting(self):
        from ..config import DISCORD_CLIENT_ID
        from ..discord_presence import DiscordPresence
        clientId = (settings.get("discordClientId") or DISCORD_CLIENT_ID or "").strip()
        wanted = bool(settings.get("discordPresence")) and bool(clientId)
        if self.discordPresence is not None and (not wanted or self.discordPresence.clientId != clientId):
            self.discordPresence.stop()
            self.discordPresence = None
        if wanted and self.discordPresence is None:
            self.discordPresence = DiscordPresence(clientId)
            self.discordPresence.start()
            self.discordTimer.start()

    def _pushDiscordPresence(self):
        if self.discordPresence is None:
            return
        from ..discord_presence import buildActivity
        song = self.player.currentSong()
        playing = self.player.isPlaying() or (self.player.loading and self.player.loadAutoplay)
        durationMs = self.player.duration() or int((song or {}).get("duration") or 0) * 1000
        self.discordPresence.update(buildActivity(song, self.player.position(), durationMs, playing, self.player.playbackRate()))

    # ---------- scopri ----------
    def discoveredSong(self, track):
        """Library row for a suggested track: the song you already have, otherwise a hidden streaming copy."""
        from .. import discover
        from .discover_page import cachedRemoteImage, loadRemoteImage
        song = self.database.findSongByUrl(track["url"]) if track.get("url") else None
        if song is None:
            song = self.database.findSong(track["title"], discover.mainArtist(track.get("artist")))
        if song is None:
            songId = self.database.addStreamSong(discover.playTarget(track), track["title"], track.get("artist") or "",
                                                 track.get("album") or "", track.get("duration") or 0,
                                                 cachedRemoteImage(track.get("image")), hidden=True)
            song = self.database.getSong(songId)
            if not song.get("cover") and track.get("image"):
                def onImage(path, songId=songId):
                    if not (self.database.getSong(songId) or {}).get("cover"):
                        self.database.updateSong(songId, cover=path)
                        fresh = self.database.getSong(songId)
                        if fresh:
                            self.broadcastSong(fresh)
                loadRemoteImage(track["image"], onImage)
        return song

    def playDiscovered(self, tracks, index):
        songs = [self.discoveredSong(track) for track in tracks]
        self.playSongs(songs, index)

    def queueDiscovered(self, tracks):
        self.player.addToQueue([self.discoveredSong(track) for track in tracks])
        self.showStatus("Aggiunto alla coda")

    def saveDiscovered(self, track):
        song = self.discoveredSong(track)
        self.database.updateSong(song["id"], hidden=0)
        self.broadcastSong(self.database.getSong(song["id"]))
        self.showStatus(f"\"{song['title']}\" salvata nella libreria (streaming)")

    # ---------- streaming ----------
    def withLocalAudio(self, song, action):
        """Cut / effects on a streaming song: its audio is fetched first (temporarily), the result is a real file."""
        if not isStreamPath(song.get("path")):
            action(song)
            return
        target = song["path"][len(STREAM_PREFIX):]
        if target.startswith("roomfile:"):
            cachedPath = self.together.roomFilePaths.get(target[len("roomfile:"):].partition("|")[0])
            if cachedPath and os.path.isfile(cachedPath):
                action(dict(song, path=cachedPath, streamOrigin=song["path"]))
            else:
                self.showStatus("Aspetta che la canzone dell'amico sia arrivata, poi riprova", 4000)
            return
        self.showStatus("Preparo la canzone (la scarico solo per modificarla)...", 120000)

        def onReady(path):
            self.showStatus("Pronta", 1500)
            action(dict(song, path=path, streamOrigin=song["path"]))

        runInBackground(downloader.downloadTempAudio, song["path"][len(STREAM_PREFIX):], onFinished=onReady,
                        onError=lambda message: self.showStatus(f"Non riesco a preparare la canzone: {message[:100]}", 5000))

    def requireFile(self, song):
        if song and isStreamPath(song.get("path")):
            self.showStatus("Questa canzone è in streaming: scaricala prima (menu → Scarica sul PC)", 4000)
            return False
        return True

    def addStreamEntries(self, entries, playlistId=None, play=False, queue=False):
        """YouTube results added to the library without downloading the audio."""
        entries = [entry for entry in entries if entry.get("url")]
        if not entries:
            return
        self.showStatus("Aggiungo in streaming..." if len(entries) > 1 else "Carico in streaming...", 30000)

        def collect():
            return [downloader.streamSongInfo(entry) for entry in entries]

        def onFinished(infos):
            songIds = [self.database.addStreamSong(info["url"], info["title"], info["artist"], info["album"],
                                                   info["duration"], info["cover"]) for info in infos]
            if playlistId and self.database.getPlaylist(playlistId):
                self.database.addToPlaylist(playlistId, songIds)
                self.refreshPlaylists()
                if self.pages.currentWidget() is self.playlistPage and self.playlistPage.playlistId == playlistId:
                    self.playlistPage.refresh()
            songs = self.database.getSongs(songIds)
            if play:
                self.playSongs(songs, 0)
            elif queue:
                self.player.addToQueue(songs)
            if self.pages.currentWidget() is not self.searchPage:
                self.refreshCurrentPage()
            self.showStatus("In riproduzione (streaming)" if play else (
                "Aggiunto alla coda (streaming)" if queue else f"Aggiunti {len(songs)} brani in streaming"))

        runInBackground(collect, onFinished=onFinished,
                        onError=lambda message: self.showStatus(f"Errore: {message[:120]}", 5000))

    def downloadStreamSongs(self, songs):
        started = 0
        for song in songs:
            if not isStreamPath(song.get("path")):
                continue
            if song.get("url"):
                entry = {"url": song["url"], "title": song.get("title") or "", "channel": song.get("artist") or "",
                         "duration": song.get("duration") or 0, "replaceSongId": song["id"]}
            else:
                entry = {"url": None, "title": song.get("title") or "", "channel": "", "duration": song.get("duration") or 0,
                         "replaceSongId": song["id"],
                         "spotify": {"title": song.get("title") or "", "artist": song.get("artist") or "",
                                     "mainArtist": song.get("artist") or "", "album": song.get("album") or "",
                                     "durationMs": int((song.get("duration") or 0) * 1000), "image": None,
                                     "playlistIndex": None, "spotifyId": f"stream-{song['id']}"}}
            self.downloads.enqueue(entry)
            started += 1
        if started:
            self.showStatus(f"Download di {started} brani avviato")

    def makeStreamOnly(self, song):
        song = self.database.getSong(song["id"]) or song
        if not song.get("url") or isStreamPath(song.get("path")):
            return
        answer = QMessageBox.question(self, APP_NAME, f"Eliminare il file di \"{song.get('title')}\" e ascoltarla solo in streaming?\n"
                                                      "Playlist, loop, testo ed effetti restano. Servirà internet per ascoltarla.")
        if answer != QMessageBox.Yes:
            return
        streamPath = STREAM_PREFIX + song["url"]
        duplicate = self.database.songByPath(streamPath)
        if duplicate and duplicate["id"] != song["id"]:
            self.database.mergeSongInto(duplicate["id"], song["id"])
        filePath = song["path"]
        current = self.player.currentSong()
        if current and current.get("id") == song["id"]:
            self.player.pause()
        self.database.updateSong(song["id"], path=streamPath, source="stream")
        try:
            os.remove(filePath)
        except OSError:
            pass
        self.rightPanel.invalidate(filePath)
        self.broadcastSong(self.database.getSong(song["id"]))
        self.refreshCurrentPage()
        self.showStatus("Ora è solo in streaming")

    def unhideSongs(self, songs):
        for song in songs:
            self.database.updateSong(song["id"], hidden=0)
            self.broadcastSong(self.database.getSong(song["id"]))
        self.refreshCurrentPage()
        self.showStatus("Salvato nella libreria")

    # ---------- speed / pitch / reverb / bass (the same for every song) ----------
    def songEffects(self, song=None):
        saved = settings.get("effects") or {}
        effects = dict(DEFAULT_EFFECTS)
        for key, default in DEFAULT_EFFECTS.items():
            try:
                effects[key] = bool(saved[key]) if key == "keepPitch" else float(saved[key])
            except (KeyError, TypeError, ValueError):
                effects[key] = default
        return effects

    def _saveEffects(self, effects):
        settings.set("effects", {key: effects.get(key, default) for key, default in DEFAULT_EFFECTS.items()})
        settings.save()

    def effectsForSong(self, song):
        return self.together.effectsFor(song) or self.songEffects(song)

    def showEffects(self):
        current = self.player.currentSong()
        if not current:
            self.showStatus("Avvia prima una canzone")
            return
        self.effectsPopup.setSong(current, self.effectsForSong(current))
        self.effectsPopup.showBelow(self.playerBar.speedButton)

    def _onEffectsChanged(self, effects):
        current = self.player.currentSong()
        if not current:
            return
        if self.together.inRoom():
            # Speed and reverb go to the whole room (your saved ones stay as they are), the bass boost stays yours
            self._saveEffects(dict(self.songEffects(), bassBoost=effects.get("bassBoost", 0.0)))
            self.together.setLocalEffects(effects)
        else:
            self._saveEffects(effects)
        self.player.setPlaybackRate(effects["rate"], effects["keepPitch"])
        self.player.setReverb(effects["reverbWet"], effects["reverbSize"])
        self.player.setBassBoost(effects.get("bassBoost", 0.0))
        self.playerBar.setEffectsIndicator(effects)

    def exportWithEffects(self, localSong=None):
        current = self.player.currentSong()
        if not current:
            return
        song = localSong or self.database.getSong(current["id"])
        if not song:
            return
        if isStreamPath(song.get("path")):
            self.withLocalAudio(song, lambda prepared: self.exportWithEffects(prepared))
            return
        effects = self.effectsForSong(song)
        if abs(effects["rate"] - 1.0) < 0.005 and effects["reverbWet"] < 0.005 and effects.get("bassBoost", 0) < 0.005:
            self.showStatus("Imposta prima una velocità, il reverb o il bass boost")
            return
        self.effectsPopup.hide()
        tags = [f"{effects['rate']:.2f}x"] if abs(effects["rate"] - 1.0) >= 0.005 else []
        if effects["reverbWet"] >= 0.005:
            tags.append("reverb")
        if effects["rate"] < 1 and effects["reverbWet"] >= 0.005:
            tags = ["slowed + reverb"]
        if effects.get("bassBoost", 0) >= 0.005:
            tags.append("bass boost")
        newTitle, accepted = QInputDialog.getText(self, "Salva come nuova canzone", "Nome:",
                                                  text=f"{song.get('title')} ({' '.join(tags)})")
        if not accepted or not newTitle.strip():
            return
        newTitle = newTitle.strip()
        baseName = audio_tools.safeFileName(f"{song.get('artist')} - {newTitle}" if song.get("artist") else newTitle)
        outputPath = audio_tools.uniquePath(settings.musicDir(), baseName, ".mp3")
        self.showStatus("Creo la nuova canzone...", 60000)

        def onFinished(path):
            metadata.writeMp3Tags(path, newTitle, song.get("artist") or "", song.get("album") or "", song.get("cover"))
            duration = metadata.readTags(path)["duration"]
            newId = self.database.addSong(path, newTitle, song.get("artist") or "", song.get("album") or "",
                                          duration, song.get("cover"), "cut", song.get("url"))
            fields = {}
            if song.get("syncedLyrics") and abs(effects["rate"] - 1.0) >= 0.005:
                synced = lyrics.scaleSynced(song["syncedLyrics"], effects["rate"])
                fields = {"syncedLyrics": synced, "lyrics": lyrics.plainFromSynced(synced), "lyricsChecked": 1}
            elif song.get("lyrics") or song.get("syncedLyrics"):
                fields = {"syncedLyrics": song.get("syncedLyrics"), "lyrics": song.get("lyrics"), "lyricsChecked": 1}
            if fields:
                self.database.updateSong(newId, **fields)
            self.refreshCurrentPage()
            self.showStatus(f"Creato \"{newTitle}\" nella libreria", 4000)

        runInBackground(audio_tools.renderWithEffects, song["path"], outputPath, effects["rate"], effects["keepPitch"],
                        effects["reverbWet"], effects["reverbSize"], settings.get("audioQuality"), effects.get("bassBoost", 0.0),
                        onFinished=onFinished, onError=lambda message: self.showStatus(f"Errore: {message[:120]}", 6000))

    # ---------- video in background ----------
    def toggleAmbient(self):
        order = ["off", "background", "fullscreen"]
        current = settings.get("ambientMode")
        self.setAmbientMode(order[(order.index(current) + 1) % len(order)] if current in order else "background")

    def setAmbientMode(self, mode):
        settings.set("ambientMode", mode)
        self.playerBar.setAmbientMode(mode)
        self.showStatus({"off": "Video di sfondo disattivato", "background": "Video di sfondo: solo sfondo (la UI resta sempre visibile)",
                         "fullscreen": "Video di sfondo: schermo intero quando non muovi il mouse"}[mode])
        if mode != "fullscreen" and not self.uiVisible:
            self._showInterface()
        self.updateAmbient()

    def _fillLyricsMenu(self):
        menu = self.playerBar.lyricsMenu
        menu.clear()
        current = self.player.currentSong()
        song = self.database.getSong(current["id"]) if current and current.get("id") else None
        menu.addAction(theme.icon("mic"), "Apri / chiudi il testo", self.toggleLyricsView)
        menu.addSeparator()
        globalAction = menu.addAction("Testo automatico (tutte le canzoni)")
        globalAction.setCheckable(True)
        globalAction.setChecked(bool(settings.get("autoLyrics")))
        globalAction.toggled.connect(self._setGlobalAutoLyrics)
        songAction = menu.addAction("Testo automatico per questa canzone")
        songAction.setCheckable(True)
        songAction.setEnabled(song is not None)
        songAction.setChecked(bool(song.get("lyricsAuto", 1)) if song else False)
        songAction.toggled.connect(lambda checked: self.setSongAuto(song, "lyricsAuto", checked))
        menu.addSeparator()
        searchAction = menu.addAction(theme.icon("search"), "Cerca il testo...", lambda: self.searchLyricsManually(song))
        searchAction.setEnabled(song is not None)

    def _setGlobalAutoLyrics(self, enabled):
        settings.set("autoLyrics", enabled)
        settings.save()
        self.showStatus("Testo automatico attivo" if enabled else "Testo automatico disattivato")
        if enabled:
            current = self.player.currentSong()
            if current:
                self.ensureLyrics(self.database.getSong(current["id"]))

    def toggleLyricsView(self):
        if self.pages.currentWidget() is self.nowPlayingPage and self.nowPlayingPage.mode == "lyrics":
            self.goBack()
            return
        self.navigate("nowplaying")
        self.nowPlayingPage.setMode("lyrics")

    def videoSourceFor(self, song):
        """Saved video file, otherwise the YouTube video in streaming (resolved in background; None until ready)."""
        if not song:
            return None
        fresh = (self.database.getSong(song["id"]) if song.get("id") else None) or song
        videoPath = fresh.get("videoPath")
        if videoPath and os.path.isfile(videoPath):
            return videoPath
        if not settings.get("streamVideo") or not fresh.get("videoAuto", 1):
            return None
        path = str(fresh.get("path") or "")
        target = fresh.get("videoUrl") or fresh.get("url") or (path[len(STREAM_PREFIX):] if isStreamPath(path) else None)
        if not target:
            return None
        key = f"{settings.get('videoQuality')}:{target}"
        cached = self.videoStreams.get(key)
        if cached and time.time() - cached[0] < (4 * 3600 if cached[1] else 30):
            return cached[1]
        if key not in self.videoResolving and self._activeForVideo():
            self.videoResolving.add(key)
            runInBackground(downloader.resolveVideoStream, target, int(settings.get("videoQuality") or 720),
                            onFinished=lambda url: self._onVideoStreamResolved(key, url),
                            onError=lambda message: self._onVideoStreamResolved(key, None))
        return None

    def _activeForVideo(self):
        # Visible is enough: a friend usually changes song while you are in another app (Discord, a game...)
        return self.isVisible() and not self.isMinimized()

    def videoStreamLoading(self, song):
        return any(key.endswith(":" + str(target)) for key in self.videoResolving
                   for target in (song.get("videoUrl"), song.get("url"), str(song.get("path") or "")[len(STREAM_PREFIX):]) if target)

    def _refreshVideo(self):
        self.updateAmbient()
        self.nowPlayingPage._loadVideo()

    def applyVideoFps(self):
        self.videoController.setFrameRate(self._videoFps(fullscreen=not self.uiVisible))

    @staticmethod
    def _videoFps(fullscreen):
        """Frames per second of the video: chosen in Impostazioni, or automatic (12, 25 at full screen)."""
        try:
            chosen = int(settings.get("videoFps") or 0)
        except (TypeError, ValueError):
            chosen = 0
        if chosen > 0:
            return chosen
        return 25 if fullscreen else 12

    def _onVideoStreamFailed(self, url):
        """The saved streaming link does not work (expired or refused): forget it and find a new one, once."""
        key = next((key for key, saved in self.videoStreams.items() if saved[1] == url), None)
        if key is None or time.time() - self.videoRetried.get(key, 0) < 600:
            return
        self.videoRetried[key] = time.time()
        self.videoStreams.pop(key, None)
        print("[Video] il link del video non va: ne cerco uno nuovo")
        QTimer.singleShot(0, self._refreshVideo)

    def _onVideoStreamResolved(self, key, url):
        self.videoResolving.discard(key)
        self.videoStreams[key] = (time.time(), url)
        self.updateAmbient()
        self.nowPlayingPage._loadVideo()

    def updateAmbient(self):
        current = self.player.currentSong()
        song = self.database.getSong(current["id"]) if current and current.get("id") else None
        videoPath = self.videoSourceFor(song) if song and settings.get("ambientMode") != "off" else None
        wanted = settings.get("ambientMode") != "off" and bool(videoPath) and bool(song.get("videoAuto", 1))
        if wanted:
            self.videoController.request("backdrop", videoPath)
        else:
            self.videoController.release("backdrop")
        coverPath = song.get("cover") if song else None
        self.backdrop.setCover(coverPath if coverPath and os.path.isfile(coverPath) else None)
        # No video (or it does not work): the song's cover is the background instead
        active = settings.get("ambientMode") != "off" and song is not None and \
            ((wanted and self.videoController.hasFrames()) or self.backdrop.coverPath is not None)
        if active != self.ambientActive:
            self.ambientActive = active
            application = QApplication.instance()
            application.setStyleSheet(theme.STYLESHEET + (theme.AMBIENT_STYLESHEET if active else ""))
            if active:
                self.idleTimer.start()
                self.cursorTimer.start()
            else:
                self.cursorTimer.stop()
                self._showInterface()
        self.backdrop.setActive(active, self.uiVisible)

    def _updateVideoSuspend(self):
        inBackground = QApplication.instance().applicationState() != Qt.ApplicationActive
        suspended = self.isMinimized() or (inBackground and bool(settings.get("pauseVideoInBackground")))
        self.videoController.setSuspended(suspended)
        if suspended:
            self.cursorTimer.stop()
        elif self.ambientActive:
            self.cursorTimer.start()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.WindowStateChange, QEvent.ActivationChange):
            self._updateVideoSuspend()
        if event.type() == QEvent.WindowStateChange and event.oldState() & Qt.WindowMinimized and not self.isMinimized():
            QTimer.singleShot(300, self._refreshVideo)

    def _onIdle(self):
        if not self.ambientActive or not self.uiVisible or settings.get("ambientMode") != "fullscreen" \
                or not self.videoController.hasFrames():
            return
        application = QApplication.instance()
        if (not self.isActiveWindow() or application.activePopupWidget() or application.activeModalWidget()
                or application.mouseButtons() != Qt.NoButton):
            self.idleTimer.start()
            return
        self.uiVisible = False
        self.hideCursorPos = QCursor.pos()
        self.ignoreActivityUntil = time.monotonic() + 0.8
        self.splitter.hide()
        self.playerBar.hide()
        self.toast.hide()
        self.backdrop.setCursor(Qt.BlankCursor)
        if settings.get("ambientMode") == "fullscreen" and not self.isFullScreen():
            self.wasMaximized = self.isMaximized()
            self.enteredFullscreen = True
            self.showFullScreen()
        self.videoController.setFrameRate(self._videoFps(fullscreen=True))
        self.backdrop.setActive(True, False)

    def _showInterface(self):
        if not self.uiVisible:
            self.uiVisible = True
            self.splitter.show()
            self.playerBar.show()
            self.backdrop.unsetCursor()
            self.videoController.setFrameRate(self._videoFps(fullscreen=False))
            if self.enteredFullscreen:
                self.enteredFullscreen = False
                if self.wasMaximized:
                    self.showMaximized()
                else:
                    self.showNormal()
            self.backdrop.setActive(self.ambientActive, True)
        if self.ambientActive:
            self.idleTimer.start()

    def _checkCursorActivity(self):
        position = QCursor.pos()
        if position == self.lastCursorPos:
            return
        self.lastCursorPos = position
        if not self.frameGeometry().contains(position):
            return
        if not self.uiVisible:
            if time.monotonic() < self.ignoreActivityUntil or (position - self.hideCursorPos).manhattanLength() < 6:
                return
        self._showInterface()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.MouseButtonPress, QEvent.Wheel, QEvent.KeyPress) and self.ambientActive:
            if isinstance(obj, QWidget) and QWidget.window(obj) is self:
                self._showInterface()
        return False

    # ---------- app updates (GitHub) ----------
    def checkAppUpdate(self, manual=False):
        from .. import app_updater
        if not app_updater.isConfigured():
            if manual:
                QMessageBox.information(self, APP_NAME, "Gli aggiornamenti automatici non sono ancora collegati a GitHub.\n"
                                                        "Usa PUBBLICA_AGGIORNAMENTO.bat una volta per attivarli.")
            return
        if not manual and not settings.get("autoCheckUpdates"):
            return
        if manual:
            self.showStatus("Controllo aggiornamenti...")

        def onFinished(info):
            if not info:
                if manual:
                    self.showStatus(f"Hai già l'ultima versione ({VERSION})")
                return
            if not manual and info["version"] == settings.get("skippedVersion"):
                return
            self._offerAppUpdate(info)

        runInBackground(app_updater.checkLatestRelease, onFinished=onFinished,
                        onError=lambda message: manual and self.showStatus(f"Controllo non riuscito: {message[:90]}", 5000))

    def _offerAppUpdate(self, info):
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Information)
        box.setText(f"È disponibile Sonus {info['version']} (hai la {VERSION}).")
        box.setInformativeText("Vuoi aggiornare ora? L'app si chiude, si aggiorna e si riapre da sola. Playlist e canzoni restano.")
        if info.get("notes"):
            box.setDetailedText(info["notes"])
        updateButton = box.addButton("Aggiorna ora", QMessageBox.AcceptRole)
        box.addButton("Più tardi", QMessageBox.RejectRole)
        skipButton = box.addButton("Salta questa versione", QMessageBox.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is skipButton:
            settings.set("skippedVersion", info["version"])
            settings.save()
        elif clicked is updateButton:
            self._downloadAppUpdate(info)

    def _downloadAppUpdate(self, info):
        from PySide6.QtWidgets import QProgressDialog
        from .. import app_updater
        progress = QProgressDialog(f"Scarico Sonus {info['version']}...", "Annulla", 0, 100, self)
        progress.setWindowTitle(APP_NAME)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        worker = runInBackground(app_updater.downloadInstaller, info, withProgress=True,
                                 onProgress=progress.setValue,
                                 onFinished=lambda path: self._runAppInstaller(path, progress),
                                 onError=lambda message: (progress.close(), QMessageBox.warning(self, APP_NAME, f"Download non riuscito:\n{message}")))
        progress.canceled.connect(lambda: setattr(worker, "cancelled", True))

    def _runAppInstaller(self, path, progress):
        progress.close()
        if not os.path.isfile(path):
            return
        from .. import app_updater
        problem = app_updater.launchInstaller(path)
        if problem:
            QMessageBox.warning(self, APP_NAME, f"Impossibile avviare l'aggiornamento:\n{problem}")
            return
        self.close()

    # ---------- updates ----------
    def checkEngineUpdate(self, force=False):
        from ..updater import checkForEngineUpdate

        def onFinished(updated):
            if updated:
                self.showStatus("Motore YouTube aggiornato: riavvia l'app per usarlo", 6000)
            elif force:
                self.showStatus("Il motore YouTube è già aggiornato")

        runInBackground(checkForEngineUpdate, force, onFinished=onFinished,
                        onError=lambda message: force and self.showStatus(f"Controllo aggiornamenti fallito: {message[:80]}"))

    # ---------- lyrics ----------
    def lyricsPending(self, songId):
        return songId in self.lyricsJobs

    def _autoLyricsOnPlay(self, songId):
        song = self.database.getSong(songId)
        if song and settings.get("autoLyrics") and not song.get("lyricsChecked"):
            self.ensureLyrics(song)

    def ensureLyrics(self, song, force=False, title=None, artist=None):
        if not song or song["id"] in self.lyricsJobs:
            return
        if not force and (song.get("lyricsChecked") or not song.get("lyricsAuto", 1)):
            return
        songId = song["id"]
        self.lyricsJobs.add(songId)
        if force:
            self.nowPlayingPage.songDataChanged(songId)

        def onFinished(result):
            self.lyricsJobs.discard(songId)
            self.lyricsRetries.pop(songId, None)
            if result:
                self.database.updateSong(songId, lyrics=result["plain"], syncedLyrics=result["synced"], lyricsChecked=1)
            else:
                self.database.updateSong(songId, lyricsChecked=1)
                if force:
                    self.showStatus("Testo non trovato")
            self._songDataUpdated(songId)

        def onError(message):
            self.lyricsJobs.discard(songId)
            retryCount = self.lyricsRetries.get(songId, 0)
            if retryCount < 3:
                self.lyricsRetries[songId] = retryCount + 1
                QTimer.singleShot(90000 * (retryCount + 1), lambda: self.ensureLyrics(self.database.getSong(songId), force=force))
            if force:
                self.showStatus("Servizio testi momentaneamente non disponibile: riprovo da solo tra poco", 5000)
            self._songDataUpdated(songId)

        cutInfo = self._cutInfo(song)
        if cutInfo and not title:
            fetchTitle, fetchArtist = cutInfo.get("sourceTitle") or song.get("title") or "", cutInfo.get("sourceArtist") or song.get("artist") or ""
            fetchAlbum, fetchDuration = cutInfo.get("sourceAlbum") or "", cutInfo.get("sourceDuration") or 0
        else:
            fetchTitle = title or song.get("title") or ""
            fetchArtist = artist if artist is not None else (song.get("artist") or "")
            fetchAlbum, fetchDuration = ("" if title else (song.get("album") or "")), (0 if title else (song.get("duration") or 0))

        def fetchAndAdapt():
            return lyrics.adaptToCut(lyrics.fetchLyrics(fetchTitle, fetchArtist, fetchAlbum, fetchDuration), cutInfo)

        runInBackground(fetchAndAdapt, onFinished=onFinished, onError=onError, pool=self.lyricsPool)

    def _cutInfo(self, song):
        try:
            return json.loads(song.get("cutInfo") or "null")
        except (ValueError, TypeError):
            return None

    def searchLyricsManually(self, song):
        if not song:
            return
        dialog = LyricsSearchDialog(self, self.database.getSong(song["id"]) or song)
        result = dialog.exec()
        if result == 2:
            self.editLyrics(song)
        elif result == LyricsSearchDialog.Accepted and dialog.selected:
            chosen = lyrics.adaptToCut(dialog.selected, self._cutInfo(self.database.getSong(song["id"]) or song))
            self.database.updateSong(song["id"], lyrics=chosen["plain"], syncedLyrics=chosen["synced"],
                                     lyricsChecked=1, lyricsAuto=1)
            self._songDataUpdated(song["id"])
            self.showStatus("Testo salvato")

    def editLyrics(self, song):
        if not song:
            return
        dialog = LyricsEditDialog(self, self.database.getSong(song["id"]))
        if dialog.exec() == LyricsEditDialog.Accepted:
            plain, synced = dialog.values()
            self.database.updateSong(song["id"], lyrics=plain, syncedLyrics=synced, lyricsChecked=1)
            self._songDataUpdated(song["id"])

    def removeLyrics(self, song):
        self.database.updateSong(song["id"], lyrics=None, syncedLyrics=None, lyricsChecked=1)
        self._songDataUpdated(song["id"])

    def setSongAuto(self, song, field, enabled):
        if not song:
            return
        self.database.updateSong(song["id"], **{field: 1 if enabled else 0})
        fresh = self.database.getSong(song["id"])
        if not enabled:
            hasSaved = fresh.get("videoPath") if field == "videoAuto" else (fresh.get("lyrics") or fresh.get("syncedLyrics"))
            if hasSaved:
                what = "il video salvato" if field == "videoAuto" else "il testo salvato"
                answer = QMessageBox.question(self, APP_NAME, f"Eliminare anche {what} per questa canzone?")
                if answer == QMessageBox.Yes:
                    if field == "videoAuto":
                        self.removeVideo(fresh, ask=False)
                    else:
                        self.removeLyrics(fresh)
        elif field == "lyricsAuto" and not (fresh.get("lyrics") or fresh.get("syncedLyrics")):
            self.ensureLyrics(fresh, force=True)
        elif field == "videoAuto" and not fresh.get("videoPath") and fresh.get("url"):
            self.downloadOriginalVideo(fresh)
        self._songDataUpdated(song["id"])

    def _songDataUpdated(self, songId):
        fresh = self.database.getSong(songId)
        if fresh:
            self.player.updateSongData(fresh)
        self.nowPlayingPage.songDataChanged(songId)
        self.updateAmbient()

    # ---------- video ----------
    def videoPending(self, songId):
        return any(job["entry"].get("kind") == "video" and job["entry"].get("songId") == songId and job["status"] in ("queued", "video")
                   for job in self.downloads.jobs)

    def _queueVideo(self, song, url):
        if isStreamPath(song.get("path")):
            baseName = f"{song.get('artist')} - {song.get('title')}" if song.get("artist") else (song.get("title") or "video")
        else:
            baseName = os.path.splitext(os.path.basename(song["path"]))[0]
        self.downloads.enqueue({"kind": "video", "songId": song["id"], "url": url, "title": f"Video: {song.get('title')}",
                                "baseName": baseName})
        self.showStatus("Download del video avviato")
        self.nowPlayingPage.songDataChanged(song["id"])

    def openVideoSearch(self, song):
        if not song:
            return
        dialog = VideoSearchDialog(self, song)
        if dialog.exec() == VideoSearchDialog.Accepted and dialog.selectedEntry:
            self._queueVideo(song, dialog.selectedEntry["url"])

    def downloadOriginalVideo(self, song):
        if song and song.get("url"):
            self._queueVideo(song, song["url"])

    def chooseVideoFile(self, song):
        if not song:
            return
        filePath, _ = QFileDialog.getOpenFileName(self, "Scegli un video", os.path.expanduser("~"),
                                                  "Video (*.mp4 *.mkv *.webm *.mov *.avi *.m4v)")
        if filePath:
            self.database.updateSong(song["id"], videoPath=os.path.normpath(filePath), videoUrl=None, videoChecked=1)
            self._songDataUpdated(song["id"])

    def _onVideoDownloaded(self, result):
        song = self.database.getSong(result["songId"])
        if not song:
            return
        oldPath = song.get("videoPath")
        self.database.updateSong(song["id"], videoPath=result["videoPath"], videoUrl=result.get("videoUrl"), videoChecked=1)
        if oldPath and oldPath != result["videoPath"] and os.path.normpath(oldPath).startswith(os.path.normpath(settings.musicDir())):
            self.videoController.unload()
            try:
                os.remove(oldPath)
            except OSError:
                pass
        self.showStatus(f"Video pronto: {song.get('title')}")
        self._songDataUpdated(song["id"])

    def removeVideo(self, song, ask=True):
        if not song or not song.get("videoPath"):
            return
        path = song["videoPath"]
        insideLibrary = os.path.normpath(path).startswith(os.path.normpath(settings.musicDir()))
        self.videoController.unload()
        if insideLibrary:
            try:
                os.remove(path)
            except OSError:
                pass
        self.database.updateSong(song["id"], videoPath=None, videoUrl=None)
        self._songDataUpdated(song["id"])

    def revealPath(self, path):
        showInFolder(path)

    # ---------- spotify ----------
    def askSpotifyLink(self):
        link, accepted = QInputDialog.getText(self, "Importa da Spotify",
                                              "Incolla il link di una playlist, album o brano Spotify (deve essere pubblico):")
        if accepted and link.strip():
            self.navigate("search")
            self.searchPage.searchEdit.setText(link.strip())
            self.searchPage.searchWeb()

    def importSpotify(self, info):
        tracks = info["tracks"]
        if info["kind"] == "track":
            self.downloadSpotifyTracks(tracks, None)
            return
        playlistId = self.database.createPlaylist(info["name"] or "Playlist Spotify", info.get("description") or "Importata da Spotify",
                                                  info.get("coverPath"))
        self.downloadSpotifyTracks(tracks, playlistId)
        self.refreshPlaylists()

    def downloadSpotifyTracks(self, tracks, playlistId):
        if settings.get("streamOnly"):
            self.addSpotifyAsStream(tracks, playlistId)
            return
        if playlistId:
            self.pendingOrder.setdefault(playlistId, {})
        reused, queued = 0, 0
        for trackInfo in tracks:
            existing = self.database.findSong(trackInfo["title"], trackInfo["mainArtist"], fileOnly=True)
            if existing:
                reused += 1
                if playlistId:
                    self.database.addToPlaylist(playlistId, [existing["id"]])
                    self.pendingOrder[playlistId][existing["id"]] = trackInfo["playlistIndex"]
                continue
            queued += 1
            self.downloads.enqueue({
                "title": f"{trackInfo['artist']} - {trackInfo['title']}" if trackInfo["artist"] else trackInfo["title"],
                "channel": "Spotify",
                "duration": trackInfo["durationMs"] / 1000,
                "url": None,
                "thumbnail": trackInfo.get("image"),
                "spotify": trackInfo,
            }, playlistId)
        if playlistId:
            self._applyPendingOrder(playlistId)
        message = f"Download di {queued} brani avviato" if queued else "Tutti i brani erano già in libreria"
        if reused and queued:
            message += f" ({reused} già in libreria)"
        self.showStatus(message, 4000)

    def addSpotifyAsStream(self, tracks, playlistId):
        """Spotify tracks added as streaming songs: YouTube is searched only when a song is played."""
        def collect():
            infos = []
            for trackInfo in tracks:
                coverPath = None
                if trackInfo.get("image"):
                    try:
                        coverPath = metadata.saveCoverBytes(downloader.fetchBytes(trackInfo["image"]))
                    except Exception:
                        coverPath = None
                infos.append((trackInfo, coverPath))
            return infos

        def onFinished(infos):
            songIds = []
            for trackInfo, coverPath in infos:
                existing = self.database.findSong(trackInfo["title"], trackInfo["mainArtist"])
                if existing:
                    songIds.append(existing["id"])
                    continue
                query = f"{trackInfo['mainArtist']} - {trackInfo['title']}".strip(" -")
                songIds.append(self.database.addStreamSong(f"ytsearch1:{query} audio", trackInfo["title"], trackInfo["artist"],
                                                           trackInfo.get("album") or "", trackInfo["durationMs"] / 1000, coverPath))
            if playlistId and self.database.getPlaylist(playlistId):
                self.database.addToPlaylist(playlistId, songIds)
                self.refreshPlaylists()
            self.refreshCurrentPage()
            self.showStatus(f"Aggiunti {len(songIds)} brani in streaming", 4000)

        self.showStatus("Aggiungo i brani in streaming...", 60000)
        runInBackground(collect, onFinished=onFinished, onError=lambda message: self.showStatus(f"Errore: {message[:120]}", 5000))

    def _applyPendingOrder(self, playlistId):
        order = self.pendingOrder.get(playlistId, {})
        entries = self.database.playlistSongs(playlistId)
        entries.sort(key=lambda song: order.get(song["id"], 1_000_000 + song["entryPosition"]))
        self.database.setPlaylistOrder([song["entryId"] for song in entries])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            playlistId = self.playlistPage.playlistId if self.pages.currentWidget() is self.playlistPage else None
            self.importPaths(paths, playlistId)

    # ---------- misc ----------
    def openSettings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.Accepted:
            self.applyDiscordSetting()
            self.applyEffectSettings()
            self.applyVideoFps()
            self.updateAmbient()
            self.nowPlayingPage._loadVideo()
            if dialog.restartForColors:
                answer = QMessageBox.question(self, APP_NAME, "Riavviare ora Sonus per applicare i nuovi colori?\n"
                                                              "Riparte dalla stessa canzone.")
                if answer == QMessageBox.Yes:
                    self.restartApp()

    def restartApp(self):
        self.restartRequested = True
        self.close()

    def _launchRestart(self):
        from PySide6.QtCore import QProcess
        if getattr(sys, "frozen", False):
            program, arguments = sys.executable, []
        else:
            program, arguments = sys.executable, [os.path.join(resourceDir(), "main.py")]
        QProcess.startDetached(program, arguments + ["--restarted"])

    def showStatus(self, text, duration=2500):
        self.toast.setText(text)
        self.toast.adjustSize()
        self._positionToast()
        self.toast.show()
        self.toast.raise_()
        self.toastTimer.start(duration)

    def _positionToast(self):
        x = (self.width() - self.toast.width()) // 2
        y = self.height() - self.playerBar.height() - self.toast.height() - 24
        self.toast.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.toast.isVisible():
            self._positionToast()

    def _onSongChanged(self, song):
        QTimer.singleShot(0, self.updateAmbient)
        current = song.get("id") if song else None
        self.pages.currentWidget().setCurrent(current, self.player.isPlaying())
        self.setWindowTitle(f"{song.get('title')} · {song.get('artist') or 'Artista sconosciuto'}" if song else APP_NAME)
        if hasattr(self, "tray"):
            self.tray.setToolTip(f"{APP_NAME}\n{song.get('title')}" if song else APP_NAME)
        self._updateMediaSession(song)

    def _updateMediaSession(self, song):
        mediaSession = getattr(self, "mediaSession", None)
        if mediaSession is None or not mediaSession.available:
            return
        if song:
            mediaSession.setSong(song.get("title"), song.get("artist"), song.get("album"), song.get("cover"))
            mediaSession.setPlaying(self.player.isPlaying())
        else:
            mediaSession.setStopped()

    def _onPlayingChanged(self, isPlaying):
        current = self.player.currentSong()
        self.pages.currentWidget().setCurrent(current.get("id") if current else None, isPlaying)
        if hasattr(self, "trayPlayAction"):
            self.trayPlayAction.setText("Pausa" if isPlaying else "Riproduci")
        if getattr(self, "mediaSession", None) is not None:
            self.mediaSession.setPlaying(isPlaying)

    def _setupShortcuts(self):
        def bind(sequence, function):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(function)
            return shortcut

        bind(Qt.Key_Space, self.player.togglePlay)
        bind("Ctrl+Right", lambda: self.player.next())
        bind("Ctrl+Left", self.player.previous)
        bind("Shift+Right", lambda: self.player.seekRelative(5000))
        bind("Shift+Left", lambda: self.player.seekRelative(-5000))
        bind("Ctrl+Up", lambda: self.player.setVolume(self.player.volume + 5))
        bind("Ctrl+Down", lambda: self.player.setVolume(self.player.volume - 5))
        bind("Ctrl+F", lambda: self.navigate("search"))
        bind("Ctrl+L", lambda: self.navigate("library"))
        bind("Ctrl+N", self.createPlaylist)
        bind("Ctrl+I", lambda: self.importFiles())
        bind("Alt+Left", self.goBack)
        bind("M", lambda: self.player.setMuted(not self.player.muted))
        bind("S", lambda: self.player.setShuffle(not self.player.shuffle))
        bind("R", self.player.cycleRepeat)
        bind("Q", lambda: self.navigate("queue"))
        bind("E", lambda: self.navigate("equalizer"))
        bind("T", lambda: self.navigate("nowplaying"))
        bind("V", self.toggleAmbient)
        bind("F11", self.nowPlayingPage.toggleFullscreen)
        bind("L", lambda: self.rightPanel.toggleDraftLoop() if self.rightPanel.isVisible() else self.openLoops())
        bind("[", self.rightPanel.setPointA)
        bind("]", self.rightPanel.setPointB)
        bind(Qt.Key_MediaTogglePlayPause, self.player.togglePlay)
        bind(Qt.Key_MediaPlay, self.player.togglePlay)
        bind(Qt.Key_MediaNext, lambda: self.player.next())
        bind(Qt.Key_MediaPrevious, self.player.previous)

    def _setupTray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(appIcon(), self)
        trayMenu = QMenu()
        trayMenu.addAction("Mostra", self._showFromTray)
        trayMenu.addSeparator()
        self.trayPlayAction = trayMenu.addAction("Riproduci", self.player.togglePlay)
        trayMenu.addAction("Successiva", lambda: self.player.next())
        trayMenu.addAction("Precedente", self.player.previous)
        trayMenu.addSeparator()
        trayMenu.addAction("Esci", self.close)
        self.trayMenu = trayMenu
        self.tray.setContextMenu(trayMenu)
        self.tray.activated.connect(lambda reason: self._showFromTray() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

    def _showFromTray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---------- global media keys (Windows) ----------
    def _registerMediaKeys(self):
        self.mediaHotkeys = {}
        if sys.platform != "win32":
            return
        self.mediaSession = MediaSession(self)
        self.mediaSession.playPausePressed.connect(self.player.togglePlay)
        self.mediaSession.playPressed.connect(self.player.play)
        self.mediaSession.pausePressed.connect(self.player.pause)
        self.mediaSession.stopPressed.connect(self.player.pause)
        self.mediaSession.nextPressed.connect(lambda: self.player.next())
        self.mediaSession.previousPressed.connect(self.player.previous)
        if self.mediaSession.start():
            self._updateMediaSession(self.player.currentSong())
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            keys = {1: (0xB3, self.player.togglePlay), 2: (0xB0, lambda: self.player.next()), 3: (0xB1, self.player.previous)}
            for hotkeyId, (virtualKey, function) in keys.items():
                if user32.RegisterHotKey(hwnd, hotkeyId, 0x4000, virtualKey):
                    self.mediaHotkeys[hotkeyId] = function
        except Exception:
            self.mediaHotkeys = {}

    def nativeEvent(self, eventType, message):
        if getattr(self, "mediaHotkeys", None) and bytes(eventType) == b"windows_generic_MSG":
            try:
                import ctypes.wintypes
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312 and msg.wParam in self.mediaHotkeys:
                    self.mediaHotkeys[msg.wParam]()
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    # ---------- state ----------
    def _restoreState(self):
        geometry = settings.get("windowGeometry")
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except Exception:
                pass
        self.player.setVolume(settings.get("volume"))
        self.player.setMuted(bool(settings.get("muted")))
        self.player.setRepeat(int(settings.get("repeatMode")))
        self.player.shuffle = bool(settings.get("shuffle"))
        self.player.modesChanged.emit()
        queueIds = settings.get("lastQueue") or []
        songs = self.database.getSongs(queueIds)
        if songs:
            lastId = settings.get("lastSongId")
            index = next((i for i, song in enumerate(songs) if song["id"] == lastId), 0)
            self.player.restoreSession(songs, index, int(settings.get("lastPosition") or 0))
        visible = bool(settings.get("rightPanelVisible"))
        self.rightPanel.setVisible(visible)
        self.playerBar.setPanelActive(visible)

    def closeEvent(self, event):
        if self.downloads.activeCount():
            answer = QMessageBox.question(self, APP_NAME, "Ci sono download in corso. Chiudere comunque?")
            if answer != QMessageBox.Yes:
                self.restartRequested = False
                event.ignore()
                return
        current = self.player.currentSong()
        if self.enteredFullscreen:
            self.enteredFullscreen = False
            self.showMaximized() if self.wasMaximized else self.showNormal()
        settings.set("windowGeometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        settings.set("volume", self.player.volume)
        settings.set("muted", self.player.muted)
        settings.set("repeatMode", self.player.repeatMode)
        settings.set("shuffle", self.player.shuffle)
        settings.set("lastQueue", [song["id"] for song in self.player.queue][:2000])
        settings.set("lastSongId", current.get("id") if current else None)
        settings.set("lastPosition", self.player.position())
        settings.save()
        if hasattr(self, "tray"):
            self.tray.hide()
        self.together.leaveRoom()
        self.sharedPlaylists.stopAll()
        if self.discordPresence is not None:
            self.discordPresence.stop()
        if getattr(self, "mediaSession", None) is not None:
            self.mediaSession.shutdown()
        if sys.platform == "win32" and self.mediaHotkeys:
            try:
                import ctypes
                for hotkeyId in self.mediaHotkeys:
                    ctypes.windll.user32.UnregisterHotKey(int(self.winId()), hotkeyId)
            except Exception:
                pass
        if self.nowPlayingPage.fullscreenHost is not None:
            self.nowPlayingPage.fullscreenHost.finish()
            self.nowPlayingPage.fullscreenHost.hide()
        self.videoController.unload()
        self.player.mediaPlayer.stop()
        self.player.shutdown()
        if getattr(self, "restartRequested", False):
            self._launchRestart()
        for leftover in os.listdir(TEMP_DIR):
            try:
                os.remove(os.path.join(TEMP_DIR, leftover))
            except OSError:
                pass
        event.accept()
        QApplication.instance().quit()


def _removeToTrash(path):
    """Deleted songs go to the Recycle Bin (recoverable), or are removed if the bin isn't available."""
    from PySide6.QtCore import QFile
    try:
        return bool(QFile.moveToTrash(path))
    except Exception:
        return False


def showInFolder(path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


_appIcon = None


def appIcon():
    global _appIcon
    if _appIcon is None:
        iconPath = os.path.join(resourceDir(), "assets", "icon.png")
        _appIcon = QIcon(iconPath) if os.path.isfile(iconPath) else QIcon(theme.placeholderCover(64, 3))
    return _appIcon
