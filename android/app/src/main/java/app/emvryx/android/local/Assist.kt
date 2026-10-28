package app.emvryx.android.local

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

// Deep Research, Talk and Scheduled tasks in the app (flags chat_research, chat_live_voice, chat_schedule): the same features as the
// website's (web/js/assist.js), on the same server calls.

/** One scheduled task as GET /api/schedules lists it (app/scheduled.py); [said] is "Every weekday at 07:30" */
@Serializable
data class Schedule(val id: String, val name: String = "", val prompt: String = "", val `when`: String = "daily", val time: String = "",
                    val days: List<Int> = emptyList(), val date: String = "", val on: Boolean = true, val chat: Long? = null,
                    @SerialName("last_run") val lastRun: Double? = null, @SerialName("last_error") val lastError: String = "", val said: String = "")

@Serializable
data class Schedules(val tasks: List<Schedule> = emptyList(), val task: Schedule? = null)

object ScheduleForm {
    val KINDS = listOf("daily" to "Every day", "weekdays" to "Weekdays", "weekly" to "On chosen days", "once" to "Once")
    val DAYS = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    private val TIME = Regex("([01]?\\d|2[0-3]):[0-5]\\d")
    private val DATE = Regex("\\d{4}-\\d{2}-\\d{2}")

    /** What is wrong before it is sent (the server checks again), or null */
    fun problem(prompt: String, kind: String, time: String, date: String, days: Set<Int>): String? = when {
        prompt.isBlank() -> "Write what Emvryx should do."
        !TIME.matches(time.trim()) -> "Write the time like 07:30."
        kind == "once" && !DATE.matches(date.trim()) -> "Write the date like 2026-05-03."
        kind == "weekly" && days.isEmpty() -> "Pick at least one day."
        else -> null
    }

    /** POST /api/schedules, as the website sends it; [tz] is the phone's offset from UTC in minutes */
    fun body(prompt: String, name: String, kind: String, time: String, date: String, days: Set<Int>, tz: Int, model: String, effort: String): JsonObject =
        buildJsonObject {
            put("prompt", prompt.trim()); put("name", name.trim()); put("when", kind); put("time", time.trim().padStart(5, '0'))
            put("date", date.trim()); put("tz", tz); put("model", model); put("effort", if (effort == "auto") "balanced" else effort)
            putJsonArray("days") { days.sorted().forEach { add(kotlinx.serialization.json.JsonPrimitive(it)) } }
        }
}

object Speech {
    /** An answer as it is read out: code is not spelled out, source numbers and markdown marks are dropped (assist.js speak) */
    fun plain(text: String): String = text
        .replace(Regex("```[\\s\\S]*?```"), " (there is code in the chat) ")
        .replace(Regex("\\s*\\[(\\d+)]"), "")
        .replace(Regex("\\[([^\\]]+)]\\([^)]+\\)"), "$1")
        .replace(Regex("[#*_`>|]"), "")
        .replace(Regex("[ \\t]+"), " ")
        .trim()

    /** The research line under the thinking words: "Searching: tallest mountains (2 of 7)" */
    fun step(step: String, done: Int, of: Int) = "🔎 " + step + if (of > 0) " ($done of $of)" else ""
}
