// The brain behind the VryxCode (coding agent) screens on the phone.
// A ViewModel is an object that holds a screen's data and logic so it survives screen rotations; the screens (Compose, Android's way of
// drawing UI from Kotlin) read its fields and call its functions. Here it talks to the Emvryx server through `api`.
// Fields declared with `by mutableStateOf(...)` are "observable": when their value changes, any screen showing them redraws by itself.
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
import app.emvryx.android.data.num
import app.emvryx.android.data.CodeUsage
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
// AndroidViewModel gives access to the Application (the app-wide object), which is how we reach the shared server client below.
class CodeViewModel(app: Application) : AndroidViewModel(app) {
    // The shared server client (one per app) used for every call to the Emvryx PC.
    private val api = (app as EmvryxApp).api

    // Start-up info from the server (models, projects, places to run, effort levels, usage); null until loaded. `private set` = only this class may change it.
    var info by mutableStateOf<CodeInfo?>(null)
        private set
    // The list of coding sessions shown on the sessions screen.
    var sessions by mutableStateOf<List<CodeSessionRow>>(emptyList())
        private set
    // A plain-words error message to show, or null when all is well.
    var error by mutableStateOf<String?>(null)
        private set

    // ---- the open session (null = the sessions list)
    // The id of the open session, or null on the list / for a brand-new session that was not sent yet.
    var sid by mutableStateOf<String?>(null)
        private set
    // True while a session screen (not the list) is showing.
    var inSession by mutableStateOf(false)
        private set
    // The session's feed: one JSON object per thing that happened (a step, a user message, the end ...). A list that the screen watches.
    val events = mutableStateListOf<JsonObject>()
    // The agent's state from the server: starting, working, asking, queued, done, failed ...
    var state by mutableStateOf("")
        private set
    // The question the agent is waiting on (a permission or a multiple-choice question), or null.
    var pending by mutableStateOf<JsonObject?>(null)
        private set
    // True when this session runs the "full" agent (which can read messages typed while it works).
    var full by mutableStateOf(false)
        private set
    // The live line under the newest step ("Calling · write_file ..."), or null.
    var liveLine by mutableStateOf<String?>(null)
    /** The usage line under the box, as fresh as the last look at the server */
    var usage by mutableStateOf<CodeUsage?>(null)
        private set
    // How many events we have already received. Each poll asks the server only for events after this number.
    private var seen = 0
    // The running polling loop (a Job is a handle to a background task that can be cancelled), or null.
    private var poller: Job? = null

    // ---- the message box
    // The settings chosen in the message box.
    var project by mutableStateOf("my-project")
    var mode by mutableStateOf("ask")                 // ask | auto | plan (MODES in code.js)
    var effort by mutableStateOf("balanced")
    var model by mutableStateOf("")
    var env by mutableStateOf("local")
    var draft by mutableStateOf("")                   // a starting idea tapped on the home screen, put in the message box
    var offer by mutableStateOf("")                   // the suggested reply after a finished turn (flag vryxcode_suggest), greyed in the empty box
    // Whether the "suggest the next reply" feature is switched on (set by the screen from the server's flags).
    var suggestOn = false
    var onTour: (() -> Unit)? = null                     // /tour: the VryxCode tour again
    val docs = mutableStateListOf<app.emvryx.android.data.DocInfo>()   // vryxcode_review: documents for the model to read first (a spec, brand guidelines)
    var review by mutableStateOf(false)                // flag vryxcode_review: the review view, like Cursor's
    var projects by mutableStateOf(false)              // flag vryxcode_projects: the projects organizer, and a new idea gets its own project
    var buildHere by mutableStateOf(false)             // ...unless the person chose this project (its +, the project picker, "use it instead")
    var alerts = false                                 // flag phone_alerts: the phone's notifications while a session works
    // SharedPreferences is Android's small key-value store kept on the phone; here it remembers when each session was last opened.
    private val seenPrefs = app.getSharedPreferences("vryxcode", android.content.Context.MODE_PRIVATE)
    // Sessions opened since they last changed (id -> updated): they leave "Ready for review".
    // Rebuild the map (session id -> its "updated" time when opened) from storage. Values may be saved as a Float or a text; both are converted to Double,
    // and anything else is skipped. mapNotNull drops the skipped ones; toMap() makes the final map.
    var reviewed by mutableStateOf(seenPrefs.all.mapNotNull { (k, v) -> (v as? Float)?.let { k to it.toDouble() } ?: (v as? String)?.toDoubleOrNull()?.let { k to it } }.toMap())
        private set
    val pictures = mutableStateListOf<String>()      // data: URLs sent with the next message (the full agent sees them)
    // The /commands the project offers (shown as suggestions when the person types a slash).
    var commands by mutableStateOf<List<CodeCommand>>(emptyList())
        private set

