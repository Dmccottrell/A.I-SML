// Unit tests for local/CodeDraft.kt (DraftWriter): when the PC is off, the phone's model writes code files as plain text, and DraftWriter
// reads that text back into separate files plus a short note. These tests check that reading step.
package app.emvryx.android

import app.emvryx.android.local.CodeDraft
import app.emvryx.android.local.DraftWriter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** VryxCode drafts on the phone: the files are read back out of what the model wrote */
class DraftWriterTest {
    /** Proves a model answer with two "FILE:" headings (in two different styles) and some prose is split into two files and a note. */
    @Test
    fun filesAndTheNote() {
        // The setup: a fake model answer. trimIndent() removes the shared left indent so the text is as the model would write it.
        // The first file is announced as "FILE: index.html", the second as bold with backticks, "**FILE: `js/app.js`**": both must work.
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
        // the file names come out in the order written, with the bold marks and backticks removed
        assertEquals(listOf("index.html", "js/app.js"), files.map { it.path })
        // the content is what was inside the ``` block, ending with exactly one newline
        assertEquals("<h1>Tips</h1>\n<script src=\"app.js\"></script>\n", files[0].content)
        // text outside the code blocks (and not a FILE line) is gathered into the note
        assertTrue(note.contains("Open index.html in a browser"))
    }

    /** Proves a code block with no FILE line gets a default name from its language, and a second one gets a number so it does not clash. */
    @Test
    fun aBlockWithNoNameIsNamedAfterItsLanguage() {
        val (files, _) = DraftWriter.parse("```python\nprint(1)\n```\n```python\nprint(2)\n```")
        assertEquals(listOf("main.py", "main2.py"), files.map { it.path })
    }

    /** Proves a code block that was never closed (the model was cut off) is dropped instead of saved as a half file. */
    @Test
    fun anUnfinishedBlockIsNotAFile() {
        assertTrue(DraftWriter.parse("FILE: a.py\n```python\nprint(1)\n").first.isEmpty())
    }

    /** Proves the id used to avoid sending a draft twice depends only on the draft's own id, not on whether the PC has given it a serverId yet. */
    @Test
    fun theSyncIdStaysTheSame() {
        val d = CodeDraft(7, "p", "r")
        assertEquals(DraftWriter.syncId(d), DraftWriter.syncId(d.copy(serverId = "x")))
    }
}
