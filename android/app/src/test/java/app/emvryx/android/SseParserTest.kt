// Unit tests for data/Sse.kt (SseParser). The server streams a chat reply as "server-sent events" (SSE): plain text lines such as
// "event: piece" and "data: {json}", with a blank line ending each event. SseParser turns those lines into ReplyEvent objects the app can show.
package app.emvryx.android

import app.emvryx.android.data.ReplyEvent
import app.emvryx.android.data.SseParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Tests that SseParser reads streamed reply lines into the right events. */
class SseParserTest {
    // Helper: feeds a whole text to a new parser, one line at a time, and collects every event it produces.
    // An extra "" (blank line) is added at the end so the last event is closed, as a real stream would do.
    // mapNotNull drops the null answers (lines that do not finish an event).
    private fun parse(text: String): List<ReplyEvent> {
        val p = SseParser()
        return (text.split('\n') + "").mapNotNull { p.feed(it) }
    }

    /** Proves a full reply (thinking, a keep-alive, loading, two pieces, done) is read into the matching events in order. */
    @Test
    fun aWholeReplyAsTheServerSendsIt() {
        // the exact shape of api_send in app/routes_chat.py
        // trimIndent() removes the shared left spaces; the blank lines are the event separators; ": keep-alive" is a comment line to ignore
        val events = parse(
            """
            event: thinking
            data: {"min_first_s": 0.48, "effort": "balanced", "auto": false, "reason": "", "temperature": null}

            : keep-alive

            event: loading
            data: {"model": "solstice-2"}

            event: piece
            data: {"t": "Hello"}

            event: piece
            data: {"t": " there"}

            event: done
            data: {"reason": "stop", "message_id": 7, "title": "Greetings", "cut": false, "usage": {"plan": "pro"}}
            """.trimIndent(),
        )
        assertEquals(
            listOf(
                ReplyEvent.Thinking("balanced"),
                ReplyEvent.Loading("solstice-2"),
                ReplyEvent.Piece("Hello"),
                ReplyEvent.Piece(" there"),
                ReplyEvent.Done("Greetings", 7, false, usage = app.emvryx.android.data.Usage()),     // {"plan": "pro"}: the rest take their defaults
            ),
            events,
        )
    }

    /** Proves an "error" event becomes a Failed event carrying the code, the message and the suggested action. */
    @Test
    fun anErrorPartWay() {
        val events = parse("event: error\ndata: {\"code\": \"timeout\", \"message\": \"The model took too long.\", \"action\": \"Try again.\", \"http\": 504}\n")
        assertEquals(listOf(ReplyEvent.Failed("timeout", "The model took too long.", "Try again.")), events)
    }

    /** Proves the text of a piece keeps its leading spaces and a newline (JSON "\n" becomes a real line break), so streamed words join up correctly. */
    @Test
    fun piecesKeepTheirSpacesAndNewlines() {
        // in the Kotlin string "\\n" is a backslash and n, which the JSON reader turns into a real newline
        val events = parse("event: piece\ndata: {\"t\": \"  two spaces\\nand a line\"}\n")
        assertEquals(listOf(ReplyEvent.Piece("  two spaces\nand a line")), events)
    }

    /** Proves a comment line and blank lines on their own produce no event (null each time). */
    @Test
    fun keepAlivesAndBlankLinesAloneMakeNothing() {
        val p = SseParser()
        assertNull(p.feed(": keep-alive"))
        assertNull(p.feed(""))
        assertNull(p.feed(""))
    }

    /** Proves an event name the app does not know still comes through as Other(name), so new server events never crash the app. */
    @Test
    fun anUnknownEventIsPassedOnByName() {
        assertEquals(listOf(ReplyEvent.Other("something_new")), parse("event: something_new\ndata: {\"used\": 3}\n"))
    }

    /** Proves a Deep Research progress event is read into its step text and the "done of" counts (2 of 7). */
    @Test
    fun deepResearchStepsAreReadOneByOne() {
        // routes_chat.py emits these while Deep Research searches, before the report is written
        assertEquals(listOf(ReplyEvent.Research("Searching: tallest mountains", 2, 7)),
            parse("event: research\ndata: {\"step\": \"Searching: tallest mountains\", \"done\": 2, \"of\": 7}\n"))
    }
}
