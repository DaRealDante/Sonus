package app.sonus.data

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/** Settings of the app (like settings.json on the PC). Only what changes the look is a Compose state. */
object AppPrefs {
    private lateinit var preferences: SharedPreferences

    var themePreset by mutableStateOf("Verde (originale)")
        private set

    fun init(context: Context) {
        preferences = context.applicationContext.getSharedPreferences("sonus", Context.MODE_PRIVATE)
        themePreset = preferences.getString("themePreset", "Verde (originale)") ?: "Verde (originale)"
    }

    fun setThemePreset(name: String) {
        themePreset = name
        preferences.edit().putString("themePreset", name).apply()
    }

    var autoCheckUpdates: Boolean
        get() = preferences.getBoolean("autoCheckUpdates", true)
        set(value) = preferences.edit().putBoolean("autoCheckUpdates", value).apply()

    var skippedVersion: String
        get() = preferences.getString("skippedVersion", "") ?: ""
        set(value) = preferences.edit().putString("skippedVersion", value).apply()

    var copyImported: Boolean
        get() = preferences.getBoolean("copyImported", false)
        set(value) = preferences.edit().putBoolean("copyImported", value).apply()

    // The last queue (like lastQueue / lastSongId / lastPosition on the PC): it comes back when the app opens
    var lastQueue: List<Long>
        get() = (preferences.getString("lastQueue", "") ?: "").split(",").mapNotNull { it.toLongOrNull() }
        set(value) = preferences.edit().putString("lastQueue", value.joinToString(",")).apply()

    var lastIndex: Int
        get() = preferences.getInt("lastIndex", 0)
        set(value) = preferences.edit().putInt("lastIndex", value).apply()

    var lastPosition: Long
        get() = preferences.getLong("lastPosition", 0L)
        set(value) = preferences.edit().putLong("lastPosition", value).apply()

    var repeatMode: Int
        get() = preferences.getInt("repeatMode", 0)
        set(value) = preferences.edit().putInt("repeatMode", value).apply()

    var shuffle: Boolean
        get() = preferences.getBoolean("shuffle", false)
        set(value) = preferences.edit().putBoolean("shuffle", value).apply()
}
