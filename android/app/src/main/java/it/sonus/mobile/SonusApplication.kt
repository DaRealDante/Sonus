package it.sonus.mobile

import android.app.Application

class SonusApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        SonusHost.initialize(this)
    }
}
