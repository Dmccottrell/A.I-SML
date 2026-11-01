package app.emvryx.android.local

/** android_assistant: one thing said to the assistant bar, as a phone action (like Bixby or Gemini) or a question for Emvryx */
sealed interface Command {
    data class OpenApp(val name: String) : Command
    data class Timer(val seconds: Int) : Command
    data class Alarm(val hour: Int, val minute: Int) : Command
    data class Torch(val on: Boolean) : Command
    data class Navigate(val place: String) : Command
    data class Search(val query: String) : Command
    data class YouTube(val query: String) : Command
    data class Dial(val number: String) : Command
    data class Settings(val which: String) : Command
    data object Camera : Command
    data class Ask(val text: String) : Command
    data object None : Command
}

/** Plain rules, no model: a command must be clear, and anything else goes to Emvryx as a question (so nothing surprising happens). */
object VoiceCommands {
    private val NUMBERS = mapOf("a" to 1, "an" to 1, "one" to 1, "two" to 2, "three" to 3, "four" to 4, "five" to 5, "six" to 6, "seven" to 7,
        "eight" to 8, "nine" to 9, "ten" to 10, "eleven" to 11, "twelve" to 12, "fifteen" to 15, "twenty" to 20, "thirty" to 30, "forty" to 40,
        "forty-five" to 45, "fifty" to 50, "sixty" to 60, "ninety" to 90)
    private val UNIT = Regex("""(\d+|[a-z-]+)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b""")

    fun parse(said: String): Command {
        val raw = said.trim().trimEnd('.', '!', '?').trim()
        if (raw.isEmpty()) return Command.None
        val t = raw.lowercase().replace(Regex("\\s+"), " ").removeSuffix(" please").trim()
        Regex("""^(?:turn|switch) (on|off) (?:the )?(?:flashlight|torch)$|^(?:flashlight|torch) (on|off)$""").find(t)?.let {
            return Command.Torch((it.groupValues[1].ifEmpty { it.groupValues[2] }) == "on")
        }
        Regex("""^(?:open |turn on |turn off )?(?:the )?(wifi|wi-fi|bluetooth|internet|display|sound|battery)(?: settings)?$""").find(t)?.let {
            return Command.Settings(it.groupValues[1].replace("wi-fi", "wifi").let { w -> if (w == "internet") "wifi" else w })
        }
        if (Regex("""^(?:take a (?:picture|photo|selfie)|open (?:the )?camera)$""").matches(t)) return Command.Camera
        if (t.contains("timer")) timer(t)?.let { return Command.Timer(it) }
        Regex("""^(?:set (?:an |the )?alarm|wake me up|alarm) (?:for |at )(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$""").find(t)?.let {
            var h = it.groupValues[1].toInt()
            val m = it.groupValues[2].ifEmpty { "0" }.toInt()
            val half = it.groupValues[3].replace(".", "")
            if (half == "pm" && h < 12) h += 12
            if (half == "am" && h == 12) h = 0
            if (h in 0..23 && m in 0..59) return Command.Alarm(h, m)
        }
        Regex("""^(?:navigate|directions|take me|drive) to (.+)$""").find(t)?.let { return Command.Navigate(original(raw, it.groupValues[1])) }
        Regex("""^play (.+) on youtube$""").find(t)?.let { return Command.YouTube(original(raw, it.groupValues[1])) }
        Regex("""^(?:search (?:google |the web )?for|google|look up) (.+)$""").find(t)?.let { return Command.Search(original(raw, it.groupValues[1])) }
        Regex("""^(?:call|dial) ([\d\s()+-]{7,})$""").find(t)?.let { return Command.Dial(it.groupValues[1].filter { c -> c.isDigit() || c == '+' }) }
        Regex("""^(?:open|launch|start) (?:the )?(.+?)(?: app)?$""").find(t)?.let {
            val name = it.groupValues[1]
            if (name.split(' ').size <= 3) return Command.OpenApp(name)              // a short name; a sentence is a question
        }
        return Command.Ask(raw)
    }

    /** The words as they were said (Chicago, not chicago) */
    private fun original(raw: String, lower: String): String {
        val i = raw.lowercase().indexOf(lower)
        return if (i >= 0) raw.substring(i, i + lower.length) else lower
    }

    /** "10 minutes", "one minute and thirty seconds", "an hour and a half", "a 45 second timer" -> seconds */
    private fun timer(t: String): Int? {
        var total = 0
        for (m in UNIT.findAll(t)) {
            val n = m.groupValues[1].toIntOrNull() ?: NUMBERS[m.groupValues[1]] ?: continue
            total += n * when {
                m.groupValues[2].startsWith("h") -> 3600
                m.groupValues[2].startsWith("m") -> 60
                else -> 1
            }
        }
        if (Regex("""\band a half\b""").containsMatchIn(t)) {
            val unit = UNIT.findAll(t).lastOrNull()?.groupValues?.get(2).orEmpty()
            total += if (unit.startsWith("h")) 1800 else if (unit.startsWith("m")) 30 else 0
        }
        return total.takeIf { it in 1..86_400 }
    }
}
