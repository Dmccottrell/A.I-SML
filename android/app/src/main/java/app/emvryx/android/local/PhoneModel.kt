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
        val k = runCatching { api.phoneKit() }.getOrNull() ?: return
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


    fun enoughRam(k: PhoneKit): Boolean {
        val mi = ActivityManager.MemoryInfo()
        (context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(mi)
        return mi.totalMem >= (k.minRamGb * 0.9 * 1024 * 1024 * 1024).toLong()
    }

    fun freeSpace(): Long = StatFs(dir.path).availableBytes

    fun canRun(): Boolean = Llama.available(context.applicationInfo.nativeLibraryDir)

    /** Downloads the model from the PC, carrying on from what is already here, then checks it */
    fun download() {
        if (job?.isActive == true) return
        job = scope.launch {
            try {
                var k = api.phoneKit()
                if (!k.available) { status = Status.Failed(k.message.ifEmpty { "The PC has no model for phones." }); return@launch }
                while (k.sha256 == null && isActive) {                       // the PC works out the checksum the first time (a few seconds)
                    status = Status.Checking
                    delay(3000)
                    k = api.phoneKit()
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
        val keep = chats.takeLast(MAX_CHATS)
        runCatching { chatsFile.writeText(json.encodeToString(keep)) }
    }

    fun newChat(): LocalChat = LocalChat(System.currentTimeMillis(), "New chat", emptyList()).also { chats.add(it); saveChats() }

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
                                     title = if (history.isEmpty()) question.take(48) else chats[i].title)
            writing = true
        }
        stopping = false
        try {
            val model = loaded?.takeIf { loadedId == k.id } ?: run {
                close()
                if (!canRun()) return@withContext "This phone cannot run the model."
                Llama.load(modelFile.path, k.context)?.also { loaded = it; loadedId = k.id }
                    ?: return@withContext "The model could not be loaded: the phone may not have enough free memory. Close other apps and try again."
            }
            val prompt = LocalPrompt.build(k, history, question) { model.count(it) }
            val joiner = Utf8Joiner()
            var shown = ""
            var last = 0L
            val end = model.generate(prompt, k.maxReplyTokens, k.sampling) { bytes ->
                joiner.add(bytes)
                val (text, done) = LocalPrompt.shown(joiner.text, k.format.stop)
                shown = text
                val now = System.currentTimeMillis()
                if (now - last > 50) { last = now; onText(text) }
                !done && !stopping
            }
            shown = LocalPrompt.shown(joiner.text, k.format.stop).first.trimEnd()
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

    companion object {
        const val MAX_CHATS = 30
    }
}

@kotlinx.serialization.Serializable
data class LocalChat(val id: Long, val title: String, val turns: List<LocalTurn>)
