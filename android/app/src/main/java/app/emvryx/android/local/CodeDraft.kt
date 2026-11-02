// CodeDraft.kt: lets the phone draft code while the PC is off. The phone's small model writes files; DraftWriter reads the
// model's answer back into separate files; they are saved on the phone and later sent to the PC to be run and tested in VryxCode.

package app.emvryx.android.local

import kotlinx.serialization.Serializable

/**
 * VryxCode drafts on the phone (android_offline_model): with the PC off, the phone's model plans and writes the files for a request. A phone
 * cannot run or test them, so they wait here; when the PC is back they go to it (POST /api/code/drafts) and "Run in VryxCode" writes them into
 * the project, runs and tests them there (coding/code_drafts.py).
 * [DraftFile] below is one file: its path inside the project and its text.
 */
@Serializable
data class DraftFile(val path: String, val content: String)

/**
 * One draft: [id] is the phone's own number, [project] and [request] say what it was for, [files] are what the model wrote, [note] is its short
 * how-to-run text, [serverId] is set once the PC has it, [made] is when it was written and [model] which model wrote it.
 */
@Serializable
data class CodeDraft(val id: Long, val project: String, val request: String, val files: List<DraftFile> = emptyList(), val note: String = "",
                     val serverId: String? = null, val made: Long = 0, val model: String = "")

/** Asks the phone's model for code in a fixed layout, and reads that layout back into files. */
object DraftWriter {
    /** Asked of the phone's model with the request: whole files in a form that can be read back (a FILE: line, then the file in a fenced block), and how to run them */
    const val INSTRUCTION = "[You are writing code on a phone that cannot run it; the person will run it on their PC later. Write the complete " +
        "files this needs, as few and as small as will do. For each file write a line FILE: followed by its path (like FILE: index.html), then " +
        "the whole file in a ``` block. After the files, two or three sentences on how to run and test it. Do not leave parts out.]"

    // FILE matches a line naming a file: optional symbols, the word "file", an optional colon, then a name (backticks allowed).
    // A name is word characters, dots, dashes or slashes ending in .extension, or a Makefile / Dockerfile. IGNORE_CASE accepts "File:" too.
    // This is a triple-quoted raw string, so the backslashes are real regex backslashes.
    private val FILE = Regex("""^\W*file\s*:?\s*`?([\w.\-/]+\.[\w]+|[\w.\-/]*Makefile|[\w.\-/]*Dockerfile)`?\W*$""", RegexOption.IGNORE_CASE)
    // FENCE matches a line that is just three backticks (a code block fence), with an optional language word after it (like kotlin or c++).
    private val FENCE = Regex("""^\s*```\s*([\w+#.-]*)\s*$""")
    // A file name to use when the model gives a code block with no FILE line, chosen by the block's language word.
    private val DEFAULT = mapOf("html" to "index.html", "css" to "style.css", "javascript" to "app.js", "js" to "app.js", "python" to "main.py",
                                "py" to "main.py", "typescript" to "app.ts", "ts" to "app.ts", "java" to "Main.java", "kotlin" to "Main.kt",
                                "go" to "main.go", "rust" to "main.rs", "c" to "main.c", "cpp" to "main.cpp", "c++" to "main.cpp", "sql" to "schema.sql",
                                "bash" to "run.sh", "sh" to "run.sh", "json" to "data.json", "php" to "index.php", "ruby" to "main.rb")

    /** The files and the note in what the model wrote. A code block with no FILE line before it is named after its language. Returns (files, note). */
    fun parse(text: String): Pair<List<DraftFile>, String> {
        // linkedMapOf keeps files in the order they were written (path -> contents).
        val files = linkedMapOf<String, String>()
        // Everything outside code blocks becomes the note.
        val note = StringBuilder()
        // State while reading line by line: the file name seen but not yet used, whether we are inside a ``` block, its language, and its lines so far.
        var pending: String? = null
        var inBlock = false
        var lang = ""
        val body = StringBuilder()
        // Go through the answer one line at a time.
        for (line in text.lines()) {
            // Inside a code block: a closing fence ends the file; any other line is file content.
            if (inBlock) {
                if (line.trim() == "```") {
                    inBlock = false
                    // Name by: the FILE line, else the language's default, else file1.txt, file2.txt...
                    val name = pending ?: DEFAULT[lang.lowercase()] ?: "file${files.size + 1}.txt"
                    // Store the contents with exactly one newline at the end. unique() avoids overwriting a file of the same name.
                    files[unique(files.keys, name)] = body.toString().trimEnd('\n') + "\n"
                    pending = null
                } else body.append(line).append('\n')
                continue
            }
            // Outside a block: is this line a FILE: line, a fence that opens a block, or normal text?
            val f = FILE.find(line)
            val fence = FENCE.find(line)
            // A FILE line sets the name for the next block (a leading ./ is dropped). A fence starts a block. Other non-empty text goes in the note.
            when {
                f != null -> pending = f.groupValues[1].removePrefix("./")
                fence != null -> { inBlock = true; lang = fence.groupValues[1]; body.clear() }
                line.isNotBlank() -> note.append(line.trim()).append(' ')
            }
        }
        // Turn the map into a list of DraftFile; the note is trimmed and capped at 2,000 characters.
        return files.map { DraftFile(it.key, it.value) } to note.toString().trim().take(2000)
    }

    // If [name] is taken, adds a number before the extension: main.py, main2.py, main3.py...
    private fun unique(have: Set<String>, name: String): String {
        if (name !in have) return name
        // Where the extension starts (a dot at position 0, like .gitignore, is not an extension).
        val dot = name.lastIndexOf('.')
        var i = 2
        // Try 2, 3, 4... until a free name is found.
        while (true) {
            val n = if (dot > 0) name.substring(0, dot) + i + name.substring(dot) else name + i
            if (n !in have) return n
            i++
        }
    }

    /** The same sync id for the same draft, so one sent again after a lost answer is kept once (the server uses it to spot a repeat) */
    fun syncId(d: CodeDraft) = "draft-${d.id}"
}
