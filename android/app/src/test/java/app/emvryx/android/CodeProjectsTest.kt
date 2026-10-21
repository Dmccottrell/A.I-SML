package app.emvryx.android

import app.emvryx.android.data.CodeSessionRow
import app.emvryx.android.ui.freeName
import app.emvryx.android.ui.ideaName
import app.emvryx.android.ui.projectGroups
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The projects organizer (flag vryxcode_projects) names and groups exactly as the website does (web/js/code.js; tests/test_vryxcode_projects.py) */
class CodeProjectsTest {
    @Test
    fun anIdeaBecomesAShortFolderName() {
        assertEquals("bill-splitter", ideaName("A bill splitter with tip and people"))
        assertEquals("pomodoro-timer", ideaName("Please can you build me a pomodoro timer, with sounds"))
        assertEquals("landing-page", ideaName("Make a landing page for my bakery"))
        assertEquals("new-project", ideaName("!!!"))
        assertEquals("one-two-three-four", ideaName("one two three four five six"))
    }

    @Test
    fun aTakenNameGetsANumber() {
        assertEquals("bill-splitter", freeName("bill-splitter", emptyList()))
        assertEquals("bill-splitter-3", freeName("bill-splitter", listOf("bill-splitter", "bill-splitter-2")))
    }

    @Test
    fun theMostRecentlyBusyProjectComesFirst() {
        val rows = listOf(CodeSessionRow("a", project = "site", updated = 5.0), CodeSessionRow("b", project = "game", updated = 9.0),
                          CodeSessionRow("c", project = "site", updated = 3.0))
        val groups = projectGroups(rows, listOf("site", "empty"))
        assertEquals(listOf("game", "site", "empty"), groups.map { it.first })
        assertEquals(listOf("a", "c"), groups[1].second.map { it.id })
    }

    @Test
    fun whatTheNotificationSays() {
        val done = CodeSessionRow("s", title = "Bill splitter", state = "done", added = 52, removed = 3, files = 2)
        assertEquals("Finished: Bill splitter", Alerts.sessionNews(done, "working")!!.first)
        assertEquals("+52 −3 · 2 files changed", Alerts.sessionNews(done, "working")!!.second)
        assertEquals("Needs you: Bill splitter", Alerts.sessionNews(done.copy(state = "asking"), "working")!!.first)
        assertEquals("Stopped: Bill splitter", Alerts.sessionNews(done.copy(state = "failed"), "working")!!.first)
        assertNull(Alerts.sessionNews(done.copy(state = "stopped"), "working"))        // stopped by the person: no news
        assertNull(Alerts.sessionNews(done, "done"))
    }
}
