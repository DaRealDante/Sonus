package app.sonus.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Explore
import androidx.compose.material.icons.rounded.Home
import androidx.compose.material.icons.rounded.LibraryMusic
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import app.sonus.core.Palette
import app.sonus.data.AppPrefs
import app.sonus.data.Song
import app.sonus.data.SongImporter
import app.sonus.playback.PlayerController
import app.sonus.ui.components.AuroraBackground
import app.sonus.ui.components.GlassNavBar
import app.sonus.ui.components.MiniPlayer
import app.sonus.ui.components.SongActionsSheet
import app.sonus.ui.screens.DiscoverScreen
import app.sonus.ui.screens.HomeScreen
import app.sonus.ui.screens.LibraryScreen
import app.sonus.ui.screens.NowPlayingScreen
import app.sonus.ui.screens.PlaylistScreen
import app.sonus.ui.screens.QueueScreen
import app.sonus.ui.screens.SearchScreen
import app.sonus.ui.screens.SettingsScreen
import app.sonus.ui.theme.SonusTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** The main places of the app (on PC they are the sidebar: Home, Cerca, Scopri, Libreria...). */
enum class Tab(val label: String, val icon: ImageVector) {
    Home("Home", Icons.Rounded.Home),
    Search("Cerca", Icons.Rounded.Search),
    Discover("Scopri", Icons.Rounded.Explore),
    Library("Libreria", Icons.Rounded.LibraryMusic),
}

private sealed interface Route {
    data class Root(val tab: Tab) : Route
    data class PlaylistRoute(val id: Long) : Route
    data object QueueRoute : Route
    data object SettingsRoute : Route
}

@Composable
fun SonusApp() {
    val preset = AppPrefs.themePreset
    val palette = remember(preset) { Palette.resolve(Palette.PRESETS[preset]) }
    SonusTheme(palette) { SonusRoot() }
}

@Composable
private fun SonusRoot() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    // remember: a new lambda every time would make the whole app draw again
    val status: (String) -> Unit = remember {
        { text ->
            scope.launch {
                snackbar.currentSnackbarData?.dismiss()
                snackbar.showSnackbar(text)
            }
        }
    }

    val tabState = rememberSaveable { mutableStateOf(Tab.Home) }
    val tab = tabState.value
    val stack = remember { mutableStateListOf<Route>() }
    var nowPlayingOpen by rememberSaveable { mutableStateOf(false) }
    var sheetSong by remember { mutableStateOf<Song?>(null) }
    var sheetEntry by remember { mutableStateOf<Long?>(null) }

    val openActions: (Song, Long?) -> Unit = remember {
        { song, entry ->
            sheetSong = song
            sheetEntry = entry
        }
    }

    val navigator = remember {
        object : Navigator {
            override fun openPlaylist(id: Long) { nowPlayingOpen = false; stack.add(Route.PlaylistRoute(id)) }
            override fun openQueue() { nowPlayingOpen = false; stack.add(Route.QueueRoute) }
            override fun openSettings() { nowPlayingOpen = false; stack.add(Route.SettingsRoute) }
            override fun openNowPlaying() { nowPlayingOpen = true }
            override fun goTo(tab: Tab) { nowPlayingOpen = false; stack.clear(); tabState.value = tab }
        }
    }
    // Permissions and file picker
    val importLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            scope.launch {
                val count = withContext(Dispatchers.IO) { SongImporter.importUris(context, uris, AppPrefs.copyImported) }
                status(if (count > 0) "$count brani aggiunti" else "Nessun brano nuovo")
            }
        }
    }
    val runScan: () -> Unit = {
        scope.launch {
            status("Cerco la musica del telefono...")
            val count = withContext(Dispatchers.IO) { SongImporter.scanDevice(context) }
            status(if (count > 0) "$count brani aggiunti" else "Nessun brano nuovo")
        }
    }
    val audioPermission = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_AUDIO else Manifest.permission.READ_EXTERNAL_STORAGE
    val scanLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) runScan() else status("Serve il permesso per leggere la musica del telefono")
    }
    val notificationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
    val libraryActions = remember {
        LibraryActions(
            importFiles = { importLauncher.launch(arrayOf("audio/*")) },
            scanDevice = {
                if (ContextCompat.checkSelfPermission(context, audioPermission) == PackageManager.PERMISSION_GRANTED) runScan()
                else scanLauncher.launch(audioPermission)
            },
        )
    }

    LaunchedEffect(PlayerController.errorMessage) {
        PlayerController.errorMessage?.let {
            status(it)
            PlayerController.errorMessage = null
        }
    }

    BackHandler(enabled = nowPlayingOpen) { nowPlayingOpen = false }
    BackHandler(enabled = !nowPlayingOpen && stack.isNotEmpty()) { stack.removeAt(stack.lastIndex) }

    val navInset = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
    val bottomPadding = navInset + if (PlayerController.currentSong != null) 164.dp else 94.dp
    val current: Route = stack.lastOrNull() ?: Route.Root(tab)
    val pop = { stack.removeAt(stack.lastIndex); Unit }

    CompositionLocalProvider(
        LocalNavigator provides navigator,
        LocalStatus provides status,
        LocalOpenSongActions provides openActions,
        LocalBottomPadding provides bottomPadding,
        LocalLibraryActions provides libraryActions,
    ) {
        AuroraBackground {
            Box(modifier = Modifier.fillMaxSize()) {
                Box(modifier = Modifier.fillMaxSize().statusBarsPadding()) {
                    Crossfade(targetState = current, label = "screen") { route ->
                        when (route) {
                            is Route.Root -> when (route.tab) {
                                Tab.Home -> HomeScreen()
                                Tab.Search -> SearchScreen()
                                Tab.Discover -> DiscoverScreen()
                                Tab.Library -> LibraryScreen()
                            }
                            is Route.PlaylistRoute -> PlaylistScreen(route.id, pop)
                            Route.QueueRoute -> QueueScreen(pop)
                            Route.SettingsRoute -> SettingsScreen(pop)
                        }
                    }
                }
                Column(
                    modifier = Modifier.align(Alignment.BottomCenter).padding(horizontal = 12.dp).navigationBarsPadding().padding(bottom = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    MiniPlayer(onOpen = { nowPlayingOpen = true })
                    GlassNavBar(selected = (current as? Route.Root)?.tab ?: tab, onSelect = { navigator.goTo(it) })
                }
                SnackbarHost(snackbar, modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = bottomPadding))
                AnimatedVisibility(
                    visible = nowPlayingOpen,
                    enter = slideInVertically { it } + fadeIn(),
                    exit = slideOutVertically { it } + fadeOut(),
                ) {
                    NowPlayingScreen(onClose = { nowPlayingOpen = false })
                }
                sheetSong?.let { song -> SongActionsSheet(song, sheetEntry) { sheetSong = null; sheetEntry = null } }
                UpdatePrompt()
            }
        }
    }
}
