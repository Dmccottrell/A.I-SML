/*
 * LocalPrompt.kt: the "words in, words out" helpers for the model that runs on the phone.
 * It holds the data shapes the server sends for the phone model (PhoneKit and friends), builds the exact prompt text the model reads
 * (LocalPrompt), and joins the model's raw byte pieces back into readable text (Utf8Joiner).
 * It does no network or file work itself; PhoneModel.kt calls it.
 * Terms: a "token" is a small chunk of text (a word or part of one) that a model reads and writes; a "prompt" is the full text given to the model.
 */
package app.emvryx.android.local

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * GET /api/phone-model (app/phone_model.py): the model file for this phone and how to answer with it, as the PC does.
 * "Serializable" means the library can turn JSON text from the server into this object (and back). Every field has a default,
 * so a missing field in the JSON just gets that default instead of crashing.
 * available: whether a phone model can be offered right now. message: a note to show when it cannot. id/name/version: which model.
 * size/sha256: the file's size in bytes and its fingerprint, used to check the download is whole and unchanged.
 * preparing: the server is still making the file. file: the download path. format: the chat markers the model expects.
 * sampling: the settings that make the model's word choice more or less random. maxReplyTokens: the longest answer allowed.
 * context: how many tokens the model can hold in mind at once. minRamGb: the least phone memory needed.
 * hints: extra instructions added after each question. memory: what Emvryx remembers about the person. choices: other models to pick from.
 */
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
    /** "Flare 3": the name (or "Flare" when empty) plus the version, shown as a whole number when it has no decimals (3.0 becomes 3) */
    val fullName get() = listOfNotNull(name.ifEmpty { "Flare" }, version?.let { if (it % 1.0 == 0.0) it.toInt().toString() else it.toString() }).joinToString(" ")
}

/**
 * The special marker words that wrap each chat turn (ChatML style), so the model can tell who is speaking.
 * The defaults match the PC; the server can send different ones. stop: if the model writes any of these, the answer is over.
 * notesIntro/questionIntro: the lead-in text placed before a memory note and before the real question.
 */
@Serializable
data class ChatFormat(
    @SerialName("user_open") val userOpen: String = "<|im_start|>user\n",
    @SerialName("turn_end") val turnEnd: String = "<|im_end|>\n",
    @SerialName("assistant_open") val assistantOpen: String = "<|im_start|>assistant\n",
    val stop: List<String> = listOf("<|im_end|>", "<|im_start|>", "<|endoftext|>"),
    @SerialName("notes_intro") val notesIntro: String = "Notes:\n",
    @SerialName("question_intro") val questionIntro: String = "\n\nQuestion: ",
)

/**
 * A model the phone may pick (Flare: fast; Equinox: smarter, needs a phone with more memory).
 * size is in bytes; minRamGb is the least phone memory (in gigabytes) it needs; tagline is a short selling line for the picker.
 */
@Serializable
data class PhoneChoice(val id: String, val name: String = "", val version: Double? = null, val size: Long = 0,
                       @SerialName("min_ram_gb") val minRamGb: Double = 4.0, val tagline: String = "") {
    // Same name rule as PhoneKit.fullName: name plus version, without a trailing ".0".
    val fullName get() = listOfNotNull(name.ifEmpty { "Flare" }, version?.let { if (it % 1.0 == 0.0) it.toInt().toString() else it.toString() }).joinToString(" ")
    // Bytes to gigabytes (1_073_741_824 = 1024 x 1024 x 1024 bytes in a GB), one decimal. Locale.US forces a "." as the decimal mark on every phone.
    val sizeText get() = String.format(java.util.Locale.US, "%.1f GB", size / 1_073_741_824.0)
}

/**
 * What Emvryx remembers about the person. on: memory is switched on. title: the label shown with a remembered note.
 * facts: short remembered sentences, oldest first. personal: a regex (a text pattern) that says when a question is about the person.
 */
@Serializable
data class PhoneMemory(val on: Boolean = false, val title: String = "", val facts: List<String> = emptyList(), val personal: String = "")

/** One message of a chat on the phone: mine is true for the person's message and false for the model's answer; text is the words. */
@Serializable
data class LocalTurn(val mine: Boolean, val text: String)

