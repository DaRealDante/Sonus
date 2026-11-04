package app.sonus.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.data.Song
import app.sonus.ui.LocalOpenSongActions
import app.sonus.ui.theme.LocalSonusColors

/** The three bars that move while a song plays. */
@Composable
fun EqBars(color: Color, animate: Boolean, modifier: Modifier = Modifier.size(18.dp)) {
    val transition = rememberInfiniteTransition(label = "eq")
    val first by transition.animateFloat(0.25f, 1f, infiniteRepeatable(tween(420, easing = LinearEasing), RepeatMode.Reverse), label = "a")
    val second by transition.animateFloat(0.3f, 0.9f, infiniteRepeatable(tween(560, easing = LinearEasing), RepeatMode.Reverse), label = "b")
    val third by transition.animateFloat(0.2f, 1f, infiniteRepeatable(tween(350, easing = LinearEasing), RepeatMode.Reverse), label = "c")
    Row(modifier = modifier, horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.Bottom) {
        listOf(first, second, third).forEach { value ->
            Box(
                modifier = Modifier.width(4.dp).fillMaxHeight(if (animate) value else 0.4f).clip(RoundedCornerShape(2.dp)).background(color),
            )
        }
    }
}

/** A song in a list: cover, title, artist, length and the menu. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SongRow(
    song: Song,
    isCurrent: Boolean,
    isPlaying: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = LocalSonusColors.current
    val openActions = LocalOpenSongActions.current
    Row(
        modifier = modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onClick, onLongClick = { openActions(song, song.entryId) })
            .padding(start = 20.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = Modifier.size(52.dp), contentAlignment = Alignment.Center) {
            CoverImage(song, Modifier.size(52.dp), 10.dp)
            if (isCurrent) {
                Box(
                    modifier = Modifier.size(52.dp).clip(RoundedCornerShape(10.dp)).background(Color.Black.copy(alpha = 0.45f)),
                    contentAlignment = Alignment.Center,
                ) { EqBars(colors.accent, isPlaying) }
            }
        }
        Column(modifier = Modifier.weight(1f).padding(horizontal = 14.dp)) {
            Text(
                song.title.ifBlank { "Senza titolo" },
                color = if (isCurrent) colors.accent else colors.text,
                fontWeight = FontWeight.SemiBold,
                fontSize = 16.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(song.displayArtist, color = colors.subtext, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (song.durationMs > 0) {
            Text(formatTime(song.durationMs), color = colors.muted, fontSize = 12.sp)
        }
        IconButton(onClick = { openActions(song, song.entryId) }) {
            Icon(Icons.Rounded.MoreVert, contentDescription = "Altro", tint = colors.subtext)
        }
    }
}

/** A song as a card with a big cover (rows of the Home). */
@Composable
fun SongCard(song: Song, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val colors = LocalSonusColors.current
    Column(modifier = modifier.width(150.dp).clip(RoundedCornerShape(14.dp)).clickable(onClick = onClick)) {
        CoverImage(song, Modifier.size(150.dp), 14.dp, 44.dp)
        Text(
            song.title.ifBlank { "Senza titolo" }, color = colors.text, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 8.dp),
        )
        Text(song.displayArtist, color = colors.subtext, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}
