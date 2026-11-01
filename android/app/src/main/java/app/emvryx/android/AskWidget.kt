package app.emvryx.android

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import app.emvryx.android.local.Launch

/** android_quick_launch: the home-screen widget (res/layout/widget_ask.xml). Each part opens the app for one thing, as the icon's shortcuts do. */
class AskWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        val views = RemoteViews(context.packageName, R.layout.widget_ask).apply {
            setOnClickPendingIntent(R.id.widget_root, open(context, "new", 11))
            setOnClickPendingIntent(R.id.widget_ask, open(context, "new", 11))
            setOnClickPendingIntent(R.id.widget_talk, open(context, "talk", 12))
            setOnClickPendingIntent(R.id.widget_code, open(context, "code", 13))
        }
        ids.forEach { manager.updateAppWidget(it, views) }
    }

    private fun open(ctx: Context, what: String, code: Int): PendingIntent =
        PendingIntent.getActivity(ctx, code, Intent(ctx, MainActivity::class.java).setAction(Intent.ACTION_VIEW).putExtra(Launch.SHORTCUT, what)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
}
