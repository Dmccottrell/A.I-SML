package app.emvryx.android.ui

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.emvryx.android.BuildConfig
import app.emvryx.android.EmvryxApp
import app.emvryx.android.data.ApiException
import app.emvryx.android.data.AppState
import app.emvryx.android.data.ChatSummary
import app.emvryx.android.data.ModelCard
import app.emvryx.android.data.OfflineException
import app.emvryx.android.data.ReplyEvent
import app.emvryx.android.data.Usage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

sealed interface Screen {
    data object Starting : Screen
    data class Off(val resting: Boolean, val server: String) : Screen
    data object SignIn : Screen
    data object Chat : Screen
}

enum class SignInWay { Password, Key }

/** One bubble on the chat screen. [streaming] is the reply still being written; [model] is the id of the model that wrote it. */
data class Bubble(val key: Long, val mine: Boolean, val text: String, val streaming: Boolean = false, val cut: Boolean = false, val model: String = "")

class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val session = (app as EmvryxApp).session
    private val api = (app as EmvryxApp).api

    var screen by mutableStateOf<Screen>(Screen.Starting)
        private set

    // ---- sign-in
    var server by mutableStateOf(session.serverUrl ?: BuildConfig.DEFAULT_SERVER)
    var signInBusy by mutableStateOf(false)
        private set
    var signInError by mutableStateOf<String?>(null)
        private set
    var twoStepTicket by mutableStateOf<String?>(null)
        private set

    // ---- chat
    var state by mutableStateOf<AppState?>(null)
        private set
    var chats by mutableStateOf<List<ChatSummary>>(emptyList())
        private set
    var model by mutableStateOf("")
        private set
    var effort by mutableStateOf("balanced")
        private set
    var chatId by mutableStateOf<Long?>(null)
        private set
    var title by mutableStateOf("New chat")
        private set
    val bubbles = mutableStateListOf<Bubble>()
    var streaming by mutableStateOf(false)
        private set
    var working by mutableStateOf<String?>(null)          // "Loading Solstice...", "Thinking..."
        private set
    var notice by mutableStateOf<String?>(null)           // a refusal or "off" message shown above the box
        private set

    private var replyJob: Job? = null
    private var nextKey = -1L

    var usage by mutableStateOf<Usage?>(null)
        private set

    /** Every model this person has (not ready ones are shown greyed, as on the website) */
    val models: List<ModelCard> get() = state?.models?.all.orEmpty()
    val currentModel: ModelCard? get() = models.firstOrNull { it.id == model }

    fun modelById(id: String): ModelCard? = models.firstOrNull { it.id == id }

    /** Auto is always there; otherwise a model may list the levels it offers */
    fun effortAllowed(id: String) = id == "auto" || currentModel?.efforts?.contains(id) ?: true

    init {
        start()
    }

    /** Is the server there, and is this phone signed in? */
    fun start() {
        val url = session.serverUrl
        if (url == null) {
            screen = Screen.SignIn
            return
        }
        screen = Screen.Starting
        viewModelScope.launch {
            try {
                val status = api.status()
                if (status.resting) {
                    screen = Screen.Off(resting = true, server = url)
                    return@launch
                }
                if (!session.signedIn) {
                    screen = Screen.SignIn
                    return@launch
                }
                loadState()
                screen = Screen.Chat
            } catch (e: OfflineException) {
                screen = Screen.Off(resting = false, server = url)
            } catch (e: ApiException) {
                if (e.signedOut) session.forget()
                screen = Screen.SignIn
            }
        }
    }

    fun changeServer() {
        screen = Screen.SignIn
    }

    fun signIn(way: SignInWay, id: String, secret: String) {
        val url = normalise(server) ?: run {
            signInError = "That address doesn't look right. It starts with https://"
            return
        }
        server = url
        session.serverUrl = url
        signInBusy = true
        signInError = null
        viewModelScope.launch {
            try {
                val reply = when (way) {
                    SignInWay.Password -> api.signInWithPassword(id.trim(), secret)
                    SignInWay.Key -> api.signInWithKey(secret.trim())
                }
                if (reply.mfa) twoStepTicket = reply.ticket else afterSignIn()
            } catch (e: Exception) {
                signInError = describe(e)
            } finally {
                signInBusy = false
            }
        }
    }

    fun submitTwoStep(code: String) {
        val ticket = twoStepTicket ?: return
        signInBusy = true
        signInError = null
        viewModelScope.launch {
            try {
                api.twoStep(ticket, code.trim())
                twoStepTicket = null
                afterSignIn()
            } catch (e: Exception) {
                signInError = describe(e)
            } finally {
                signInBusy = false
            }
        }
    }

    fun cancelTwoStep() {
        twoStepTicket = null
        signInError = null
    }

    private suspend fun afterSignIn() {
        loadState()
        newChat()
        screen = Screen.Chat
    }

    fun signOut() {
        viewModelScope.launch {
            replyJob?.cancel()
            api.signOut()
            state = null
            chats = emptyList()
            bubbles.clear()
            chatId = null
            screen = Screen.SignIn
        }
    }

    private suspend fun loadState() {
        val s = api.state(model.ifEmpty { null })
        state = s
        chats = s.chats
        usage = s.usage
        if (model.isEmpty() || models.none { it.id == model && it.ready }) model = s.model
    }

    /** The chat list and the usage line (the usage figure depends on the model and effort picked) */
    fun refreshChats() {
        viewModelScope.launch {
            runCatching { api.state(model) }.onSuccess {
                state = it
                chats = it.chats
                usage = it.usage
            }
        }
    }

    fun pickModel(id: String) {
        val m = modelById(id) ?: return
        if (!m.ready) return
        model = id
        if (effort != "auto" && m.efforts != null && effort !in m.efforts) effort = "balanced"
        refreshChats()
    }

    fun pickEffort(id: String) {
        effort = id
    }

    fun newChat() {
        if (streaming) return
        chatId = null
        title = "New chat"
        bubbles.clear()
        notice = null
    }

    fun openChat(id: Long) {
        if (streaming) return
        notice = null
        viewModelScope.launch {
            try {
                val c = api.chat(id)
                chatId = c.id
                title = c.title
                bubbles.clear()
                bubbles.addAll(c.messages.map { Bubble(it.id, it.role == "user", it.content, cut = it.status == "partial" && !c.generating, model = it.modelId) })
                c.messages.lastOrNull { it.role == "assistant" && it.modelId.isNotEmpty() }?.let { m ->
                    if (models.any { it.id == m.modelId }) model = m.modelId
                }
                if (c.generating) notice = "Still writing this reply. Open the chat again in a moment to see the rest."
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            }
        }
    }

    fun send(text: String) {
        val words = text.trim()
        if (words.isEmpty() || streaming) return
        bubbles.add(Bubble(nextKey--, mine = true, text = words))
        reply(words, regenerate = false)
    }

    /** Write the last reply again, with the model and effort picked now */
    fun regenerate() {
        if (streaming || chatId == null) return
        val last = bubbles.lastOrNull() ?: return
        if (!last.mine) bubbles.removeAt(bubbles.lastIndex)
        reply("", regenerate = true)
    }

    private fun reply(words: String, regenerate: Boolean) {
        notice = null
        streaming = true
        working = "Thinking…"
        val replyKey = nextKey--
        bubbles.add(Bubble(replyKey, mine = false, text = "", streaming = true, model = model))
        replyJob = viewModelScope.launch {
            try {
                val id = chatId ?: api.newChat().also { chatId = it }
                api.send(id, words, model, effort, regenerate).collect { ev ->
                    when (ev) {
                        is ReplyEvent.Thinking -> working = "Thinking…"
                        is ReplyEvent.Loading -> working = "Loading ${modelById(ev.model)?.fullName ?: "the model"}…"
                        is ReplyEvent.Compacting -> working = "Tidying up the chat's memory…"
                        is ReplyEvent.Piece -> {
                            working = null
                            update(replyKey) { it.copy(text = it.text + ev.text) }
                        }
                        is ReplyEvent.Done -> {
                            ev.title?.let { title = it }
                            update(replyKey) { it.copy(streaming = false, cut = ev.cut) }
                        }
                        is ReplyEvent.Failed -> notice = listOf(ev.message, ev.action).filter { it.isNotBlank() }.joinToString(" ")
                        is ReplyEvent.Other -> Unit
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            } finally {
                update(replyKey) { it.copy(streaming = false) }
                bubbles.removeAll { it.key == replyKey && it.text.isEmpty() }
                streaming = false
                working = null
                refreshChats()
            }
        }
    }

    fun stop() {
        val id = chatId ?: return
        viewModelScope.launch {
            runCatching { api.stop(id) }      // the server stops writing; what was written so far is kept
            replyJob?.cancel()
        }
    }

    private fun update(key: Long, change: (Bubble) -> Bubble) {
        val i = bubbles.indexOfFirst { it.key == key }
        if (i >= 0) bubbles[i] = change(bubbles[i])
    }

    private fun handleSignedOut(e: Exception): Boolean {
        if (e is ApiException && e.signedOut) {
            session.forget()
            signInError = "You were signed out. Please sign in again."
            screen = Screen.SignIn
            return true
        }
        return false
    }

    private fun describe(e: Exception): String = when (e) {
        is OfflineException -> "Emvryx is off right now. The PC may be switched off or asleep; try again in a little while."
        is ApiException -> listOf(e.message, e.action).filter { it.isNotBlank() }.joinToString(" ")
        else -> "Something went wrong. Please try again."
    }

    companion object {
        /** "chat.emvryx.app" -> "https://chat.emvryx.app"; null when it can't be an address. */
        fun normalise(input: String): String? {
            var s = input.trim().trimEnd('/')
            if (s.isEmpty() || s.any { it.isWhitespace() }) return null
            if (!s.startsWith("http://") && !s.startsWith("https://")) s = "https://$s"
            val host = s.substringAfter("://").substringBefore('/').substringBefore(':')
            return if (host.isEmpty()) null else s
        }
    }
}
