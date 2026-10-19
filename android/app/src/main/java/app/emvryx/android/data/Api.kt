package app.emvryx.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// What the server sends back (app/routes_get.py, app/routes_chat.py). Only the fields the app uses; the rest is ignored.

@Serializable
data class Status(
    val up: Boolean = false,
    val paused: Boolean = false,
    val resting: Boolean = false,
    val demo: Boolean = false,
)

@Serializable
data class LoginReply(
    val ok: Boolean = false,
    val mfa: Boolean = false,
    val ticket: String? = null,
)

@Serializable
data class ModelCard(
    val id: String,
    val name: String,
    val version: Double? = null,
    val tagline: String = "",
    val state: String = "",
    val badge: String = "",
    val efforts: List<String>? = null,       // when set, only these (plus Auto) can be picked
    val preview: Boolean = false,
    val vryxcode: Boolean = false,
    @SerialName("context_tested") val contextTested: Long? = null,
    val tour: List<TourSlide> = emptyList(),  // the model's welcome tour (models.json "tour"; feature flag model_tours)
    @SerialName("whats_new") val whatsNew: WhatsNew? = null,
) {
    val ready get() = state == "ready"

    /** "Flare 2.5", "Solstice 2": the name with its version, as the website shows it (core.js mname) */
    val fullName: String
        get() = version?.let { v -> name + " " + (if (v % 1.0 == 0.0) v.toLong().toString() else v.toString()) } ?: name
}

/** One slide of a model's welcome tour: art is memory, eyes, fast, think, deeper, sense, code or logo */
@Serializable
data class TourSlide(val art: String = "logo", val title: String = "", val text: String = "")

/** What is better than the version before (models.json "whats_new"): the points, and the measured numbers as [what, before, now] (null = still being measured) */
@Serializable
data class WhatsNew(val vs: String = "", val points: List<String> = emptyList(), val scores: List<List<String?>> = emptyList())

/** The person's own settings the app reads (the rest stay on the website's Settings page) */
@Serializable
data class UserSettings(@SerialName("model_tours_seen") val modelToursSeen: List<String> = emptyList())

@Serializable
data class Tank(val pct: Double = 100.0)

@Serializable
data class Week(@SerialName("pct_left") val pctLeft: Double = 100.0)

/** The usage line under the message box (app usage_snapshot; web/js/chat.js renderUsage) */
@Serializable
data class Usage(
    val exempt: Boolean = false,
    @SerialName("can_send") val canSend: Int = 0,
    val tank: Tank = Tank(),
    val week: Week = Week(),
) {
    val fraction get() = if (exempt) 1.0 else minOf(tank.pct, week.pctLeft) / 100.0

    val label: String
        get() = when {
            exempt -> "Usage: no limit (owner)"
            canSend <= 0 -> "Usage: out for now"
            else -> "Usage: ${percent(fraction)} · about ${"%,d".format(java.util.Locale.US, canSend)} messages left"
        }

    companion object {
        /** Near full, one decimal, so a small message is visible (chat.js pctText) */
        fun percent(frac: Double): String {
            val p = frac * 100
            return (if (p >= 99.95) "100" else if (p >= 90) "%.1f".format(java.util.Locale.US, p) else Math.round(p).toString()) + "%"
        }
    }
}

@Serializable
data class Catalog(
    val cards: List<ModelCard> = emptyList(),
    val other: List<ModelCard> = emptyList(),
) {
    val all get() = cards + other
}

@Serializable
data class Effort(
    val id: String,
    val name: String,
    val use: String = "",
    val blurb: String = "",
)

@Serializable
data class ChatSummary(
    val id: Long,
    val title: String = "New chat",
    val updated: Double = 0.0,
    val pinned: Boolean = false,
)

/** "Regenerate" with a choice of how the new answer should differ (app/regen_modes.py) */
@Serializable
data class RegenOption(val id: String, val label: String, val blurb: String = "")

@Serializable
data class AppState(
    val user: String,
    val plan: String = "",
    val demo: Boolean = false,
    val owner: Boolean = false,
    val admin: Boolean = false,
    val models: Catalog = Catalog(),
    val model: String = "",
    val efforts: List<Effort> = emptyList(),
    val chats: List<ChatSummary> = emptyList(),
    val usage: Usage? = null,
    val gaming: Boolean = false,
    @SerialName("regen_options") val regenOptions: List<RegenOption> = emptyList(),
    val features: Map<String, Boolean> = emptyMap(),        // the feature flags as they apply to this person (Admin > Previews)
    val settings: UserSettings = UserSettings(),
) {
    /** "Pro plan" */
    val planName get() = plan.replaceFirstChar { it.uppercase() } + " plan"

    fun on(flag: String) = features[flag] == true
}

/** How full the model's memory (context window) is: the ring by the message box (feature flag context_meter) */
@Serializable
data class Ctx(
    val used: Long = 0,
    val window: Long = 1,
    val pct: Double = 0.0,
    @SerialName("compact_at") val compactAt: Long = 0,
)

/** A picture or file attached to a chat (app/documents.py) */
@Serializable
data class DocInfo(val id: Long, val name: String = "", val kind: String = "") {
    val picture get() = kind.lowercase() in PICTURE_KINDS                       // documents.IMAGE_KINDS: the extension without the dot

    companion object {
        val PICTURE_KINDS = setOf("png", "jpg", "jpeg", "webp", "bmp", "gif", "heic")
    }
}

@Serializable
data class Message(
    val id: Long = 0,
    val role: String,
    val content: String = "",
    @SerialName("model_id") val modelId: String = "",
    val status: String = "done",
    val cut: Boolean = false,
    val fb: String = "",
    val ctx: Ctx? = null,
    val docs: List<DocInfo> = emptyList(),
)

@Serializable
data class Chat(
    val id: Long,
    val title: String = "New chat",
    val messages: List<Message> = emptyList(),
    val generating: Boolean = false,
    val ctx: Ctx? = null,
    val pinned: Boolean = false,
    val docs: List<DocInfo> = emptyList(),
)

@Serializable
data class SearchHit(val id: Long, val title: String = "", val snippet: String = "")

@Serializable
data class SearchReply(val results: List<SearchHit> = emptyList())

@Serializable
data class DocsReply(val docs: List<DocInfo> = emptyList())

@Serializable
data class BranchReply(val id: Long, val title: String = "")

@Serializable
data class CompactReply(val folded: Int = 0, val context: Ctx? = null)

@Serializable
data class NewChat(val id: Long)

/** Every refusal from the server is {"code", "message", "action"} (docs/API.md). */
@Serializable
data class ErrorBody(
    val code: String = "",
    val message: String = "",
    val action: String = "",
)

class ApiException(val http: Int, val code: String, override val message: String, val action: String = "") : Exception(message) {
    val signedOut get() = http == 401
}

/** No answer at all: the PC is off, the tunnel is down, or there is no signal. */
class OfflineException(cause: Throwable) : Exception("Emvryx is off right now.", cause)
