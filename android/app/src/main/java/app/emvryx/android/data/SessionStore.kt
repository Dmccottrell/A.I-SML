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
 */
class SessionStore(context: Context) {
    private val prefs: SharedPreferences = open(context)

    var serverUrl: String?
        get() = prefs.getString(KEY_SERVER, null)
        set(value) = prefs.edit().putString(KEY_SERVER, value).apply()

    val signedIn get() = session() != null

    fun forget() = prefs.edit().remove(KEY_COOKIE).apply()

    private fun session(): Cookie? {
        val base = serverUrl?.toHttpUrlOrNull() ?: return null
        val raw = prefs.getString(KEY_COOKIE, null) ?: return null
        val c = Cookie.parse(base, raw) ?: return null
        return if (c.expiresAt < System.currentTimeMillis()) null else c
    }

    val cookieJar = object : CookieJar {
        override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
            val c = cookies.firstOrNull { it.name == COOKIE } ?: return
            if (c.expiresAt < System.currentTimeMillis() || c.value.isEmpty()) forget()
            else prefs.edit().putString(KEY_COOKIE, c.toString()).apply()
        }

        override fun loadForRequest(url: HttpUrl): List<Cookie> {
            val c = session() ?: return emptyList()
            return if (c.matches(url)) listOf(c) else emptyList()
        }
    }

    private companion object {
        const val FILE = "emvryx_session"
        const val KEY_SERVER = "server"
        const val KEY_COOKIE = "cookie"
        const val COOKIE = "emvryx_session"

        fun open(context: Context): SharedPreferences {
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
                // The keystore key was lost (a restore from backup, a reset lock screen): start again signed out.
                context.deleteSharedPreferences(FILE)
                make()
            }
        }
    }
}
