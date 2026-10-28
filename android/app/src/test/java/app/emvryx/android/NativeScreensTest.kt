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
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    @Test
    fun memoryReads() {
        val m = json.decodeFromString<MemoryList>("""{"facts": [{"id": 3, "text": "Lives in Leeds", "created": 1761600000.5, "slot": "home"}], "on": false}""")
        assertEquals(1, m.facts.size)
        assertEquals("Lives in Leeds", m.facts[0].text)
        assertFalse(m.on)
    }

    @Test
    fun documentsRead() {
        val d = json.decodeFromString<DocList>("""{"documents": [{"id": 7, "name": "notes.pdf", "kind": "pdf", "chars": 12000, "created": 1761600000}], "max_mb": 20, "kinds": ["pdf"]}""")
        assertEquals(20, d.maxMb)
        assertEquals("notes.pdf", d.documents[0].name)
        assertEquals("2,000 words", docSize(d.documents[0].chars))
        assertEquals("", docSize(0))
    }

    @Test
    fun skillsRead() {
        // GET /api/skills: "for" and "try" are Kotlin words, so they are read into other names
        val s = json.decodeFromString<SkillList>("""{"skills": [{"id": "study", "name": "Study helper", "for": "Students", "icon": "book",
            "does": "Explains a school topic.", "try": "Explain fractions."}]}""").skills
        assertEquals("Students", s[0].forWho)
        assertEquals("Explain fractions.", s[0].tryThis)
    }

    @Test
    fun settingsRead() {
        val s = json.decodeFromString<SettingsData>("""{"window_mode": "long", "show_tokens": true, "web_search": "none", "memory": false,
            "thinking_pause": "off", "live_data": false, "connected_apps": false, "tour_seen": 3, "model_tours_seen": []}""")
        assertEquals("long", s.windowMode)
        assertEquals("none", s.webSearch)
        assertTrue(s.showTokens)
        assertEquals("", s.customInstructions)              // not set yet: the server leaves it out
    }

    @Test
    fun aPanelThatNeverOpensSaysSoInsteadOfABlackPage() {
        // the bug: after 8 s the cover lifted on a page whose website is hidden behind a panel that never opened, which is all black
        assertEquals(Cover.Waiting, coverAfter(up = true, panel = true, open = 0, waitedMs = 9_000))
        assertEquals(Cover.Failed, coverAfter(up = true, panel = true, open = 0, waitedMs = COVER_GIVE_UP_MS + 1))
        assertEquals(Cover.Failed, coverAfter(up = false, panel = false, open = 0, waitedMs = COVER_GIVE_UP_MS + 1))
        assertEquals(Cover.Ready, coverAfter(up = true, panel = true, open = 1, waitedMs = 500))
        assertEquals(Cover.Ready, coverAfter(up = true, panel = false, open = 0, waitedMs = 500))
    }
}
