package app.emvryx.android

import app.emvryx.android.local.PictureText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Pictures offline: the words read from a picture go with the question, and a picture alone asks what it says */
class PictureTextTest {
    @Test
    fun theWordsGoAfterTheQuestion() {
        val m = PictureText.withPicture("Is this bill right?", "Total: 42.50\nDue 3 Nov")
        assertTrue(m.startsWith("Is this bill right?\n\n[Text read from the picture I sent:]\n"))
        assertTrue(m.endsWith("Total: 42.50\nDue 3 Nov"))
    }

    @Test
    fun aPictureAloneAsksWhatItSays() {
        assertTrue(PictureText.withPicture("  ", "STOP").startsWith("What does this picture say?"))
    }

    @Test
    fun longTextIsCut() {
        val m = PictureText.withPicture("q", "x".repeat(10_000))
        assertEquals(PictureText.MAX_CHARS, m.substringAfter("sent:]\n").length)
    }

    @Test
    fun words() {
        assertEquals("3 words", PictureText.words(" a b\nc "))
        assertEquals("1 word", PictureText.words("hi"))
    }
}
