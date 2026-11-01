package app.emvryx.android

// Unit tests for the helper features around the chat: reading answers aloud (Speech), the form for scheduled tasks (ScheduleForm),
// and reading the server's list of scheduled tasks. Plain JVM tests: no phone needed.
import app.emvryx.android.local.ScheduleForm
import app.emvryx.android.local.Schedules
import app.emvryx.android.local.Speech
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Checks for the read-aloud text cleaner, the schedule form's checks and request body, and the schedule list reply. */
class AssistTest {
    @Test
    // Proves: before an answer is spoken, markdown marks, source numbers like [1], link addresses and code blocks are removed or replaced.
    fun answersAreReadOutWithoutCodeSourceNumbersOrMarks() {
        // ** bold marks and the [1] source number vanish; a link [text](address) keeps only its text.
        assertEquals("Mount Everest is the tallest. See Wikipedia.",
            Speech.plain("**Mount Everest** is the tallest [1]. See [Wikipedia](https://en.wikipedia.org)."))
        // A fenced code block (between triple backticks) is not read aloud; a short spoken note stands in for it.
        assertEquals("Run this: (there is code in the chat) then wait.", Speech.plain("Run this: ```py\nprint(1)\n``` then wait."))
    }

    @Test
    // Proves: the schedule form returns a plain-words problem message when something is missing or wrong, and null (no problem) when it is fine.
    fun theFormSaysWhatIsMissingBeforeSending() {
        // A blank task text (just a space) is rejected.
        assertEquals("Write what Emvryx should do.", ScheduleForm.problem(" ", "daily", "07:30", "", emptySet()))
        // "7.30" uses a dot, not a colon, so the time is rejected.
        assertEquals("Write the time like 07:30.", ScheduleForm.problem("news", "daily", "7.30", "", emptySet()))
        // A one-time task needs a date in year-month-day form; "3 May" is rejected.
        assertEquals("Write the date like 2026-05-03.", ScheduleForm.problem("call the bank", "once", "09:00", "3 May", emptySet()))
        // A weekly task with an empty set of days is rejected.
        assertEquals("Pick at least one day.", ScheduleForm.problem("meal plan", "weekly", "18:00", "", emptySet()))
        // A valid form ("7:30" is accepted and fixed up later) gives no problem.
        assertNull(ScheduleForm.problem("news", "weekdays", "7:30", "", emptySet()))
    }

    @Test
    // Proves: the request body the app builds for a schedule matches what the website sends (so the server treats both the same).
    fun theBodyIsWhatTheWebsiteSends() {
        // Build the body: the task text has stray spaces, the time is short ("7:30"), days are given out of order, and the effort is "auto".
        val b = ScheduleForm.body(" news ", "", "weekly", "7:30", "", setOf(4, 0), 60, "flare-3", "auto")
        // The time is padded to two digits: 7:30 becomes 07:30.
        assertEquals("07:30", b["time"]!!.jsonPrimitive.content)
        assertEquals("balanced", b["effort"]!!.jsonPrimitive.content)      // Auto is not a scheduled effort, as on the website
        // Days are sorted (the set {4, 0} becomes [0, 4]).
        assertEquals(listOf(0, 4), b["days"]!!.jsonArray.map { it.jsonPrimitive.content.toInt() })
        // The task text is trimmed of the surrounding spaces.
        assertEquals("news", b["prompt"]!!.jsonPrimitive.content)
    }

    @Test
    // Proves: the server's list of scheduled tasks can be decoded into the app's Schedules object.
    fun theServersListIsRead() {
        // the shape of app/scheduled.py Schedules.list
        // Decode a sample reply; ignoreUnknownKeys makes the decoder skip fields the app does not know instead of failing.
        // (The triple-quoted text below is a raw string, so its content is exactly the JSON.)
        val s = Json { ignoreUnknownKeys = true }.decodeFromString<Schedules>("""{"tasks": [{"id": "0123456789ab", "name": "Morning news",
            "prompt": "news", "when": "weekdays", "time": "07:30", "days": [], "date": "", "tz": 60, "model": "", "effort": "balanced", "chat": 12,
            "last_run": 1761600000.5, "runs": 3, "on": false, "last_error": "", "next_run": 1761700000, "said": "Every weekday at 07:30"}]}""")
        // The human-readable summary, the chat id (a Long, hence 12L) and the on/off switch were all read correctly.
        assertEquals("Every weekday at 07:30", s.tasks[0].said)
        assertEquals(12L, s.tasks[0].chat)
        assertEquals(false, s.tasks[0].on)
    }

    @Test
    // Proves: a research progress line shows a magnifier emoji, the step text and "(done of total)".
    fun aResearchStepShowsHowFarItIs() {
        assertEquals("🔎 Reading 3 pages (2 of 7)", Speech.step("Reading 3 pages", 2, 7))
    }
}
