package app.sonus.update

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.sonus.data.AppPrefs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** The state of the update of the app, shared by the start check and the "Controlla ora" button in the settings. */
object UpdateManager {
    var available by mutableStateOf<UpdateInfo?>(null)
    var progress by mutableStateOf<Float?>(null)
    var error by mutableStateOf<String?>(null)

    /** True when a newer version was found (it is then in [available]). A version the user skipped is ignored unless [manual]. */
    suspend fun check(context: Context, manual: Boolean): Boolean {
        val found = withContext(Dispatchers.IO) {
            runCatching { AppUpdater.check(AppUpdater.installedVersion(context)) }.getOrNull()
        }
        if (found != null && (manual || found.version != AppPrefs.skippedVersion)) {
            available = found
            error = null
            return true
        }
        return false
    }

    suspend fun downloadAndInstall(context: Context) {
        val info = available ?: return
        error = null
        progress = 0f
        try {
            val file = withContext(Dispatchers.IO) {
                AppUpdater.download(context, info) { done, total -> if (total > 0) progress = done.toFloat() / total }
            }
            AppUpdater.install(context, file)
        } catch (exception: Exception) {
            error = "Aggiornamento non riuscito: ${exception.message ?: "errore di rete"}"
        } finally {
            progress = null
        }
    }

    fun skip() {
        available?.let { AppPrefs.skippedVersion = it.version }
        available = null
    }

    fun later() {
        available = null
    }
}
