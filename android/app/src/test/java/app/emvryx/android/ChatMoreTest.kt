package app.emvryx.android

import app.emvryx.android.data.ChatSummary
import app.emvryx.android.data.LookupNotes
import app.emvryx.android.data.ReplyEvent
import app.emvryx.android.data.SseParser
import app.emvryx.android.data.Timing
import app.emvryx.android.ui.clockText
import app.emvryx.android.ui.groups
import app.emvryx.android.ui.kTok
import app.emvryx.android.ui.lookupText
import app.emvryx.android.ui.timingText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

/** The lines the app writes the same way the website does (web/js/send.js, chat.js, core.js) */
class ChatMoreTest {
    @Test
    fun whatAnAnswerLookedUp() {
        assertNull(lookupText(null))
        assertNull(lookupText(LookupNotes(asked = false, wiki = 2)))
        assertEquals("Read 2 notes from Wikipedia and searched the web: 1 source", lookupText(LookupNotes(asked = true, wiki = 2, web = 1)))
        assertEquals("Read 1 saved note and 3 from Wikipedia", lookupText(LookupNotes(asked = true, saved = 1, wiki = 3)))
        assertEquals("Looked at 2 pictures", lookupText(LookupNotes(asked = true, pictures = 2)))
        assertEquals("Searched, but found nothing useful.", lookupText(LookupNotes(asked = true, webTried = true)))
        assertTrue(lookupText(LookupNotes(asked = true, wiki = 1, webSource = "wikipedia"))!!.contains("Only Wikipedia was searched"))
    }

    @Test
    fun theOwnersTimingLine() {
        assertEquals("⏱ 9.8s in all · loading the model 2.1s · first word at 6.1s", timingText(Timing(total = 9.8, load = 2.1, firstWord = 6.1)))
        assertEquals("⏱ 12s in all · first word at 0.4s · thought first (Deep)", timingText(Timing(total = 12.3, firstWord = 0.4, thought = true)))
    }

    @Test
    fun theThinkingClockAndTokenCounts() {
        assertEquals("", clockText(0))
        assertEquals("12s", clockText(12))
        assertEquals("1m 05s", clockText(65))
        assertEquals("950", kTok(950))
        assertEquals("1.2K", kTok(1234))
        assertEquals("8K", kTok(8000))
        assertEquals("128K", kTok(128_000))
    }

    @Test
    fun theReplyStreamCarriesNotesMemoryAndTiming() {
        val p = SseParser()
        fun one(event: String, data: String) = (listOf("event: $event", "data: $data", "")).mapNotNull { p.feed(it) }.single()
        val notes = one("notes", """{"asked": true, "wiki": 2, "sources": [{"title": "Rainbow", "url": "https://en.wikipedia.org/wiki/Rainbow"}]}""")
        assertEquals(2, (notes as ReplyEvent.Notes).notes.wiki)
        val mem = one("memory", """{"saved": ["The user's name is Sam."], "forgot": 1}""")
        assertEquals(ReplyEvent.Memory(listOf("The user's name is Sam."), 1), mem)
        val done = one("done", """{"title": "T", "message_id": 3, "cut": false, "timing": {"total": 4.5, "first_word": 1.0}, "context": {"used": 10, "window": 8192, "pct": 0.1, "compact_at": 4992}}""")
        done as ReplyEvent.Done
        assertEquals(4.5, done.timing!!.total, 0.0)
        assertEquals(8192L, done.context!!.window)
        val auto = one("thinking", """{"effort": "deep", "auto": true, "reason": "a hard question"}""")
        assertEquals(ReplyEvent.Thinking("deep", true, "a hard question"), auto)
    }

    @Test
    fun foldersAndSkillsHaveTheirOwnGroups() {
        val today = LocalDate.of(2026, 10, 20)
        fun at(daysAgo: Long) = today.minusDays(daysAgo).atTime(12, 0).atZone(ZoneId.systemDefault()).toEpochSecond().toDouble()
        val got = groups(listOf(
            ChatSummary(1, "a", at(0)), ChatSummary(2, "pinned", at(3), pinned = true), ChatSummary(3, "work", at(0), folder = "Work"),
            ChatSummary(4, "lesson", at(1), skill = "teacher"), ChatSummary(5, "old", at(20)),
        ), today)
        assertEquals(listOf("PINNED", "WORK", "TODAY", "OLDER", "TEACHER MODE"), got.map { it.first })
    }
}
