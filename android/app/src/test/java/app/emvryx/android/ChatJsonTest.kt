package app.emvryx.android

import app.emvryx.android.data.Chat
import app.emvryx.android.data.ChatSummary
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Replies exactly as the server sends them, so a field the app reads the wrong way shows up here and not as "Something went wrong" */
class ChatJsonTest {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    @Test
    fun aSavedChatOpens() {
        // GET /api/chats/5 from the demo server: "pinned" is a number here (app_engine.meta), and a message's ctx is filled in
        val c = json.decodeFromString<Chat>(
            """
            {"id": 5, "title": "Explain how rainbows form", "private": false, "skill": "",
             "messages": [
               {"id": 9, "role": "user", "content": "Explain how rainbows form", "model_id": "", "status": "done", "cut": false, "fb": "", "ctx": null, "docs": []},
               {"id": 10, "role": "assistant", "content": "Demo mode: ...", "model_id": "flare-2.5", "status": "done", "cut": false, "fb": "",
                "ctx": {"used": 166, "window": 8192, "pct": 2.0, "compact_at": 4992}, "docs": []}],
             "ctx": null, "pinned": 0, "folder": "", "generating": false, "docs": []}
            """.trimIndent(),
        )
        assertEquals(2, c.messages.size)
        assertFalse(c.pinned)
        assertEquals(166L, c.messages[1].ctx?.used)
    }

    @Test
    fun pinnedAsNumberOrTrueFalse() {
        assertTrue(json.decodeFromString<Chat>("""{"id": 1, "pinned": 1}""").pinned)
        assertTrue(json.decodeFromString<ChatSummary>("""{"id": 1, "pinned": true}""").pinned)
        assertFalse(json.decodeFromString<ChatSummary>("""{"id": 1, "pinned": false}""").pinned)
    }
}
