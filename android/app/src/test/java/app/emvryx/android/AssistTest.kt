package app.emvryx.android

import app.emvryx.android.local.ScheduleForm
import app.emvryx.android.local.Schedules
import app.emvryx.android.local.Speech
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AssistTest {
    @Test
    fun answersAreReadOutWithoutCodeSourceNumbersOrMarks() {
        assertEquals("Mount Everest is the tallest. See Wikipedia.",
            Speech.plain("**Mount Everest** is the tallest [1]. See [Wikipedia](https://en.wikipedia.org)."))
        assertEquals("Run this: (there is code in the chat) then wait.", Speech.plain("Run this: ```py\nprint(1)\n``` then wait."))
    }

    @Test
    fun theFormSaysWhatIsMissingBeforeSending() {
        assertEquals("Write what Emvryx should do.", ScheduleForm.problem(" ", "daily", "07:30", "", emptySet()))
        assertEquals("Write the time like 07:30.", ScheduleForm.problem("news", "daily", "7.30", "", emptySet()))
        assertEquals("Write the date like 2026-05-03.", ScheduleForm.problem("call the bank", "once", "09:00", "3 May", emptySet()))
        assertEquals("Pick at least one day.", ScheduleForm.problem("meal plan", "weekly", "18:00", "", emptySet()))
        assertNull(ScheduleForm.problem("news", "weekdays", "7:30", "", emptySet()))
    }

    @Test
    fun theBodyIsWhatTheWebsiteSends() {
        val b = ScheduleForm.body(" news ", "", "weekly", "7:30", "", setOf(4, 0), 60, "flare-3", "auto")
        assertEquals("07:30", b["time"]!!.jsonPrimitive.content)
        assertEquals("balanced", b["effort"]!!.jsonPrimitive.content)      // Auto is not a scheduled effort, as on the website
        assertEquals(listOf(0, 4), b["days"]!!.jsonArray.map { it.jsonPrimitive.content.toInt() })
        assertEquals("news", b["prompt"]!!.jsonPrimitive.content)
    }

    @Test
    fun theServersListIsRead() {
        // the shape of app/scheduled.py Schedules.list
        val s = Json { ignoreUnknownKeys = true }.decodeFromString<Schedules>("""{"tasks": [{"id": "0123456789ab", "name": "Morning news",
            "prompt": "news", "when": "weekdays", "time": "07:30", "days": [], "date": "", "tz": 60, "model": "", "effort": "balanced", "chat": 12,
            "last_run": 1761600000.5, "runs": 3, "on": false, "last_error": "", "next_run": 1761700000, "said": "Every weekday at 07:30"}]}""")
        assertEquals("Every weekday at 07:30", s.tasks[0].said)
        assertEquals(12L, s.tasks[0].chat)
        assertEquals(false, s.tasks[0].on)
    }

    @Test
    fun aResearchStepShowsHowFarItIs() {
        assertEquals("🔎 Reading 3 pages (2 of 7)", Speech.step("Reading 3 pages", 2, 7))
    }
}
