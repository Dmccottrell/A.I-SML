// ApiClient.kt: every call the Android app makes to the Emvryx server lives here, one small function per call.
// The screens never build web requests themselves; they call these functions and get back the classes from Api.kt / Code.kt.
// Vocabulary used below:
//   - a "suspend" function is a coroutine: it can pause while it waits for the network without freezing the screen.
//   - JSON is the text format the server speaks, e.g. {"key": "value"}.
//   - HTTP verbs: GET reads something, POST sends something, DELETE removes something.
//   - SSE (server-sent events) is one long answer the server writes a little at a time, used for streaming a reply.

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
 * [session] holds the server address and the sign-in cookie (see SessionStore.kt).
 */
class ApiClient(private val session: SessionStore) {
    // The JSON reader/writer. ignoreUnknownKeys: a newer server may add fields; skip them instead of crashing.
    // explicitNulls = false: leave out null fields when writing. coerceInputValues: a null or odd value falls back to the field's default.
    val json = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

    // OkHttp is the library that does the real network work. This one client is shared by every call.
    // The cookie jar stores the sign-in cookie; the timeouts give up after 10 s to connect and 30 s of silence.
    private val http = OkHttpClient.Builder()
        .cookieJar(session.cookieJar)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        // An interceptor runs on every request: here it stamps our User-Agent so the server knows the call came from the app.
        .addInterceptor { chain -> chain.proceed(chain.request().newBuilder().header("User-Agent", USER_AGENT).build()) }
        .build()

    // The server sends a keep-alive every 10 s while a model loads or thinks, so a minute of silence means the line is gone.
    // (A second client for streaming replies, with a longer silence limit.)
    private val stream = http.newBuilder().readTimeout(60, TimeUnit.SECONDS).build()

    // The server address without a trailing slash. Throws if the person has not typed one yet (a programming error, not a network one).
    private val base get() = session.serverUrl?.trimEnd('/') ?: throw IllegalStateException("No server address yet")

    // Is the server up? Used before sign-in.
    suspend fun status(): Status = get("/api/status")

    // Three ways to sign in: with an access key, with an id and password, then (if asked) the second-step code.
    suspend fun signInWithKey(key: String): LoginReply = post("/api/login", buildJsonObject { put("key", key) })

    suspend fun signInWithPassword(id: String, password: String): LoginReply =
        post("/api/login/password", buildJsonObject { put("id", id); put("password", password) })

    suspend fun twoStep(ticket: String, code: String): LoginReply =
        post("/api/login/mfa", buildJsonObject { put("ticket", ticket); put("code", code) })

    /** Tells the server to end the session, then forgets the cookie on the phone. runCatching ignores a failure: we sign out locally anyway. */
    suspend fun signOut() {
        runCatching { post<JsonObject>("/api/logout", JsonObject(emptyMap())) }
        session.forget()
    }

    /** Everything needed after sign-in (models, chats, usage, flags). [model] asks for the numbers as they apply to that model. */
    suspend fun state(model: String? = null): AppState = get("/api/state" + (model?.let { "?model=$it" } ?: ""))

    /** One whole chat with its messages. */
    suspend fun chat(id: Long): Chat = get("/api/chats/$id")

    /**
     * A new chat; a private one is never saved, never listed and never uses memory (its id is below zero).
     * Returns the new chat's id. Only the options that are set are put in the JSON body.
     */
    suspend fun newChat(private: Boolean = false, skill: String = ""): Long =
        post<NewChat>("/api/chats", buildJsonObject { if (private) put("private", true); if (skill.isNotEmpty()) put("skill", skill) }).id

    // ---- the app's own Memory, Files, Skills and Settings screens (feature flag android_native): the website's calls

    // Memory: the facts the model remembers about the person. List, add, delete one, clear all.
    suspend fun memory(): MemoryList = get("/api/memory")

    suspend fun memoryAdd(text: String): MemoryList = post("/api/memory/add", buildJsonObject { put("text", text) })

    suspend fun memoryDelete(id: Long) {
        post<JsonObject>("/api/memory/delete", buildJsonObject { put("id", id) })
    }

