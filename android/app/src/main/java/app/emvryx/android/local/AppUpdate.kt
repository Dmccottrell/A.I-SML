package app.emvryx.android.local

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * app_updates: "A new version of Emvryx is ready", as Claude's app says. Every app GitHub builds is stamped with the commit it was built from
 * (BuildConfig.BUILT_FROM); next to the newest APK is version.json with the commit of that build. A different one means a newer app is ready.
 */
object AppUpdate {
    const val APK_URL = "https://github.com/Dmccottrell/A.I-SML/releases/download/android-latest/emvryx.apk"
    const val VERSION_URL = "https://github.com/Dmccottrell/A.I-SML/releases/download/android-latest/version.json"

    @Serializable
    data class Latest(val sha: String = "", val built: String = "")

    /** True when [latest] is a different build from this one, and not the one the person said Later to. An app built on a computer
     *  (no stamp) never asks. */
    fun newer(installed: String, latest: Latest?, dismissed: String): Boolean =
        installed.isNotBlank() && latest != null && latest.sha.isNotBlank() && latest.sha != installed && latest.sha != dismissed

    private val json = Json { ignoreUnknownKeys = true }
    private val http by lazy { OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS).build() }

    /** The newest build, or null when it cannot be told (no signal, GitHub busy) */
    suspend fun latest(): Latest? = withContext(Dispatchers.IO) {
        runCatching {
            http.newCall(Request.Builder().url(VERSION_URL).header("Cache-Control", "no-cache").build()).execute().use { r ->
                if (r.isSuccessful) json.decodeFromString<Latest>(r.body?.string().orEmpty()) else null
            }
        }.getOrNull()
    }
}
