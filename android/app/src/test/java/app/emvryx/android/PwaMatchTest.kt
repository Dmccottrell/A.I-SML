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
    @Test
    fun modelNamesCarryTheirVersion() {
        assertEquals("Flare 2.5", ModelCard("flare-2.5", "Flare", version = 2.5).fullName)
        assertEquals("Solstice 2", ModelCard("solstice-2", "Solstice", version = 2.0).fullName)
        assertEquals("Apogee", ModelCard("apogee", "Apogee").fullName)
    }

    @Test
    fun theUsageLine() {
        // the lower of "right now" and "this week", one decimal when nearly full (chat.js pctText)
        assertEquals("Usage: 99.5% · about 397 messages left", Usage(canSend = 397, tank = Tank(99.482), week = Week(99.8964)).label)
        assertEquals("Usage: 100% · about 1,200 messages left", Usage(canSend = 1200, tank = Tank(100.0), week = Week(100.0)).label)
        assertEquals("Usage: 42% · about 80 messages left", Usage(canSend = 80, tank = Tank(42.4), week = Week(90.0)).label)
        assertEquals("Usage: out for now", Usage(canSend = 0).label)
        assertEquals("Usage: no limit (owner)", Usage(exempt = true).label)
    }

    @Test
    fun chatsAreGroupedByDay() {
        val today = LocalDate.of(2026, 10, 18)
        fun at(daysAgo: Long) = today.minusDays(daysAgo).atTime(12, 0).atZone(ZoneId.systemDefault()).toEpochSecond().toDouble()
        val got = groups(listOf(ChatSummary(1, "a", at(0)), ChatSummary(2, "b", at(1)), ChatSummary(3, "c", at(4)), ChatSummary(4, "d", at(30))), today)
        assertEquals(listOf("TODAY", "YESTERDAY", "PREVIOUS 7 DAYS", "OLDER"), got.map { it.first })
    }
}
