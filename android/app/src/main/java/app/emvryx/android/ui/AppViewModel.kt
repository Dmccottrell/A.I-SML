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
import app.emvryx.android.data.Ctx
import app.emvryx.android.data.DocInfo
import app.emvryx.android.data.ModelCard
import app.emvryx.android.data.SearchHit
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
    data object Code : Screen
    /** A page of the website inside the app, signed in with the same session: Settings, Admin, or everything else the app has no screen for. */
    data class Web(val path: String, val title: String) : Screen
}

enum class SignInWay { Password, Key }

/** One bubble on the chat screen. [streaming] is the reply still being written; [model] is the id of the model that wrote it. */
data class Bubble(val key: Long, val mine: Boolean, val text: String, val streaming: Boolean = false, val cut: Boolean = false, val model: String = "",
                  val id: Long = 0, val docs: List<DocInfo> = emptyList(), val fb: String = "")

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

    // ---- pictures and files waiting to go with the next message, the memory ring, search, and things shared from other apps
    val attached = mutableStateListOf<DocInfo>()
    var uploading by mutableStateOf(false)
        private set
    var ctx by mutableStateOf<Ctx?>(null)
        private set
    var hits by mutableStateOf<List<SearchHit>?>(null)
        private set
    var draft by mutableStateOf("")                      // text shared from another app, put in the message box
    private var searchJob: Job? = null
    private var pendingShare: Pair<String?, List<Pair<String, ByteArray>>>? = null     // shared from another app before it was ready
    private var chatDocIds: List<Long> = emptyList()     // all of this chat's pictures and files (sent ones too: the model keeps seeing them)

    fun flag(name: String) = state?.on(name) == true
    val isAdmin get() = state?.admin == true || state?.owner == true

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
                applyShare()
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
        applyShare()
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
        attached.clear()
        chatDocIds = emptyList()
        ctx = null
        notice = null
    }

    fun open(screen: Screen) {
        this.screen = screen
    }

    /** Back from VryxCode or a website page to the chat */
    fun backToChat() {
        screen = Screen.Chat
        refreshChats()
    }

    // ---- pictures and files
    /** Uploads a picture or file and attaches it to this chat (a new chat is made first if needed); it goes with the next message. */
    fun attach(name: String, bytes: ByteArray) {
        if (bytes.size > MAX_UPLOAD) {
            notice = "That file is too big to send (the limit is ${MAX_UPLOAD / 1_000_000} MB)."
            return
        }
        uploading = true
        notice = null
        viewModelScope.launch {
            try {
                val id = chatId ?: api.newChat().also { chatId = it }
                val doc = api.upload(name, bytes)
                chatDocIds = api.setChatDocs(id, (chatDocIds + doc.id).distinct()).map { it.id }     // every file of the chat stays with it
                attached.add(doc)
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            } finally {
                uploading = false
            }
        }
    }

    fun unattach(doc: DocInfo) {
        val id = chatId ?: return
        attached.remove(doc)
        chatDocIds = chatDocIds - doc.id
        viewModelScope.launch { runCatching { api.setChatDocs(id, chatDocIds) } }
    }

    suspend fun pictureBytes(id: Long): ByteArray? = api.picture(id)

    /** Something shared to Emvryx from another app: its text goes in the box, pictures are attached. Kept until the app is signed in and ready. */
    fun incoming(text: String?, files: List<Pair<String, ByteArray>>) {
        pendingShare = text to files
        if (screen == Screen.Chat || screen == Screen.Code || screen is Screen.Web) applyShare()
    }

    private fun applyShare() {
        val (text, files) = pendingShare ?: return
        pendingShare = null
        screen = Screen.Chat
        newChat()
        if (!text.isNullOrBlank()) draft = text
        files.forEach { (name, bytes) -> attach(name, bytes) }
    }

    // ---- chat list: pin, delete, search
    fun pin(c: ChatSummary) {
        viewModelScope.launch { runCatching { api.pin(c.id, !c.pinned) }; refreshChats() }
    }

    fun delete(c: ChatSummary) {
        viewModelScope.launch {
            runCatching { api.deleteChat(c.id) }
            if (chatId == c.id) newChat()
            refreshChats()
        }
    }

    /** Searches every chat's words on the server (titles are matched on the phone as you type) */
    fun search(q: String) {
        searchJob?.cancel()
        if (q.isBlank()) {
            hits = null
            return
        }
        searchJob = viewModelScope.launch {
            kotlinx.coroutines.delay(250)
            runCatching { api.search(q.trim()) }.onSuccess { hits = it }
        }
    }

    // ---- one answer: report it, start a new chat from it, ask again after an edit
    fun report(b: Bubble, kind: String, note: String) {
        val id = chatId ?: return
        viewModelScope.launch {
            try {
                api.report(id, b.id, kind, note)
                update(b.key) { it.copy(fb = kind) }
                notice = null
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            }
        }
    }

    fun branch(b: Bubble) {
        val id = chatId ?: return
        viewModelScope.launch {
            try {
                openChat(api.branch(id, b.id).id)
                refreshChats()
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            }
        }
    }

    /** Change what you asked: the answers after it are forgotten and it is asked again */
    fun edit(b: Bubble, text: String) {
        val id = chatId ?: return
        if (streaming || text.isBlank()) return
        viewModelScope.launch {
            try {
                api.editMessage(id, b.id, text.trim())
                val c = api.chat(id)
                showChat(c)
                if (bubbles.lastOrNull()?.mine == true) reply("", regenerate = true)
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            }
        }
    }

    /** The answer stopped at its length limit: carry on from there */
    fun continueReply() {
        if (streaming || chatId == null) return
        bubbles.add(Bubble(nextKey--, mine = true, text = "Continue"))
        reply("Continue", regenerate = false, cont = true)
    }

    // ---- the memory ring (feature flag context_meter)
    fun compact() {
        val id = chatId ?: return
        if (streaming) return
        working = "Summarizing earlier messages…"
        viewModelScope.launch {
            try {
                val r = api.compact(id, model)
                r.context?.let { ctx = it }
                notice = if (r.folded > 0) null else "There was nothing to summarize yet."
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            } finally {
                working = null
            }
        }
    }

    fun openChat(id: Long) {
        if (streaming) return
        notice = null
        viewModelScope.launch {
            try {
                val c = api.chat(id)
                showChat(c)
                c.messages.lastOrNull { it.role == "assistant" && it.modelId.isNotEmpty() }?.let { m ->
                    if (models.any { it.id == m.modelId }) model = m.modelId
                }
                if (c.generating) notice = "Still writing this reply. Open the chat again in a moment to see the rest."
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            }
        }
    }

    private fun showChat(c: app.emvryx.android.data.Chat) {
        chatId = c.id
        title = c.title
        bubbles.clear()
        bubbles.addAll(c.messages.map {
            Bubble(it.id, it.role == "user", it.content, cut = (it.cut || it.status == "partial") && !c.generating, model = it.modelId, id = it.id,
                   docs = it.docs, fb = it.fb)
        })
        ctx = c.ctx ?: c.messages.lastOrNull { it.ctx != null }?.ctx
        val sent = c.messages.flatMap { it.docs }.map { it.id }.toSet()
        chatDocIds = c.docs.map { it.id }
        attached.clear()
        attached.addAll(c.docs.filter { it.id !in sent })               // attached but not sent yet
    }

    fun send(text: String) {
        val words = text.trim()
        if ((words.isEmpty() && attached.isEmpty()) || streaming) return
        bubbles.add(Bubble(nextKey--, mine = true, text = words, docs = attached.toList()))
        attached.clear()
        draft = ""
        reply(words, regenerate = false)
    }

    /** Write the last reply again, with the model and effort picked now; [mode] is how it should differ (Regenerate options) */
    fun regenerate(mode: String? = null) {
        if (streaming || chatId == null) return
        val last = bubbles.lastOrNull() ?: return
        if (!last.mine) bubbles.removeAt(bubbles.lastIndex)
        reply("", regenerate = true, mode = mode)
    }

    private fun reply(words: String, regenerate: Boolean, mode: String? = null, cont: Boolean = false) {
        notice = null
        streaming = true
        working = "Thinking…"
        val replyKey = nextKey--
        bubbles.add(Bubble(replyKey, mine = false, text = "", streaming = true, model = model))
        replyJob = viewModelScope.launch {
            try {
                val id = chatId ?: api.newChat().also { chatId = it }
                api.send(id, words, model, effort, regenerate, mode, cont).collect { ev ->
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
                chatId?.let { id ->                          // the saved messages: their ids (edit, report), pictures and the memory ring
                    runCatching { api.chat(id) }.onSuccess { c -> if (!streaming && chatId == c.id) showChat(c) }
                }
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
        const val MAX_UPLOAD = 20_000_000

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