/**
 * The prompt the phone's model reads, written exactly like the PC writes it for the same model (core/chat.py, ChatML): every earlier turn,
 * then the new question with what Emvryx remembers about the person in front (only when the question is about them, as user_memory.note
 * decides) and their own instructions after it (app_engine.run_turn's style_hint). Oldest turns are left out first when it does not fit.
 */
object LocalPrompt {
    // The most characters of remembered facts that may be added to one question (keeps the prompt short).
    private const val MEMORY_CHARS = 700

    /**
     * A person's text can never contain a control marker: "<|im_end|>" typed in a message stays ordinary characters (allow_special=False).
     * It breaks every "<|" by slipping an invisible zero-width space between the two characters, so typed text can never look like a real marker.
     */
    fun clean(text: String) = text.replace("<|", "<​|")

    /**
     * Picks the remembered facts to show with this question, or null for none.
     * In: the phone kit (holds the memory) and the person's question. Out: the facts joined into one short text, or null.
     * Why: memory is only added when the question is about the person, so unrelated questions stay clean and short.
     */
    fun memoryNote(kit: PhoneKit, question: String): String? {
        // Nothing to add when memory is off or empty.
        val m = kit.memory
        if (!m.on || m.facts.isEmpty() || m.personal.isEmpty()) return null
        // Build the "is this about the person?" pattern, ignoring capital letters. runCatching turns a broken pattern from the server into null
        // instead of a crash, and then we simply add no memory.
        val personal = runCatching { Regex(m.personal, RegexOption.IGNORE_CASE) }.getOrNull() ?: return null
        // The question does not look personal: add no memory.
        if (!personal.containsMatchIn(question)) return null
        // Collect facts while they fit in MEMORY_CHARS (the +1 is the space between facts). Walking the list backwards puts the newest first.
        var text = ""
        for (f in m.facts.asReversed()) {                       // the newest facts first, as many as fit
            if (text.length + f.length + 1 > MEMORY_CHARS) break
            // Each older fact is placed in front, so the final text still reads oldest to newest.
            text = if (text.isEmpty()) f else "$f $text"
        }
        return text.ifEmpty { null }
    }

    /**
     * The text of the person's new message as the model should read it.
     * In: the kit and the raw question. Out: the cleaned question plus the server's hints, with a memory note in front when one applies.
     */
    fun question(kit: PhoneKit, question: String): String {
        // Clean the question, then put the person's own instructions (hints) after it, after a blank line.
        val q = clean(question.trim()) + if (kit.hints.isNotBlank()) "\n\n" + kit.hints else ""
        // No memory note: the cleaned question is the whole message.
        val note = memoryNote(kit, question) ?: return q
        // With a note, the model sees "Notes: [1] title: note" first and then the question.
        return kit.format.notesIntro + "[1] " + kit.memory.title + ": " + clean(note) + kit.format.questionIntro + q
    }

    /**
     * The whole prompt for answering [question] after [history]; [count] gives a text's length in tokens (the model's own tokenizer).
     * Out: one long text with every earlier question and answer, then the new question, ending where the model should start writing.
     * Why: the model can only hold [PhoneKit.context] tokens, and part of that must stay free for the reply, so old turns are dropped when needed.
     * The default [count] guesses one token per 3 characters, only used when no real tokenizer is given.
     */
    fun build(kit: PhoneKit, history: List<LocalTurn>, question: String, count: (String) -> Int = { it.length / 3 }): String {
        val f = kit.format
        // The new question, opened as a user turn and closed, followed by the opening of the assistant turn that the model will complete.
        val last = f.userOpen + question(kit, question) + f.turnEnd + f.assistantOpen
        // Turn the history into complete question+answer pairs, in order. A message that has no partner is skipped.
        val pairs = mutableListOf<String>()
        var i = 0
        while (i < history.size) {
            val u = history[i]
            val a = history.getOrNull(i + 1)
            // A pair is a person message followed by a model message. Take both and move on two places; otherwise (for example two person messages in a row) skip just this one message.
            if (u.mine && a != null && !a.mine) {
                pairs += f.userOpen + clean(u.text) + f.turnEnd + f.assistantOpen + clean(a.text) + f.turnEnd
                i += 2
            } else i += 1
        }
        // room = the tokens the prompt may use: the whole context minus what is kept free for the model's reply.
        val room = kit.context - kit.maxReplyTokens
        // Drop pairs from the front (oldest) until the prompt fits in room, or no pairs are left.
        var start = 0
        var prompt = pairs.joinToString("") + last
        while (start < pairs.size && count(prompt) > room) {          // the oldest turns are forgotten first
            start++
            prompt = pairs.subList(start, pairs.size).joinToString("") + last
        }
        return prompt
    }

