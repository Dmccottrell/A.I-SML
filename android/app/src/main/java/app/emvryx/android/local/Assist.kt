package app.emvryx.android.local

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

// Assist.kt: small helpers for three assistant features in the app: Scheduled tasks (run a prompt on a timetable),
// Talk (speaking answers aloud) and Deep Research (shows progress). The screens are in ui/AssistScreens.kt.
//
// Deep Research, Talk and Scheduled tasks in the app (flags chat_research, chat_live_voice, chat_schedule): the same features as the
// website's (web/js/assist.js), on the same server calls.

/**
 * One scheduled task as GET /api/schedules lists it (app/scheduled.py); [said] is "Every weekday at 07:30".
 * `when` is a Kotlin keyword, so the backticks let it be used as a field name (it is the JSON name too): "daily", "weekdays", "weekly" or "once".
 * [days] are numbers for the weekdays (the order of ScheduleForm.DAYS); [lastRun] is a Unix time, [chat] the chat the last run wrote into.
 */
@Serializable
data class Schedule(val id: String, val name: String = "", val prompt: String = "", val `when`: String = "daily", val time: String = "",
                    val days: List<Int> = emptyList(), val date: String = "", val on: Boolean = true, val chat: Long? = null,
                    @SerialName("last_run") val lastRun: Double? = null, @SerialName("last_error") val lastError: String = "", val said: String = "")

/** The reply of the schedule calls: the whole [tasks] list, or a single [task]. */
@Serializable
data class Schedules(val tasks: List<Schedule> = emptyList(), val task: Schedule? = null)

/** Rules and body-building for the "new scheduled task" form. */
object ScheduleForm {
    // How often a task repeats: the server's word, then the label on screen.
    val KINDS = listOf("daily" to "Every day", "weekdays" to "Weekdays", "weekly" to "On chosen days", "once" to "Once")
    // Day names; their position in this list (0 = Mon) is the number sent to the server.
    val DAYS = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    // A regex is a text pattern. TIME: an hour 0-23 (one or two digits) then a colon and minutes 00-59, e.g. 7:30 or 07:30.
    // DATE: four digits, dash, two digits, dash, two digits, e.g. 2026-05-03. (Only the shape is checked here; the server checks again.)
    private val TIME = Regex("([01]?\\d|2[0-3]):[0-5]\\d")
    private val DATE = Regex("\\d{4}-\\d{2}-\\d{2}")

    /** What is wrong before it is sent (the server checks again), or null when the form is fine. Checks run in order and the first problem wins. */
    fun problem(prompt: String, kind: String, time: String, date: String, days: Set<Int>): String? = when {
        prompt.isBlank() -> "Write what Emvryx should do."
        !TIME.matches(time.trim()) -> "Write the time like 07:30."
        kind == "once" && !DATE.matches(date.trim()) -> "Write the date like 2026-05-03."
        kind == "weekly" && days.isEmpty() -> "Pick at least one day."
        else -> null
    }

    /** POST /api/schedules, as the website sends it; [tz] is the phone's offset from UTC in minutes (so "07:30" means 07:30 where the person is) */
    fun body(prompt: String, name: String, kind: String, time: String, date: String, days: Set<Int>, tz: Int, model: String, effort: String): JsonObject =
        buildJsonObject {
            // padStart turns "7:30" into "07:30". The server has no "auto" effort for a task, so Auto becomes "balanced".
            put("prompt", prompt.trim()); put("name", name.trim()); put("when", kind); put("time", time.trim().padStart(5, '0'))
            put("date", date.trim()); put("tz", tz); put("model", model); put("effort", if (effort == "auto") "balanced" else effort)
            // The chosen days as a sorted JSON list of numbers.
            putJsonArray("days") { days.sorted().forEach { add(kotlinx.serialization.json.JsonPrimitive(it)) } }
        }
}

/** Cleans an answer for text-to-speech so it reads well out loud. */
object Speech {
    /** An answer as it is read out: code is not spelled out, source numbers and markdown marks are dropped (assist.js speak) */
    fun plain(text: String): String = text
        // A code block (three backticks to three backticks, across lines) becomes a short spoken note instead of being read symbol by symbol.
        .replace(Regex("```[\\s\\S]*?```"), " (there is code in the chat) ")
        // Source markers like [3] (and the space before them) are removed.
        .replace(Regex("\\s*\\[(\\d+)]"), "")
        // A markdown link [words](address) keeps only the words ($1 is the text captured in the first brackets).
        .replace(Regex("\\[([^\\]]+)]\\([^)]+\\)"), "$1")
        // Markdown marks that would be read aloud as symbols are dropped.
        .replace(Regex("[#*_`>|]"), "")
        // Runs of spaces and tabs collapse into one space.
        .replace(Regex("[ \\t]+"), " ")
        .trim()

    /** The research line under the thinking words: "Searching: tallest mountains (2 of 7)" ([of] is the total steps; the count is left out when unknown) */
    fun step(step: String, done: Int, of: Int) = "🔎 " + step + if (of > 0) " ($done of $of)" else ""
}
