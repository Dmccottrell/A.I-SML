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

// The app's own Admin screen (android_native): what Admin > Overview, Previews, PC, People and Crashes read (app/routes_get.py), kept on the
// phone so they can be read with the PC off; switch changes made then wait in a queue and are sent as soon as the PC is back.

@Serializable
data class AdminCheck(val id: String = "", val ok: Boolean = false, val title: String = "", val how: String = "")

@Serializable
data class AdminHealth(@SerialName("uptime_minutes") val uptimeMinutes: Long = 0, @SerialName("server_errors") val serverErrors: Long = 0,
                       @SerialName("devices_signed_in") val devices: Long = 0, @SerialName("coding_running") val codingRunning: Long = 0,
                       @SerialName("code_sandbox") val codeSandbox: String = "")

@Serializable
data class AdminOverview(val people: Int = 0, val banned: Int = 0, val plans: Map<String, Int> = emptyMap(), @SerialName("signup_mode") val signupMode: String = "",
                         val checklist: List<AdminCheck> = emptyList(), val health: AdminHealth = AdminHealth())

@Serializable
data class AdminFlag(val id: String, val title: String = "", val desc: String = "", val default: String = "admins", val audience: String = "admins",
                     val model: String? = null)

@Serializable
data class AdminFlags(val flags: List<AdminFlag> = emptyList(), val version: String = "", val fixes: List<String> = emptyList())

@Serializable
data class AdminPc(val gaming: Boolean = false, @SerialName("loaded_label") val loaded: String? = null, @SerialName("idle_seconds") val idleSeconds: Long? = null,
                   @SerialName("idle_unload_minutes") val idleUnloadMinutes: Int = 15, val busy: Boolean = false)

@Serializable
data class AdminUser(val user: String, val tier: String = "", val banned: Boolean = false, val owner: Boolean = false, val admin: Boolean = false,
                     val unlimited: Boolean = false, @SerialName("last_seen") val lastSeen: Double? = null)

@Serializable
data class AdminUsers(val users: List<AdminUser> = emptyList(), val paused: Boolean = false)

@Serializable
data class AdminCrash(val id: String, val kind: String = "", val where: String = "", val count: Int = 0, val error: String = "", val last: String? = null)

@Serializable
data class AdminCrashes(val crashes: List<AdminCrash> = emptyList())

/** Everything the screen shows, as it was when last read from the PC ([at]: when, ms) */
@Serializable
data class AdminSnapshot(val at: Long = 0, val overview: AdminOverview? = null, val flags: AdminFlags? = null, val pc: AdminPc? = null,
                         val users: AdminUsers? = null, val crashes: AdminCrashes? = null)

/** A switch change made with the PC off */
@Serializable
data class QueuedSwitch(val id: String, val audience: String)

object AdminRules {
    val AUDIENCES = listOf("off" to "Off", "owner" to "Owner", "admins" to "Admins", "everyone" to "Everyone")

    /** The switches as the screen shows them: what the PC said, with the changes still waiting applied on top */
    fun shown(flags: List<AdminFlag>, queued: List<QueuedSwitch>): List<AdminFlag> {
        val wait = queued.associate { it.id to it.audience }
        return flags.map { f -> wait[f.id]?.let { f.copy(audience = it) } ?: f }
    }

    /** A new change replaces an earlier one for the same switch; changing it back to what the PC has drops it */
    fun queue(queued: List<QueuedSwitch>, flags: List<AdminFlag>, id: String, audience: String): List<QueuedSwitch> {
        val rest = queued.filter { it.id != id }
        return if (flags.firstOrNull { it.id == id }?.audience == audience) rest else rest + QueuedSwitch(id, audience)
    }

    /** How many switches are on for fewer than everyone (what Publish all would publish) */
    fun inPreview(flags: List<AdminFlag>) = flags.count { it.audience != "everyone" && it.audience != "off" && it.model == null }
}

class AdminCache(context: Context) {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
    private val dir = File(context.filesDir, "admin").apply { mkdirs() }
    private val snapFile = File(dir, "snapshot.json")
    private val queueFile = File(dir, "queue.json")

    var snap by mutableStateOf(runCatching { json.decodeFromString<AdminSnapshot>(snapFile.readText()) }.getOrDefault(AdminSnapshot()))
        private set
    val queued = mutableStateListOf<QueuedSwitch>().apply { addAll(runCatching { json.decodeFromString<List<QueuedSwitch>>(queueFile.readText()) }.getOrDefault(emptyList())) }

    fun keep(s: AdminSnapshot) {
        snap = s
        runCatching { snapFile.writeText(json.encodeToString(s)) }
    }

    fun queue(id: String, audience: String) {
        val now = AdminRules.queue(queued.toList(), snap.flags?.flags.orEmpty(), id, audience)
        queued.clear()
        queued.addAll(now)
        saveQueue()
    }

    fun sent(id: String) {
        queued.removeAll { it.id == id }
        saveQueue()
    }

    private fun saveQueue() {
        runCatching { queueFile.writeText(json.encodeToString(queued.toList())) }
    }
}
