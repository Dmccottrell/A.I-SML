package app.emvryx.android

import app.emvryx.android.local.AppUpdate
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** "A new version of Emvryx is ready" (flag app_updates): the app compares the build it is with version.json next to the newest APK */
class AppUpdateTest {
    private val latest = AppUpdate.Latest(sha = "f9efd9afcea6edfd912da4a54c6252f35f965791", built = "2026-10-29T02:53:24Z")

    @Test
    fun aNewerBuildIsOffered() {
        assertTrue(AppUpdate.newer("1fb72885a084fb0a958853f565a43ffb31306047", latest, dismissed = ""))
    }

    @Test
    fun theSameBuildAHomeBuildOrOneSaidLaterToIsNot() {
        assertFalse(AppUpdate.newer(latest.sha, latest, dismissed = ""))
        assertFalse(AppUpdate.newer("", latest, dismissed = ""))                    // built on a computer, not by GitHub: it cannot tell
        assertFalse(AppUpdate.newer("1fb72885", null, dismissed = ""))               // no answer (no signal)
        assertFalse(AppUpdate.newer("1fb72885", latest, dismissed = latest.sha))    // Later on this one: not asked again until the next build
    }

    @Test
    fun theVersionFileIsRead() {
        // the release job in .github/workflows/android.yml writes it
        val j = Json { ignoreUnknownKeys = true }.decodeFromString<AppUpdate.Latest>("""{"sha": "abc123", "built": "2026-10-29T02:53:24Z", "extra": 1}""")
        assertEquals("abc123", j.sha)
        assertEquals(AppUpdate.APK_URL.substringBeforeLast('/') + "/version.json", AppUpdate.VERSION_URL)
    }
}
