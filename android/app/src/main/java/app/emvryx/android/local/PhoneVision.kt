package app.emvryx.android.local

import android.content.Context
import androidx.compose.runtime.getValue
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
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest

/** One of the picture model's two files (GET /api/phone-model/vision, app/phone_model.py vision_kit) */
@Serializable
data class VisionPart(val size: Long = 0, val sha256: String? = null, val file: String = "")

@Serializable
data class VisionKit(val available: Boolean = false, val message: String = "", val parts: Map<String, VisionPart> = emptyMap(), val size: Long = 0,
                     val preparing: Boolean = false, val prompt: String = "", @SerialName("max_reply_tokens") val maxReplyTokens: Int = 600,
                     @SerialName("min_ram_gb") val minRamGb: Double = 6.0)

object Vision {
    val PARTS = listOf("model", "mmproj")

    /** The PC's picture-helper instructions with the person's question in them (vision.py PROMPT) */
    fun prompt(template: String, question: String) =
        template.replace("{question}", question.trim().ifEmpty { "What is in this picture?" })

    /** The message the phone's model gets: the question, then what the picture shows, as the PC gives its models the helper's notes */
    fun withPicture(question: String, seen: String): String {
        val q = question.trim().ifEmpty { "What is in this picture? Explain it briefly." }
        return q + "\n\n[What the picture I sent shows, looked at on this phone:]\n" + seen.trim().take(PictureText.MAX_CHARS)
    }
}

/**
 * android_phone_vision: the PC's picture model on the phone, so a picture sent with the PC off is looked at, not only its words read. Downloaded
 * once (two files, each carrying on where it stopped and checked against the PC's checksum). Looking at a picture loads it, writes what the
 * picture shows and frees it again, so it never sits in memory next to the chat model.
 */
class PhoneVision(private val context: Context, private val api: ApiClient, private val phone: PhoneModel) {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val dir = File(context.filesDir, "phone-vision").apply { mkdirs() }
    private val kitFile = File(dir, "kit.json")
    private fun file(part: String) = File(dir, "$part.gguf")
    private fun partial(part: String) = File(dir, "$part.gguf.part")

    private val prefs = context.getSharedPreferences("emvryx_phone_vision", Context.MODE_PRIVATE)

    /** The android_phone_vision switch as it was the last time the PC answered */
    var allowed by mutableStateOf(prefs.getBoolean("allowed", false))
        private set

    fun rememberAllowed(on: Boolean) {
        allowed = on
        prefs.edit().putBoolean("allowed", on).apply()
    }

    /** Ready to look at pictures */
    val usable get() = allowed && status == PhoneModel.Status.Ready

    var kit by mutableStateOf(runCatching { json.decodeFromString<VisionKit>(kitFile.readText()) }.getOrNull())
        private set
    var status by mutableStateOf<PhoneModel.Status>(if (ready()) PhoneModel.Status.Ready else PhoneModel.Status.None)
        private set
    private var job: Job? = null
    @Volatile private var stopping = false

    private fun ready() = kit != null && Vision.PARTS.all { file(it).exists() }

    fun download() {
        if (job?.isActive == true) return
        job = scope.launch {
            try {
                var k = api.phoneVision()
                if (!k.available) { status = PhoneModel.Status.Failed(k.message.ifEmpty { "The PC has no picture model." }); return@launch }
                while (k.preparing && isActive) {                            // the PC works out the checksums the first time
                    status = PhoneModel.Status.Checking
                    delay(3000)
                    k = api.phoneVision()
                }
                if (!phone.canRun()) { status = PhoneModel.Status.Failed("This phone cannot run the picture model (it needs a 64-bit phone)."); return@launch }
                if (!phone.enoughRam(k.minRamGb)) { status = PhoneModel.Status.Failed("This phone has less memory than the picture model needs (${k.minRamGb.toInt()} GB)."); return@launch }
                if (phone.freeSpace() < k.size + 200L * 1024 * 1024) {
                    status = PhoneModel.Status.Failed("Not enough free space: about ${(k.size + (1 shl 29)) / (1 shl 30)} GB is needed.")
                    return@launch
                }
                var before = 0L
                for (name in Vision.PARTS) {
                    val part = k.parts[name] ?: throw IllegalStateException("The PC's picture model is incomplete.")
                    val done = file(name)
                    if (!(done.exists() && done.length() == part.size && kit?.parts?.get(name)?.sha256 == part.sha256)) {
                        fetch(name, part, before, k.size)
                        if (!isActive) return@launch
                    }
                    before += part.size
                }
                kitFile.writeText(json.encodeToString(k))
                kit = k
                status = PhoneModel.Status.Ready
            } catch (e: Exception) {
                status = PhoneModel.Status.Failed(when (e) {
                    is app.emvryx.android.data.OfflineException -> "The PC could not be reached. Try again when it is on: the download carries on where it stopped."
                    else -> e.message ?: "The download stopped."
                })
            }
        }
    }

