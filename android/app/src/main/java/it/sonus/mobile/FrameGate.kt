package it.sonus.mobile

/** Limits output scheduling; it does not claim to reduce decoder work. Zero preserves source cadence. */
internal class FrameGate(fps: Int) {
    private val minimumIntervalNs = if (fps > 0) 1_000_000_000L / fps.coerceAtMost(240) else 0L
    private var lastFrameNs: Long? = null

    fun shouldRender(releaseTimeNs: Long): Boolean {
        val previous = lastFrameNs
        if (minimumIntervalNs == 0L || previous == null || releaseTimeNs < previous || releaseTimeNs - previous >= minimumIntervalNs) {
            lastFrameNs = releaseTimeNs
            return true
        }
        return false
    }

    fun reset() { lastFrameNs = null }
}