    suspend fun memoryClear() {
        post<JsonObject>("/api/memory/clear", JsonObject(emptyMap()))
    }

    // Files the person uploaded (list and delete).
    suspend fun documents(): DocList = get("/api/documents")

    suspend fun deleteDocument(id: Long) {
        delete<JsonObject>("/api/documents/$id")
    }

    // Skills are saved instruction sets the person can start a chat from; the server wraps the list in an object, so we unwrap `.skills`.
    suspend fun skills(): List<Skill> = get<SkillList>("/api/skills").skills

    /** All of the person's settings. */
    suspend fun settings(): SettingsData = get("/api/settings")

    /** Changes only what [body] names; the server checks each value and sends back all the settings */
    suspend fun saveSettings(body: JsonObject): SettingsData = post("/api/settings", body)

    // ---- what the website's chat menus do (web/js/chat.js, core.js): archive, folders, share a link, save as, Right, Your day

    // Archive hides a chat from the main list without deleting it; [archived] lists them.
    suspend fun archive(chatId: Long, on: Boolean) {
        post<JsonObject>("/api/chats/$chatId/archive", buildJsonObject { put("archived", on) })
    }

    suspend fun archived(): List<ChatSummary> = get<ChatList>("/api/chats/archived").chats

    // Put a chat in a named folder (an empty name takes it out).
    suspend fun folder(chatId: Long, folder: String) {
        post<JsonObject>("/api/chats/$chatId/folder", buildJsonObject { put("folder", folder) })
    }

    // Share links: list what exists, make one that lasts [days] days, and turn one off.
    suspend fun shares(): Shares = get("/api/shares")

    suspend fun share(chatId: Long, days: Int): ShareMade = post("/api/chats/$chatId/share", buildJsonObject { put("days", days) })

    suspend fun revokeShare(id: String) {
        post<JsonObject>("/api/shares/revoke", buildJsonObject { put("id", id) })
    }

    /** "Right answer": keeps the notes it used, so it can answer this again offline (POST .../like). Returns how many notes were saved. */
    suspend fun like(chatId: Long, messageId: Long): LikeReply = post("/api/chats/$chatId/messages/$messageId/like", JsonObject(emptyMap()))

    /**
     * The text as a PDF, Word or Markdown file (POST /api/export-doc): the file's bytes.
     * Runs on the IO thread pool (Dispatchers.IO) because it waits on the network.
     */
    suspend fun exportDoc(text: String, format: String, title: String): ByteArray = withContext(Dispatchers.IO) {
        // Build the JSON body {"text":..., "format":..., "title":...}.
        val body = buildJsonObject { put("text", text); put("format", format); put("title", title) }
        // Send it. A network failure (no signal, PC off) is turned into OfflineException so screens can say "off right now".
        val r = try {
            http.newCall(request("/api/export-doc", body)).execute()
        } catch (e: IOException) {
            throw OfflineException(e)
        }
        // `use` closes the reply when done. A bad status becomes an error; otherwise return the file's bytes (empty if there is no body).
        r.use { if (!it.isSuccessful) throw error(it) else it.body?.bytes() ?: ByteArray(0) }
    }

    /** "Your day" from connected apps. */
    suspend fun briefing(): Briefing = get("/api/briefing")

    // ---- sign in with a code sent by email (web/js/auth.js): ask which ways exist, send the code, then check it.

    suspend fun authOptions(): AuthOptions = get("/api/auth-options")

    suspend fun emailCode(email: String) {
        post<JsonObject>("/api/login/email/start", buildJsonObject { put("email", email) })
    }

    suspend fun emailSignIn(email: String, code: String): LoginReply =
        post("/api/login/email/verify", buildJsonObject { put("email", email); put("code", code) })

    /** Stops a reply that is still being written. */
    suspend fun stop(id: Long) {
        post<JsonObject>("/api/chats/$id/stop", JsonObject(emptyMap()))
    }

    // ---- chat: pictures and files, edit, report, pin, delete, branch, search, compact (the same calls as web/js/chat.js and core.js)

