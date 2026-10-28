package app.emvryx.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// The replies the app's own Memory, Files, Skills and Settings screens read (feature flag android_native), as app/routes_get.py sends them.

/** GET /api/memory: what Emvryx remembers about you, and whether memory is on */
@Serializable
data class MemoryList(val facts: List<Fact> = emptyList(), val on: Boolean = true)

@Serializable
data class Fact(val id: Long, val text: String = "", val created: Double = 0.0, val slot: String = "")

/** GET /api/documents: your files, and the size limit */
@Serializable
data class DocList(val documents: List<DocRow> = emptyList(), @SerialName("max_mb") val maxMb: Int = 0)

@Serializable
data class DocRow(val id: Long, val name: String = "", val kind: String = "", val chars: Long = 0, val created: Double = 0.0)

/** GET /api/skills */
@Serializable
data class SkillList(val skills: List<Skill> = emptyList())

@Serializable
data class Skill(val id: String, val name: String = "", @SerialName("for") val forWho: String = "", val icon: String = "",
                 val does: String = "", @SerialName("try") val tryThis: String = "")

/** GET /api/settings: the settings the app's own Settings screen shows (app/state_settings.py get_settings) */
@Serializable
data class SettingsData(
    @SerialName("window_mode") val windowMode: String = "everyday",
    @SerialName("show_tokens") val showTokens: Boolean = false,
    @SerialName("web_search") val webSearch: String = "auto",
    val memory: Boolean = true,
    @SerialName("thinking_pause") val thinkingPause: String = "short",
    @SerialName("live_data") val liveData: Boolean = true,
    @SerialName("connected_apps") val connectedApps: Boolean = true,
    @SerialName("custom_instructions") val customInstructions: String = "",
)

/** "12 KB of text", "3,400 words": how big a file is, from the characters the server read out of it */
fun docSize(chars: Long): String = when {
    chars <= 0 -> ""
    chars < 6_000 -> "${maxOf(1, chars / 6)} words"
    else -> "${String.format(java.util.Locale.US, "%,d", chars / 6)} words"
}

/** POST /api/phone-sync */
@Serializable
data class PhoneSynced(val chat: Long)
