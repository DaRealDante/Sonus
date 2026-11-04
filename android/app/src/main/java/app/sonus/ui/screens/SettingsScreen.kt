package app.sonus.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.core.Palette
import app.sonus.core.Rgb
import app.sonus.data.AppPrefs
import app.sonus.ui.LocalBottomPadding
import app.sonus.ui.LocalLibraryActions
import app.sonus.ui.LocalStatus
import app.sonus.ui.components.GlassButton
import app.sonus.ui.components.GlassIconButton
import app.sonus.ui.components.GlassSurface
import app.sonus.ui.theme.LocalSonusColors
import app.sonus.update.AppUpdater
import app.sonus.update.UpdateManager
import kotlinx.coroutines.launch

@Composable
private fun SettingsCard(title: String, content: @Composable () -> Unit) {
    val colors = LocalSonusColors.current
    GlassSurface(modifier = Modifier.padding(horizontal = 20.dp).fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(title, color = colors.text, fontSize = 17.sp, fontWeight = FontWeight.Bold)
            content()
        }
    }
}

@Composable
private fun SwitchRow(text: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    val colors = LocalSonusColors.current
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(text, color = colors.text, fontSize = 15.sp, modifier = Modifier.weight(1f).padding(end = 12.dp))
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(checkedThumbColor = colors.accentText, checkedTrackColor = colors.accent),
        )
    }
}

@Composable
fun SettingsScreen(onBack: () -> Unit) {
    val colors = LocalSonusColors.current
    val bottom = LocalBottomPadding.current
    val actions = LocalLibraryActions.current
    val status = LocalStatus.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var copyImported by remember { mutableStateOf(AppPrefs.copyImported) }
    var autoUpdates by remember { mutableStateOf(AppPrefs.autoCheckUpdates) }

    LazyColumn(modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = bottom), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                GlassIconButton(Icons.AutoMirrored.Rounded.ArrowBack, "Indietro", onBack)
                Text("Impostazioni", color = colors.text, fontSize = 26.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.padding(start = 14.dp))
            }
        }
        item {
            SettingsCard("Aspetto") {
                Row(modifier = Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Palette.PRESETS.forEach { (name, custom) ->
                        val accent = Rgb.parse(Palette.resolve(custom).accent)!!.argb()
                        val selected = AppPrefs.themePreset == name
                        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.clickable { AppPrefs.setThemePreset(name) }) {
                            Box(
                                modifier = Modifier.size(46.dp).clip(CircleShape).background(Color(accent))
                                    .border(BorderStroke(if (selected) 3.dp else 1.dp, if (selected) Color.White else Color.White.copy(alpha = 0.25f)), CircleShape),
                                contentAlignment = Alignment.Center,
                            ) {
                                if (selected) Icon(Icons.Rounded.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(24.dp))
                            }
                            Text(name.substringBefore(" ("), color = if (selected) colors.text else colors.subtext, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
                        }
                    }
                }
            }
        }
        item {
            SettingsCard("Libreria") {
                GlassButton("Aggiungi la musica del telefono", { actions.scanDevice() }, modifier = Modifier.fillMaxWidth())
                GlassButton("Importa file", { actions.importFiles() }, modifier = Modifier.fillMaxWidth())
                SwitchRow("Copia i file importati dentro Sonus", copyImported) { copyImported = it; AppPrefs.copyImported = it }
            }
        }
        item {
            SettingsCard("Aggiornamenti") {
                SwitchRow("Controlla gli aggiornamenti all'avvio", autoUpdates) { autoUpdates = it; AppPrefs.autoCheckUpdates = it }
                GlassButton(
                    "Controlla ora",
                    {
                        scope.launch {
                            status("Controllo gli aggiornamenti...")
                            if (!UpdateManager.check(context, manual = true)) status("Hai già l'ultima versione")
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
        item {
            SettingsCard("Informazioni") {
                Text("Sonus per Android ${AppUpdater.installedVersion(context)}", color = colors.subtext, fontSize = 14.sp)
                Text("github.com/${AppUpdater.REPO}", color = colors.muted, fontSize = 13.sp)
            }
        }
    }
}
