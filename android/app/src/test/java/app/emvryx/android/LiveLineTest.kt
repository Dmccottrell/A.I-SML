package app.emvryx.android

// Unit tests for the working line under the newest step ("Running python test.py… 7s"). They need no phone: they only call the pure functions that choose its words.
import app.emvryx.android.ui.liveHeadline
import app.emvryx.android.ui.liveKind
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The website's working line (ide.js paintLive) says what VryxCode is running, in one calm line with a word that changes only every 6 seconds. The Android app says the same words.
 * A "live" object comes from the server: phase (thinking, writing, tool), tool, target (the file or command), secs, tokens.
 */
class LiveLineTest {
    // Reads a live object from JSON text, the way the app reads the server's reply.
    private fun live(json: String): JsonObject = Json.parseToJsonElement(json) as JsonObject

    @Test
    // Proves: with a command or file named, the line is a plain verb and that target ("Running python test_valid_code.py…"), whatever the seconds.
    fun itNamesWhatItIsRunning() {
        val run = live("""{"phase": "tool", "tool": "run", "target": "python test_valid_code.py", "secs": 4}""")
        assertEquals("Running python test_valid_code.py…", liveHeadline(run, 4))
        assertEquals("Running python test_valid_code.py…", liveHeadline(run, 40))                  // no changing words once it names the target
        assertEquals("Reading utils.py…", liveHeadline(live("""{"phase": "tool", "tool": "read_file", "target": "utils.py"}"""), 2))
        assertEquals("Writing fixed_code.py…", liveHeadline(live("""{"phase": "tool", "tool": "write_file", "target": "fixed_code.py"}"""), 2))
        assertEquals("Looking through .…", liveHeadline(live("""{"phase": "tool", "tool": "list_files", "target": "."}"""), 2))
    }

    @Test
    // Proves: only the first line of a long target is used, cut to 60 characters, and Stopping wins while the person has pressed Stop.
    fun aLongTargetIsCutAndStopWins() {
        val long = live("""{"phase": "tool", "tool": "run", "target": "python ${"x".repeat(100)}\nsecond line", "secs": 1}""")
        assertEquals("Running python " + "x".repeat(53) + "…", liveHeadline(long, 1))
        assertEquals("Stopping…", liveHeadline(long, 1, stopping = true))
    }

    @Test
    // Proves: while only thinking (no target) it shows a word that changes every 6 seconds, never faster, and the words belong to the kind of work.
    fun thinkingWordsChangeSlowly() {
        val thinking = live("""{"phase": "thinking", "tool": "", "target": ""}""")
        assertEquals("Thinking…", liveHeadline(thinking, 0))
        assertEquals("Thinking…", liveHeadline(thinking, 5))                                        // still the same word at 5 seconds
        assertEquals("Pondering…", liveHeadline(thinking, 6))
        assertEquals("thinking", liveKind(thinking))
        assertEquals("writing", liveKind(live("""{"phase": "writing"}""")))
        assertEquals("test", liveKind(live("""{"phase": "tool", "tool": "run", "target": "python -m unittest"}""")))
        assertTrue(liveHeadline(live("""{"phase": "writing"}"""), 0).startsWith("Writing"))
    }
}
