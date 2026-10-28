package app.emvryx.android

import app.emvryx.android.local.CodeDraft
import app.emvryx.android.local.DraftWriter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** VryxCode drafts on the phone: the files are read back out of what the model wrote */
class DraftWriterTest {
    @Test
    fun filesAndTheNote() {
        val text = """
            Here is a small tip calculator.

            FILE: index.html
            ```html
            <h1>Tips</h1>
            <script src="app.js"></script>
            ```

            **FILE: `js/app.js`**
            ```javascript
            console.log("tip");
            ```

            Open index.html in a browser and type a bill.
        """.trimIndent()
        val (files, note) = DraftWriter.parse(text)
        assertEquals(listOf("index.html", "js/app.js"), files.map { it.path })
        assertEquals("<h1>Tips</h1>\n<script src=\"app.js\"></script>\n", files[0].content)
        assertTrue(note.contains("Open index.html in a browser"))
    }

    @Test
    fun aBlockWithNoNameIsNamedAfterItsLanguage() {
        val (files, _) = DraftWriter.parse("```python\nprint(1)\n```\n```python\nprint(2)\n```")
        assertEquals(listOf("main.py", "main2.py"), files.map { it.path })
    }

    @Test
    fun anUnfinishedBlockIsNotAFile() {
        assertTrue(DraftWriter.parse("FILE: a.py\n```python\nprint(1)\n").first.isEmpty())
    }

    @Test
    fun theSyncIdStaysTheSame() {
        val d = CodeDraft(7, "p", "r")
        assertEquals(DraftWriter.syncId(d), DraftWriter.syncId(d.copy(serverId = "x")))
    }
}
