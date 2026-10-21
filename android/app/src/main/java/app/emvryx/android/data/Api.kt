package app.emvryx.android.data

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonPrimitive

// What the server sends back (app/routes_get.py, app/routes_chat.py). Only the fields the app uses; the rest is ignored.

/** A yes/no the server sends as true/false in some places and 0/1 in others (a chat's "pinned": the list says false, the chat itself 0) */
object FlexBool : KSerializer<Boolean> {
    override val descriptor = PrimitiveSerialDescriptor("FlexBool", PrimitiveKind.BOOLEAN)

    override fun deserialize(decoder: Decoder): Boolean {
        val p = (decoder as? JsonDecoder)?.decodeJsonElement()?.jsonPrimitive ?: return decoder.decodeBoolean()
        return p.booleanOrNull ?: ((p.content.toDoubleOrNull() ?: 0.0) != 0.0)
    }

    override fun serialize(encoder: Encoder, value: Boolean) = encoder.encodeBoolean(value)
}

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
data class UserSettings(
    @SerialName("model_tours_seen") val modelToursSeen: List<String> = emptyList(),
    @SerialName("vryx_tour_seen") val vryxTourSeen: Int = 0,
)

@Serializable
data class Tank(
    val pct: Double = 100.0,
    val left: Double = 0.0,
    val cap: Double = 0.0,
    @SerialName("messages_left") val messagesLeft: Int = 0,
    @SerialName("full_at") val fullAt: Double = 0.0,
    @SerialName("refill_per_hour") val refillPerHour: Double = 0.0,
    val mode: String = "",
    @SerialName("refill_hours") val refillHours: Double = 0.0,
)

@Serializable
data class Week(
    @SerialName("pct_left") val pctLeft: Double = 100.0,
    val left: Double = 0.0,
    val cap: Double = 0.0,
    @SerialName("messages_left") val messagesLeft: Int = 0,
    @SerialName("resets_at") val resetsAt: Double = 0.0,
)

/** Messages left on one model ("flare", "solstice" ...) */
@Serializable
data class ModelLeft(val model: String = "", @SerialName("messages_left") val messagesLeft: Int = 0)

/** The usage line under the message box (app usage_snapshot; web/js/chat.js renderUsage) */
@Serializable
data class Usage(
    val exempt: Boolean = false,
    val status: String = "",
    @SerialName("can_send") val canSend: Int = 0,
    val tank: Tank = Tank(),
    val week: Week = Week(),
    val models: List<ModelLeft> = emptyList(),
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
    @Serializable(with = FlexBool::class) val pinned: Boolean = false,
    val skill: String = "",             // started from a skill or Teacher mode: listed on its own, as on the website
    val folder: String = "",
)

/** The model's memory size for the person (state "window"): used to estimate the memory ring before the first reply measures it */
@Serializable
data class ChatWindow(val window: Long = 0)

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
    val window: ChatWindow? = null,
    val briefing: Boolean = false,                           // "Your day" can be read from connected apps
    @SerialName("thinking_words") val thinkingWords: List<String> = emptyList(),
    @SerialName("think_switch_s") val thinkSwitchS: Double = 2.5,
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
    @Serializable(with = FlexBool::class) val pinned: Boolean = false,    // GET /api/chats/{id} sends 0 or 1 (app_engine.meta)
    val docs: List<DocInfo> = emptyList(),
    val private: Boolean = false,
    val skill: String = "",
    val folder: String = "",
)

@Serializable
data class ChatList(val chats: List<ChatSummary> = emptyList())

/** What the model was given before it answered (the "notes" event; web/js/send.js lookupLine) */
@Serializable
data class Source(val title: String = "", val url: String = "")

@Serializable
data class AppError(val app: String = "", val message: String = "")

@Serializable
data class LookupNotes(
    val asked: Boolean = false,
    val retry: Boolean = false,
    val pictures: Int = 0,
    val ocr: Int = 0,
    val saved: Int = 0,
    val wiki: Int = 0,
    val web: Int = 0,
    val live: Int = 0,
    val apps: List<String> = emptyList(),
    val names: List<String> = emptyList(),
    val unreadable: List<String> = emptyList(),
    @SerialName("app_errors") val appErrors: List<AppError> = emptyList(),
    @SerialName("web_tried") val webTried: Boolean = false,
    @SerialName("web_source") val webSource: String = "",
    val sources: List<Source> = emptyList(),
)

/** Where a reply's time went: shown under it to the owner and admins (the "done" event's timing; send.js timingLine) */
@Serializable
data class Timing(
    val total: Double = 0.0,
    val lookup: Double = 0.0,
    val load: Double = 0.0,
    @SerialName("first_word") val firstWord: Double = 0.0,
    val thought: Boolean = false,
    val tries: Int = 1,
)

/** "Your day" from the connected apps (GET /api/briefing) */
@Serializable
data class BriefItem(val title: String = "", val text: String = "")

@Serializable
data class BriefSection(val kind: String = "", val app: String = "", val items: List<BriefItem> = emptyList(), val error: String = "")

@Serializable
data class Briefing(val sections: List<BriefSection> = emptyList(), val off: Boolean = false)

/** Read-only links to a copy of a chat (POST /api/chats/{id}/share, GET /api/shares) */
@Serializable
data class ShareRow(val id: String = "", val title: String = "", val expires: Double = 0.0)

@Serializable
data class Shares(val shares: List<ShareRow> = emptyList(), val on: Boolean = false)

@Serializable
data class ShareMade(val url: String = "", val shares: List<ShareRow> = emptyList())

@Serializable
data class LikeReply(val saved: Int = 0)

/** Which ways of signing in this server offers (GET /api/auth-options) */
@Serializable
data class AuthOptions(val email: Boolean = false, val password: Boolean = true, val passkeys: Boolean = false)

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
