package app.emvryx.android

import app.emvryx.android.data.AppState
import app.emvryx.android.data.Chat
import app.emvryx.android.data.CodeInfo
import app.emvryx.android.data.CodeView
import app.emvryx.android.data.DocInfo
import app.emvryx.android.data.bool
import app.emvryx.android.data.int
import app.emvryx.android.data.str
import app.emvryx.android.data.strings
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The server's replies for the new screens read the way the website reads them (app/routes_chat.py, app/routes_code.py). */
class CodeJsonTest {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    @Test
    fun stateCarriesFlagsRolesAndRegenerateOptions() {
        val s = json.decodeFromString<AppState>("""{"user":"owner","owner":true,"admin":true,"features":{"context_meter":true,"whats_new":false},
            "regen_options":[{"id":"again","label":"Try again","blurb":"Same question"},{"id":"shorter","label":"Shorter"}],"extra":1}""")
        assertTrue(s.on("context_meter"))
        assertFalse(s.on("whats_new"))
        assertFalse(s.on("not_a_flag"))
        assertEquals(listOf("again", "shorter"), s.regenOptions.map { it.id })
        assertTrue(s.owner && s.admin)
    }

    @Test
    fun chatCarriesPicturesCutReportsAndTheMemoryRing() {
        val c = json.decodeFromString<Chat>("""{"id":4,"title":"t","ctx":{"used":1200,"window":32768,"pct":3.7,"compact_at":20000},
            "docs":[{"id":9,"name":"shot.png","kind":"png"},{"id":10,"name":"notes.pdf","kind":"pdf"}],
            "messages":[{"id":1,"role":"user","content":"(sent a picture)","docs":[{"id":9,"name":"shot.png","kind":"png"}]},
                        {"id":2,"role":"assistant","content":"x","cut":true,"fb":"too_long","ctx":null}]}""")
        assertEquals(3.7, c.ctx!!.pct, 0.0)
        assertEquals(20000L, c.ctx!!.compactAt)
        assertTrue(c.docs[0].picture)
        assertFalse(c.docs[1].picture)
        assertTrue(c.messages[1].cut)
        assertEquals("too_long", c.messages[1].fb)
        assertNull(c.messages[1].ctx)
        assertTrue(DocInfo(1, "a.JPG", "JPG").picture)
    }

    @Test
    fun vryxcodeInfoWithEffortAndASessionPoll() {
        val i = json.decodeFromString<CodeInfo>("""{"allowed":true,"models":[{"id":"solstice-3","name":"Solstice","label":"Solstice 3","state":"ready"}],
            "projects":["demo"],"environments":[{"id":"local","name":"This computer","available":true}],
            "effort":{"auto":"solstice-3","levels":[{"id":"quick","name":"Quick","note":"n"}]},"ci_watch":["demo"]}""")
        assertEquals("solstice-3", i.effort!!.auto)
        assertTrue(i.models[0].ready)
        val v = json.decodeFromString<CodeView>("""{"state":"asking","full":true,"pending":{"id":7,"tool":"ask_user","question":"Which?","options":["A","B"]},
            "events":[{"kind":"step","tool":"glob","preview":"glob **/*.py"},{"kind":"user","text":"use sqlite","steer":true},{"kind":"end","finished":true,"next":["Run it"]}]}""")
        assertTrue(v.working && v.full)
        assertEquals(7, v.pending!!.int("id"))
        assertEquals(listOf("A", "B"), v.pending!!.strings("options"))
        assertEquals("glob", v.events[0].str("tool"))
        assertTrue(v.events[1].bool("steer"))
        assertEquals(listOf("Run it"), v.events[2].strings("next"))
        assertEquals("7", v.pending!!.str("id"))                       // a number read as text matches an "answer" event's id
    }
}
