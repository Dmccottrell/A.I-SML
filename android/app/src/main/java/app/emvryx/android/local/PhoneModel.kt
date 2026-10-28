package app.emvryx.android.local

import android.app.ActivityManager
import android.content.Context
import android.os.StatFs
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.emvryx.android.data.ApiClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest

/**
 * android_offline_model: your small Flare model on the phone. It is downloaded from your PC once (and carries on where it stopped), checked
 * against the PC's checksum, and then answers chats here when the PC is off. Your instructions and what Emvryx remembers come with it and are
 * refreshed whenever the PC answers. The chats written here stay on the phone.
 */
class PhoneModel(private val context: Context, private val api: ApiClient) {
    sealed interface Status {
        data object None : Status
        data class Downloading(val done: Long, val total: Long) : Status
        data object Checking : Status
        data object Ready : Status
        data class Failed(val message: String) : Status
    }

    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val dir = File(context.filesDir, "phone-model").apply { mkdirs() }
    private val modelFile = File(dir, "model.gguf")
    private val partFile = File(dir, "model.gguf.part")
    private val kitFile = File(dir, "kit.json")
    private val chatsFile = File(dir, "chats.json")
    private val prefs = context.getSharedPreferences("emvryx_phone_model", Context.MODE_PRIVATE)

    /** The android_offline_model switch as it was the last time the PC answered (offline, it cannot be asked) */
    var allowed by mutableStateOf(prefs.getBoolean("allowed", false))
        private set
    var kit by mutableStateOf(readKit())
        private set
    var status by mutableStateOf<Status>(if (modelFile.exists() && kit != null) Status.Ready else Status.None)
        private set
    private var job: Job? = null
    /** A newer model is on the PC than the one on this phone (Settings offers to download it) */
    var newer by mutableStateOf<PhoneKit?>(null)
        private set

    // ---- the chats written on this phone
    val chats = mutableStateListOf<LocalChat>().apply { addAll(readChats()) }
    var writing by mutableStateOf(false)
        private set
    private var loaded: Llama.Model? = null
    private var loadedId = ""

    fun rememberAllowed(on: Boolean) {
        allowed = on
        prefs.edit().putBoolean("allowed", on).apply()
    }

    private fun readKit(): PhoneKit? = runCatching { json.decodeFromString<PhoneKit>(kitFile.readText()) }.getOrNull()

    /** The PC answered: keep the newest instructions, memory and format (the model file itself only changes with Download) */
    suspend fun refresh() {
        if (!allowed) return
        val k = runCatching { api.phoneKit(kit?.id ?: wanted) }.getOrNull() ?: return
        choices = k.choices
        if (!k.available) return
        val have = kit ?: return                                          // nothing downloaded yet: nothing to keep up to date
        if (have.id != k.id || (k.sha256 != null && k.sha256 != have.sha256)) {
            newer = k                                                     // a newer model is on the PC: Settings offers it
            return
        }
        val fresh = k.copy(sha256 = have.sha256, size = have.size)
        kit = fresh
        withContext(Dispatchers.IO) { runCatching { kitFile.writeText(json.encodeToString(fresh)) } }
    }


    fun enoughRam(k: PhoneKit): Boolean = enoughRam(k.minRamGb)

