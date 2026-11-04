package app.sonus.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.MusicNote
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.sonus.data.CoverLoader
import app.sonus.data.Song
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** A soft coloured picture for songs without a cover (the colour depends on a number, like the PC app does). */
@Composable
fun PlaceholderCover(seed: Long, modifier: Modifier = Modifier, iconSize: Dp = 28.dp) {
    val hue = ((seed * 47) % 360).toFloat().let { if (it < 0) it + 360f else it }
    val first = Color.hsv(hue, 0.55f, 0.55f)
    val second = Color.hsv((hue + 40f) % 360f, 0.65f, 0.28f)
    Box(modifier = modifier.background(Brush.linearGradient(listOf(first, second))), contentAlignment = Alignment.Center) {
        Icon(Icons.Rounded.MusicNote, contentDescription = null, tint = Color.White.copy(alpha = 0.55f), modifier = Modifier.size(iconSize))
    }
}

/** The cover of a song. It is loaded when it is needed. */
@Composable
fun CoverImage(song: Song?, modifier: Modifier = Modifier, corner: Dp = 10.dp, iconSize: Dp = 28.dp) {
    val context = LocalContext.current
    var bitmap by remember(song?.id, song?.cover) { mutableStateOf(song?.let { CoverLoader.cached(it) }) }
    LaunchedEffect(song?.id, song?.cover) {
        if (song != null && bitmap == null && !CoverLoader.hasNoCover(song)) {
            bitmap = withContext(Dispatchers.IO) { CoverLoader.loadBlocking(context, song) }
        }
    }
    val shape = RoundedCornerShape(corner)
    val loaded = bitmap
    if (loaded != null) {
        Image(loaded.asImageBitmap(), contentDescription = null, contentScale = ContentScale.Crop, modifier = modifier.clip(shape))
    } else {
        PlaceholderCover(song?.id ?: 0L, modifier.clip(shape), iconSize)
    }
}

/** The main colour of the cover of a song (null while it is loading or when there is no cover). */
@Composable
fun rememberCoverColor(song: Song?): Color? {
    val context = LocalContext.current
    var color by remember(song?.id) { mutableStateOf<Color?>(null) }
    LaunchedEffect(song?.id) {
        color = if (song == null) null else withContext(Dispatchers.IO) {
            CoverLoader.loadBlocking(context, song)?.let { Color(CoverLoader.dominantColor(it)) }
        }
    }
    return color
}

/** The cover of a playlist: the covers of its first songs, as a mosaic. */
@Composable
fun CoverMosaic(songs: List<Song>, modifier: Modifier = Modifier, corner: Dp = 12.dp, seed: Long = 0L) {
    val shape = RoundedCornerShape(corner)
    val covers = songs.take(4)
    if (covers.size < 4) {
        if (covers.isEmpty()) PlaceholderCover(seed, modifier.clip(shape), 36.dp) else CoverImage(covers.first(), modifier, corner)
        return
    }
    Column(modifier = modifier.clip(shape)) {
        Row(modifier = Modifier.weight(1f).fillMaxWidth()) {
            CoverImage(covers[0], Modifier.weight(1f).fillMaxSize(), 0.dp, 18.dp)
            CoverImage(covers[1], Modifier.weight(1f).fillMaxSize(), 0.dp, 18.dp)
        }
        Row(modifier = Modifier.weight(1f).fillMaxWidth()) {
            CoverImage(covers[2], Modifier.weight(1f).fillMaxSize(), 0.dp, 18.dp)
            CoverImage(covers[3], Modifier.weight(1f).fillMaxSize(), 0.dp, 18.dp)
        }
    }
}

