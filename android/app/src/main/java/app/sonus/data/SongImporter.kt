package app.sonus.data

import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.MediaStore
import android.provider.OpenableColumns
import java.io.File

/** Puts songs of the phone in the library (like "Importa file" on the PC). */
object SongImporter {

    private fun displayName(context: Context, uri: Uri): String {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val name = cursor.getString(0)
                if (!name.isNullOrBlank()) return name
            }
        }
        return uri.lastPathSegment?.substringAfterLast('/') ?: "Brano"
    }

    private class Tags(val title: String?, val artist: String, val album: String, val duration: Double)

    private fun readTags(context: Context, uri: Uri?, file: File?): Tags {
        val retriever = MediaMetadataRetriever()
        return try {
            if (file != null) retriever.setDataSource(file.absolutePath) else retriever.setDataSource(context, uri!!)
            Tags(
                title = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_TITLE)?.trim()?.ifBlank { null },
                artist = (retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ARTIST)
                    ?: retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ALBUMARTIST) ?: "").trim(),
                album = (retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ALBUM) ?: "").trim(),
                duration = (retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L) / 1000.0,
            )
        } catch (error: Exception) {
            Tags(null, "", "", 0.0)
        } finally {
            runCatching { retriever.release() }
        }
    }

    /** Songs chosen with the file picker. With [copy] the files are copied inside the app. Returns how many are new. */
    fun importUris(context: Context, uris: List<Uri>, copy: Boolean): Int {
        var added = 0
        for (uri in uris) {
            runCatching { context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
            val name = displayName(context, uri)
            var file: File? = null
            var path = uri.toString()
            if (copy) {
                val folder = File(context.filesDir, "music").apply { mkdirs() }
                var target = File(folder, name)
                var counter = 1
                while (target.exists()) {
                    target = File(folder, "${name.substringBeforeLast('.')} ($counter).${name.substringAfterLast('.', "mp3")}")
                    counter += 1
                }
                val copied = runCatching {
                    context.contentResolver.openInputStream(uri)?.use { input -> target.outputStream().use { input.copyTo(it) } } != null
                }.getOrDefault(false)
                if (!copied) continue
                file = target
                path = target.absolutePath
            }
            if (Library.db.songByPath(path) != null) continue
            val tags = readTags(context, if (file == null) uri else null, file)
            val title = tags.title ?: name.substringBeforeLast('.')
            Library.db.addSong(path, title, tags.artist, tags.album, tags.duration)
            added += 1
        }
        Library.changed()
        return added
    }

    /** All the music of the phone (the music in the media library of Android). Returns how many are new. */
    fun scanDevice(context: Context): Int {
        val collection = MediaStore.Audio.Media.EXTERNAL_CONTENT_URI
        val projection = arrayOf(
            MediaStore.Audio.Media._ID, MediaStore.Audio.Media.TITLE, MediaStore.Audio.Media.ARTIST,
            MediaStore.Audio.Media.ALBUM, MediaStore.Audio.Media.DURATION,
        )
        val selection = "${MediaStore.Audio.Media.IS_MUSIC} != 0 AND ${MediaStore.Audio.Media.DURATION} >= 20000"
        var added = 0
        val database = Library.db.writableDatabase
        database.beginTransaction()
        try {
            context.contentResolver.query(collection, projection, selection, null, "${MediaStore.Audio.Media.DATE_ADDED} DESC")?.use { cursor ->
                val idColumn = cursor.getColumnIndexOrThrow(MediaStore.Audio.Media._ID)
                val titleColumn = cursor.getColumnIndexOrThrow(MediaStore.Audio.Media.TITLE)
                val artistColumn = cursor.getColumnIndexOrThrow(MediaStore.Audio.Media.ARTIST)
                val albumColumn = cursor.getColumnIndexOrThrow(MediaStore.Audio.Media.ALBUM)
                val durationColumn = cursor.getColumnIndexOrThrow(MediaStore.Audio.Media.DURATION)
                while (cursor.moveToNext()) {
                    val path = ContentUris.withAppendedId(collection, cursor.getLong(idColumn)).toString()
                    if (Library.db.songByPath(path) != null) continue
                    val artist = cursor.getString(artistColumn)?.takeUnless { it == "<unknown>" } ?: ""
                    val album = cursor.getString(albumColumn)?.takeUnless { it.startsWith("<unknown") } ?: ""
                    Library.db.addSong(path, cursor.getString(titleColumn) ?: "Brano", artist, album, cursor.getLong(durationColumn) / 1000.0)
                    added += 1
                }
            }
            database.setTransactionSuccessful()
        } finally {
            database.endTransaction()
        }
        Library.changed()
        return added
    }
}
