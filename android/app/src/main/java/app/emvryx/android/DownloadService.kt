// A "foreground service": a background job with a visible notification, which stops Android from killing the app while a big file downloads.
// It only WATCHES the download (the offline model downloads in PhoneModel / PhoneVision) and keeps the progress notification up to date.
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
 * A Service is an Android component that runs without a screen. It is declared in AndroidManifest.xml.
 */
class DownloadService : Service() {
    // A coroutine is a function that can pause and resume without blocking a thread. The scope owns the ones started here, so they can all be
    // cancelled together. SupervisorJob: one failing child does not cancel the others. Dispatchers.Main: run on the UI thread.
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    // The running watch loop (null before it starts), kept so a second start does not launch a second loop
    private var watching: Job? = null

    // Nothing can bind to this service (connect to it directly); it is only started and stopped
    override fun onBind(intent: Intent?): IBinder? = null

    /**
     * Android calls this each time something starts the service. Two cases: the Stop button in the notification (action STOP) cancels the
     * downloads and ends the service; any other start shows the notification and starts the watching loop.
     * The return value START_NOT_STICKY means: if Android kills the service, do not restart it by itself.
     */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val app = application as EmvryxApp
        if (intent?.action == STOP) {
            AutoOffline.setAnswer(this, false)                        // Stop is final, as in Settings
            app.phone.cancel(); app.vision.cancel()
            stopSelf()
            return START_NOT_STICKY
        }
        // Make sure the notification channels exist before showing anything
        Alerts.channels(this)
        // A foreground service must show its notification within seconds, so start it now. The type DATA_SYNC (moving data) exists from Android 10
        // (API 29); older phones get 0 (no type). Android may refuse (for example when started while the app is in the background), hence runCatching.
        val shown = runCatching {
            ServiceCompat.startForeground(this, ID, build(DownloadNote.Note(true, "Getting Emvryx ready for offline", "Starting…")),
                if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
        }.isSuccess
        if (!shown) { stopSelf(); return START_NOT_STICKY }          // the phone said no (started from the background): the app's own download still runs
        // Start the watch loop only if one is not already running
        if (watching?.isActive != true) watching = scope.launch { watch(app) }
        return START_NOT_STICKY
    }

    /**
     * The loop (a `suspend` function: it may pause, here in delay) that checks the two downloads once a second and refreshes the notification.
     * It stops when nothing has been downloading for 2 checks in a row (or 20 checks if none ever started), then posts a "ready / stopped" notice.
     */
    private suspend fun watch(app: EmvryxApp) {
        // seen: a download was active at least once. quiet: how many checks in a row found nothing happening.
        var seen = false
        var quiet = 0
        while (scope.isActive) {
            // Combine the status of the phone model and the picture model into one notification text
            val n = DownloadNote.of(app.phone.status, app.vision.status)
            if (n.active) {
                seen = true; quiet = 0
                runCatching { NotificationManagerCompat.from(this).notify(ID, build(n)) }
            } else if (++quiet >= (if (seen) 2 else 20)) break        // not started yet: give it 20 seconds to get going
            delay(1000)
        }
        // Something was downloading and has now ended: show a final notice (title, text) saying it is ready or why it stopped. Tapping opens the app.
        if (seen) DownloadNote.finished(app.phone.status, app.vision.status)?.let { (title, text) ->
            if (Alerts.allowed(this)) runCatching {
                NotificationManagerCompat.from(this).notify(DONE_ID, NotificationCompat.Builder(this, Alerts.DOWNLOADS).setSmallIcon(R.drawable.ic_notify)
                    .setColor(0xFF8B5CF6.toInt()).setContentTitle(title).setContentText(text).setAutoCancel(true)
                    .setContentIntent(PendingIntent.getActivity(this, DONE_ID, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)).build())
            }
        }
        // Take down the progress notification and end the service
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    /**
     * Builds the progress notification for note [n] (title, text, percent). It cannot be swiped away (ongoing), makes no sound, and has a Stop
     * button that sends STOP back to this service. A bar with no known total (total <= 0) is shown as a moving "unknown" bar.
     */
    private fun build(n: DownloadNote.Note) = NotificationCompat.Builder(this, Alerts.DOWNLOADS).setSmallIcon(R.drawable.ic_notify)
        .setColor(0xFF8B5CF6.toInt()).setContentTitle(n.title).setContentText(n.text).setOngoing(true).setOnlyAlertOnce(true).setSilent(true)
        .setProgress(100, n.percent, n.total <= 0).setCategory(NotificationCompat.CATEGORY_PROGRESS)
        .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
        .setContentIntent(PendingIntent.getActivity(this, ID, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
        .addAction(0, "Stop", PendingIntent.getService(this, ID, Intent(this, DownloadService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE))
        .build()

    // Android 15 limits how long a data-sync service may run; when time is up it calls this, and we must stop
    override fun onTimeout(startId: Int, fgsType: Int) { stopSelf() }       // Android 15 ends a data-sync service after 6 hours

    /** The service is ending: cancel the watch loop so nothing keeps running */
    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    // Shared constants and the start helper (a companion object is Kotlin's "static")
    companion object {
        // Notification numbers: ID is the progress one, DONE_ID the final one; STOP is the label of the Stop button's action
        const val ID = 3
        const val DONE_ID = 4
        const val STOP = "app.emvryx.android.STOP_DOWNLOAD"

        /**
         * A download has started: keep the app alive for it and show how far it is.
         * Does nothing unless the android_auto_offline switch (a feature flag) is on; errors are swallowed so a refusal never crashes the app.
         */
        fun start(ctx: Context) {
            if (!app.emvryx.android.local.NativeFlags.on(ctx, "android_auto_offline")) return          // part of that switch
            runCatching { ContextCompat.startForegroundService(ctx, Intent(ctx, DownloadService::class.java)) }
        }
    }
}
