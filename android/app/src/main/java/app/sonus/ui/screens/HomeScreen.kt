package app.sonus.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
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
import app.sonus.ui.components.GlassIconButton
import app.sonus.ui.components.GlassSurface
import app.sonus.ui.components.PlaylistCover
import app.sonus.ui.components.SectionTitle
import app.sonus.ui.components.SongCard
import app.sonus.ui.rememberQuery
import app.sonus.ui.theme.LocalSonusColors
import java.util.Calendar

private fun greeting(): String {
    val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
    return when {
        hour < 6 -> "Buonanotte"
        hour < 13 -> "Buongiorno"
        hour < 19 -> "Buon pomeriggio"
        else -> "Buonasera"
    }
}

@Composable
fun HomeScreen() {
    val colors = LocalSonusColors.current
    val nav = LocalNavigator.current
    val actions = LocalLibraryActions.current
    val bottom = LocalBottomPadding.current

    val songs = rememberQuery<List<Song>?>(null) { Library.db.allSongs() }
    val playlists = rememberQuery(emptyList<Playlist>()) { Library.db.playlists() }
    val favorites = rememberQuery(emptyList<Song>()) { Library.db.favoriteSongs() }
    val played = rememberQuery(emptyList<Song>()) { Library.db.recentlyPlayed(12) }
    val added = rememberQuery(emptyList<Song>()) { Library.db.recentSongs(12) }
    val most = rememberQuery(emptyList<Song>()) { Library.db.mostPlayed(12) }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(bottom = bottom),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(greeting(), fontSize = 30.sp, fontWeight = FontWeight.ExtraBold, color = colors.text)
                    Text("Cosa ascoltiamo oggi?", fontSize = 14.sp, color = colors.subtext)
                }
                GlassIconButton(Icons.Rounded.Settings, "Impostazioni", { nav.openSettings() })
            }
        }
        val loaded = songs
        if (loaded != null && loaded.isEmpty()) {
            item {
                GlassSurface(modifier = Modifier.padding(horizontal = 20.dp).fillMaxWidth(), strong = true) {
                    EmptyState(
                        Icons.Rounded.LibraryMusic,
                        "La tua libreria è vuota",
                        "Aggiungi la musica che hai sul telefono per cominciare.",
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            AccentButton("Aggiungi la musica del telefono", { actions.scanDevice() }, icon = Icons.Rounded.LibraryMusic)
                            GlassButton("Importa file", { actions.importFiles() }, icon = Icons.Rounded.FolderOpen)
                        }
                    }
                }
            }
        } else if (loaded != null) {
            // Quick tiles: favourites and the first playlists, two by row
            val tiles = buildList<QuickTileData> {
                add(QuickTileData(null, "Brani che ti piacciono") { nav.goTo(app.sonus.ui.Tab.Library) })
                playlists.take(7).forEach { playlist -> add(QuickTileData(playlist, playlist.name) { nav.openPlaylist(playlist.id) }) }
            }
            items(tiles.chunked(2)) { pair ->
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    pair.forEach { tile -> QuickTile(tile, favorites, Modifier.weight(1f)) }
                    if (pair.size == 1) Spacer(Modifier.weight(1f))
                }
            }
            if (played.isNotEmpty()) item { SongRowSection("Ascoltati di recente", played) }
            if (added.isNotEmpty()) item { SongRowSection("Aggiunti di recente", added) }
            if (most.isNotEmpty()) item { SongRowSection("I più ascoltati", most) }
            if (playlists.isNotEmpty()) {
                item {
                    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        SectionTitle("Le tue playlist")
                        LazyRow(contentPadding = PaddingValues(horizontal = 20.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            items(playlists, key = { it.id }) { playlist ->
                                Column(
                                    modifier = Modifier.width150().clip(RoundedCornerShape(14.dp)).clickable { nav.openPlaylist(playlist.id) },
                                ) {
                                    PlaylistCover(playlist.id, Modifier.size(150.dp), 14.dp)
                                    Text(
                                        playlist.name, color = colors.text, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
                                        maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 8.dp),
                                    )
                                    Text("${playlist.songCount} brani", color = colors.subtext, fontSize = 12.sp)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun Modifier.width150(): Modifier = this.then(Modifier.size(width = 150.dp, height = 214.dp))

private class QuickTileData(val playlist: Playlist?, val title: String, val onOpen: () -> Unit)

@Composable
private fun SongRowSection(title: String, songs: List<Song>) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SectionTitle(title)
        LazyRow(contentPadding = PaddingValues(horizontal = 20.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            items(songs, key = { it.id }) { song ->
                SongCard(song, onClick = { PlayerController.playSongs(songs, songs.indexOf(song)) })
            }
        }
    }
}

@Composable
private fun QuickTile(tile: QuickTileData, favorites: List<Song>, modifier: Modifier) {
    val colors = LocalSonusColors.current
    GlassSurface(modifier = modifier.height(58.dp), shape = RoundedCornerShape(14.dp), onClick = tile.onOpen) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxSize()) {
            if (tile.playlist == null) {
                Box(
                    modifier = Modifier.size(58.dp).background(Brush.linearGradient(listOf(colors.accent, Color(0xFF3A3A8C)))),
                    contentAlignment = Alignment.Center,
                ) { Icon(Icons.Rounded.Favorite, contentDescription = null, tint = Color.White) }
            } else {
                PlaylistCover(tile.playlist.id, Modifier.size(58.dp), 0.dp)
            }
            Text(
                tile.title, color = colors.text, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f).padding(horizontal = 10.dp),
            )
            Box(
                modifier = Modifier.padding(end = 8.dp).size(30.dp).clip(RoundedCornerShape(50)).background(colors.accent)
                    .clickable {
                        val list = if (tile.playlist == null) favorites else app.sonus.data.Library.db.playlistSongs(tile.playlist.id)
                        PlayerController.playSongs(list, 0)
                    },
                contentAlignment = Alignment.Center,
            ) { Icon(Icons.Rounded.PlayArrow, contentDescription = "Riproduci", tint = colors.accentText, modifier = Modifier.size(20.dp)) }
        }
    }
}
