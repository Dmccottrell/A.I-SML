package app.emvryx.android.ui

import app.emvryx.android.data.CodeSessionRow
import app.emvryx.android.data.bool
import app.emvryx.android.data.int
import app.emvryx.android.data.num
import app.emvryx.android.data.str
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive

// CodeReview.kt: turns the raw list of events a VryxCode session produced (JSON objects from the server) into the items the
// review screen draws. Nothing here draws anything; keeping it plain functions and data classes makes it easy to unit test.
// An "event" is one JSON record such as a user message, a tool step, a tool result, or the end of a message.
// VryxCode's review view, like Cursor's (feature flag vryxcode_review; web/js/ide.js and code.js): looking around is a quiet grey line, a change
// is a file chip with its +/- lines that opens to show the change, each message ends with the files it changed, and the sessions list is
// grouped Working / Ready for review / Done. Worked out here from the session's events, so the screen only draws it (and it is tested).

/** The names of the tools that only look at things (read, list, search) and never change anything: each is shown as one quiet grey line */
val QUIET_TOOLS = setOf("read_file", "list_files", "glob", "grep", "diagnostics", "command_output", "project_map", "search_project", "code_search", "lookup_docs", "memory")

// Maps a tool's internal name to the past-tense word shown for it in the feed ("Wrote", "Ran" ...). Tools not listed use their own name.
private val DONE_VERB = mapOf("read_file" to "Read", "write_file" to "Wrote", "edit_file" to "Edited", "run" to "Ran", "list_files" to "Looked around",
                              "git" to "Git", "diagnostics" to "Checked", "github" to "GitHub")

/**
 * Splits a tool step into a verb and the thing it worked on, for example "Wrote" + "main.py".
 * [preview] is the step's preview text from the server (only its first line is used); [tool] is the tool's internal name.
 * Returns (verb, argument). Mirrors toolParts in the website's web/js/ide.js so both apps show the same words.
 */
fun toolParts(preview: String, tool: String): Pair<String, String> {
    // Only the first line of the preview describes the step; later lines can be a diff or output.
    val first = preview.substringBefore('\n')
    // A regex is a text pattern. "^write (\\S+)" means: starts with "write ", then one or more non-space characters (captured as group 1, the file name).
    // find() returns null when there is no match; ?.let { } runs its block only when there was a match, and `return` then leaves the function early.
    Regex("^write (\\S+)").find(first)?.let { return (DONE_VERB["write_file"] ?: "Wrote") to it.groupValues[1] }
    Regex("^edit (\\S+)").find(first)?.let { return (DONE_VERB["edit_file"] ?: "Edited") to it.groupValues[1] }
    // Tools that show their input as JSON, like: read_file {"path": "a.py"}. This pattern captures the tool name (group 1) and the value of the first
    // "path", "command", "args" or "action" key (group 2). \w is a letter/digit/underscore, .* is "anything", [^"]* is "any characters up to the next quote" (the doubled backslashes above are just Kotlin string escaping).
    Regex("^(\\w+) \\{.*\"(?:path|command|args|action)\"\\s*:\\s*\"([^\"]*)\"").find(first)?.let {
        // Use the friendly past-tense verb if we know one, else the tool's own name.
        return (DONE_VERB[it.groupValues[1]] ?: it.groupValues[1]) to it.groupValues[2]
    }
    // Fallback: the tool's verb plus the first line of the preview, cut to 90 characters (with "..." added) so one line never gets huge.
    return (DONE_VERB[tool] ?: tool) to (if (first.length > 90) first.take(90) + "..." else first)
}

/**
 * One line of a change shown in a diff (a diff is a list of what was added or removed).
 * [text] is the line's content; [kind] is '+' for added, '-' for taken away, or ' ' for a header or unchanged line.
 */
data class DiffLine(val text: String, val kind: Char)

