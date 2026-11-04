package app.sonus.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.ArrowDownward
import androidx.compose.material.icons.rounded.ArrowUpward
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.QueueMusic
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.data.Song
import app.sonus.playback.PlayerController
import app.sonus.ui.LocalBottomPadding
import app.sonus.ui.components.CoverImage
import app.sonus.ui.components.EmptyState
import app.sonus.ui.components.EqBars
import app.sonus.ui.components.GlassButton
import app.sonus.ui.components.GlassIconButton
import app.sonus.ui.theme.LocalSonusColors

@Composable
fun QueueScreen(onBack: () -> Unit) {
    val colors = LocalSonusColors.current
    val bottom = LocalBottomPadding.current
    val queue = PlayerController.queue
    val currentIndex = PlayerController.currentIndex

    LazyColumn(modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = bottom)) {
        item {
            Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                GlassIconButton(Icons.AutoMirrored.Rounded.ArrowBack, "Indietro", onBack)
                Text("Coda", color = colors.text, fontSize = 26.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.weight(1f).padding(start = 14.dp))
                if (currentIndex in 0 until queue.size - 1) {
                    GlassButton("Svuota", { PlayerController.clearUpcoming() })
                }
            }
        }
        if (queue.isEmpty() || currentIndex < 0) {
            item { EmptyState(Icons.Rounded.QueueMusic, "La coda è vuota", "Scegli un brano o aggiungine dal menu dei tre puntini.") }
        } else {
            item { QueueHeader("In riproduzione") }
            item { QueueRow(queue[currentIndex], currentIndex, currentIndex, queue.size, true) }
            if (currentIndex + 1 < queue.size) {
                item { QueueHeader("Prossimi brani") }
                itemsIndexed(queue.subList(currentIndex + 1, queue.size)) { offset, song ->
                    val index = currentIndex + 1 + offset
                    QueueRow(song, index, currentIndex, queue.size, false)
                }
            }
        }
    }
}

@Composable
private fun QueueHeader(text: String) {
    val colors = LocalSonusColors.current
    Text(text, color = colors.subtext, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(start = 20.dp, top = 16.dp, bottom = 6.dp))
}

@Composable
private fun QueueRow(song: Song, index: Int, currentIndex: Int, size: Int, isCurrent: Boolean) {
    val colors = LocalSonusColors.current
    Row(
        modifier = Modifier.fillMaxWidth().clickable { if (!isCurrent) PlayerController.jumpTo(index) }.padding(start = 20.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = Modifier.size(48.dp), contentAlignment = Alignment.Center) {
            CoverImage(song, Modifier.size(48.dp), 10.dp)
            if (isCurrent) EqBars(colors.accent, PlayerController.isPlaying)
        }
        Column(modifier = Modifier.weight(1f).padding(horizontal = 14.dp)) {
            Text(song.title.ifBlank { "Senza titolo" }, color = if (isCurrent) colors.accent else colors.text, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(song.displayArtist, color = colors.subtext, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (!isCurrent) {
            IconButton(onClick = { PlayerController.moveInQueue(index, index - 1) }, enabled = index - 1 > currentIndex) {
                Icon(Icons.Rounded.ArrowUpward, contentDescription = "Sposta su", tint = if (index - 1 > currentIndex) colors.subtext else colors.muted, modifier = Modifier.size(20.dp))
            }
            IconButton(onClick = { PlayerController.moveInQueue(index, index + 1) }, enabled = index + 1 < size) {
                Icon(Icons.Rounded.ArrowDownward, contentDescription = "Sposta giù", tint = if (index + 1 < size) colors.subtext else colors.muted, modifier = Modifier.size(20.dp))
            }
            IconButton(onClick = { PlayerController.removeFromQueue(listOf(index)) }) {
                Icon(Icons.Rounded.Close, contentDescription = "Rimuovi", tint = colors.subtext, modifier = Modifier.size(20.dp))
            }
        }
    }
}
