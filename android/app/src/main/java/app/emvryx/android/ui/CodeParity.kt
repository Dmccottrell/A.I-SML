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

// CodeParity.kt: "parity" means the Android app matching the website. Each function below takes the session's events
// (raw JSON objects from the server) and works out what a newer VryxCode screen part should show.
// The website's newer VryxCode parts for the Android app (feature flag android_vryxcode, and each part's own VryxCode flag; web/js/ide.js, code.js).
// Worked out here from the session's events, so the screen only draws them (and they are tested in CodeParityTest).

/**
 * One step of VryxCode's plan (flag vryxcode_taskbox).
 * [text] is what the step says; [state] is "done", "now" (the one being worked on) or "todo" (still to come).
 */
data class PlanStep(val text: String, val state: String)

/**
 * Reads the plan from the most recent `todo` step.
 * [events] is the session's event list; [working] says whether VryxCode is busy right now.
 * Returns the steps in order, or an empty list if there is no plan (or it cannot be read).
 * The first unfinished step is marked "now", but only while VryxCode is still working.
 */
fun planSteps(events: List<JsonObject>, working: Boolean): List<PlanStep> {
    // Find the newest step event whose tool is "todo"; if there is none, return an empty plan right away (`?: return` leaves the function).
    val last = events.lastOrNull { it.str("kind") == "step" && it.str("tool") == "todo" } ?: return emptyList()
    // runCatching catches any error (bad JSON, missing field) so a broken plan shows nothing instead of crashing the app.
    val items = runCatching {
        // The preview looks like `todo {"items":[...]}`: strip the leading "todo " and parse the rest as JSON, then read its "items" list.
        // `!!` means "I am sure this is not null"; if it is, an error is thrown, which runCatching catches.
        Json.parseToJsonElement(last.str("preview").removePrefix("todo ")).jsonObject["items"]!!.jsonArray.map {
            val o = it.jsonObject
            // Each item becomes (text, done): "done" defaults to false when the key is missing.
            o["text"]!!.jsonPrimitive.content to (o["done"]?.jsonPrimitive?.booleanOrNull ?: false)
        }
    // On any failure fall back to an empty list.
    }.getOrDefault(emptyList())
    // Position of the first step that is not done (-1 if all are done).
    val now = items.indexOfFirst { !it.second }
    // Label each step: done wins; otherwise the first unfinished step is "now" (only while working); the rest are "todo".
    return items.mapIndexed { i, (text, done) -> PlanStep(text, if (done) "done" else if (i == now && working) "now" else "todo") }
}

/**
 * How a message ended, said plainly (flag vryxcode_autocontinue). A sealed interface = a fixed set of possible answers.
 * Finished: the work is complete. Waiting: VryxCode said something and is waiting for the user. OutOfSteps: it used up its step limit after [rounds] rounds.
 */
sealed interface EndState {
    data object Finished : EndState
    data object Waiting : EndState
    data class OutOfSteps(val rounds: Int) : EndState
}

/**
 * Works out how a message ended from an "end" event [e]. Returns null if [e] is not an end event or none of the cases apply.
 */
fun endState(e: JsonObject): EndState? = when {
    // Not an "end" event: nothing to say.
    e.str("kind") != "end" -> null
    e.bool("finished") -> EndState.Finished
    // The agent stopped because it hit its step limit.
    e.str("reason") == "steps" -> EndState.OutOfSteps(e.int("rounds"))
    // It spoke and did not just make a plan: it is waiting for the user to answer.
    e.bool("said") && !e.bool("plan") -> EndState.Waiting
    else -> null
}

/**
 * A review's verdict (flag vryxcode_guardrails on the server).
 * [approved] is true when the review passed; [blocking] counts serious problems that must be fixed; [nits] counts minor
 * style points; [fix] is the message to send VryxCode to fix the problems (test first).
 */
data class Verdict(val approved: Boolean, val blocking: Int, val nits: Int, val fix: String)

/** Reads the "verdict" object out of an event [e]; returns null when the event has none. */
fun verdictOf(e: JsonObject): Verdict? {
    // `as?` is a safe cast: it gives null instead of failing when "verdict" is missing or not an object, and `?: return null` then exits.
    val v = e["verdict"] as? JsonObject ?: return null
    return Verdict(v.str("status") == "APPROVED", v.int("blocking"), v.int("nits"), v.str("fix"))
}

/**
 * The Claude Code-style feed (flag vryxcode_lines): quiet lines in a row fold into one line that opens on a tap.
 * [items] is the review feed; returns the same feed where each run of two or more Quiet items is replaced by one Group.
 */
