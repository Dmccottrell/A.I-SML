package app.emvryx.android.local

import kotlinx.serialization.Serializable

/**
 * VryxCode drafts on the phone (android_offline_model): with the PC off, the phone's model plans and writes the files for a request. A phone
 * cannot run or test them, so they wait here; when the PC is back they go to it (POST /api/code/drafts) and "Run in VryxCode" writes them into
 * the project, runs and tests them there (coding/code_drafts.py).
 */
@Serializable
data class DraftFile(val path: String, val content: String)

@Serializable
data class CodeDraft(val id: Long, val project: String, val request: String, val files: List<DraftFile> = emptyList(), val note: String = "",
                     val serverId: String? = null, val made: Long = 0, val model: String = "")

object DraftWriter {
    /** Asked of the phone's model with the request: whole files in a form that can be read back, and how to run them */
    const val INSTRUCTION = "[You are writing code on a phone that cannot run it; the person will run it on their PC later. Write the complete " +
        "files this needs, as few and as small as will do. For each file write a line FILE: followed by its path (like FILE: index.html), then " +
        "the whole file in a ``` block. After the files, two or three sentences on how to run and test it. Do not leave parts out.]"

    private val FILE = Regex("""^\W*file\s*:?\s*`?([\w.\-/]+\.[\w]+|[\w.\-/]*Makefile|[\w.\-/]*Dockerfile)`?\W*$""", RegexOption.IGNORE_CASE)
    private val FENCE = Regex("""^\s*```\s*([\w+#.-]*)\s*$""")
    private val DEFAULT = mapOf("html" to "index.html", "css" to "style.css", "javascript" to "app.js", "js" to "app.js", "python" to "main.py",
                                "py" to "main.py", "typescript" to "app.ts", "ts" to "app.ts", "java" to "Main.java", "kotlin" to "Main.kt",
                                "go" to "main.go", "rust" to "main.rs", "c" to "main.c", "cpp" to "main.cpp", "c++" to "main.cpp", "sql" to "schema.sql",
                                "bash" to "run.sh", "sh" to "run.sh", "json" to "data.json", "php" to "index.php", "ruby" to "main.rb")

    /** The files and the note in what the model wrote. A code block with no FILE line before it is named after its language. */
    fun parse(text: String): Pair<List<DraftFile>, String> {
        val files = linkedMapOf<String, String>()
        val note = StringBuilder()
        var pending: String? = null
        var inBlock = false
        var lang = ""
        val body = StringBuilder()
        for (line in text.lines()) {
            if (inBlock) {
                if (line.trim() == "```") {
                    inBlock = false
                    val name = pending ?: DEFAULT[lang.lowercase()] ?: "file${files.size + 1}.txt"
                    files[unique(files.keys, name)] = body.toString().trimEnd('\n') + "\n"
                    pending = null
                } else body.append(line).append('\n')
                continue
            }
            val f = FILE.find(line)
            val fence = FENCE.find(line)
            when {
                f != null -> pending = f.groupValues[1].removePrefix("./")
                fence != null -> { inBlock = true; lang = fence.groupValues[1]; body.clear() }
                line.isNotBlank() -> note.append(line.trim()).append(' ')
            }
        }
        return files.map { DraftFile(it.key, it.value) } to note.toString().trim().take(2000)
    }

    private fun unique(have: Set<String>, name: String): String {
        if (name !in have) return name
        val dot = name.lastIndexOf('.')
        var i = 2
        while (true) {
            val n = if (dot > 0) name.substring(0, dot) + i + name.substring(dot) else name + i
            if (n !in have) return n
            i++
        }
    }

    /** The same sync id for the same draft, so one sent again after a lost answer is kept once */
    fun syncId(d: CodeDraft) = "draft-${d.id}"
}
