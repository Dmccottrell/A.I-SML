package app.emvryx.android

// Unit tests (plain JVM tests, no phone needed) for the offline part of the app's Admin screen.
// They prove: queued switch changes, the preview counts, how the PC's replies are read, and the "time ago" text.
// The imports below pull in the code under test plus JUnit (the test library: @Test marks a test, assertEquals compares values).
import app.emvryx.android.local.AdminFlag
import app.emvryx.android.local.AdminFlags
import app.emvryx.android.local.AdminOverview
import app.emvryx.android.local.AdminRules
import app.emvryx.android.local.QueuedSwitch
import app.emvryx.android.ui.ago
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The app's own Admin: switch changes made with the PC off, and Admin's replies as the PC sends them.
 * Each @Test function below is one small, independent check; the test run reports any whose asserts fail.
 */
class AdminCacheTest {
    // Sample feature switches ("flags") shared by the tests: "a" is on for admins only, "b" is off for everyone,
    // and "vryxcode_x" belongs to the VryxCode coding product (its own model) rather than the app.
    private val flags = listOf(AdminFlag("a", audience = "admins"), AdminFlag("b", audience = "off"), AdminFlag("vryxcode_x", audience = "admins", model = "vryxcode"))

    @Test
    // Proves: when the PC is off, a switch change is kept in a waiting list (a queue) and the screen already shows the new value.
    fun aChangeWaitsAndShows() {
        // Start with an empty queue and ask to make switch "a" visible to everyone.
        val q = AdminRules.queue(emptyList(), flags, "a", "everyone")
        // The queue now holds exactly that one change.
        assertEquals(listOf(QueuedSwitch("a", "everyone")), q)
        // "shown" overlays the queued change on the real flags, so the screen displays "everyone" straight away.
        assertEquals("everyone", AdminRules.shown(flags, q).first { it.id == "a" }.audience)
    }

    @Test
    // Proves: two changes to the same switch keep only the newest, and setting it back to what the PC already has removes it from the queue.
    fun theLastChangeWinsAndChangingBackDropsIt() {
        // First change "a" to everyone, then change it again to owner.
        var q = AdminRules.queue(emptyList(), flags, "a", "everyone")
        q = AdminRules.queue(q, flags, "a", "owner")
        // Only the latest change (owner) is left, not both.
        assertEquals(listOf(QueuedSwitch("a", "owner")), q)
        assertTrue(AdminRules.queue(q, flags, "a", "admins").isEmpty())            // back to what the PC has: nothing to send
    }

    @Test
    // Proves: the "publish all" button counts only app features that are in preview (shown to admins first).
    fun publishAllCountsOnlyAppFeaturesInPreview() {
        // Of the three sample flags only "a" counts: "b" is off and the VryxCode one is published with its own push.
        assertEquals(1, AdminRules.inPreview(flags))                                // not the off one, not VryxCode's own (published with its own push)
    }

    @Test
    // Proves: features and bug fixes are counted (and published) apart, and the fix "kind" survives reading JSON.
    fun newFeaturesAndBugFixesArePublishedSeparately() {
        // features add 0.5 to the version, fixes 0.1 (app/flags.py): each button counts only its own kind, and a fix note counts as a fix
        // Add a fix-type flag so the list has both kinds.
        val mixed = flags + AdminFlag("chat_fixes", audience = "admins", kind = "fix")
        // One feature waiting and one fix waiting, each button counts only its own kind.
        assertEquals(1, AdminRules.inPreview(mixed, "feature"))
        assertEquals(1, AdminRules.inPreview(mixed, "fix"))
        // Fixes waiting = 1 fix flag + 2 written fix notes = 3.
        assertEquals(3, AdminRules.fixesWaiting(AdminFlags(mixed, fixes = listOf("One", "Two"))))
        // Read a reply the way the PC sends it: JSON text turned into an AdminFlags object. ignoreUnknownKeys means extra fields are skipped, not errors.
        // (The triple-quoted text below is a raw string, so its content is exactly the JSON.)
        val j = Json { ignoreUnknownKeys = true }.decodeFromString<AdminFlags>("""{"flags": [{"id": "chat_fixes", "kind": "fix"}], "version": "3.1",
            "next": {"features": "3.6", "fixes": "3.2"}, "fixes": []}""")
        // The flag's kind and the "next version" numbers were read correctly.
        assertEquals("fix", j.flags[0].kind)
        assertEquals("3.2", j.next["fixes"])
    }

    @Test
    // Proves: the Admin overview and flags replies decode into the app's objects with the right values.
    fun repliesRead() {
        // Same lenient JSON settings the app uses: skip unknown fields, treat missing values as null, and fall back to defaults for bad values.
        val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
        // A sample overview reply (people counts, a checklist, server health).
        val o = json.decodeFromString<AdminOverview>("""{"signup_mode": "closed", "people": 2, "banned": 0, "plans": {"free": 1, "mega": 1},
            "checklist": [{"id": "mfa", "ok": false, "title": "Two-step sign-in", "how": "Settings > Security."}],
            "health": {"uptime_minutes": 5, "server_errors": 0, "devices_signed_in": 1, "coding_running": 0, "code_sandbox": "docker", "alerts_on": false}}""")
        // A plain number and a snake_case JSON field (code_sandbox) mapped to a camelCase property (codeSandbox).
        assertEquals(2, o.people)
        assertEquals("docker", o.health.codeSandbox)
        // A sample flags reply; the "null" values must be accepted without crashing.
        val f = json.decodeFromString<AdminFlags>("""{"flags": [{"id": "x", "title": "X", "desc": "d", "default": "admins", "audience": "everyone",
            "changed": null, "scheduled": null}], "version": "1.4.0"}""")
        // The audience came through unchanged.
        assertEquals("everyone", f.flags[0].audience)
    }

    @Test
    // Proves: the "ago" helper turns a time difference (milliseconds) into friendly words.
    fun howLongAgo() {
        // Under a minute (30 000 ms apart) reads "just now"; then minutes; then hours (3 * 3 600 000 ms = 3 hours).
        assertEquals("just now", ago(1_000_000, now = 1_030_000))
        assertEquals("5 min ago", ago(0, now = 300_000))
        assertEquals("3 hours ago", ago(0, now = 3 * 3_600_000L))
    }
}
