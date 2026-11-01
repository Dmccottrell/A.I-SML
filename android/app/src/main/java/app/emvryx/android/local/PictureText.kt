/*
 * PictureText.kt: reads the words out of a picture on the phone itself (OCR, "optical character recognition", means turning
 * the letters in a photo into text). The phone's own model cannot look at images, so the chat code reads the picture's words here
 * and hands those words to the model as ordinary text. Uses Google ML Kit's text reader that ships inside the app.
 */
package app.emvryx.android.local

import android.content.Context
import android.net.Uri
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * android_offline_model: the text in a picture (a screenshot, a letter, a sign), read on the phone itself, so the phone's model can answer
 * about it with the PC off. Nothing leaves the phone: the reading model is part of the app. The phone's model cannot see pictures, only
 * the words read from them.
 */
object PictureText {
    // The most characters of picture text sent to the model; more would crowd out the question in its limited memory.
    const val MAX_CHARS = 4000

    /**
     * The words in the picture, or null when none could be read.
     * In: the Android context (needed to open the file) and the picture's address (uri). Out: the text, or null.
     * "suspend" marks a coroutine function: one that can pause while it waits and let the app keep running, then continue later.
     * suspendCancellableCoroutine turns the reader's callback style (do it later, call me back) into a simple pause-and-resume:
     * c.resume(value) wakes the waiting caller with that value.
     */
    suspend fun read(context: Context, uri: Uri): String? = suspendCancellableCoroutine { c ->
        // Open the picture; a file that is missing or not an image gives null instead of a crash.
        val image = runCatching { InputImage.fromFilePath(context, uri) }.getOrNull()
        if (image == null) {
            c.resume(null)
            return@suspendCancellableCoroutine
        }
        // Make a Latin-letters text reader (it works offline) and give it the picture. It answers through one of the two listeners below.
        val reader = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        reader.process(image)
            // Success: hand back the trimmed text (null when it is blank). c.isActive guards against resuming a caller that already gave up
            // (cancelled), which would crash. Always close the reader to free its memory.
            .addOnSuccessListener { r -> if (c.isActive) c.resume(r.text.trim().ifEmpty { null }); reader.close() }
            // The reader failed: answer null, and close it.
            .addOnFailureListener { if (c.isActive) c.resume(null); reader.close() }
    }

    /**
     * The message the model gets: the question, then what the picture says (no question: what does it say?).
     * In: the person's question (may be empty) and the words read from the picture. Out: one message text.
     */
    fun withPicture(question: String, text: String): String {
        // With no typed question, ask a default one.
        val q = question.trim().ifEmpty { "What does this picture say? Explain it briefly." }
        // The label tells the model where the words came from; take(MAX_CHARS) cuts very long text.
        return q + "\n\n[Text read from the picture I sent:]\n" + text.trim().take(MAX_CHARS)
    }

    /**
     * "36 words": a short count of the words in a text, shown to the person.
     * The regex \s+ means "one or more white-space characters" (spaces, tabs, line breaks), so the text is split into words; blanks are not counted.
     */
    fun words(text: String) = text.split(Regex("\\s+")).count { it.isNotBlank() }.let { if (it == 1) "1 word" else "$it words" }
}
