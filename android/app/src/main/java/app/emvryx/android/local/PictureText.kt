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
    const val MAX_CHARS = 4000

    /** The words in the picture, or null when none could be read */
    suspend fun read(context: Context, uri: Uri): String? = suspendCancellableCoroutine { c ->
        val image = runCatching { InputImage.fromFilePath(context, uri) }.getOrNull()
        if (image == null) {
            c.resume(null)
            return@suspendCancellableCoroutine
        }
        val reader = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        reader.process(image)
            .addOnSuccessListener { r -> if (c.isActive) c.resume(r.text.trim().ifEmpty { null }); reader.close() }
            .addOnFailureListener { if (c.isActive) c.resume(null); reader.close() }
    }

    /** The message the model gets: the question, then what the picture says (no question: what does it say?) */
    fun withPicture(question: String, text: String): String {
        val q = question.trim().ifEmpty { "What does this picture say? Explain it briefly." }
        return q + "\n\n[Text read from the picture I sent:]\n" + text.trim().take(MAX_CHARS)
    }

    /** "36 words" */
    fun words(text: String) = text.split(Regex("\\s+")).count { it.isNotBlank() }.let { if (it == 1) "1 word" else "$it words" }
}
