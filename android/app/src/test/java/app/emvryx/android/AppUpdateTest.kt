package app.emvryx.android

// Unit tests for the "new version available" check. They need no phone: they only call the comparison logic and read sample JSON.
import app.emvryx.android.local.AppUpdate
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * "A new version of Emvryx is ready" (flag app_updates): the app compares the build it is with version.json next to the newest APK
 * (an APK is the installable Android app file). A build is identified by its git commit "sha" (a long fingerprint of the code).
 */
class AppUpdateTest {
    // The pretend "newest build" the server says exists: its commit fingerprint and when it was built.
    private val latest = AppUpdate.Latest(sha = "f9efd9afcea6edfd912da4a54c6252f35f965791", built = "2026-10-29T02:53:24Z")

    @Test
    // Proves: a phone running a different (older) build than the newest one is offered the update.
    fun aNewerBuildIsOffered() {
        // The installed sha differs from the newest one, and nothing was dismissed, so the answer is yes.
        assertTrue(AppUpdate.newer("1fb72885a084fb0a958853f565a43ffb31306047", latest, dismissed = ""))
    }

    @Test
    // Proves: the update is NOT offered when the build is already the newest, is unknown, there is no answer, or the person said Later.
    fun theSameBuildAHomeBuildOrOneSaidLaterToIsNot() {
        // Same build as the newest: nothing to update.
        assertFalse(AppUpdate.newer(latest.sha, latest, dismissed = ""))
        assertFalse(AppUpdate.newer("", latest, dismissed = ""))                    // built on a computer, not by GitHub: it cannot tell
        assertFalse(AppUpdate.newer("1fb72885", null, dismissed = ""))               // no answer (no signal)
        assertFalse(AppUpdate.newer("1fb72885", latest, dismissed = latest.sha))    // Later on this one: not asked again until the next build
    }

    @Test
    // Proves: the small version.json file is read correctly (extra fields ignored) and its web address sits next to the APK's.
    fun theVersionFileIsRead() {
        // the release job in .github/workflows/android.yml writes it
        // ignoreUnknownKeys: the made-up "extra" field must be skipped, not cause an error.
        val j = Json { ignoreUnknownKeys = true }.decodeFromString<AppUpdate.Latest>("""{"sha": "abc123", "built": "2026-10-29T02:53:24Z", "extra": 1}""")
        // The sha was read; and VERSION_URL is the APK's folder address plus "/version.json" (substringBeforeLast cuts off the file name after the last slash).
        assertEquals("abc123", j.sha)
        assertEquals(AppUpdate.APK_URL.substringBeforeLast('/') + "/version.json", AppUpdate.VERSION_URL)
    }
}
