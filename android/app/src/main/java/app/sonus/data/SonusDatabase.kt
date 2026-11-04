package app.sonus.data

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

private val SCHEMA = listOf(
    """CREATE TABLE IF NOT EXISTS songs (
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
    )""",
    """CREATE TABLE IF NOT EXISTS playlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        cover TEXT,
        createdAt REAL,
        position INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS playlistSongs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        playlistId INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
        songId INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
        position INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS loops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        songId INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
        name TEXT,
        startMs INTEGER NOT NULL,
        endMs INTEGER NOT NULL,
        createdAt REAL
    )""",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    """CREATE TABLE IF NOT EXISTS sharedPlaylists (
        playlistId INTEGER PRIMARY KEY REFERENCES playlists(id) ON DELETE CASCADE,
        code TEXT NOT NULL,
        snapshot TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idxPlaylistSongs ON playlistSongs(playlistId, position)",
    "CREATE INDEX IF NOT EXISTS idxLoops ON loops(songId)",
)

private const val SCHEMA_VERSION = 2
private val SONG_FIELDS = setOf(
    "title", "artist", "album", "duration", "cover", "source", "url", "favorite", "path",
    "lyrics", "syncedLyrics", "lyricsChecked", "lyricsAuto", "videoPath", "videoUrl", "videoAuto", "videoChecked", "cutInfo",
    "songRate", "keepPitch", "reverbWet", "reverbSize", "hidden", "bassBoost",
)
private val SONG_COLUMNS_V2 = linkedMapOf(
    "lyrics" to "TEXT", "syncedLyrics" to "TEXT", "lyricsChecked" to "INTEGER DEFAULT 0", "lyricsAuto" to "INTEGER DEFAULT 1",
    "videoPath" to "TEXT", "videoUrl" to "TEXT", "videoAuto" to "INTEGER DEFAULT 1", "videoChecked" to "INTEGER DEFAULT 0",
    "cutInfo" to "TEXT",
    "songRate" to "REAL DEFAULT 1.0", "keepPitch" to "INTEGER DEFAULT 1", "reverbWet" to "REAL DEFAULT 0", "reverbSize" to "REAL DEFAULT 1.8",
    "hidden" to "INTEGER DEFAULT 0",
    "bassBoost" to "REAL DEFAULT 0",
)

private fun now(): Double = System.currentTimeMillis() / 1000.0

private fun Cursor.string(name: String): String = getColumnIndex(name).let { if (it < 0 || isNull(it)) "" else getString(it) }
private fun Cursor.stringOrNull(name: String): String? = getColumnIndex(name).let { if (it < 0 || isNull(it)) null else getString(it) }
private fun Cursor.double(name: String): Double = getColumnIndex(name).let { if (it < 0 || isNull(it)) 0.0 else getDouble(it) }
private fun Cursor.long(name: String): Long = getColumnIndex(name).let { if (it < 0 || isNull(it)) 0L else getLong(it) }

private fun Cursor.toSong(): Song = Song(
    id = long("id"), path = string("path"), title = string("title"), artist = string("artist"), album = string("album"),
    duration = double("duration"), cover = stringOrNull("cover"), source = string("source").ifEmpty { "local" }, url = stringOrNull("url"),
    addedAt = double("addedAt"), playCount = long("playCount").toInt(),
    lastPlayed = getColumnIndex("lastPlayed").let { if (it < 0 || isNull(it)) null else getDouble(it) },
    favorite = long("favorite") != 0L, hidden = long("hidden") != 0L,
    entryId = getColumnIndex("entryId").let { if (it < 0 || isNull(it)) null else getLong(it) },
)

/** Port of app/database.py: same tables and same queries as the PC app. */
class SonusDatabase(context: Context) : SQLiteOpenHelper(context, "sonus.db", null, 1) {

    override fun onConfigure(db: SQLiteDatabase) {
        db.setForeignKeyConstraintsEnabled(true)
        db.enableWriteAheadLogging()
    }

    override fun onCreate(db: SQLiteDatabase) {
        SCHEMA.forEach { db.execSQL(it) }
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {}

    override fun onOpen(db: SQLiteDatabase) {
        SCHEMA.forEach { db.execSQL(it) }
        migrate(db)
    }

    private fun columnsOf(db: SQLiteDatabase, table: String): Set<String> {
        val names = mutableSetOf<String>()
        db.rawQuery("PRAGMA table_info($table)", null).use { cursor ->
            while (cursor.moveToNext()) names.add(cursor.getString(cursor.getColumnIndexOrThrow("name")))
        }
        return names
    }

    private fun migrate(db: SQLiteDatabase) {
        val existing = columnsOf(db, "songs")
        for ((name, type) in SONG_COLUMNS_V2) {
            if (name !in existing) db.execSQL("ALTER TABLE songs ADD COLUMN $name $type")
        }
        if ("shareKey" !in columnsOf(db, "playlistSongs")) db.execSQL("ALTER TABLE playlistSongs ADD COLUMN shareKey TEXT")
        db.execSQL("INSERT OR REPLACE INTO meta VALUES ('schemaVersion', ?)", arrayOf(SCHEMA_VERSION.toString()))
    }

    private fun songs(query: String, vararg args: String): List<Song> =
        readableDatabase.rawQuery(query, args).use { cursor ->
            val result = ArrayList<Song>(cursor.count)
            while (cursor.moveToNext()) result.add(cursor.toSong())
            result
        }

    private fun longValue(query: String, vararg args: String): Long =
        readableDatabase.rawQuery(query, args).use { if (it.moveToFirst()) it.getLong(0) else 0L }

    // ---------- songs ----------
    fun addSong(path: String, title: String, artist: String = "", album: String = "", duration: Double = 0.0,
                cover: String? = null, source: String = "local", url: String? = null): Long {
        val existing = longValue("SELECT id FROM songs WHERE path=?", path)
        if (existing > 0) return existing
        val values = ContentValues().apply {
            put("path", path); put("title", title); put("artist", artist); put("album", album); put("duration", duration)
            put("cover", cover); put("source", source); put("url", url); put("addedAt", now())
        }
        return writableDatabase.insert("songs", null, values)
    }

    fun songByPath(path: String): Song? = songs("SELECT * FROM songs WHERE path=?", path).firstOrNull()
    fun getSong(songId: Long): Song? = songs("SELECT * FROM songs WHERE id=?", songId.toString()).firstOrNull()

    fun getSongs(songIds: List<Long>): List<Song> {
        if (songIds.isEmpty()) return emptyList()
        val placeholders = songIds.joinToString(",") { "?" }
        val map = songs("SELECT * FROM songs WHERE id IN ($placeholders)", *songIds.map { it.toString() }.toTypedArray()).associateBy { it.id }
        return songIds.mapNotNull { map[it] }
    }

    fun allSongs(): List<Song> = songs("SELECT * FROM songs WHERE hidden=0 ORDER BY addedAt DESC")
    fun favoriteSongs(): List<Song> = songs("SELECT * FROM songs WHERE favorite=1 AND hidden=0 ORDER BY title COLLATE NOCASE")
    fun recentSongs(limit: Int = 12): List<Song> = songs("SELECT * FROM songs WHERE hidden=0 ORDER BY addedAt DESC LIMIT ?", limit.toString())
    fun mostPlayed(limit: Int = 12): List<Song> =
        songs("SELECT * FROM songs WHERE playCount>0 AND hidden=0 ORDER BY playCount DESC LIMIT ?", limit.toString())
    fun recentlyPlayed(limit: Int = 12): List<Song> =
        songs("SELECT * FROM songs WHERE lastPlayed IS NOT NULL AND hidden=0 ORDER BY lastPlayed DESC LIMIT ?", limit.toString())

    fun searchSongs(text: String): List<Song> {
        val like = "%$text%"
        return songs(
            "SELECT * FROM songs WHERE hidden=0 AND (title LIKE ? OR artist LIKE ? OR album LIKE ?) ORDER BY title COLLATE NOCASE",
            like, like, like,
        )
    }

    fun updateSong(songId: Long, fields: Map<String, Any?>) {
        val allowed = fields.filterKeys { it in SONG_FIELDS }
        if (allowed.isEmpty()) return
        val values = ContentValues()
        for ((key, value) in allowed) {
            when (value) {
                null -> values.putNull(key)
                is String -> values.put(key, value)
                is Double -> values.put(key, value)
                is Float -> values.put(key, value.toDouble())
                is Int -> values.put(key, value)
                is Long -> values.put(key, value)
                is Boolean -> values.put(key, if (value) 1 else 0)
                else -> values.put(key, value.toString())
            }
        }
        writableDatabase.update("songs", values, "id=?", arrayOf(songId.toString()))
    }

    fun toggleFavorite(songId: Long): Boolean {
        writableDatabase.execSQL("UPDATE songs SET favorite = 1 - favorite WHERE id=?", arrayOf(songId))
        return longValue("SELECT favorite FROM songs WHERE id=?", songId.toString()) != 0L
    }

    fun registerPlay(songId: Long) {
        writableDatabase.execSQL("UPDATE songs SET playCount = playCount + 1, lastPlayed=? WHERE id=?", arrayOf(now(), songId))
    }

    fun deleteSongs(songIds: List<Long>) {
        val database = writableDatabase
        database.beginTransaction()
        try {
            songIds.forEach { database.delete("songs", "id=?", arrayOf(it.toString())) }
            database.setTransactionSuccessful()
        } finally {
            database.endTransaction()
        }
    }

    // ---------- playlists ----------
    fun createPlaylist(name: String, description: String = "", cover: String? = null): Long {
        val nextPosition = longValue("SELECT COALESCE(MAX(position), -1) + 1 FROM playlists")
        val values = ContentValues().apply {
            put("name", name); put("description", description); put("cover", cover); put("createdAt", now()); put("position", nextPosition)
        }
        return writableDatabase.insert("playlists", null, values)
    }

    private fun toPlaylist(cursor: Cursor) = Playlist(
        id = cursor.long("id"), name = cursor.string("name"), description = cursor.string("description"),
        cover = cursor.stringOrNull("cover"), songCount = cursor.long("songCount").toInt(),
    )

    fun playlists(): List<Playlist> = readableDatabase.rawQuery(
        "SELECT p.*, (SELECT COUNT(*) FROM playlistSongs ps WHERE ps.playlistId=p.id) AS songCount FROM playlists p ORDER BY position", null,
    ).use { cursor ->
        val result = ArrayList<Playlist>()
        while (cursor.moveToNext()) result.add(toPlaylist(cursor))
        result
    }

    fun getPlaylist(playlistId: Long): Playlist? = readableDatabase.rawQuery(
        "SELECT p.*, (SELECT COUNT(*) FROM playlistSongs ps WHERE ps.playlistId=p.id) AS songCount FROM playlists p WHERE p.id=?",
        arrayOf(playlistId.toString()),
    ).use { if (it.moveToFirst()) toPlaylist(it) else null }

    fun updatePlaylist(playlistId: Long, name: String, description: String, cover: String?) {
        val values = ContentValues().apply { put("name", name); put("description", description); put("cover", cover) }
        writableDatabase.update("playlists", values, "id=?", arrayOf(playlistId.toString()))
    }

    fun deletePlaylist(playlistId: Long) {
        writableDatabase.delete("playlists", "id=?", arrayOf(playlistId.toString()))
    }

    fun playlistSongs(playlistId: Long): List<Song> = songs(
        "SELECT s.*, ps.id AS entryId, ps.position AS entryPosition FROM playlistSongs ps " +
            "JOIN songs s ON s.id = ps.songId WHERE ps.playlistId=? ORDER BY ps.position",
        playlistId.toString(),
    )

    fun addToPlaylist(playlistId: Long, songIds: List<Long>) {
        val database = writableDatabase
        database.beginTransaction()
        try {
            val nextPosition = longValue("SELECT COALESCE(MAX(position), -1) + 1 FROM playlistSongs WHERE playlistId=?", playlistId.toString())
            songIds.forEachIndexed { offset, songId ->
                val values = ContentValues().apply { put("playlistId", playlistId); put("songId", songId); put("position", nextPosition + offset) }
                database.insert("playlistSongs", null, values)
            }
            database.setTransactionSuccessful()
        } finally {
            database.endTransaction()
        }
    }

    fun removeEntries(entryIds: List<Long>) {
        val database = writableDatabase
        database.beginTransaction()
        try {
            entryIds.forEach { database.delete("playlistSongs", "id=?", arrayOf(it.toString())) }
            database.setTransactionSuccessful()
        } finally {
            database.endTransaction()
        }
    }

    fun setPlaylistOrder(entryIds: List<Long>) {
        val database = writableDatabase
        database.beginTransaction()
        try {
            entryIds.forEachIndexed { index, entryId ->
                database.execSQL("UPDATE playlistSongs SET position=? WHERE id=?", arrayOf(index, entryId))
            }
            database.setTransactionSuccessful()
        } finally {
            database.endTransaction()
        }
    }
}
