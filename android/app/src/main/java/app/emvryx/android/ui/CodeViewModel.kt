package app.emvryx.android.ui

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.emvryx.android.EmvryxApp
import app.emvryx.android.data.ApiException
import app.emvryx.android.data.CodeCommand
import app.emvryx.android.data.CodeInfo
import app.emvryx.android.data.CodeRules
import app.emvryx.android.data.CodeSessionRow
import app.emvryx.android.data.OfflineException
import app.emvryx.android.data.bool
import app.emvryx.android.data.int
import app.emvryx.android.data.str
import app.emvryx.android.data.strings
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/**
 * VryxCode on the phone (web/js/code.js and ide.js): the sessions list, one session's work feed (polled, as the website does), the message box
 * with effort (or model), how it works (Ask / Auto / Plan) and where it runs, permission and multiple-choice questions, messages typed while it
 * works, pictures, and the /commands. The editor, preview and file browser open the website's VryxCode inside the app.
 */
class CodeViewModel(app: Application) : AndroidViewModel(app) {
    private val api = (app as EmvryxApp).api

    var info by mutableStateOf<CodeInfo?>(null)
        private set
    var sessions by mutableStateOf<List<CodeSessionRow>>(emptyList())
        private set
    var error by mutableStateOf<String?>(null)
        private set

    // ---- the open session (null = the sessions list)
    var sid by mutableStateOf<String?>(null)
        private set
    var inSession by mutableStateOf(false)
        private set
    val events = mutableStateListOf<JsonObject>()
    var state by mutableStateOf("")
        private set
    var pending by mutableStateOf<JsonObject?>(null)
        private set
    var full by mutableStateOf(false)
        private set
    var liveLine by mutableStateOf<String?>(null)
        private set
    private var seen = 0
    private var poller: Job? = null

    // ---- the message box
    var project by mutableStateOf("my-project")
    var mode by mutableStateOf("ask")                 // ask | auto | plan (MODES in code.js)
    var effort by mutableStateOf("balanced")
    var model by mutableStateOf("")
    var env by mutableStateOf("local")
    var offer by mutableStateOf("")                   // the suggested reply after a finished turn (flag vryxcode_suggest), greyed in the empty box
    var suggestOn = false
    var onTour: (() -> Unit)? = null                     // /tour: the VryxCode tour again
    val pictures = mutableStateListOf<String>()      // data: URLs sent with the next message (the full agent sees them)
    var commands by mutableStateOf<List<CodeCommand>>(emptyList())
        private set

    // ---- dialogs (/memory, /permissions)
    var memory by mutableStateOf<List<String>?>(null)
        private set
    var rules by mutableStateOf<CodeRules?>(null)
        private set

    val working get() = state in setOf("starting", "working", "asking", "queued")
    val oneModel get() = info?.effort != null                       // feature flag vryxcode_effort: effort instead of a model picker

    fun load() {
        error = null
        viewModelScope.launch {
            try {
                val i = api.codeInfo()
                info = i
                if (i.effort != null) model = i.effort.auto ?: model
                if (model.isEmpty() || i.models.none { it.id == model && it.ready }) model = i.models.firstOrNull { it.ready }?.id ?: ""
                project = i.project ?: i.projects.firstOrNull() ?: project
                if (i.environments.none { it.id == env && it.available }) env = "local"
                sessions = api.codeSessions()
                commands = runCatching { api.codeCommands(project) }.getOrDefault(emptyList())
            } catch (e: Exception) {
                error = describe(e)
            }
        }
    }

    fun newSession() {
        stopPolling()
        sid = null
        inSession = true
        events.clear()
        seen = 0
        state = ""
        pending = null
        liveLine = null
        offer = ""
        pictures.clear()
    }

    fun openSession(row: CodeSessionRow) {
        stopPolling()
        sid = row.id
        project = row.project.ifEmpty { project }
        if (info?.models?.any { it.id == row.model && it.ready } == true && !oneModel) model = row.model
        inSession = true
        events.clear()
        seen = 0
        pending = null
        pictures.clear()
        poll()
    }

    fun backToList() {
        stopPolling()
        inSession = false
        sid = null
        viewModelScope.launch { runCatching { api.codeSessions() }.onSuccess { sessions = it } }
    }

    private fun stopPolling() {
        poller?.cancel()
        poller = null
    }

    /** Reads what happened since the last look; keeps reading while it works (every 0.4 s, 1.5 s while it waits for an answer) */
    private fun poll() {
        val id = sid ?: return
        poller?.cancel()
        poller = viewModelScope.launch {
            while (isActive) {
                try {
                    val v = api.codeView(id, seen)
                    events.addAll(v.events)
                    v.events.forEach(::offerFrom)
                    seen += v.events.size
                    state = v.state
                    pending = v.pending
                    full = v.full
                    liveLine = v.live?.let { l -> listOf(l["phase"], l["tool"], l["target"]).mapNotNull { (it as? JsonPrimitive)?.content }.filter { it.isNotBlank() }.joinToString(" · ") }
                    if (!v.working) break
                    delay(if (v.state == "asking") 1500 else 400)
                } catch (e: Exception) {
                    error = describe(e)
                    delay(3000)
                }
            }
        }
    }

