package app.sonus.data

import android.net.Uri
import java.io.File

const val STREAM_PREFIX = "stream:"

fun isStreamPath(path: String?): Boolean = !path.isNullOrEmpty() && path.startsWith(STREAM_PREFIX)

/** A row of the "songs" table (same columns as the PC app). */
data class Song(
    val id: Long,
    val path: String,
    val title: String,
    val artist: String,
    val album: String,
    val duration: Double,
    val cover: String?,
    val source: String,
    val url: String?,
    val addedAt: Double,
    val playCount: Int,
    val lastPlayed: Double?,
    val favorite: Boolean,
    val hidden: Boolean,
    /** Only for songs that come from a playlist: the row of the entry in that playlist. */
    val entryId: Long? = null,
) {
    val displayArtist: String get() = artist.ifBlank { "Artista sconosciuto" }
    val durationMs: Long get() = (duration * 1000).toLong()

    /** Where the player finds the sound: a content:// address or a file of the phone. */
    fun playUri(): Uri = if (path.startsWith("/")) Uri.fromFile(File(path)) else Uri.parse(path)
}

data class Playlist(val id: Long, val name: String, val description: String, val cover: String?, val songCount: Int)
