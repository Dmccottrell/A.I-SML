// This file turns a sentence the person SAID (or typed) into something the phone can DO.
// Example: "set a timer for 10 minutes" becomes Command.Timer(600).
// It uses plain rules (regular expressions), not an AI model, so it is fast, works offline, and never does anything surprising.
package app.emvryx.android.local

/**
 * android_assistant: one thing said to the assistant bar, as a phone action (like Bixby or Gemini) or a question for Emvryx.
 *
 * A "sealed interface" is a list of every possible answer. Kotlin then forces any code that handles a Command to deal with all of them,
 * so we cannot forget one by accident.
 */
sealed interface Command {
    // "open WhatsApp" -> name = "whatsapp"
    data class OpenApp(val name: String) : Command
    // "set a timer for 10 minutes" -> seconds = 600
    data class Timer(val seconds: Int) : Command
    // "set an alarm for 7:30 pm" -> hour = 19, minute = 30 (24-hour clock)
    data class Alarm(val hour: Int, val minute: Int) : Command
    // "turn on the flashlight" -> on = true
    data class Torch(val on: Boolean) : Command
    // "navigate to the airport" -> place = "the airport"
    data class Navigate(val place: String) : Command
    // "search for cheap flights" -> query = "cheap flights"
    data class Search(val query: String) : Command
    // "play lo-fi on youtube" -> query = "lo-fi"
    data class YouTube(val query: String) : Command
    // "call 07700 900123" -> number = digits only (the dialler only SHOWS it; the person taps Call)
    data class Dial(val number: String) : Command
    // "wifi" / "bluetooth" / "battery"... -> which settings page to open
    data class Settings(val which: String) : Command
    // "take a photo" / "open the camera"
    data object Camera : Command
    // Anything that is not clearly a command: it is a question, so it goes to Emvryx to answer
    data class Ask(val text: String) : Command
    // Nothing was said (an empty sentence)
    data object None : Command
}

/** Plain rules, no model: a command must be clear, and anything else goes to Emvryx as a question (so nothing surprising happens). */
object VoiceCommands {
    // Number words people say out loud, with their value. "a" and "an" count as one ("a minute").
    private val NUMBERS = mapOf("a" to 1, "an" to 1, "one" to 1, "two" to 2, "three" to 3, "four" to 4, "five" to 5, "six" to 6, "seven" to 7,
        "eight" to 8, "nine" to 9, "ten" to 10, "eleven" to 11, "twelve" to 12, "fifteen" to 15, "twenty" to 20, "thirty" to 30, "forty" to 40,
        "forty-five" to 45, "fifty" to 50, "sixty" to 60, "ninety" to 90)
    // Finds "a number then a unit" in a sentence: "10 minutes", "two hours", "30 secs".
    // Group 1 is the number (digits or a word), group 2 is the unit.
    private val UNIT = Regex("""(\d+|[a-z-]+)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b""")

