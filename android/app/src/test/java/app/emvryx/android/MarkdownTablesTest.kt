package app.emvryx.android

import app.emvryx.android.ui.Block
import app.emvryx.android.ui.Markdown
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Answers read like on the website (markdown.js): tables become tables, LaTeX maths becomes plain text */
class MarkdownTablesTest {
    @Test
    fun aTableIsItsOwnBlock() {
        val b = Markdown.blocks("Here:\n| Name | Age |\n|---|---|\n| Sam | 30 |\n| Jo | 41 |\nThat is all.")
        assertEquals(3, b.size)
        val t = b[1] as Block.Table
        assertEquals(listOf("Name", "Age"), t.head)
        assertEquals(listOf(listOf("Sam", "30"), listOf("Jo", "41")), t.rows)
        assertTrue(b[2] is Block.Prose)
    }

    @Test
    fun pipesInsideCodeAreNotATable() {
        val b = Markdown.blocks("```\na | b\n---|---\n```")
        assertEquals(1, b.size)
        assertTrue(b[0] is Block.Code)
    }

    @Test
    fun mathsBecomesPlainText() {
        assertEquals("So  x = 3/4  and the answer is **42**.", Markdown.math("So \\( x = \\frac{3}{4} \\) and the answer is \\boxed{42}."))
        assertEquals("(x+1)/2 ≤ 5", Markdown.math("\\frac{x+1}{2} \\leq 5"))
        assertEquals("Area = π r² ≈ 3.14 × 4", Markdown.math("Area = \\pi r^2 \\approx 3.14 \\times 4"))
        assertEquals("It costs \$5 and \$10.", Markdown.math("It costs \$5 and \$10."))
    }
}
