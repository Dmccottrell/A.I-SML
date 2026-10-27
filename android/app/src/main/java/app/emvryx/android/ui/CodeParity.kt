package app.emvryx.android.ui

import app.emvryx.android.data.bool
import app.emvryx.android.data.int
import app.emvryx.android.data.str
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

// The website's newer VryxCode parts for the Android app (feature flag android_vryxcode, and each part's own VryxCode flag; web/js/ide.js, code.js).
// Worked out here from the session's events, so the screen only draws them (and they are tested in CodeParityTest).

/** One step of VryxCode's plan (flag vryxcode_taskbox): done, the one it is doing now, or still to come */
data class PlanStep(val text: String, val state: String)

/** The plan from the last `todo` step: the first unfinished step is "now" while VryxCode is working */
fun planSteps(events: List<JsonObject>, working: Boolean): List<PlanStep> {
    val last = events.lastOrNull { it.str("kind") == "step" && it.str("tool") == "todo" } ?: return emptyList()
    val items = runCatching {
        Json.parseToJsonElement(last.str("preview").removePrefix("todo ")).jsonObject["items"]!!.jsonArray.map {
            val o = it.jsonObject
            o["text"]!!.jsonPrimitive.content to (o["done"]?.jsonPrimitive?.booleanOrNull ?: false)
        }
    }.getOrDefault(emptyList())
    val now = items.indexOfFirst { !it.second }
    return items.mapIndexed { i, (text, done) -> PlanStep(text, if (done) "done" else if (i == now && working) "now" else "todo") }
}

/** How a message ended, said plainly (flag vryxcode_autocontinue) */
sealed interface EndState {
    data object Finished : EndState
    data object Waiting : EndState
    data class OutOfSteps(val rounds: Int) : EndState
}

fun endState(e: JsonObject): EndState? = when {
    e.str("kind") != "end" -> null
    e.bool("finished") -> EndState.Finished
    e.str("reason") == "steps" -> EndState.OutOfSteps(e.int("rounds"))
    e.bool("said") && !e.bool("plan") -> EndState.Waiting
    else -> null
}

/** A review's verdict (flag vryxcode_guardrails on the server): approved, or the serious problems and the message that fixes them, test first */
data class Verdict(val approved: Boolean, val blocking: Int, val nits: Int, val fix: String)

fun verdictOf(e: JsonObject): Verdict? {
    val v = e["verdict"] as? JsonObject ?: return null
    return Verdict(v.str("status") == "APPROVED", v.int("blocking"), v.int("nits"), v.str("fix"))
}

/** The Claude Code-style feed (flag vryxcode_lines): quiet lines in a row fold into one line that opens on a tap */
fun foldQuiet(items: List<ReviewItem>): List<ReviewItem> {
    val out = mutableListOf<ReviewItem>()
    for (item in items) {
        val prev = out.lastOrNull()
        if (item !is ReviewItem.Quiet) { out += item; continue }
        when (prev) {
            is ReviewItem.Group -> out[out.lastIndex] = ReviewItem.Group(prev.lines + item)
            is ReviewItem.Quiet -> out[out.lastIndex] = ReviewItem.Group(listOf(prev, item))
            else -> out += item
        }
    }
    return out
}

/** "Read 3 files, ran 2 commands" for a folded line */
fun groupTitle(g: ReviewItem.Group): String {
    val reads = g.lines.count { it.text.startsWith("Read ") }
    val runs = g.lines.count { it.text.startsWith("Ran ") }
    val thought = g.lines.count { it.text.startsWith("Thought ") }
    val other = g.lines.size - reads - runs - thought
    val parts = listOfNotNull(
        thought.takeIf { it > 0 }?.let { "thought" },
        reads.takeIf { it > 0 }?.let { if (it == 1) "read a file" else "read $it files" },
        runs.takeIf { it > 0 }?.let { if (it == 1) "ran a command" else "ran $it commands" },
        other.takeIf { it > 0 }?.let { if (it == 1) "looked around" else "$it more steps" },
    )
    return parts.joinToString(", ").replaceFirstChar { it.uppercase() }
}
