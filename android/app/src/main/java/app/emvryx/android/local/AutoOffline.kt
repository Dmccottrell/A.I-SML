package app.emvryx.android.local

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

/**
 * android_auto_offline: a phone with the room gets what it needs for the PC-off answers by itself. On Wi-Fi or mobile data (any working connection), only a model the phone has the memory and the free space for (with [SPARE] to spare), the smallest that fits unless a model was picked
 * in Settings. The picture model is not fetched on its own: it is big and few people need it. The first time the person is asked once
 * (admins are not); "No thanks", Stop and Remove are remembered, so it never starts again against their wish.
 */
object AutoOffline {
    const val SPARE = 2L shl 30                       // keep this much free after the download

    enum class Step { Nothing, Ask, Go }

    /** The model to fetch: the one picked in Settings if it fits, else the smallest that fits; null when none does */
    fun pick(choices: List<PhoneChoice>, wanted: String?, free: Long, ramOk: (Double) -> Boolean): PhoneChoice? {
        val fits = choices.filter { ramOk(it.minRamGb) && it.size + SPARE <= free }
        return fits.firstOrNull { it.id == wanted } ?: fits.minByOrNull { it.size }
    }

    /** [needs]: no model on the phone yet (or the last try failed). [answer]: what the person said before ("yes", "no" or nothing) */
    fun step(on: Boolean, connected: Boolean, needs: Boolean, answer: String?, admin: Boolean): Step = when {
        !on || !connected || !needs || answer == "no" -> Step.Nothing
        admin || answer == "yes" -> Step.Go
        else -> Step.Ask
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("emvryx_auto_offline", Context.MODE_PRIVATE)

    fun answer(ctx: Context): String? = prefs(ctx).getString("answer", null)

    fun setAnswer(ctx: Context, yes: Boolean) = prefs(ctx).edit().putString("answer", if (yes) "yes" else "no").apply()

    /** Any connection with the internet working: Wi-Fi or mobile data */
    fun connected(ctx: Context): Boolean = runCatching {
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        val c = cm.getNetworkCapabilities(cm.activeNetwork)
        c != null && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }.getOrDefault(false)
}
