package app.sonus.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import app.sonus.core.isNewerVersion
import org.json.JSONArray
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

data class UpdateInfo(val version: String, val notes: String, val url: String, val size: Long, val name: String)

/**
 * Same idea as app/app_updater.py: looks in the GitHub releases of the repository for a newer Sonus.
 * The Android releases are "pre-releases" with the tag "android-vX.Y.Z" (so the PC app never sees them as its latest release).
 */
object AppUpdater {
    const val REPO = "DaRealDante/Sonus"
    private const val TAG_PREFIX = "android-v"
    private const val USER_AGENT = "Sonus-Android"

    fun installedVersion(context: Context): String =
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "0"

    /** Newer version found, or null. Call from a background thread. */
    fun check(currentVersion: String): UpdateInfo? {
        val connection = (URL("https://api.github.com/repos/$REPO/releases?per_page=30").openConnection() as HttpURLConnection).apply {
            connectTimeout = 15000
            readTimeout = 15000
            setRequestProperty("User-Agent", USER_AGENT)
            setRequestProperty("Accept", "application/vnd.github+json")
        }
        try {
            if (connection.responseCode == 404) return null
            val releases = JSONArray(connection.inputStream.bufferedReader().use { it.readText() })
            for (index in 0 until releases.length()) {
                val release = releases.getJSONObject(index)
                val tag = release.optString("tag_name")
                if (!tag.startsWith(TAG_PREFIX) || release.optBoolean("draft")) continue
                val version = tag.removePrefix(TAG_PREFIX)
                if (!isNewerVersion(version, currentVersion)) return null
                val assets = release.optJSONArray("assets") ?: return null
                for (assetIndex in 0 until assets.length()) {
                    val asset = assets.getJSONObject(assetIndex)
                    if (asset.optString("name").lowercase().endsWith(".apk")) {
                        return UpdateInfo(
                            version = version,
                            notes = release.optString("body").trim(),
                            url = asset.getString("browser_download_url"),
                            size = asset.optLong("size"),
                            name = asset.getString("name"),
                        )
                    }
                }
                return null
            }
            return null
        } finally {
            connection.disconnect()
        }
    }

    /** Downloads the APK into the cache of the app. Call from a background thread. */
    fun download(context: Context, info: UpdateInfo, onProgress: (Long, Long) -> Unit): File {
        val folder = File(context.cacheDir, "updates").apply { mkdirs() }
        folder.listFiles()?.forEach { it.delete() }
        val target = File(folder, info.name)
        val partial = File(folder, info.name + ".part")
        val connection = (URL(info.url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 20000
            readTimeout = 30000
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", USER_AGENT)
        }
        try {
            val total = connection.contentLengthLong.takeIf { it > 0 } ?: info.size
            connection.inputStream.use { input ->
                partial.outputStream().use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var done = 0L
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                        done += count
                        onProgress(done, total)
                    }
                }
            }
        } finally {
            connection.disconnect()
        }
        if (!partial.renameTo(target)) throw IllegalStateException("Impossibile salvare l'aggiornamento")
        return target
    }

    /** Opens the Android installer for the APK. If the phone does not allow it yet, opens the setting first. */
    fun install(context: Context, apk: File) {
        if (!context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            return
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", apk)
        context.startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}
