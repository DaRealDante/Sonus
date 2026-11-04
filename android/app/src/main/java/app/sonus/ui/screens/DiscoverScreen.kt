package app.sonus.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Explore
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.sonus.ui.LocalBottomPadding
import app.sonus.ui.components.EmptyState
import app.sonus.ui.components.GlassSurface
import app.sonus.ui.components.ScreenTitle

@Composable
fun DiscoverScreen() {
    val bottom = LocalBottomPadding.current
    Column(modifier = Modifier.fillMaxSize().padding(bottom = bottom), verticalArrangement = Arrangement.Top) {
        ScreenTitle("Scopri")
        GlassSurface(modifier = Modifier.padding(horizontal = 20.dp), strong = true) {
            EmptyState(
                Icons.Rounded.Explore,
                "Nuova musica in arrivo",
                "Qui troverai consigli e musica da scoprire. Arriva con la fase di YouTube.",
            )
        }
    }
}
