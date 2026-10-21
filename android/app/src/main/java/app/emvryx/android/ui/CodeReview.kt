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

// VryxCode's review view, like Cursor's (feature flag vryxcode_review; web/js/ide.js and code.js): looking around is a quiet grey line, a change
// is a file chip with its +/- lines that opens to show the change, each message ends with the files it changed, and the sessions list is
// grouped Working / Ready for review / Done. Worked out here from the session's events, so the screen only draws it (and it is tested).

/** The tools that only look (read, list, search): a quiet line each */
val QUIET_TOOLS = setOf("read_file", "list_files", "glob", "grep", "diagnostics", "command_output", "project_map", "search_project", "code_search", "lookup_docs", "memory")

private val DONE_VERB = mapOf("read_file" to "Read", "write_file" to "Wrote", "edit_file" to "Edited", "run" to "Ran", "list_files" to "Looked around",
                              "git" to "Git", "diagnostics" to "Checked", "github" to "GitHub")

/** "Wrote" + "main.py": a step's verb and what it worked on, from the first line of its preview (ide.js toolParts) */
fun toolParts(preview: String, tool: String): Pair<String, String> {
    val first = preview.substringBefore('\n')
    Regex("^write (\\S+)").find(first)?.let { return (DONE_VERB["write_file"] ?: "Wrote") to it.groupValues[1] }
    Regex("^edit (\\S+)").find(first)?.let { return (DONE_VERB["edit_file"] ?: "Edited") to it.groupValues[1] }
    Regex("^(\\w+) \\{.*\"(?:path|command|args|action)\"\\s*:\\s*\"([^\"]*)\"").find(first)?.let {
        return (DONE_VERB[it.groupValues[1]] ?: it.groupValues[1]) to it.groupValues[2]
    }
    return (DONE_VERB[tool] ?: tool) to (if (first.length > 90) first.take(90) + "..." else first)
}

/** One line of a change: + added, - taken away, or a header */
data class DiffLine(val text: String, val kind: Char)

fun diffLines(preview: String): List<DiffLine> = preview.split('\n').drop(1).map { l ->
    val m = Regex("^(\\s*)([+-]) ").find(l)
    if (m != null) DiffLine(m.groupValues[2] + " " + l.substring(m.range.last + 1), m.groupValues[2][0]) else DiffLine(l, ' ')
}

/** What the review feed shows, in order */
sealed interface ReviewItem {
    /** "Read app/page.tsx", "Thought 4s": [bad] when the step went wrong, with the first line of why */
    data class Quiet(val text: String, val bad: Boolean = false, val why: String = "") : ReviewItem
    data class File(val path: String, val add: Int, val del: Int, val diff: List<DiffLine>, val bad: Boolean = false, val why: String = "") : ReviewItem
    /** The end of a message: every file it changed, with the totals */
    data class Done(val files: List<Triple<String, Int, Int>>) : ReviewItem {
        val add get() = files.sumOf { it.second }
        val del get() = files.sumOf { it.third }
    }
    /** Anything else, drawn as before (your message, a long step, the summary, a question ...) */
    data class Event(val e: JsonObject) : ReviewItem
}


private val BAD = Regex("^error|exit code [1-9]|Traceback|FAILED", RegexOption.MULTILINE)

/** The events of a session as the review feed: quiet lines and file chips take in the result after them; a finished message adds its Done line */
fun reviewItems(events: List<JsonObject>): List<ReviewItem> {
    val out = mutableListOf<ReviewItem>()
    var turn = linkedMapOf<String, Pair<Int, Int>>()                     // the files this message changed (only the steps that went through)
    var last: Int = -1                                                  // the quiet line or chip waiting for its result
    for (e in events) {
        val kind = e.str("kind")
        if (kind == "start" || kind == "user") turn = linkedMapOf()
        if (kind == "step") {
            val tool = e.str("tool")
            if (tool.isNotEmpty() && tool != "todo" && tool != "finish") {
                val (verb, arg) = toolParts(e.str("preview"), tool)
                if (e.num("secs") >= 2) out += ReviewItem.Quiet("Thought ${Math.round(e.num("secs"))}s")
                if (tool in QUIET_TOOLS) {
                    out += ReviewItem.Quiet("$verb $arg".trim()); last = out.lastIndex; continue
                }
                if (tool == "write_file" || tool == "edit_file") {
                    out += ReviewItem.File(arg, e.int("add"), e.int("del"), diffLines(e.str("preview"))); last = out.lastIndex; continue
                }
            }
        }
        if (kind == "result" && last >= 0) {                            // no output line under a quiet line or a chip, only a mark when it went wrong
            val t = e.str("text")
            val bad = BAD.containsMatchIn(t)
            when (val it = out[last]) {
                is ReviewItem.Quiet -> out[last] = it.copy(bad = bad, why = if (bad) t.substringBefore('\n').take(200) else "")
                is ReviewItem.File -> {
                    out[last] = it.copy(bad = bad, why = if (bad) t.substringBefore('\n').take(200) else "")
                    if (!bad) turn[it.path] = (turn[it.path] ?: (0 to 0)).let { (a, d) -> (a + it.add) to (d + it.del) }
                }
                else -> Unit
            }
            last = -1
            continue
        }
        last = -1
        if (kind == "end" && e.bool("finished") && turn.isNotEmpty()) {
            out += ReviewItem.Done(turn.map { (p, ad) -> Triple(p, ad.first, ad.second) })
        }
        out += ReviewItem.Event(e)
    }
    return out
}

/** The sessions list in groups: Working (and waiting), Ready for review (finished with changes not opened since), Done (code.js renderHome) */
fun sessionGroups(sessions: List<CodeSessionRow>, seen: Map<String, Double>): List<Pair<String, List<CodeSessionRow>>> {
    val busy = { s: CodeSessionRow -> s.state in setOf("starting", "working", "asking", "queued") }
    val ready = { s: CodeSessionRow -> !busy(s) && s.state == "done" && (s.added > 0 || s.removed > 0 || s.files > 0) && seen[s.id] != s.updated }
    return listOf("WORKING" to sessions.filter(busy), "READY FOR REVIEW" to sessions.filter(ready), "DONE" to sessions.filter { !busy(it) && !ready(it) })
        .filter { it.second.isNotEmpty() }
}
