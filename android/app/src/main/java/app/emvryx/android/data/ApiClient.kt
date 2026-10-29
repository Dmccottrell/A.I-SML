package app.emvryx.android.data

import android.os.Build
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Talks to the Emvryx server the same way the website does: the session cookie, JSON in and out,
 * and replies streamed as server-sent events. A phone app sends no Origin header, which the server's
 * origin check lets through (app_server.py, _origin_ok); it still needs a signed-in session.
 */
class ApiClient(private val session: SessionStore) {
    val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    private val http = OkHttpClient.Builder()
        .cookieJar(session.cookieJar)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .addInterceptor { chain -> chain.proceed(chain.request().newBuilder().header("User-Agent", USER_AGENT).build()) }
        .build()

    // The server sends a keep-alive every 10 s while a model loads or thinks, so a minute of silence means the line is gone.
    private val stream = http.newBuilder().readTimeout(60, TimeUnit.SECONDS).build()

    private val base get() = session.serverUrl?.trimEnd('/') ?: throw IllegalStateException("No server address yet")

    suspend fun status(): Status = get("/api/status")

    suspend fun signInWithKey(key: String): LoginReply = post("/api/login", buildJsonObject { put("key", key) })

    suspend fun signInWithPassword(id: String, password: String): LoginReply =
        post("/api/login/password", buildJsonObject { put("id", id); put("password", password) })

    suspend fun twoStep(ticket: String, code: String): LoginReply =
        post("/api/login/mfa", buildJsonObject { put("ticket", ticket); put("code", code) })

    suspend fun signOut() {
        runCatching { post<JsonObject>("/api/logout", JsonObject(emptyMap())) }
        session.forget()
    }

    suspend fun state(model: String? = null): AppState = get("/api/state" + (model?.let { "?model=$it" } ?: ""))

    suspend fun chat(id: Long): Chat = get("/api/chats/$id")

    /** A new chat; a private one is never saved, never listed and never uses memory (its id is below zero) */
    suspend fun newChat(private: Boolean = false, skill: String = ""): Long =
        post<NewChat>("/api/chats", buildJsonObject { if (private) put("private", true); if (skill.isNotEmpty()) put("skill", skill) }).id

    // ---- the app's own Memory, Files, Skills and Settings screens (feature flag android_native): the website's calls

    suspend fun memory(): MemoryList = get("/api/memory")

    suspend fun memoryAdd(text: String): MemoryList = post("/api/memory/add", buildJsonObject { put("text", text) })

    suspend fun memoryDelete(id: Long) {
        post<JsonObject>("/api/memory/delete", buildJsonObject { put("id", id) })
    }

    suspend fun memoryClear() {
        post<JsonObject>("/api/memory/clear", JsonObject(emptyMap()))
    }

    suspend fun documents(): DocList = get("/api/documents")

    suspend fun deleteDocument(id: Long) {
        delete<JsonObject>("/api/documents/$id")
    }

    suspend fun skills(): List<Skill> = get<SkillList>("/api/skills").skills

    suspend fun settings(): SettingsData = get("/api/settings")

    /** Changes only what [body] names; the server checks each value and sends back all the settings */
    suspend fun saveSettings(body: JsonObject): SettingsData = post("/api/settings", body)

    // ---- what the website's chat menus do (web/js/chat.js, core.js): archive, folders, share a link, save as, Right, Your day

    suspend fun archive(chatId: Long, on: Boolean) {
        post<JsonObject>("/api/chats/$chatId/archive", buildJsonObject { put("archived", on) })
    }

    suspend fun archived(): List<ChatSummary> = get<ChatList>("/api/chats/archived").chats

    suspend fun folder(chatId: Long, folder: String) {
        post<JsonObject>("/api/chats/$chatId/folder", buildJsonObject { put("folder", folder) })
    }

    suspend fun shares(): Shares = get("/api/shares")

    suspend fun share(chatId: Long, days: Int): ShareMade = post("/api/chats/$chatId/share", buildJsonObject { put("days", days) })

    suspend fun revokeShare(id: String) {
        post<JsonObject>("/api/shares/revoke", buildJsonObject { put("id", id) })
    }

    /** "Right answer": keeps the notes it used, so it can answer this again offline (POST .../like) */
    suspend fun like(chatId: Long, messageId: Long): LikeReply = post("/api/chats/$chatId/messages/$messageId/like", JsonObject(emptyMap()))

