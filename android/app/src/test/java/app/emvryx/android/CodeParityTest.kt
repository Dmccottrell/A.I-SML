package app.emvryx.android

// Unit tests for the Android VryxCode screen's helper logic, which must decide what to show exactly like the website's JavaScript does.
// Events are small JSON objects sent by the coding agent; each test builds some by hand and checks the result.
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

/**
 * The website's newer VryxCode parts for the Android app (flag android_vryxcode) work out what to show the way web/js/ide.js and code.js do.
 * Covers: the plan checklist, how a message ended, a review's verdict, and folding quiet lines together.
 */
class CodeParityTest {
    // Helper: turn JSON text into a JSON object (an event) so tests can write events as plain strings.
    private fun ev(s: String): JsonObject = Json.parseToJsonElement(s).jsonObject

    @Test
    // Proves: the plan checklist comes from the LAST "todo" step, marking finished items done, the first unfinished one "now" (while working) and the rest "todo".
    fun thePlanFromTheLastTodoStepWithTheStepItIsOn() {
        // Two todo steps: an old plan and a newer one. Inside the strings, \" is an escaped quote because the plan is itself JSON text inside JSON.
        val events = listOf(
            ev("""{"kind": "step", "tool": "todo", "preview": "todo {\"items\": [{\"text\": \"old\", \"done\": false}]}"}"""),
            ev("""{"kind": "step", "tool": "todo", "preview": "todo {\"items\": [{\"text\": \"Write the page\", \"done\": true}, {\"text\": \"Add the buttons\", \"done\": false}, {\"text\": \"Test it\", \"done\": false}]}"}"""),
        )
        // Only the newer plan is used; "Add the buttons" is the step being worked on right now.
        assertEquals(listOf(PlanStep("Write the page", "done"), PlanStep("Add the buttons", "now"), PlanStep("Test it", "todo")), planSteps(events, working = true))
        // When the agent is no longer working, nothing is "now": unfinished steps are plain "todo".
        assertEquals(listOf("done", "todo", "todo"), planSteps(events, working = false).map { it.state })
        // A todo preview that was cut off (not valid JSON) gives an empty plan rather than a crash.
        assertEquals(emptyList<PlanStep>(), planSteps(listOf(ev("""{"kind": "step", "tool": "todo", "preview": "todo {cut off"}""")), true))
    }

    @Test
    // Proves: the final "end" event is turned into a clear state, or null when there is nothing special to say.
    fun howAMessageEndedSaidPlainly() {
        // Finished normally; ran out of steps (5 rounds); stopped but already said something (waiting for the person).
        assertEquals(EndState.Finished, endState(ev("""{"kind": "end", "finished": true}""")))
        assertEquals(EndState.OutOfSteps(5), endState(ev("""{"kind": "end", "finished": false, "reason": "steps", "rounds": 5}""")))
        assertEquals(EndState.Waiting, endState(ev("""{"kind": "end", "finished": false, "said": true}""")))
        // Not finished but with only a summary: no special state. An event that is not an "end" event also gives null.
        assertNull(endState(ev("""{"kind": "end", "finished": false, "summary": "Stopped."}""")))
        assertNull(endState(ev("""{"kind": "user", "text": "hi"}""")))
    }

    @Test
    // Proves: a code review's verdict (approved or not, blocking problems, nitpicks, fix advice) is read from the end event.
    fun aReviewsVerdict() {
        // "CHANGES" means changes are requested, so approved must be false; "!!" asserts the verdict was found (not null).
        val v = verdictOf(ev("""{"kind": "end", "verdict": {"status": "CHANGES", "blocking": 2, "nits": 1, "fix": "Fix these, test first"}}"""))!!
        assertEquals(false, v.approved)
        assertEquals(2, v.blocking)
        assertEquals("Fix these, test first", v.fix)
        // "APPROVED" gives approved = true; an end event with no verdict at all gives null.
        assertTrue(verdictOf(ev("""{"kind": "end", "verdict": {"status": "APPROVED", "blocking": 0, "nits": 0}}"""))!!.approved)
        assertNull(verdictOf(ev("""{"kind": "end"}""")))
    }

    @Test
    // Proves: several quiet one-line actions in a row (reading files, running a command) fold into one group with a summary title.
    fun quietLinesInARowFoldIntoOne() {
        // A normal event that sits in the middle and splits the quiet lines into two runs.
        val e = ReviewItem.Event(ev("""{"kind": "note"}"""))
        // Three quiet lines, then the event, then one more quiet line.
        val folded = foldQuiet(listOf(ReviewItem.Quiet("Read a.py"), ReviewItem.Quiet("Read b.py"), ReviewItem.Quiet("Ran pytest"), e, ReviewItem.Quiet("Read c.py")))
        // Result: one group (the first three), the event, and the last quiet line = 3 items.
        assertEquals(3, folded.size)
        val g = folded[0] as ReviewItem.Group
        // The group title counts what happened; the event is untouched.
        assertEquals("Read 2 files, ran a command", groupTitle(g))
        assertEquals(e, folded[1])
        assertTrue(folded[2] is ReviewItem.Quiet)                       // one on its own stays a plain line
    }
}
