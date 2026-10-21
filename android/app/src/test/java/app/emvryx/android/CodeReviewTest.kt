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
    private fun ev(s: String): JsonObject = Json.parseToJsonElement(s).jsonObject

    @Test
    fun aStepsVerbAndPath() {
        assertEquals("Wrote" to "app/page.tsx", toolParts("write app/page.tsx (52 lines)\n+ export default", "write_file"))
        assertEquals("Edited" to "main.py", toolParts("edit main.py\n- a\n+ b", "edit_file"))
        assertEquals("Read" to "README.md", toolParts("read_file {\"path\": \"README.md\"}", "read_file"))
    }

    @Test
    fun lookingIsQuietChangesAreChipsAndAFinishedMessageListsItsFiles() {
        val items = reviewItems(listOf(
            ev("""{"kind": "start", "task": "Make a page"}"""),
            ev("""{"kind": "step", "tool": "read_file", "preview": "read_file {\"path\": \"README.md\"}", "secs": 3}"""),
            ev("""{"kind": "result", "text": "# Hello"}"""),
            ev("""{"kind": "step", "tool": "write_file", "preview": "write app/page.tsx (2 lines)\n+ a\n+ b", "add": 2, "del": 0}"""),
            ev("""{"kind": "result", "text": "ok"}"""),
            ev("""{"kind": "step", "tool": "edit_file", "preview": "edit app/x.py\n- a\n+ b", "add": 1, "del": 1}"""),
            ev("""{"kind": "result", "text": "error: no such text"}"""),
            ev("""{"kind": "end", "finished": true, "summary": "Done."}"""),
        ))
        assertTrue(items[0] is ReviewItem.Event)                                            // your message, as before
        assertEquals(ReviewItem.Quiet("Thought 3s"), items[1])
        assertEquals(ReviewItem.Quiet("Read README.md"), items[2])
        val chip = items[3] as ReviewItem.File
        assertEquals(Triple("app/page.tsx", 2, 0), Triple(chip.path, chip.add, chip.del))
        assertEquals(listOf('+', '+'), chip.diff.map { it.kind })
        val failed = items[4] as ReviewItem.File
        assertTrue(failed.bad && failed.why.startsWith("error"))
        val done = items[5] as ReviewItem.Done                                              // only the change that went through
        assertEquals(listOf(Triple("app/page.tsx", 2, 0)), done.files)
        assertTrue(items[6] is ReviewItem.Event)                                            // the summary card, as before
    }

    @Test
    fun sessionsAreGroupedAndOpeningOneTakesItOutOfReview() {
        val rows = listOf(
            CodeSessionRow("a", "busy", state = "working"),
            CodeSessionRow("b", "changed", state = "done", added = 10, removed = 2, updated = 5.0),
            CodeSessionRow("c", "nothing changed", state = "done"),
        )
        assertEquals(listOf("WORKING", "READY FOR REVIEW", "DONE"), sessionGroups(rows, emptyMap()).map { it.first })
        val afterOpening = sessionGroups(rows, mapOf("b" to 5.0))
        assertEquals(listOf("WORKING", "DONE"), afterOpening.map { it.first })
        assertEquals(listOf("b", "c"), afterOpening.last().second.map { it.id })
    }
}
