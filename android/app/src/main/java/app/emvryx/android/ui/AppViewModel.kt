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
import app.emvryx.android.data.Briefing
import app.emvryx.android.data.LookupNotes
import app.emvryx.android.data.ShareRow
import app.emvryx.android.data.Shares
import app.emvryx.android.data.Timing
import app.emvryx.android.ui.theme.Emvryx
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
    /** A page of the website inside the app, signed in with the same session: Settings, Admin, or everything else the app has no screen for.
     *  [run] is the website's own call that opens a part of it once the page has loaded ("openSkills()", "openMemory()"). */
    data class Web(val path: String, val title: String, val run: String = "", val panel: Boolean = false) : Screen
    /** The app's own screens for what the website shows in a panel (feature flag android_native): "memory", "files", "skills", "settings" */
    data class Native(val kind: String) : Screen
    /** Chats answered by the model on this phone (feature flag android_offline_model), for when the PC is off */
    data object Local : Screen
}

enum class SignInWay { Password, Key, Email }

/** One bubble on the chat screen. [streaming] is the reply still being written; [model] is the id of the model that wrote it.
 *  [notes]: what it looked up first; [timing]: where its time went (owner and admins); [memory]: what it remembered; [liked]: "Right" was pressed. */
data class Bubble(val key: Long, val mine: Boolean, val text: String, val streaming: Boolean = false, val cut: Boolean = false, val model: String = "",
                  val id: Long = 0, val docs: List<DocInfo> = emptyList(), val fb: String = "", val notes: LookupNotes? = null,
                  val timing: Timing? = null, val memory: String? = null, val liked: String? = null, val autoNote: String? = null)

/** A reply that did not come: the message, what to do, and for an empty tank a word about what is not counted (web/js/send.js errorCard) */
data class Failure(val message: String, val action: String = "", val code: String = "", val later: String = "")

