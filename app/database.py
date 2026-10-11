import sqlite3
import time

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    title TEXT,
    artist TEXT,
    album TEXT,
    duration REAL DEFAULT 0,
    cover TEXT,
    source TEXT DEFAULT 'local',
    url TEXT,
    addedAt REAL,
    playCount INTEGER DEFAULT 0,
    lastPlayed REAL,
    favorite INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    cover TEXT,
    createdAt REAL,
    position INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS playlistSongs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlistId INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    songId INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    position INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS loops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    songId INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    name TEXT,
    startMs INTEGER NOT NULL,
    endMs INTEGER NOT NULL,
    createdAt REAL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sharedPlaylists (
    playlistId INTEGER PRIMARY KEY REFERENCES playlists(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    snapshot TEXT
);
CREATE INDEX IF NOT EXISTS idxPlaylistSongs ON playlistSongs(playlistId, position);
CREATE INDEX IF NOT EXISTS idxLoops ON loops(songId);
"""

SCHEMA_VERSION = 2
SONG_FIELDS = ("title", "artist", "album", "duration", "cover", "source", "url", "favorite", "path",
               "lyrics", "syncedLyrics", "lyricsChecked", "lyricsAuto", "videoPath", "videoUrl", "videoAuto", "videoChecked", "cutInfo",
               "songRate", "keepPitch", "reverbWet", "reverbSize", "hidden", "bassBoost")
SONG_COLUMNS_V2 = {
    "lyrics": "TEXT", "syncedLyrics": "TEXT", "lyricsChecked": "INTEGER DEFAULT 0", "lyricsAuto": "INTEGER DEFAULT 1",
    "videoPath": "TEXT", "videoUrl": "TEXT", "videoAuto": "INTEGER DEFAULT 1", "videoChecked": "INTEGER DEFAULT 0",
    "cutInfo": "TEXT",
    "songRate": "REAL DEFAULT 1.0", "keepPitch": "INTEGER DEFAULT 1", "reverbWet": "REAL DEFAULT 0", "reverbSize": "REAL DEFAULT 1.8",
    "hidden": "INTEGER DEFAULT 0",
    "bassBoost": "REAL DEFAULT 0",
}
STREAM_PREFIX = "stream:"


def isStreamPath(path):
    return bool(path) and str(path).startswith(STREAM_PREFIX)


def streamTarget(path):
    return str(path)[len(STREAM_PREFIX):] if isStreamPath(path) else None


class Database:
    def __init__(self, dbPath=DB_PATH):
        self.playlistListener = None
        self.connection = sqlite3.connect(dbPath)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        self._migrate()
        self.connection.commit()

    def _migrate(self):
        row = self.connection.execute("SELECT value FROM meta WHERE key='schemaVersion'").fetchone()
        currentVersion = int(row["value"]) if row else 0
        existingColumns = {info["name"] for info in self.connection.execute("PRAGMA table_info(songs)").fetchall()}
        for columnName, columnType in SONG_COLUMNS_V2.items():
            if columnName not in existingColumns:
                self.connection.execute(f"ALTER TABLE songs ADD COLUMN {columnName} {columnType}")
        entryColumns = {info["name"] for info in self.connection.execute("PRAGMA table_info(playlistSongs)").fetchall()}
        if "shareKey" not in entryColumns:
            self.connection.execute("ALTER TABLE playlistSongs ADD COLUMN shareKey TEXT")
        if currentVersion != SCHEMA_VERSION:
            self.connection.execute("INSERT OR REPLACE INTO meta VALUES ('schemaVersion', ?)", (str(SCHEMA_VERSION),))

    def _rows(self, query, params=()):
        return [dict(row) for row in self.connection.execute(query, params).fetchall()]

    # ---------- songs ----------
    def addSong(self, path, title, artist="", album="", duration=0, cover=None, source="local", url=None):
        existing = self.connection.execute("SELECT id FROM songs WHERE path=?", (path,)).fetchone()
        if existing:
            return existing["id"]
        cursor = self.connection.execute(
            "INSERT INTO songs (path, title, artist, album, duration, cover, source, url, addedAt) VALUES (?,?,?,?,?,?,?,?,?)",
            (path, title, artist, album, duration, cover, source, url, time.time()),
        )
        self.connection.commit()
        return cursor.lastrowid

    def addStreamSong(self, target, title, artist="", album="", duration=0, cover=None, hidden=False):
        path = STREAM_PREFIX + target
        existing = self.connection.execute("SELECT id FROM songs WHERE path=?", (path,)).fetchone()
        if existing:
            if not hidden:
                self.connection.execute("UPDATE songs SET hidden=0 WHERE id=?", (existing["id"],))
                self.connection.commit()
            return existing["id"]
        url = target if target.startswith("http") else None
        cursor = self.connection.execute(
            "INSERT INTO songs (path, title, artist, album, duration, cover, source, url, addedAt, hidden) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (path, title, artist, album, duration, cover, "stream", url, time.time(), 1 if hidden else 0),
        )
        self.connection.commit()
        return cursor.lastrowid

    def findSongByUrl(self, url):
        if not url:
            return None
        rows = self._rows("SELECT * FROM songs WHERE url=? ORDER BY (path LIKE 'stream:%'), hidden LIMIT 1", (url,))
        return rows[0] if rows else None

    def mergeSongInto(self, duplicateId, keptId):
        """Moves playlist entries and loops of a duplicate song row to another row, then deletes the duplicate."""
        affected = self._playlistsContaining([duplicateId])
        self.connection.execute("UPDATE playlistSongs SET songId=? WHERE songId=?", (keptId, duplicateId))
        self.connection.execute("UPDATE loops SET songId=? WHERE songId=?", (keptId, duplicateId))
        self.connection.execute("DELETE FROM songs WHERE id=?", (duplicateId,))
        self.connection.commit()
        self._notifyPlaylists(affected)

    def songByPath(self, path):
        rows = self._rows("SELECT * FROM songs WHERE path=?", (path,))
        return rows[0] if rows else None

    def _notifyPlaylists(self, playlistIds):
        if self.playlistListener is None:
            return
        for playlistId in dict.fromkeys(playlistIds):
            try:
                self.playlistListener(playlistId)
            except Exception as error:
                print(f"[Database] playlistListener: {error!r}")

    def getSong(self, songId):
        rows = self._rows("SELECT * FROM songs WHERE id=?", (songId,))
        return rows[0] if rows else None

    def getSongs(self, songIds):
        if not songIds:
            return []
        placeholders = ",".join("?" * len(songIds))
        songMap = {row["id"]: row for row in self._rows(f"SELECT * FROM songs WHERE id IN ({placeholders})", list(songIds))}
        return [songMap[songId] for songId in songIds if songId in songMap]

    def allSongs(self):
        return self._rows("SELECT * FROM songs WHERE hidden=0 ORDER BY addedAt DESC")

    def favoriteSongs(self):
        return self._rows("SELECT * FROM songs WHERE favorite=1 AND hidden=0 ORDER BY title COLLATE NOCASE")

    def recentSongs(self, limit=12):
        return self._rows("SELECT * FROM songs WHERE hidden=0 ORDER BY addedAt DESC LIMIT ?", (limit,))

    def mostPlayed(self, limit=12):
        return self._rows("SELECT * FROM songs WHERE playCount>0 AND hidden=0 ORDER BY playCount DESC LIMIT ?", (limit,))

    def recentlyPlayed(self, limit=12, includeHidden=False):
        hiddenFilter = "" if includeHidden else " AND hidden=0"
        return self._rows(f"SELECT * FROM songs WHERE lastPlayed IS NOT NULL{hiddenFilter} ORDER BY lastPlayed DESC LIMIT ?", (limit,))

    def searchSongs(self, text):
        likeText = f"%{text}%"
        return self._rows(
            "SELECT * FROM songs WHERE hidden=0 AND (title LIKE ? OR artist LIKE ? OR album LIKE ?) ORDER BY title COLLATE NOCASE",
            (likeText, likeText, likeText),
        )

    def findSong(self, title, artist="", fileOnly=False):
        fileFilter = " AND hidden=0 AND path NOT LIKE 'stream:%'" if fileOnly else ""
        rows = self._rows(
            "SELECT * FROM songs WHERE lower(title)=lower(?) AND (?='' OR lower(artist) LIKE lower(?))" + fileFilter +
            " ORDER BY (path LIKE 'stream:%'), hidden LIMIT 1",
            (title.strip(), artist.strip(), f"%{artist.strip()}%"),
        )
        return rows[0] if rows else None

    def updateSong(self, songId, **fields):
        fields = {key: value for key, value in fields.items() if key in SONG_FIELDS}
        if not fields:
            return
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.connection.execute(f"UPDATE songs SET {assignments} WHERE id=?", (*fields.values(), songId))
        self.connection.commit()

    def toggleFavorite(self, songId):
        self.connection.execute("UPDATE songs SET favorite = 1 - favorite WHERE id=?", (songId,))
        self.connection.commit()
        return bool(self.connection.execute("SELECT favorite FROM songs WHERE id=?", (songId,)).fetchone()["favorite"])

    def registerPlay(self, songId):
        self.connection.execute("UPDATE songs SET playCount = playCount + 1, lastPlayed=? WHERE id=?", (time.time(), songId))
        self.connection.commit()

    def deleteSongs(self, songIds):
        affected = self._playlistsContaining(songIds)
        self.connection.executemany("DELETE FROM songs WHERE id=?", [(songId,) for songId in songIds])
        self.connection.commit()
        self._notifyPlaylists(affected)

    def _playlistsContaining(self, songIds):
        if not songIds:
            return []
        placeholders = ",".join("?" * len(songIds))
        return [row["playlistId"] for row in self._rows(
            f"SELECT DISTINCT playlistId FROM playlistSongs WHERE songId IN ({placeholders})", list(songIds))]

    # ---------- playlists ----------
    def createPlaylist(self, name, description="", cover=None):
        nextPosition = self.connection.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM playlists").fetchone()[0]
        cursor = self.connection.execute(
            "INSERT INTO playlists (name, description, cover, createdAt, position) VALUES (?,?,?,?,?)",
            (name, description, cover, time.time(), nextPosition),
        )
        self.connection.commit()
        return cursor.lastrowid

    def playlists(self):
        return self._rows(
            "SELECT p.*, (SELECT COUNT(*) FROM playlistSongs ps WHERE ps.playlistId=p.id) AS songCount "
            "FROM playlists p ORDER BY position"
        )

    def getPlaylist(self, playlistId):
        rows = self._rows("SELECT * FROM playlists WHERE id=?", (playlistId,))
        return rows[0] if rows else None

    def updatePlaylist(self, playlistId, name, description, cover):
        self.connection.execute(
            "UPDATE playlists SET name=?, description=?, cover=? WHERE id=?", (name, description, cover, playlistId)
        )
        self.connection.commit()
        self._notifyPlaylists([playlistId])

    def deletePlaylist(self, playlistId):
        self.connection.execute("DELETE FROM playlists WHERE id=?", (playlistId,))
        self.connection.commit()

    def playlistSongs(self, playlistId):
        return self._rows(
            "SELECT s.*, ps.id AS entryId, ps.position AS entryPosition, ps.shareKey AS shareKey FROM playlistSongs ps "
            "JOIN songs s ON s.id = ps.songId WHERE ps.playlistId=? ORDER BY ps.position",
            (playlistId,),
        )

    def addToPlaylist(self, playlistId, songIds):
        nextPosition = self.connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM playlistSongs WHERE playlistId=?", (playlistId,)
        ).fetchone()[0]
        self.connection.executemany(
            "INSERT INTO playlistSongs (playlistId, songId, position) VALUES (?,?,?)",
            [(playlistId, songId, nextPosition + offset) for offset, songId in enumerate(songIds)],
        )
        self.connection.commit()
        self._notifyPlaylists([playlistId])

    def addEntry(self, playlistId, songId, shareKey=None):
        nextPosition = self.connection.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM playlistSongs WHERE playlistId=?", (playlistId,)
        ).fetchone()[0]
        cursor = self.connection.execute("INSERT INTO playlistSongs (playlistId, songId, position, shareKey) VALUES (?,?,?,?)",
                                         (playlistId, songId, nextPosition, shareKey))
        self.connection.commit()
        self._notifyPlaylists([playlistId])
        return cursor.lastrowid

    def setEntryKeys(self, entryKeys):
        self.connection.executemany("UPDATE playlistSongs SET shareKey=? WHERE id=?", [(key, entryId) for entryId, key in entryKeys])
        self.connection.commit()

    def removeEntries(self, entryIds):
        affected = self._playlistsOfEntries(entryIds)
        self.connection.executemany("DELETE FROM playlistSongs WHERE id=?", [(entryId,) for entryId in entryIds])
        self.connection.commit()
        self._notifyPlaylists(affected)

    def _playlistsOfEntries(self, entryIds):
        if not entryIds:
            return []
        placeholders = ",".join("?" * len(entryIds))
        return [row["playlistId"] for row in self._rows(
            f"SELECT DISTINCT playlistId FROM playlistSongs WHERE id IN ({placeholders})", list(entryIds))]

    def setPlaylistOrder(self, entryIds):
        self.connection.executemany(
            "UPDATE playlistSongs SET position=? WHERE id=?", [(index, entryId) for index, entryId in enumerate(entryIds)]
        )
        self.connection.commit()
        self._notifyPlaylists(self._playlistsOfEntries(entryIds))

    def setPlaylistsOrder(self, playlistIds):
        self.connection.executemany(
            "UPDATE playlists SET position=? WHERE id=?", [(index, playlistId) for index, playlistId in enumerate(playlistIds)]
        )
        self.connection.commit()

    def playlistCoverSongs(self, playlistId, limit=4):
        return self._rows(
            "SELECT s.cover FROM playlistSongs ps JOIN songs s ON s.id=ps.songId "
            "WHERE ps.playlistId=? AND s.cover IS NOT NULL GROUP BY s.cover ORDER BY MIN(ps.position) LIMIT ?",
            (playlistId, limit),
        )

    # ---------- shared playlists ----------
    def setShared(self, playlistId, code, snapshot):
        self.connection.execute("INSERT OR REPLACE INTO sharedPlaylists (playlistId, code, snapshot) VALUES (?,?,?)",
                                (playlistId, code, snapshot))
        self.connection.commit()

    def sharedPlaylist(self, playlistId):
        rows = self._rows("SELECT * FROM sharedPlaylists WHERE playlistId=?", (playlistId,))
        return rows[0] if rows else None

    def sharedPlaylistByCode(self, code):
        rows = self._rows("SELECT * FROM sharedPlaylists WHERE code=?", (code,))
        return rows[0] if rows else None

    def sharedPlaylists(self):
        return self._rows("SELECT sp.* FROM sharedPlaylists sp JOIN playlists p ON p.id = sp.playlistId")

    def unshare(self, playlistId):
        self.connection.execute("DELETE FROM sharedPlaylists WHERE playlistId=?", (playlistId,))
        self.connection.commit()

    # ---------- loops ----------
    def loops(self, songId):
        return self._rows("SELECT * FROM loops WHERE songId=? ORDER BY startMs", (songId,))

    def addLoop(self, songId, name, startMs, endMs):
        cursor = self.connection.execute(
            "INSERT INTO loops (songId, name, startMs, endMs, createdAt) VALUES (?,?,?,?,?)",
            (songId, name, int(startMs), int(endMs), time.time()),
        )
        self.connection.commit()
        return cursor.lastrowid

    def updateLoop(self, loopId, name=None, startMs=None, endMs=None):
        current = self._rows("SELECT * FROM loops WHERE id=?", (loopId,))
        if not current:
            return
        current = current[0]
        self.connection.execute(
            "UPDATE loops SET name=?, startMs=?, endMs=? WHERE id=?",
            (
                current["name"] if name is None else name,
                current["startMs"] if startMs is None else int(startMs),
                current["endMs"] if endMs is None else int(endMs),
                loopId,
            ),
        )
        self.connection.commit()

    def deleteLoop(self, loopId):
        self.connection.execute("DELETE FROM loops WHERE id=?", (loopId,))
        self.connection.commit()

    def close(self):
        self.connection.close()
