package app.emvryx.android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
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
    /** A Markdown table (markdown.js, flag chat_fixes on the website): the header row and the rows, cell by cell */
    data class Table(val head: List<String>, val rows: List<List<String>>) : Block
}

private val TABLE_RULE = Regex("^\\s*\\|?\\s*:?-{2,}:?\\s*(\\|\\s*:?-{2,}:?\\s*)*\\|?\\s*$")
private fun cells(line: String) = line.trim().removePrefix("|").removeSuffix("|").split('|').map { it.trim() }

/** A table as the website shows it: a header row on a tinted strip, lines between cells, sideways scrolling when it is wide */
@Composable
fun MdTable(t: Block.Table) {
    val shape = RoundedCornerShape(10.dp)
    Column(Modifier.clip(shape).border(1.dp, Emvryx.line, shape).horizontalScroll(rememberScrollState())) {
        listOf(t.head).plus(t.rows).forEachIndexed { n, row ->
            Row(Modifier.then(if (n == 0) Modifier.background(Emvryx.surface2) else Modifier)) {
                t.head.indices.forEach { k ->
                    Text(Markdown.inline(row.getOrElse(k) { "" }), Modifier.width(140.dp).border(0.5.dp, Emvryx.line).padding(horizontal = 10.dp, vertical = 6.dp),
                        fontWeight = if (n == 0) FontWeight.SemiBold else null, fontSize = 14.sp, color = Emvryx.text)
                }
            }
        }
    }
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
        val lines = text.split('\n')
        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            val fence = line.trimStart().startsWith("```")
            if (lang == null && !fence && '|' in line && i + 1 < lines.size && '-' in lines[i + 1] && TABLE_RULE.matches(lines[i + 1])) {
                flushProse()
                val head = cells(line)
                val rows = mutableListOf<List<String>>()
                i += 2
                while (i < lines.size && '|' in lines[i] && lines[i].isNotBlank()) rows += cells(lines[i++])
                out += Block.Table(head, rows)
                continue
            }
            i++
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

    /** The LaTeX a model writes for maths, as plain readable text (markdown.js mdMath): 3/4, x², √(2), the boxed answer in bold */
    fun math(line: String): String {
        if (!Regex("\\\\[a-zA-Z()\\[\\]%,;:!]|\\$\\$|\\^").containsMatchIn(line)) return line
        var t = line
        val simple = Regex("^\\w+$")
        t = Regex("\\\\boxed\\{([^{}]*)\\}").replace(t) { "**" + it.groupValues[1] + "**" }
        t = Regex("\\\\d?frac\\{([^{}]+)\\}\\{([^{}]+)\\}").replace(t) {
            val (a, b) = it.destructured
            (if (simple.matches(a)) a else "($a)") + "/" + (if (simple.matches(b)) b else "($b)")
        }
        t = Regex("\\\\sqrt\\{([^{}]+)\\}").replace(t) { "\u221a(" + it.groupValues[1] + ")" }
        t = Regex("\\\\(?:text|mathrm|mathbf|operatorname)\\{([^{}]*)\\}").replace(t) { it.groupValues[1] }
        listOf("\\\\times" to "\u00d7", "\\\\cdot" to "\u00b7", "\\\\div" to "\u00f7", "\\\\pm" to "\u00b1", "\\\\leq?(?![a-z])" to "\u2264",
            "\\\\geq?(?![a-z])" to "\u2265", "\\\\neq?(?![a-z])" to "\u2260", "\\\\approx" to "\u2248", "\\\\pi(?![a-z])" to "\u03c0", "\\\\infty" to "\u221e",
            "\\\\degree|\\^\\{?\\\\circ\\}?" to "\u00b0", "\\^\\{?2\\}?(?![\\d{])" to "\u00b2", "\\^\\{?3\\}?(?![\\d{])" to "\u00b3", "\\\\%" to "%",
            "\\\\[,;:!]|\\\\q?quad" to " ", "\\\\left|\\\\right" to "", "\\\\[()\\[\\]]|\\$\\$" to "").forEach { (re, to) -> t = Regex(re).replace(t, to) }
        return t
    }

    private fun AnnotatedString.Builder.spans(raw: String) {
        val s = raw.split('`').mapIndexed { n, part -> if (n % 2 == 0) math(part) else part }.joinToString("`")     // maths is cleaned outside `code` only
        var i = 0
        while (i < s.length) {
            when {
                s.startsWith("**", i) && s.indexOf("**", i + 2) > i + 2 -> {
                    val end = s.indexOf("**", i + 2)
                    withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(s.substring(i + 2, end)) }
                    i = end + 2
                }
                s[i] == '*' && i + 1 < s.length && s[i + 1] != ' ' && s[i + 1] != '*' && s.indexOf('*', i + 1) > i + 1 && s[s.indexOf('*', i + 1) - 1] != ' ' -> {
                    val end = s.indexOf('*', i + 1)
                    withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(s.substring(i + 1, end)) }
                    i = end + 1
                }
                s[i] == '`' && s.indexOf('`', i + 1) > i + 1 -> {
                    val end = s.indexOf('`', i + 1)
                    withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = Emvryx.surface2, color = Emvryx.text)) {
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
