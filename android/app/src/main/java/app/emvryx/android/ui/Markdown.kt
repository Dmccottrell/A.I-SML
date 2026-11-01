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

// Markdown.kt: turns the text of a chat reply into things the screen can draw. Markdown is a way of writing formatting as plain text
// (**bold**, `code`, # headings, | tables |). The model's replies arrive in that form. This file does two jobs:
//   1. Markdown.blocks cuts a reply into prose, code blocks and tables (the Block types below);
//   2. Markdown.inline / spans / math style the text inside a block (bold, italics, inline code, headings, bullets, maths).
// It is a small renderer on purpose: "enough Markdown for chat". It mirrors the website's web/js/markdown.js so both look alike.

/** A reply split into prose and fenced code, the two things replies are made of. Enough Markdown for chat, not a full renderer. */
// "sealed interface" = a fixed list of kinds; each kind below is one possible piece of a reply.
sealed interface Block {
    // Ordinary text. [text] is the Markdown text, still with its **bold** marks etc.
    data class Prose(val text: String) : Block
    // A fenced code block (between ``` lines). [lang] is the language word after the opening fence (may be empty), [text] is the code.
    data class Code(val lang: String, val text: String) : Block
    /** A Markdown table (markdown.js, flag chat_fixes on the website): the header row and the rows, cell by cell */
    data class Table(val head: List<String>, val rows: List<List<String>>) : Block
}

// Matches the divider line under a table header, such as |---|:---:|. A regex is a text pattern. Reading it left to right:
// optional spaces and a leading |, then a cell of 2 or more dashes with optional : (alignment marks), then more | cells, then an optional closing |.
private val TABLE_RULE = Regex("^\\s*\\|?\\s*:?-{2,}:?\\s*(\\|\\s*:?-{2,}:?\\s*)*\\|?\\s*$")
// Splits one table row such as "| a | b |" into its trimmed cell texts ["a", "b"] (drops the outer | first).
private fun cells(line: String) = line.trim().removePrefix("|").removeSuffix("|").split('|').map { it.trim() }

/** A table as the website shows it: a header row on a tinted strip, lines between cells, sideways scrolling when it is wide */
@Composable
fun MdTable(t: Block.Table) {
    // Rounded outline for the whole table.
    val shape = RoundedCornerShape(10.dp)
    // Column = stack the rows. horizontalScroll lets a wide table slide sideways instead of squeezing.
    Column(Modifier.clip(shape).border(1.dp, Emvryx.line, shape).horizontalScroll(rememberScrollState())) {
        // The header counts as row 0, followed by the body rows; n is the row number.
        listOf(t.head).plus(t.rows).forEachIndexed { n, row ->
            // One table row; only the header row (n == 0) gets the tinted background.
            Row(Modifier.then(if (n == 0) Modifier.background(Emvryx.surface2) else Modifier)) {
                // One cell per header column, so every row has the same number of columns.
                t.head.indices.forEach { k ->
                    // A missing cell (short row) becomes empty text. Each cell is 140 dp wide with a thin border; the header is semi-bold. Cell text may contain **bold** etc., so it goes through Markdown.inline.
                    Text(Markdown.inline(row.getOrElse(k) { "" }), Modifier.width(140.dp).border(0.5.dp, Emvryx.line).padding(horizontal = 10.dp, vertical = 6.dp),
                        fontWeight = if (n == 0) FontWeight.SemiBold else null, fontSize = 14.sp, color = Emvryx.text)
                }
            }
        }
    }
}