    /**
     * What to show of what the model has written so far: a thinking block left out, and nothing from a stop marker on.
     * In: the raw text so far and the stop markers. Out: the text to show and [done] (true when a stop marker was reached, so the answer is over).
     * It is called again and again while the answer streams in, so it must cope with half-arrived markers.
     */
    fun shown(raw: String, stops: List<String>): Pair<String, Boolean> {
        var text = raw
        var done = false
        // Find the earliest stop marker in the text; cut everything from there and remember that the answer is over.
        stops.mapNotNull { s -> text.indexOf(s).takeIf { it >= 0 } }.minOrNull()?.let { text = text.substring(0, it); done = true }
        // Remove finished thinking blocks. In this regex, .*? means "as little as possible" and DOT_MATCHES_ALL lets the dot match line breaks too.
        text = text.replace(Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL), "")
        // A thinking block that has started but not ended yet is cut off below.
        val open = text.indexOf("<think>")
        if (open >= 0) text = text.substring(0, open)                  // still thinking: nothing to show yet from here
        // a stop marker that has only partly arrived ("<|im_") is held back until it is clear
        // For each stop marker, find the longest start of it (from length-1 down to 1 letter) that the text ends with; keep the biggest over all markers.
        // That many characters at the end are not shown yet, because they may turn out to be a marker.
        val hold = stops.maxOfOrNull { s -> (s.length - 1 downTo 1).firstOrNull { n -> text.endsWith(s.substring(0, n)) } ?: 0 } ?: 0
        // Show the text minus the held-back end, without leading blanks, together with the done flag.
        return text.substring(0, text.length - hold).trimStart() to done
    }
}

/**
 * Turns the model's pieces (UTF-8 bytes, a letter can be split across two pieces) into text.
 * UTF-8 is the way text is stored as bytes: simple letters take 1 byte, others (accents, emoji) take 2 to 4. A model streams small
 * pieces, so the bytes of one letter can arrive in two different pieces. Decoding half a letter would give a broken character, so the
 * unfinished end is kept in [pending] until the rest arrives. Use: call add() for each piece and read [text] any time.
 */
class Utf8Joiner {
    // Bytes of a letter that is not complete yet.
    private var pending = ByteArray(0)
    // All the text decoded so far.
    private val out = StringBuilder()

    // The text decoded so far (never contains a half letter).
    val text: String get() = out.toString()

    /** Adds the next piece of bytes: decodes all complete letters now and keeps an unfinished last letter for next time. */
    fun add(bytes: ByteArray) {
        // The old leftover bytes plus the new ones; cut is where decoding will stop (the whole thing unless the end is unfinished).
        val all = pending + bytes
        var cut = all.size
        // the end of `all` may be the start of a letter whose other bytes come with the next piece: keep those back
        for (back in 1..minOf(3, all.size)) {
            // Look at up to the last 3 bytes, from the end backwards. "and 0xFF" turns the signed byte (-128..127) into a plain 0..255 number.
            val b = all[all.size - back].toInt() and 0xFF
            // Bit patterns: a byte that starts with binary 10 is a "continuation" (the middle or end of a letter). Mask 0xC0 keeps the top two bits.
            // The first byte of a letter says how long the letter is: 0xxxxxxx = 1 byte, 110xxxxx = 2, 1110xxxx = 3, 11110xxx = 4.
            if (b and 0xC0 == 0x80) continue                            // a continuation byte: look further back
            // How many bytes this letter needs in total, read from the top bits of its first byte (an odd byte counts as 1 so it is never held forever).
            val need = when {
                b and 0x80 == 0 -> 1
                b and 0xE0 == 0xC0 -> 2
                b and 0xF0 == 0xE0 -> 3
                b and 0xF8 == 0xF0 -> 4
                else -> 1
            }
            // The letter needs more bytes than we have from here to the end: stop decoding before it and keep it for the next piece.
            if (need > back) cut = all.size - back
            break
        }
        // Decode only the complete part.
        out.append(String(all, 0, cut, Charsets.UTF_8))
        pending = all.copyOfRange(cut, all.size)
    }
}