    fun enoughRam(gb: Double): Boolean {
        val mi = ActivityManager.MemoryInfo()
        (context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(mi)
        return mi.totalMem >= (gb * 0.9 * 1024 * 1024 * 1024).toLong()
    }

    /** The models the PC offers for phones (Flare, Equinox), once it has been asked */
    var choices by mutableStateOf<List<PhoneChoice>>(emptyList())
        private set

    /** The model picked in Settings > This phone (null: the PC's default, the small one) */
    var wanted by mutableStateOf(prefs.getString("wanted", null))
        private set

    fun pick(id: String) {
        wanted = id
        prefs.edit().putString("wanted", id).apply()
    }

    suspend fun loadChoices() {
        if (!allowed || choices.isNotEmpty()) return
        runCatching { api.phoneKit(kit?.id ?: wanted) }.getOrNull()?.let { choices = it.choices }
    }

    fun freeSpace(): Long = StatFs(dir.path).availableBytes

    fun canRun(): Boolean = Llama.available(context.applicationInfo.nativeLibraryDir)

    /** Downloads the model from the PC, carrying on from what is already here, then checks it */
    fun download() {
        if (job?.isActive == true) return
        job = scope.launch {
            try {
                var k = api.phoneKit(wanted)
                choices = k.choices
                if (!k.available) { status = Status.Failed(k.message.ifEmpty { "The PC has no model for phones." }); return@launch }
                while (k.sha256 == null && isActive) {                       // the PC works out the checksum the first time (a few seconds)
                    status = Status.Checking
                    delay(3000)
                    k = api.phoneKit(wanted)
                }
                if (!canRun()) { status = Status.Failed("This phone cannot run the model (it needs a 64-bit phone)."); return@launch }
                if (!enoughRam(k)) { status = Status.Failed("This phone has less memory than the model needs (${k.minRamGb.toInt()} GB)."); return@launch }
                val have = if (partFile.exists()) partFile.length() else 0L
                if (freeSpace() < k.size - have + 200L * 1024 * 1024) {
                    status = Status.Failed("Not enough free space: about ${(k.size + (1 shl 29)) / (1 shl 30)} GB is needed.")
                    return@launch
                }
                if (have > k.size || prefs.getString("part_sha", "") != k.sha256) partFile.delete()     // a part of another model: start over
                prefs.edit().putString("part_sha", k.sha256).apply()
                var done = if (partFile.exists()) partFile.length() else 0L
                status = Status.Downloading(done, k.size)
                if (done < k.size) api.downloadFrom(k.file, done).use { r ->
                    if (r.code == 200 && done > 0) { partFile.delete(); done = 0 }    // the PC sent it all again: start over
                    else if (!r.isSuccessful) throw IllegalStateException("The download was refused (${r.code}).")
                    val body = r.body ?: throw IllegalStateException("The PC sent nothing.")
                    FileOutputStream(partFile, done > 0).use { out ->
                        val buf = ByteArray(1 shl 16)
                        val input = body.byteStream()
                        var last = 0L
                        while (isActive) {
                            val n = input.read(buf)
                            if (n < 0) break
                            out.write(buf, 0, n)
                            done += n
                            if (done - last > 4L * 1024 * 1024) { last = done; status = Status.Downloading(done, k.size) }
                        }
                    }
                }
                if (!isActive) return@launch
                if (partFile.length() != k.size) throw IllegalStateException("The download stopped early. Try again: it carries on where it was.")
                status = Status.Checking
                if (sha256(partFile) != k.sha256) {
                    partFile.delete()
                    status = Status.Failed("The download arrived damaged and was removed. Please download it again.")
                    return@launch
                }
                close()
                modelFile.delete()
                partFile.renameTo(modelFile)
                kitFile.writeText(json.encodeToString(k))
                kit = k
                newer = null
                status = Status.Ready
            } catch (e: Exception) {
                status = Status.Failed(when (e) {
                    is app.emvryx.android.data.OfflineException -> "The PC could not be reached. Try again when it is on: the download carries on where it stopped."
                    else -> e.message ?: "The download stopped."
                })
            }
        }
    }

    fun cancel() {
        job?.cancel()
        status = if (modelFile.exists() && kit != null) Status.Ready else Status.None
    }

    /** Removes the model from the phone (the chats written here stay) */
    fun remove() {
        cancel()
        close()
        modelFile.delete()
        partFile.delete()
        kitFile.delete()
        kit = null
        status = Status.None
    }

    /** Frees the chat model's memory (the picture model is about to be loaded); it loads again on the next answer */
    fun unload() = close()

    private fun close() {
        loaded?.close()
        loaded = null
        loadedId = ""
    }

    private fun sha256(f: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        f.inputStream().use { input ->
            val buf = ByteArray(1 shl 20)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    // ---- answering

    private fun readChats(): List<LocalChat> = runCatching { json.decodeFromString<List<LocalChat>>(chatsFile.readText()) }.getOrDefault(emptyList())

    private fun saveChats() {
        val keep = LocalSync.keep(chats.toList(), MAX_CHATS)
        runCatching { chatsFile.writeText(json.encodeToString(keep)) }
    }

    fun newChat(): LocalChat = LocalChat(System.currentTimeMillis(), "New chat", emptyList(), updated = System.currentTimeMillis()).also { chats.add(it); saveChats() }

    // ---- the PC's chats kept on the phone, and the phone's chats sent to the PC (both only while the switch is on)

    /** Keeps a copy of one of the PC's chats; returns the phone's id for it */
    fun keepCopy(c: app.emvryx.android.data.Chat): Long {
        val turns = c.messages.filter { (it.role == "user" || it.role == "assistant") && it.content.isNotBlank() }.map { LocalTurn(it.role == "user", it.content) }
        val i = chats.indexOfFirst { it.serverId == c.id }
        val merged = LocalSync.merge(chats.getOrNull(i), c.id, c.title, turns, System.currentTimeMillis())
        if (i >= 0) chats[i] = merged else chats.add(merged)
        saveChats()
        return merged.id
    }

    /** The PC is there: copies of the most recent chats (at most every 10 minutes, unless [force]) */
    suspend fun keepRecent(list: List<app.emvryx.android.data.ChatSummary>, force: Boolean = false) {
        if (!allowed) return
        val now = System.currentTimeMillis()
        if (!force && now - prefs.getLong("kept_at", 0) < 10 * 60_000) return
        prefs.edit().putLong("kept_at", now).apply()
        for (s in list.filter { it.id >= 0 }.take(KEEP_RECENT)) {
            val c = runCatching { api.chat(s.id) }.getOrNull() ?: break      // the PC went away: stop, try again next time
            withContext(Dispatchers.Main) { keepCopy(c) }
        }
    }

    /** Sends what was written on the phone to the PC. Returns how many chats were sent. */
    suspend fun syncUp(): Int {
        if (!allowed || writing) return 0
        var sent = 0
        for (c in chats.toList().filter { it.pending.isNotEmpty() }) {
            val body = kotlinx.serialization.json.buildJsonObject {
                put("sync_id", kotlinx.serialization.json.JsonPrimitive(LocalSync.syncId(c)))
                c.serverId?.let { put("chat", kotlinx.serialization.json.JsonPrimitive(it)) }
                put("title", kotlinx.serialization.json.JsonPrimitive(c.title))
                put("model", kotlinx.serialization.json.JsonPrimitive(kit?.id ?: "phone"))
                put("messages", kotlinx.serialization.json.JsonArray(c.pending.map { t ->
                    kotlinx.serialization.json.buildJsonObject {
                        put("role", kotlinx.serialization.json.JsonPrimitive(if (t.mine) "user" else "assistant"))
                        put("content", kotlinx.serialization.json.JsonPrimitive(t.text))
                    }
                }))
            }
            val id = runCatching { api.phoneSync(body) }.getOrNull() ?: break
            withContext(Dispatchers.Main) {
                val j = chats.indexOfFirst { it.id == c.id }
                if (j >= 0) chats[j] = chats[j].copy(serverId = id, synced = c.turns.size)
                saveChats()
            }
            sent++
        }
        return sent
    }

    /** The chat the phone's chat screen opens next, and a question to answer there at once (the PC dropped while it was being sent) */
    var openChat by mutableStateOf<Long?>(null)
    var ask by mutableStateOf<String?>(null)

    /** Carries a chat on here: the PC's chat [serverId] with the [turns] it has (or a new chat), then [question] is answered on the phone */
    fun carryOn(serverId: Long?, title: String, turns: List<LocalTurn>, question: String) {
        val id = if (serverId != null && serverId >= 0) {
            val i = chats.indexOfFirst { it.serverId == serverId }
            val merged = LocalSync.merge(chats.getOrNull(i), serverId, title, turns, System.currentTimeMillis())
            if (i >= 0) chats[i] = merged else chats.add(merged)
            saveChats()
            merged.id
        } else newChat().id
        openChat = id
        ask = question
    }

    fun deleteChat(id: Long) {
        chats.removeAll { it.id == id }
        saveChats()
    }

    @Volatile private var stopping = false

    fun stop() {
        stopping = true
        loaded?.stop()
    }

    /**
     * Answers [question] in chat [chatId], calling [onText] with the answer so far. Returns null when it went well, else what went wrong.
     * Runs on a background thread (the model is loaded the first time, which takes a few seconds).
     */
    suspend fun answer(chatId: Long, question: String, onText: (String) -> Unit): String? = withContext(Dispatchers.Default) {
        val k = kit ?: return@withContext "The model is not on this phone yet."
        val i = chats.indexOfFirst { it.id == chatId }
        if (i < 0) return@withContext "That chat is gone."
        val history = chats[i].turns
        withContext(Dispatchers.Main) {
            chats[i] = chats[i].copy(turns = history + LocalTurn(true, question) + LocalTurn(false, ""),
                                     title = if (history.isEmpty()) question.take(48) else chats[i].title, updated = System.currentTimeMillis())
            writing = true
        }
        stopping = false
        try {
            val (shown, end) = generateWith(k, history, question, k.maxReplyTokens, onText) ?: return@withContext loadError
            withContext(Dispatchers.Main) {
                val j = chats.indexOfFirst { it.id == chatId }
                if (j >= 0) chats[j] = chats[j].copy(turns = history + LocalTurn(true, question) + LocalTurn(false, shown.ifEmpty { "…" }))
                saveChats()
            }
            onText(shown)
            when (end) {
                Llama.End.TooLong -> "That message is too long for the phone's model."
                Llama.End.Failed -> "The phone's model stopped. Please try again."
                else -> null
            }
        } finally {
            withContext(Dispatchers.Main) { writing = false }
        }
    }

    private var loadError = ""

    /** Loads the model if needed and writes the answer to [question] after [history]: (text, how it ended), or null (loadError says why) */
    private fun generateWith(k: PhoneKit, history: List<LocalTurn>, question: String, maxTokens: Int, onText: (String) -> Unit): Pair<String, Llama.End>? {
        val model = loaded?.takeIf { loadedId == k.id } ?: run {
            close()
            if (!canRun()) { loadError = "This phone cannot run the model."; return null }
            Llama.load(modelFile.path, k.context)?.also { loaded = it; loadedId = k.id }
                ?: run { loadError = "The model could not be loaded: the phone may not have enough free memory. Close other apps and try again."; return null }
        }
        val prompt = LocalPrompt.build(k, history, question) { model.count(it) }
        val joiner = Utf8Joiner()
        var last = 0L
        val end = model.generate(prompt, maxTokens, k.sampling) { bytes ->
            joiner.add(bytes)
            val (text, done) = LocalPrompt.shown(joiner.text, k.format.stop)
            val now = System.currentTimeMillis()
            if (now - last > 50) { last = now; onText(text) }
            !done && !stopping
        }
        return LocalPrompt.shown(joiner.text, k.format.stop).first.trimEnd() to end
    }

    // ---- VryxCode drafts: written here with the PC off, run on the PC when it is back

    val drafts = mutableStateListOf<CodeDraft>().apply { addAll(readDrafts()) }
    private val draftsFile get() = File(dir, "drafts.json")

    private fun readDrafts(): List<CodeDraft> = runCatching { json.decodeFromString<List<CodeDraft>>(File(dir, "drafts.json").readText()) }.getOrDefault(emptyList())

    private fun saveDrafts() {
        runCatching { draftsFile.writeText(json.encodeToString(drafts.toList().takeLast(MAX_DRAFTS))) }
    }

    fun deleteDraft(id: Long) {
        drafts.removeAll { it.id == id }
        saveDrafts()
    }

    /** Writes a draft for [request] in [project]; [onText] shows it as it is written. Returns null when it went well, else what went wrong. */
    suspend fun writeDraft(project: String, request: String, onText: (String) -> Unit): String? = withContext(Dispatchers.Default) {
        val k = kit ?: return@withContext "The model is not on this phone yet."
        withContext(Dispatchers.Main) { writing = true }
        stopping = false
        try {
            val (text, end) = generateWith(k, emptyList(), request.trim() + "\n\n" + DraftWriter.INSTRUCTION, maxOf(k.maxReplyTokens, DRAFT_TOKENS), onText)
                ?: return@withContext loadError
            val (files, note) = DraftWriter.parse(text)
            if (files.isEmpty()) return@withContext if (end == Llama.End.Stopped) "Stopped." else "No files came out of it. Try saying more exactly what to build."
            withContext(Dispatchers.Main) {
                drafts.add(CodeDraft(System.currentTimeMillis(), project.trim(), request.trim(), files, note, made = System.currentTimeMillis(), model = k.id))
                saveDrafts()
            }
            null
        } finally {
            withContext(Dispatchers.Main) { writing = false }
        }
    }

    /** The PC is back: drafts not sent yet go to it. Returns how many were sent. */
    suspend fun syncDrafts(): Int {
        if (!allowed) return 0
        var sent = 0
        for (d in drafts.toList().filter { it.serverId == null }) {
            val body = kotlinx.serialization.json.buildJsonObject {
                put("sync_id", kotlinx.serialization.json.JsonPrimitive(DraftWriter.syncId(d)))
                put("project", kotlinx.serialization.json.JsonPrimitive(d.project))
                put("request", kotlinx.serialization.json.JsonPrimitive(d.request))
                put("note", kotlinx.serialization.json.JsonPrimitive(d.note))
                put("model", kotlinx.serialization.json.JsonPrimitive(d.model))
                put("files", kotlinx.serialization.json.JsonArray(d.files.map { f ->
                    kotlinx.serialization.json.buildJsonObject {
                        put("path", kotlinx.serialization.json.JsonPrimitive(f.path))
                        put("content", kotlinx.serialization.json.JsonPrimitive(f.content))
                    }
                }))
            }
            val id = runCatching { api.codeDraft(body) }.getOrNull() ?: continue          // a bad draft (or the PC went away): the others still go
            withContext(Dispatchers.Main) {
                val i = drafts.indexOfFirst { it.id == d.id }
                if (i >= 0) drafts[i] = drafts[i].copy(serverId = id)
                saveDrafts()
            }
            sent++
        }
        return sent
    }

    /** Starts a VryxCode session on the PC that writes, runs and tests the draft. Null when it started, else what went wrong. */
    suspend fun runDraft(d: CodeDraft): String? {
        if (d.serverId == null && syncDrafts() == 0 && drafts.firstOrNull { it.id == d.id }?.serverId == null) return "The PC could not be reached."
        val id = drafts.firstOrNull { it.id == d.id }?.serverId ?: return "The PC could not be reached."
        return runCatching { api.codeDraftRun(id); null }.getOrElse { (it as? app.emvryx.android.data.ApiException)?.message ?: "The PC could not be reached." }
    }

    companion object {
        const val MAX_DRAFTS = 30
        const val DRAFT_TOKENS = 2048
        const val MAX_CHATS = 60
        const val KEEP_RECENT = 30
    }
}

/** A chat on the phone. [serverId]: the PC's chat it is a copy of (null: started on the phone); [synced]: how many of its turns the PC has. */
@kotlinx.serialization.Serializable
data class LocalChat(val id: Long, val title: String, val turns: List<LocalTurn>, val serverId: Long? = null, val synced: Int = 0,
                     val updated: Long = 0) {
    /** Written on the phone and not on the PC yet */
    val pending get() = turns.drop(synced).filter { it.text.isNotBlank() && it.text != "…" }
}

/** The rules for keeping the phone's chats and the PC's in step (plain code, so it is tested on its own) */
object LocalSync {
    /** The PC's copy of a chat, kept on the phone: what was written on the phone and not synced yet stays at the end. */
    fun merge(existing: LocalChat?, serverId: Long, title: String, serverTurns: List<LocalTurn>, now: Long): LocalChat {
        val extra = existing?.turns?.drop(existing.synced).orEmpty()
        return LocalChat(existing?.id ?: (now * 1000 + (serverId % 1000)), title, serverTurns + extra, serverId, serverTurns.size,
                         if (extra.isNotEmpty()) existing!!.updated else now)
    }

    /** The same sync id for the same turns, so a sync sent again after a lost answer is not added twice */
    fun syncId(c: LocalChat) = "${c.id}-${c.synced}-${c.turns.size}"

    /** Which chats to keep: every chat with something not synced, then the newest, up to [max] */
    fun keep(chats: List<LocalChat>, max: Int): List<LocalChat> {
        val must = chats.filter { it.pending.isNotEmpty() }
        val rest = chats.filter { it.pending.isEmpty() }.sortedByDescending { it.updated }.take(maxOf(0, max - must.size))
        return chats.filter { c -> must.any { it.id == c.id } || rest.any { it.id == c.id } }
    }
}
