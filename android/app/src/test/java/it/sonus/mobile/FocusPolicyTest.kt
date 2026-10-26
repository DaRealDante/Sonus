package it.sonus.mobile

import org.junit.Assert.*
import org.junit.Test

class FocusPolicyTest {
    @Test fun transientLossResumesOnlyPreviouslyPlayingAudio() {
        val policy = FocusPolicy()
        assertTrue(policy.change(FocusPolicy.LOSS_TRANSIENT, true).pause)
        assertTrue(policy.change(FocusPolicy.GAIN, false).resume)
        assertFalse(policy.change(FocusPolicy.GAIN, false).resume)
        policy.change(FocusPolicy.LOSS_TRANSIENT, false)
        assertFalse(policy.change(FocusPolicy.GAIN, false).resume)
    }

    @Test fun manualPauseAndPermanentLossCancelAutomaticResume() {
        val policy = FocusPolicy()
        policy.change(FocusPolicy.LOSS_TRANSIENT, true)
        policy.cancelResume()
        assertFalse(policy.change(FocusPolicy.GAIN, false).resume)
        policy.change(FocusPolicy.LOSS_TRANSIENT, true)
        assertTrue(policy.change(FocusPolicy.LOSS, true).pause)
        assertFalse(policy.change(FocusPolicy.GAIN, false).resume)
    }

    @Test fun duckingRestoresGainWithoutChangingUserVolume() {
        val policy = FocusPolicy()
        assertEquals(0.2f, policy.change(FocusPolicy.LOSS_DUCK, true).gain)
        assertEquals(1f, policy.change(FocusPolicy.GAIN, true).gain)
    }

    @Test fun quickFocusGainReassertsPlayBeforePauseSnapshotArrives() {
        val policy = FocusPolicy()
        assertTrue(policy.change(FocusPolicy.LOSS_TRANSIENT, true).pause)
        assertTrue(policy.change(FocusPolicy.GAIN, true).resume)
    }
}
