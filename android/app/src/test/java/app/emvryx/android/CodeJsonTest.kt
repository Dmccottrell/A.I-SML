package app.emvryx.android

// Unit tests that decode sample server replies for the chat state, a saved chat and VryxCode (the coding agent) screens,
// so a field read the wrong way fails here instead of in the app. Plain JVM tests: no phone needed.
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
    // Lenient JSON settings: skip unknown fields, treat missing values as null, and use defaults for values of the wrong type.
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    @Test
    // Proves: the app-state reply gives feature switches, owner/admin roles and the "regenerate" options.
    fun stateCarriesFlagsRolesAndRegenerateOptions() {
        // Sample state reply; the unknown field "extra" must be ignored. (The triple-quoted text is a raw string holding the JSON.)
        val s = json.decodeFromString<AppState>("""{"user":"owner","owner":true,"admin":true,"features":{"context_meter":true,"whats_new":false},
            "regen_options":[{"id":"again","label":"Try again","blurb":"Same question"},{"id":"shorter","label":"Shorter"}],"extra":1}""")
        // on(name) is true for a switch that is true, false for one that is false, and false for one that is missing.
        assertTrue(s.on("context_meter"))
        assertFalse(s.on("whats_new"))
        assertFalse(s.on("not_a_flag"))
        // The regenerate options came through in order.
        assertEquals(listOf("again", "shorter"), s.regenOptions.map { it.id })
        // Both role flags are true.
        assertTrue(s.owner && s.admin)
    }

    @Test
    // Proves: a chat reply gives the context meter numbers, attached files (is each a picture?), cut-off flags and feedback tags.
    fun chatCarriesPicturesCutReportsAndTheMemoryRing() {
        // Sample chat: a context meter, two attached files (png and pdf), a user message with a picture, and a cut-off assistant message.
        val c = json.decodeFromString<Chat>("""{"id":4,"title":"t","ctx":{"used":1200,"window":32768,"pct":3.7,"compact_at":20000},
            "docs":[{"id":9,"name":"shot.png","kind":"png"},{"id":10,"name":"notes.pdf","kind":"pdf"}],
            "messages":[{"id":1,"role":"user","content":"(sent a picture)","docs":[{"id":9,"name":"shot.png","kind":"png"}]},
                        {"id":2,"role":"assistant","content":"x","cut":true,"fb":"too_long","ctx":null}]}""")
        // The percent (compared exactly, tolerance 0.0) and the "compact at" token count; "!!" says the value is not null.
        assertEquals(3.7, c.ctx!!.pct, 0.0)
        assertEquals(20000L, c.ctx!!.compactAt)
        // A png counts as a picture, a pdf does not.
        assertTrue(c.docs[0].picture)
        assertFalse(c.docs[1].picture)
        // The answer was cut short, its feedback tag was "too_long", and its own meter is null (missing).
        assertTrue(c.messages[1].cut)
        assertEquals("too_long", c.messages[1].fb)
        assertNull(c.messages[1].ctx)
        // The picture check ignores upper/lower case: JPG counts.
        assertTrue(DocInfo(1, "a.JPG", "JPG").picture)
    }

    @Test
    // Proves: VryxCode's start-up info (models, effort levels) and a poll of a running coding session decode correctly, including the loose JSON helpers int/str/bool/strings.
    fun vryxcodeInfoWithEffortAndASessionPoll() {
        // Sample start-up info: one model that is ready, one project, one place to run, and effort levels.
        val i = json.decodeFromString<CodeInfo>("""{"allowed":true,"models":[{"id":"solstice-3","name":"Solstice","label":"Solstice 3","state":"ready"}],
            "projects":["demo"],"environments":[{"id":"local","name":"This computer","available":true}],
            "effort":{"auto":"solstice-3","levels":[{"id":"quick","name":"Quick","note":"n"}]},"ci_watch":["demo"]}""")
        // The automatic effort model, and the model's "state" of ready means ready == true.
        assertEquals("solstice-3", i.effort!!.auto)
        assertTrue(i.models[0].ready)
        // Sample poll reply: the agent is asking the person a question, with a pending question and three events (a tool step, a user note, the end).
        val v = json.decodeFromString<CodeView>("""{"state":"asking","full":true,"pending":{"id":7,"tool":"ask_user","question":"Which?","options":["A","B"]},
            "events":[{"kind":"step","tool":"glob","preview":"glob **/*.py"},{"kind":"user","text":"use sqlite","steer":true},{"kind":"end","finished":true,"next":["Run it"]}]}""")
        // An "asking" state counts as working. The helpers int/strings/str/bool read a field of the loose event objects, whatever its JSON type.
        assertTrue(v.working && v.full)
        assertEquals(7, v.pending!!.int("id"))
        assertEquals(listOf("A", "B"), v.pending!!.strings("options"))
        assertEquals("glob", v.events[0].str("tool"))
        assertTrue(v.events[1].bool("steer"))
        assertEquals(listOf("Run it"), v.events[2].strings("next"))
        // (str on the number 7 gives "7".)
        assertEquals("7", v.pending!!.str("id"))                       // a number read as text matches an "answer" event's id
    }
}
