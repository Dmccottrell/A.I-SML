// Unit tests for the table and maths parts of ui/Markdown.kt: the Android app turns a model's markdown-style text into blocks (prose, code,
// tables) and turns LaTeX maths (a typesetting notation like \frac{3}{4}) into plain readable text, the same way the website's markdown.js does.
package app.emvryx.android

import app.emvryx.android.ui.Block
import app.emvryx.android.ui.Markdown
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Answers read like on the website (markdown.js): tables become tables, LaTeX maths becomes plain text */
class MarkdownTablesTest {
    /** Proves a markdown table in the middle of text becomes its own Table block, with the heading cells and row cells split out. */
    @Test
    fun aTableIsItsOwnBlock() {
        // The setup: a line of text, a table (header row, a "|---|---|" divider row, two data rows), and a closing line.
        val b = Markdown.blocks("Here:\n| Name | Age |\n|---|---|\n| Sam | 30 |\n| Jo | 41 |\nThat is all.")
        // three blocks in order: prose, table, prose
        assertEquals(3, b.size)
        val t = b[1] as Block.Table
        assertEquals(listOf("Name", "Age"), t.head)
        assertEquals(listOf(listOf("Sam", "30"), listOf("Jo", "41")), t.rows)
        assertTrue(b[2] is Block.Prose)
    }

    /** Proves something that looks like a table but sits inside a ``` code fence stays code. */
    @Test
    fun pipesInsideCodeAreNotATable() {
        val b = Markdown.blocks("```\na | b\n---|---\n```")
        assertEquals(1, b.size)
        assertTrue(b[0] is Block.Code)
    }

    /** Proves Markdown.math() rewrites common LaTeX into plain text (fractions, symbols, powers) and leaves ordinary dollar prices alone. */
    @Test
    fun mathsBecomesPlainText() {
        // \( \) brackets are dropped, \frac{3}{4} becomes 3/4 and \boxed{42} becomes bold
        assertEquals("So  x = 3/4  and the answer is **42**.", Markdown.math("So \\( x = \\frac{3}{4} \\) and the answer is \\boxed{42}."))
        // a fraction with a non-simple top gets brackets, and \leq becomes the real symbol
        assertEquals("(x+1)/2 ≤ 5", Markdown.math("\\frac{x+1}{2} \\leq 5"))
        // \pi, ^2, \approx and \times become π, ², ≈ and ×
        assertEquals("Area = π r² ≈ 3.14 × 4", Markdown.math("Area = \\pi r^2 \\approx 3.14 \\times 4"))
        // a single $ (money, not maths) must not be touched; "\$" is just a dollar sign written inside a Kotlin string
        assertEquals("It costs \$5 and \$10.", Markdown.math("It costs \$5 and \$10."))
    }
}
