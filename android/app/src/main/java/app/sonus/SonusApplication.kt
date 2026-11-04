package app.sonus

import android.app.Application
import app.sonus.data.AppPrefs
import app.sonus.data.Library
import app.sonus.playback.PlayerController

class SonusApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        AppPrefs.init(this)
        Library.init(this)
        PlayerController.init(this)
    }
}
