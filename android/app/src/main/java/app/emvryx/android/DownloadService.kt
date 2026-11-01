package app.emvryx.android

import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.emvryx.android.local.AutoOffline
import app.emvryx.android.local.DownloadNote
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Keeps the phone model's (and the picture model's) download going with the app closed, with a progress notification and a Stop button. The
 * download itself runs in PhoneModel / PhoneVision as always; this keeps the app alive while it does, and says how far it is. It ends by itself
 * when nothing is downloading any more, and says whether it is ready or why it stopped. A download that Android ended anyway carries on where
 * it was (a .part file) the next time it is started.
 */
class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var watching: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val app = application as EmvryxApp
        if (intent?.action == STOP) {
            AutoOffline.setAnswer(this, false)                        // Stop is final, as in Settings
            app.phone.cancel(); app.vision.cancel()
            stopSelf()
            return START_NOT_STICKY
        }
        Alerts.channels(this)
        val shown = runCatching {
            ServiceCompat.startForeground(this, ID, build(DownloadNote.Note(true, "Getting Emvryx ready for offline", "Starting…")),
                if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
        }.isSuccess
        if (!shown) { stopSelf(); return START_NOT_STICKY }          // the phone said no (started from the background): the app's own download still runs
        if (watching?.isActive != true) watching = scope.launch { watch(app) }
        return START_NOT_STICKY
    }

    private suspend fun watch(app: EmvryxApp) {
        var seen = false
        var quiet = 0
        while (scope.isActive) {
            val n = DownloadNote.of(app.phone.status, app.vision.status)
            if (n.active) {
                seen = true; quiet = 0
                runCatching { NotificationManagerCompat.from(this).notify(ID, build(n)) }
            } else if (++quiet >= (if (seen) 2 else 20)) break        // not started yet: give it 20 seconds to get going
            delay(1000)
        }
        if (seen) DownloadNote.finished(app.phone.status, app.vision.status)?.let { (title, text) ->
            if (Alerts.allowed(this)) runCatching {
                NotificationManagerCompat.from(this).notify(DONE_ID, NotificationCompat.Builder(this, Alerts.DOWNLOADS).setSmallIcon(R.drawable.ic_notify)
                    .setColor(0xFF8B5CF6.toInt()).setContentTitle(title).setContentText(text).setAutoCancel(true)
                    .setContentIntent(PendingIntent.getActivity(this, DONE_ID, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)).build())
            }
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun build(n: DownloadNote.Note) = NotificationCompat.Builder(this, Alerts.DOWNLOADS).setSmallIcon(R.drawable.ic_notify)
        .setColor(0xFF8B5CF6.toInt()).setContentTitle(n.title).setContentText(n.text).setOngoing(true).setOnlyAlertOnce(true).setSilent(true)
        .setProgress(100, n.percent, n.total <= 0).setCategory(NotificationCompat.CATEGORY_PROGRESS)
        .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
        .setContentIntent(PendingIntent.getActivity(this, ID, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
        .addAction(0, "Stop", PendingIntent.getService(this, ID, Intent(this, DownloadService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE))
        .build()

    override fun onTimeout(startId: Int, fgsType: Int) { stopSelf() }       // Android 15 ends a data-sync service after 6 hours

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        const val ID = 3
        const val DONE_ID = 4
        const val STOP = "app.emvryx.android.STOP_DOWNLOAD"

        /** A download has started: keep the app alive for it and show how far it is */
        fun start(ctx: Context) {
            if (!app.emvryx.android.local.NativeFlags.on(ctx, "android_auto_offline")) return          // part of that switch
            runCatching { ContextCompat.startForegroundService(ctx, Intent(ctx, DownloadService::class.java)) }
        }
    }
}
