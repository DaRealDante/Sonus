package it.sonus.mobile

import android.graphics.Bitmap
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.core.graphics.ColorUtils
import androidx.core.graphics.drawable.toBitmap
import coil.imageLoader
import coil.request.ImageRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

object VideoTint { var color by mutableStateOf(Color(0xFF263B33)) }

fun imageTint(bitmap: Bitmap): Color {
    var best = bitmap.getPixel(bitmap.width / 2, bitmap.height / 2)
    var score = -1f
    val hsl = FloatArray(3)
    for (x in 0 until bitmap.width step (bitmap.width / 8).coerceAtLeast(1)) for (y in 0 until bitmap.height step (bitmap.height / 8).coerceAtLeast(1)) {
        val pixel = bitmap.getPixel(x, y)
        ColorUtils.colorToHSL(pixel, hsl)
        val candidate = hsl[1] * (1f - kotlin.math.abs(hsl[2] - .45f))
        if (candidate > score) { score = candidate; best = pixel }
    }
    return Color(best)
}

@Composable fun songTint(song: JSONObject, settings: JSONObject): Color {
    val context = LocalContext.current
    val source = settings.str("songColorSource", "cover")
    val fallback = MaterialTint(settings)
    val cover = song.str("cover").ifEmpty { song.str("image").ifEmpty { song.str("thumbnail") } }
    val color by produceState(fallback, cover, source, settings.flag("fxCoverColors", true)) {
        value = fallback
        if (settings.flag("fxCoverColors", true) && source == "cover" && cover.isNotEmpty()) {
            runCatching {
                val request = ImageRequest.Builder(context).data(if (cover.startsWith("http")) cover else File(cover)).size(48).allowHardware(false).build()
                val drawable = context.imageLoader.execute(request).drawable
                if (drawable != null) value = withContext(Dispatchers.Default) { imageTint(drawable.toBitmap(48, 48)) }
            }
        }
    }
    return when {
        !settings.flag("fxCoverColors", true) -> fallback
        source == "custom" -> remember(settings.str("songColorCustom")) { runCatching { Color(android.graphics.Color.parseColor(settings.str("songColorCustom", "#1ED760"))) }.getOrDefault(fallback) }
        source == "video" -> VideoTint.color
        else -> color
    }
}

private fun MaterialTint(settings: JSONObject) = runCatching { Color(android.graphics.Color.parseColor(settings.obj("themeColors").str("accent", "#1ED760"))) }.getOrDefault(Color(0xFF1ED760))
