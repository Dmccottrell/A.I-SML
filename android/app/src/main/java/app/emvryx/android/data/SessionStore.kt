// SessionStore.kt: the phone's small private notebook for the app. It remembers the server address, the sign-in cookie
// and a few choices (light/dark, lock). It is stored encrypted, so other apps cannot read it.
// ApiClient.kt uses it to attach the cookie to every call; the sign-in screen and Settings read and write it.

package app.emvryx.android.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * The server address and the sign-in session, kept encrypted on the phone (Android Keystore).
 * The server's session cookie is the same one the website uses (emvryx_session, app_server.py), so signing out
 * on the website's "Devices" list signs this phone out too.
 * SharedPreferences is Android's built-in key/value storage; the Encrypted version scrambles both keys and values.
 * Every `var` below reads and writes one saved value, so setting `store.light = true` saves it straight away.
 */
class SessionStore(context: Context) {
    // The encrypted storage itself (made by open() in the companion object at the bottom).
    private val prefs: SharedPreferences = open(context)

    // The server address the person typed, e.g. https://chat.emvryx.app. `.apply()` saves in the background.
    var serverUrl: String?
        get() = prefs.getString(KEY_SERVER, null)
        set(value) = prefs.edit().putString(KEY_SERVER, value).apply()

    // Signed in = we hold a session cookie that exists and has not expired.
    val signedIn get() = session() != null

    /** Light or dark, as picked with the moon button (the website keeps it per browser too) */
    var light: Boolean
        get() = prefs.getBoolean(KEY_LIGHT, false)
        set(value) = prefs.edit().putBoolean(KEY_LIGHT, value).apply()

    /** The looks the server had on last time (violet, modern), so the sign-in screen already wears them, as the website remembers them */
    var looks: Pair<Boolean, Boolean>
        get() = prefs.getBoolean(KEY_VIOLET, false) to prefs.getBoolean(KEY_MODERN, false)
        set(value) = prefs.edit().putBoolean(KEY_VIOLET, value.first).putBoolean(KEY_MODERN, value.second).apply()

    /** Fingerprint (or face, PIN) lock when the app opens */
    var lock: Boolean
        get() = prefs.getBoolean(KEY_LOCK, false)
        set(value) = prefs.edit().putBoolean(KEY_LOCK, value).apply()

    /** Signs out on the phone: deletes only the cookie (the server address and choices stay). */
    fun forget() = prefs.edit().remove(KEY_COOKIE).apply()

    /** The session cookie as a Set-Cookie line, for the in-app website pages (WebView), so they open signed in */
    fun cookieLine(): String? = session()?.toString()

    // Rebuilds the saved cookie, or null when there is none: no server address, nothing saved, unreadable, or already expired.
    // Cookie.parse needs the server address because a cookie belongs to one site.
    private fun session(): Cookie? {
        // No server address means there can be no cookie.
        val base = serverUrl?.toHttpUrlOrNull() ?: return null
        val raw = prefs.getString(KEY_COOKIE, null) ?: return null
        val c = Cookie.parse(base, raw) ?: return null
        // expiresAt is a time in milliseconds; an old cookie counts as signed out.
        return if (c.expiresAt < System.currentTimeMillis()) null else c
    }

    // OkHttp asks this "cookie jar" to store cookies the server sends and to supply them on later requests.
    // It keeps just one cookie: the emvryx_session sign-in cookie.
    val cookieJar = object : CookieJar {
        // Called after each reply. Look for our session cookie among the ones the server sent.
        override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
            // (Return quietly if this reply carried no session cookie.)
            val c = cookies.firstOrNull { it.name == COOKIE } ?: return
            // An empty or already-expired cookie is how the server says "you are signed out": forget it. Otherwise save the new one.
            if (c.expiresAt < System.currentTimeMillis() || c.value.isEmpty()) forget()
            else prefs.edit().putString(KEY_COOKIE, c.toString()).apply()
        }

        // Called before each request. Send the cookie only to the address it was issued for (c.matches).
        override fun loadForRequest(url: HttpUrl): List<Cookie> {
            val c = session() ?: return emptyList()
            return if (c.matches(url)) listOf(c) else emptyList()
        }
    }

    // Names used for the saved values: the file name, the keys inside it, and the cookie's name. Constants live here so a typo cannot hide.
    private companion object {
        const val FILE = "emvryx_session"
        const val KEY_SERVER = "server"
        const val KEY_COOKIE = "cookie"
        const val KEY_LIGHT = "light"
        const val KEY_LOCK = "lock"
        const val KEY_VIOLET = "look_violet"
        const val KEY_MODERN = "look_modern"
        const val COOKIE = "emvryx_session"

        /**
         * Opens the encrypted storage. The master key is created in the Android Keystore (a vault the phone's hardware protects);
         * AES-256 is the scrambling method: SIV for the keys, GCM for the values.
         */
        fun open(context: Context): SharedPreferences {
            // Build (or open) the encrypted file.
            fun make(): SharedPreferences {
                val key = MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
                return EncryptedSharedPreferences.create(
                    context, FILE, key,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
                )
            }
            return try {
                make()
            } catch (e: Exception) {
                // If the first try failed: delete the unreadable file and make a fresh, empty one.
                // The keystore key was lost (a restore from backup, a reset lock screen): start again signed out.
                context.deleteSharedPreferences(FILE)
                make()
            }
        }
    }
}
