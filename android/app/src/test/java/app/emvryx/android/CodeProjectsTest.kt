package app.emvryx.android

// Unit tests for the VryxCode projects organizer: turning an idea into a folder name, avoiding taken names, grouping sessions,
// and the notification wording. Plain JVM tests: no phone needed.
import app.emvryx.android.data.CodeSessionRow
import app.emvryx.android.ui.freeName
import app.emvryx.android.ui.ideaName
import app.emvryx.android.ui.projectGroups
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The projects organizer (flag vryxcode_projects) names and groups exactly as the website does (web/js/code.js; tests/test_vryxcode_projects.py).
 */
class CodeProjectsTest {
    @Test
    // Proves: a sentence describing an idea becomes a short lowercase dashed folder name (filler words dropped, at most four words), with a fallback.
    fun anIdeaBecomesAShortFolderName() {
        // Leading filler ("a", "please can you build me") is dropped and the text is cut at a stop word or mark ("with", "for", a comma); the rest is joined with dashes.
        assertEquals("bill-splitter", ideaName("A bill splitter with tip and people"))
        assertEquals("pomodoro-timer", ideaName("Please can you build me a pomodoro timer, with sounds"))
        assertEquals("landing-page", ideaName("Make a landing page for my bakery"))
        // Nothing usable left: a default name. And long ideas are cut to the first four words.
        assertEquals("new-project", ideaName("!!!"))
        assertEquals("one-two-three-four", ideaName("one two three four five six"))
    }

    @Test
    // Proves: if a folder name is already used, a number is added (-2, -3 ...) to make it free.
    fun aTakenNameGetsANumber() {
        // Nothing taken: the name is kept. Both the plain name and -2 taken: the next free is -3.
        assertEquals("bill-splitter", freeName("bill-splitter", emptyList()))
        assertEquals("bill-splitter-3", freeName("bill-splitter", listOf("bill-splitter", "bill-splitter-2")))
    }

    @Test
    // Proves: sessions are grouped by project, the project with the newest activity comes first, and empty known projects come last.
    fun theMostRecentlyBusyProjectComesFirst() {
        // Three sessions: two in project "site" (updated at 5.0 and 3.0) and one in "game" (updated at 9.0, the newest).
        val rows = listOf(CodeSessionRow("a", project = "site", updated = 5.0), CodeSessionRow("b", project = "game", updated = 9.0),
                          CodeSessionRow("c", project = "site", updated = 3.0))
        // Also pass the known project names; "empty" has no sessions yet.
        val groups = projectGroups(rows, listOf("site", "empty"))
        // Order: game (newest), site, then empty. Each group is a pair of (name, sessions).
        assertEquals(listOf("game", "site", "empty"), groups.map { it.first })
        // Inside "site" the newest session (a) comes before the older one (c).
        assertEquals(listOf("a", "c"), groups[1].second.map { it.id })
    }

    @Test
    // Proves: the phone notification (title, details) for a coding session that changed state, or no notification when there is no news.
    fun whatTheNotificationSays() {
        // A sample session that finished: 52 lines added, 3 removed, 2 files.
        val done = CodeSessionRow("s", title = "Bill splitter", state = "done", added = 52, removed = 3, files = 2)
        // The previous state was "working" and it is now "done": a Finished notice, with a +added/-removed summary as the second line.
        assertEquals("Finished: Bill splitter", Alerts.sessionNews(done, "working")!!.first)
        assertEquals("+52 −3 · 2 files changed", Alerts.sessionNews(done, "working")!!.second)
        // copy(state = ...) makes a changed copy of the sample. Asking means the agent needs the person; failed reads as Stopped.
        assertEquals("Needs you: Bill splitter", Alerts.sessionNews(done.copy(state = "asking"), "working")!!.first)
        assertEquals("Stopped: Bill splitter", Alerts.sessionNews(done.copy(state = "failed"), "working")!!.first)
        assertNull(Alerts.sessionNews(done.copy(state = "stopped"), "working"))        // stopped by the person: no news
        // The state did not change (done to done): nothing new to tell.
        assertNull(Alerts.sessionNews(done, "done"))
    }
}
