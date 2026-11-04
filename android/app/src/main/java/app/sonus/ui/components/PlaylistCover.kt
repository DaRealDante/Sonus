package app.sonus.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.sonus.data.Library
import app.sonus.data.Song
import app.sonus.ui.rememberQuery

/** Songs of a playlist (the first ones are enough for the cover). */
@Composable
fun PlaylistCover(playlistId: Long, modifier: Modifier = Modifier, corner: Dp = 12.dp) {
    val songs = rememberQuery(emptyList<Song>(), playlistId) { Library.db.playlistSongs(playlistId).take(4) }
    CoverMosaic(songs, modifier, corner, seed = playlistId)
}
