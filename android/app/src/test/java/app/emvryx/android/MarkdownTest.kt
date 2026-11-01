// Unit tests for the basic markdown reading in ui/Markdown.kt (splitting text into prose and code, removing **bold** and `code` marks)
// and for AppViewModel.normalise (turning what a person types as the server address into a proper web address).
package app.emvryx.android

import app.emvryx.android.ui.AppViewModel
import app.emvryx.android.ui.Block
import app.emvryx.android.ui.Markdown
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Tests markdown block splitting, inline marks and server address cleanup. */
class MarkdownTest {
    /** Proves text with a ``` code block in the middle is split into prose, then code (with its language), then prose. */
    @Test
    fun proseAndCodeAreSplit() {
        val blocks = Markdown.blocks("Here it is:\n```python\nprint('hi')\n```\nDone.")
        assertEquals(listOf(Block.Prose("Here it is:"), Block.Code("python", "print('hi')"), Block.Prose("Done.")), blocks)
    }

    /** Proves a code block whose closing ``` has not arrived yet (the answer is still streaming in) is still shown as code. */
    @Test
    fun anOpenFenceWhileStreamingStillShowsTheCode() {
        assertEquals(listOf(Block.Prose("Sure"), Block.Code("", "x = 1")), Markdown.blocks("Sure\n```\nx = 1"))
    }

    /** Proves the ** and ` marks are removed from the shown text (the bold or code look is added as a style, not as characters). */
    @Test
    fun boldAndCodeLoseTheirMarks() {
        assertEquals("a bold and code word", Markdown.inline("a **bold** and `code` word").text)
    }

    /** Proves a single star used as a multiplication sign is kept, not treated as the start of italic text. */
    @Test
    fun aLoneStarIsLeftAlone() {
        assertEquals("2 * 3 = 6", Markdown.inline("2 * 3 = 6").text)
    }

    /** Proves normalise() adds https:// and drops a trailing slash, keeps an existing http:// address, trims spaces, and rejects non-addresses with null. */
    @Test
    fun serverAddresses() {
        // no scheme: https:// is added and the trailing "/" removed
        assertEquals("https://chat.emvryx.app", AppViewModel.normalise("chat.emvryx.app/"))
        // surrounding spaces are trimmed; a typed http:// address and its port are kept as they are
        assertEquals("http://10.0.2.2:8000", AppViewModel.normalise(" http://10.0.2.2:8000 "))
        // spaces inside, or nothing at all, cannot be an address
        assertNull(AppViewModel.normalise("not an address"))
        assertNull(AppViewModel.normalise(""))
    }
}
