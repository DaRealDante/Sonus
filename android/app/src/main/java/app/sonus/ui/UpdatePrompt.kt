package app.sonus.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.sonus.data.AppPrefs
import app.sonus.ui.theme.LocalSonusColors
import app.sonus.update.UpdateManager
import kotlinx.coroutines.launch

/** At start the app looks for a newer version (like the PC app): Aggiorna / Dopo / Salta questa versione. */
@Composable
fun UpdatePrompt() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val colors = LocalSonusColors.current

    LaunchedEffect(Unit) {
        if (AppPrefs.autoCheckUpdates) UpdateManager.check(context, manual = false)
    }

    val info = UpdateManager.available ?: return
    val progress = UpdateManager.progress
    AlertDialog(
        onDismissRequest = { if (progress == null) UpdateManager.later() },
        containerColor = colors.elevated,
        titleContentColor = colors.text,
        textContentColor = colors.subtext,
        title = { Text("Nuova versione ${info.version}") },
        text = {
            Column {
                Text(info.notes.ifBlank { "È disponibile una nuova versione di Sonus." })
                if (progress != null) LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth().padding(top = 12.dp), color = colors.accent)
                UpdateManager.error?.let { Text(it, modifier = Modifier.padding(top = 12.dp)) }
            }
        },
        confirmButton = {
            TextButton(enabled = progress == null, onClick = { scope.launch { UpdateManager.downloadAndInstall(context) } }) {
                Text("Aggiorna", color = colors.accent)
            }
        },
        dismissButton = {
            Row {
                TextButton(enabled = progress == null, onClick = { UpdateManager.skip() }) { Text("Salta", color = colors.subtext) }
                TextButton(enabled = progress == null, onClick = { UpdateManager.later() }) { Text("Dopo", color = colors.subtext) }
            }
        },
    )
}
