package app.sonus.ui

import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.sonus.data.Song

/** Opens the menu of a song (second value: the row of the song in a playlist, if it comes from one). */
val LocalOpenSongActions = staticCompositionLocalOf<(Song, Long?) -> Unit> { { _, _ -> } }

/** Shows a short message at the bottom. */
val LocalStatus = staticCompositionLocalOf<(String) -> Unit> { {} }

/** Space to leave at the bottom of the lists, so the floating bar does not cover the last rows. */
val LocalBottomPadding = staticCompositionLocalOf<Dp> { 100.dp }

/** Actions of the library that need the phone (file picker, permission). */
class LibraryActions(val importFiles: () -> Unit, val scanDevice: () -> Unit)

val LocalLibraryActions = staticCompositionLocalOf { LibraryActions({}, {}) }

/** Where the screens can go. */
interface Navigator {
    fun openPlaylist(id: Long)
    fun openQueue()
    fun openSettings()
    fun openNowPlaying()
    fun goTo(tab: Tab)
}

val LocalNavigator = staticCompositionLocalOf<Navigator> {
    object : Navigator {
        override fun openPlaylist(id: Long) {}
        override fun openQueue() {}
        override fun openSettings() {}
        override fun openNowPlaying() {}
        override fun goTo(tab: Tab) {}
    }
}