    /**
     * A picture or file for the chat: uploaded once (POST /api/documents), then attached with [setChatDocs].
     * The bytes are sent as Base64 text (a way to write any bytes using only letters and digits) because the body is JSON; NO_WRAP means no line breaks in it.
     */
    suspend fun upload(name: String, bytes: ByteArray): DocInfo =
        post("/api/documents", buildJsonObject { put("name", name); put("data", android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)) })

    /** Attaches exactly these uploaded files to the chat (replacing what was attached) and returns the resulting list. */
    suspend fun setChatDocs(chatId: Long, ids: List<Long>): List<DocInfo> =
        post<DocsReply>("/api/chats/$chatId/docs", buildJsonObject { putJsonArray("ids") { ids.forEach { add(JsonPrimitive(it)) } } }).docs

    /** The bytes of a picture someone sent (GET /api/documents/{id}/image), for the thread. Returns null on any failure so a broken picture just does not show. */
    suspend fun picture(id: Long): ByteArray? = withContext(Dispatchers.IO) {
        runCatching { http.newCall(Request.Builder().url("$base/api/documents/$id/image").get().build()).execute().use { if (it.isSuccessful) it.body?.bytes() else null } }.getOrNull()
    }

    /** Replaces the text of one of the person's own messages. */
    suspend fun editMessage(chatId: Long, messageId: Long, text: String) {
        post<JsonObject>("/api/chats/$chatId/messages/$messageId/edit", buildJsonObject { put("text", text) })
    }

    /** Sends feedback on a reply: a [kind] (what was wrong) and an optional [note]. */
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

    // Pin keeps a chat at the top of the list; deleteChat removes it for good.
    suspend fun pin(chatId: Long, pinned: Boolean) {
        post<JsonObject>("/api/chats/$chatId/pin", buildJsonObject { put("pinned", pinned) })
    }

    suspend fun deleteChat(chatId: Long) {
        delete<JsonObject>("/api/chats/$chatId")
    }

    /** "Branch": copies the chat up to [messageId] into a new chat. */
    suspend fun branch(chatId: Long, messageId: Long): BranchReply = post("/api/chats/$chatId/branch", buildJsonObject { put("message_id", messageId) })

    /** Searches the person's chats. The text is URL-encoded (spaces and symbols turned into safe %xx codes) so it can sit in the address. */
    suspend fun search(q: String): List<SearchHit> = get<SearchReply>("/api/chats/search?q=" + java.net.URLEncoder.encode(q, "UTF-8")).results

    /** Folds old messages into a summary to free up the model's memory. */
    suspend fun compact(chatId: Long, model: String): CompactReply = post("/api/chats/$chatId/compact", buildJsonObject { put("model", model) })

    // ---- VryxCode (app/routes_code.py): the coding agent. The same calls as web/js/code.js and ide.js

    // General info, the session list, one session's view (only events after number [after], so each poll sends just what is new), then start / reply to a session.
    suspend fun codeInfo(): CodeInfo = get("/api/code")

    // [archived] = true asks for the Archived list instead of the normal one (flag vryxcode_archive)
    suspend fun codeSessions(archived: Boolean = false): List<CodeSessionRow> = get<CodeSessions>("/api/code/sessions" + if (archived) "?archived=1" else "").sessions

    // vryxcode_archive: tuck a session away (on = true) or bring it back; and delete one for good. Both only for a session that is not running.
    suspend fun codeArchive(id: String, on: Boolean) {
        post<JsonObject>("/api/code/sessions/$id/archive", buildJsonObject { put("archived", on) })
    }

    suspend fun codeDeleteSession(id: String) {
        post<JsonObject>("/api/code/sessions/$id/delete", JsonObject(emptyMap()))
    }

    // The project starters (coding/templates.py) the home offers: a small working project the model then fills in
    suspend fun codeTemplates(): List<CodeTemplate> = get<CodeTemplates>("/api/code/templates").templates

    suspend fun codeView(id: String, after: Int): CodeView = get("/api/code/sessions/$id?after=$after")

    suspend fun codeStart(body: JsonObject): CodeStarted = post("/api/code/start", body)

    suspend fun codeMessage(id: String, body: JsonObject): CodeStarted = post("/api/code/sessions/$id/message", body)

    /** Sends a mid-run nudge to the agent while it is working. */
    suspend fun codeSteer(id: String, text: String) {
        post<JsonObject>("/api/code/sessions/$id/steer", buildJsonObject { put("text", text) })
    }

    /** Answers a question or permission request from the agent: allow or not, optionally "always", or a chosen option. */
    suspend fun codeAnswer(id: String, question: Int, allow: Boolean, always: Boolean = false, choice: String? = null) {
        post<JsonObject>("/api/code/sessions/$id/answer", buildJsonObject {
            put("id", question); put("allow", allow); put("always", always); if (choice != null) put("choice", choice)
        })
    }

    /** Stops the agent's current run. */
    suspend fun codeStop(id: String) {
        post<JsonObject>("/api/code/sessions/$id/stop", JsonObject(emptyMap()))
    }

    /** vryxcode_restore: the project's files as they were before message `turn` of this session (an undo for the agent's work) */
    suspend fun codeRewind(id: String, turn: Int) {
        post<JsonObject>("/api/code/sessions/$id/rewind", buildJsonObject { put("turn", turn) })
    }

    /** Asks the agent to fix a failing automated check (CI = continuous integration, tests that run on every change). */
    suspend fun codeFixCi(body: JsonObject): CodeStarted = post("/api/code/fixci", body)

    // The agent's own memory notes; codeForget removes one by position (null clears all, sent as JSON null).
    suspend fun codeMemory(): CodeMemory = get("/api/code/memory")

    suspend fun codeForget(index: Int?): CodeMemory = post("/api/code/memory", buildJsonObject { put("forget", index?.let { JsonPrimitive(it) } ?: kotlinx.serialization.json.JsonNull) })

    // Per-project rules the agent must follow: read, and add one ([add] = kind and text) or remove one.
    suspend fun codeRules(project: String): CodeRules = get("/api/code/rules?project=" + java.net.URLEncoder.encode(project, "UTF-8"))

    suspend fun codeRule(project: String, add: Pair<String, String>? = null, remove: String? = null): CodeRules = post("/api/code/rules", buildJsonObject {
        put("project", project)
        if (add != null) put("add", buildJsonObject { put("kind", add.first); put("rule", add.second) }) else put("remove", remove ?: "")
    })

    /** Saved shell commands for a project (the project name is URL-encoded to sit safely in the address). */
    suspend fun codeCommands(project: String): List<CodeCommand> =
        get<CodeCommands>("/api/code/commands?project=" + java.net.URLEncoder.encode(project, "UTF-8")).commands

    /**
     * Sends one message and streams the reply. Refusals (limits, a model that is not available) throw [ApiException] before anything streams.
     * [regenMode] is how a regenerated answer should differ (Regenerate options); [cont] carries on an answer that stopped at its length limit.
     * Returns a Flow: a stream of [ReplyEvent]s that arrive one at a time while the model writes.
     */
    fun send(chatId: Long, text: String, model: String, effort: String, regenerate: Boolean = false, regenMode: String? = null,
             cont: Boolean = false, research: Boolean = false): Flow<ReplyEvent> = flow {
        // Build the JSON body; optional switches are added only when they are on.
        val body = buildJsonObject {
            put("text", text); put("model", model); put("effort", effort)
            if (regenerate) put("regenerate", true)          // write the last reply again (api_send in app/routes_chat.py)
            if (regenMode != null) put("regen_mode", regenMode)
            if (cont) put("continue", true)
            if (research) put("research", true)              // chat_research: search the web several ways and write a report
        }
        // Open the connection (this call blocks until the server starts answering, which is fine on the IO thread).
        val call = stream.newCall(request("/api/chats/$chatId/send", body))
        // No connection at all means the PC is off or there is no signal.
        val response = try {
            call.execute()
        } catch (e: IOException) {
            throw OfflineException(e)
        }
        // `use` makes sure the connection is closed however we leave this block.
        response.use { r ->
            // A refusal (limit reached, model unavailable...) is thrown now, before any text streams.
            if (!r.isSuccessful) throw error(r)
            // `source` is the stream of bytes coming in; the SseParser turns text lines into events.
            val source = r.body?.source() ?: return@use
            val parser = SseParser(json)
            try {
                // Read one line at a time until the server closes the stream (readUtf8Line gives null at the end).
                while (true) {
                    // If the screen cancelled this flow (e.g. Stop was tapped), throw now instead of reading on.
                    currentCoroutineContext().ensureActive()
                    val line = source.readUtf8Line() ?: break
                    parser.feed(line)?.let { emit(it) }
                }
                // An empty line marks the end of an event; feed one in case the stream ended without it so the last event is not lost.
                parser.feed("")?.let { emit(it) }
            } catch (e: IOException) {
                // The line dropped. If we cancelled it ourselves that is normal; otherwise tell the screen it is offline.
                if (!call.isCanceled()) throw OfflineException(e)
            } finally {
                // Always hang up when done, so no connection is left open.
                call.cancel()
            }
        }
    // flowOn: run all of the above on the background IO threads, not the screen thread.
    }.flowOn(Dispatchers.IO)

    // The three private helpers below send a request and turn the JSON answer into a [T]. `reified` lets Kotlin remember what T is, so the library knows which class to build.
    // They run on Dispatchers.IO (background threads for network/disk work).
    private suspend inline fun <reified T> get(path: String): T = withContext(Dispatchers.IO) {
        call(Request.Builder().url(base + path).get().build())
    }

    private suspend inline fun <reified T> post(path: String, body: JsonObject): T = withContext(Dispatchers.IO) {
        call(request(path, body))
    }

    private suspend inline fun <reified T> delete(path: String): T = withContext(Dispatchers.IO) {
        call(Request.Builder().url(base + path).delete().build())
    }

    // ---- android_offline_model: the model the phone runs itself (app/phone_model.py): the "kit" says which file to download and where

    suspend fun phoneKit(model: String? = null): app.emvryx.android.local.PhoneKit =
        get("/api/phone-model" + (model?.let { "?model=" + java.net.URLEncoder.encode(it, "UTF-8") } ?: ""))

    // ---- the app's own Admin screen (android_native): the website's Admin calls: overview, feature flags, the PC's settings, users

    suspend fun adminOverview(): app.emvryx.android.local.AdminOverview = get("/api/admin/overview")

    suspend fun adminFlags(): app.emvryx.android.local.AdminFlags = get("/api/admin/flags")

    suspend fun adminSetFlag(id: String, audience: String): app.emvryx.android.local.AdminFlags =
        post("/api/admin/flags", buildJsonObject { put("id", id); put("audience", audience) })

    /** Admin > Previews: the new features in preview ([kind] "features", +0.5) or the bug fixes ("fixes", +0.1) go to everyone as one release (the numbers are the version bump) */
    suspend fun adminPublish(kind: String): app.emvryx.android.local.AdminFlags = post("/api/admin/flags", buildJsonObject { put("publish", "all"); put("kind", kind) })

    suspend fun adminPc(): app.emvryx.android.local.AdminPc = get("/api/admin/pc")

    suspend fun adminSetPc(body: JsonObject): app.emvryx.android.local.AdminPc = post("/api/admin/pc", body)

    suspend fun adminUsers(): app.emvryx.android.local.AdminUsers = get("/api/admin/users")

    /** Admin > Crashes (the owner, with the admin_crashes switch on); null when it is not there for this person (the server answers 404 or 403) */
    suspend fun adminCrashes(): app.emvryx.android.local.AdminCrashes? =
        try { get("/api/admin/crashes") } catch (e: ApiException) { if (e.http == 404 || e.http == 403) null else throw e }

    /** A VryxCode draft written on the phone while the PC was off: sent to the PC, which answers with its id there */
    suspend fun codeDraft(body: JsonObject): String = post<DraftSaved>("/api/code/drafts", body).id

    /** Runs a draft in VryxCode on the PC (it writes the files, runs and tests them) */
    suspend fun codeDraftRun(id: String): CodeStarted = post("/api/code/drafts/$id/run", JsonObject(emptyMap()))

    /** The picture-reading (vision) model kit for the phone. */
    suspend fun phoneVision(): app.emvryx.android.local.VisionKit = get("/api/phone-model/vision")

    // Scheduled tasks: list, add, and one call for the actions on an existing one.
    suspend fun schedules(): app.emvryx.android.local.Schedules = get("/api/schedules")

    suspend fun scheduleAdd(body: JsonObject): app.emvryx.android.local.Schedules = post("/api/schedules", body)

    /** [what]: delete, on (with [on]) or run; it becomes the last part of the address */
    suspend fun scheduleDo(id: String, what: String, on: Boolean = false): app.emvryx.android.local.Schedules =
        post("/api/schedules/$id/$what", buildJsonObject { if (what == "on") put("on", on) })

    /** Messages written on the phone while the PC was off, added to the PC's chat (or a new one): the chat's id */
    suspend fun phoneSync(body: JsonObject): Long = post<PhoneSynced>("/api/phone-sync", body).chat

    /**
     * The model file from byte [from] on (a download that stopped carries on). Blocking: call it off the main thread, and close the reply.
     * The HTTP "Range" header asks the server to start the file at that byte instead of the beginning.
     */
    fun downloadFrom(path: String, from: Long): Response {
        // Only add the Range header when resuming (from > 0). Model files are big, so wait up to 120 s of silence.
        val req = Request.Builder().url(base + path).get().apply { if (from > 0) header("Range", "bytes=$from-") }.build()
        return try {
            stream.newBuilder().readTimeout(120, TimeUnit.SECONDS).build().newCall(req).execute()
        } catch (e: IOException) {
            throw OfflineException(e)
        }
    }

    /** The server address the in-app pages open (Settings, Admin, the full website) */
    val server: String? get() = session.serverUrl?.trimEnd('/')

    // Builds a POST request carrying the JSON body.
    private fun request(path: String, body: JsonObject) =
        Request.Builder().url(base + path).post(body.toString().toRequestBody(JSON)).build()

    // Sends any request, checks it worked, and decodes the JSON answer into a [T]. All GET/POST/DELETE helpers end up here.
    private inline fun <reified T> call(request: Request): T {
        val r = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            throw OfflineException(e)
        }
        r.use {
            if (!it.isSuccessful) throw error(it)
            // An empty reply body is read as {} so calls that answer with nothing still work.
            return json.decodeFromString(it.body?.string().orEmpty().ifEmpty { "{}" })
        }
    }

    /** Turns a failed reply into the right exception: [OfflineException] when the tunnel answered for a PC that is off, otherwise an [ApiException] with the server's message. */
    private fun error(r: Response): Exception {
        // The tunnel answers for a PC that is off with its own page (502/503/504 and no JSON): that is "off", not an error.
        val text = runCatching { r.body?.string() }.getOrNull().orEmpty()
        // Try to read the server's {code, message, action}; null if the reply was not that shape.
        val body = runCatching { json.decodeFromString<ErrorBody>(text) }.getOrNull()
        if (body == null || body.code.isEmpty()) {
            // 502/503/504 are "gateway" errors and 530 is the tunnel's own "origin is down" code.
            if (r.code in 502..504 || r.code == 530) return OfflineException(IOException("HTTP ${r.code}"))
            return ApiException(r.code, "http_${r.code}", "Something went wrong (${r.code}).")
        }
        return ApiException(r.code, body.code, body.message, body.action)
    }

    // A companion object holds constants shared by the whole class (like "static" in other languages).
    private companion object {
        // The content type to label request bodies with.
        val JSON = "application/json".toMediaType()
        // "Emvryx-Android" lets the server's Devices list say "The Emvryx app on Android" (auth.device_label).
        val USER_AGENT = "Emvryx-Android/0.1 (Android ${Build.VERSION.RELEASE}; ${Build.MODEL})"
    }
}