    /** The send button: a new session, the next message, or (the full agent, while it works) a message it reads before its next step */
    fun send(text: String) {
        val words = text.trim()
        if (words.isEmpty() && pictures.isEmpty()) return
        error = null
        if (words.startsWith("/") && runSlash(words)) return
        offer = ""
        viewModelScope.launch {
            try {
                val id = sid
                when {
                    id != null && working && full -> api.codeSteer(id, words)
                    id != null -> api.codeMessage(id, body(words, start = false))
                    else -> {
                        val r = api.codeStart(body(words, start = true))
                        sid = r.id
                        events.clear()
                        seen = 0
                    }
                }
                pictures.clear()
                poll()
            } catch (e: Exception) {
                error = describe(e)
            }
        }
    }

    /** What to suggest next, as the website does: "build it" after a plan, otherwise the first of the model's suggested next steps */
    private fun offerFrom(e: JsonObject) {
        when (e.str("kind")) {
            "user", "start" -> offer = ""
            "end" -> if (e.bool("finished") || e.bool("plan")) offer = if (!suggestOn) "" else if (e.bool("plan")) "Go ahead and build it as planned." else e.strings("next").firstOrNull().orEmpty().take(200)
        }
    }

    private fun body(text: String, start: Boolean): JsonObject = buildJsonObject {
        if (start) {
            put("project", project); put("task", text); put("env", env); put("queue", true)
        } else put("text", text)
        put("model", model); put("effort", effort)
        put("auto_edits", mode == "auto"); put("plan", mode == "plan")
        if (pictures.isNotEmpty()) putJsonArray("images") { pictures.forEach { add(JsonPrimitive(it)) } }
    }

    fun stop() {
        val id = sid ?: return
        viewModelScope.launch { runCatching { api.codeStop(id) }; poll() }
    }

    /** A permission question: Yes / Yes and don't ask again / No */
    fun answer(allow: Boolean, always: Boolean = false) {
        val id = sid ?: return
        val q = pending?.int("id") ?: return
        viewModelScope.launch { runCatching { api.codeAnswer(id, q, allow, always) }; pending = null; poll() }
    }

    /** A multiple-choice question: the option picked, or the person's own words */
    fun choose(text: String) {
        val id = sid ?: return
        val q = pending?.int("id") ?: return
        if (text.isBlank()) return
        viewModelScope.launch { runCatching { api.codeAnswer(id, q, true, choice = text.trim()) }; pending = null; poll() }
    }

    fun addPicture(name: String, bytes: ByteArray) {
        if (pictures.size >= 3 || bytes.size > 5_000_000) {
            error = "Up to 3 pictures, 5 MB each."
            return
        }
        val ext = name.substringAfterLast('.', "png").lowercase().let { if (it == "jpg") "jpeg" else it }
        if (ext !in setOf("png", "jpeg", "webp", "gif")) {
            error = "Pictures can be PNG, JPEG, WebP or GIF."
            return
        }
        pictures.add("data:image/$ext;base64," + android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP))
    }

    // ---- /commands that the app answers itself (the rest go to the server: a project's own /commands become their text there)
    private fun runSlash(text: String): Boolean {
        when (text.substringBefore(' ').lowercase()) {
            "/plan" -> mode = "plan"
            "/ask" -> mode = "ask"
            "/auto" -> mode = "auto"
            "/new" -> newSession()
            "/memory" -> showMemory()
            "/permissions" -> showRules()
            "/fixci" -> fixCi()
            "/tour" -> onTour?.invoke()
            else -> return false
        }
        return true
    }

    fun showMemory() {
        viewModelScope.launch { runCatching { api.codeMemory() }.onSuccess { memory = it.notes }.onFailure { error = describe(it as? Exception ?: Exception(it)) } }
    }

    fun forget(index: Int?) {
        viewModelScope.launch { runCatching { api.codeForget(index) }.onSuccess { memory = it.notes } }
    }

    fun closeMemory() {
        memory = null
    }

    fun showRules() {
        viewModelScope.launch { runCatching { api.codeRules(project) }.onSuccess { rules = it }.onFailure { error = describe(it as? Exception ?: Exception(it)) } }
    }

    fun addRule(kind: String, rule: String) {
        if (rule.isBlank()) return
        viewModelScope.launch {
            try {
                rules = api.codeRule(project, add = kind to rule.trim())
            } catch (e: Exception) {
                error = describe(e)
            }
        }
    }

    fun removeRule(rule: String) {
        viewModelScope.launch { runCatching { api.codeRule(project, remove = rule) }.onSuccess { rules = it } }
    }

    fun closeRules() {
        rules = null
    }

    /** /fixci: what is failing on GitHub for this project becomes a new session */
    fun fixCi() {
        viewModelScope.launch {
            try {
                val r = api.codeFixCi(buildJsonObject { put("project", project); put("model", model); put("effort", effort); put("env", env) })
                if (r.id.isEmpty()) {
                    error = r.message ?: "Nothing is failing."
                    return@launch
                }
                newSession()
                sid = r.id
                poll()
            } catch (e: Exception) {
                error = describe(e)
            }
        }
    }

    private fun describe(e: Exception): String = when (e) {
        is OfflineException -> "Emvryx is off right now. The PC may be switched off or asleep."
        is ApiException -> listOf(e.message, e.action).filter { it.isNotBlank() }.joinToString(" ")
        else -> "Something went wrong. Please try again."
    }
}
