// The home-screen widget (the little box you can put on the phone's home screen). It has an "Ask Emvryx" box and Talk / VryxCode buttons.
// Tapping a part simply opens the app and tells it WHICH thing to open; MainActivity reads that and shows the right screen.
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
    // Android calls this when the widget is first placed and whenever it needs redrawing. [ids] are all the copies of the widget on the screen.
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        // RemoteViews = a description of the widget's layout that Android draws for us (a widget lives in the launcher, not in our app)
        val views = RemoteViews(context.packageName, R.layout.widget_ask).apply {
            // Tapping the background or the "Ask Emvryx" box starts a new chat ("new"). The number is a request code: it must differ per target.
            setOnClickPendingIntent(R.id.widget_root, open(context, "new", 11))
            setOnClickPendingIntent(R.id.widget_ask, open(context, "new", 11))
            // The Talk button opens Talk
            setOnClickPendingIntent(R.id.widget_talk, open(context, "talk", 12))
            // The VryxCode button opens VryxCode
            setOnClickPendingIntent(R.id.widget_code, open(context, "code", 13))
        }
        // Give the finished layout to every copy of the widget
        ids.forEach { manager.updateAppWidget(it, views) }
    }

    // Builds the "tap here to open the app for [what]" action. A PendingIntent is a permission slip we hand to the launcher
    // so that it can start our app later, when the person taps.
    private fun open(ctx: Context, what: String, code: Int): PendingIntent =
        PendingIntent.getActivity(ctx, code, Intent(ctx, MainActivity::class.java).setAction(Intent.ACTION_VIEW).putExtra(Launch.SHORTCUT, what)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
}
