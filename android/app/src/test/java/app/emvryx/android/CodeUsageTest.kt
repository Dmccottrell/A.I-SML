// Unit tests for the two short text lines VryxCode shows in the Android app: the usage line ("Pro · 87% left ...", data/Code.kt CodeUsage.label)
// and the live "what is it doing now" line under the newest step (ui/CodeViewModel.kt liveText). Both copy what the website prints.
package app.emvryx.android

import app.emvryx.android.data.CodeUsage
import app.emvryx.android.ui.liveText
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** Tests the wording of VryxCode's usage line and live status line. */
class CodeUsageTest {
    /**
     * Proves the usage JSON the server sends is read into a CodeUsage and shown as one readable line, and that the owner (exempt) sees
     * "Owner: no limits" instead.
     */
    @Test
    fun theUsageLineAsTheWebsiteWritesIt() {
        // the shape of app/routes_code.py _code_usage
        // ignoreUnknownKeys = true lets the JSON carry fields CodeUsage does not know (here "status" and "week_pct") without an error
        val u = Json { ignoreUnknownKeys = true }.decodeFromString<CodeUsage>(
            """{"status": "ok", "exempt": false, "tank_pct": 87, "week_pct": 95, "steps_left": 1234, "plan": "pro"}""")
        // plan gets a capital letter, steps_left gets a thousands comma
        assertEquals("Pro · 87% left · about 1,234 coding steps", u.label)
        assertEquals("Owner: no limits", CodeUsage(exempt = true).label)
    }

    /**
     * Proves liveText() joins phase, tool, target, seconds and tokens with " · ", and leaves out the parts that are empty or zero.
     */
    @Test
    fun theLiveLineHasTheSecondsAndTokens() {
        // A "calling" phase with 12.4 seconds (shown as whole seconds, 12s) and 1534 tokens. The target has two lines and only the
        // first is kept, so "templates/index.html\nmore" shows as "templates/index.html".
        val l = Json.decodeFromString<JsonObject>(
            """{"phase": "calling", "secs": 12.4, "tokens": 1534, "text": "", "tool": "write_file", "target": "templates/index.html\nmore"}""")
        assertEquals("Calling · write_file · templates/index.html · 12s · 1,534 tokens", liveText(l))
        // With 0 tokens the tokens part is dropped, so the line ends at the seconds
        val running = Json.decodeFromString<JsonObject>("""{"phase": "running", "secs": 3, "tokens": 0, "tool": "run", "target": "pytest"}""")
        assertEquals("Running · run · pytest · 3s", liveText(running))
    }
}