    /** The text as a PDF, Word or Markdown file (POST /api/export-doc): the file's bytes */
    suspend fun exportDoc(text: String, format: String, title: String): ByteArray = withContext(Dispatchers.IO) {
        val body = buildJsonObject { put("text", text); put("format", format); put("title", title) }
        val r = try {
            http.newCall(request("/api/export-doc", body)).execute()
        } catch (e: IOException) {
            throw OfflineException(e)
        }
        r.use { if (!it.isSuccessful) throw error(it) else it.body?.bytes() ?: ByteArray(0) }
    }

    suspend fun briefing(): Briefing = get("/api/briefing")

    // ---- sign in with a code sent by email (web/js/auth.js)

    suspend fun authOptions(): AuthOptions = get("/api/auth-options")

    suspend fun emailCode(email: String) {
        post<JsonObject>("/api/login/email/start", buildJsonObject { put("email", email) })
    }

    suspend fun emailSignIn(email: String, code: String): LoginReply =
        post("/api/login/email/verify", buildJsonObject { put("email", email); put("code", code) })

    suspend fun stop(id: Long) {
        post<JsonObject>("/api/chats/$id/stop", JsonObject(emptyMap()))
    }

    // ---- chat: pictures and files, edit, report, pin, delete, branch, search, compact (the same calls as web/js/chat.js and core.js)

