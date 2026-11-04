package app.sonus.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.media.MediaMetadataRetriever
import android.util.LruCache
import java.io.File

/** Covers of the songs: the picture inside the audio file (or a saved picture), loaded when needed and kept in memory. */
object CoverLoader {
    private val cache = object : LruCache<String, Bitmap>((Runtime.getRuntime().maxMemory() / 12).toInt().coerceAtLeast(4 * 1024 * 1024)) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount
    }
    private val missing = HashSet<String>()

    private fun key(song: Song) = "${song.id}:${song.cover ?: ""}"

    fun cached(song: Song): Bitmap? = cache.get(key(song))

    fun hasNoCover(song: Song): Boolean = synchronized(missing) { key(song) in missing }

    /** Call from a background thread. */
    fun loadBlocking(context: Context, song: Song, maxSize: Int = 640): Bitmap? {
        val key = key(song)
        cache.get(key)?.let { return it }
        if (synchronized(missing) { key in missing }) return null
        val bitmap = runCatching { decode(context, song, maxSize) }.getOrNull()
        if (bitmap != null) cache.put(key, bitmap) else synchronized(missing) { missing.add(key) }
        return bitmap
    }

    private fun decode(context: Context, song: Song, maxSize: Int): Bitmap? {
        val saved = song.cover
        if (!saved.isNullOrBlank() && saved.startsWith("/") && File(saved).exists()) {
            decodeBytes(File(saved).readBytes(), maxSize)?.let { return it }
        }
        val retriever = MediaMetadataRetriever()
        return try {
            if (song.path.startsWith("/")) retriever.setDataSource(song.path) else retriever.setDataSource(context, song.playUri())
            retriever.embeddedPicture?.let { decodeBytes(it, maxSize) }
        } finally {
            runCatching { retriever.release() }
        }
    }

    private fun decodeBytes(data: ByteArray, maxSize: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(data, 0, data.size, bounds)
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= maxSize && bounds.outHeight / (sample * 2) >= maxSize) sample *= 2
        return BitmapFactory.decodeByteArray(data, 0, data.size, BitmapFactory.Options().apply { inSampleSize = sample })
    }

    /** The main colour of a cover (used for the background of "In riproduzione"), a little more vivid. */
    fun dominantColor(bitmap: Bitmap): Int {
        val pixel = Bitmap.createScaledBitmap(bitmap, 1, 1, true).getPixel(0, 0)
        val hsv = FloatArray(3)
        Color.colorToHSV(pixel, hsv)
        hsv[1] = (hsv[1] * 1.15f).coerceIn(0f, 1f)
        hsv[2] = hsv[2].coerceIn(0.35f, 0.85f)
        return Color.HSVToColor(hsv)
    }
}
