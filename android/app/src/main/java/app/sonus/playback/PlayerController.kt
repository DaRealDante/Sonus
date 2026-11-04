package app.sonus.playback

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.ListenableFuture
import app.sonus.core.PlayQueue
import app.sonus.core.REPEAT_ALL
import app.sonus.core.REPEAT_ONE
import app.sonus.data.AppPrefs
import app.sonus.data.Library
import app.sonus.data.Song

/**
 * The player of the app (port of app/player.py). The queue logic is in [PlayQueue]; this class keeps the sound player
 * (ExoPlayer) in step with it and gives the screens their state.
 */
object PlayerController {
    /** One entry of the queue: a distinct object, so the same song can be in the queue twice. */
    private class Entry(val song: Song)

    private lateinit var appContext: Context
    private lateinit var player: ExoPlayer
    private val model = PlayQueue<Entry>()

    var queue by mutableStateOf<List<Song>>(emptyList())
        private set
    var currentIndex by mutableIntStateOf(-1)
        private set
    var isPlaying by mutableStateOf(false)
        private set
    var isBuffering by mutableStateOf(false)
        private set
    var shuffle by mutableStateOf(false)
        private set
    var repeatMode by mutableIntStateOf(0)
        private set
    var durationMs by mutableLongStateOf(0L)
        private set
    var errorMessage by mutableStateOf<String?>(null)

    val currentSong: Song? get() = queue.getOrNull(currentIndex)

    private var controllerFuture: ListenableFuture<MediaController>? = null
    private var pendingCount = false
    private var errorsInRow = 0

    fun init(context: Context) {
        appContext = context.applicationContext
        player = PlayerHolder.get(appContext)
        player.addListener(listener)
        // Connecting a controller starts the background service (notification, lock screen)
        val token = SessionToken(appContext, ComponentName(appContext, PlaybackService::class.java))
        controllerFuture = MediaController.Builder(appContext, token).buildAsync()
        model.setRepeat(AppPrefs.repeatMode)
        model.setShuffle(AppPrefs.shuffle)
        applyModes()
        restoreSession()
    }

