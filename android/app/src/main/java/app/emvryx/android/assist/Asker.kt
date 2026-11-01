// Answers a question that comes from OUTSIDE the main chat screen: the assistant bar, or a reply typed into a notification.
// It tries the PC first; if the PC is off it falls back to the small model that lives on the phone.
package app.emvryx.android.assist

import android.content.Context
import app.emvryx.android.EmvryxApp
import app.emvryx.android.data.OfflineException
import app.emvryx.android.data.ReplyEvent
import app.emvryx.android.local.LastChoice
import app.emvryx.android.local.PhoneModel

/**
 * A question asked from outside the app (the assistant bar, a reply typed in a notification): answered by the PC in a chat of its own (or in
 * [chatId]), with the model last used; with the PC off, by the model on the phone when it is there. [onText] gets the answer so far.
 * Returns (the chat's id on the PC, or null when the phone answered; the answer, or null with the reason in the second place on failure).
 */
object Asker {
    // The result: which chat it landed in, the answer text, and (only if it went wrong) a plain-words reason
    data class Answer(val chatId: Long?, val text: String?, val problem: String? = null)

    // "suspend" means this can pause while waiting for the network without freezing the screen; it must be called from a coroutine.
    suspend fun ask(ctx: Context, question: String, chatId: Long? = null, picture: Pair<String, ByteArray>? = null, onText: (String) -> Unit): Answer {
        // The app object holds the shared pieces: the server connection (api) and the on-phone model (phone)
        val app = ctx.applicationContext as EmvryxApp
        val api = app.api
        try {
            // Use the model last chosen in the app; if none yet, ask the PC which one it would pick
            val model = LastChoice.model(ctx).ifEmpty { api.state().model }
            // Carry on in the given chat, or open a new one
            val id = chatId ?: api.newChat(false, "")
            // A picture (for "Ask about this screen") is uploaded first and attached to the chat
            if (picture != null) api.setChatDocs(id, listOf(api.upload(picture.first, picture.second).id))
            val out = StringBuilder()          // the answer so far, built piece by piece as it streams in
            var failed: String? = null         // a problem reported by the PC, if any
            // Send the question and handle each event as the answer streams back
            api.send(id, question, model, LastChoice.effort(ctx)).collect { ev ->
                when (ev) {
                    // A new piece of the answer: add it and show the answer so far
                    is ReplyEvent.Piece -> { out.append(ev.text); onText(out.toString()) }
                    // The PC said it could not answer
                    is ReplyEvent.Failed -> failed = ev.message
                    // Other events (thinking, sources...) do not matter here
                    else -> Unit
                }
            }
            // Blank answers count as "no answer"
            return Answer(id, out.toString().takeIf { it.isNotBlank() }, failed)
        } catch (e: OfflineException) {
            // The PC could not be reached: try the model on the phone instead
            val phone = app.phone
            // Not possible if the phone model is not switched on / downloaded, or if a picture was sent (the phone cannot look at the screen here)
            if (!(phone.allowed && phone.status == PhoneModel.Status.Ready) || picture != null)
                return Answer(null, null, if (picture != null) "Emvryx is off, so it cannot look at the screen right now." else "Emvryx is off right now.")
            val c = phone.newChat()                                   // a chat that lives only on the phone
            val problem = phone.answer(c.id, question, onText)        // the phone's model writes the answer
            return Answer(null, phone.chats.firstOrNull { it.id == c.id }?.turns?.lastOrNull()?.text, problem)
        } catch (e: Exception) {
            // Anything else that went wrong: pass on its message in plain words
            return Answer(null, null, e.message ?: "That did not work.")
        }
    }
}
