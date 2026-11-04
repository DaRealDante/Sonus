package app.sonus.ui.screens

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.PlaylistPlay
import androidx.compose.material.icons.rounded.Shuffle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.data.Library
import app.sonus.data.Playlist
import app.sonus.data.Song
import app.sonus.playback.PlayerController
import app.sonus.ui.LocalBottomPadding
import app.sonus.ui.LocalStatus
import app.sonus.ui.components.AccentButton
import app.sonus.ui.components.ConfirmDialog
import app.sonus.ui.components.EmptyState
import app.sonus.ui.components.GlassButton
import app.sonus.ui.components.GlassIconButton
import app.sonus.ui.components.PlaylistCover
import app.sonus.ui.components.PlaylistEditDialog
import app.sonus.ui.components.SongRow
import app.sonus.ui.rememberQuery
import app.sonus.ui.theme.LocalSonusColors

@Composable
fun PlaylistScreen(playlistId: Long, onBack: () -> Unit) {
    val colors = LocalSonusColors.current
    val bottom = LocalBottomPadding.current
    val status = LocalStatus.current
    val playlist = rememberQuery<Playlist?>(null, playlistId) { Library.db.getPlaylist(playlistId) }
    val songs = rememberQuery(emptyList<Song>(), playlistId) { Library.db.playlistSongs(playlistId) }
    val current = PlayerController.currentSong
    var renaming by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }

    LazyColumn(modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = bottom)) {
        item {
            Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                GlassIconButton(Icons.AutoMirrored.Rounded.ArrowBack, "Indietro", onBack)
                Box(modifier = Modifier.weight(1f))
                GlassIconButton(Icons.Rounded.Edit, "Rinomina", { renaming = true })
                Box(modifier = Modifier.size(8.dp))
                GlassIconButton(Icons.Rounded.Delete, "Elimina", { deleting = true })
            }
        }
        item {
            Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                PlaylistCover(playlistId, Modifier.size(190.dp), 20.dp)
                Text(
                    playlist?.name ?: "", color = colors.text, fontSize = 26.sp, fontWeight = FontWeight.ExtraBold,
                    textAlign = TextAlign.Center, modifier = Modifier.padding(top = 16.dp),
                )
                if (!playlist?.description.isNullOrBlank()) {
                    Text(playlist?.description ?: "", color = colors.subtext, fontSize = 14.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp))
                }
                Text("${songs.size} brani", color = colors.muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
                Row(modifier = Modifier.padding(top = 16.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    AccentButton("Riproduci", { PlayerController.playSongs(songs, 0, false) }, icon = Icons.Rounded.PlayArrow)
                    GlassButton("Casuale", { PlayerController.playSongs(songs, null, true) }, icon = Icons.Rounded.Shuffle)
                }
            }
        }
        if (songs.isEmpty()) {
            item {
                EmptyState(Icons.Rounded.PlaylistPlay, "Playlist vuota", "Tocca i tre puntini di un brano e scegli \"Aggiungi a una playlist\".")
            }
        } else {
            item { Box(modifier = Modifier.size(12.dp)) }
            itemsIndexed(songs, key = { _, song -> song.entryId ?: song.id }) { index, song ->
                SongRow(
                    song = song,
                    isCurrent = current?.id == song.id,
                    isPlaying = PlayerController.isPlaying,
                    onClick = { PlayerController.playSongs(songs, index) },
                )
            }
        }
    }

    if (renaming && playlist != null) {
        PlaylistEditDialog(
            title = "Modifica playlist", initialName = playlist.name, initialDescription = playlist.description, confirmText = "Salva",
            onSave = { name, description -> Library.updatePlaylist(playlistId, name, description); renaming = false },
            onDismiss = { renaming = false },
        )
    }
    if (deleting) {
        ConfirmDialog(
            title = "Eliminare la playlist?",
            text = "I brani restano nella libreria.",
            confirmText = "Elimina",
            onConfirm = { deleting = false; Library.deletePlaylist(playlistId); status("Playlist eliminata"); onBack() },
            onDismiss = { deleting = false },
        )
    }
}
