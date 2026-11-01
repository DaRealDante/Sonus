package app.sonus.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.sonus.ui.theme.LocalSonusColors
import app.sonus.ui.theme.SonusTheme

/** The main places of the app (on PC they are the sidebar: Home, Cerca, Scopri, Libreria...). */
enum class Tab(val label: String, val icon: ImageVector, val description: String) {
    Home("Home", Icons.Filled.Home, "Brani recenti, più ascoltati e playlist"),
    Search("Cerca", Icons.Filled.Search, "Cerca nella libreria e su YouTube"),
    Discover("Scopri", Icons.Filled.Explore, "Nuova musica da scoprire"),
    Library("Libreria", Icons.Filled.LibraryMusic, "Brani, preferiti, recenti, playlist e download"),
}

@Composable
fun SonusApp() {
    SonusTheme {
        SonusScaffold()
        UpdatePrompt()
    }
}

@Composable
private fun SonusScaffold() {
    var tab by rememberSaveable { mutableStateOf(Tab.Home) }
    val colors = LocalSonusColors.current
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            Column {
                MiniPlayer()
                NavigationBar(containerColor = colors.sidebar) {
                    Tab.entries.forEach { item ->
                        NavigationBarItem(
                            selected = tab == item,
                            onClick = { tab = item },
                            icon = { Icon(item.icon, contentDescription = item.label) },
                            label = { Text(item.label) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = colors.accent,
                                selectedTextColor = colors.accent,
                                indicatorColor = colors.accentDim,
                                unselectedIconColor = colors.subtext,
                                unselectedTextColor = colors.subtext,
                            ),
                        )
                    }
                }
            }
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            PlaceholderScreen(tab.label, tab.description)
        }
    }
}

@Composable
private fun PlaceholderScreen(title: String, description: String) {
    val colors = LocalSonusColors.current
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(title, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold, color = colors.text)
        Text(description, style = MaterialTheme.typography.bodyMedium, color = colors.subtext, modifier = Modifier.padding(top = 8.dp))
        Text("Fase 0: scheletro dell'app", style = MaterialTheme.typography.bodySmall, color = colors.muted, modifier = Modifier.padding(top = 16.dp))
    }
}

/** The bar above the navigation: the song that plays now (empty for now). Tap = full "In riproduzione" screen later. */
@Composable
private fun MiniPlayer() {
    val colors = LocalSonusColors.current
    Row(
        modifier = Modifier.fillMaxWidth().height(64.dp).background(colors.elevated).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier.size(44.dp).clip(RoundedCornerShape(8.dp)).background(colors.accentGlow),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Filled.MusicNote, contentDescription = null, tint = colors.accent)
        }
        Column(modifier = Modifier.weight(1f).padding(horizontal = 12.dp)) {
            Text("Nessuna canzone", color = colors.text, fontWeight = FontWeight.SemiBold, maxLines = 1)
            Text("Sonus", color = colors.subtext, style = MaterialTheme.typography.bodySmall, maxLines = 1)
        }
        IconButton(onClick = {}, enabled = false) {
            Icon(Icons.Filled.PlayArrow, contentDescription = "Riproduci", tint = colors.muted)
        }
    }
}
