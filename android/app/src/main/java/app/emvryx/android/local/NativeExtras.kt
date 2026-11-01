package app.emvryx.android.local

import android.content.Context

/**
 * The switches of the phone's own extras, remembered on the phone: some are needed before the PC has answered (the app opened from selected text
 * or the assistant button) or with the app closed (a reply typed in a notification, the sync in the background).
 */
object NativeFlags {
    val IDS = setOf("android_text_menu", "android_quick_launch", "android_reply_inline", "android_camera_scan", "android_background_sync", "android_offline_talk", "android_assistant")

    /** The ones that are on, from the PC's list (state.features) */
    fun pick(features: Map<String, Boolean>): Set<String> = IDS.filter { features[it] == true }.toSet()

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("emvryx_native_flags", Context.MODE_PRIVATE)

    fun remember(ctx: Context, on: Set<String>) = prefs(ctx).edit().putStringSet("on", on).apply()

    fun on(ctx: Context): Set<String> = prefs(ctx).getStringSet("on", emptySet()).orEmpty()

    fun on(ctx: Context, id: String) = id in on(ctx)
}

/** What the app was opened for from outside it: selected text (android_text_menu), the assistant button, the icon's shortcuts or the widget
 *  (android_quick_launch). [None]: it opens as always. */
sealed interface Launch {
    data class Text(val text: String) : Launch
    data object Talk : Launch
    data object NewChat : Launch
    data object Code : Launch
    data object Local : Launch
    data object None : Launch

    companion object {
        const val SHORTCUT = "emvryx.shortcut"           // the extra the shortcuts and the widget set: new, talk, code, local
        const val MAX_TEXT = 8000

        fun from(action: String?, shortcut: String?, selected: CharSequence?, on: Set<String>): Launch = when {
            action == "android.intent.action.PROCESS_TEXT" ->
                if ("android_text_menu" in on) selected?.toString()?.trim()?.take(MAX_TEXT)?.takeIf { it.isNotEmpty() }?.let { Text(it) } ?: None else None
            action == "android.intent.action.ASSIST" || action == "android.intent.action.VOICE_COMMAND" ->
                if ("android_quick_launch" in on) Talk else None
            shortcut != null && "android_quick_launch" in on -> when (shortcut) {
                "new" -> NewChat
                "talk" -> Talk
                "code" -> Code
                "local" -> Local
                else -> None
            }
            else -> None
        }
    }
}

/** The model and effort last used in a chat, for the answers given outside the app (the assistant bar, a reply in a notification) */
object LastChoice {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("emvryx_last_choice", Context.MODE_PRIVATE)

    fun remember(ctx: Context, model: String, effort: String) {
        if (model.isNotBlank()) prefs(ctx).edit().putString("model", model).putString("effort", effort).apply()
    }

    fun model(ctx: Context): String = prefs(ctx).getString("model", "").orEmpty()

    fun effort(ctx: Context): String = prefs(ctx).getString("effort", "balanced").orEmpty().ifEmpty { "balanced" }
}