    // ---- dialogs (/memory, /permissions)
    // The notes VryxCode has remembered (shown in the /memory dialog), or null when that dialog is closed.
    var memory by mutableStateOf<List<String>?>(null)
        private set
    // The permission rules (allowed / denied things) for the /permissions dialog, or null when it is closed.
    var rules by mutableStateOf<CodeRules?>(null)
        private set

    // A computed property (re-evaluated each time it is read): true while the agent is busy or waiting on the person.
    val working get() = state in setOf("starting", "working", "asking", "queued")
    val oneModel get() = info?.effort != null                       // feature flag vryxcode_effort: effort instead of a model picker

    /**
     * Loads everything the VryxCode home needs: start-up info, the session list and the project's /commands. Call it when the screen opens.
     * Runs in the background (a coroutine, a function that can pause while waiting for the network); failures become a message in [error].
     */
    fun load() {
        error = null
        viewModelScope.launch {
            try {
                // Ask the server for the start-up info; this call pauses the coroutine until the reply arrives, without freezing the screen.
                val i = api.codeInfo()
                info = i
                // `?.let` runs only if usage is not null.
                i.usage?.let { usage = it }
                // With the effort feature on, one automatic model is used, so pick its id (or keep the current one).
                if (i.effort != null) model = i.effort.auto ?: model
                // Otherwise, if no model is chosen or the chosen one is not ready, pick the first ready model (or none).
                if (model.isEmpty() || i.models.none { it.id == model && it.ready }) model = i.models.firstOrNull { it.ready }?.id ?: ""
                // Choose the project: the server's suggestion, else the first one, else keep the current.
                project = i.project ?: i.projects.firstOrNull() ?: project
                // If the chosen place to run is not available, go back to "local" (this computer).
                if (i.environments.none { it.id == env && it.available }) env = "local"
                // Fetch the session list.
                sessions = api.codeSessions()
                // If notifications are on and a session is still running, start the background watcher that will notify when it finishes.
                if (alerts && sessions.any { it.live }) app.emvryx.android.WatchService.start(getApplication())   // one still working: keep an eye on it
                // Fetch the /commands; runCatching turns a failure into a result we can default, so a missing list never blocks loading.
                commands = runCatching { api.codeCommands(project) }.getOrDefault(emptyList())
            } catch (e: Exception) {
                // Any failure (PC off, bad reply ...) becomes a plain-words message for the screen.
                error = describe(e)
            }
        }
    }