class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val session = (app as EmvryxApp).session
    private val api = (app as EmvryxApp).api
    private val phone = (app as EmvryxApp).phone

    /** The PC answered the last time it was asked (the phone's model is downloaded only then) */
    var online by mutableStateOf(false)
        private set

    /** The chats on this phone can be opened: the switch is on and the model is here (or, online, to download it) */
    val phoneChats get() = phone.allowed && (online || phone.status == app.emvryx.android.local.PhoneModel.Status.Ready)

    /** Back from the phone's chats: to the chat when the PC answers, else to "Emvryx is off" (which tries again) */
    fun leaveLocal() {
        if (online && state != null) backToChat() else start()
    }

    var screen by mutableStateOf<Screen>(Screen.Starting)
        private set

    // ---- sign-in
    var server by mutableStateOf(run {
        // 10.0.2.2 is the PC as seen from the emulator only: on a real phone it goes nowhere and looks like "Emvryx is off"
        if (!onEmulator() && session.serverUrl?.contains(EMULATOR_HOST) == true) session.serverUrl = null
        session.serverUrl ?: defaultServer()
    })
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
    /** Counts model picks, so the chat plays the colour wash once for each */
    var washes by mutableStateOf(0)
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
    var failure by mutableStateOf<Failure?>(null)         // the error card under the thread
        private set
    var isPrivate by mutableStateOf(false)                // a private chat: never saved, never listed, no memory
        private set
    var skill by mutableStateOf("")                       // the skill a new chat starts with (Skills, feature flag android_native)
        private set
    var sentAt by mutableStateOf(0L)                      // when the message went (elapsedRealtime), for the thinking clock
        private set
    var following by mutableStateOf(false)                // watching a reply the server is still writing (the app was away)
        private set
    var briefing by mutableStateOf<Briefing?>(null)       // "Your day", once read
        private set
    var briefingBusy by mutableStateOf(false)
        private set
    var archivedChats by mutableStateOf<List<ChatSummary>?>(null)
        private set
    var shares by mutableStateOf<Shares?>(null)
        private set
    var shareUrl by mutableStateOf<String?>(null)
        private set
    var toast by mutableStateOf<String?>(null)            // a short message at the bottom ("Saved as a PDF")
    var locked by mutableStateOf(session.lock)            // the fingerprint lock is showing
        private set
    var lockOn by mutableStateOf(session.lock)
        private set
    var emailOffered by mutableStateOf(false)             // this server can send sign-in codes by email
        private set
    var emailSentTo by mutableStateOf<String?>(null)      // a code was sent: now type it
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

    // ---- model welcome tours (declared before init: loading the state reads them)
    var tour by mutableStateOf<ModelCard?>(null)
        private set
    private val toursSeen = mutableSetOf<String>()
    private var tourChecked = false
    var vryxTour by mutableStateOf(false)                        // the VryxCode tour is showing (flag vryxcode_tour)
        private set
    private var vryxSeen = 0

    init {
        Emvryx.light = session.light
        session.looks.let { (v, m) -> Emvryx.violet = v; Emvryx.modern = m }
        start()
    }

    // ---- light or dark (the website's moon button)
    fun toggleLight() {
        Emvryx.light = !Emvryx.light
        session.light = Emvryx.light
    }

    // ---- the fingerprint lock
    fun setLock(on: Boolean) {
        lockOn = on
        session.lock = on
    }

    fun lockIfOn() {
        if (lockOn) locked = true
    }

    fun unlocked() {
        locked = false
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
                online = false
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

    /** Which ways of signing in the server offers (email codes need the owner's mail set up) */
    fun checkSignInOptions() {
        if (session.serverUrl == null) return
        viewModelScope.launch { runCatching { api.authOptions() }.onSuccess { emailOffered = it.email } }
    }

    /** "Email me a code": the server sends a 6-digit code if that email belongs to an account (it answers the same either way) */
    fun sendEmailCode(email: String) {
        val url = normalise(server) ?: return
        session.serverUrl = url
        val e = email.trim()
        if (!e.contains('@')) {
            signInError = "Type the email on your account."
            return
        }
        signInBusy = true
        signInError = null
        viewModelScope.launch {
            try {
                api.emailCode(e)
                emailSentTo = e
            } catch (x: Exception) {
                signInError = describe(x)
            } finally {
                signInBusy = false
            }
        }
    }

    fun signInWithEmailCode(code: String) {
        val e = emailSentTo ?: return
        signInBusy = true
        signInError = null
        viewModelScope.launch {
            try {
                val reply = api.emailSignIn(e, code.trim())
                emailSentTo = null
                if (reply.mfa) twoStepTicket = reply.ticket else afterSignIn()
            } catch (x: Exception) {
                signInError = describe(x)
            } finally {
                signInBusy = false
            }
        }
    }

    fun cancelEmailCode() {
        emailSentTo = null
        signInError = null
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
                    SignInWay.Email -> return@launch                     // email codes go through sendEmailCode / signInWithEmailCode
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

    /** The website's looks follow the server's switches; remembered for the next sign-in screen */
    private fun applyLooks(s: AppState) {
        val v = s.on("violet_theme")
        val m = s.on("modern_look")
        if (Emvryx.violet != v) Emvryx.violet = v
        if (Emvryx.modern != m) Emvryx.modern = m
        Emvryx.modelBar = s.on("model_bar")
        if (session.looks != (v to m)) session.looks = v to m
    }

    private suspend fun loadState() {
        val s = api.state(model.ifEmpty { null })
        applyLooks(s)
        state = s
        online = true
        phone.setAllowed(s.on("android_offline_model"))                  // remembered for when the PC is off
        if (phone.allowed) viewModelScope.launch { phone.refresh() }       // the newest instructions and memory for the phone's model
        chats = s.chats
        usage = s.usage
        if (model.isEmpty() || models.none { it.id == model && it.ready }) model = s.model
        toursSeen.addAll(s.settings.modelToursSeen)
        vryxSeen = maxOf(vryxSeen, s.settings.vryxTourSeen)
        if (!tourChecked) {                                       // once per launch: the newest model this person has not toured yet
            tourChecked = true
            s.models.cards.filter { it.ready && it.tour.isNotEmpty() && it.id !in toursSeen }.maxByOrNull { it.version ?: 0.0 }?.let(::maybeTour)
        }
    }

    // ---- model welcome tours (feature flag model_tours): "WELCOME to Flare 3", what only that model brings, then VryxCode for its models
    fun maybeTour(card: ModelCard) {
        if (flag("model_tours") && card.tour.isNotEmpty() && card.id !in toursSeen && tour == null) tour = card
    }

    /** The first time VryxCode opens */
    fun maybeVryxTour() {
        if (flag("vryxcode_tour") && vryxSeen < VRYX_TOUR_VERSION && tour == null) vryxTour = true
    }

    fun replayVryxTour() {
        vryxTour = true
    }

    fun closeVryxTour() {
        vryxTour = false
        if (vryxSeen < VRYX_TOUR_VERSION) {
            vryxSeen = VRYX_TOUR_VERSION
            viewModelScope.launch { runCatching { api.vryxTourSeen(VRYX_TOUR_VERSION) } }
        }
    }

    /** Replay from the model picker, seen or not */
    fun replayTour(card: ModelCard) {
        if (card.tour.isNotEmpty()) tour = card
    }

    fun closeTour(use: Boolean) {
        val card = tour ?: return
        tour = null
        if (toursSeen.add(card.id)) viewModelScope.launch { runCatching { api.modelTourSeen(card.id) } }
        if (use && card.ready && model != card.id) pickModel(card.id)
    }

    /** The chat list and the usage line (the usage figure depends on the model and effort picked) */
    fun refreshChats() {
        viewModelScope.launch {
            runCatching { api.state(model) }.onSuccess {
                // only what changed is set, so an unchanged list does not redraw the screen (opening the menu stayed smooth)
                applyLooks(it)
                if (it != state) state = it
                if (it.chats != chats) chats = it.chats
                if (it.usage != usage) usage = it.usage
            }
        }
    }

    fun pickModel(id: String) {
        val m = modelById(id) ?: return
        if (!m.ready) return
        if (id != model) washes++                                   // the model's colour washes over the screen (core.js wash)
        model = id
        if (effort != "auto" && m.efforts != null && effort !in m.efforts) effort = "balanced"
        refreshChats()
        maybeTour(m)
    }

    fun pickEffort(id: String) {
        effort = id
    }

    /** A new chat; [private] makes it one that is never saved; [skill] (an id from GET /api/skills) shapes every answer in it */
    fun newChat(private: Boolean = false, skill: String = "", skillName: String = "") {
        if (streaming) return
        chatId = null
        isPrivate = private
        this.skill = skill
        title = if (private) "Private chat" else skillName.ifEmpty { "New chat" }
        bubbles.clear()
        attached.clear()
        chatDocIds = emptyList()
        ctx = null
        notice = null
        failure = null
    }

    /** The memory ring's reading: the last reply's, else an estimate from the words so far (web/js/chat.js lastCtx) */
    val shownCtx: Ctx?
        get() {
            ctx?.let { return it }
            val w = state?.window?.window ?: return null
            if (w <= 0) return null
            val used = Math.round(bubbles.sumOf { it.text.length } / 3.5)
            return Ctx(used, w, minOf(100.0, Math.round(1000.0 * used / w) / 10.0), minOf(0.75 * maxOf(64L, w - 1024), 96000.0).toLong())
        }

    // ---- the chat's menu and the answer's: Right, archive, folder, share a link, save as
    fun like(b: Bubble) {
        val id = chatId ?: return
        viewModelScope.launch {
            try {
                val r = api.like(id, b.id)
                update(b.key) { it.copy(liked = if (r.saved > 0) "Saved" else "Thanks") }
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            }
        }
    }

    fun archive(c: ChatSummary, on: Boolean = true) {
        viewModelScope.launch {
            runCatching { api.archive(c.id, on) }
            if (on && chatId == c.id) newChat()
            if (!on) loadArchived()
            refreshChats()
        }
    }

    fun archiveThis() {
        val id = chatId ?: return
        archive(ChatSummary(id, title), true)
    }

    fun loadArchived() {
        viewModelScope.launch { archivedChats = runCatching { api.archived() }.getOrDefault(emptyList()) }
    }

    fun closeArchived() {
        archivedChats = null
    }

    fun moveToFolder(c: ChatSummary, folder: String) {
        viewModelScope.launch { runCatching { api.folder(c.id, folder.trim()) }; refreshChats() }
    }

    fun loadShares() {
        shareUrl = null
        viewModelScope.launch { shares = runCatching { api.shares() }.getOrNull() ?: Shares() }
    }

    fun makeShare(days: Int) {
        val id = chatId ?: return
        viewModelScope.launch {
            try {
                val r = api.share(id, days)
                shareUrl = (api.server ?: "") + r.url
                shares = shares?.copy(shares = r.shares)
            } catch (e: Exception) {
                if (!handleSignedOut(e)) toast = describe(e)
            }
        }
    }

    fun revokeShare(s: ShareRow) {
        viewModelScope.launch { runCatching { api.revokeShare(s.id) }; shares = runCatching { api.shares() }.getOrNull() }
    }

    fun closeShares() {
        shares = null
        shareUrl = null
    }

    /** The whole chat as text, as the website's "Save as" makes it (chat.js chatAsText) */
    fun chatAsText(): String = "# $title\n\n" + bubbles.filter { it.text.isNotBlank() && !it.text.startsWith(SUMMARY_MARK) }.joinToString("\n\n") {
        (if (it.mine) "**You:** " else "**${modelById(it.model)?.fullName ?: "Emvryx"}:** ") + it.text
    }

    /** Makes the PDF / Word / Markdown file on the server and writes it where the person chose */
    fun saveAs(uri: android.net.Uri, text: String, format: String) {
        viewModelScope.launch {
            try {
                val bytes = api.exportDoc(text, format, title)
                kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                }
                toast = when (format) { "pdf" -> "Saved as a PDF."; "docx" -> "Saved as a Word file."; else -> "Saved." }
            } catch (e: Exception) {
                if (!handleSignedOut(e)) toast = describe(e)
            }
        }
    }

    // ---- "Your day" from the connected apps (nothing is read until it is asked for)
    fun readMyDay() {
        briefingBusy = true
        viewModelScope.launch {
            briefing = runCatching { api.briefing() }.getOrNull()
            briefingBusy = false
        }
    }

    fun planMyDay(text: String) {
        briefing = null
        send("Here is my day. Please give me a short plan: what to do first, and anything I should not forget.\n\n$text")
    }

    /** The next stronger model that is ready, for "Ask a stronger model" (chat.js strongerModel) */
    fun strongerModel(modelId: String): ModelCard? {
        val cur = modelById(modelId) ?: return null
        fun rank(m: ModelCard) = MODEL_RANK.indexOf(m.name) + (m.version ?: 0.0) / 100
        if (cur.name !in MODEL_RANK) return null
        return models.filter { it.ready && it.name in MODEL_RANK && it.name != cur.name && rank(it) > rank(cur) }.minByOrNull(::rank)
    }

    fun askStronger(m: ModelCard) {
        pickModel(m.id)
        regenerate()
    }

    fun open(screen: Screen) {
        this.screen = screen
    }

    /** The app's own screen for one of the website's panels when android_native is on, else the website's panel */
    fun panel(kind: String, web: Screen.Web): Screen = if (flag("android_native")) Screen.Native(kind) else web

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
                val id = chatId ?: api.newChat(isPrivate, skill).also { chatId = it }
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

    /** A notification tapped (flag phone_alerts): VryxCode opens that session (CodeScreen reads [openSession]), or the chat opens. Kept until ready. */
    var openSession by mutableStateOf<String?>(null)
    private var pendingAlert: Pair<String?, Long?>? = null

    fun fromAlert(session: String?, chat: Long?) {
        if (session == null && chat == null) return
        pendingAlert = session to chat
        if (screen == Screen.Chat || screen == Screen.Code || screen is Screen.Web) applyAlert()
    }

    private fun applyAlert() {
        val (session, chat) = pendingAlert ?: return
        pendingAlert = null
        if (session != null) {
            openSession = session
            screen = Screen.Code
        } else if (chat != null) {
            screen = Screen.Chat
            openChat(chat)
        }
    }

    private fun applyShare() {
        applyAlert()
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
                if (c.generating) follow()
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            }
        }
    }

    /** The reply is still being written on the server (the app was closed or switched away from): watch it until it is done (send.js followReply) */
    fun follow() {
        val id = chatId ?: return
        if (following || streaming) return
        following = true
        streaming = true
        if (sentAt == 0L) sentAt = android.os.SystemClock.elapsedRealtime()
        replyJob = viewModelScope.launch {
            try {
                var last = ""
                for (i in 0 until 750) {                         // about 15 minutes
                    val c = try { api.chat(id) } catch (e: OfflineException) { kotlinx.coroutines.delay(2000); continue }
                    if (chatId != id) break
                    val sig = c.messages.joinToString { it.content.length.toString() + it.status } + c.generating
                    if (sig != last) {
                        last = sig
                        showChat(c)
                        val end = bubbles.lastOrNull()
                        if (c.generating && (end == null || end.mine)) bubbles.add(Bubble(nextKey--, mine = false, text = "", streaming = true, model = model))
                        else if (c.generating && end != null) bubbles[bubbles.lastIndex] = end.copy(streaming = true)
                    }
                    if (!c.generating) break
                    kotlinx.coroutines.delay(1200)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (!handleSignedOut(e)) notice = describe(e)
            } finally {
                following = false
                streaming = false
                working = null
                sentAt = 0L
                chatId?.let { cid -> runCatching { api.chat(cid) }.onSuccess { if (chatId == it.id) showChat(it) } }
                refreshChats()
            }
        }
    }

    private fun showChat(c: app.emvryx.android.data.Chat) {
        val kept = bubbles.filter { !it.mine && it.id > 0 }.associateBy { it.id }
        chatId = c.id
        isPrivate = c.private
        skill = c.skill
        title = c.title
        bubbles.clear()
        bubbles.addAll(c.messages.map {
            val old = kept[it.id]                                  // what only this phone saw stays with the answer: what it looked up, its timing
            Bubble(it.id, it.role == "user", it.content, cut = (it.cut || it.status == "partial") && !c.generating, model = it.modelId, id = it.id,
                   docs = it.docs, fb = it.fb, notes = old?.notes, timing = old?.timing, memory = old?.memory, liked = old?.liked, autoNote = old?.autoNote)
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
        failure = null
        streaming = true
        working = null                                         // the thinking words show while nothing is written yet
        sentAt = android.os.SystemClock.elapsedRealtime()
        val replyKey = nextKey--
        bubbles.add(Bubble(replyKey, mine = false, text = "", streaming = true, model = model))
        var finished = false
        var lost = false
        var got = false
        replyJob = viewModelScope.launch {
            try {
                val id = chatId ?: api.newChat(isPrivate, skill).also { chatId = it }
                api.send(id, words, model, effort, regenerate, mode, cont).collect { ev ->
                    when (ev) {
                        is ReplyEvent.Thinking -> if (ev.auto) update(replyKey) {
                            it.copy(autoNote = "Auto chose " + ev.effort.replaceFirstChar { c -> c.uppercase() })
                        }
                        is ReplyEvent.Loading -> working = "Loading ${modelById(ev.model)?.fullName ?: "the model"}…"
                        is ReplyEvent.Compacting -> working = "Summarizing earlier messages to make room…"
                        is ReplyEvent.Notes -> update(replyKey) { if (ev.notes.retry) it.copy(text = "", notes = ev.notes) else it.copy(notes = ev.notes) }
                        is ReplyEvent.Memory -> {
                            val bits = ev.saved.map { it.replace(USER_PREFIX, "").removeSuffix(".") } +
                                (if (ev.forgot > 0) listOf("forgot ${ev.forgot} " + if (ev.forgot == 1) "thing" else "things") else emptyList())
                            if (bits.isNotEmpty()) update(replyKey) { it.copy(memory = "📖 Memory updated: " + bits.joinToString("; ")) }
                        }
                        is ReplyEvent.Piece -> {
                            working = null
                            got = true
                            update(replyKey) { it.copy(text = it.text + ev.text) }
                        }
                        is ReplyEvent.Done -> {
                            finished = true
                            if (!app.emvryx.android.Alerts.visible && flag("phone_alerts") && !isPrivate)       // answered while the app was away
                                app.emvryx.android.Alerts.chat(getApplication(), chatId ?: 0L, ev.title ?: title,
                                    bubbles.firstOrNull { it.key == replyKey }?.text.orEmpty())
                            ev.title?.let { title = it }
                            ev.usage?.let { usage = it }
                            ev.context?.let { ctx = it }
                            update(replyKey) { it.copy(streaming = false, cut = ev.cut, timing = ev.timing) }
                        }
                        is ReplyEvent.Failed -> failure = Failure(ev.message, ev.action, ev.code)
                        is ReplyEvent.Other -> Unit
                    }
                }
                if (!finished && failure == null) lost = true            // the line ended without "done": the phone dropped it, the reply carries on
            } catch (e: CancellationException) {
                throw e
            } catch (e: OfflineException) {
                if (got) lost = true else failure = Failure(describe(e))
            } catch (e: Exception) {
                if (!handleSignedOut(e)) failure = failureOf(e)
            } finally {
                update(replyKey) { it.copy(streaming = false) }
                bubbles.removeAll { it.key == replyKey && it.text.isEmpty() }
                streaming = false
                working = null
                sentAt = 0L
                if (failure != null && !got && !regenerate && words.isNotBlank()) draft = words   // refused before a word: the message goes back in the box
                if (lost && chatId != null) follow()
                else {
                    refreshChats()
                    chatId?.let { id ->                          // the saved messages: their ids (edit, report), pictures and the memory ring
                        runCatching { api.chat(id) }.onSuccess { c -> if (!streaming && chatId == c.id) showChat(c) }
                    }
                }
            }
        }
    }

    /** A refusal before anything was written: the card says what happened and what to do (send.js errorCard) */
    private fun failureOf(e: Exception): Failure {
        if (e !is ApiException) return Failure(describe(e))
        val later = if (e.code == "tank_empty" || e.code == "week_limit") "Models on your own device are not counted." else ""
        return Failure(e.message, e.action, e.code, later)
    }

    /** The words that change while it thinks ("Thinking", "Pondering" ...), from the server */
    val thinkingWords: List<String> get() = state?.thinkingWords.orEmpty().ifEmpty { listOf("Thinking") }

    fun stop() {
        val id = chatId ?: return
        viewModelScope.launch {
            runCatching { api.stop(id) }      // the server stops writing; what was written so far is kept
            replyJob?.cancel()
        }
    }

    fun dismissFailure() {
        failure = null
    }

    private fun update(key: Long, change: (Bubble) -> Bubble) {
        val i = bubbles.indexOfFirst { it.key == key }
        if (i >= 0) bubbles[i] = change(bubbles[i])
    }

    fun handleSignedOut(e: Exception): Boolean {
        if (e is ApiException && e.signedOut) {
            session.forget()
            signInError = "You were signed out. Please sign in again."
            screen = Screen.SignIn
            return true
        }
        return false
    }

    fun describe(e: Exception): String = when (e) {
        is OfflineException -> "Emvryx is off right now. The PC may be switched off or asleep; try again in a little while."
        is ApiException -> listOf(e.message, e.action).filter { it.isNotBlank() }.joinToString(" ")
        else -> "Something went wrong. Please try again."
    }

    companion object {
        private const val EMULATOR_HOST = "10.0.2.2"
        private const val PUBLIC_SERVER = "https://chat.emvryx.app"

        /** The Android emulator (where 10.0.2.2 reaches the PC), not a real phone */
        fun onEmulator(): Boolean = android.os.Build.FINGERPRINT.let { it.startsWith("generic") || it.contains("emulator") || it.contains("sdk_gphone") } ||
            android.os.Build.HARDWARE.let { it == "ranchu" || it == "goldfish" }

        /** The debug build's PC address is only for the emulator; a real phone (a test build sideloaded on it) starts at the real address */
        fun defaultServer(): String =
            if (BuildConfig.DEFAULT_SERVER.contains(EMULATOR_HOST) && !onEmulator()) PUBLIC_SERVER else BuildConfig.DEFAULT_SERVER

        const val MAX_UPLOAD = 20_000_000
        const val SUMMARY_MARK = "[Earlier in this chat, shortened to save room]"
        private val MODEL_RANK = listOf("Flare", "Equinox", "Solstice", "Apogee")   // small and quick to strong and slow
        private val USER_PREFIX = Regex("^The user\\W?s? ?", RegexOption.IGNORE_CASE)
        const val VRYX_TOUR_VERSION = 1                          // web/js/tour.js VRYX_TOUR_VERSION: raise both to show a changed tour again

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
