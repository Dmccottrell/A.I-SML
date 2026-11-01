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

// Api.kt: the "shapes" of the JSON the Emvryx server sends back (and a few it receives).
// Each `data class` below is a plain box of named fields. The kotlinx.serialization library
// (the @Serializable marker) turns the server's JSON text into these boxes for us, so the rest
// of the app can read `chat.title` instead of digging through raw text.
// ApiClient.kt makes the calls; the screens in ui/ show what is in these classes.
// Every field has a default value, so a missing field in the JSON never crashes the app.
//
// What the server sends back (app/routes_get.py, app/routes_chat.py). Only the fields the app uses; the rest is ignored.

/**
 * A yes/no the server sends as true/false in some places and 0/1 in others (a chat's "pinned": the list says false, the chat itself 0).
 * A "serializer" is the little translator that reads one JSON value into a Kotlin value and back; this one accepts both spellings.
 */
object FlexBool : KSerializer<Boolean> {
    // Tells the library what kind of value this is (a boolean); required by every serializer.
    override val descriptor = PrimitiveSerialDescriptor("FlexBool", PrimitiveKind.BOOLEAN)

    // Reads the JSON value and returns a real Boolean.
    override fun deserialize(decoder: Decoder): Boolean {
        // Get the raw JSON piece (a number, true/false...). If this is not JSON at all, just read a plain boolean.
        val p = (decoder as? JsonDecoder)?.decodeJsonElement()?.jsonPrimitive ?: return decoder.decodeBoolean()
        // "true"/"false" -> that boolean. Otherwise read it as a number: 0 means false, anything else means true.
        return p.booleanOrNull ?: ((p.content.toDoubleOrNull() ?: 0.0) != 0.0)
    }

    // Writing back out: always a real true/false.
    override fun serialize(encoder: Encoder, value: Boolean) = encoder.encodeBoolean(value)
}

/** The server's health check (GET /api/status): is it up, paused, resting (asleep to save power) or in demo mode. */
@Serializable
data class Status(
    val up: Boolean = false,
    val paused: Boolean = false,
    val resting: Boolean = false,
    val demo: Boolean = false,
)

/** The answer to a sign-in try: [ok] means signed in; [mfa] means a second step (a code) is needed, and [ticket] is the receipt to send back with that code. */
@Serializable
data class LoginReply(
    val ok: Boolean = false,
    val mfa: Boolean = false,
    val ticket: String? = null,
)

/** One model in the picker (name, version, whether it is ready, and its tour and "what's new"). */
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
    // True once the server says this model is loaded and usable.
    val ready get() = state == "ready"

    /**
     * "Flare 2.5", "Solstice 2": the name with its version, as the website shows it (core.js mname).
     * A whole-number version prints without ".0"; with no version it is just the name.
     */
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

/**
 * The short-term usage "tank" (the bar under the message box): how full it is, how many messages it still covers, and how fast it refills.
 * Numbers are Doubles (decimals) because the server sends fractions.
 */
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

/** The weekly allowance: percent left, how many messages that is, and the time (Unix seconds) it resets. */
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
    // The fuller-looking limit wins: the smaller of the tank and the week, as a 0..1 fraction (owners have no limit, so always full).
    val fraction get() = if (exempt) 1.0 else minOf(tank.pct, week.pctLeft) / 100.0

    // The line shown under the message box, e.g. "Usage: 80% · about 1,200 messages left".
    val label: String
        get() = when {
            exempt -> "Usage: no limit (owner)"
            canSend <= 0 -> "Usage: out for now"
            // "%,d" puts thousands commas in; Locale.US makes sure the commas and dots are the same on every phone.
            else -> "Usage: ${percent(fraction)} · about ${"%,d".format(java.util.Locale.US, canSend)} messages left"
        }

    companion object {
        /**
         * Turns a 0..1 fraction into text like "87%". Near full (90% and up) it shows one decimal so a small message
         * is visible, and 99.95% or more shows "100%" (web chat.js pctText does the same).
         */
        fun percent(frac: Double): String {
            // Fraction to percent.
            val p = frac * 100
            // Pick the format by size; Math.round gives a whole number for the lower range.
            return (if (p >= 99.95) "100" else if (p >= 90) "%.1f".format(java.util.Locale.US, p) else Math.round(p).toString()) + "%"
        }
    }
}

/** The model list: [cards] are the main models and [other] the rest; [all] joins them. */
@Serializable
data class Catalog(
    val cards: List<ModelCard> = emptyList(),
    val other: List<ModelCard> = emptyList(),
) {
    val all get() = cards + other
}

/** One "thinking effort" choice (e.g. how hard the model tries): its id, name, when to use it and a short blurb. */
@Serializable
data class Effort(
    val id: String,
    val name: String,
    val use: String = "",
    val blurb: String = "",
)

/** One row of the chat list: enough to show the title and sort it, not the messages. */
@Serializable
data class ChatSummary(
    val id: Long,
    val title: String = "New chat",
    val updated: Double = 0.0,
    // FlexBool because the server's spelling of this yes/no differs between the list and a single chat.
    @Serializable(with = FlexBool::class) val pinned: Boolean = false,
    val skill: String = "",             // started from a skill or Teacher mode: listed on its own, as on the website
    val folder: String = "",
)

/** The model's memory size (its context window, counted in tokens, which are small pieces of text) for the person (state "window"): used to estimate the memory ring before the first reply measures it */
@Serializable
data class ChatWindow(val window: Long = 0)

/** "Regenerate" with a choice of how the new answer should differ (app/regen_modes.py): an id to send, a label and a short blurb */
@Serializable
data class RegenOption(val id: String, val label: String, val blurb: String = "")

