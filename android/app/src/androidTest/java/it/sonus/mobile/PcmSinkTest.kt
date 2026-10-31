package it.sonus.mobile

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PcmSinkTest {
    @Test fun writesFloatFramesAndCloseIsIdempotent() {
        val sink = PcmSink(48000, 2, 1024)
        try {
            assertEquals(8192, sink.write(ByteArray(8192)))
        } finally {
            sink.close()
            sink.close()
        }
        assertEquals(0, sink.write(ByteArray(8192)))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsUnalignedFramesBeforeWriting() {
        val sink = PcmSink(48000, 2, 1024)
        try { sink.write(ByteArray(7)) } finally { sink.close() }
    }
}