    /** Opens an empty "new session" screen: stops any polling and clears everything left from the previous session. */
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
        docs.clear()
        buildHere = false
    }

    /** A new session in this project (the + on a project, or picking it): it builds there, not in a new project */
    fun newSessionIn(p: String) {
        project = p
        newSession()
        buildHere = true
    }

    /** Where a new idea will be built (flag vryxcode_projects): this project, or a new one named from the idea */
    fun whereFor(text: String): String =
        if (!projects || buildHere) project else freeName(ideaName(text), info?.projects.orEmpty())

    /** A notification tapped: that session, from the list (read again if it is not in it yet) */
    fun openById(id: String) {
        viewModelScope.launch {
            // Look in the list we have; if it is missing, fetch the list again (`?:` means "otherwise") and look once more.
            val row = sessions.firstOrNull { it.id == id } ?: runCatching { api.codeSessions() }.getOrNull()?.also { sessions = it }?.firstOrNull { it.id == id }
            if (row != null) openSession(row)
        }
    }

    /** Opens an existing session: remembers it was seen, clears the old feed and starts polling for its events. */
    fun openSession(row: CodeSessionRow) {
        reviewed = reviewed + (row.id to row.updated)                  // opened: no longer "Ready for review"
        // Save the opened time to the phone's storage; apply() writes it in the background.
        seenPrefs.edit().putString(row.id, row.updated.toString()).apply()
        stopPolling()
        sid = row.id
        project = row.project.ifEmpty { project }
        // Use the session's own model for the next message when it is ready (and the effort feature is not choosing the model).
        if (info?.models?.any { it.id == row.model && it.ready } == true && !oneModel) model = row.model
        inSession = true
        events.clear()
        seen = 0
        pending = null
        pictures.clear()
        docs.clear()
        poll()
    }

    /** Leaves the session screen and refreshes the sessions list in the background. */
    fun backToList() {
        stopPolling()
        inSession = false
        sid = null
        viewModelScope.launch { runCatching { api.codeSessions() }.onSuccess { sessions = it } }
    }

    // Cancels the polling loop, if one is running.
    private fun stopPolling() {
        poller?.cancel()
        poller = null
    }

    /** Reads what happened since the last look; keeps reading while it works (every 0.4 s, 1.5 s while it waits for an answer) */
    private fun poll() {
        val id = sid ?: return
        poller?.cancel()
        // Start a new background loop. It keeps asking the server for new events until the agent stops being busy.
        poller = viewModelScope.launch {
            // Counts failed requests in a row, so one blip on a phone network does not show an error.
            var fails = 0
            // isActive turns false when the Job is cancelled, which ends the loop.
            while (isActive) {
                try {
                    // Ask for the events after number `seen`, plus the current state and any pending question.
                    val v = api.codeView(id, seen)
                    fails = 0
                    if (error != null && error == pollError) error = null      // the connection came back: the old warning goes
                    pollError = null
                    // Append the new events and count them, so the next request starts after them.
                    events.addAll(v.events)
                    v.events.forEach(::offerFrom)
                    seen += v.events.size
                    // Copy the rest of the reply into the fields the screen watches.
                    state = v.state
                    pending = v.pending
                    full = v.full
                    v.usage?.let { usage = it }
                    liveLine = v.live?.let(::liveText)
                    // Finished or stopped: leave the loop. Otherwise wait before asking again (longer while waiting on the person, 1500 ms vs 400 ms, to save battery).
                    if (!v.working) break
                    delay(if (v.state == "asking") 1500 else 400)
                } catch (e: kotlinx.coroutines.CancellationException) {
                    // Cancellation is how a coroutine is told to stop; it must be passed on (re-thrown), never treated as a failure.
                    throw e                                     // a newer check took over (after sending, opening a session): not a problem to show
                } catch (e: Exception) {
                    // A network or server failure: count it, wait 3 seconds and try again.
                    fails += 1
                    if (fails >= 3) {                           // one dropped answer on a phone network is normal: only say so when it keeps failing
                        error = describe(e)
                        pollError = error
                    }
                    delay(3000)
                }
            }
        }
    }

    // The error text set by polling, kept so that only that same message is cleared when the connection returns.
    private var pollError: String? = null

    /** The send button: a new session, the next message, or (the full agent, while it works) a message it reads before its next step */
    fun send(text: String) {
        // Ignore a send with no text and no pictures.
        val words = text.trim()
        if (words.isEmpty() && pictures.isEmpty()) return
        error = null
        // A /command that the app answers itself is handled here and not sent to the server.
        if (words.startsWith("/") && runSlash(words)) return
        offer = ""
        viewModelScope.launch {
            try {
                // Pick what sending means: a steering note to a working full agent, the next message of an open session, or the first message of a new one.
                val id = sid
                when {
                    id != null && working && full -> api.codeSteer(id, words)
                    id != null -> api.codeMessage(id, body(words, start = false))
                    else -> {
                        // Which project the new idea goes into.
                        val where = whereFor(words)
                        if (where != project) {                 // vryxcode_projects: a new idea gets its own project
                            project = where
                            info = info?.let { it.copy(projects = it.projects + where) }
                        }
                        buildHere = false
                        // Create the session on the server; the reply carries its id.
                        val r = api.codeStart(body(words, start = true))
                        sid = r.id
                        events.clear()
                        seen = 0
                    }
                }
                pictures.clear()
                docs.clear()
                poll()
                if (alerts) app.emvryx.android.WatchService.start(getApplication())    // the phone keeps an eye on it, and says when it is done
            } catch (e: Exception) {
                error = describe(e)
            }
        }
    }

    /**
     * What to suggest next, as the website does: "build it" after a plan, otherwise the first of the model's suggested next steps.
     * Looks at one event [e] and updates [offer]: cleared when the person speaks, set when a turn ends. `e.str("kind")` reads the text field "kind".
     */
    private fun offerFrom(e: JsonObject) {
        when (e.str("kind")) {
            "user", "start" -> offer = ""
            "end" -> if (e.bool("finished") || e.bool("plan")) offer = if (!suggestOn) "" else if (e.bool("plan")) "Go ahead and build it as planned." else e.strings("next").firstOrNull().orEmpty().take(200)
        }
    }

    // Builds the JSON the server expects. A first message (start = true) also names the project, task, place to run and queue flag;
    // a follow-up carries just the text. Model, effort and the Ask/Auto/Plan mode go in both; pictures and documents are added when present.
    private fun body(text: String, start: Boolean): JsonObject = buildJsonObject {
        if (start) {
            put("project", project); put("task", text); put("env", env); put("queue", true)
        } else put("text", text)
        put("model", model); put("effort", effort)
        put("auto_edits", mode == "auto"); put("plan", mode == "plan")
        if (pictures.isNotEmpty()) putJsonArray("images") { pictures.forEach { add(JsonPrimitive(it)) } }
        if (docs.isNotEmpty()) putJsonArray("docs") { docs.forEach { add(JsonPrimitive(it.id)) } }
    }

    var onWeb: ((String, String) -> Unit)? = null      // opens the website's VryxCode with this script (Preview, Save to GitHub, Publish)
    var parity by mutableStateOf<Set<String>>(emptySet())   // flag android_vryxcode: the website's newer VryxCode parts that are switched on (their own flags)

    /** Restore on a message (flag vryxcode_restore): the files go back to just before it */
    fun restore(turn: Int) {
        val id = sid ?: return
        viewModelScope.launch {
            try { api.codeRewind(id, turn); error = null } catch (e: Exception) { error = describe(e) }
            poll()
        }
    }

    /** Asks the server to stop the working agent, then polls once to show the new state. */
    fun stop() {
        val id = sid ?: return
        viewModelScope.launch { runCatching { api.codeStop(id) }; poll() }
    }

    /** A permission question: Yes / Yes and don't ask again / No */
    fun answer(allow: Boolean, always: Boolean = false) {
        val id = sid ?: return
        // The pending question's id (a number); with no pending question there is nothing to answer.
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

    /** A PDF, Word or text file for VryxCode to read with the next message: kept in your Documents (code.js pickDocs) */
    fun addDoc(name: String, bytes: ByteArray) {
        if (docs.size >= 8) return
        if (bytes.size > 10_000_000) {
            error = "$name is over 10 MB."
            return
        }
        viewModelScope.launch {
            try {
                docs.add(api.upload(name, bytes))
            } catch (e: Exception) {
                error = "$name was not attached: " + describe(e)
            }
        }
    }

    /** Attaches a picture to the next message: at most 3, each under 5 MB, and only PNG, JPEG, WebP or GIF. [bytes] is the file's content. */
    fun addPicture(name: String, bytes: ByteArray) {
        if (pictures.size >= 3 || bytes.size > 5_000_000) {
            error = "Up to 3 pictures, 5 MB each."
            return
        }
        // The file extension in lower case ("png" if there is none); "jpg" is called "jpeg" in picture web addresses.
        val ext = name.substringAfterLast('.', "png").lowercase().let { if (it == "jpg") "jpeg" else it }
        if (ext !in setOf("png", "jpeg", "webp", "gif")) {
            error = "Pictures can be PNG, JPEG, WebP or GIF."
            return
        }
        // A "data URL" holds the whole picture inside text: base64 turns the bytes into letters; NO_WRAP keeps it on one line.
        pictures.add("data:image/$ext;base64," + android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP))
    }

    // ---- /commands that the app answers itself (the rest go to the server: a project's own /commands become their text there)
    // Handles /commands the app can answer itself. Returns true if it did (so the text is not sent), false to let the server handle it.
    private fun runSlash(text: String): Boolean {
        // Look only at the first word (before the first space), in lower case.
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

    /** Opens the /memory dialog by fetching what VryxCode remembers. */
    fun showMemory() {
        viewModelScope.launch { runCatching { api.codeMemory() }.onSuccess { memory = it.notes }.onFailure { error = describe(it as? Exception ?: Exception(it)) } }
    }

    /** Forgets one remembered note (by its position) or, when [index] is null, all of them, and shows the updated list. */
    fun forget(index: Int?) {
        viewModelScope.launch { runCatching { api.codeForget(index) }.onSuccess { memory = it.notes } }
    }

    /** Closes the /memory dialog. */
    fun closeMemory() {
        memory = null
    }

    /** Opens the /permissions dialog by fetching this project's rules. */
    fun showRules() {
        viewModelScope.launch { runCatching { api.codeRules(project) }.onSuccess { rules = it }.onFailure { error = describe(it as? Exception ?: Exception(it)) } }
    }

    /** Adds a permission rule of the given [kind] (allow or deny) with the typed [rule] text. */
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

    /** Removes one permission rule. */
    fun removeRule(rule: String) {
        viewModelScope.launch { runCatching { api.codeRule(project, remove = rule) }.onSuccess { rules = it } }
    }

    /** Closes the /permissions dialog. */
    fun closeRules() {
        rules = null
    }

    /** /fixci: what is failing on GitHub for this project becomes a new session */
    fun fixCi() {
        viewModelScope.launch {
            try {
                // Ask the server to start a session that fixes the failing GitHub checks of this project.
                val r = api.codeFixCi(buildJsonObject { put("project", project); put("model", model); put("effort", effort); put("env", env) })
                // No session id came back: nothing was failing (or the server said why). `return@launch` leaves the background task.
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

    // Turns an exception into a message a person can understand: PC off, a server message (plus advice), or a generic try-again line.
    private fun describe(e: Exception): String = when (e) {
        is OfflineException -> "Emvryx is off right now. The PC may be switched off or asleep."
        is ApiException -> listOf(e.message, e.action).filter { it.isNotBlank() }.joinToString(" ")
        else -> "Something went wrong. Please try again."
    }
}

/** The line under the newest step while it works, as the website's (ide.js paintLive): "Calling · write_file · index.html · 12s · 1,234 tokens" */
internal fun liveText(l: JsonObject): String {
    // Capitalise the first letter of the phase, e.g. "calling" becomes "Calling".
    val phase = l.str("phase").replaceFirstChar { it.uppercase() }
    // Seconds spent so far and tokens used so far (a token is a small chunk of text the model counts in).
    val secs = l.num("secs").toInt()
    val tokens = l.int("tokens")
    // Join the non-empty parts with a middle dot; the target is cut to its first line and 60 characters, and tokens use thousands commas.
    return listOf(phase, l.str("tool"), l.str("target").lineSequence().firstOrNull().orEmpty().take(60), "${secs}s",
        if (tokens > 0) "%,d tokens".format(tokens) else "").filter { it.isNotBlank() }.joinToString(" · ")
}
