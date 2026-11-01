// Unit test for reading the app's state JSON (data/AppState): a model's welcome tour, its "What's new" scores and the list of tours the
// person has already seen. It checks the phone reads this JSON the same way the website does, including values that are null.
package app.emvryx.android

import app.emvryx.android.data.AppState
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** A model's welcome tour, its What's new numbers (some still being measured) and the tours already seen read the way the website reads them. */
class ModelTourJsonTest {
    // Reader settings used by the app: ignore fields it does not know, allow missing nulls, and use defaults for bad values.
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    /** Proves one state reply is read into the right fields: tours seen, a feature switch, a model card with its tour and score table. */
    @Test
    fun tourWhatsNewAndSeenList() {
        // The setup: a small copy of what the server sends. It has the settings (tours already seen), one feature switch that is on,
        // and one model card with a one-step tour and a "what's new" table. The last score is null: that number is still being measured.
        val s = json.decodeFromString<AppState>(
            """{"user":"owner","settings":{"model_tours_seen":["flare-3"],"vryx_tour_seen":1},"features":{"model_tours":true},
              "models":{"cards":[{"id":"solstice-3","name":"Solstice","version":3,"state":"ready","preview":true,"vryxcode":true,"context_tested":262144,
                "tour":[{"art":"memory","title":"Remembers whole conversations","text":"256K tokens."}],
                "whats_new":{"vs":"solstice-2","points":["a"],"scores":[["Common sense (HellaSwag)","73.6%","75.3%"],["Thinking test","not measured",null]]}}]}}""",
        )
        val c = s.models.cards.single()                      // single() fails the test unless there is exactly one card
        assertTrue(s.on("model_tours"))
        assertEquals(listOf("flare-3"), s.settings.modelToursSeen)
        assertEquals(1, s.settings.vryxTourSeen)
        assertEquals("memory", c.tour.single().art)
        assertEquals(262144L, c.contextTested)
        assertTrue(c.preview && c.vryxcode)
        assertEquals("solstice-2", c.whatsNew?.vs)
        // the JSON null in the second score row is kept as null, not turned into a word or zero
        assertNull(c.whatsNew!!.scores[1][2])
    }
}
