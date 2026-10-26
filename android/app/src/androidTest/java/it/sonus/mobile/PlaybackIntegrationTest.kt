package it.sonus.mobile

import android.content.Intent
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Runs the packaged Python, FFmpeg, DSP and Android AudioTrack, not test doubles. */
class PlaybackIntegrationTest {
    private fun await(label: String, timeout: Long = 60000, predicate: () -> Boolean) {
        val until = SystemClock.elapsedRealtime() + timeout
        while (SystemClock.elapsedRealtime() < until) { if (predicate()) return; SystemClock.sleep(80) }
        fail("Timeout: $label; state=${SonusHost.state.value}")
    }

    private fun wav(file: File) {
        val frames = 44100 * 18
        val buffer = ByteBuffer.allocate(44 + frames * 2).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put("RIFF".toByteArray()).putInt(36 + frames * 2).put("WAVEfmt ".toByteArray()).putInt(16)
            .putShort(1).putShort(1).putInt(44100).putInt(88200).putShort(2).putShort(16)
            .put("data".toByteArray()).putInt(frames * 2)
        repeat(frames) { buffer.putShort((kotlin.math.sin(it * 2 * Math.PI * 440 / 44100) * 5000).toInt().toShort()) }
        file.writeBytes(buffer.array())
    }

    @Test fun packagedCorePlaysWhileScreenIsOffAndRestoresControls() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val scenario = ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java))
        val tone = File(context.filesDir, "screen_off_test.wav")
        try {
            if (android.os.Build.VERSION.SDK_INT >= 33) instrumentation.uiAutomation.executeShellCommand("pm grant ${context.packageName} android.permission.POST_NOTIFICATIONS").close()
            await("core ready") { SonusHost.state.value.optBoolean("ready") }
            wav(tone)
            SonusHost.command("import_files", JSONObject().put("paths", JSONArray().put(tone.absolutePath)))
            await("WAV import") { SonusHost.state.value.list("songs").any { it.str("path") == tone.absolutePath || it.str("title") == "screen_off_test" } }
            val song = SonusHost.state.value.list("songs").first { it.str("path") == tone.absolutePath || it.str("title") == "screen_off_test" }
            SonusHost.command("play", json("ids" to JSONArray().put(song.int("id")), "index" to 0))
            await("real PCM playback") { SonusHost.state.value.flag("playing") && SonusHost.state.value.num("position") > 300 }
            val before = SonusHost.state.value.num("position")
            instrumentation.uiAutomation.executeShellCommand("input keyevent 223").close()
            await("music continues with screen off", 15000) { SonusHost.state.value.num("position") > before + 1500 && SonusHost.state.value.flag("playing") }
            SonusHost.command("pause")
            await("pause from service") { !SonusHost.state.value.flag("playing") }
            SonusHost.command("seek", json("position" to 5000))
            SonusHost.command("play_pause", json("playing" to true))
            await("resume and seek") { SonusHost.state.value.flag("playing") && SonusHost.state.value.num("position") > 5000 }
            SonusHost.command("effects", json("values" to json("rate" to .85, "keepPitch" to false, "reverbWet" to .2, "reverbSize" to 2.0, "bassBoost" to .15)))
            await("live DSP effects") { SonusHost.state.value.obj("effects").num("rate") == .85 }
            SonusHost.command("eq", json("values" to json("enabled" to true, "preset" to "Bass Boost")))
            await("real EQ") { SonusHost.state.value.obj("eq").flag("enabled") }
            assertTrue(SonusHost.state.value.flag("playing"))
        } finally {
            SonusHost.command("pause")
            instrumentation.uiAutomation.executeShellCommand("input keyevent 224").close()
            scenario.close()
        }
    }
}
