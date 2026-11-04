package app.sonus.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.data.Library
import app.sonus.data.Song
import app.sonus.playback.PlayerController
import app.sonus.ui.LocalBottomPadding
import app.sonus.ui.components.EmptyState
import app.sonus.ui.components.GlassSurface
import app.sonus.ui.components.ScreenTitle
import app.sonus.ui.components.SongRow
import app.sonus.ui.rememberQuery
import app.sonus.ui.theme.LocalSonusColors

@Composable
fun SearchScreen() {
    val colors = LocalSonusColors.current
    val bottom = LocalBottomPadding.current
    var text by rememberSaveable { mutableStateOf("") }
    val results = rememberQuery(emptyList<Song>(), text) { if (text.isBlank()) emptyList() else Library.db.searchSongs(text.trim()) }
    val current = PlayerController.currentSong

    LazyColumn(modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = bottom)) {
        item { ScreenTitle("Cerca") }
        item {
            GlassSurface(modifier = Modifier.padding(horizontal = 20.dp).fillMaxWidth(), shape = RoundedCornerShape(28.dp), strong = true) {
                TextField(
                    value = text,
                    onValueChange = { text = it },
                    singleLine = true,
                    placeholder = { Text("Brani, artisti o album", color = colors.muted) },
                    leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, tint = colors.subtext) },
                    trailingIcon = {
                        if (text.isNotEmpty()) {
                            IconButton(onClick = { text = "" }) { Icon(Icons.Rounded.Close, contentDescription = "Cancella", tint = colors.subtext) }
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                    colors = TextFieldDefaults.colors(
                        focusedContainerColor = Color.Transparent, unfocusedContainerColor = Color.Transparent,
                        focusedIndicatorColor = Color.Transparent, unfocusedIndicatorColor = Color.Transparent,
                        cursorColor = colors.accent, focusedTextColor = colors.text, unfocusedTextColor = colors.text,
                    ),
                )
            }
        }
        if (text.isBlank()) {
            item {
                EmptyState(Icons.Rounded.Search, "Cerca nella tua musica", "Scrivi il titolo di un brano, un artista o un album. La ricerca su YouTube arriva con la prossima fase.")
            }
        } else if (results.isEmpty()) {
            item { EmptyState(Icons.Rounded.Search, "Nessun risultato", "Non ho trovato niente per \"${text.trim()}\".") }
        } else {
            item {
                Text(
                    "${results.size} risultati", color = colors.subtext, fontSize = 13.sp,
                    modifier = Modifier.padding(start = 20.dp, top = 16.dp, bottom = 4.dp),
                )
            }
            itemsIndexed(results, key = { _, song -> song.id }) { index, song ->
                SongRow(
                    song = song,
                    isCurrent = current?.id == song.id,
                    isPlaying = PlayerController.isPlaying,
                    onClick = { PlayerController.playSongs(results, index) },
                )
            }
        }
        item { Box(modifier = Modifier.padding(1.dp)) }
    }
}
