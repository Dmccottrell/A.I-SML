package app.emvryx.android

// Unit tests that decode chat JSON exactly as the server sends it, to catch fields the app would read the wrong way.
import app.emvryx.android.data.Chat
import app.emvryx.android.data.ChatSummary
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Replies exactly as the server sends them, so a field the app reads the wrong way shows up here and not as "Something went wrong" */
class ChatJsonTest {
    // Lenient settings: skip unknown fields, treat missing values as null, and replace values of the wrong type with defaults.
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    @Test
    // Proves: a whole saved chat (messages, context-size info, odd "pinned" number) decodes without error.
    fun aSavedChatOpens() {
        // GET /api/chats/5 from the demo server: "pinned" is a number here (app_engine.meta), and a message's ctx is filled in
        // Decode the sample reply; trimIndent() below removes the leading spaces of the raw string.
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
        // Both messages came through; pinned 0 reads as false; the second message's "used" token count is a Long (166L).
        assertEquals(2, c.messages.size)
        assertFalse(c.pinned)
        assertEquals(166L, c.messages[1].ctx?.used)
    }

    @Test
    // Proves: "pinned" is understood whether the server sends 1 (a number) or true/false.
    fun pinnedAsNumberOrTrueFalse() {
        assertTrue(json.decodeFromString<Chat>("""{"id": 1, "pinned": 1}""").pinned)
        assertTrue(json.decodeFromString<ChatSummary>("""{"id": 1, "pinned": true}""").pinned)
        assertFalse(json.decodeFromString<ChatSummary>("""{"id": 1, "pinned": false}""").pinned)
    }
}
