package it.sonus.mobile

internal data class FocusDecision(val pause: Boolean = false, val resume: Boolean = false, val gain: Float = 1f)

/** Pure transition policy: the service performs the Android/Python side effects. */
internal class FocusPolicy {
    private var resumeAfterTransient = false

    fun cancelResume() { resumeAfterTransient = false }

    fun change(focus: Int, playing: Boolean): FocusDecision = when (focus) {
        LOSS -> {
            resumeAfterTransient = false
            FocusDecision(pause = playing)
        }
        LOSS_TRANSIENT -> {
            resumeAfterTransient = resumeAfterTransient || playing
            FocusDecision(pause = playing)
        }
        LOSS_DUCK -> FocusDecision(gain = 0.2f)
        GAIN -> {
            // The pause command may still be queued when focus returns. Reasserting
            // a desired playing state is safe even before its snapshot arrives.
            val resume = resumeAfterTransient
            resumeAfterTransient = false
            FocusDecision(resume = resume)
        }
        else -> FocusDecision()
    }

    companion object {
        const val GAIN = 1
        const val LOSS = -1
        const val LOSS_TRANSIENT = -2
        const val LOSS_DUCK = -3
    }
}
