package it.sonus.mobile

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.core.content.FileProvider
import java.io.File
import java.util.concurrent.Executors
import org.json.JSONArray
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    private val io = Executors.newSingleThreadExecutor()
    private var pending = JSONObject()
    private val files = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris -> importUris(uris) }
    private val folder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        val request = JSONObject(pending.toString())
        if (uri != null) io.execute {
            runCatching {
                val audio = setOf("mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma", "webm")
                val found = mutableListOf<Uri>()
                val queue = ArrayDeque<String>()
                queue.add(DocumentsContract.getTreeDocumentId(uri))
                while (queue.isNotEmpty()) {
                    val children = DocumentsContract.buildChildDocumentsUriUsingTree(uri, queue.removeFirst())
                    contentResolver.query(children, arrayOf("document_id", "mime_type", "_display_name"), null, null, null)?.use { cursor ->
                        while (cursor.moveToNext()) {
                            val id = cursor.getString(0)
                            if (cursor.getString(1) == DocumentsContract.Document.MIME_TYPE_DIR) queue.add(id)
                            else if (cursor.getString(2).substringAfterLast('.', "").lowercase() in audio)
                                found.add(DocumentsContract.buildDocumentUriUsingTree(uri, id))
                        }
                    }
                }
                importUris(found, request)
            }.onFailure { localError(it) }
        }
    }
    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SonusHost.initialize(applicationContext)
        if (android.os.Build.VERSION.SDK_INT >= 33) permission.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        handleIntent(intent)
        setContent {
            val state by SonusHost.state.collectAsState()
            SonusTheme(state.obj("settings")) {
                SonusApp(state, { action, payload -> SonusHost.command(action, payload) }, ::pick, ::share, ::open)
            }
        }
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); handleIntent(intent) }
    override fun onStart() { super.onStart(); SonusHost.command("foreground", json("active" to true)) }
    override fun onStop() { SonusHost.command("foreground", json("active" to false)); super.onStop() }
    private fun handleIntent(intent: Intent?) {
        intent?.data?.toString()?.takeIf { it.startsWith("sonus://", true) }?.let {
            SonusHost.command("handle_code", json("code" to it))
        }
        if (intent?.action == Intent.ACTION_SEND) {
            intent.getStringExtra(Intent.EXTRA_TEXT)?.takeIf { it.contains("sonus://") }?.let {
                SonusHost.command("handle_code", json("code" to it))
            }
        }
    }

    private fun pick(request: JSONObject) {
        pending = request
        when (request.str("kind")) {
            "folder" -> folder.launch(null)
            "audio" -> files.launch(arrayOf("audio/*", "application/ogg"))
            "video" -> files.launch(arrayOf("video/*"))
            "apk" -> files.launch(arrayOf("application/vnd.android.package-archive"))
            else -> files.launch(arrayOf("image/*"))
        }
    }

    private fun importUris(uris: List<Uri>, request: JSONObject = JSONObject(pending.toString())) {
        if (uris.isEmpty()) return
        io.execute {
            runCatching {
                val paths = uris.map { uri ->
                    val name = contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
                        if (it.moveToFirst()) it.getString(0) else null
                    } ?: "import_${System.currentTimeMillis()}"
                    val dir = File(filesDir, "imports").apply { mkdirs() }
                    val safe = name.replace(Regex("[^\\p{L}\\p{N} ._()-]"), "_").take(180)
                    var dest = File(dir, safe)
                    var suffix = 1
                    while (dest.exists()) { dest = File(dir, "${suffix++}_$safe") }
                    try {
                        contentResolver.openInputStream(uri)?.use { input -> dest.outputStream().use { input.copyTo(it, 64 * 1024) } }
                            ?: error("File non leggibile")
                    } catch (error: Exception) { dest.delete(); throw error }
                    dest.absolutePath
                }
                when (request.str("kind")) {
                    "audio", "folder" -> SonusHost.command("import_files", json("paths" to JSONArray(paths), "playlistId" to request.opt("playlistId")))
                    "video" -> SonusHost.command("video_set", json("id" to request.int("id"), "path" to paths.first()))
                    "profile" -> SonusHost.command("profile", json("photo" to paths.first()))
                    "song_cover" -> SonusHost.command("song_edit", json("id" to request.int("id"), "fields" to json("cover" to paths.first())))
                    "playlist_cover" -> SonusHost.command("playlist_edit", json("id" to request.int("id"), "name" to request.str("name"), "description" to request.str("description"), "cover" to paths.first()))
                    "apk" -> runOnUiThread { open(paths.first()) }
                }
            }.onFailure { localError(it) }
        }
    }

    private fun localError(error: Throwable) { runOnUiThread { android.widget.Toast.makeText(this, error.message ?: "Operazione non riuscita", android.widget.Toast.LENGTH_LONG).show() } }

    private fun share(value: String) {
        runCatching {
            val file = File(value)
            val send = Intent(Intent.ACTION_SEND).apply {
                if (file.isFile) {
                    type = when (file.extension.lowercase()) { "mp4", "webm" -> "video/*"; "png", "jpg", "jpeg" -> "image/*"; else -> "audio/*" }
                    putExtra(Intent.EXTRA_STREAM, FileProvider.getUriForFile(this@MainActivity, "$packageName.files", file))
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                } else { type = "text/plain"; putExtra(Intent.EXTRA_TEXT, value) }
            }
            startActivity(Intent.createChooser(send, "Condividi con"))
        }.onFailure(::localError)
    }

    private fun open(value: String) {
        runCatching {
            val file = File(value)
            if (file.extension == "apk" && !packageManager.canRequestPackageInstalls()) {
                startActivity(Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
                return
            }
            val view = Intent(Intent.ACTION_VIEW).apply {
                if (file.isFile) {
                    val uri = FileProvider.getUriForFile(this@MainActivity, "$packageName.files", file)
                    setDataAndType(uri, if (file.extension == "apk") "application/vnd.android.package-archive" else "audio/*")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                } else data = Uri.parse(value)
            }
            startActivity(view)
        }.onFailure(::localError)
    }
}
