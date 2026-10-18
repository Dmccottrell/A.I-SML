package app.emvryx.android.ui

import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.sp
import app.emvryx.android.ui.theme.Emvryx

/** A reply split into prose and fenced code, the two things replies are made of. Enough Markdown for chat, not a full renderer. */
sealed interface Block {
    data class Prose(val text: String) : Block
    data class Code(val lang: String, val text: String) : Block
}

object Markdown {
    fun blocks(text: String): List<Block> {
        val out = mutableListOf<Block>()
        val prose = StringBuilder()
        val code = StringBuilder()
        var lang: String? = null
        fun flushProse() {
            val p = prose.toString().trim('\n')
            if (p.isNotBlank()) out += Block.Prose(p)
            prose.clear()
        }
        for (line in text.split('\n')) {
            val fence = line.trimStart().startsWith("```")
            when {
                lang == null && fence -> {
                    flushProse()
                    lang = line.trimStart().removePrefix("```").trim()
                }
                lang != null && fence -> {
                    out += Block.Code(lang, code.toString().trimEnd('\n'))
                    code.clear()
                    lang = null
                }
                lang != null -> code.append(line).append('\n')
                else -> prose.append(line).append('\n')
            }
        }
        if (lang != null) out += Block.Code(lang, code.toString().trimEnd('\n'))     // still streaming: show the open block
        flushProse()
        return out
    }

    /** **bold**, `code` and # headings inside prose. */
    fun inline(text: String): AnnotatedString = buildAnnotatedString {
        text.split('\n').forEachIndexed { n, raw ->
            if (n > 0) append('\n')
            val heading = Regex("^#{1,6} ").find(raw)
            val line = if (heading != null) raw.substring(heading.range.last + 1) else raw
            val bullet = Regex("^(\\s*)[-*] ").find(line)
            val body = if (bullet != null) bullet.groupValues[1] + "•  " + line.substring(bullet.range.last + 1) else line
            if (heading != null) withStyle(SpanStyle(fontWeight = FontWeight.SemiBold, fontSize = 18.sp)) { spans(body) } else spans(body)
        }
    }

    private fun AnnotatedString.Builder.spans(s: String) {
        var i = 0
        while (i < s.length) {
            when {
                s.startsWith("**", i) && s.indexOf("**", i + 2) > i + 2 -> {
                    val end = s.indexOf("**", i + 2)
                    withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(s.substring(i + 2, end)) }
                    i = end + 2
                }
                s[i] == '`' && s.indexOf('`', i + 1) > i + 1 -> {
                    val end = s.indexOf('`', i + 1)
                    withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = Emvryx.surface2, color = Emvryx.accentText)) {
                        append(s.substring(i + 1, end))
                    }
                    i = end + 1
                }
                else -> {
                    append(s[i])
                    i++
                }
            }
        }
    }
}
