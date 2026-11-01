package app.emvryx.android.assist

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.RemoteInput
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import app.emvryx.android.Alerts
import app.emvryx.android.EmvryxApp
import app.emvryx.android.R
import app.emvryx.android.local.NativeFlags
import java.util.concurrent.TimeUnit

/**
 * android_background_sync: chats and VryxCode drafts written on the phone with the PC off go to it by themselves, even with the app closed
 * (about every 15 minutes, only with a connection; the PC drops a copy it already has, so a send twice is harmless).
 */
class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        if (!NativeFlags.on(applicationContext, "android_background_sync")) return Result.success()
        val phone = (applicationContext as EmvryxApp).phone
        if (!phone.allowed) return Result.success()
        runCatching { phone.syncUp(); phone.syncDrafts() }
        return Result.success()
    }

    companion object {
        private const val NAME = "emvryx-sync"

        /** Start (or stop) the background sync to match the switch */
        fun schedule(ctx: Context, on: Boolean) {
            val wm = runCatching { WorkManager.getInstance(ctx) }.getOrNull() ?: return
            if (!on) { wm.cancelUniqueWork(NAME); return }
            val job = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build()
            wm.enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.KEEP, job)
        }
    }
}

/**
 * android_reply_inline: the next message typed in a "your answer is ready" notification, like replying to a text. It is sent in that chat and the
 * answer comes back in the same notification.
 */
class ReplyReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val chat = intent.getLongExtra(Alerts.EXTRA_CHAT, 0L)
        val text = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(KEY)?.toString()?.trim().orEmpty()
        if (chat == 0L || text.isEmpty() || !NativeFlags.on(ctx, "android_reply_inline")) return
        sending(ctx, chat, text)
        WorkManager.getInstance(ctx).enqueue(OneTimeWorkRequestBuilder<ReplyWorker>()
            .setInputData(workDataOf("chat" to chat, "text" to text)).build())
    }

    companion object {
        const val KEY = "emvryx.reply"

        /** The notification while the reply is on its way (Android needs it updated, or the box keeps spinning) */
        fun sending(ctx: Context, chat: Long, text: String) {
            if (!Alerts.allowed(ctx)) return
            val n = NotificationCompat.Builder(ctx, Alerts.CHAT).setSmallIcon(R.drawable.ic_notify).setColor(0xFFF59E0B.toInt())
                .setContentTitle("Sent: " + text.take(80)).setContentText("Emvryx is answering…").setProgress(0, 0, true)
                .setOnlyAlertOnce(true).setSilent(true).setContentIntent(Alerts.open(ctx, Alerts.EXTRA_CHAT, chat.toString(), chat.toInt()))
                .build()
            runCatching { NotificationManagerCompat.from(ctx).notify("chat", chat.toInt(), n) }
        }
    }
}

class ReplyWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val chat = inputData.getLong("chat", 0L)
        val text = inputData.getString("text").orEmpty()
        if (chat == 0L || text.isEmpty()) return Result.success()
        val a = Asker.ask(applicationContext, text, chat, null) {}
        Alerts.chat(applicationContext, chat, if (a.text != null) "Emvryx answered" else "Not sent",
            a.text ?: (a.problem ?: "It could not be sent.") + " Open the chat to try again.")
        return Result.success()
    }
}