/**
 * Splits a step's preview into diff lines. The first line of the preview is the title ("edit file.py"), so it is dropped.
 * Returns one DiffLine per remaining line, with its kind worked out from a leading "+ " or "- ".
 */
fun diffLines(preview: String): List<DiffLine> = preview.split('\n').drop(1).map { l ->
    // Looks for optional spaces, then a "+" or "-", then one space at the start of the line (group 2 is the sign).
    val m = Regex("^(\\s*)([+-]) ").find(l)
    // If it matched: keep the sign, a single space, and the text after the matched prefix (range.last + 1 is the first character after it). Otherwise it is a plain line.
    if (m != null) DiffLine(m.groupValues[2] + " " + l.substring(m.range.last + 1), m.groupValues[2][0]) else DiffLine(l, ' ')
}

/**
 * Everything the review feed can show, in order. A sealed interface means these few types are the only ones allowed,
 * so the screen can handle every case with a `when` and the compiler checks none is missing.
 */
sealed interface ReviewItem {
    /** A quiet grey line such as "Read app/page.tsx" or "Thought 4s". [bad] is true when the step went wrong, and [why] holds the first line of the reason */
    data class Quiet(val text: String, val bad: Boolean = false, val why: String = "") : ReviewItem
    /** A changed file: its [path], how many lines were added ([add]) and taken away ([del]), the [diff] lines to show when opened, and [bad]/[why] if the change failed */
    data class File(val path: String, val add: Int, val del: Int, val diff: List<DiffLine>, val bad: Boolean = false, val why: String = "") : ReviewItem
    /** The end of a message: every file it changed, as (path, lines added, lines removed), with the totals */
    data class Done(val files: List<Triple<String, Int, Int>>) : ReviewItem {
        // Total lines added and removed across all files (sumOf adds up one number per file; second and third are the Triple's 2nd and 3rd values).
        val add get() = files.sumOf { it.second }
        val del get() = files.sumOf { it.third }
    }
    /** Quiet lines in a row, folded into one line that opens on a tap (flag vryxcode_lines, CodeParity.kt foldQuiet) */
    data class Group(val lines: List<Quiet>) : ReviewItem
    /** Anything else, drawn as it always was (your message, a long step, the summary, a question ...). Holds the raw event */
    data class Event(val e: JsonObject) : ReviewItem
}


// Regex for a tool result that means failure: a line starting with "error", the words "exit code" followed by a non-zero digit,
// a Python "Traceback", or "FAILED". MULTILINE makes ^ match at the start of every line, not just the start of the text.
private val BAD = Regex("^error|exit code [1-9]|Traceback|FAILED", RegexOption.MULTILINE)

/**
 * Builds the review feed from the session's events.
 * [events] are the raw events in the order they happened. Returns the items to draw, in order.
 * Quiet lines and file chips wait for the result event that follows them and take in whether it failed; when a message
 * finishes, a Done item lists the files it changed. It exists so the screen does not have to understand the event format.
 */
