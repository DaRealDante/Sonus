package app.sonus.ui

import android.content.Context
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.sonus.update.AppUpdater
import app.sonus.update.UpdateInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** At start the app looks for a newer version (like the PC app): Aggiorna / Dopo / Salta questa versione. */
@Composable
fun UpdatePrompt() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var info by remember { mutableStateOf<UpdateInfo?>(null) }
    var progress by remember { mutableStateOf<Float?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        val preferences = context.getSharedPreferences("sonus", Context.MODE_PRIVATE)
        if (!preferences.getBoolean("autoCheckUpdates", true)) return@LaunchedEffect
        val found = withContext(Dispatchers.IO) {
            runCatching { AppUpdater.check(AppUpdater.installedVersion(context)) }.getOrNull()
        }
        if (found != null && found.version != preferences.getString("skippedVersion", "")) info = found
    }

    val current = info ?: return
    AlertDialog(
        onDismissRequest = { if (progress == null) info = null },
        title = { Text("Nuova versione ${current.version}") },
        text = {
            Column {
                Text(current.notes.ifBlank { "È disponibile una nuova versione di Sonus." })
                progress?.let { LinearProgressIndicator(progress = { it }, modifier = Modifier.padding(top = 12.dp)) }
                error?.let { Text(it, modifier = Modifier.padding(top = 12.dp)) }
            }
        },
        confirmButton = {
            TextButton(
                enabled = progress == null,
                onClick = {
                    error = null
                    progress = 0f
                    scope.launch {
                        try {
                            val file = withContext(Dispatchers.IO) {
                                AppUpdater.download(context, current) { done, total ->
                                    if (total > 0) progress = done.toFloat() / total
                                }
                            }
                            AppUpdater.install(context, file)
                        } catch (exception: Exception) {
                            error = "Aggiornamento non riuscito: ${exception.message ?: "errore di rete"}"
                        } finally {
                            progress = null
                        }
                    }
                },
            ) { Text("Aggiorna") }
        },
        dismissButton = {
            Row {
                TextButton(
                    enabled = progress == null,
                    onClick = {
                        context.getSharedPreferences("sonus", Context.MODE_PRIVATE).edit().putString("skippedVersion", current.version).apply()
                        info = null
                    },
                ) { Text("Salta") }
                TextButton(enabled = progress == null, onClick = { info = null }) { Text("Dopo") }
            }
        },
    )
}
