package app.sonus.ui.screens

import androidx.compose.animation.Crossfade
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.FavoriteBorder
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.QueueMusic
import androidx.compose.material.icons.rounded.Repeat
import androidx.compose.material.icons.rounded.RepeatOne
import androidx.compose.material.icons.rounded.Shuffle
import androidx.compose.material.icons.rounded.SkipNext
import androidx.compose.material.icons.rounded.SkipPrevious
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.core.REPEAT_OFF
import app.sonus.core.REPEAT_ONE
import app.sonus.data.Library
import app.sonus.playback.PlayerController
import app.sonus.ui.LocalNavigator
import app.sonus.ui.LocalOpenSongActions
import app.sonus.ui.components.AuroraBackground
import app.sonus.ui.components.CoverImage
import app.sonus.ui.components.GlassIconButton
import app.sonus.ui.components.GlassSurface
import app.sonus.ui.components.formatTime
import app.sonus.ui.components.rememberCoverColor
import app.sonus.ui.rememberQuery
import app.sonus.ui.theme.LocalSonusColors
import kotlinx.coroutines.delay

@Composable
fun NowPlayingScreen(onClose: () -> Unit) {
    val colors = LocalSonusColors.current
    val nav = LocalNavigator.current
    val openActions = LocalOpenSongActions.current
    val song = PlayerController.currentSong
    val tint = rememberCoverColor(song) ?: colors.accent
    val favorite = rememberQuery(false, song?.id) { song?.let { Library.db.getSong(it.id)?.favorite } ?: false }

    var position by remember { mutableLongStateOf(0L) }
    var dragging by remember { mutableStateOf<Float?>(null) }
    LaunchedEffect(song?.id) {
        while (true) {
            position = PlayerController.positionMs()
            delay(250)
        }
    }
    val duration = maxOf(PlayerController.durationMs, 1L)
    val fraction = dragging ?: (position.toFloat() / duration).coerceIn(0f, 1f)

    AuroraBackground(
        tint = tint,
        modifier = Modifier.pointerInput(Unit) {
            var total = 0f
            detectVerticalDragGestures(
                onDragStart = { total = 0f },
                onDragEnd = { if (total > 220f) onClose() },
                onDragCancel = {},
                onVerticalDrag = { _, amount -> total += amount },
            )
        },
    ) {
        Column(
            modifier = Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(modifier = Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                GlassIconButton(Icons.Rounded.KeyboardArrowDown, "Chiudi", onClose)
                Text(
                    "In riproduzione", color = colors.subtext, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f), textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                )
                GlassIconButton(Icons.Rounded.QueueMusic, "Coda", { nav.openQueue() })
            }
            Spacer(Modifier.weight(0.6f))
            Crossfade(targetState = song, label = "cover", modifier = Modifier.fillMaxWidth().aspectRatio(1f)) { shown ->
                CoverImage(
                    shown,
                    Modifier.fillMaxSize().shadow(28.dp, RoundedCornerShape(28.dp), spotColor = tint, ambientColor = tint),
                    28.dp, 72.dp,
                )
            }
            Spacer(Modifier.weight(0.5f))
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        song?.title?.ifBlank { "Senza titolo" } ?: "Nessun brano", color = colors.text, fontSize = 24.sp,
                        fontWeight = FontWeight.ExtraBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                    Text(song?.displayArtist ?: "", color = colors.subtext, fontSize = 16.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                if (song != null) {
                    IconButton(onClick = { Library.toggleFavorite(song.id) }) {
                        Icon(
                            if (favorite) Icons.Rounded.Favorite else Icons.Rounded.FavoriteBorder, contentDescription = "Preferito",
                            tint = if (favorite) colors.accent else colors.text, modifier = Modifier.size(28.dp),
                        )
                    }
                    IconButton(onClick = { openActions(song, null) }) {
                        Icon(Icons.Rounded.MoreVert, contentDescription = "Altro", tint = colors.text)
                    }
                }
            }
            Slider(
                value = fraction,
                onValueChange = { dragging = it },
                onValueChangeFinished = {
                    dragging?.let { PlayerController.seekTo((it * duration).toLong()) }
                    dragging = null
                },
                colors = SliderDefaults.colors(
                    thumbColor = Color.White, activeTrackColor = colors.accent, inactiveTrackColor = Color.White.copy(alpha = 0.22f),
                ),
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
            )
            Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(formatTime(if (dragging != null) (fraction * duration).toLong() else position), color = colors.subtext, fontSize = 12.sp)
                Text(formatTime(duration), color = colors.subtext, fontSize = 12.sp)
            }
            Spacer(Modifier.height(10.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { PlayerController.setShuffle(!PlayerController.shuffle) }) {
                    Icon(Icons.Rounded.Shuffle, contentDescription = "Casuale", tint = if (PlayerController.shuffle) colors.accent else colors.subtext, modifier = Modifier.size(26.dp))
                }
                IconButton(onClick = { PlayerController.previous() }, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Rounded.SkipPrevious, contentDescription = "Precedente", tint = colors.text, modifier = Modifier.size(38.dp))
                }
                Box(
                    modifier = Modifier.size(76.dp).clip(CircleShape).background(colors.accent).clickable { PlayerController.togglePlay() },
                    contentAlignment = Alignment.Center,
                ) {
                    if (PlayerController.isBuffering && !PlayerController.isPlaying) {
                        CircularProgressIndicator(color = colors.accentText, strokeWidth = 3.dp, modifier = Modifier.size(34.dp))
                    } else {
                        Icon(
                            if (PlayerController.isPlaying) Icons.Rounded.Pause else Icons.Rounded.PlayArrow,
                            contentDescription = "Riproduci o metti in pausa", tint = colors.accentText, modifier = Modifier.size(44.dp),
                        )
                    }
                }
                IconButton(onClick = { PlayerController.next() }, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Rounded.SkipNext, contentDescription = "Successivo", tint = colors.text, modifier = Modifier.size(38.dp))
                }
                IconButton(onClick = { PlayerController.cycleRepeat() }) {
                    Icon(
                        if (PlayerController.repeatMode == REPEAT_ONE) Icons.Rounded.RepeatOne else Icons.Rounded.Repeat,
                        contentDescription = "Ripeti",
                        tint = if (PlayerController.repeatMode != REPEAT_OFF) colors.accent else colors.subtext,
                        modifier = Modifier.size(26.dp),
                    )
                }
            }
            Spacer(Modifier.weight(0.4f))
            val next = PlayerController.queue.getOrNull(PlayerController.currentIndex + 1)
            if (next != null) {
                GlassSurface(modifier = Modifier.fillMaxWidth().padding(bottom = 14.dp), shape = RoundedCornerShape(18.dp), onClick = { nav.openQueue() }) {
                    Row(modifier = Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        CoverImage(next, Modifier.size(42.dp), 8.dp, 20.dp)
                        Column(modifier = Modifier.weight(1f).padding(horizontal = 12.dp)) {
                            Text("A seguire", color = colors.subtext, fontSize = 11.sp)
                            Text(next.title.ifBlank { "Senza titolo" }, color = colors.text, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        Icon(Icons.Rounded.QueueMusic, contentDescription = null, tint = colors.subtext)
                    }
                }
            } else {
                Spacer(Modifier.height(14.dp))
            }
        }
    }
}
