// Unit tests (plain JVM tests, no phone needed) for the VryxCode "review" view of the Android app: how a coding session's events turn into
// quiet grey lines, file chips and "Done" summaries, and how the sessions list is grouped. The code under test is ui/CodeReview.kt.
package app.emvryx.android

import app.emvryx.android.data.CodeSessionRow
import app.emvryx.android.ui.ReviewItem
import app.emvryx.android.ui.reviewItems
import app.emvryx.android.ui.sessionGroups
import app.emvryx.android.ui.toolParts
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** VryxCode's review view (flag vryxcode_review) works out its lines the way web/js/ide.js and code.js do */
class CodeReviewTest {
    // Small helper: turns a JSON text into a JsonObject, so each test can write the events a session would send as plain text.
    private fun ev(s: String): JsonObject = Json.parseToJsonElement(s).jsonObject

    /**
     * Proves toolParts() splits a step's preview text into a past-tense verb ("Wrote") and the thing it worked on (a file path).
     * Three different preview shapes are tried: a write, an edit, and a read whose preview is a small JSON call.
     */
    @Test
    fun aStepsVerbAndPath() {
        // "write <path> (N lines)" -> verb "Wrote" and the path; the extra lines after the first are the diff and are ignored here
        assertEquals("Wrote" to "app/page.tsx", toolParts("write app/page.tsx (52 lines)\n+ export default", "write_file"))
        // "edit <path>" -> verb "Edited" and the path
        assertEquals("Edited" to "main.py", toolParts("edit main.py\n- a\n+ b", "edit_file"))
        // a tool call written as JSON ({"path": ...}): the path is pulled out of the JSON and read_file becomes "Read"
        assertEquals("Read" to "README.md", toolParts("read_file {\"path\": \"README.md\"}", "read_file"))
    }

    /**
     * Proves reviewItems() builds the feed from a whole session: looking around is quiet, a change is a file chip (with its +/- lines),
     * a failed change is marked bad, and a finished message ends with a Done line listing only the changes that went through.
     */
    @Test
    fun lookingIsQuietChangesAreChipsAndAFinishedMessageListsItsFiles() {
        // The setup: a pretend session, event by event, written as the server would send it. A "step" is something the agent does and the
        // "result" right after it is what came back. The JSON is in triple-quoted raw strings so the quotes inside need no escaping.
        val items = reviewItems(listOf(
            // the person's task begins the message
            ev("""{"kind": "start", "task": "Make a page"}"""),
            // a read that took 3 seconds (2 or more seconds adds a "Thought 3s" line first), followed by its result
            ev("""{"kind": "step", "tool": "read_file", "preview": "read_file {\"path\": \"README.md\"}", "secs": 3}"""),
            ev("""{"kind": "result", "text": "# Hello"}"""),
            // a successful write of 2 added lines
            ev("""{"kind": "step", "tool": "write_file", "preview": "write app/page.tsx (2 lines)\n+ a\n+ b", "add": 2, "del": 0}"""),
            ev("""{"kind": "result", "text": "ok"}"""),
            // an edit whose result starts with "error", so it must show as failed
            ev("""{"kind": "step", "tool": "edit_file", "preview": "edit app/x.py\n- a\n+ b", "add": 1, "del": 1}"""),
            ev("""{"kind": "result", "text": "error: no such text"}"""),
            // the message ends successfully with a summary
            ev("""{"kind": "end", "finished": true, "summary": "Done."}"""),
        ))
        assertTrue(items[0] is ReviewItem.Event)                                            // your message, as before
        // the 3 second step gives a "Thought 3s" line, then the read itself as a quiet line
        assertEquals(ReviewItem.Quiet("Thought 3s"), items[1])
        assertEquals(ReviewItem.Quiet("Read README.md"), items[2])
        // the write is a file chip carrying its path and counts, and its diff has two "+" lines
        val chip = items[3] as ReviewItem.File
        assertEquals(Triple("app/page.tsx", 2, 0), Triple(chip.path, chip.add, chip.del))
        assertEquals(listOf('+', '+'), chip.diff.map { it.kind })
        // the failed edit is flagged bad, with the first line of the error as the reason
        val failed = items[4] as ReviewItem.File
        assertTrue(failed.bad && failed.why.startsWith("error"))
        val done = items[5] as ReviewItem.Done                                              // only the change that went through
        assertEquals(listOf(Triple("app/page.tsx", 2, 0)), done.files)
        assertTrue(items[6] is ReviewItem.Event)                                            // the summary card, as before
    }

    /**
     * Proves sessionGroups() sorts the sessions list into WORKING / READY FOR REVIEW / DONE, and that opening a session
     * (remembering its "updated" time in the second argument) moves it out of "ready for review".
     */
    @Test
    fun sessionsAreGroupedAndOpeningOneTakesItOutOfReview() {
        // The setup: three sessions. "a" is still working; "b" is done and changed lines of code; "c" is done and changed nothing.
        val rows = listOf(
            CodeSessionRow("a", "busy", state = "working"),
            CodeSessionRow("b", "changed", state = "done", added = 10, removed = 2, updated = 5.0),
            CodeSessionRow("c", "nothing changed", state = "done"),
        )
        // Nothing opened yet (empty map): b has changes nobody has looked at, so it is "ready for review"
        assertEquals(listOf("WORKING", "READY FOR REVIEW", "DONE"), sessionGroups(rows, emptyMap()).map { it.first })
        // The person opened b when its "updated" time was 5.0, so it is no longer new and drops into DONE (the empty group disappears)
        val afterOpening = sessionGroups(rows, mapOf("b" to 5.0))
        assertEquals(listOf("WORKING", "DONE"), afterOpening.map { it.first })
        assertEquals(listOf("b", "c"), afterOpening.last().second.map { it.id })
    }
}