/**
 * Everything the app needs right after sign-in (GET /api/state): who you are, your plan, the model list,
 * your chats, your usage, and which feature flags are switched on for you.
 */
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
    // A feature flag is an on/off switch for a new feature; the server decides per person which are on.
    @SerialName("regen_options") val regenOptions: List<RegenOption> = emptyList(),
    val features: Map<String, Boolean> = emptyMap(),        // the feature flags as they apply to this person (Admin > Previews)
    val settings: UserSettings = UserSettings(),
    val window: ChatWindow? = null,
    val briefing: Boolean = false,                           // "Your day" can be read from connected apps
    @SerialName("thinking_words") val thinkingWords: List<String> = emptyList(),
    @SerialName("think_switch_s") val thinkSwitchS: Double = 2.5,
) {
    /** "Pro plan": the plan name with a capital first letter and the word "plan" after it. */
    val planName get() = plan.replaceFirstChar { it.uppercase() } + " plan"

    /** True when the named feature flag is switched on for this person (a missing flag counts as off). */
    fun on(flag: String) = features[flag] == true
}

/** How full the model's memory (context window) is: the ring by the message box (feature flag context_meter). [used] of [window] tokens, [pct] percent, and [compactAt] is where old messages start getting folded into a summary. */
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
    // True when the file is a picture: its kind (the extension without the dot) is in the list below, in any letter case.
    val picture get() = kind.lowercase() in PICTURE_KINDS                       // documents.IMAGE_KINDS: the extension without the dot

    companion object {
        val PICTURE_KINDS = setOf("png", "jpg", "jpeg", "webp", "bmp", "gif", "heic")
    }
}

/** One message in a chat. [role] says who wrote it (the person or the model); [status] and [cut] tell if the reply finished or was stopped at a length limit; [fb] is any feedback given. */
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

/** A whole chat as GET /api/chats/{id} returns it: its messages, whether a reply is being written, and its memory reading. */
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

/** The reply of the chat-list calls: just the rows. */
@Serializable
data class ChatList(val chats: List<ChatSummary> = emptyList())

/** What the model was given before it answered (the "notes" event; web/js/send.js lookupLine). A [Source] is one web page it read: its title and link. */
@Serializable
data class Source(val title: String = "", val url: String = "")

/** A connected app (mail, calendar...) that failed while the model looked things up, with the reason. */
@Serializable
data class AppError(val app: String = "", val message: String = "")

/**
 * The "notes" the model was handed before replying: counts of what it looked at (pictures, text read from pictures,
 * saved notes, Wikipedia, web, live data), the apps it asked, anything it could not read, and the web pages used.
 * The app turns this into the small "looked at..." line under a reply.
 */
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

/** "Your day" from the connected apps (GET /api/briefing): sections (one per app), each with items that have a title and text, or an error. [Briefing.off] means the feature is off. */
@Serializable
data class BriefItem(val title: String = "", val text: String = "")

@Serializable
data class BriefSection(val kind: String = "", val app: String = "", val items: List<BriefItem> = emptyList(), val error: String = "")

@Serializable
data class Briefing(val sections: List<BriefSection> = emptyList(), val off: Boolean = false)

/** Read-only links to a copy of a chat (POST /api/chats/{id}/share, GET /api/shares). [ShareRow.expires] is a Unix time (seconds since 1970); [Shares.on] says if sharing is allowed. */
@Serializable
data class ShareRow(val id: String = "", val title: String = "", val expires: Double = 0.0)

@Serializable
data class Shares(val shares: List<ShareRow> = emptyList(), val on: Boolean = false)

/** The reply after making a share link: the link itself and the updated list. */
@Serializable
data class ShareMade(val url: String = "", val shares: List<ShareRow> = emptyList())

/** The reply to "Right answer": how many notes were saved for offline use. */
@Serializable
data class LikeReply(val saved: Int = 0)

/** Which ways of signing in this server offers (GET /api/auth-options): an emailed code, a password, passkeys. */
@Serializable
data class AuthOptions(val email: Boolean = false, val password: Boolean = true, val passkeys: Boolean = false)

/** One chat found by search: its id, title and a short matching snippet. */
@Serializable
data class SearchHit(val id: Long, val title: String = "", val snippet: String = "")

/** The reply of the chat search call. */
@Serializable
data class SearchReply(val results: List<SearchHit> = emptyList())

/** The files now attached to a chat. */
@Serializable
data class DocsReply(val docs: List<DocInfo> = emptyList())

/** The new chat made by "branch from here". */
@Serializable
data class BranchReply(val id: Long, val title: String = "")

/** The result of "compact" (folding old messages into a summary): how many were folded and the new memory reading. */
@Serializable
data class CompactReply(val folded: Int = 0, val context: Ctx? = null)

/** The id of a chat that was just created. */
@Serializable
data class NewChat(val id: Long)

/** Every refusal from the server is {"code", "message", "action"} (docs/API.md). [action] hints what the person can do next. */
@Serializable
data class ErrorBody(
    val code: String = "",
    val message: String = "",
    val action: String = "",
)

/**
 * Thrown when the server answered but said no. [http] is the HTTP status number (401 = not signed in, 429 = too many, ...),
 * [code] is the server's short machine word, and [message] is plain text safe to show the person.
 */
class ApiException(val http: Int, val code: String, override val message: String, val action: String = "") : Exception(message) {
    // 401 means the session has expired or never existed: the app should send the person back to sign in.
    val signedOut get() = http == 401
}

/** No answer at all: the PC is off, the tunnel is down, or there is no signal. */
class OfflineException(cause: Throwable) : Exception("Emvryx is off right now.", cause)
