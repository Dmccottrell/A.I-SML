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
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var watching: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Alerts.channels(this)
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

    private suspend fun watch() {
        val api = (application as EmvryxApp).api
        val last = HashMap<String, String>()            // session id -> its state at the last look
        val until = SystemClock.elapsedRealtime() + LONGEST_MS
        var fails = 0
        while (scope.isActive && SystemClock.elapsedRealtime() < until) {
            val rows = runCatching { api.codeSessions() }.getOrNull()
            if (rows == null) {
                if (++fails >= 30) break                 // the PC or the phone's connection has been gone a good while
            } else {
                fails = 0
                for (s in rows) {
                    val was = last[s.id] ?: continue     // first sight: only changes from now on are news
                    val news = Alerts.sessionNews(s, was) ?: continue
                    if (!Alerts.visible) Alerts.session(this, s, news.first, news.second)
                }
                last.clear()
                rows.forEach { last[it.id] = it.state }
                val live = rows.filter { it.live }
                if (live.isEmpty()) break
                if (Alerts.allowed(this)) runCatching { NotificationManagerCompat.from(this).notify(Alerts.ONGOING_ID, Alerts.ongoing(this, live)) }
            }
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

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val LONGEST_MS = 3 * 60 * 60 * 1000L

        /** Start watching (from the app while it is on screen; the phone does not allow it from the background) */
        fun start(ctx: Context) {
            if (!Alerts.allowed(ctx)) return
            runCatching { ContextCompat.startForegroundService(ctx, Intent(ctx, WatchService::class.java)) }
        }
    }
}
