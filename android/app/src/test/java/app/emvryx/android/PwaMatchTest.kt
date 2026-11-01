// Unit tests that check the Android app shows the same words and numbers as the website does (the website is also called a PWA, a web app
// that can be installed on a phone): model names with versions, the usage line, and the chat list grouped by day.
package app.emvryx.android

import app.emvryx.android.data.ChatSummary
import app.emvryx.android.data.ModelCard
import app.emvryx.android.data.Tank
import app.emvryx.android.data.Usage
import app.emvryx.android.data.Week
import app.emvryx.android.ui.groups
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

/** The words and numbers the app shows the same way the website does (web/js/chat.js, core.js) */
class PwaMatchTest {
    /** Proves a model's full name is its name plus its version, and the version is left off when it has none. */
    @Test
    fun modelNamesCarryTheirVersion() {
        assertEquals("Flare 2.5", ModelCard("flare-2.5", "Flare", version = 2.5).fullName)
        // a whole-number version (2.0) is shown without ".0"
        assertEquals("Solstice 2", ModelCard("solstice-2", "Solstice", version = 2.0).fullName)
        assertEquals("Apogee", ModelCard("apogee", "Apogee").fullName)
    }

    /** Proves the usage line text for each case: nearly full, full, middle, out, and owner. */
    @Test
    fun theUsageLine() {
        // the lower of "right now" and "this week", one decimal when nearly full (chat.js pctText)
        // tank 99.482 is the lower one; 99.5 is shown with one decimal because it is over 90
        assertEquals("Usage: 99.5% · about 397 messages left", Usage(canSend = 397, tank = Tank(99.482), week = Week(99.8964)).label)
        // exactly full shows as 100%, and 1200 gets a thousands comma
        assertEquals("Usage: 100% · about 1,200 messages left", Usage(canSend = 1200, tank = Tank(100.0), week = Week(100.0)).label)
        // below 90 percent it is a whole number (42.4 -> 42)
        assertEquals("Usage: 42% · about 80 messages left", Usage(canSend = 80, tank = Tank(42.4), week = Week(90.0)).label)
        // no messages can be sent: "out for now"
        assertEquals("Usage: out for now", Usage(canSend = 0).label)
        assertEquals("Usage: no limit (owner)", Usage(exempt = true).label)
    }

    /** Proves the chat list is split under TODAY, YESTERDAY, PREVIOUS 7 DAYS and OLDER headings, by how long ago each chat was updated. */
    @Test
    fun chatsAreGroupedByDay() {
        // A fixed "today" keeps the test the same on any date.
        val today = LocalDate.of(2026, 10, 18)
        // Helper: the time (in seconds since 1970, as the server sends it) of noon, this many days before today, in the computer's time zone.
        fun at(daysAgo: Long) = today.minusDays(daysAgo).atTime(12, 0).atZone(ZoneId.systemDefault()).toEpochSecond().toDouble()
        // Four chats: today, 1 day ago, 4 days ago, and 30 days ago.
        val got = groups(listOf(ChatSummary(1, "a", at(0)), ChatSummary(2, "b", at(1)), ChatSummary(3, "c", at(4)), ChatSummary(4, "d", at(30))), today)
        assertEquals(listOf("TODAY", "YESTERDAY", "PREVIOUS 7 DAYS", "OLDER"), got.map { it.first })
    }
}
