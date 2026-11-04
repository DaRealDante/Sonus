package app.sonus.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.FavoriteBorder
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.PlaylistAdd
import androidx.compose.material.icons.rounded.Queue
import androidx.compose.material.icons.rounded.SkipNext
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.data.Library
import app.sonus.data.Playlist
import app.sonus.data.Song
import app.sonus.playback.PlayerController
import app.sonus.ui.LocalStatus
import app.sonus.ui.rememberQuery
import app.sonus.ui.theme.LocalSonusColors

@Composable
fun SonusTextField(value: String, onValueChange: (String) -> Unit, label: String, modifier: Modifier = Modifier, singleLine: Boolean = true) {
    val colors = LocalSonusColors.current
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        singleLine = singleLine,
        modifier = modifier.fillMaxWidth(),
        colors = OutlinedTextFieldDefaults.colors(
            focusedTextColor = colors.text, unfocusedTextColor = colors.text,
            focusedBorderColor = colors.accent, unfocusedBorderColor = colors.line,
            focusedLabelColor = colors.accent, unfocusedLabelColor = colors.subtext,
            cursorColor = colors.accent,
        ),
    )
}

@Composable
fun ConfirmDialog(title: String, text: String, confirmText: String, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    val colors = LocalSonusColors.current
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = colors.elevated,
        titleContentColor = colors.text,
        textContentColor = colors.subtext,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = { TextButton(onClick = onConfirm) { Text(confirmText, color = colors.accent) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annulla", color = colors.subtext) } },
    )
}

@Composable
fun PlaylistEditDialog(
    title: String, initialName: String, initialDescription: String, confirmText: String,
    onSave: (String, String) -> Unit, onDismiss: () -> Unit,
) {
    val colors = LocalSonusColors.current
    var name by remember { mutableStateOf(initialName) }
    var description by remember { mutableStateOf(initialDescription) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = colors.elevated,
        titleContentColor = colors.text,
        title = { Text(title) },
        text = {
            Column {
                SonusTextField(name, { name = it }, "Nome")
                Spacer(Modifier.height(10.dp))
                SonusTextField(description, { description = it }, "Descrizione (facoltativa)", singleLine = false)
            }
        },
        confirmButton = {
            TextButton(onClick = { if (name.isNotBlank()) onSave(name.trim(), description.trim()) }, enabled = name.isNotBlank()) {
                Text(confirmText, color = if (name.isNotBlank()) colors.accent else colors.muted)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annulla", color = colors.subtext) } },
    )
}

@Composable
fun SongEditDialog(song: Song, onSave: (String, String, String) -> Unit, onDismiss: () -> Unit) {
    val colors = LocalSonusColors.current
    var title by remember { mutableStateOf(song.title) }
    var artist by remember { mutableStateOf(song.artist) }
    var album by remember { mutableStateOf(song.album) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = colors.elevated,
        titleContentColor = colors.text,
        title = { Text("Modifica informazioni") },
        text = {
            Column {
                SonusTextField(title, { title = it }, "Titolo")
                Spacer(Modifier.height(10.dp))
                SonusTextField(artist, { artist = it }, "Artista")
                Spacer(Modifier.height(10.dp))
                SonusTextField(album, { album = it }, "Album")
            }
        },
        confirmButton = {
            TextButton(onClick = { if (title.isNotBlank()) onSave(title.trim(), artist.trim(), album.trim()) }, enabled = title.isNotBlank()) {
                Text("Salva", color = if (title.isNotBlank()) colors.accent else colors.muted)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annulla", color = colors.subtext) } },
    )
}

@Composable
private fun ActionItem(icon: ImageVector, text: String, onClick: () -> Unit, danger: Boolean = false) {
    val colors = LocalSonusColors.current
    val tint = if (danger) androidx.compose.ui.graphics.Color(0xFFF23F42) else colors.text
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 24.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = if (danger) tint else colors.subtext, modifier = Modifier.size(24.dp))
        Text(text, color = tint, fontSize = 16.sp, modifier = Modifier.padding(start = 18.dp))
    }
}

/** The menu of a song (long press, or the three dots). [entryId] is set when the song is shown inside a playlist. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SongActionsSheet(song: Song, entryId: Long?, onDismiss: () -> Unit) {
    val colors = LocalSonusColors.current
    val status = LocalStatus.current
    var pickPlaylist by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    val favorite = rememberQuery(song.favorite, song.id) { Library.db.getSong(song.id)?.favorite ?: false }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = colors.elevated,
        contentColor = colors.text,
    ) {
        Column(modifier = Modifier.navigationBarsPadding()) {
            Row(modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                CoverImage(song, Modifier.size(56.dp), 10.dp)
                Column(modifier = Modifier.padding(start = 16.dp)) {
                    Text(song.title.ifBlank { "Senza titolo" }, fontWeight = FontWeight.Bold, fontSize = 17.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(song.displayArtist, color = colors.subtext, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            Spacer(Modifier.height(6.dp))
            ActionItem(Icons.Rounded.PlayArrow, "Riproduci ora", { PlayerController.playSongs(listOf(song)); onDismiss() })
            ActionItem(Icons.Rounded.SkipNext, "Riproduci dopo", { PlayerController.playNext(listOf(song)); status("Aggiunto come prossimo brano"); onDismiss() })
            ActionItem(Icons.Rounded.Queue, "Aggiungi alla coda", { PlayerController.addToQueue(listOf(song)); status("Aggiunto alla coda"); onDismiss() })
            ActionItem(Icons.Rounded.PlaylistAdd, "Aggiungi a una playlist", { pickPlaylist = true })
            ActionItem(
                if (favorite) Icons.Rounded.Favorite else Icons.Rounded.FavoriteBorder,
                if (favorite) "Rimuovi dai preferiti" else "Aggiungi ai preferiti",
                { Library.toggleFavorite(song.id); onDismiss() },
            )
            ActionItem(Icons.Rounded.Edit, "Modifica informazioni", { editing = true })
            if (entryId != null) {
                ActionItem(Icons.Rounded.Delete, "Rimuovi dalla playlist", { Library.removeEntries(listOf(entryId)); status("Rimosso dalla playlist"); onDismiss() })
            }
            ActionItem(Icons.Rounded.Delete, "Rimuovi dalla libreria", { deleting = true }, danger = true)
            Spacer(Modifier.height(12.dp))
        }
    }

    if (pickPlaylist) {
        PlaylistPickerSheet(
            onDismiss = { pickPlaylist = false },
            onPick = { playlist ->
                Library.addToPlaylist(playlist.id, listOf(song.id))
                status("Aggiunto a \"${playlist.name}\"")
                pickPlaylist = false
                onDismiss()
            },
            onCreate = { name ->
                val id = Library.createPlaylist(name)
                Library.addToPlaylist(id, listOf(song.id))
                status("Creata la playlist \"$name\"")
                pickPlaylist = false
                onDismiss()
            },
        )
    }
    if (editing) {
        SongEditDialog(
            song,
            onSave = { title, artist, album ->
                Library.updateSong(song.id, mapOf("title" to title, "artist" to artist, "album" to album))
                editing = false
                onDismiss()
            },
            onDismiss = { editing = false },
        )
    }
    if (deleting) {
        ConfirmDialog(
            title = "Rimuovere dalla libreria?",
            text = "\"${song.title}\" sparisce dalla libreria di Sonus. Il file sul telefono non viene cancellato.",
            confirmText = "Rimuovi",
            onConfirm = { Library.deleteSongs(listOf(song.id)); deleting = false; onDismiss() },
            onDismiss = { deleting = false },
        )
    }
}

/** Choose a playlist, or make a new one. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaylistPickerSheet(onDismiss: () -> Unit, onPick: (Playlist) -> Unit, onCreate: (String) -> Unit) {
    val colors = LocalSonusColors.current
    val playlists = rememberQuery(emptyList<Playlist>()) { Library.db.playlists() }
    var creating by remember { mutableStateOf(false) }
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = colors.elevated,
        contentColor = colors.text,
    ) {
        Column(modifier = Modifier.navigationBarsPadding()) {
            Text("Aggiungi a una playlist", fontWeight = FontWeight.Bold, fontSize = 18.sp, modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
            ActionItem(Icons.Rounded.Add, "Nuova playlist", { creating = true })
            LazyColumn {
                items(playlists, key = { it.id }) { playlist ->
                    Row(
                        modifier = Modifier.fillMaxWidth().clickable { onPick(playlist) }.padding(horizontal = 24.dp, vertical = 14.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(playlist.name, fontSize = 16.sp, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text("${playlist.songCount} brani", color = colors.subtext, fontSize = 13.sp)
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
        }
    }
    if (creating) {
        PlaylistEditDialog(
            title = "Nuova playlist", initialName = "", initialDescription = "", confirmText = "Crea",
            onSave = { name, _ -> creating = false; onCreate(name) },
            onDismiss = { creating = false },
        )
    }
}