    /** A picture or file for the chat: uploaded once (POST /api/documents), then attached with [setChatDocs]. */
    suspend fun upload(name: String, bytes: ByteArray): DocInfo =
        post("/api/documents", buildJsonObject { put("name", name); put("data", android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)) })

    suspend fun setChatDocs(chatId: Long, ids: List<Long>): List<DocInfo> =
        post<DocsReply>("/api/chats/$chatId/docs", buildJsonObject { putJsonArray("ids") { ids.forEach { add(JsonPrimitive(it)) } } }).docs

    /** The bytes of a picture someone sent (GET /api/documents/{id}/image), for the thread */
    suspend fun picture(id: Long): ByteArray? = withContext(Dispatchers.IO) {
        runCatching { http.newCall(Request.Builder().url("$base/api/documents/$id/image").get().build()).execute().use { if (it.isSuccessful) it.body?.bytes() else null } }.getOrNull()
    }

    suspend fun editMessage(chatId: Long, messageId: Long, text: String) {
        post<JsonObject>("/api/chats/$chatId/messages/$messageId/edit", buildJsonObject { put("text", text) })
    }

    suspend fun report(chatId: Long, messageId: Long, kind: String, note: String) {
        post<JsonObject>("/api/chats/$chatId/messages/$messageId/feedback", buildJsonObject { put("kind", kind); put("note", note) })
    }

    /** A model's welcome tour was shown: it does not play again on any device */
    suspend fun modelTourSeen(modelId: String) {
        post<JsonObject>("/api/settings", buildJsonObject { put("model_tour_seen", modelId) })
    }

    /** The VryxCode tour was shown (the version seen) */
    suspend fun vryxTourSeen(version: Int) {
        post<JsonObject>("/api/settings", buildJsonObject { put("vryx_tour_seen", version) })
    }

    suspend fun pin(chatId: Long, pinned: Boolean) {
        post<JsonObject>("/api/chats/$chatId/pin", buildJsonObject { put("pinned", pinned) })
    }

    suspend fun deleteChat(chatId: Long) {
        delete<JsonObject>("/api/chats/$chatId")
    }

    suspend fun branch(chatId: Long, messageId: Long): BranchReply = post("/api/chats/$chatId/branch", buildJsonObject { put("message_id", messageId) })

    suspend fun search(q: String): List<SearchHit> = get<SearchReply>("/api/chats/search?q=" + java.net.URLEncoder.encode(q, "UTF-8")).results

    suspend fun compact(chatId: Long, model: String): CompactReply = post("/api/chats/$chatId/compact", buildJsonObject { put("model", model) })

    // ---- VryxCode (app/routes_code.py): the same calls as web/js/code.js and ide.js

    suspend fun codeInfo(): CodeInfo = get("/api/code")

    suspend fun codeSessions(): List<CodeSessionRow> = get<CodeSessions>("/api/code/sessions").sessions

    suspend fun codeView(id: String, after: Int): CodeView = get("/api/code/sessions/$id?after=$after")

    suspend fun codeStart(body: JsonObject): CodeStarted = post("/api/code/start", body)

    suspend fun codeMessage(id: String, body: JsonObject): CodeStarted = post("/api/code/sessions/$id/message", body)

    suspend fun codeSteer(id: String, text: String) {
        post<JsonObject>("/api/code/sessions/$id/steer", buildJsonObject { put("text", text) })
    }

    suspend fun codeAnswer(id: String, question: Int, allow: Boolean, always: Boolean = false, choice: String? = null) {
        post<JsonObject>("/api/code/sessions/$id/answer", buildJsonObject {
            put("id", question); put("allow", allow); put("always", always); if (choice != null) put("choice", choice)
        })
    }

    suspend fun codeStop(id: String) {
        post<JsonObject>("/api/code/sessions/$id/stop", JsonObject(emptyMap()))
    }

    /** vryxcode_restore: the project's files as they were before message `turn` of this session */
    suspend fun codeRewind(id: String, turn: Int) {
        post<JsonObject>("/api/code/sessions/$id/rewind", buildJsonObject { put("turn", turn) })
    }

    suspend fun codeFixCi(body: JsonObject): CodeStarted = post("/api/code/fixci", body)

    suspend fun codeMemory(): CodeMemory = get("/api/code/memory")

    suspend fun codeForget(index: Int?): CodeMemory = post("/api/code/memory", buildJsonObject { put("forget", index?.let { JsonPrimitive(it) } ?: kotlinx.serialization.json.JsonNull) })

    suspend fun codeRules(project: String): CodeRules = get("/api/code/rules?project=" + java.net.URLEncoder.encode(project, "UTF-8"))

    suspend fun codeRule(project: String, add: Pair<String, String>? = null, remove: String? = null): CodeRules = post("/api/code/rules", buildJsonObject {
        put("project", project)
        if (add != null) put("add", buildJsonObject { put("kind", add.first); put("rule", add.second) }) else put("remove", remove ?: "")
    })

    suspend fun codeCommands(project: String): List<CodeCommand> =
        get<CodeCommands>("/api/code/commands?project=" + java.net.URLEncoder.encode(project, "UTF-8")).commands

    /** Sends one message and streams the reply. Refusals (limits, a model that is not available) throw [ApiException] before anything streams.
     *  [regenMode] is how a regenerated answer should differ (Regenerate options); [cont] carries on an answer that stopped at its length limit. */
    fun send(chatId: Long, text: String, model: String, effort: String, regenerate: Boolean = false, regenMode: String? = null,
             cont: Boolean = false, research: Boolean = false): Flow<ReplyEvent> = flow {
        val body = buildJsonObject {
            put("text", text); put("model", model); put("effort", effort)
            if (regenerate) put("regenerate", true)          // write the last reply again (api_send in app/routes_chat.py)
            if (regenMode != null) put("regen_mode", regenMode)
            if (cont) put("continue", true)
            if (research) put("research", true)              // chat_research: search the web several ways and write a report
        }
        val call = stream.newCall(request("/api/chats/$chatId/send", body))
        val response = try {
            call.execute()
        } catch (e: IOException) {
            throw OfflineException(e)
        }
        response.use { r ->
            if (!r.isSuccessful) throw error(r)
            val source = r.body?.source() ?: return@use
            val parser = SseParser(json)
            try {
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val line = source.readUtf8Line() ?: break
                    parser.feed(line)?.let { emit(it) }
                }
                parser.feed("")?.let { emit(it) }
            } catch (e: IOException) {
                if (!call.isCanceled()) throw OfflineException(e)
            } finally {
                call.cancel()
            }
        }
    }.flowOn(Dispatchers.IO)

    private suspend inline fun <reified T> get(path: String): T = withContext(Dispatchers.IO) {
        call(Request.Builder().url(base + path).get().build())
    }

    private suspend inline fun <reified T> post(path: String, body: JsonObject): T = withContext(Dispatchers.IO) {
        call(request(path, body))
    }

    private suspend inline fun <reified T> delete(path: String): T = withContext(Dispatchers.IO) {
        call(Request.Builder().url(base + path).delete().build())
    }

    // ---- android_offline_model: the model the phone runs itself (app/phone_model.py)

    suspend fun phoneKit(model: String? = null): app.emvryx.android.local.PhoneKit =
        get("/api/phone-model" + (model?.let { "?model=" + java.net.URLEncoder.encode(it, "UTF-8") } ?: ""))

    // ---- the app's own Admin screen (android_native): the website's Admin calls

    suspend fun adminOverview(): app.emvryx.android.local.AdminOverview = get("/api/admin/overview")

    suspend fun adminFlags(): app.emvryx.android.local.AdminFlags = get("/api/admin/flags")

    suspend fun adminSetFlag(id: String, audience: String): app.emvryx.android.local.AdminFlags =
        post("/api/admin/flags", buildJsonObject { put("id", id); put("audience", audience) })

    /** Admin > Previews: the new features in preview ([kind] "features", +0.5) or the bug fixes ("fixes", +0.1) go to everyone as one release */
    suspend fun adminPublish(kind: String): app.emvryx.android.local.AdminFlags = post("/api/admin/flags", buildJsonObject { put("publish", "all"); put("kind", kind) })

    suspend fun adminPc(): app.emvryx.android.local.AdminPc = get("/api/admin/pc")

    suspend fun adminSetPc(body: JsonObject): app.emvryx.android.local.AdminPc = post("/api/admin/pc", body)

    suspend fun adminUsers(): app.emvryx.android.local.AdminUsers = get("/api/admin/users")

    /** Admin > Crashes (the owner, with the admin_crashes switch on); null when it is not there for this person */
    suspend fun adminCrashes(): app.emvryx.android.local.AdminCrashes? =
        try { get("/api/admin/crashes") } catch (e: ApiException) { if (e.http == 404 || e.http == 403) null else throw e }

    /** A VryxCode draft written on the phone while the PC was off: its id on the PC */
    suspend fun codeDraft(body: JsonObject): String = post<DraftSaved>("/api/code/drafts", body).id

    /** Runs a draft in VryxCode on the PC (it writes the files, runs and tests them) */
    suspend fun codeDraftRun(id: String): CodeStarted = post("/api/code/drafts/$id/run", JsonObject(emptyMap()))

    /** Messages written on the phone while the PC was off, added to the PC's chat (or a new one): the chat's id */
    suspend fun phoneVision(): app.emvryx.android.local.VisionKit = get("/api/phone-model/vision")

    suspend fun schedules(): app.emvryx.android.local.Schedules = get("/api/schedules")

    suspend fun scheduleAdd(body: JsonObject): app.emvryx.android.local.Schedules = post("/api/schedules", body)

    /** [what]: delete, on (with [on]) or run */
    suspend fun scheduleDo(id: String, what: String, on: Boolean = false): app.emvryx.android.local.Schedules =
        post("/api/schedules/$id/$what", buildJsonObject { if (what == "on") put("on", on) })

    suspend fun phoneSync(body: JsonObject): Long = post<PhoneSynced>("/api/phone-sync", body).chat

    /** The model file from byte [from] on (a download that stopped carries on). Blocking: call it off the main thread, and close the reply. */
    fun downloadFrom(path: String, from: Long): Response {
        val req = Request.Builder().url(base + path).get().apply { if (from > 0) header("Range", "bytes=$from-") }.build()
        return try {
            stream.newBuilder().readTimeout(120, TimeUnit.SECONDS).build().newCall(req).execute()
        } catch (e: IOException) {
            throw OfflineException(e)
        }
    }

    /** The server address the in-app pages open (Settings, Admin, the full website) */
    val server: String? get() = session.serverUrl?.trimEnd('/')

    private fun request(path: String, body: JsonObject) =
        Request.Builder().url(base + path).post(body.toString().toRequestBody(JSON)).build()

    private inline fun <reified T> call(request: Request): T {
        val r = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            throw OfflineException(e)
        }
        r.use {
            if (!it.isSuccessful) throw error(it)
            return json.decodeFromString(it.body?.string().orEmpty().ifEmpty { "{}" })
        }
    }

    private fun error(r: Response): Exception {
        // The tunnel answers for a PC that is off with its own page (502/503/504 and no JSON): that is "off", not an error.
        val text = runCatching { r.body?.string() }.getOrNull().orEmpty()
        val body = runCatching { json.decodeFromString<ErrorBody>(text) }.getOrNull()
        if (body == null || body.code.isEmpty()) {
            if (r.code in 502..504 || r.code == 530) return OfflineException(IOException("HTTP ${r.code}"))
            return ApiException(r.code, "http_${r.code}", "Something went wrong (${r.code}).")
        }
        return ApiException(r.code, body.code, body.message, body.action)
    }

    private companion object {
        val JSON = "application/json".toMediaType()
        // "Emvryx-Android" lets the server's Devices list say "The Emvryx app on Android" (auth.device_label).
        val USER_AGENT = "Emvryx-Android/0.1 (Android ${Build.VERSION.RELEASE}; ${Build.MODEL})"
    }
}
