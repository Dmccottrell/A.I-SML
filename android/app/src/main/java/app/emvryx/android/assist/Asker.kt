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
    data class Answer(val chatId: Long?, val text: String?, val problem: String? = null)

    suspend fun ask(ctx: Context, question: String, chatId: Long? = null, picture: Pair<String, ByteArray>? = null, onText: (String) -> Unit): Answer {
        val app = ctx.applicationContext as EmvryxApp
        val api = app.api
        try {
            val model = LastChoice.model(ctx).ifEmpty { api.state().model }
            val id = chatId ?: api.newChat(false, "")
            if (picture != null) api.setChatDocs(id, listOf(api.upload(picture.first, picture.second).id))
            val out = StringBuilder()
            var failed: String? = null
            api.send(id, question, model, LastChoice.effort(ctx)).collect { ev ->
                when (ev) {
                    is ReplyEvent.Piece -> { out.append(ev.text); onText(out.toString()) }
                    is ReplyEvent.Failed -> failed = ev.message
                    else -> Unit
                }
            }
            return Answer(id, out.toString().takeIf { it.isNotBlank() }, failed)
        } catch (e: OfflineException) {
            val phone = app.phone
            if (!(phone.allowed && phone.status == PhoneModel.Status.Ready) || picture != null)
                return Answer(null, null, if (picture != null) "Emvryx is off, so it cannot look at the screen right now." else "Emvryx is off right now.")
            val c = phone.newChat()
            val problem = phone.answer(c.id, question, onText)
            return Answer(null, phone.chats.firstOrNull { it.id == c.id }?.turns?.lastOrNull()?.text, problem)
        } catch (e: Exception) {
            return Answer(null, null, e.message ?: "That did not work.")
        }
    }
}
