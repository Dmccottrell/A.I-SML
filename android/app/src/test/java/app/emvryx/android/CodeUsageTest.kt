package app.emvryx.android

import app.emvryx.android.data.CodeUsage
import app.emvryx.android.ui.liveText
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

class CodeUsageTest {
    @Test
    fun theUsageLineAsTheWebsiteWritesIt() {
        // the shape of app/routes_code.py _code_usage
        val u = Json { ignoreUnknownKeys = true }.decodeFromString<CodeUsage>(
            """{"status": "ok", "exempt": false, "tank_pct": 87, "week_pct": 95, "steps_left": 1234, "plan": "pro"}""")
        assertEquals("Pro · 87% left · about 1,234 coding steps", u.label)
        assertEquals("Owner: no limits", CodeUsage(exempt = true).label)
    }

    @Test
    fun theLiveLineHasTheSecondsAndTokens() {
        val l = Json.decodeFromString<JsonObject>(
            """{"phase": "calling", "secs": 12.4, "tokens": 1534, "text": "", "tool": "write_file", "target": "templates/index.html\nmore"}""")
        assertEquals("Calling · write_file · templates/index.html · 12s · 1,534 tokens", liveText(l))
        val running = Json.decodeFromString<JsonObject>("""{"phase": "running", "secs": 3, "tokens": 0, "tool": "run", "target": "pytest"}""")
        assertEquals("Running · run · pytest · 3s", liveText(running))
    }
}
