// "Get offline ready by itself" (switch android_auto_offline): the decisions about WHEN and WHAT to download.
// The real downloading is done by PhoneModel; this file only answers questions like "is there room?" and "should we ask the person first?".
// It is kept as small, separate functions so they can be unit-tested without a phone (see AutoOfflineTest).
package app.emvryx.android.local

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

/**
 * android_auto_offline: a phone with the room gets what it needs for the PC-off answers by itself. On Wi-Fi or mobile data (any working connection), only
 * a model the phone has the memory and free space for (with [SPARE] to spare), the smallest that fits unless a model was picked
 * in Settings. The picture model is not fetched on its own: it is big and few people need it. The first time the person is asked once
 * (admins are not); "No thanks", Stop and Remove are remembered, so it never starts again against their wish.
 */
object AutoOffline {
    // Keep 2 GB free after the download so the phone does not run out of space. "2L shl 30" means 2 x 2^30 bytes = 2 GB.
    const val SPARE = 2L shl 30

    // The three things the app can decide to do next:
    //   Nothing = do not download;  Ask = show the "Get Emvryx ready for offline?" banner;  Go = start downloading now
    enum class Step { Nothing, Ask, Go }

    /** The model to fetch: the one picked in Settings if it fits, else the smallest that fits; null when none does */
    fun pick(choices: List<PhoneChoice>, wanted: String?, free: Long, ramOk: (Double) -> Boolean): PhoneChoice? {
        // Keep only the models this phone can really handle: enough memory (ramOk) and enough free space plus the spare 2 GB
        val fits = choices.filter { ramOk(it.minRamGb) && it.size + SPARE <= free }
        // Prefer the model the person chose in Settings; otherwise the smallest one that fits (null if the list is empty)
        return fits.firstOrNull { it.id == wanted } ?: fits.minByOrNull { it.size }
    }

    /** [needs]: no model on the phone yet (or the last try failed). [answer]: what the person said before ("yes", "no" or nothing) */
    fun step(on: Boolean, connected: Boolean, needs: Boolean, answer: String?, admin: Boolean): Step = when {
        // The switch is off, there is no connection, nothing is needed, or the person already said no: do nothing
        !on || !connected || !needs || answer == "no" -> Step.Nothing
        // Admins (the owner's own accounts) and anyone who said yes before: start without asking again
        admin || answer == "yes" -> Step.Go
        // Everyone else is asked once
        else -> Step.Ask
    }

    // SharedPreferences is Android's tiny key-value file for settings. This one remembers only the person's answer.
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("emvryx_auto_offline", Context.MODE_PRIVATE)

    // What the person answered before: "yes", "no", or null if they were never asked
    fun answer(ctx: Context): String? = prefs(ctx).getString("answer", null)

    // Remember the answer. Stop, Remove and "No thanks" all save "no" so it never starts again by itself.
    fun setAnswer(ctx: Context, yes: Boolean) = prefs(ctx).edit().putString("answer", if (yes) "yes" else "no").apply()

    /** Any connection with the internet working: Wi-Fi or mobile data */
    fun connected(ctx: Context): Boolean = runCatching {
        // Ask Android's connectivity service about the connection that is being used right now
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        val c = cm.getNetworkCapabilities(cm.activeNetwork)
        // True only if there is a connection and it can reach the internet. runCatching below turns any error into "not connected".
        c != null && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }.getOrDefault(false)
}
