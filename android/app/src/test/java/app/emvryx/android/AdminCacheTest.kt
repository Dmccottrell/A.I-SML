package app.emvryx.android

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

/** The app's own Admin: switch changes made with the PC off, and Admin's replies as the PC sends them */
class AdminCacheTest {
    private val flags = listOf(AdminFlag("a", audience = "admins"), AdminFlag("b", audience = "off"), AdminFlag("vryxcode_x", audience = "admins", model = "vryxcode"))

    @Test
    fun aChangeWaitsAndShows() {
        val q = AdminRules.queue(emptyList(), flags, "a", "everyone")
        assertEquals(listOf(QueuedSwitch("a", "everyone")), q)
        assertEquals("everyone", AdminRules.shown(flags, q).first { it.id == "a" }.audience)
    }

    @Test
    fun theLastChangeWinsAndChangingBackDropsIt() {
        var q = AdminRules.queue(emptyList(), flags, "a", "everyone")
        q = AdminRules.queue(q, flags, "a", "owner")
        assertEquals(listOf(QueuedSwitch("a", "owner")), q)
        assertTrue(AdminRules.queue(q, flags, "a", "admins").isEmpty())            // back to what the PC has: nothing to send
    }

    @Test
    fun publishAllCountsOnlyAppFeaturesInPreview() {
        assertEquals(1, AdminRules.inPreview(flags))                                // not the off one, not VryxCode's own (published with its own push)
    }

    @Test
    fun newFeaturesAndBugFixesArePublishedSeparately() {
        // features add 0.5 to the version, fixes 0.1 (app/flags.py): each button counts only its own kind, and a fix note counts as a fix
        val mixed = flags + AdminFlag("chat_fixes", audience = "admins", kind = "fix")
        assertEquals(1, AdminRules.inPreview(mixed, "feature"))
        assertEquals(1, AdminRules.inPreview(mixed, "fix"))
        assertEquals(3, AdminRules.fixesWaiting(AdminFlags(mixed, fixes = listOf("One", "Two"))))
        val j = Json { ignoreUnknownKeys = true }.decodeFromString<AdminFlags>("""{"flags": [{"id": "chat_fixes", "kind": "fix"}], "version": "3.1",
            "next": {"features": "3.6", "fixes": "3.2"}, "fixes": []}""")
        assertEquals("fix", j.flags[0].kind)
        assertEquals("3.2", j.next["fixes"])
    }

    @Test
    fun repliesRead() {
        val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
        val o = json.decodeFromString<AdminOverview>("""{"signup_mode": "closed", "people": 2, "banned": 0, "plans": {"free": 1, "mega": 1},
            "checklist": [{"id": "mfa", "ok": false, "title": "Two-step sign-in", "how": "Settings > Security."}],
            "health": {"uptime_minutes": 5, "server_errors": 0, "devices_signed_in": 1, "coding_running": 0, "code_sandbox": "docker", "alerts_on": false}}""")
        assertEquals(2, o.people)
        assertEquals("docker", o.health.codeSandbox)
        val f = json.decodeFromString<AdminFlags>("""{"flags": [{"id": "x", "title": "X", "desc": "d", "default": "admins", "audience": "everyone",
            "changed": null, "scheduled": null}], "version": "1.4.0"}""")
        assertEquals("everyone", f.flags[0].audience)
    }

    @Test
    fun howLongAgo() {
        assertEquals("just now", ago(1_000_000, now = 1_030_000))
        assertEquals("5 min ago", ago(0, now = 300_000))
        assertEquals("3 hours ago", ago(0, now = 3 * 3_600_000L))
    }
}