    private suspend fun fetch(name: String, part: VisionPart, before: Long, total: Long) = withContext(Dispatchers.IO) {
        val tmp = partial(name)
        if (tmp.length() > part.size) tmp.delete()
        var done = if (tmp.exists()) tmp.length() else 0L
        status = PhoneModel.Status.Downloading(before + done, total)
        if (done < part.size) api.downloadFrom(part.file, done).use { r ->
            if (r.code == 200 && done > 0) { tmp.delete(); done = 0 }
            else if (!r.isSuccessful) throw IllegalStateException("The download was refused (${r.code}).")
            val body = r.body ?: throw IllegalStateException("The PC sent nothing.")
            FileOutputStream(tmp, done > 0).use { out ->
                val buf = ByteArray(1 shl 16)
                val input = body.byteStream()
                var last = 0L
                while (isActive) {
                    val n = input.read(buf)
                    if (n < 0) break
                    out.write(buf, 0, n)
                    done += n
                    if (done - last > 4L * 1024 * 1024) { last = done; status = PhoneModel.Status.Downloading(before + done, total) }
                }
            }
        }
        if (!isActive) return@withContext
        if (tmp.length() != part.size) throw IllegalStateException("The download stopped early. Try again: it carries on where it was.")
        status = PhoneModel.Status.Checking
        if (sha256(tmp) != part.sha256) {
            tmp.delete()
            throw IllegalStateException("The download arrived damaged and was removed. Please download it again.")
        }
        file(name).delete()
        tmp.renameTo(file(name))
    }

    fun cancel() {
        job?.cancel()
        status = if (ready()) PhoneModel.Status.Ready else PhoneModel.Status.None
    }

    fun remove() {
        cancel()
        Vision.PARTS.forEach { file(it).delete(); partial(it).delete() }
        kitFile.delete()
        kit = null
        status = PhoneModel.Status.None
    }

    fun stop() {
        stopping = true
    }

    /** What the picture shows ([question] steers what matters), written on the phone; null with [error] set when it could not be done */
    var error = ""
        private set

    suspend fun look(image: ByteArray, question: String, onText: (String) -> Unit): String? = withContext(Dispatchers.Default) {
        val k = kit ?: run { error = "The picture model is not on this phone."; return@withContext null }
        if (!phone.canRun()) { error = "This phone cannot run the picture model."; return@withContext null }
        phone.unload()                                                   // one model in memory at a time
        stopping = false
        val joiner = Utf8Joiner()
        var last = 0L
        val end = Llama.describe(file("model").path, file("mmproj").path, image, Vision.prompt(k.prompt, question), k.maxReplyTokens) { bytes ->
            joiner.add(bytes)
            val now = System.currentTimeMillis()
            if (now - last > 80) { last = now; onText(joiner.text) }
            !stopping
        }
        val seen = joiner.text.replace(Regex("(?s)<think>.*?</think>"), "").trim()
        when {
            end == Llama.End.TooLong -> { error = "That picture could not be read."; null }
            end == Llama.End.Failed -> { error = "The picture model could not run: the phone may not have enough free memory. Close other apps and try again."; null }
            seen.isEmpty() -> { error = "The picture model saw nothing it could describe."; null }
            else -> seen
        }
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
}