    // ---------- state ----------
    private fun mediaItem(entry: Entry): MediaItem {
        val song = entry.song
        return MediaItem.Builder()
            .setMediaId(song.id.toString())
            .setUri(song.playUri())
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(song.title)
                    .setArtist(song.displayArtist)
                    .setAlbumTitle(song.album.ifBlank { null })
                    .setArtworkUri(Uri.parse("sonus-cover://${song.id}"))
                    .build(),
            )
            .build()
    }

    private fun items(entries: List<Entry>) = entries.map { mediaItem(it) }

    private fun publish() {
        queue = model.queue.map { it.song }
        currentIndex = model.currentIndex
        shuffle = model.shuffle
        repeatMode = model.repeatMode
        val total = player.duration
        durationMs = if (total != C.TIME_UNSET && total > 0) total else currentSong?.durationMs ?: 0L
        saveSession()
    }

    /** With shuffle on, "repeat all" is done by hand (the queue is mixed again at the end), the player only repeats one song. */
    private fun applyModes() {
        player.repeatMode = when (model.repeatMode) {
            REPEAT_ONE -> Player.REPEAT_MODE_ONE
            REPEAT_ALL -> if (model.shuffle) Player.REPEAT_MODE_OFF else Player.REPEAT_MODE_ALL
            else -> Player.REPEAT_MODE_OFF
        }
        player.shuffleModeEnabled = false
        shuffle = model.shuffle
        repeatMode = model.repeatMode
    }

    fun saveSession() {
        AppPrefs.lastQueue = model.queue.map { it.song.id }
        AppPrefs.lastIndex = model.currentIndex
        AppPrefs.lastPosition = if (this::player.isInitialized) player.currentPosition else 0L
        AppPrefs.repeatMode = model.repeatMode
        AppPrefs.shuffle = model.shuffle
    }

    private fun restoreSession() {
        val songs = Library.db.getSongs(AppPrefs.lastQueue)
        if (songs.isEmpty()) return
        val entries = songs.map { Entry(it) }
        val index = AppPrefs.lastIndex.coerceIn(0, entries.size - 1)
        model.restore(entries, index)
        player.setMediaItems(items(model.queue), index, AppPrefs.lastPosition)
        player.playWhenReady = false
        player.prepare()
        pendingCount = false
        publish()
    }

    fun positionMs(): Long = if (this::player.isInitialized) player.currentPosition else 0L

    // ---------- start / queue ----------
    fun playSongs(songs: List<Song>, startIndex: Int? = 0, shuffled: Boolean? = null) {
        if (songs.isEmpty()) return
        model.playSongs(songs.map { Entry(it) }, startIndex, shuffled)
        startFromModel()
    }

    private fun startFromModel() {
        applyModes()
        errorsInRow = 0
        player.setMediaItems(items(model.queue), model.currentIndex, 0L)
        player.prepare()
        player.play()
        publish()
    }

    fun addToQueue(songs: List<Song>) {
        val entries = songs.map { Entry(it) }
        if (!model.addToQueue(entries)) {
            startFromModel()
            return
        }
        player.addMediaItems(items(entries))
        publish()
    }

    fun playNext(songs: List<Song>) {
        val entries = songs.map { Entry(it) }
        val insertAt = model.currentIndex + 1
        if (!model.playNext(entries)) {
            startFromModel()
            return
        }
        player.addMediaItems(insertAt, items(entries))
        publish()
    }

    fun removeFromQueue(indexes: Collection<Int>) {
        for (index in indexes.toSortedSet().reversed()) {
            if (index != model.currentIndex && index in model.queue.indices) player.removeMediaItem(index)
        }
        model.removeFromQueue(indexes)
        publish()
    }

    fun moveInQueue(fromIndex: Int, toIndex: Int) {
        if (fromIndex !in model.queue.indices) return
        val target = toIndex.coerceIn(0, model.queue.size - 1)
        player.moveMediaItem(fromIndex, target)
        model.moveInQueue(fromIndex, toIndex)
        publish()
    }

    fun clearUpcoming() {
        player.removeMediaItems(model.currentIndex + 1, Int.MAX_VALUE)
        model.clearUpcoming()
        publish()
    }

    fun jumpTo(index: Int) {
        if (!model.jumpTo(index)) return
        errorsInRow = 0
        player.seekTo(index, 0L)
        player.prepare()
        player.play()
        publish()
    }

    /** Rebuilds the items before and after the current song after the order changed (the current song keeps playing). */
    private fun syncKeepingCurrent(oldPlayerIndex: Int) {
        val current = model.currentIndex
        player.replaceMediaItems(oldPlayerIndex + 1, Int.MAX_VALUE, items(model.queue.subList(current + 1, model.queue.size)))
        player.replaceMediaItems(0, oldPlayerIndex, items(model.queue.subList(0, current)))
    }

    // ---------- controls ----------
    fun togglePlay() {
        if (model.queue.isEmpty()) return
        if (player.isPlaying || player.playWhenReady && player.playbackState != Player.STATE_ENDED) {
            player.pause()
            return
        }
        if (player.playbackState == Player.STATE_ENDED) player.seekTo(player.currentMediaItemIndex, 0L)
        if (player.playbackState == Player.STATE_IDLE) player.prepare()
        player.play()
    }

    fun next() {
        if (model.queue.isEmpty()) return
        if (model.currentIndex + 1 < model.queue.size) {
            jumpTo(model.currentIndex + 1)
            return
        }
        // Last song: "next" goes back to the first one (it plays by itself only with "repeat all")
        val repeatAll = model.repeatMode == REPEAT_ALL
        model.wrapAround()
        player.setMediaItems(items(model.queue), model.currentIndex, 0L)
        player.prepare()
        if (repeatAll) player.play() else player.pause()
        publish()
    }

    fun previous() {
        if (model.queue.isEmpty()) return
        if (player.currentPosition > 3000 || model.currentIndex == 0) {
            player.seekTo(0L)
            return
        }
        jumpTo(model.currentIndex - 1)
    }

    fun seekTo(positionMs: Long) {
        player.seekTo(positionMs.coerceAtLeast(0L))
    }

    fun setShuffle(enabled: Boolean) {
        if (enabled == model.shuffle) return
        val oldIndex = player.currentMediaItemIndex
        model.setShuffle(enabled)
        if (model.queue.isNotEmpty() && oldIndex >= 0) syncKeepingCurrent(oldIndex)
        applyModes()
        publish()
    }

    fun cycleRepeat() {
        model.cycleRepeat()
        applyModes()
        publish()
    }

    // ---------- events of the sound player ----------
    private val listener = object : Player.Listener {
        override fun onIsPlayingChanged(isPlaying: Boolean) {
            PlayerController.isPlaying = isPlaying
            if (isPlaying && pendingCount) countPlay()
            if (!isPlaying) saveSession()
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            isBuffering = playbackState == Player.STATE_BUFFERING
            val total = player.duration
            if (total != C.TIME_UNSET && total > 0) durationMs = total
            if (playbackState == Player.STATE_READY) errorsInRow = 0
            if (playbackState == Player.STATE_ENDED) onEnded()
        }

        override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
            if (mediaItem == null) return
            val newIndex = player.currentMediaItemIndex
            if (reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO) model.onAdvanced(newIndex)
            if (player.isPlaying) countPlay() else pendingCount = true
            val total = player.duration
            durationMs = if (total != C.TIME_UNSET && total > 0) total else model.current()?.song?.durationMs ?: 0L
            publish()
        }

        override fun onPlayerError(error: PlaybackException) {
            errorMessage = "Impossibile riprodurre questo brano"
            errorsInRow += 1
            if (errorsInRow < model.queue.size && model.currentIndex + 1 < model.queue.size) {
                jumpTo(model.currentIndex + 1)
            }
        }
    }

    private fun countPlay() {
        pendingCount = false
        model.current()?.song?.id?.let { Library.registerPlay(it) }
    }

    /** The last song is over. With "repeat all" and shuffle the queue is mixed again and starts from the beginning. */
    private fun onEnded() {
        if (model.repeatMode == REPEAT_ALL && model.shuffle && model.queue.size > 1) {
            model.wrapAround()
            startFromModel()
        }
        saveSession()
    }
}
