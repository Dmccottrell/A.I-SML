// AppUpdate.kt: checks whether a newer Emvryx app has been built. GitHub's build publishes the newest APK (the Android
// install file) plus a small version.json naming the commit it was built from; the app compares that with its own stamp.

package app.emvryx.android.local

import android.content.Context
import android.os.Build
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
    // Where the newest install file and its version note live (a fixed "android-latest" release on GitHub).
    const val APK_URL = "https://github.com/Dmccottrell/A.I-SML/releases/download/android-latest/emvryx.apk"
    const val VERSION_URL = "https://github.com/Dmccottrell/A.I-SML/releases/download/android-latest/version.json"

    /** The contents of version.json: [sha] is the commit the newest app was built from, [built] when. */
    @Serializable
    data class Latest(val sha: String = "", val built: String = "")

    /**
     * True when [latest] is a different build from this one, and not the one the person said Later to. An app built on a computer
     * (no stamp) never asks.
     * [installed] is this app's own commit stamp, [dismissed] the commit the person already waved away.
     */
    fun newer(installed: String, latest: Latest?, dismissed: String): Boolean =
        // All of these must hold: we have our own stamp, we got an answer, the answer names a commit, and that commit is neither ours nor one the person dismissed.
        installed.isNotBlank() && latest != null && latest.sha.isNotBlank() && latest.sha != installed && latest.sha != dismissed

    // The app that installed this one: "com.android.vending" is the Google Play Store. An app put on the phone by hand (the install file) has another installer or none.
    const val PLAY_STORE = "com.android.vending"

    /** True when the Play Store installed this app: its updates must come from the Play Store too, not from a downloaded install file */
    fun fromPlayStore(installer: String?): Boolean = installer == PLAY_STORE

    /** The words in the banner: a store app is told to go to the store; an app installed by hand is offered the download */
    fun title(fromStore: Boolean): String = if (fromStore) "A new version of Emvryx is in the Play Store" else "A new version of Emvryx is ready"

    /** The button's words (see [title]) */
    fun action(fromStore: Boolean): String = if (fromStore) "Open Play Store" else "Update"

    /** The Play Store app's own address for this app (opens the store app straight on it) and the web address as a fallback when no store app answers */
    fun storeUri(pkg: String): String = "market://details?id=$pkg"
    fun storeWebUrl(pkg: String): String = "https://play.google.com/store/apps/details?id=$pkg"

    /** Who installed this app (null when unknown): from Android 11 the install-source record, before that the older installer name */
    fun installer(ctx: Context): String? = runCatching {
        if (Build.VERSION.SDK_INT >= 30) ctx.packageManager.getInstallSourceInfo(ctx.packageName).installingPackageName
        else @Suppress("DEPRECATION") ctx.packageManager.getInstallerPackageName(ctx.packageName)
    }.getOrNull()

    // Lenient JSON reader: ignore fields we do not know.
    private val json = Json { ignoreUnknownKeys = true }
    // The network client, made only the first time it is used (`by lazy`), with short time limits so a bad connection does not hang.
    private val http by lazy { OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS).build() }

    /** The newest build, or null when it cannot be told (no signal, GitHub busy). Runs on a background thread. */
    suspend fun latest(): Latest? = withContext(Dispatchers.IO) {
        // Any failure (offline, bad JSON) is turned into null by runCatching + getOrNull.
        runCatching {
            // Ask for a fresh copy every time (no-cache) so an old stored answer never hides a new build.
            http.newCall(Request.Builder().url(VERSION_URL).header("Cache-Control", "no-cache").build()).execute().use { r ->
                if (r.isSuccessful) json.decodeFromString<Latest>(r.body?.string().orEmpty()) else null
            }
        }.getOrNull()
    }
}
