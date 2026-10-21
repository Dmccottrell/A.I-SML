package app.emvryx.android

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import app.emvryx.android.data.CodeSessionRow

/**
 * The phone's own notifications (flag phone_alerts): a VryxCode session finished, needs you or stopped, the live "working on it" one while it runs,
 * and a chat answer ready while the app is away. Tapping one opens that session or chat (MainActivity reads [EXTRA_SESSION] / [EXTRA_CHAT]).
 */
object Alerts {
    const val CODE = "vryxcode"            // channels, each switchable in the phone's settings
    const val WORKING = "vryxcode_working"
    const val CHAT = "chat"
    const val EXTRA_SESSION = "emvryx.session"
    const val EXTRA_CHAT = "emvryx.chat"
    const val ONGOING_ID = 1

    /** True while the app is on screen (MainActivity onStart/onStop): then the app itself shows what happened, no notification */
    @Volatile var visible = false

    fun channels(ctx: Context) {
        val m = ctx.getSystemService(NotificationManager::class.java) ?: return
        m.createNotificationChannels(listOf(
            NotificationChannel(CODE, "VryxCode", NotificationManager.IMPORTANCE_HIGH).apply { description = "A session finished, needs you, or stopped" },
            NotificationChannel(WORKING, "VryxCode working", NotificationManager.IMPORTANCE_LOW).apply { description = "While a session works in the background"; setShowBadge(false) },
            NotificationChannel(CHAT, "Chat answers", NotificationManager.IMPORTANCE_DEFAULT).apply { description = "An answer is ready while the app is in the background" },
        ))
    }

    /** May the app show notifications? (Android 13 and later ask the person first) */
    fun allowed(ctx: Context): Boolean =
        (Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) &&
            NotificationManagerCompat.from(ctx).areNotificationsEnabled()

    fun open(ctx: Context, key: String, value: String, code: Int): PendingIntent =
        PendingIntent.getActivity(ctx, code, Intent(ctx, MainActivity::class.java).putExtra(key, value).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    /** A session changed from [was] to its state now: what to say, or null for nothing (stopped by the person, or still going) */
    fun sessionNews(s: CodeSessionRow, was: String): Pair<String, String>? {
        if (was == s.state) return null
        val busy = setOf("starting", "working", "queued")
        val title = s.title.ifBlank { "Your session" }
        val lines = listOfNotNull(if (s.added > 0 || s.removed > 0) "+${s.added} −${s.removed}" else null,
                                  if (s.files > 0) "${s.files} " + (if (s.files == 1) "file" else "files") + " changed" else null).joinToString(" · ")
        return when {
            s.state == "asking" -> "Needs you: $title" to "VryxCode is waiting for your answer before it carries on."
            s.state == "done" && (was in busy || was == "asking") -> "Finished: $title" to listOf(lines, s.snippet.take(160)).filter { it.isNotBlank() }.joinToString(" · ").ifEmpty { "Ready to look at." }
            s.state in setOf("failed", "interrupted") && (was in busy || was == "asking") -> "Stopped: $title" to s.snippet.take(160).ifBlank { "It could not finish. Open it to see why or to try again." }
            else -> null
        }
    }

    fun session(ctx: Context, s: CodeSessionRow, title: String, text: String) {
        if (!allowed(ctx)) return
        val n = NotificationCompat.Builder(ctx, CODE).setSmallIcon(R.drawable.ic_notify).setColor(0xFF8B5CF6.toInt())
            .setContentTitle(title).setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text)).setSubText(s.project)
            .setCategory(NotificationCompat.CATEGORY_STATUS).setAutoCancel(true).setContentIntent(open(ctx, EXTRA_SESSION, s.id, s.id.hashCode()))
            .build()
        runCatching { NotificationManagerCompat.from(ctx).notify("vx", s.id.hashCode(), n) }
    }

    fun chat(ctx: Context, chatId: Long, title: String, text: String) {
        if (!allowed(ctx)) return
        val body = text.lineSequence().map { it.trim().trimStart('#', '*', '-', '>', ' ') }.firstOrNull { it.isNotBlank() }.orEmpty().take(200)
        val n = NotificationCompat.Builder(ctx, CHAT).setSmallIcon(R.drawable.ic_notify).setColor(0xFFF59E0B.toInt())
            .setContentTitle(title.ifBlank { "Your answer is ready" }).setContentText(body).setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setCategory(NotificationCompat.CATEGORY_MESSAGE).setAutoCancel(true).setContentIntent(open(ctx, EXTRA_CHAT, chatId.toString(), chatId.toInt()))
            .build()
        runCatching { NotificationManagerCompat.from(ctx).notify("chat", chatId.toInt(), n) }
    }

    /** The live one while sessions work: their names and a moving bar */
    fun ongoing(ctx: Context, live: List<CodeSessionRow>): android.app.Notification {
        val text = if (live.isEmpty()) "Checking on your sessions" else live.joinToString(" · ") { it.title.ifBlank { "Session" } }
        val title = when {
            live.any { it.state == "asking" } -> "VryxCode needs you"
            live.size > 1 -> "VryxCode is working on ${live.size} sessions"
            else -> "VryxCode is working"
        }
        val tap = live.firstOrNull()?.let { open(ctx, EXTRA_SESSION, it.id, ONGOING_ID) }
        return NotificationCompat.Builder(ctx, WORKING).setSmallIcon(R.drawable.ic_notify).setColor(0xFF8B5CF6.toInt())
            .setContentTitle(title).setContentText(text).setOngoing(true).setOnlyAlertOnce(true).setSilent(true)
            .setProgress(0, 0, live.any { it.state != "asking" }).setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .apply { if (tap != null) setContentIntent(tap) }
            .build()
    }
}
