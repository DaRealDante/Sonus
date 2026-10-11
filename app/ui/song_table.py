import datetime
import json

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, QRect, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTableView

from . import theme

SONG_MIME = "application/x-sonus-songs"
COL_INDEX, COL_TITLE, COL_ALBUM, COL_ADDED, COL_FAV, COL_DURATION = range(6)
HEADERS = ["#", "Titolo", "Album", "Aggiunto", "", "Durata"]
SORT_ROLE = Qt.UserRole + 1
SONG_ROLE = Qt.UserRole + 2


class SongModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.songs = []
        self.currentSongId = None
        self.isPlaying = False

    def setSongs(self, songs):
        self.beginResetModel()
        self.songs = list(songs)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.songs)

    def columnCount(self, parent=QModelIndex()):
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return HEADERS[section]
            if role == Qt.DecorationRole and section == COL_DURATION:
                return theme.icon("clock", theme.SUBTEXT, 14)
            if role == Qt.TextAlignmentRole and section in (COL_INDEX, COL_DURATION, COL_FAV):
                return int(Qt.AlignCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        song = self.songs[index.row()]
        column = index.column()
        if role == SONG_ROLE:
            return song
        if role == Qt.DisplayRole:
            if column == COL_INDEX:
                return str(index.row() + 1)
            if column == COL_TITLE:
                return song.get("title") or ""
            if column == COL_ALBUM:
                return song.get("album") or ""
            if column == COL_ADDED:
                addedAt = song.get("addedAt")
                return datetime.datetime.fromtimestamp(addedAt).strftime("%d/%m/%Y") if addedAt else ""
            if column == COL_DURATION:
                return theme.formatTime((song.get("duration") or 0) * 1000)
        if role == SORT_ROLE:
            if column == COL_INDEX:
                return index.row()
            if column == COL_TITLE:
                return (song.get("title") or "").lower()
            if column == COL_ALBUM:
                return (song.get("album") or "").lower()
            if column == COL_ADDED:
                return song.get("addedAt") or 0
            if column == COL_FAV:
                return song.get("favorite") or 0
            if column == COL_DURATION:
                return song.get("duration") or 0
        if role == Qt.DecorationRole and column == COL_FAV and song.get("favorite"):
            return theme.icon("heartFill", theme.ACCENT, 16)
        if role == Qt.TextAlignmentRole:
            if column in (COL_INDEX, COL_DURATION, COL_FAV):
                return int(Qt.AlignCenter)
            return int(Qt.AlignVCenter | Qt.AlignLeft)
        if role == Qt.ForegroundRole:
            if column == COL_INDEX and song.get("id") == self.currentSongId:
                return QColor(theme.ACCENT)
            if column != COL_TITLE:
                return QColor(theme.SUBTEXT)
        if role == Qt.ToolTipRole and column == COL_TITLE:
            return song.get("path")
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.isValid():
            return base | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        return base | Qt.ItemIsDropEnabled

    def supportedDropActions(self):
        return Qt.MoveAction | Qt.CopyAction

    def mimeTypes(self):
        return [SONG_MIME]

    def mimeData(self, indexes):
        rows = sorted({index.row() for index in indexes})
        mimeData = QMimeData()
        payload = {
            "songIds": [self.songs[row]["id"] for row in rows],
            "entryIds": [self.songs[row].get("entryId") for row in rows],
        }
        mimeData.setData(SONG_MIME, json.dumps(payload).encode("utf-8"))
        return mimeData

    def setCurrent(self, songId, isPlaying):
        self.currentSongId = songId
        self.isPlaying = isPlaying
        if self.songs:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.songs) - 1, COL_TITLE))

    def updateSong(self, songData):
        for row, song in enumerate(self.songs):
            if song.get("id") == songData.get("id"):
                song.update({key: value for key, value in songData.items() if key not in ("entryId", "entryPosition")})
                self.dataChanged.emit(self.index(row, 0), self.index(row, len(HEADERS) - 1))


class SongProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.filterText = ""

    def setFilterText(self, text):
        self.filterText = text.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, sourceRow, sourceParent):
        if not self.filterText:
            return True
        song = self.sourceModel().songs[sourceRow]
        haystack = " ".join(str(song.get(key) or "") for key in ("title", "artist", "album")).lower()
        return all(word in haystack for word in self.filterText.split())


