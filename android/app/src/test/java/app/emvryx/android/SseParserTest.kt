package app.emvryx.android

import app.emvryx.android.data.ReplyEvent
import app.emvryx.android.data.SseParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SseParserTest {
    private fun parse(text: String): List<ReplyEvent> {
        val p = SseParser()
        return (text.split('\n') + "").mapNotNull { p.feed(it) }
    }

    @Test
    fun aWholeReplyAsTheServerSendsIt() {
        // the exact shape of api_send in app/routes_chat.py
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
                ReplyEvent.Done("Greetings", 7, false),
            ),
            events,
        )
    }

    @Test
    fun anErrorPartWay() {
        val events = parse("event: error\ndata: {\"code\": \"timeout\", \"message\": \"The model took too long.\", \"action\": \"Try again.\", \"http\": 504}\n")
        assertEquals(listOf(ReplyEvent.Failed("timeout", "The model took too long.", "Try again.")), events)
    }

    @Test
    fun piecesKeepTheirSpacesAndNewlines() {
        val events = parse("event: piece\ndata: {\"t\": \"  two spaces\\nand a line\"}\n")
        assertEquals(listOf(ReplyEvent.Piece("  two spaces\nand a line")), events)
    }

    @Test
    fun keepAlivesAndBlankLinesAloneMakeNothing() {
        val p = SseParser()
        assertNull(p.feed(": keep-alive"))
        assertNull(p.feed(""))
        assertNull(p.feed(""))
    }

    @Test
    fun anUnknownEventIsPassedOnByName() {
        assertEquals(listOf(ReplyEvent.Other("memory")), parse("event: memory\ndata: {\"used\": 3}\n"))
    }
}
