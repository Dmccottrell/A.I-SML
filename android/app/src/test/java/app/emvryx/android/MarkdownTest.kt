package app.emvryx.android

import app.emvryx.android.ui.AppViewModel
import app.emvryx.android.ui.Block
import app.emvryx.android.ui.Markdown
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MarkdownTest {
    @Test
    fun proseAndCodeAreSplit() {
        val blocks = Markdown.blocks("Here it is:\n```python\nprint('hi')\n```\nDone.")
        assertEquals(listOf(Block.Prose("Here it is:"), Block.Code("python", "print('hi')"), Block.Prose("Done.")), blocks)
    }

    @Test
    fun anOpenFenceWhileStreamingStillShowsTheCode() {
        assertEquals(listOf(Block.Prose("Sure"), Block.Code("", "x = 1")), Markdown.blocks("Sure\n```\nx = 1"))
    }

    @Test
    fun boldAndCodeLoseTheirMarks() {
        assertEquals("a bold and code word", Markdown.inline("a **bold** and `code` word").text)
    }

    @Test
    fun aLoneStarIsLeftAlone() {
        assertEquals("2 * 3 = 6", Markdown.inline("2 * 3 = 6").text)
    }

    @Test
    fun serverAddresses() {
        assertEquals("https://chat.emvryx.app", AppViewModel.normalise("chat.emvryx.app/"))
        assertEquals("http://10.0.2.2:8000", AppViewModel.normalise(" http://10.0.2.2:8000 "))
        assertNull(AppViewModel.normalise("not an address"))
        assertNull(AppViewModel.normalise(""))
    }
}
