// Work that runs in the background with the app closed, scheduled through WorkManager (Android's library for tasks that must happen later,
// even after a restart): the periodic sync of phone-written chats to the PC, and sending a reply typed inside a notification.
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
// A CoroutineWorker is a job WorkManager runs for us; doWork may pause (suspend) while waiting on the network.
class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    /** One sync round. Returns success in every case (a failure is not retried; the next 15-minute round tries again) */
    override suspend fun doWork(): Result {
        // Do nothing when the feature switch is off
        if (!NativeFlags.on(applicationContext, "android_background_sync")) return Result.success()
        val phone = (applicationContext as EmvryxApp).phone
        // Also nothing when the offline phone chats are not allowed for this account
        if (!phone.allowed) return Result.success()
        // Upload chats and drafts written offline; any error is swallowed because it will be tried again later
        runCatching { phone.syncUp(); phone.syncDrafts() }
        return Result.success()
    }

    companion object {
        // The unique name of the scheduled job, so there is never more than one
        private const val NAME = "emvryx-sync"

        /** Start (or stop) the background sync to match the switch */
        fun schedule(ctx: Context, on: Boolean) {
            // WorkManager can fail to start in odd situations; then simply do nothing
            val wm = runCatching { WorkManager.getInstance(ctx) }.getOrNull() ?: return
            if (!on) { wm.cancelUniqueWork(NAME); return }
            // Repeat about every 15 minutes (Android's minimum for repeating work), only while the phone has a connection.
            // KEEP: if the job already exists, leave it alone instead of restarting its timer.
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
    /**
     * Android calls this when the person sends a reply from the notification. It reads the chat id and the typed words, shows "Sent..." in the
     * notification right away, and hands the real sending to ReplyWorker (a receiver must finish in a few seconds).
     */
    override fun onReceive(ctx: Context, intent: Intent) {
        // chat id sent along with the notification button (0 = missing)
        val chat = intent.getLongExtra(Alerts.EXTRA_CHAT, 0L)
        // The typed words come back inside a RemoteInput result under KEY; trim spaces
        val text = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(KEY)?.toString()?.trim().orEmpty()
        // Ignore an empty or unknown reply, or when the feature is switched off
        if (chat == 0L || text.isEmpty() || !NativeFlags.on(ctx, "android_reply_inline")) return
        sending(ctx, chat, text)
        // Queue a one-time job with the chat id and text as its input data
        WorkManager.getInstance(ctx).enqueue(OneTimeWorkRequestBuilder<ReplyWorker>()
            .setInputData(workDataOf("chat" to chat, "text" to text)).build())
    }

    companion object {
        // The name under which the typed text travels inside the notification's reply box (must match Alerts.reply)
        const val KEY = "emvryx.reply"

        /** The notification while the reply is on its way (Android needs it updated, or the box keeps spinning) */
        fun sending(ctx: Context, chat: Long, text: String) {
            if (!Alerts.allowed(ctx)) return
            // Same chat notification id as the original (chat.toInt()), so this replaces the answer-ready notice; an indefinite progress bar shows it is working.
            // Silent and "only alert once" so it does not buzz again.
            val n = NotificationCompat.Builder(ctx, Alerts.CHAT).setSmallIcon(R.drawable.ic_notify).setColor(0xFFF59E0B.toInt())
                .setContentTitle("Sent: " + text.take(80)).setContentText("Emvryx is answering…").setProgress(0, 0, true)
                .setOnlyAlertOnce(true).setSilent(true).setContentIntent(Alerts.open(ctx, Alerts.EXTRA_CHAT, chat.toString(), chat.toInt()))
                .build()
            runCatching { NotificationManagerCompat.from(ctx).notify("chat", chat.toInt(), n) }
        }
    }
}

/** Sends a notification reply to the server as a follow-up in its chat, then posts the answer (or the problem) as a new chat notification */
class ReplyWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        // Read back the values ReplyReceiver queued
        val chat = inputData.getLong("chat", 0L)
        val text = inputData.getString("text").orEmpty()
        if (chat == 0L || text.isEmpty()) return Result.success()
        // Ask in that chat with no picture; the empty {} ignores streaming updates because only the final answer is shown
        val a = Asker.ask(applicationContext, text, chat, null) {}
        // Show the answer, or "Not sent" with the reason
        Alerts.chat(applicationContext, chat, if (a.text != null) "Emvryx answered" else "Not sent",
            a.text ?: (a.problem ?: "It could not be sent.") + " Open the chat to try again.")
        return Result.success()
    }
}
