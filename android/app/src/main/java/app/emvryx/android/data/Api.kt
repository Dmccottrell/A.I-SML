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
    val tagline: String = "",
    val state: String = "",
    @SerialName("supports_effort") val supportsEffort: Boolean = false,
) {
    val ready get() = state == "ready"
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

@Serializable
data class AppState(
    val user: String,
    val plan: String = "",
    val demo: Boolean = false,
    val models: Catalog = Catalog(),
    val model: String = "",
    val efforts: List<Effort> = emptyList(),
    val chats: List<ChatSummary> = emptyList(),
    val gaming: Boolean = false,
)

@Serializable
data class Message(
    val id: Long = 0,
    val role: String,
    val content: String = "",
    @SerialName("model_id") val modelId: String = "",
    val status: String = "done",
)

@Serializable
data class Chat(
    val id: Long,
    val title: String = "New chat",
    val messages: List<Message> = emptyList(),
    val generating: Boolean = false,
)

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
