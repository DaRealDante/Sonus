package app.sonus.data

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue

/**
 * The library of the app. Every change goes through here and raises [version]: the screens that show lists
 * read again when it changes.
 */
object Library {
    lateinit var db: SonusDatabase
        private set

    var version by mutableIntStateOf(0)
        private set

    fun init(context: Context) {
        db = SonusDatabase(context.applicationContext)
    }

    fun changed() {
        version += 1
    }

    fun toggleFavorite(songId: Long): Boolean = db.toggleFavorite(songId).also { changed() }

    fun registerPlay(songId: Long) {
        db.registerPlay(songId)
        changed()
    }

    fun deleteSongs(songIds: List<Long>) {
        db.deleteSongs(songIds)
        changed()
    }

    fun updateSong(songId: Long, fields: Map<String, Any?>) {
        db.updateSong(songId, fields)
        changed()
    }

    fun createPlaylist(name: String, description: String = ""): Long = db.createPlaylist(name, description).also { changed() }

    fun updatePlaylist(playlistId: Long, name: String, description: String) {
        db.updatePlaylist(playlistId, name, description, null)
        changed()
    }

    fun deletePlaylist(playlistId: Long) {
        db.deletePlaylist(playlistId)
        changed()
    }

    fun addToPlaylist(playlistId: Long, songIds: List<Long>) {
        db.addToPlaylist(playlistId, songIds)
        changed()
    }

    fun removeEntries(entryIds: List<Long>) {
        db.removeEntries(entryIds)
        changed()
    }

    fun setPlaylistOrder(entryIds: List<Long>) {
        db.setPlaylistOrder(entryIds)
        changed()
    }
}
