// Unit tests for local/PictureText.kt: when the PC is off, the phone reads the words out of a picture (OCR) and passes them to its model as text.
// Only the plain text helpers are tested here (withPicture and words); the picture reading itself needs a real phone.
package app.emvryx.android

import app.emvryx.android.local.PictureText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Pictures offline: the words read from a picture go with the question, and a picture alone asks what it says */
class PictureTextTest {
    /** Proves the question comes first, then a label line, then the words read from the picture. */
    @Test
    fun theWordsGoAfterTheQuestion() {
        val m = PictureText.withPicture("Is this bill right?", "Total: 42.50\nDue 3 Nov")
        assertTrue(m.startsWith("Is this bill right?\n\n[Text read from the picture I sent:]\n"))
        assertTrue(m.endsWith("Total: 42.50\nDue 3 Nov"))
    }

    /** Proves a blank question (only spaces) is replaced by a default question about what the picture says. */
    @Test
    fun aPictureAloneAsksWhatItSays() {
        assertTrue(PictureText.withPicture("  ", "STOP").startsWith("What does this picture say?"))
    }

    /** Proves very long picture text is cut to MAX_CHARS characters so it cannot crowd out the question. */
    @Test
    fun longTextIsCut() {
        // 10,000 letters in, but only MAX_CHARS may come out after the label line (which ends with "sent:]" and a newline)
        val m = PictureText.withPicture("q", "x".repeat(10_000))
        assertEquals(PictureText.MAX_CHARS, m.substringAfter("sent:]\n").length)
    }

    /** Proves words() counts words split by any spaces or line breaks, ignoring blanks, and says "1 word" in the singular. */
    @Test
    fun words() {
        // spaces at both ends and a line break between words do not add extra words
        assertEquals("3 words", PictureText.words(" a b\nc "))
        assertEquals("1 word", PictureText.words("hi"))
    }
}
