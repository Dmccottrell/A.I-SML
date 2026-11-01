// A "foreground service" (a background job with a visible notification so Android keeps it alive) that polls the server for VryxCode session
// states while the app is in the background, and raises a notification when one finishes, needs an answer or fails. Starts from the app only.
package app.emvryx.android

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Keeps an eye on working VryxCode sessions (flag phone_alerts), so they can be left to work while the phone does something else:
 * a quiet "VryxCode is working" notification while any session works, and a notification when one finishes, needs you or stops.
 * It reads the sessions list every few seconds and ends by itself when nothing is working (or after [LONGEST_MS]).
 */
class WatchService : Service() {
    // Coroutines (functions that can pause without blocking) started here belong to this scope and are all cancelled together in onDestroy.
    // SupervisorJob: one failing child does not cancel its siblings. Dispatchers.Main: run on the UI thread (the network call below suspends, not blocks).
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    // The running watch loop (null until started), so a repeat start does not run a second loop
    private var watching: Job? = null

    // Nobody connects to this service directly; it is only started and stopped
    override fun onBind(intent: Intent?): IBinder? = null

    /**
     * Called by Android each time the service is started. Shows the required notification at once (a foreground service must, within seconds),
     * then starts the watch loop. START_NOT_STICKY: if Android kills it, do not restart it by itself.
     */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Alerts.channels(this)
        // DATA_SYNC type needs Android 10 (API 29) or later; older phones pass 0. runCatching: the phone may refuse, which must not crash.
        val shown = runCatching {
            ServiceCompat.startForeground(this, Alerts.ONGOING_ID, Alerts.ongoing(this, emptyList()),
                if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
        }.isSuccess
        if (!shown) {                                   // the phone said no (started from the background): nothing to watch with
            stopSelf()
            return START_NOT_STICKY
        }
        if (watching?.isActive != true) watching = scope.launch { watch() }
        return START_NOT_STICKY
    }

    /**
     * The watch loop (`suspend` = it may pause, here in delay): every 4 s (6 s when the app is visible) it asks the server for all sessions,
     * compares each state with the last look, and notifies on important changes. It stops when no session is live, after 30 failed reads in a row,
     * or after LONGEST_MS, and then removes the notification and ends the service.
     */
    private suspend fun watch() {
        val api = (application as EmvryxApp).api
        val last = HashMap<String, String>()            // session id -> its state at the last look
        val until = SystemClock.elapsedRealtime() + LONGEST_MS
        // fails counts reads that failed one after another
        var fails = 0
        while (scope.isActive && SystemClock.elapsedRealtime() < until) {
            // A failed network call gives null instead of crashing the loop
            val rows = runCatching { api.codeSessions() }.getOrNull()
            if (rows == null) {
                if (++fails >= 30) break                 // the PC or the phone's connection has been gone a good while
            } else {
                fails = 0
                // Compare every session with how it looked last time
                for (s in rows) {
                    val was = last[s.id] ?: continue     // first sight: only changes from now on are news
                    val news = Alerts.sessionNews(s, was) ?: continue
                    // Only notify when the app is not on screen (when it is, the app itself shows the change)
                    if (!Alerts.visible) Alerts.session(this, s, news.first, news.second)
                }
                // Remember this look (id -> state) for the next round
                last.clear()
                rows.forEach { last[it.id] = it.state }
                // Live = still working or waiting on the person; if none are left there is nothing more to watch
                val live = rows.filter { it.live }
                if (live.isEmpty()) break
                // Refresh the "VryxCode is working" notification with the current names (same ID so it replaces the old one)
                if (Alerts.allowed(this)) runCatching { NotificationManagerCompat.from(this).notify(Alerts.ONGOING_ID, Alerts.ongoing(this, live)) }
            }
            // Wait before the next look: a bit slower while the app is on screen, since it already refreshes itself
            delay(if (Alerts.visible) 6000 else 4000)
        }
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    /** Android 15 limits how long this kind of work may run in a day: stop quietly when told */
    override fun onTimeout(startId: Int, fgsType: Int) {
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    /** The service is ending: cancel the watch loop so nothing keeps running */
    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        // The longest one watch may run: 3 hours in milliseconds (3 * 60 min * 60 s * 1000 ms)
        private const val LONGEST_MS = 3 * 60 * 60 * 1000L

        /** Start watching (from the app while it is on screen; the phone does not allow it from the background) */
        fun start(ctx: Context) {
            if (!Alerts.allowed(ctx)) return
            runCatching { ContextCompat.startForegroundService(ctx, Intent(ctx, WatchService::class.java)) }
        }
    }
}
