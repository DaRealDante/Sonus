package app.sonus.playback

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.media3.common.util.BitmapLoader
import app.sonus.data.CoverLoader
import app.sonus.data.Library
import com.google.common.util.concurrent.ListenableFuture
import com.google.common.util.concurrent.ListeningExecutorService
import com.google.common.util.concurrent.MoreExecutors
import java.util.concurrent.Executors

/** Gives the cover of the song to the notification and to the lock screen (address "sonus-cover://<id of the song>"). */
class CoverBitmapLoader(private val context: Context) : BitmapLoader {
    private val executor: ListeningExecutorService = MoreExecutors.listeningDecorator(Executors.newSingleThreadExecutor())

    override fun supportsMimeType(mimeType: String): Boolean = true

    override fun decodeBitmap(data: ByteArray): ListenableFuture<Bitmap> = executor.submit<Bitmap> {
        BitmapFactory.decodeByteArray(data, 0, data.size) ?: throw IllegalStateException("Copertina non valida")
    }

    override fun loadBitmap(uri: Uri): ListenableFuture<Bitmap> = executor.submit<Bitmap> {
        val song = uri.host?.toLongOrNull()?.let { Library.db.getSong(it) } ?: throw IllegalStateException("Brano non trovato")
        CoverLoader.loadBlocking(context, song, 512) ?: throw IllegalStateException("Nessuna copertina")
    }
}
