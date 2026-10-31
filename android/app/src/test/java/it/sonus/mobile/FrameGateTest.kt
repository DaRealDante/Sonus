package it.sonus.mobile

import org.junit.Assert.*
import org.junit.Test

class FrameGateTest {
    @Test fun capSkipsFramesAndAllowsFirstFrameImmediately() {
        val gate = FrameGate(25)
        assertTrue(gate.shouldRender(1_000_000_000))
        assertFalse(gate.shouldRender(1_020_000_000))
        assertTrue(gate.shouldRender(1_040_000_000))
        assertFalse(gate.shouldRender(1_050_000_000))
        assertTrue(gate.shouldRender(1_080_000_000))
    }

    @Test fun automaticModeDoesNotDiscardAnyFrames() {
        val gate = FrameGate(0)
        assertTrue(gate.shouldRender(1))
        assertTrue(gate.shouldRender(2))
        assertTrue(gate.shouldRender(3))
    }

    @Test fun seekAndTimestampRewindAllowImmediateFrame() {
        val gate = FrameGate(12)
        assertTrue(gate.shouldRender(2_000_000_000))
        assertFalse(gate.shouldRender(2_010_000_000))
        gate.reset()
        assertTrue(gate.shouldRender(2_011_000_000))
        assertTrue(gate.shouldRender(1_000_000_000))
    }
}
