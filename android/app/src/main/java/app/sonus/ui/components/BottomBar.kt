package app.sonus.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.SkipNext
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.playback.PlayerController
import app.sonus.ui.Tab
import app.sonus.ui.theme.LocalSonusColors
import kotlinx.coroutines.delay

/** The bar above the menu: the song that plays now. A tap opens "In riproduzione". */
@Composable
fun MiniPlayer(onOpen: () -> Unit, modifier: Modifier = Modifier) {
    val song = PlayerController.currentSong ?: return
    val colors = LocalSonusColors.current
    var position by remember { mutableLongStateOf(0L) }
    LaunchedEffect(song.id, PlayerController.isPlaying) {
        while (true) {
            position = PlayerController.positionMs()
            if (!PlayerController.isPlaying) break
            delay(500)
        }
    }
    val duration = maxOf(PlayerController.durationMs, 1L)
    GlassSurface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(22.dp),
        strong = true,
        base = Color.Black.copy(alpha = 0.40f),
        onClick = onOpen,
    ) {
        Column {
            Row(modifier = Modifier.padding(start = 10.dp, end = 4.dp, top = 8.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                CoverImage(song, Modifier.size(46.dp), 10.dp, 22.dp)
                Column(modifier = Modifier.weight(1f).padding(horizontal = 12.dp)) {
                    Text(song.title.ifBlank { "Senza titolo" }, color = colors.text, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(song.displayArtist, color = colors.subtext, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                Box(
                    modifier = Modifier.size(40.dp).clip(CircleShape).background(colors.accent).clickable { PlayerController.togglePlay() },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        if (PlayerController.isPlaying) Icons.Rounded.Pause else Icons.Rounded.PlayArrow,
                        contentDescription = "Riproduci o metti in pausa", tint = colors.accentText, modifier = Modifier.size(26.dp),
                    )
                }
                IconButton(onClick = { PlayerController.next() }) {
                    Icon(Icons.Rounded.SkipNext, contentDescription = "Successivo", tint = colors.text)
                }
            }
            LinearProgressIndicator(
                progress = { (position.toFloat() / duration).coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth().height(2.dp),
                color = colors.accent,
                trackColor = Color.White.copy(alpha = 0.10f),
            )
        }
    }
}

/** The menu at the bottom: a glass pill with the four main places. */
@Composable
fun GlassNavBar(selected: Tab, onSelect: (Tab) -> Unit, modifier: Modifier = Modifier) {
    val colors = LocalSonusColors.current
    GlassSurface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(28.dp),
        strong = true,
        base = Color.Black.copy(alpha = 0.40f),
    ) {
        Row(modifier = Modifier.padding(horizontal = 8.dp, vertical = 8.dp), horizontalArrangement = Arrangement.SpaceEvenly) {
            Tab.entries.forEach { item ->
                val active = item == selected
                Column(
                    modifier = Modifier.weight(1f).clip(RoundedCornerShape(20.dp))
                        .background(if (active) colors.accentDim else Color.Transparent)
                        .clickable { onSelect(item) }.padding(vertical = 7.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Icon(item.icon, contentDescription = item.label, tint = if (active) colors.accent else colors.subtext, modifier = Modifier.size(24.dp))
                    Text(item.label, color = if (active) colors.accent else colors.subtext, fontSize = 11.sp, fontWeight = if (active) FontWeight.Bold else FontWeight.Normal)
                }
            }
        }
    }
}
