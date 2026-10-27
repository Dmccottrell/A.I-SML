package app.emvryx.android

import app.emvryx.android.ui.EndState
import app.emvryx.android.ui.PlanStep
import app.emvryx.android.ui.ReviewItem
import app.emvryx.android.ui.endState
import app.emvryx.android.ui.foldQuiet
import app.emvryx.android.ui.groupTitle
import app.emvryx.android.ui.planSteps
import app.emvryx.android.ui.verdictOf
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The website's newer VryxCode parts for the Android app (flag android_vryxcode) work out what to show the way web/js/ide.js and code.js do */
class CodeParityTest {
    private fun ev(s: String): JsonObject = Json.parseToJsonElement(s).jsonObject

    @Test
    fun thePlanFromTheLastTodoStepWithTheStepItIsOn() {
        val events = listOf(
            ev("""{"kind": "step", "tool": "todo", "preview": "todo {\"items\": [{\"text\": \"old\", \"done\": false}]}"}"""),
            ev("""{"kind": "step", "tool": "todo", "preview": "todo {\"items\": [{\"text\": \"Write the page\", \"done\": true}, {\"text\": \"Add the buttons\", \"done\": false}, {\"text\": \"Test it\", \"done\": false}]}"}"""),
        )
        assertEquals(listOf(PlanStep("Write the page", "done"), PlanStep("Add the buttons", "now"), PlanStep("Test it", "todo")), planSteps(events, working = true))
        assertEquals(listOf("done", "todo", "todo"), planSteps(events, working = false).map { it.state })
        assertEquals(emptyList<PlanStep>(), planSteps(listOf(ev("""{"kind": "step", "tool": "todo", "preview": "todo {cut off"}""")), true))
    }

    @Test
    fun howAMessageEndedSaidPlainly() {
        assertEquals(EndState.Finished, endState(ev("""{"kind": "end", "finished": true}""")))
        assertEquals(EndState.OutOfSteps(5), endState(ev("""{"kind": "end", "finished": false, "reason": "steps", "rounds": 5}""")))
        assertEquals(EndState.Waiting, endState(ev("""{"kind": "end", "finished": false, "said": true}""")))
        assertNull(endState(ev("""{"kind": "end", "finished": false, "summary": "Stopped."}""")))
        assertNull(endState(ev("""{"kind": "user", "text": "hi"}""")))
    }

    @Test
    fun aReviewsVerdict() {
        val v = verdictOf(ev("""{"kind": "end", "verdict": {"status": "CHANGES", "blocking": 2, "nits": 1, "fix": "Fix these, test first"}}"""))!!
        assertEquals(false, v.approved)
        assertEquals(2, v.blocking)
        assertEquals("Fix these, test first", v.fix)
        assertTrue(verdictOf(ev("""{"kind": "end", "verdict": {"status": "APPROVED", "blocking": 0, "nits": 0}}"""))!!.approved)
        assertNull(verdictOf(ev("""{"kind": "end"}""")))
    }

    @Test
    fun quietLinesInARowFoldIntoOne() {
        val e = ReviewItem.Event(ev("""{"kind": "note"}"""))
        val folded = foldQuiet(listOf(ReviewItem.Quiet("Read a.py"), ReviewItem.Quiet("Read b.py"), ReviewItem.Quiet("Ran pytest"), e, ReviewItem.Quiet("Read c.py")))
        assertEquals(3, folded.size)
        val g = folded[0] as ReviewItem.Group
        assertEquals("Read 2 files, ran a command", groupTitle(g))
        assertEquals(e, folded[1])
        assertTrue(folded[2] is ReviewItem.Quiet)                       // one on its own stays a plain line
    }
}
