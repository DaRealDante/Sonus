package it.sonus.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.support.v4.media.MediaMetadataCompat
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.media.app.NotificationCompat.MediaStyle
import androidx.media.session.MediaButtonReceiver
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Owns Android playback lifecycle; Python owns the player, queue, and persistence. */
class PlaybackService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val handler = Handler(Looper.getMainLooper())
    private val focusPolicy = FocusPolicy()
    private lateinit var audioManager: AudioManager
    private lateinit var focusRequest: AudioFocusRequest
    private lateinit var session: MediaSessionCompat
    private lateinit var wakeLock: PowerManager.WakeLock
    private lateinit var wifiLock: WifiManager.WifiLock
    private var hasFocus = false
    private var focusRequested = false
    private var focusInterrupted = false
    private var foreground = false
    private var lastState = JSONObject()
    private var lastNotificationKey = ""
    private var lastPositionUpdate = 0L
    private var lastWakeRenewal = 0L
    private val noisyReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == AudioManager.ACTION_AUDIO_BECOMING_NOISY) userPause()
        }
    }

    override fun onCreate() {
        super.onCreate()
        active = this
        SonusHost.initialize(this)
        audioManager = getSystemService(AudioManager::class.java)
        focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
            .setAcceptsDelayedFocusGain(false)
            .setOnAudioFocusChangeListener({ focus -> onFocus(focus) }, handler)
            .build()
        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "sonus:playback").apply { setReferenceCounted(false) }
        @Suppress("DEPRECATION")
        wifiLock = (applicationContext.getSystemService(WIFI_SERVICE) as WifiManager)
            .createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "sonus:stream").apply { setReferenceCounted(false) }
        session = MediaSessionCompat(this, "Sonus").apply {
            setSessionActivity(openApp())
            setCallback(object : MediaSessionCompat.Callback() {
                override fun onPlay() {
                    if (!lastState.optBoolean("playing")) playCommand("play_pause", JSONObject().put("playing", true))
                }
                override fun onPause() { userPause() }
                override fun onStop() { stopPlayback() }
                override fun onSkipToNext() { playCommand("next") }
                override fun onSkipToPrevious() { playCommand("previous") }
                override fun onSeekTo(position: Long) {
                    SonusHost.enqueueCommand("seek", JSONObject().put("position", position.coerceAtLeast(0)))
                }
                override fun onSetRepeatMode(repeatMode: Int) {
                    val repeat = when (repeatMode) {
                        PlaybackStateCompat.REPEAT_MODE_ONE -> "one"
                        PlaybackStateCompat.REPEAT_MODE_ALL -> "all"
                        else -> "off"
                    }
                    SonusHost.enqueueCommand("repeat", JSONObject().put("value", repeat))
                }
                override fun onSetShuffleMode(shuffleMode: Int) {
                    SonusHost.enqueueCommand("shuffle", JSONObject().put("value", shuffleMode == PlaybackStateCompat.SHUFFLE_MODE_ALL))
                }
            })
            isActive = true
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.playback_channel), NotificationManager.IMPORTANCE_LOW).apply {
                description = getString(R.string.playback_channel_description)
                setShowBadge(false)
            })
        ContextCompat.registerReceiver(this, noisyReceiver, IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY),
            ContextCompat.RECEIVER_NOT_EXPORTED)
        promote(notification(JSONObject()))
        scope.launch { SonusHost.state.collect { update(it) } }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // A receiver may launch a previously paused service from the lock screen.
        promote(notification(SonusHost.state.value))
        when (intent?.action) {
            Intent.ACTION_MEDIA_BUTTON -> MediaButtonReceiver.handleIntent(session, intent)
            ACTION_COMMAND -> {
                val action = intent.getStringExtra(EXTRA_ACTION).orEmpty()
                val payload = runCatching { JSONObject(intent.getStringExtra(EXTRA_PAYLOAD) ?: "{}") }.getOrDefault(JSONObject())
                if (action == "pause") userPause()
                else if (action == "stop") stopPlayback()
                else playCommand(action, payload)
            }
            else -> if (SonusHost.state.value.optBoolean("playing")) {
                if (!requestFocus()) SonusHost.enqueueCommand("pause")
            }
        }
        handler.postDelayed({
            if (!lastState.optBoolean("playing") && !lastState.optBoolean("loading") && !focusInterrupted) demote()
        }, 15_000)
        return START_NOT_STICKY // Persisted state restores on next explicit user launch, without surprise autoplay.
    }

    private fun playCommand(action: String, payload: JSONObject = JSONObject()) {
        if (action.isBlank()) return
        if ((action == "toggle" || action == "play_pause") && !payload.has("playing") && lastState.optBoolean("playing")) {
            userPause()
            return
        }
        promote(notification(SonusHost.state.value))
        if (requestFocus()) SonusHost.enqueueCommand(action, payload)
        else {
            SonusHost.reportError("Audio occupato da un’altra applicazione")
            demote()
        }
    }

    private fun userPause() {
        focusPolicy.cancelResume()
        focusInterrupted = false
        SonusHost.enqueueCommand("pause")
        abandonFocus()
    }

    private fun stopPlayback() {
        userPause()
        demote()
        getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_ID)
        stopSelf()
    }

    private fun requestFocus(): Boolean {
        if (hasFocus) return true
        hasFocus = audioManager.requestAudioFocus(focusRequest) == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
        focusRequested = focusRequested || hasFocus
        return hasFocus
    }

    private fun abandonFocus() {
        if (focusRequested) audioManager.abandonAudioFocusRequest(focusRequest)
        hasFocus = false
        focusRequested = false
        PcmSink.setDucking(1f)
    }

    private fun onFocus(focus: Int) {
        val decision = focusPolicy.change(focus, lastState.optBoolean("playing"))
        PcmSink.setDucking(decision.gain)
        when (focus) {
            AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> { hasFocus = false; focusInterrupted = true }
            AudioManager.AUDIOFOCUS_LOSS -> { hasFocus = false; focusRequested = false; focusInterrupted = false }
            AudioManager.AUDIOFOCUS_GAIN -> { hasFocus = true; focusRequested = true; focusInterrupted = false }
        }
        if (decision.pause) SonusHost.enqueueCommand("pause")
        if (decision.resume) {
            promote(notification(lastState))
            SonusHost.enqueueCommand("play_pause", JSONObject().put("playing", true))
        }
    }

    private fun update(state: JSONObject) {
        lastState = state
        val playing = state.optBoolean("playing")
        val loading = state.optBoolean("loading")
        val now = SystemClock.elapsedRealtime()
        if (playing) {
            if (!hasFocus && !focusInterrupted && !requestFocus()) {
                SonusHost.enqueueCommand("pause")
                return
            }
            if (!wakeLock.isHeld || now - lastWakeRenewal > 8 * 60_000) {
                wakeLock.acquire(10 * 60_000L)
                lastWakeRenewal = now
            }
            if (!wifiLock.isHeld) wifiLock.acquire()
        } else {
            releaseLocks()
            if (!focusInterrupted) abandonFocus()
        }
        val song = state.optJSONObject("current")
        val key = "${song?.opt("id")}:${song?.optString("title")}:${song?.optString("artist")}:${state.optLong("duration")}:$playing:$loading:$focusInterrupted"
        if (lastNotificationKey != key) {
            session.setMetadata(MediaMetadataCompat.Builder()
                .putString(MediaMetadataCompat.METADATA_KEY_MEDIA_ID, song?.opt("id")?.toString().orEmpty())
                .putString(MediaMetadataCompat.METADATA_KEY_TITLE, song?.optString("title").orEmpty())
                .putString(MediaMetadataCompat.METADATA_KEY_ARTIST, song?.optString("artist").orEmpty())
                .putString(MediaMetadataCompat.METADATA_KEY_ALBUM, song?.optString("album").orEmpty())
                .putLong(MediaMetadataCompat.METADATA_KEY_DURATION, state.optLong("duration"))
                .build())
            val notification = notification(state)
            if (playing || loading || focusInterrupted) promote(notification) else {
                demote()
                if (song != null) getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification)
            }
            lastNotificationKey = key
        }
        if (now - lastPositionUpdate >= 1000 || !playing) {
            session.setPlaybackState(PlaybackStateCompat.Builder()
                .setActions(PlaybackStateCompat.ACTION_PLAY or PlaybackStateCompat.ACTION_PAUSE or
                    PlaybackStateCompat.ACTION_PLAY_PAUSE or PlaybackStateCompat.ACTION_SKIP_TO_NEXT or
                    PlaybackStateCompat.ACTION_SKIP_TO_PREVIOUS or PlaybackStateCompat.ACTION_SEEK_TO or
                    PlaybackStateCompat.ACTION_STOP or PlaybackStateCompat.ACTION_SET_REPEAT_MODE or
                    PlaybackStateCompat.ACTION_SET_SHUFFLE_MODE)
                .setState(when { loading -> PlaybackStateCompat.STATE_BUFFERING
                    playing -> PlaybackStateCompat.STATE_PLAYING
                    song != null -> PlaybackStateCompat.STATE_PAUSED
                    else -> PlaybackStateCompat.STATE_STOPPED },
                    state.optLong("position"), if (playing) state.optJSONObject("effects")?.optDouble("rate", 1.0)?.toFloat() ?: 1f else 0f)
                .build())
            lastPositionUpdate = now
        }
    }

    private fun notification(state: JSONObject): Notification {
        val song = state.optJSONObject("current")
        val playing = state.optBoolean("playing")
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_music_note)
            .setContentTitle(song?.optString("title")?.ifBlank { "Sonus" } ?: "Sonus")
            .setContentText(song?.optString("artist")?.ifBlank { "Sonus" } ?: getString(R.string.starting_playback))
            .setContentIntent(openApp())
            .setDeleteIntent(commandIntent("stop"))
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setCategory(NotificationCompat.CATEGORY_TRANSPORT)
            .setOnlyAlertOnce(true)
            .setOngoing(playing)
            .addAction(android.R.drawable.ic_media_previous, getString(R.string.previous), commandIntent("previous"))
            .addAction(if (playing) android.R.drawable.ic_media_pause else android.R.drawable.ic_media_play,
                getString(if (playing) R.string.pause else R.string.play), commandIntent(if (playing) "pause" else "play_pause"))
            .addAction(android.R.drawable.ic_media_next, getString(R.string.next), commandIntent("next"))
            .setStyle(MediaStyle().setMediaSession(session.sessionToken).setShowActionsInCompactView(0, 1, 2))
            .build()
    }

    private fun openApp(): PendingIntent = PendingIntent.getActivity(this, 0,
        Intent(this, MainActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    private fun commandIntent(action: String): PendingIntent = PendingIntent.getForegroundService(this, action.hashCode(),
        Intent(this, PlaybackService::class.java).setAction(ACTION_COMMAND).putExtra(EXTRA_ACTION, action)
            .putExtra(EXTRA_PAYLOAD, if (action == "play_pause") "{\"playing\":true}" else "{}"),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    private fun promote(notification: Notification) {
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notification,
            if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK else 0)
        foreground = true
    }

    private fun demote() {
        if (foreground) stopForeground(STOP_FOREGROUND_DETACH)
        foreground = false
    }

    private fun releaseLocks() {
        if (wakeLock.isHeld) wakeLock.release()
        if (wifiLock.isHeld) wifiLock.release()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        active = null
        handler.removeCallbacksAndMessages(null)
        scope.cancel()
        unregisterReceiver(noisyReceiver)
        if (lastState.optBoolean("playing")) SonusHost.enqueueCommand("pause")
        releaseLocks()
        abandonFocus()
        session.isActive = false
        session.release()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "sonus_playback"
        private const val NOTIFICATION_ID = 1001
        private const val ACTION_COMMAND = "it.sonus.mobile.PLAYBACK_COMMAND"
        private const val EXTRA_ACTION = "command"
        private const val EXTRA_PAYLOAD = "payload"
        @Volatile private var active: PlaybackService? = null
        private val serviceCommands = setOf("play", "play_entry", "search_play", "toggle", "play_pause", "next", "previous", "queue_jump")

        internal fun needsService(action: String): Boolean = action in serviceCommands

        internal fun dispatch(context: Context, action: String, payload: JSONObject) {
            try {
                ContextCompat.startForegroundService(context, Intent(context, PlaybackService::class.java)
                    .setAction(ACTION_COMMAND).putExtra(EXTRA_ACTION, action).putExtra(EXTRA_PAYLOAD, payload.toString()))
            } catch (error: RuntimeException) {
                SonusHost.reportError("Impossibile avviare l’audio in background", error)
            }
        }

        internal fun ensureRunning(context: Context) {
            if (active != null) return
            try { ContextCompat.startForegroundService(context, Intent(context, PlaybackService::class.java)) }
            catch (error: RuntimeException) {
                SonusHost.enqueueCommand("pause")
                SonusHost.reportError("Apri Sonus per riprendere l’ascolto", error)
            }
        }

        internal fun cancelAutomaticResume() {
            active?.let { service -> service.handler.post {
                service.focusPolicy.cancelResume()
                service.focusInterrupted = false
                if (!service.lastState.optBoolean("playing")) service.abandonFocus()
            } }
        }
    }
}
