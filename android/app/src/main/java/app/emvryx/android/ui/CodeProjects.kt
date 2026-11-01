package app.emvryx.android.ui

import app.emvryx.android.data.CodeSessionRow

// CodeProjects.kt: small pure helper functions (no screen drawing) for naming VryxCode projects and grouping sessions under them.
// The projects organizer (flag vryxcode_projects; web/js/code.js vxIdeaName, vxFreeName, vxOrganizer): a new idea gets its own project,
// and the sessions list shows every project with its sessions under it, newest first.

// A regex (a text pattern) matching the polite or filler words at the very START of a request, all optional:
//   "please", "can you" / "could you", "make/build/create/write/code/give (me)", then "a/an/the/my/me".
// \s means a whitespace character (written with two backslashes because Kotlin strings need the backslash doubled).
// ^ anchors the match to the beginning of the text; (...)? makes each group optional.
private val IDEA_LEAD = Regex("^(please\\s+)?((can|could) you\\s+)?((make|build|create|write|code|give)( me)?\\s+)?((a|an|the|my|me)\\s+)?")
// A regex matching the first place where the idea's name should stop: a joining word surrounded by spaces
// (with, that, which, where, for, using, in, so, to) or a punctuation mark such as , . ; : ! ? ( ).
// (?: ... ) is a group that only groups and does not remember the match.
private val IDEA_CUT = Regex("\\s(?:with|that|which|where|for|using|in|so|to)\\s|[,.;:!?()]")

/**
 * Turns what the user typed into a short folder-style project name.
 * [text] is the request; returns lower-case words joined by dashes, at most 4 words and 32 characters,
 * or "new-project" if nothing usable is left. Example: "A bill splitter with tip and people" -> "bill-splitter".
 * It exists so each new idea can get its own project folder with a readable name.
 */
fun ideaName(text: String): String {
    // Lower-case the text and cut off the leading filler words ("please can you make a ...").
    val t = IDEA_LEAD.replaceFirst(text.lowercase(), "")
    // 1) split at the first stopping point and keep only the part before it ([0]);
    // 2) turn any character that is not a letter, digit, whitespace or dash into a space;
    // 3) trim, then split into words on runs of whitespace and drop empty pieces;
    // 4) keep at most the first 4 words so the name stays short.
    val words = IDEA_CUT.split(t)[0].replace(Regex("[^a-z0-9\\s-]"), " ").trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.take(4)
    // Join with dashes, cap at 32 characters, remove a dash left dangling at the end by the cut,
    // and fall back to "new-project" if nothing usable was left.
    return words.joinToString("-").take(32).trimEnd('-').ifEmpty { "new-project" }
}

/**
 * Makes a project name that is not taken yet.
 * [base] is the name we would like; [have] is every project name that already exists.
 * Returns [base] if it is free, otherwise base-2, base-3 ... the first one not in [have].
 */
fun freeName(base: String, have: Collection<String>): String {
    var n = base
    var i = 2
    // Keep trying base-2, base-3 ... until the name is not in the list (i++ adds one after each use).
    while (n in have) n = base + "-" + i++
    return n
}

/**
 * Builds the list the sessions screen shows: every project with its sessions under it.
 * [sessions] are the sessions as the server lists them (newest first); [projects] are all project folder names,
 * including ones that have no session yet. Returns pairs of (project name, its sessions): the project that was
 * busiest most recently comes first, projects with no session come last (ties are sorted by name).
 */
fun projectGroups(sessions: List<CodeSessionRow>, projects: List<String>): List<Pair<String, List<CodeSessionRow>>> {
    // Group the sessions by the project each belongs to (a Map from project name to its sessions).
    val by = sessions.groupBy { it.project }
    // latest(p) = the newest "updated" time among project p's sessions, or 0.0 if it has none (so empty projects sink to the bottom).
    val latest = { p: String -> by[p].orEmpty().maxOfOrNull { it.updated } ?: 0.0 }
    // Combine project names found in sessions with the known project list, remove duplicates, sort newest-activity first
    // (then by name so the order never jumps around), and pair each name with its sessions (empty list if none).
    return (by.keys + projects).distinct().sortedWith(compareByDescending<String> { latest(it) }.thenBy { it }).map { it to by[it].orEmpty() }
}
