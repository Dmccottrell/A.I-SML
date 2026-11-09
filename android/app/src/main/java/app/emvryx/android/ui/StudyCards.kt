package app.emvryx.android.ui

/**
 * study_cards: does a reply hold flashcards? At least three lines like "1. Term: meaning" (or rows of a two-column table), the same rule the
 * website uses (web/js/documents.js studyHasCards). The server decides for real when the deck is saved; this only decides whether the
 * Practise button shows. The practising itself is the website's own screen, opened inside the app.
 */
object StudyCards {
    // A numbered or bulleted line, a term of up to 200 characters, then a colon, a long dash or " - ", then the meaning.
    private val line = Regex("""^\s*(?:\d{1,3}[.)]|[-*•])\s+[^:\n]{1,200}?(?::|—| - )\s*\S""")
    // The row of dashes under a table's heading: not a card.
    private val tableRule = Regex("""^\s*\|?\s*:?-{2,}""")

    fun hasCards(text: String): Boolean {
        var n = 0
        for (l in text.split('\n')) {
            if (line.containsMatchIn(l) || (l.count { it == '|' } >= 2 && !tableRule.containsMatchIn(l))) n++
            if (n >= 3) return true
        }
        return false
    }

    /** What the website runs to save the cards in message [messageId] of chat [chatId] as a deck and start practising */
    fun practiseJs(chatId: Long, messageId: Long) = "studyFromChat($chatId, $messageId)"
}
