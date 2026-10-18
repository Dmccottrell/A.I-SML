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
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
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

    suspend fun newChat(): Long = post<NewChat>("/api/chats", JsonObject(emptyMap())).id

    suspend fun stop(id: Long) {
        post<JsonObject>("/api/chats/$id/stop", JsonObject(emptyMap()))
    }

    /** Sends one message and streams the reply. Refusals (limits, a model that is not available) throw [ApiException] before anything streams. */
    fun send(chatId: Long, text: String, model: String, effort: String): Flow<ReplyEvent> = flow {
        val body = buildJsonObject { put("text", text); put("model", model); put("effort", effort) }
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