    /**
     * Read one sentence and say what it means. The rules are tried from the most specific to the most general;
     * the first one that matches wins. If none match, the sentence is returned as a question (Command.Ask).
     */
    fun parse(said: String): Command {
        // Remove spaces and the full stop / ! / ? at the end ("Open maps." -> "Open maps")
        val raw = said.trim().trimEnd('.', '!', '?').trim()
        // Nothing left means nothing was said
        if (raw.isEmpty()) return Command.None
        // A lower-case copy with single spaces and no trailing "please", so the rules below only have to match one spelling
        val t = raw.lowercase().replace(Regex("\\s+"), " ").removeSuffix(" please").trim()
        // Rule: flashlight. Matches "turn on the torch", "switch off flashlight", "torch on".
        Regex("""^(?:turn|switch) (on|off) (?:the )?(?:flashlight|torch)$|^(?:flashlight|torch) (on|off)$""").find(t)?.let {
            // The word on/off is in group 1 (first wording) or group 2 (second wording); whichever is not empty tells us which way to switch it
            return Command.Torch((it.groupValues[1].ifEmpty { it.groupValues[2] }) == "on")
        }
        // Rule: a settings page. Matches "wifi", "open bluetooth settings", "battery"...
        Regex("""^(?:open |turn on |turn off )?(?:the )?(wifi|wi-fi|bluetooth|internet|display|sound|battery)(?: settings)?$""").find(t)?.let {
            // "wi-fi" and "internet" both mean the Wi-Fi page, so they are renamed to "wifi"
            return Command.Settings(it.groupValues[1].replace("wi-fi", "wifi").let { w -> if (w == "internet") "wifi" else w })
        }
        // Rule: camera. Matches "take a photo", "take a selfie", "open the camera".
        if (Regex("""^(?:take a (?:picture|photo|selfie)|open (?:the )?camera)$""").matches(t)) return Command.Camera
        // Rule: timer. Only tried when the word "timer" is said; timer() works out the seconds (or null if it cannot).
        if (t.contains("timer")) timer(t)?.let { return Command.Timer(it) }
        // Rule: alarm. Matches "set an alarm for 7:30 pm", "wake me up at 6", "alarm at 6 am".
        Regex("""^(?:set (?:an |the )?alarm|wake me up|alarm) (?:for |at )(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$""").find(t)?.let {
            var h = it.groupValues[1].toInt()                            // the hour as said (1-12 or 0-23)
            val m = it.groupValues[2].ifEmpty { "0" }.toInt()            // the minutes; "6" with no minutes means 6:00
            val half = it.groupValues[3].replace(".", "")                // "p.m." -> "pm"
            if (half == "pm" && h < 12) h += 12                          // 7 pm -> 19 (but 12 pm stays 12, which is noon)
            if (half == "am" && h == 12) h = 0                           // 12 am -> 0 (midnight)
            // Only accept a real time; "25:99" falls through to the next rules and ends up as a question
            if (h in 0..23 && m in 0..59) return Command.Alarm(h, m)
        }
        // Rule: directions. "original(...)" keeps the capital letters the person used ("Chicago", not "chicago")
        Regex("""^(?:navigate|directions|take me|drive) to (.+)$""").find(t)?.let { return Command.Navigate(original(raw, it.groupValues[1])) }
        // Rule: YouTube. Matches "play <anything> on youtube".
        Regex("""^play (.+) on youtube$""").find(t)?.let { return Command.YouTube(original(raw, it.groupValues[1])) }
        // Rule: web search. Matches "search for ...", "search the web for ...", "google ...", "look up ...".
        Regex("""^(?:search (?:google |the web )?for|google|look up) (.+)$""").find(t)?.let { return Command.Search(original(raw, it.groupValues[1])) }
        // Rule: phone number. Needs at least 7 digit-like characters, so "call mum" is NOT a command (it has no number to show)
        Regex("""^(?:call|dial) ([\d\s()+-]{7,})$""").find(t)?.let { return Command.Dial(it.groupValues[1].filter { c -> c.isDigit() || c == '+' }) }
        // Rule: open an app. This is the most general rule, so it comes last. Matches "open maps", "launch the camera app"...
        Regex("""^(?:open|launch|start) (?:the )?(.+?)(?: app)?$""").find(t)?.let {
            val name = it.groupValues[1]
            if (name.split(' ').size <= 3) return Command.OpenApp(name)              // a short name; a sentence is a question
        }
        // Nothing matched: treat the whole sentence as a question for Emvryx
        return Command.Ask(raw)
    }

    /** The words as they were said (Chicago, not chicago) */
    private fun original(raw: String, lower: String): String {
        // Find where the lower-case words sit inside the original sentence...
        val i = raw.lowercase().indexOf(lower)
        // ...and cut the same piece out of the original, which still has its capital letters
        return if (i >= 0) raw.substring(i, i + lower.length) else lower
    }

    /** "10 minutes", "one minute and thirty seconds", "an hour and a half", "a 45 second timer" -> seconds */
    private fun timer(t: String): Int? {
        var total = 0                                                      // running total, in seconds
        for (m in UNIT.findAll(t)) {                                       // each "number + unit" found in the sentence
            // The number is digits ("10") or a word ("ten"); skip this piece if it is neither
            val n = m.groupValues[1].toIntOrNull() ?: NUMBERS[m.groupValues[1]] ?: continue
            // Multiply by the size of the unit: hours = 3600 seconds, minutes = 60, seconds = 1
            total += n * when {
                m.groupValues[2].startsWith("h") -> 3600
                m.groupValues[2].startsWith("m") -> 60
                else -> 1
            }
        }
        // "and a half" adds half of the LAST unit said: half an hour is 1800 s, half a minute is 30 s
        if (Regex("""\band a half\b""").containsMatchIn(t)) {
            val unit = UNIT.findAll(t).lastOrNull()?.groupValues?.get(2).orEmpty()
            total += if (unit.startsWith("h")) 1800 else if (unit.startsWith("m")) 30 else 0
        }
        // Only accept between 1 second and 24 hours; anything else is not a sensible timer, so null (= not understood)
        return total.takeIf { it in 1..86_400 }
    }
}
