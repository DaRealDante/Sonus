package it.sonus.mobile

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.annotation.Keep
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

object SonusHost {
    private val started = AtomicBoolean()
    private val executor = Executors.newSingleThreadExecutor { runnable -> Thread(runnable, "sonus-host") }
    private val main = Handler(Looper.getMainLooper())
    private val mutableState = MutableStateFlow(JSONObject().put("ready", false).put("playing", false))
    val state: StateFlow<JSONObject> = mutableState.asStateFlow()
    private lateinit var application: Context
    @Volatile private var entry: PyObject? = null
    private val callback = Callback()

    fun initialize(context: Context) {
        if (!started.compareAndSet(false, true)) return
        application = context.applicationContext
        executor.execute {
            try {
                YoutubeDL.getInstance().init(application)
                FFmpeg.getInstance().init(application)
                if (!Python.isStarted()) Python.start(AndroidPlatform(application))
                val module = Python.getInstance().getModule("sonus_mobile.entry")
                entry = module
                val dataDir = File(application.filesDir, "sonus").apply { mkdirs() }
                val packages = File(application.noBackupFilesDir, "youtubedl-android/packages").apply { mkdirs() }
                module.callAttr("initialize", dataDir.absolutePath, application.applicationInfo.nativeLibraryDir,
                    packages.absolutePath, callback)
            } catch (error: Exception) {
                reportError("Avvio non riuscito", error)
            }
        }
    }

    fun command(action: String, payload: JSONObject = JSONObject()) {
        check(started.get()) { "Initialize SonusHost before sending commands" }
        if (PlaybackService.needsService(action)) {
            PlaybackService.dispatch(application, action, payload)
        } else {
            if (action == "pause") PlaybackService.cancelAutomaticResume()
            enqueueCommand(action, payload)
        }
    }

    internal fun enqueueCommand(action: String, payload: JSONObject = JSONObject()) {
        // Detach the caller's object before crossing threads.
        val encoded = payload.toString()
        executor.execute {
            try {
                val module = entry ?: error("Il motore musicale non è disponibile")
                module.callAttr("command", action, encoded)
            } catch (error: Exception) {
                reportError("Comando non riuscito: $action", error)
            }
        }
    }

    internal fun reportError(message: String, error: Throwable? = null) {
        Log.e("SonusHost", message, error)
        publish(JSONObject().put("message", "$message${error?.message?.let { ": $it" } ?: ""}")
            .put("messageId", System.nanoTime()))
    }

    private fun publish(update: JSONObject) {
        main.post {
            mutableState.value = HostState.merge(mutableState.value, update)
            if (update.optBoolean("playing", false)) PlaybackService.ensureRunning(application)
        }
    }

    @Keep
    class Callback {
        @Keep fun onEvent(json: String) {
            try { publish(JSONObject(json)) }
            catch (error: Exception) { reportError("Risposta del motore non valida", error) }
        }
    }
}
