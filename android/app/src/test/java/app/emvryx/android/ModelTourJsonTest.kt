package app.emvryx.android

import app.emvryx.android.data.AppState
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** A model's welcome tour, its What's new numbers (some still being measured) and the tours already seen read the way the website reads them. */
class ModelTourJsonTest {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    @Test
    fun tourWhatsNewAndSeenList() {
        val s = json.decodeFromString<AppState>(
            """{"user":"owner","settings":{"model_tours_seen":["flare-3"]},"features":{"model_tours":true},
              "models":{"cards":[{"id":"solstice-3","name":"Solstice","version":3,"state":"ready","preview":true,"vryxcode":true,"context_tested":262144,
                "tour":[{"art":"memory","title":"Remembers whole conversations","text":"256K tokens."}],
                "whats_new":{"vs":"solstice-2","points":["a"],"scores":[["Common sense (HellaSwag)","73.6%","75.3%"],["Thinking test","not measured",null]]}}]}}""",
        )
        val c = s.models.cards.single()
        assertTrue(s.on("model_tours"))
        assertEquals(listOf("flare-3"), s.settings.modelToursSeen)
        assertEquals("memory", c.tour.single().art)
        assertEquals(262144L, c.contextTested)
        assertTrue(c.preview && c.vryxcode)
        assertEquals("solstice-2", c.whatsNew?.vs)
        assertNull(c.whatsNew!!.scores[1][2])
    }
}
