// Unit tests for the app's own (native) screens: Memory, Documents, Skills and Settings. They check the phone reads the server's JSON replies
// correctly (data/Native.kt), and that the "cover" shown over a website page gives up with an error instead of lifting onto a black page (ui/WebScreen.kt).
package app.emvryx.android

import app.emvryx.android.data.DocList
import app.emvryx.android.data.MemoryList
import app.emvryx.android.data.SettingsData
import app.emvryx.android.data.SkillList
import app.emvryx.android.data.docSize
import app.emvryx.android.ui.COVER_GIVE_UP_MS
import app.emvryx.android.ui.Cover
import app.emvryx.android.ui.coverAfter
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The app's own Memory, Documents, Skills and Settings screens (feature flag android_native) read the server's replies as it sends them */
class NativeScreensTest {
    // Reader settings used by the app: ignore fields it does not know, allow missing nulls, and use defaults for bad values.
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    /** Proves a Memory reply is read: one remembered fact with its text, and the switch that says memory is off. */
    @Test
    fun memoryReads() {
        val m = json.decodeFromString<MemoryList>("""{"facts": [{"id": 3, "text": "Lives in Leeds", "created": 1761600000.5, "slot": "home"}], "on": false}""")
        assertEquals(1, m.facts.size)
        assertEquals("Lives in Leeds", m.facts[0].text)
        assertFalse(m.on)
    }

    /** Proves a Documents reply is read, and that docSize() turns a character count into a rough word count (about 6 characters a word). */
    @Test
    fun documentsRead() {
        val d = json.decodeFromString<DocList>("""{"documents": [{"id": 7, "name": "notes.pdf", "kind": "pdf", "chars": 12000, "created": 1761600000}], "max_mb": 20, "kinds": ["pdf"]}""")
        assertEquals(20, d.maxMb)
        assertEquals("notes.pdf", d.documents[0].name)
        assertEquals("2,000 words", docSize(d.documents[0].chars))      // 12,000 characters / 6 = 2,000 words
        assertEquals("", docSize(0))                                    // an empty file shows no size
    }

    /** Proves a Skills reply is read, including the two JSON keys ("for", "try") that clash with Kotlin keywords. */
    @Test
    fun skillsRead() {
        // GET /api/skills: "for" and "try" are Kotlin words, so they are read into other names
        val s = json.decodeFromString<SkillList>("""{"skills": [{"id": "study", "name": "Study helper", "for": "Students", "icon": "book",
            "does": "Explains a school topic.", "try": "Explain fractions."}]}""").skills
        assertEquals("Students", s[0].forWho)
        assertEquals("Explain fractions.", s[0].tryThis)
    }

    /** Proves a Settings reply is read into its fields, and that a field the server leaves out falls back to its default. */
    @Test
    fun settingsRead() {
        val s = json.decodeFromString<SettingsData>("""{"window_mode": "long", "show_tokens": true, "web_search": "none", "memory": false,
            "thinking_pause": "off", "live_data": false, "connected_apps": false, "tour_seen": 3, "model_tours_seen": []}""")
        assertEquals("long", s.windowMode)
        assertEquals("none", s.webSearch)
        assertTrue(s.showTokens)
        assertEquals("", s.customInstructions)              // not set yet: the server leaves it out
    }

    /**
     * Proves coverAfter() decides when to lift, keep, or fail the cover over a website page. The cover is the loading screen over the
     * embedded web page; "panel" pages show the site inside a pop-up panel that has to open first.
     */
    @Test
    fun aPanelThatNeverOpensSaysSoInsteadOfABlackPage() {
        // the bug: after 8 s the cover lifted on a page whose website is hidden behind a panel that never opened, which is all black
        // page is up and wants a panel, but no panel is open and only 9 seconds have passed: keep waiting
        assertEquals(Cover.Waiting, coverAfter(up = true, panel = true, open = 0, waitedMs = 9_000))
        // still no panel after the give-up time: show the "did not open" error instead of a black page
        assertEquals(Cover.Failed, coverAfter(up = true, panel = true, open = 0, waitedMs = COVER_GIVE_UP_MS + 1))
        // the page itself never came up and time is over: also an error
        assertEquals(Cover.Failed, coverAfter(up = false, panel = false, open = 0, waitedMs = COVER_GIVE_UP_MS + 1))
        // page is up and its panel is open: lift the cover at once
        assertEquals(Cover.Ready, coverAfter(up = true, panel = true, open = 1, waitedMs = 500))
        // page is up and needs no panel: also ready
        assertEquals(Cover.Ready, coverAfter(up = true, panel = false, open = 0, waitedMs = 500))
    }
}
