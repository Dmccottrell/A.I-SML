package app.emvryx.android.ui

import app.emvryx.android.data.CodeSessionRow

// The projects organizer (flag vryxcode_projects; web/js/code.js vxIdeaName, vxFreeName, vxOrganizer): a new idea gets its own project,
// and the sessions list shows every project with its sessions under it, newest first.

private val IDEA_LEAD = Regex("^(please\\s+)?((can|could) you\\s+)?((make|build|create|write|code|give)( me)?\\s+)?((a|an|the|my|me)\\s+)?")
private val IDEA_CUT = Regex("\\s(?:with|that|which|where|for|using|in|so|to)\\s|[,.;:!?()]")

/** "A bill splitter with tip and people" -> "bill-splitter": a short folder name made from the idea */
fun ideaName(text: String): String {
    val t = IDEA_LEAD.replaceFirst(text.lowercase(), "")
    val words = IDEA_CUT.split(t)[0].replace(Regex("[^a-z0-9\\s-]"), " ").trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.take(4)
    return words.joinToString("-").take(32).trimEnd('-').ifEmpty { "new-project" }
}

/** [base], or base-2, base-3... if a project already has that name */
fun freeName(base: String, have: Collection<String>): String {
    var n = base
    var i = 2
    while (n in have) n = base + "-" + i++
    return n
}

/** Every project with its sessions (as the server lists them, newest first), the most recently busy project first; projects with no session yet last */
fun projectGroups(sessions: List<CodeSessionRow>, projects: List<String>): List<Pair<String, List<CodeSessionRow>>> {
    val by = sessions.groupBy { it.project }
    val latest = { p: String -> by[p].orEmpty().maxOfOrNull { it.updated } ?: 0.0 }
    return (by.keys + projects).distinct().sortedWith(compareByDescending<String> { latest(it) }.thenBy { it }).map { it to by[it].orEmpty() }
}
