package app.emvryx.android.local

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** GET /api/phone-model (app/phone_model.py): the model file for this phone and how to answer with it, as the PC does */
@Serializable
data class PhoneKit(
    val available: Boolean = false,
    val message: String = "",
    val id: String = "",
    val name: String = "",
    val version: Double? = null,
    val size: Long = 0,
    val sha256: String? = null,
    val preparing: Boolean = false,
    val file: String = "/api/phone-model/file",
    val format: ChatFormat = ChatFormat(),
    val sampling: Map<String, Double> = emptyMap(),
    @SerialName("max_reply_tokens") val maxReplyTokens: Int = 1024,
    val context: Int = 4096,
    @SerialName("min_ram_gb") val minRamGb: Double = 4.0,
    val hints: String = "",
    val memory: PhoneMemory = PhoneMemory(),
    val choices: List<PhoneChoice> = emptyList(),
) {
    /** "Flare 3" */
    val fullName get() = listOfNotNull(name.ifEmpty { "Flare" }, version?.let { if (it % 1.0 == 0.0) it.toInt().toString() else it.toString() }).joinToString(" ")
}

@Serializable
data class ChatFormat(
    @SerialName("user_open") val userOpen: String = "<|im_start|>user\n",
    @SerialName("turn_end") val turnEnd: String = "<|im_end|>\n",
    @SerialName("assistant_open") val assistantOpen: String = "<|im_start|>assistant\n",
    val stop: List<String> = listOf("<|im_end|>", "<|im_start|>", "<|endoftext|>"),
    @SerialName("notes_intro") val notesIntro: String = "Notes:\n",
    @SerialName("question_intro") val questionIntro: String = "\n\nQuestion: ",
)

/** A model the phone may pick (Flare: fast; Equinox: smarter, needs a phone with more memory) */
@Serializable
data class PhoneChoice(val id: String, val name: String = "", val version: Double? = null, val size: Long = 0,
                       @SerialName("min_ram_gb") val minRamGb: Double = 4.0, val tagline: String = "") {
    val fullName get() = listOfNotNull(name.ifEmpty { "Flare" }, version?.let { if (it % 1.0 == 0.0) it.toInt().toString() else it.toString() }).joinToString(" ")
    val sizeText get() = String.format(java.util.Locale.US, "%.1f GB", size / 1_073_741_824.0)
}

@Serializable
data class PhoneMemory(val on: Boolean = false, val title: String = "", val facts: List<String> = emptyList(), val personal: String = "")

/** One message of a chat on the phone */
@Serializable
data class LocalTurn(val mine: Boolean, val text: String)

/**
 * The prompt the phone's model reads, written exactly like the PC writes it for the same model (core/chat.py, ChatML): every earlier turn,
 * then the new question with what Emvryx remembers about the person in front (only when the question is about them, as user_memory.note
 * decides) and their own instructions after it (app_engine.run_turn's style_hint). Oldest turns are left out first when it does not fit.
 */
object LocalPrompt {
    private const val MEMORY_CHARS = 700

    /** A person's text can never contain a control marker: "<|im_end|>" typed in a message stays ordinary characters (allow_special=False) */
    fun clean(text: String) = text.replace("<|", "<​|")

    fun memoryNote(kit: PhoneKit, question: String): String? {
        val m = kit.memory
        if (!m.on || m.facts.isEmpty() || m.personal.isEmpty()) return null
        val personal = runCatching { Regex(m.personal, RegexOption.IGNORE_CASE) }.getOrNull() ?: return null
        if (!personal.containsMatchIn(question)) return null
        var text = ""
        for (f in m.facts.asReversed()) {                       // the newest facts first, as many as fit
            if (text.length + f.length + 1 > MEMORY_CHARS) break
            text = if (text.isEmpty()) f else "$f $text"
        }
        return text.ifEmpty { null }
    }

    fun question(kit: PhoneKit, question: String): String {
        val q = clean(question.trim()) + if (kit.hints.isNotBlank()) "\n\n" + kit.hints else ""
        val note = memoryNote(kit, question) ?: return q
        return kit.format.notesIntro + "[1] " + kit.memory.title + ": " + clean(note) + kit.format.questionIntro + q
    }

    /** The whole prompt for answering [question] after [history]; [count] gives a text's length in tokens (the model's own tokenizer). */
    fun build(kit: PhoneKit, history: List<LocalTurn>, question: String, count: (String) -> Int = { it.length / 3 }): String {
        val f = kit.format
        val last = f.userOpen + question(kit, question) + f.turnEnd + f.assistantOpen
        val pairs = mutableListOf<String>()
        var i = 0
        while (i < history.size) {
            val u = history[i]
            val a = history.getOrNull(i + 1)
            if (u.mine && a != null && !a.mine) {
                pairs += f.userOpen + clean(u.text) + f.turnEnd + f.assistantOpen + clean(a.text) + f.turnEnd
                i += 2
            } else i += 1
        }
        val room = kit.context - kit.maxReplyTokens
        var start = 0
        var prompt = pairs.joinToString("") + last
        while (start < pairs.size && count(prompt) > room) {          // the oldest turns are forgotten first
            start++
            prompt = pairs.subList(start, pairs.size).joinToString("") + last
        }
        return prompt
    }

    /** What to show of what the model has written so far: a thinking block left out, and nothing from a stop marker on.
     *  [done] is true when a stop marker was reached (the answer is over). */
    fun shown(raw: String, stops: List<String>): Pair<String, Boolean> {
        var text = raw
        var done = false
        stops.mapNotNull { s -> text.indexOf(s).takeIf { it >= 0 } }.minOrNull()?.let { text = text.substring(0, it); done = true }
        text = text.replace(Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL), "")
        val open = text.indexOf("<think>")
        if (open >= 0) text = text.substring(0, open)                  // still thinking: nothing to show yet from here
        // a stop marker that has only partly arrived ("<|im_") is held back until it is clear
        val hold = stops.maxOfOrNull { s -> (s.length - 1 downTo 1).firstOrNull { n -> text.endsWith(s.substring(0, n)) } ?: 0 } ?: 0
        return text.substring(0, text.length - hold).trimStart() to done
    }
}

/** Turns the model's pieces (UTF-8 bytes, a letter can be split across two pieces) into text */
class Utf8Joiner {
    private var pending = ByteArray(0)
    private val out = StringBuilder()

    val text: String get() = out.toString()

    fun add(bytes: ByteArray) {
        val all = pending + bytes
        var cut = all.size
        // the end of `all` may be the start of a letter whose other bytes come with the next piece: keep those back
        for (back in 1..minOf(3, all.size)) {
            val b = all[all.size - back].toInt() and 0xFF
            if (b and 0xC0 == 0x80) continue                            // a continuation byte: look further back
            val need = when {
                b and 0x80 == 0 -> 1
                b and 0xE0 == 0xC0 -> 2
                b and 0xF0 == 0xE0 -> 3
                b and 0xF8 == 0xF0 -> 4
                else -> 1
            }
            if (need > back) cut = all.size - back
            break
        }
        out.append(String(all, 0, cut, Charsets.UTF_8))
        pending = all.copyOfRange(cut, all.size)
    }
}