fun foldQuiet(items: List<ReviewItem>): List<ReviewItem> {
    // Build the shortened list here.
    val out = mutableListOf<ReviewItem>()
    // Look at every item; `prev` is the last thing already placed in the output.
    for (item in items) {
        val prev = out.lastOrNull()
        // Anything that is not a quiet line is copied through unchanged (the `;` lets two statements share one line).
        if (item !is ReviewItem.Quiet) { out += item; continue }
        // A quiet line after an existing group joins that group; after another quiet line, the two become a new group; otherwise it starts the run as a single item.
        when (prev) {
            is ReviewItem.Group -> out[out.lastIndex] = ReviewItem.Group(prev.lines + item)
            is ReviewItem.Quiet -> out[out.lastIndex] = ReviewItem.Group(listOf(prev, item))
            else -> out += item
        }
    }
    return out
}

/** A short title for a folded line, for example "Thought, read 3 files, ran 2 commands". [g] is the group of quiet lines. */
fun groupTitle(g: ReviewItem.Group): String {
    // Count the lines by what their text starts with.
    val reads = g.lines.count { it.text.startsWith("Read ") }
    val runs = g.lines.count { it.text.startsWith("Ran ") }
    val thought = g.lines.count { it.text.startsWith("Thought ") }
    // Whatever is left over that is none of the three kinds.
    val other = g.lines.size - reads - runs - thought
    // takeIf { it > 0 } gives null for a zero count, and listOfNotNull drops the nulls, so only kinds that happened appear in the title.
    val parts = listOfNotNull(
        thought.takeIf { it > 0 }?.let { "thought" },
        reads.takeIf { it > 0 }?.let { if (it == 1) "read a file" else "read $it files" },
        runs.takeIf { it > 0 }?.let { if (it == 1) "ran a command" else "ran $it commands" },
        other.takeIf { it > 0 }?.let { if (it == 1) "looked around" else "$it more steps" },
    )
    // Join the parts with commas and make the first letter a capital.
    return parts.joinToString(", ").replaceFirstChar { it.uppercase() }
}

/**
 * What to answer when VryxCode stops with "Not finished yet: it is waiting for your answer", given what it said ([text]): replies one tap sends, the first also greyed
 * in the message box. A question gets "Yes, go ahead."; anything else is a push to really save the work, run it and explain what was wrong. (The same words as the website's.)
 */
fun waitingReplies(text: String): List<String> {
    return if (asksYou(text)) listOf("Yes, go ahead.", "Explain your options first.", "No, I want something different.")
    else listOf("Please save the fix to the project files, run the tests, and tell me what was wrong.", "Explain in plain words what was wrong.", "Show me what you changed.")
}

/** True when the reply ends by asking the person something (a question mark, "would you like", "should I", ...). The website's vxAsksYou. */
fun asksYou(text: String): Boolean {
    val tail = text.trim().takeLast(400)
    return tail.endsWith("?") || Regex("\\b(would you like|do you want|shall i|should i|let me know|which (one|option|file))\\b", RegexOption.IGNORE_CASE).containsMatchIn(tail)
}

/** True when what the person typed is a question (why, what, explain, show me, ...?), so a plain explanation is the whole answer. The website's vxIsQuestion. */
fun isQuestion(text: String): Boolean {
    val t = text.trim().lowercase()
    return t.endsWith("?") || Regex("^(why|what|how|when|where|who|which|explain|show me|tell me|describe|can you explain|could you explain|is it|does it|did it|are you)\\b").containsMatchIn(t)
}

/** What the person last typed before the end event [e] (a "user" or "start" message), lower case. */
fun lastAsked(events: List<JsonObject>, e: JsonObject): String {
    val at = events.indexOfFirst { it === e }.let { if (it < 0) events.size else it }
    for (i in at - 1 downTo 0) {
        val x = events[i]
        if (x.str("kind") == "user" || x.str("kind") == "start") return (x.str("text").ifBlank { x.str("task") }).trim().lowercase()
    }
    return ""
}

/**
 * True when the turn ended with a plain answer to a question: not finished, not a plan, the person asked a question and the reply does not ask one back. That is an
 * answer, not a task "waiting for your answer", so no banner. (The website's justAnswered.)
 */
fun justAnswered(e: JsonObject, events: List<JsonObject>): Boolean =
    endState(e) == EndState.Waiting && isQuestion(lastAsked(events, e)) && !asksYou(e.str("summary"))

/** A few things the person could ask next after a plain answer, leaving out what they just asked. "Show me what you changed." opens the changes by itself (see CodeScreen). */
fun followUps(last: String, text: String): List<String> {
    val said = text.lowercase()
    val all = listOf("Show me what you changed.", "Run the tests and tell me the result.", "Explain it again in simpler words.", "What should I do next?")
    return all.filter { t ->
        t.lowercase() != last && !(t.startsWith("Explain") && Regex("plain words|simpler").containsMatchIn(last)) && !(t.startsWith("Show") && "changed" in last && "changed" in said)
    }.take(3)
}