fun reviewItems(events: List<JsonObject>): List<ReviewItem> {
    // The list we build up and finally return.
    val out = mutableListOf<ReviewItem>()
    var turn = linkedMapOf<String, Pair<Int, Int>>()                     // the files this message changed (only the steps that went through)
    var last: Int = -1                                                  // the quiet line or chip waiting for its result
    // Walk through every event once, in order.
    for (e in events) {
        val kind = e.str("kind")
        // A new message starts: forget the files counted for the previous one.
        if (kind == "start" || kind == "user") turn = linkedMapOf()
        // A "step" event is VryxCode using a tool.
        if (kind == "step") {
            val tool = e.str("tool")
            // Skip steps with no tool, and the "todo" (plan) and "finish" tools: those are drawn another way as plain events further down.
            if (tool.isNotEmpty() && tool != "todo" && tool != "finish") {
                // Destructuring: split the returned pair into verb and arg.
                val (verb, arg) = toolParts(e.str("preview"), tool)
                // If the step took 2 seconds or more, first add a "Thought Ns" line (rounded) to show the model was thinking.
                if (e.num("secs") >= 2) out += ReviewItem.Quiet("Thought ${Math.round(e.num("secs"))}s")
                // Looking-only tools become a quiet line; remember its position in `last` so the next result event can mark it.
                if (tool in QUIET_TOOLS) {
                    out += ReviewItem.Quiet("$verb $arg".trim()); last = out.lastIndex; continue
                }
                // Writing or editing a file becomes a file chip carrying the lines added/removed and the diff.
                if (tool == "write_file" || tool == "edit_file") {
                    out += ReviewItem.File(arg, e.int("add"), e.int("del"), diffLines(e.str("preview"))); last = out.lastIndex; continue
                }
            }
        }
        if (kind == "result" && last >= 0) {                            // no output line under a quiet line or a chip, only a mark when it went wrong
            // Result events carry the tool's output text; decide from it whether the step failed.
            val t = e.str("text")
            val bad = BAD.containsMatchIn(t)
            // Look at what is waiting at position `last`; `it` is just a name for that item here (the `when` picks by its type).
            when (val it = out[last]) {
                // Copy the quiet line with the failure mark; the reason is the first line of the output, at most 200 characters.
                is ReviewItem.Quiet -> out[last] = it.copy(bad = bad, why = if (bad) t.substringBefore('\n').take(200) else "")
                is ReviewItem.File -> {
                    // A file chip is marked the same way.
                    out[last] = it.copy(bad = bad, why = if (bad) t.substringBefore('\n').take(200) else "")
                    // Only a successful change counts toward this message's totals: add this file's lines to what is already counted for its path (starting from 0 and 0).
                    if (!bad) turn[it.path] = (turn[it.path] ?: (0 to 0)).let { (a, d) -> (a + it.add) to (d + it.del) }
                }
                else -> Unit
            }
            // The waiting item has its result now. The result event itself is not drawn (continue skips to the next event).
            last = -1
            continue
        }
        // Any other event means nothing is waiting for a result any more.
        last = -1
        // The message ended and finished: add a Done summary of the changed files first (it comes before the end event itself).
        if (kind == "end" && e.bool("finished") && turn.isNotEmpty()) {
            out += ReviewItem.Done(turn.map { (p, ad) -> Triple(p, ad.first, ad.second) })
        }
        // Everything else is kept as a plain event for the screen to draw as before.
        out += ReviewItem.Event(e)
    }
    return out
}

/**
 * Groups the sessions list for the home screen.
 * [sessions] are the session rows; [seen] maps a session id to the "updated" time when the user last opened it.
 * Returns (title, sessions) pairs, leaving out empty groups: WORKING (still busy or waiting), READY FOR REVIEW (done with
 * changes the user has not opened since), and DONE (everything else). Mirrors renderHome in web/js/code.js.
 */
fun sessionGroups(sessions: List<CodeSessionRow>, seen: Map<String, Double>): List<Pair<String, List<CodeSessionRow>>> {
    // busy = the session is still starting, running, asking the user something, or queued.
    val busy = { s: CodeSessionRow -> s.state in setOf("starting", "working", "asking", "queued") }
    // ready = finished, changed something (lines added/removed or files), and its last update differs from the one the user last saw.
    val ready = { s: CodeSessionRow -> !busy(s) && s.state == "done" && (s.added > 0 || s.removed > 0 || s.files > 0) && seen[s.id] != s.updated }
    // Three groups in this order; DONE takes whatever is neither busy nor ready.
    return listOf("WORKING" to sessions.filter(busy), "READY FOR REVIEW" to sessions.filter(ready), "DONE" to sessions.filter { !busy(it) && !ready(it) })
        // Drop groups with no sessions so the screen shows no empty headings.
        .filter { it.second.isNotEmpty() }
}
