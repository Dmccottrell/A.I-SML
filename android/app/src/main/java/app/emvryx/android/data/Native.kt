// Native.kt: the JSON shapes for the app's own screens (Memory, Files, Skills, Settings) that are drawn natively
// instead of opening the website. They are behind the feature flag android_native. Same pattern as Api.kt:
// @Serializable data classes with defaults, filled from the server's JSON.

package app.emvryx.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// The replies the app's own Memory, Files, Skills and Settings screens read (feature flag android_native), as app/routes_get.py sends them. (A feature flag is an on/off switch the server controls.)

/** GET /api/memory: what Emvryx remembers about you, and whether memory is on */
@Serializable
data class MemoryList(val facts: List<Fact> = emptyList(), val on: Boolean = true)

/** One remembered fact: its id, the text, when it was made (Unix seconds) and the slot it belongs to. */
@Serializable
data class Fact(val id: Long, val text: String = "", val created: Double = 0.0, val slot: String = "")

/** GET /api/documents: your files, and the size limit in megabytes ([maxMb]) */
@Serializable
data class DocList(val documents: List<DocRow> = emptyList(), @SerialName("max_mb") val maxMb: Int = 0)

/** One file in the Files list: [chars] is how much text the server read from it, [created] a Unix time. */
@Serializable
data class DocRow(val id: Long, val name: String = "", val kind: String = "", val chars: Long = 0, val created: Double = 0.0)

/** GET /api/skills: the list of skills (saved instruction sets a chat can start from) */
@Serializable
data class SkillList(val skills: List<Skill> = emptyList())

/**
 * One skill. `for` and `try` are reserved words in Kotlin, so the JSON names "for" and "try" are mapped
 * (@SerialName) onto the field names [forWho] and [tryThis].
 */
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

/**
 * How big a file is, in words, worked out from the characters the server read out of it: "40 words", "3,400 words" ("" for nothing).
 * The divide by 6 is a rough guess of 6 characters per word (including the space).
 */
fun docSize(chars: Long): String = when {
    // Under 6,000 characters: show the plain count, at least 1. Otherwise add thousands commas (Locale.US so every phone prints the same).
    chars <= 0 -> ""
    chars < 6_000 -> "${maxOf(1, chars / 6)} words"
    else -> "${String.format(java.util.Locale.US, "%,d", chars / 6)} words"
}

/** POST /api/phone-sync: the reply holds the id of the chat the phone's messages were added to. */
@Serializable
data class PhoneSynced(val chat: Long)

/** POST /api/code/drafts: the reply holds the id of the saved VryxCode draft. */
@Serializable
data class DraftSaved(val id: String)
