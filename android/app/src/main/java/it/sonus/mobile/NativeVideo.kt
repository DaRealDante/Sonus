package it.sonus.mobile

import android.content.Context
import android.os.Handler
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.Renderer
import androidx.media3.exoplayer.mediacodec.MediaCodecAdapter
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector
import androidx.media3.exoplayer.video.MediaCodecVideoRenderer
import androidx.media3.exoplayer.video.VideoRendererEventListener
import java.util.ArrayList

/** A cap on frames submitted to the Surface, independent of the original Python audio DSP. */
@UnstableApi
class SonusVideoRenderers(context: Context, private val fps: Int) : DefaultRenderersFactory(context) {
    override fun buildVideoRenderers(
        context: Context,
        extensionRendererMode: Int,
        mediaCodecSelector: MediaCodecSelector,
        enableDecoderFallback: Boolean,
        eventHandler: Handler,
        eventListener: VideoRendererEventListener,
        allowedVideoJoiningTimeMs: Long,
        out: ArrayList<Renderer>,
    ) {
        out.add(CappedVideoRenderer(context, codecAdapterFactory, mediaCodecSelector, allowedVideoJoiningTimeMs,
            enableDecoderFallback, eventHandler, eventListener, fps))
    }
}

@UnstableApi
private class CappedVideoRenderer(
    context: Context,
    adapterFactory: MediaCodecAdapter.Factory,
    selector: MediaCodecSelector,
    joiningTimeMs: Long,
    fallback: Boolean,
    handler: Handler,
    listener: VideoRendererEventListener,
    fps: Int,
) : MediaCodecVideoRenderer(context, adapterFactory, selector, joiningTimeMs, fallback, handler, listener, 50) {
    private val frameGate = FrameGate(fps)

    override fun renderOutputBufferV21(codec: MediaCodecAdapter, index: Int, presentationTimeUs: Long, releaseTimeNs: Long) {
        if (frameGate.shouldRender(releaseTimeNs)) super.renderOutputBufferV21(codec, index, presentationTimeUs, releaseTimeNs)
        else skipOutputBuffer(codec, index, presentationTimeUs)
    }

    override fun renderOutputBuffer(codec: MediaCodecAdapter, index: Int, presentationTimeUs: Long) {
        if (frameGate.shouldRender(System.nanoTime())) super.renderOutputBuffer(codec, index, presentationTimeUs)
        else skipOutputBuffer(codec, index, presentationTimeUs)
    }

    override fun onPositionReset(positionUs: Long, joining: Boolean) {
        frameGate.reset()
        super.onPositionReset(positionUs, joining)
    }

    override fun onDisabled() {
        frameGate.reset()
        super.onDisabled()
    }
}
