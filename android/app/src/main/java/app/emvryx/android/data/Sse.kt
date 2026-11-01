// Sse.kt: reads the live stream of a chat reply. The server answers a "send" call with server-sent events (SSE): plain text
// where each event looks like
//     event: piece
//     data: {"t": "Hello"}
//     (blank line)
// SseParser (below) is fed those lines one at a time by ApiClient.send and returns a ReplyEvent each time an event is complete.
// The screens then react: show the next piece of text, a "thinking" label, the final "done" and so on.

package app.emvryx.android.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/** One step of a streamed reply (POST /api/chats/{id}/send, see api_send in app/routes_chat.py). A `sealed interface` is a closed list of kinds: the code that handles it can be checked to cover every kind. */
sealed interface ReplyEvent {
    /** The model started thinking. [auto]: Auto chose the effort; [reason] says why */
    data class Thinking(val effort: String, val auto: Boolean = false, val reason: String = "") : ReplyEvent
    /** The model is being loaded into memory (can take a while on first use). */
    data class Loading(val model: String) : ReplyEvent
    /** The next bit of the answer text; the screen appends it. */
    data class Piece(val text: String) : ReplyEvent
    /** Old messages are being folded into a summary to make room. */
    data object Compacting : ReplyEvent
    /** What the model was given before it answered; [LookupNotes.retry]: it said it didn't know, the web was searched, it answers again */
    data class Notes(val notes: LookupNotes) : ReplyEvent
    /** Things it remembered about you ([saved]) or forgot ([forgot] counts them) from this message */
    data class Memory(val saved: List<String>, val forgot: Int) : ReplyEvent
    /** The reply is finished: the chat's title, the message's id, whether it was [cut] at a length limit, and optional timing, usage and memory readings. */
    data class Done(val title: String?, val messageId: Long?, val cut: Boolean, val timing: Timing? = null, val usage: Usage? = null,
                    val context: Ctx? = null) : ReplyEvent
    /** Deep Research (chat_research): one search or page read, [done] of [of] */
    data class Research(val step: String, val done: Int, val of: Int) : ReplyEvent
    /** The server reported an error inside the stream. */
    data class Failed(val code: String, val message: String, val action: String) : ReplyEvent
    /** An event name this app version does not know; ignored by the screens (a newer server may add some). */
    data class Other(val name: String) : ReplyEvent
}

/** Turns server-sent-event lines into [ReplyEvent]s. Feed it every line (without the newline); a blank line ends an event. Not thread-safe: use one parser per stream. */
class SseParser(private val json: Json = Json { ignoreUnknownKeys = true; coerceInputValues = true }) {
    // The event name seen so far ("message" is the default when none is given).
    private var event = "message"
    // The data lines collected for the event being built. A StringBuilder is a text buffer you can add to cheaply.
    private val data = StringBuilder()

    /** Takes one line of the stream. Returns a finished event when this line was the blank one that ends it, otherwise null. */
    fun feed(line: String): ReplyEvent? {
        // A blank line = the event is complete: build and return it.
        if (line.isEmpty()) return flush()
        if (line.startsWith(":")) return null                 // keep-alive comment
        // A line is "name: value". Split at the first colon and drop the one space after it.
        val name = line.substringBefore(':')
        val value = line.substringAfter(':', "").removePrefix(" ")
        // Remember the name; collect data lines (several data lines of one event are joined with a newline).
        when (name) {
            "event" -> event = value
            "data" -> {
                if (data.isNotEmpty()) data.append('\n')
                data.append(value)
            }
        }
        return null
    }

    // Reads a nested object (like "timing") from the event into class [T]; null if it is missing or malformed.
    private inline fun <reified T> obj(body: JsonObject, key: String): T? =
        body[key]?.let { runCatching { json.decodeFromJsonElement<T>(it) }.getOrNull() }

    // Turns the collected name + data into a ReplyEvent, then resets for the next event.
    private fun flush(): ReplyEvent? {
        // Nothing collected (e.g. only an event name): no event to give.
        if (data.isEmpty()) {
            event = "message"
            return null
        }
        val name = event
        // The data is JSON text. If it is broken, use an empty object so the event still comes through with default values.
        val body = runCatching { json.parseToJsonElement(data.toString()).jsonObject }.getOrNull() ?: JsonObject(emptyMap())
        event = "message"
        // Reset now, before returning, so the next event starts clean.
        data.clear()
        // Small readers: s = text field (null if missing), b = true/false field (false if missing).
        fun s(k: String) = body[k]?.let { runCatching { it.jsonPrimitive.content }.getOrNull() }
        fun b(k: String) = body[k]?.let { runCatching { it.jsonPrimitive.booleanOrNull }.getOrNull() } ?: false
        // Match the event name the server uses (see api_send in app/routes_chat.py) to the right ReplyEvent.
        return when (name) {
            "thinking" -> ReplyEvent.Thinking(s("effort") ?: "", b("auto"), s("reason") ?: "")
            "loading" -> ReplyEvent.Loading(s("model") ?: "")
            // "t" is the piece of text.
            "piece" -> ReplyEvent.Piece(s("t") ?: "")
            "compacting" -> ReplyEvent.Compacting
            "notes" -> ReplyEvent.Notes(runCatching { json.decodeFromJsonElement<LookupNotes>(body) }.getOrDefault(LookupNotes()))
            // A list of saved facts and a count of forgotten ones; anything unreadable counts as none.
            "memory" -> ReplyEvent.Memory(
                saved = body["saved"]?.let { runCatching { it.jsonArray.map { x -> x.jsonPrimitive.content } }.getOrNull() }.orEmpty(),
                forgot = body["forgot"]?.let { runCatching { it.jsonPrimitive.longOrNull?.toInt() }.getOrNull() } ?: 0,
            )
            // The final event: any of the extras may be absent, so they are read leniently.
            "done" -> ReplyEvent.Done(
                title = s("title"),
                messageId = body["message_id"]?.let { runCatching { it.jsonPrimitive.longOrNull }.getOrNull() },
                cut = b("cut"),
                timing = obj(body, "timing"),
                usage = obj(body, "usage"),
                context = obj(body, "context"),
            )
            "research" -> ReplyEvent.Research(s("step") ?: "", s("done")?.toIntOrNull() ?: 0, s("of")?.toIntOrNull() ?: 0)
            "error" -> ReplyEvent.Failed(s("code") ?: "error", s("message") ?: "Something went wrong.", s("action") ?: "")
            // Unknown event: keep its name only.
            else -> ReplyEvent.Other(name)
        }
    }
}
