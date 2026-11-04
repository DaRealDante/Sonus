package app.sonus.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.FavoriteBorder
import androidx.compose.material.icons.rounded.LibraryAdd
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.PlaylistPlay
import androidx.compose.material.icons.rounded.Shuffle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.data.Library
import app.sonus.data.Playlist
import app.sonus.data.Song
import app.sonus.playback.PlayerController
import app.sonus.ui.LocalBottomPadding
import app.sonus.ui.LocalLibraryActions
import app.sonus.ui.LocalNavigator
import app.sonus.ui.components.AccentButton
import app.sonus.ui.components.EmptyState
import app.sonus.ui.components.GlassButton
import app.sonus.ui.components.GlassChip
import app.sonus.ui.components.GlassIconButton
import app.sonus.ui.components.PlaylistCover
import app.sonus.ui.components.PlaylistEditDialog
import app.sonus.ui.components.ScreenTitle
import app.sonus.ui.components.SongRow
import app.sonus.ui.rememberQuery
import app.sonus.ui.theme.LocalSonusColors

private enum class LibraryTab(val label: String) {
    Songs("Brani"), Favorites("Preferiti"), Recent("Recenti"), Playlists("Playlist"), Downloads("Download")
}

@Composable
fun LibraryScreen() {
    val colors = LocalSonusColors.current
    val bottom = LocalBottomPadding.current
    val nav = LocalNavigator.current
    val actions = LocalLibraryActions.current
    var tabName by rememberSaveable { mutableStateOf(LibraryTab.Songs.name) }
    val tab = LibraryTab.valueOf(tabName)
    var creating by remember { mutableStateOf(false) }

    val songs = rememberQuery(emptyList<Song>(), tab) {
        when (tab) {
            LibraryTab.Songs -> Library.db.allSongs()
            LibraryTab.Favorites -> Library.db.favoriteSongs()
            LibraryTab.Recent -> Library.db.recentlyPlayed(50)
            else -> emptyList()
        }
    }
    val playlists = rememberQuery(emptyList<Playlist>()) { Library.db.playlists() }
    val current = PlayerController.currentSong

    LazyColumn(modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = bottom)) {
        item {
            ScreenTitle("Libreria") {
                GlassIconButton(Icons.Rounded.LibraryAdd, "Aggiungi musica", { actions.scanDevice() })
            }
        }
        item {
            LazyRow(contentPadding = PaddingValues(horizontal = 20.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(LibraryTab.entries.toList()) { item -> GlassChip(item.label, item == tab, { tabName = item.name }) }
            }
        }
        when (tab) {
            LibraryTab.Playlists -> {
                item {
                    Row(modifier = Modifier.padding(horizontal = 20.dp, vertical = 14.dp)) {
                        AccentButton("Nuova playlist", { creating = true }, icon = Icons.Rounded.Add)
                    }
                }
                if (playlists.isEmpty()) {
                    item { EmptyState(Icons.Rounded.PlaylistPlay, "Nessuna playlist", "Crea la tua prima playlist e mettici i brani che ami.") }
                }
                items(playlists, key = { it.id }) { playlist ->
                    Row(
                        modifier = Modifier.fillMaxWidth().clickable { nav.openPlaylist(playlist.id) }.padding(horizontal = 20.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        PlaylistCover(playlist.id, Modifier.size(64.dp), 12.dp)
                        Column(modifier = Modifier.padding(start = 16.dp)) {
                            Text(playlist.name, color = colors.text, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("${playlist.songCount} brani", color = colors.subtext, fontSize = 13.sp)
                        }
                    }
                }
            }
            LibraryTab.Downloads -> {
                item {
                    EmptyState(Icons.Rounded.Download, "Download", "Qui troverai i brani scaricati da YouTube. Arriva con la prossima fase.")
                }
            }
            else -> {
                if (songs.isEmpty()) {
                    item {
                        when (tab) {
                            LibraryTab.Favorites -> EmptyState(Icons.Rounded.FavoriteBorder, "Nessun preferito", "Tocca i tre puntini di un brano e scegli \"Aggiungi ai preferiti\".")
                            LibraryTab.Recent -> EmptyState(Icons.Rounded.LibraryMusic, "Ancora niente", "I brani che ascolti compaiono qui.")
                            else -> EmptyState(Icons.Rounded.LibraryMusic, "La libreria è vuota", "Aggiungi la musica che hai sul telefono.") {
                                AccentButton("Aggiungi la musica del telefono", { actions.scanDevice() })
                            }
                        }
                    }
                } else {
                    item {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            AccentButton("Riproduci", { PlayerController.playSongs(songs, 0, false) }, icon = Icons.Rounded.PlayArrow)
                            GlassButton("Casuale", { PlayerController.playSongs(songs, null, true) }, icon = Icons.Rounded.Shuffle)
                            Text("${songs.size} brani", color = colors.subtext, fontSize = 13.sp, modifier = Modifier.weight(1f), maxLines = 1)
                        }
                    }
                    itemsIndexed(songs, key = { _, song -> song.id }) { index, song ->
                        SongRow(
                            song = song,
                            isCurrent = current?.id == song.id,
                            isPlaying = PlayerController.isPlaying,
                            onClick = { PlayerController.playSongs(songs, index) },
                        )
                    }
                }
            }
        }
    }

    if (creating) {
        PlaylistEditDialog(
            title = "Nuova playlist", initialName = "", initialDescription = "", confirmText = "Crea",
            onSave = { name, description ->
                creating = false
                nav.openPlaylist(Library.createPlaylist(name, description))
            },
            onDismiss = { creating = false },
        )
    }
}
