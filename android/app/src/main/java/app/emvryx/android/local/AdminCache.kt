package app.emvryx.android.local

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

// AdminCache.kt: data and a small saver for the app's own Admin screen (ui/AdminScreen.kt).
// The data classes are the JSON shapes of the admin calls (see ApiClient.kt "Admin" section). AdminCache keeps the last
// answers as files on the phone, and keeps a "queue" of feature-switch changes made while the PC was off.
//
// The app's own Admin screen (android_native): what Admin > Overview, Previews, PC, People and Crashes read (app/routes_get.py), kept on the
// phone so they can be read with the PC off; switch changes made then wait in a queue and are sent as soon as the PC is back.
// phone so they can be read with the PC off; switch changes made then wait in a queue and are sent as soon as the PC is back.

/** One line of the Overview checklist: [ok] says if it passes, [title] names it and [how] says how to fix it. */
@Serializable
data class AdminCheck(val id: String = "", val ok: Boolean = false, val title: String = "", val how: String = "")

/** The server's health numbers on the Overview page (minutes up, errors, signed-in devices, coding runs, the code sandbox in use). */
@Serializable
data class AdminHealth(@SerialName("uptime_minutes") val uptimeMinutes: Long = 0, @SerialName("server_errors") val serverErrors: Long = 0,
                       @SerialName("devices_signed_in") val devices: Long = 0, @SerialName("coding_running") val codingRunning: Long = 0,
                       @SerialName("code_sandbox") val codeSandbox: String = "")

/** Admin > Overview: how many people, how many are banned, how many on each plan, the sign-up mode, the checklist and the health numbers. */
@Serializable
data class AdminOverview(val people: Int = 0, val banned: Int = 0, val plans: Map<String, Int> = emptyMap(), @SerialName("signup_mode") val signupMode: String = "",
                         val checklist: List<AdminCheck> = emptyList(), val health: AdminHealth = AdminHealth())

/**
 * One feature flag (an on/off switch for a feature). [audience] is who has it now ("off", "owner", "admins" or "everyone"),
 * [default] is the audience it starts with, [model] is set when it belongs to one model, and [kind] is "feature" or "fix".
 */
@Serializable
data class AdminFlag(val id: String, val title: String = "", val desc: String = "", val default: String = "admins", val audience: String = "admins",
                     val model: String? = null, val kind: String = "feature")

/** Admin > Previews: all the flags, the app [version], the bug-fix notes waiting for the next release, and the versions the next release would get. */
@Serializable
data class AdminFlags(val flags: List<AdminFlag> = emptyList(), val version: String = "", val fixes: List<String> = emptyList(),
                      val next: Map<String, String> = emptyMap())

/** Admin > PC: whether the PC is in gaming mode, which model is loaded, how long it has been idle, when idle models unload (minutes), and whether it is busy. */
@Serializable
data class AdminPc(val gaming: Boolean = false, @SerialName("loaded_label") val loaded: String? = null, @SerialName("idle_seconds") val idleSeconds: Long? = null,
                   @SerialName("idle_unload_minutes") val idleUnloadMinutes: Int = 15, val busy: Boolean = false)

/** One person in Admin > People: their tier, whether banned / owner / admin / unlimited, and when last seen (Unix seconds). */
@Serializable
data class AdminUser(val user: String, val tier: String = "", val banned: Boolean = false, val owner: Boolean = false, val admin: Boolean = false,
                     val unlimited: Boolean = false, @SerialName("last_seen") val lastSeen: Double? = null)

/** The People list, and whether the service is paused. */
@Serializable
data class AdminUsers(val users: List<AdminUser> = emptyList(), val paused: Boolean = false)

/** One kind of crash: where it happened, how many times, the error text and the last time. */
@Serializable
data class AdminCrash(val id: String, val kind: String = "", val where: String = "", val count: Int = 0, val error: String = "", val last: String? = null)

/** The Crashes list. */
@Serializable
data class AdminCrashes(val crashes: List<AdminCrash> = emptyList())

/** Everything the screen shows, as it was when last read from the PC ([at]: when, in milliseconds since 1970). Each part is null until read once. */
@Serializable
data class AdminSnapshot(val at: Long = 0, val overview: AdminOverview? = null, val flags: AdminFlags? = null, val pc: AdminPc? = null,
                         val users: AdminUsers? = null, val crashes: AdminCrashes? = null)

