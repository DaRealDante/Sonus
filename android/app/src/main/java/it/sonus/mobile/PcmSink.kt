package it.sonus.mobile

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import androidx.annotation.Keep
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CopyOnWriteArraySet

/** Receives little-endian interleaved float32 frames from the original Python DSP. */
@Keep
class PcmSink(sampleRate: Int, channels: Int, blockSize: Int) {
    private val frameBytes = channels * 4
    @Volatile private var closed = false
    private var buffer = ByteBuffer.allocateDirect(maxOf(1, blockSize) * frameBytes).order(ByteOrder.LITTLE_ENDIAN)
    private val track: AudioTrack

    init {
        require(sampleRate in 8000..192000) { "Unsupported PCM sample rate: $sampleRate" }
        require(channels in 1..2) { "PCM output supports mono and stereo" }
        require(blockSize > 0) { "PCM block size must be positive" }
        val channelMask = if (channels == 1) AudioFormat.CHANNEL_OUT_MONO else AudioFormat.CHANNEL_OUT_STEREO
        val minimum = AudioTrack.getMinBufferSize(sampleRate, channelMask, AudioFormat.ENCODING_PCM_FLOAT)
        check(minimum > 0) { "Float PCM output is unavailable ($minimum)" }
        track = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
            .setAudioFormat(AudioFormat.Builder().setSampleRate(sampleRate).setChannelMask(channelMask)
                .setEncoding(AudioFormat.ENCODING_PCM_FLOAT).build())
            .setTransferMode(AudioTrack.MODE_STREAM)
            .setBufferSizeInBytes(maxOf(minimum, blockSize * frameBytes * 2))
            .build()
        check(track.state == AudioTrack.STATE_INITIALIZED) { "AudioTrack could not initialize" }
        sinks.add(this)
        track.setVolume(duckingGain)
        track.play()
    }

    fun write(data: ByteArray): Int {
        if (closed) return 0
        require(data.size % frameBytes == 0) { "PCM data must contain complete float frames" }
        if (data.isEmpty()) return 0
        if (buffer.capacity() < data.size) buffer = ByteBuffer.allocateDirect(data.size).order(ByteOrder.LITTLE_ENDIAN)
        buffer.clear()
        buffer.put(data)
        buffer.flip()
        return try {
            val written = track.write(buffer, data.size, AudioTrack.WRITE_BLOCKING)
            check(written >= 0 || closed) { "AudioTrack write failed ($written)" }
            maxOf(0, written)
        } catch (error: IllegalStateException) {
            if (closed) 0 else throw error
        }
    }

    fun close() {
        if (closed) return
        synchronized(this) {
            if (closed) return
            closed = true
            sinks.remove(this)
            try { track.pause(); track.flush() } finally { track.release() }
        }
    }

    companion object {
        private val sinks = CopyOnWriteArraySet<PcmSink>()
        @Volatile private var duckingGain = 1f
        internal fun setDucking(gain: Float) {
            duckingGain = gain.coerceIn(0f, 1f)
            sinks.forEach { sink ->
                if (!sink.closed) runCatching { sink.track.setVolume(duckingGain) }
            }
        }
    }
}