/** The reply-text tools: [blocks] splits a reply, [inline] styles a paragraph, [math] cleans up LaTeX. Plain functions, no state. */
object Markdown {
    /**
     * Splits a whole reply into [Block]s, in order: prose, code and tables. Goes line by line, remembering whether it is inside a
     * code fence. [text] may be unfinished (the reply is still streaming in), which is allowed.
     */
    fun blocks(text: String): List<Block> {
        // out collects the finished blocks. prose and code collect the lines of the block being read. lang is null when we are outside a code fence, otherwise the fence's language word.
        val out = mutableListOf<Block>()
        val prose = StringBuilder()
        val code = StringBuilder()
        var lang: String? = null
        // Finishes the prose being collected: trims blank lines at the ends and, if anything is left, adds it to out.
        fun flushProse() {
            val p = prose.toString().trim('\n')
            if (p.isNotBlank()) out += Block.Prose(p)
            prose.clear()
        }
        // Go through the reply one line at a time (i is the current line number).
        val lines = text.split('\n')
        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            // A fence line starts with three backticks (the mark that opens or closes a code block).
            val fence = line.trimStart().startsWith("```")
            // A table starts where a line has a | and the next line is a divider like |---|---| (checked cheaply for a '-' first, then with the regex). Not inside code.
            if (lang == null && !fence && '|' in line && i + 1 < lines.size && '-' in lines[i + 1] && TABLE_RULE.matches(lines[i + 1])) {
                flushProse()
                // Header cells come from this line; then skip the header and the divider (i += 2) and read body rows while lines still contain | and are not blank.
                val head = cells(line)
                val rows = mutableListOf<List<String>>()
                i += 2
                while (i < lines.size && '|' in lines[i] && lines[i].isNotBlank()) rows += cells(lines[i++])
                // Table done; continue = go straight to the next line without running the code below.
                out += Block.Table(head, rows)
                continue
            }
            i++
            // Not a table: step to the next line and decide what this line is.
            when {
                // Opening fence: save the prose so far and remember the language word after the three backticks.
                lang == null && fence -> {
                    flushProse()
                    lang = line.trimStart().removePrefix("```").trim()
                }
                // Closing fence: the code collected is complete, so add it as a Code block and go back to prose.
                lang != null && fence -> {
                    out += Block.Code(lang, code.toString().trimEnd('\n'))
                    code.clear()
                    lang = null
                }
                // Inside a fence: this line is code.
                lang != null -> code.append(line).append('\n')
                // Outside a fence: this line is prose.
                else -> prose.append(line).append('\n')
            }
        }
        if (lang != null) out += Block.Code(lang, code.toString().trimEnd('\n'))     // still streaming: show the open block
        flushProse()
        return out
    }

    /**
     * **bold**, `code` and # headings inside prose. [text] may hold several lines; the result is one styled string.
     * Also turns "- item" / "* item" bullets into a bullet dot.
     */
    fun inline(text: String): AnnotatedString = buildAnnotatedString {
        text.split('\n').forEachIndexed { n, raw ->
            if (n > 0) append('\n')
            // A heading is 1 to 6 # marks plus a space at the start of the line. If found, cut the marks off the text.
            val heading = Regex("^#{1,6} ").find(raw)
            val line = if (heading != null) raw.substring(heading.range.last + 1) else raw
            // A bullet line starts with optional spaces, then - or * and a space; keep the indent and swap the mark for a round bullet.
            val bullet = Regex("^(\\s*)[-*] ").find(line)
            val body = if (bullet != null) bullet.groupValues[1] + "•  " + line.substring(bullet.range.last + 1) else line
            // Headings are drawn bigger (18 sp) and semi-bold; other lines are styled normally.
            if (heading != null) withStyle(SpanStyle(fontWeight = FontWeight.SemiBold, fontSize = 18.sp)) { spans(body) } else spans(body)
        }
    }

    /** The LaTeX a model writes for maths, as plain readable text (markdown.js mdMath): 3/4, x², √(2), the boxed answer in bold */
    // [line] is one line of prose; the result has the LaTeX commands swapped for readable symbols. Lines with no LaTeX come back untouched.
    fun math(line: String): String {
        // Quick check: does the line contain anything that looks like LaTeX (a backslash command, $$ or ^)? If not, leave it alone.
        if (!Regex("\\\\[a-zA-Z()\\[\\]%,;:!]|\\$\\$|\\^").containsMatchIn(line)) return line
        var t = line
        val simple = Regex("^\\w+$")
        // \boxed{x} (the final answer box) becomes **x**, shown in bold.
        t = Regex("\\\\boxed\\{([^{}]*)\\}").replace(t) { "**" + it.groupValues[1] + "**" }
        // \frac{a}{b} (or \dfrac) becomes a/b; a part that is not a single word gets brackets, e.g. (x+1)/2.
        t = Regex("\\\\d?frac\\{([^{}]+)\\}\\{([^{}]+)\\}").replace(t) {
            val (a, b) = it.destructured
            (if (simple.matches(a)) a else "($a)") + "/" + (if (simple.matches(b)) b else "($b)")
        }
        // \sqrt{x} becomes the square-root sign followed by (x).
        t = Regex("\\\\sqrt\\{([^{}]+)\\}").replace(t) { "\u221a(" + it.groupValues[1] + ")" }
        // \text{..}, \mathrm{..} and similar wrappers are dropped, keeping the words inside.
        t = Regex("\\\\(?:text|mathrm|mathbf|operatorname)\\{([^{}]*)\\}").replace(t) { it.groupValues[1] }
        // Pairs of (pattern, replacement) applied one after the other: multiplication, dot, division, plus-minus, <=, >=, !=, approx, pi, infinity,
        // degrees, squared and cubed, percent, LaTeX spacing commands, \left and \right, and leftover bracket/$$ marks. (?![a-z]) means "not followed by a letter",
        // so \leq is changed but \length is not. The odd-looking codes in the replacements are the Unicode symbols themselves.
        listOf("\\\\times" to "\u00d7", "\\\\cdot" to "\u00b7", "\\\\div" to "\u00f7", "\\\\pm" to "\u00b1", "\\\\leq?(?![a-z])" to "\u2264",
            "\\\\geq?(?![a-z])" to "\u2265", "\\\\neq?(?![a-z])" to "\u2260", "\\\\approx" to "\u2248", "\\\\pi(?![a-z])" to "\u03c0", "\\\\infty" to "\u221e",
            "\\\\degree|\\^\\{?\\\\circ\\}?" to "\u00b0", "\\^\\{?2\\}?(?![\\d{])" to "\u00b2", "\\^\\{?3\\}?(?![\\d{])" to "\u00b3", "\\\\%" to "%",
            "\\\\[,;:!]|\\\\q?quad" to " ", "\\\\left|\\\\right" to "", "\\\\[()\\[\\]]|\\$\\$" to "").forEach { (re, to) -> t = Regex(re).replace(t, to) }
        return t
    }

    /**
     * Appends [raw] to the string being built, turning **bold**, *italic* and `code` into styled pieces (an AnnotatedString is text
     * with styles attached to ranges). Walks the characters with an index and, at each spot, checks which mark starts there.
     */
    private fun AnnotatedString.Builder.spans(raw: String) {
        // Splitting on backticks gives alternating pieces: even numbers are outside `code`, odd are inside. Only the outside pieces get maths cleaned, so code is never altered.
        val s = raw.split('`').mapIndexed { n, part -> if (n % 2 == 0) math(part) else part }.joinToString("`")     // maths is cleaned outside `code` only
        var i = 0
        while (i < s.length) {
            when {
                // **bold**: the text starts with ** and there is a closing ** after at least one character. Show what is between in semi-bold.
                s.startsWith("**", i) && s.indexOf("**", i + 2) > i + 2 -> {
                    val end = s.indexOf("**", i + 2)
                    withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(s.substring(i + 2, end)) }
                    i = end + 2
                }
                // *italic*: a single * not followed by a space or another *, with a closing * that is not preceded by a space (so "2 * 3 * 4" is not italic).
                s[i] == '*' && i + 1 < s.length && s[i + 1] != ' ' && s[i + 1] != '*' && s.indexOf('*', i + 1) > i + 1 && s[s.indexOf('*', i + 1) - 1] != ' ' -> {
                    val end = s.indexOf('*', i + 1)
                    withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(s.substring(i + 1, end)) }
                    i = end + 1
                }
                // `code`: a backtick pair; show the inside in a monospace font with a tinted background.
                s[i] == '`' && s.indexOf('`', i + 1) > i + 1 -> {
                    val end = s.indexOf('`', i + 1)
                    withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = Emvryx.surface2, color = Emvryx.text)) {
                        append(s.substring(i + 1, end))
                    }
                    i = end + 1
                }
                else -> {
                    // Plain character: copy it and move on by one.
                    append(s[i])
                    i++
                }
            }
        }
    }
}