class TitleDelegate(QStyledItemDelegate):
    def __init__(self, table):
        super().__init__(table)
        self.table = table

    def paint(self, painter, option, index):
        song = index.data(SONG_ROLE)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor(theme.HOVER))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor(theme.ROW_HOVER))
        rect = option.rect
        coverSize = rect.height() - 14
        coverRect = QRect(rect.left() + 4, rect.top() + 7, coverSize, coverSize)
        painter.drawPixmap(coverRect, theme.coverPixmap(song.get("cover"), coverSize, song.get("id") or 0, 4))
        textLeft = coverRect.right() + 12
        textWidth = rect.right() - textLeft - 6
        model = self.table.songModel
        isCurrent = song.get("id") == model.currentSongId
        titleFont = QFont(option.font)
        titleFont.setPointSizeF(10.5)
        titleFont.setWeight(QFont.DemiBold)
        painter.setFont(titleFont)
        painter.setPen(QColor(theme.ACCENT if isCurrent else theme.TEXT))
        titleMetrics = QFontMetrics(titleFont)
        titleText = titleMetrics.elidedText(song.get("title") or "", Qt.ElideRight, textWidth)
        painter.drawText(QRect(textLeft, rect.top() + 8, textWidth, rect.height() // 2 - 6), Qt.AlignLeft | Qt.AlignBottom, titleText)
        artistFont = QFont(option.font)
        artistFont.setPointSizeF(9.5)
        painter.setFont(artistFont)
        painter.setPen(QPen(QColor(theme.SUBTEXT)))
        artistText = song.get("artist") or "Artista sconosciuto"
        if str(song.get("path") or "").startswith("stream:"):
            artistText = "Streaming · " + artistText
        artistText = QFontMetrics(artistFont).elidedText(artistText, Qt.ElideRight, textWidth)
        painter.drawText(QRect(textLeft, rect.top() + rect.height() // 2 + 1, textWidth, rect.height() // 2 - 8), Qt.AlignLeft | Qt.AlignTop, artistText)


class SongTable(QTableView):
    playRequested = Signal(list, int)
    menuRequested = Signal(list, object)
    favoriteClicked = Signal(dict)
    reorderRequested = Signal(list, int)
    deletePressed = Signal(list)

    def __init__(self, parent=None, reorderable=False):
        super().__init__(parent)
        self.reorderable = reorderable
        self.songModel = SongModel(self)
        self.proxy = SongProxy(self)
        self.proxy.setSourceModel(self.songModel)
        self.setModel(self.proxy)
        self.setItemDelegateForColumn(COL_TITLE, TitleDelegate(self))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setMouseTracking(True)
        self.setWordWrap(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(58)
        self.setSortingEnabled(True)
        self.sortByColumn(COL_INDEX, Qt.AscendingOrder)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(COL_INDEX, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_ALBUM, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_ADDED, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_FAV, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_DURATION, QHeaderView.Fixed)
        header.resizeSection(COL_INDEX, 48)
        header.resizeSection(COL_ALBUM, 220)
        header.resizeSection(COL_ADDED, 110)
        header.resizeSection(COL_FAV, 44)
        header.resizeSection(COL_DURATION, 80)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDrop if reorderable else QAbstractItemView.DragOnly)
        self.setAcceptDrops(reorderable)
        self.setDropIndicatorShown(reorderable)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._onContextMenu)
        self.doubleClicked.connect(self._onDoubleClick)
        self.clicked.connect(self._onClick)

    def setSongs(self, songs):
        self.songModel.setSongs(songs)

    def visibleSongs(self):
        return [self.proxy.index(row, 0).data(SONG_ROLE) for row in range(self.proxy.rowCount())]

    def selectedSongs(self):
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        return [self.proxy.index(row, 0).data(SONG_ROLE) for row in rows]

    def setFilterText(self, text):
        self.proxy.setFilterText(text)

    def _onDoubleClick(self, index):
        self.playRequested.emit(self.visibleSongs(), index.row())

    def _onClick(self, index):
        if index.column() == COL_FAV:
            self.favoriteClicked.emit(index.data(SONG_ROLE))

    def _onContextMenu(self, position):
        index = self.indexAt(position)
        if not index.isValid():
            return
        if not self.selectionModel().isRowSelected(index.row(), QModelIndex()):
            self.selectRow(index.row())
        self.menuRequested.emit(self.selectedSongs(), self.viewport().mapToGlobal(position))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentIndex().isValid():
            self.playRequested.emit(self.visibleSongs(), self.currentIndex().row())
            return
        if event.key() == Qt.Key_Delete and self.selectedSongs():
            self.deletePressed.emit(self.selectedSongs())
            return
        super().keyPressEvent(event)

    def isSortedByPosition(self):
        return self.horizontalHeader().sortIndicatorSection() == COL_INDEX and \
            self.horizontalHeader().sortIndicatorOrder() == Qt.AscendingOrder and not self.proxy.filterText

    def dragEnterEvent(self, event):
        if self.reorderable and event.source() is self and event.mimeData().hasFormat(SONG_MIME) and self.isSortedByPosition():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.reorderable and event.source() is self and self.isSortedByPosition():
            super().dragMoveEvent(event)
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not (self.reorderable and event.source() is self and self.isSortedByPosition()):
            event.ignore()
            return
        payload = json.loads(bytes(event.mimeData().data(SONG_MIME)).decode("utf-8"))
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            rect = self.visualRect(index)
            targetRow = index.row() + (1 if event.position().y() > rect.center().y() else 0)
        else:
            targetRow = self.proxy.rowCount()
        event.setDropAction(Qt.CopyAction)
        event.accept()
        self.reorderRequested.emit(payload.get("entryIds") or [], targetRow)
