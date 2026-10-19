package app.emvryx.android.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/** One step of a streamed reply (POST /api/chats/{id}/send, see api_send in app/routes_chat.py). */
sealed interface ReplyEvent {
    data class Thinking(val effort: String) : ReplyEvent
    data class Loading(val model: String) : ReplyEvent
    data class Piece(val text: String) : ReplyEvent
    data object Compacting : ReplyEvent
    data class Done(val title: String?, val messageId: Long?, val cut: Boolean) : ReplyEvent
    data class Failed(val code: String, val message: String, val action: String) : ReplyEvent
    data class Other(val name: String) : ReplyEvent
}

/** Turns server-sent-event lines into [ReplyEvent]s. Feed it every line (without the newline); a blank line ends an event. */
class SseParser(private val json: Json = Json { ignoreUnknownKeys = true }) {
    private var event = "message"
    private val data = StringBuilder()

    fun feed(line: String): ReplyEvent? {
        if (line.isEmpty()) return flush()
        if (line.startsWith(":")) return null                 // keep-alive comment
        val name = line.substringBefore(':')
        val value = line.substringAfter(':', "").removePrefix(" ")
        when (name) {
            "event" -> event = value
            "data" -> {
                if (data.isNotEmpty()) data.append('\n')
                data.append(value)
            }
        }
        return null
    }

    private fun flush(): ReplyEvent? {
        if (data.isEmpty()) {
            event = "message"
            return null
        }
        val name = event
        val body = runCatching { json.parseToJsonElement(data.toString()).jsonObject }.getOrNull() ?: JsonObject(emptyMap())
        event = "message"
        data.clear()
        fun s(k: String) = body[k]?.let { runCatching { it.jsonPrimitive.content }.getOrNull() }
        return when (name) {
            "thinking" -> ReplyEvent.Thinking(s("effort") ?: "")
            "loading" -> ReplyEvent.Loading(s("model") ?: "")
            "piece" -> ReplyEvent.Piece(s("t") ?: "")
            "compacting" -> ReplyEvent.Compacting
            "done" -> ReplyEvent.Done(
                title = s("title"),
                messageId = body["message_id"]?.let { runCatching { it.jsonPrimitive.longOrNull }.getOrNull() },
                cut = body["cut"]?.let { runCatching { it.jsonPrimitive.booleanOrNull }.getOrNull() } ?: false,
            )
            "error" -> ReplyEvent.Failed(s("code") ?: "error", s("message") ?: "Something went wrong.", s("action") ?: "")
            else -> ReplyEvent.Other(name)
        }
    }
}
