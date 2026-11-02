package app.emvryx.android

// Unit tests for small text helpers and the reply-stream reader, checking the app words things the same way the website does.
// Plain JVM tests: no phone needed.
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

/**
 * The lines the app writes the same way the website does (web/js/send.js, chat.js, core.js).
 * Covers: the "what the answer looked up" line, the timing line, the thinking clock and token counts,
 * reading a live reply stream (SSE, server-sent events), and grouping the chat list.
 */
class ChatMoreTest {
    @Test
    // Proves: the small line under an answer telling what it looked up (notes, Wikipedia, web, pictures) is worded correctly, or hidden.
    fun whatAnAnswerLookedUp() {
        // No lookup info at all: no line. Also no line when nothing was asked for (asked = false).
        assertNull(lookupText(null))
        assertNull(lookupText(LookupNotes(asked = false, wiki = 2)))
        // Different mixes of sources give different wording: Wikipedia + web, saved notes + Wikipedia, pictures only, and a search that found nothing.
        assertEquals("Read 2 notes from Wikipedia and searched the web: 1 source", lookupText(LookupNotes(asked = true, wiki = 2, web = 1)))
        assertEquals("Read 1 saved note and 3 from Wikipedia", lookupText(LookupNotes(asked = true, saved = 1, wiki = 3)))
        assertEquals("Looked at 2 pictures", lookupText(LookupNotes(asked = true, pictures = 2)))
        assertEquals("Searched, but found nothing useful.", lookupText(LookupNotes(asked = true, webTried = true)))
        // If only Wikipedia was searched (not the whole web), the line says so; contains() checks for that phrase inside the text.
        assertTrue(lookupText(LookupNotes(asked = true, wiki = 1, webSource = "wikipedia"))!!.contains("Only Wikipedia was searched"))
    }

    @Test
    // Proves: the owner-only timing line shows total time, model load time and time to the first word, and notes when the model thought first.
    fun theOwnersTimingLine() {
        // Under 10 seconds keeps one decimal (9.8s); 12.3 is shown as a whole number (12s). Missing parts are left out.
        assertEquals("⏱ 9.8s in all · loading the model 2.1s · first word at 6.1s", timingText(Timing(total = 9.8, load = 2.1, firstWord = 6.1)))
        assertEquals("⏱ 12s in all · first word at 0.4s · thought first (Deep)", timingText(Timing(total = 12.3, firstWord = 0.4, thought = true)))
    }

    @Test
    // Proves: the thinking timer text (clockText) and the short token counts (kTok, K = thousand) are formatted nicely.
    fun theThinkingClockAndTokenCounts() {
        // Zero seconds shows nothing; seconds under a minute show as "12s"; longer shows minutes and zero-padded seconds ("1m 05s").
        assertEquals("", clockText(0))
        assertEquals("12s", clockText(12))
        assertEquals("1m 05s", clockText(65))
        // Under 1000 stays a plain number; above, K is added with one decimal only if needed (1.2K, 8K, 128K).
        assertEquals("950", kTok(950))
        assertEquals("1.2K", kTok(1234))
        assertEquals("8K", kTok(8000))
        assertEquals("128K", kTok(128_000))
    }

    @Test
    // Proves: the parser turns the server's streamed reply lines ("event:" and "data:" lines) into the right event objects.
    fun theReplyStreamCarriesNotesMemoryAndTiming() {
        // A parser that is fed one line at a time and returns an event once it has seen a full one (ended by a blank line).
        val p = SseParser()
        // Helper: feed the three lines of one event (name, data, blank line) and return the single event the parser produced (mapNotNull drops the nulls from unfinished lines).
        fun one(event: String, data: String) = (listOf("event: $event", "data: $data", "")).mapNotNull { p.feed(it) }.single()
        // A "notes" event: what the answer looked up, with a list of sources.
        val notes = one("notes", """{"asked": true, "wiki": 2, "sources": [{"title": "Rainbow", "url": "https://en.wikipedia.org/wiki/Rainbow"}]}""")
        // "as" casts the event to its specific type so its fields can be read; the Wikipedia count must be 2.
        assertEquals(2, (notes as ReplyEvent.Notes).notes.wiki)
        // A "memory" event: facts saved about the user and a count of forgotten ones.
        val mem = one("memory", """{"saved": ["The user's name is Sam."], "forgot": 1}""")
        assertEquals(ReplyEvent.Memory(listOf("The user's name is Sam."), 1), mem)
        // The final "done" event: title, message id, timing numbers and the context-size meter.
        val done = one("done", """{"title": "T", "message_id": 3, "cut": false, "timing": {"total": 4.5, "first_word": 1.0}, "context": {"used": 10, "window": 8192, "pct": 0.1, "compact_at": 4992}}""")
        // Cast (so Kotlin knows it is a Done event); later lines then read its fields directly.
        done as ReplyEvent.Done
        // The third number (0.0) is how far apart two decimals may be and still count as equal. "!!" asserts the value is not null.
        assertEquals(4.5, done.timing!!.total, 0.0)
        assertEquals(8192L, done.context!!.window)
        // A "thinking" event: the effort level chosen automatically and why.
        val auto = one("thinking", """{"effort": "deep", "auto": true, "reason": "a hard question"}""")
        assertEquals(ReplyEvent.Thinking("deep", true, "a hard question"), auto)
    }

    @Test
    // Proves: the chat list is split into groups in the right order: pinned, folders, then date buckets, then skill (mode) groups.
    fun foldersAndSkillsHaveTheirOwnGroups() {
        // A fixed "today" so the test gives the same answer on any day.
        val today = LocalDate.of(2026, 10, 20)
        // Helper: the timestamp (seconds since 1970, as a decimal) for noon, the given number of days before today, in this computer's time zone.
        fun at(daysAgo: Long) = today.minusDays(daysAgo).atTime(12, 0).atZone(ZoneId.systemDefault()).toEpochSecond().toDouble()
        // Five chats: one today, one pinned (3 days old), one in folder Work, one using the teacher skill, and one 20 days old.
        val got = groups(listOf(
            ChatSummary(1, "a", at(0)), ChatSummary(2, "pinned", at(3), pinned = true), ChatSummary(3, "work", at(0), folder = "Work"),
            ChatSummary(4, "lesson", at(1), skill = "teacher"), ChatSummary(5, "old", at(20)),
        ), today)
        // Expected order of group titles. Pinned and folder groups come first, then Today and Older, with skill groups last.
        assertEquals(listOf("PINNED", "WORK", "TODAY", "OLDER", "TEACHER MODE"), got.map { it.first })
    }
}