/** A switch change made with the PC off: set flag [id] to [audience]. It waits in the queue until it can be sent. */
@Serializable
data class QueuedSwitch(val id: String, val audience: String)

/**
 * Plain rules for the queue of switch changes, kept apart from the screen and the files so they are easy to test.
 * An `object` is a single shared instance; its functions are called as AdminRules.shown(...).
 */
object AdminRules {
    // The audience choices in order: the server's word, then the label shown on screen.
    val AUDIENCES = listOf("off" to "Off", "owner" to "Owner", "admins" to "Admins", "everyone" to "Everyone")

    /** The switches as the screen shows them: what the PC said, with the changes still waiting applied on top (so the screen shows what the person chose) */
    fun shown(flags: List<AdminFlag>, queued: List<QueuedSwitch>): List<AdminFlag> {
        // Make a quick lookup: flag id -> the audience waiting to be sent.
        val wait = queued.associate { it.id to it.audience }
        // For each flag, use the waiting audience if there is one (`copy` makes a changed copy), otherwise leave it.
        return flags.map { f -> wait[f.id]?.let { f.copy(audience = it) } ?: f }
    }

    /** A new change replaces an earlier one for the same switch; changing it back to what the PC has drops it (nothing left to send) */
    fun queue(queued: List<QueuedSwitch>, flags: List<AdminFlag>, id: String, audience: String): List<QueuedSwitch> {
        // Everything in the queue except an older change to this same flag.
        val rest = queued.filter { it.id != id }
        // If the new choice equals what the PC already has, there is nothing to send; otherwise add it to the end.
        return if (flags.firstOrNull { it.id == id }?.audience == audience) rest else rest + QueuedSwitch(id, audience)
    }

    /** How many app switches of one kind ("feature" or "fix") are on for fewer than everyone: what its Publish button would publish (switches that are off or tied to one model do not count) */
    fun inPreview(flags: List<AdminFlag>, kind: String = "feature") =
        flags.count { it.audience != "everyone" && it.audience != "off" && it.model == null && it.kind == kind }

    /** Everything a bug-fix release would send: the fix switches in preview and the fix notes waiting */
    // (Fix switches in preview) + (fix notes waiting) = the number the bug-fix Publish button reports.
    fun fixesWaiting(f: AdminFlags) = inPreview(f.flags, "fix") + f.fixes.size
}

/**
 * Keeps the Admin screen's last data and queued changes in files inside the app's private folder, so they survive closing the app.
 * Reading a file that is missing or damaged just gives the empty starting value (runCatching catches the failure).
 */
class AdminCache(context: Context) {
    // Lenient JSON settings: ignore unknown fields, leave out nulls, use defaults for bad values.
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
    // <app files>/admin/ holds the two files (mkdirs makes the folder if needed).
    private val dir = File(context.filesDir, "admin").apply { mkdirs() }
    private val snapFile = File(dir, "snapshot.json")
    private val queueFile = File(dir, "queue.json")

    // The last data read from the PC. `mutableStateOf` is a Compose "observable box": when it changes, any screen
    // drawing it redraws by itself. `private set` means only this class may change it.
    var snap by mutableStateOf(runCatching { json.decodeFromString<AdminSnapshot>(snapFile.readText()) }.getOrDefault(AdminSnapshot()))
        private set
    // The waiting changes, as an observable list loaded from the file at start-up.
    val queued = mutableStateListOf<QueuedSwitch>().apply { addAll(runCatching { json.decodeFromString<List<QueuedSwitch>>(queueFile.readText()) }.getOrDefault(emptyList())) }

    /** Remembers new data from the PC: in memory at once, and written to the file (a failed write is ignored; the screen still works). */
    fun keep(s: AdminSnapshot) {
        snap = s
        runCatching { snapFile.writeText(json.encodeToString(s)) }
    }

    /** Adds or replaces a waiting change (see AdminRules.queue) and saves the queue. */
    fun queue(id: String, audience: String) {
        // Work out the new queue, then swap the list's contents (it must stay the same observable list object).
        val now = AdminRules.queue(queued.toList(), snap.flags?.flags.orEmpty(), id, audience)
        queued.clear()
        queued.addAll(now)
        saveQueue()
    }

    /** The PC accepted this change, so take it off the queue. */
    fun sent(id: String) {
        queued.removeAll { it.id == id }
        saveQueue()
    }

    // Writes the queue to disk as JSON.
    private fun saveQueue() {
        runCatching { queueFile.writeText(json.encodeToString(queued.toList())) }
    }
}
